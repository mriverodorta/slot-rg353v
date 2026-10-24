//! Debounced content discovery. Work runs off the render thread, only while no game is active.
use std::collections::{BTreeMap, BTreeSet};
use std::hash::{Hash, Hasher};
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
use std::time::{Duration, Instant};

use slot_store::{Cart, Platform};

#[cfg(all(feature = "rg353v", target_os = "linux"))]
#[path = "sd_hotplug.rs"]
mod sd_hotplug;

const INTERVAL: Duration = Duration::from_secs(2);
const IMAGE_LIMIT: u64 = 16 << 20;
type Manifest = BTreeMap<PathBuf, Mark>;

#[derive(Clone, Debug, PartialEq, Eq)]
struct Mark {
    len: u64,
    modified: Option<std::time::SystemTime>,
    changed: Option<(i64, i64, u64)>,
    // Hash image bytes as well: Finder can preserve both filename and mtime on replacement.
    image_hash: Option<u64>,
}

#[derive(Default)]
pub struct Catalog {
    observed: Option<Manifest>,
    applied: Option<Manifest>,
    valid: Manifest,
    carts: Vec<Cart>,
    issues: BTreeMap<PathBuf, String>,
}

pub struct Refresh {
    pub carts: Vec<Cart>,
    pub wallpapers: Vec<String>,
    pub changed_labels: BTreeSet<PathBuf>,
    pub changed_wallpapers: BTreeSet<PathBuf>,
    pub issues: Vec<String>,
}

impl Catalog {
    /// Requires two identical observations; incomplete/invalid replacements keep last good art.
    pub fn poll(&mut self, root: &Path) -> io::Result<Option<Refresh>> {
        self.poll_inner(root, true)
    }
    fn poll_inner(&mut self, root: &Path, local: bool) -> io::Result<Option<Refresh>> {
        let manifest = match manifest(root, self.observed.as_ref(), local) {
            Ok(manifest) => manifest,
            Err(error) => {
                self.applied = None;
                return Err(error);
            }
        };
        if self.observed.as_ref() != Some(&manifest) {
            self.observed = Some(manifest);
            return Ok(None);
        }
        if self.applied.as_ref() == Some(&manifest) {
            return Ok(None);
        }
        let mut issues = self.issues.clone();
        issues.retain(|p, _| manifest.contains_key(p));
        let mut changed_labels = BTreeSet::new();
        let mut changed_wallpapers = BTreeSet::new();
        let mut valid = self.valid.clone();
        valid.retain(|p, _| manifest.contains_key(p));
        for (path, mark) in &manifest {
            if self.valid.get(path) == Some(mark) {
                continue;
            }
            let full = root.join(path);
            let kind = path
                .components()
                .next()
                .and_then(|p| p.as_os_str().to_str());
            let png = path
                .extension()
                .is_some_and(|s| s.eq_ignore_ascii_case("png"));
            let problem = if matches!(kind, Some("Wallpapers" | "Labels")) {
                if !png {
                    Some("Use PNG artwork")
                } else if mark.len > IMAGE_LIMIT || !valid_png(&full) {
                    Some("Invalid PNG; retry copy")
                } else {
                    if kind == Some("Labels") {
                        changed_labels.insert(full.clone());
                    } else {
                        changed_wallpapers.insert(full.clone());
                    }
                    None
                }
            } else if kind == Some("Games") {
                let platform = Platform::ALL.into_iter().find(|p| {
                    path.starts_with(Path::new("Games").join(p.dir_name())) && p.accepts(path)
                });
                match platform {
                    None => Some("Unsupported game file"),
                    Some(platform) if !rom_valid(&full, platform, mark.len) => {
                        Some("Incomplete/invalid ROM")
                    }
                    _ => None,
                }
            } else {
                None
            };
            if let Some(problem) = problem {
                if kind == Some("Games") {
                    valid.remove(path);
                }
                issues.insert(path.clone(), format!("{}: {problem}", path.display()));
            } else {
                valid.insert(path.clone(), mark.clone());
                issues.remove(path);
            }
        }
        let mut carts = slot_store::scan_library(root).map_err(io::Error::other)?;
        carts.retain(|c| {
            c.rom
                .strip_prefix(root)
                .is_ok_and(|p| valid.contains_key(p))
        });
        for cart in &mut carts {
            if cart.stem.ends_with([' ', '.']) {
                if let Ok(path) = cart.rom.strip_prefix(root) {
                    issues.insert(
                        path.to_path_buf(),
                        format!(
                            "{}: Mac-incompatible trailing space/dot; use slot-fix-mac-names",
                            path.display()
                        ),
                    );
                }
            }
            // An invalid new label falls back to the generated label. A bad replacement retains
            // the valid cache; label_cache never overwrites good pixels with a failed decode.
            if cart
                .label
                .as_ref()
                .is_some_and(|p| !p.strip_prefix(root).is_ok_and(|p| valid.contains_key(p)))
            {
                cart.label = None;
            }
            if let Some(old) = self.carts.iter().find(|c| c.rom == cart.rom) {
                cart.title.clone_from(&old.title);
                cart.code.clone_from(&old.code);
            }
        }
        let wallpapers = valid
            .keys()
            .filter_map(|p| {
                (p.parent() == Some(Path::new("Wallpapers")))
                    .then(|| p.file_name()?.to_str().map(str::to_owned))
                    .flatten()
            })
            .collect();
        // Do not publish a catalog assembled across a changing upload.
        if manifest != self::manifest(root, Some(&manifest), local)? {
            self.observed = None;
            return Ok(None);
        }
        let report = issues
            .values()
            .take(100)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n");
        if local {
            let _ = std::fs::create_dir_all(root.join("Diagnostics"));
            let _ =
                slot_store::atomic_write(&root.join("Diagnostics/content.log"), report.as_bytes());
        }
        self.issues = issues.clone();
        let issues = issues.into_values().collect();
        self.valid = valid;
        self.applied = Some(manifest);
        self.carts = carts.clone();
        Ok(Some(Refresh {
            carts,
            wallpapers,
            changed_labels,
            changed_wallpapers,
            issues,
        }))
    }
}

fn manifest(root: &Path, prior: Option<&Manifest>, local: bool) -> io::Result<Manifest> {
    // A disconnected/missing content mount must never empty the shelf.
    if !root.join("Games").is_dir() || (local && !root.join("Config").is_dir()) {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            "Content unavailable; check SD card",
        ));
    }
    let mut result = Manifest::new();
    let dirs = std::iter::once(PathBuf::from("Wallpapers")).chain(
        ["Games", "Labels"].into_iter().flat_map(|kind| {
            Platform::ALL
                .into_iter()
                .map(move |p| Path::new(kind).join(p.dir_name()))
        }),
    );
    for dir in dirs {
        let entries = match std::fs::read_dir(root.join(&dir)) {
            Ok(entries) => entries,
            Err(e) if e.kind() == io::ErrorKind::NotFound => continue,
            Err(e) => return Err(e),
        };
        for entry in entries {
            let entry = entry?;
            let path = entry.path();
            if slot_store::is_hidden(&path) || !entry.file_type()?.is_file() || temporary(&path) {
                continue;
            }
            let meta = entry.metadata()?;
            let png = path
                .extension()
                .is_some_and(|s| s.eq_ignore_ascii_case("png"));
            let modified = meta.modified().ok();
            let changed = changed(&meta);
            let key = dir.join(entry.file_name());
            let unchanged = prior.and_then(|p| p.get(&key)).filter(|p| {
                changed.is_some()
                    && p.len == meta.len()
                    && p.modified == modified
                    && p.changed == changed
            });
            let image_hash = if let Some(previous) = unchanged {
                previous.image_hash
            } else if png && meta.len() <= IMAGE_LIMIT {
                let mut hasher = std::collections::hash_map::DefaultHasher::new();
                let mut file = std::fs::File::open(&path)?.take(IMAGE_LIMIT + 1);
                let mut buf = [0; 16384];
                loop {
                    let n = file.read(&mut buf)?;
                    if n == 0 {
                        break;
                    }
                    buf[..n].hash(&mut hasher);
                }
                Some(hasher.finish())
            } else {
                None
            };
            result.insert(
                key,
                Mark {
                    len: meta.len(),
                    modified,
                    changed,
                    image_hash,
                },
            );
        }
    }
    for name in [slot_store::CART_SHELL_FILE, slot_store::LABELS_SHELL_FILE] {
        if let Ok(bytes) = std::fs::read(root.join(name)) {
            let mut h = std::collections::hash_map::DefaultHasher::new();
            bytes.hash(&mut h);
            result.insert(
                PathBuf::from(name),
                Mark {
                    len: bytes.len() as u64,
                    modified: None,
                    changed: None,
                    image_hash: Some(h.finish()),
                },
            );
        }
    }
    Ok(result)
}

fn temporary(path: &Path) -> bool {
    path.extension().and_then(|s| s.to_str()).is_some_and(|s| {
        ["part", "partial", "tmp", "download", "filepart"]
            .iter()
            .any(|x| s.eq_ignore_ascii_case(x))
    })
}

fn rom_valid(path: &Path, platform: Platform, len: u64) -> bool {
    let Ok(mut f) = std::fs::File::open(path) else {
        return false;
    };
    let mut head = [0; 0x150];
    if platform == Platform::Gba {
        return (0xc0..=32 << 20).contains(&len)
            && len.is_multiple_of(4)
            && f.read_exact(&mut head[..0xc0]).is_ok()
            && head[3] == 0xea
            && head[0xb2] == 0x96;
    }
    if f.read_exact(&mut head).is_err() {
        return false;
    }
    let expected = match head[0x148] {
        n @ 0..=8 => 32768u64 << n,
        0x52 => 72 * 16384,
        0x53 => 80 * 16384,
        0x54 => 96 * 16384,
        _ => return false,
    };
    len >= expected && len <= 8 << 20
}

#[derive(Default)]
pub struct Libraries {
    local: Catalog,
    external: BTreeMap<PathBuf, Catalog>,
    roots: Vec<PathBuf>,
}
impl Libraries {
    pub fn poll(&mut self, root: &Path) -> io::Result<Option<Refresh>> {
        self.poll_roots(root, &slot_store::library_roots(root)[1..])
    }
    pub fn poll_roots(&mut self, root: &Path, external: &[PathBuf]) -> io::Result<Option<Refresh>> {
        let local = self.local.poll(root)?;
        let mut changed = local.is_some() || self.roots != external;
        self.external.retain(|p, _| external.contains(p));
        self.roots = external.to_vec();
        let mut labels = BTreeSet::new();
        let mut wallpapers_changed = BTreeSet::new();
        if let Some(r) = local {
            labels.extend(r.changed_labels);
            wallpapers_changed = r.changed_wallpapers;
        }
        let mut issues = self.local.issues.values().cloned().collect::<Vec<_>>();
        let mut libraries = vec![self.local.carts.clone()];
        for path in external {
            let catalog = self.external.entry(path.clone()).or_default();
            match catalog.poll_inner(path, false) {
                Ok(Some(r)) => {
                    changed = true;
                    labels.extend(r.changed_labels);
                }
                Ok(None) => {}
                Err(_) => {
                    changed |= !catalog.carts.is_empty();
                    *catalog = Catalog::default();
                    issues.push(format!(
                        "{}: card unavailable; refresh after inserting",
                        path.display()
                    ));
                }
            }
            issues.extend(
                catalog
                    .issues
                    .values()
                    .map(|s| format!("{}: {s}", path.display())),
            );
            libraries.push(catalog.carts.clone());
        }
        if !changed || self.local.applied.is_none() {
            return Ok(None);
        }
        let wallpapers = self
            .local
            .valid
            .keys()
            .filter_map(|p| {
                (p.parent() == Some(Path::new("Wallpapers")))
                    .then(|| p.file_name()?.to_str().map(str::to_owned))
                    .flatten()
            })
            .collect();
        Ok(Some(Refresh {
            carts: slot_store::merge_libraries(libraries),
            wallpapers,
            changed_labels: labels,
            changed_wallpapers: wallpapers_changed,
            issues,
        }))
    }
    fn settled(&self) -> bool {
        self.local.applied.is_some() && self.external.values().all(|c| c.applied.is_some())
    }

    fn invalidate(&mut self) {
        self.local.applied = None;
        for catalog in self.external.values_mut() {
            catalog.applied = None;
        }
    }
}

pub struct Watcher {
    tx: Sender<bool>,
    rx: Receiver<io::Result<Option<Refresh>>>,
    scan_activity: Arc<AtomicU64>,
    last_scan_activity: u64,
    busy: bool,
    requested: bool,
    next: Instant,
}
impl Watcher {
    pub fn spawn(root: PathBuf) -> Self {
        let (tx, jobs) = mpsc::channel();
        let (out, rx) = mpsc::channel();
        let scan_activity = Arc::new(AtomicU64::new(0));
        let worker_scan_activity = Arc::clone(&scan_activity);
        let _ = std::thread::Builder::new()
            .name("slot-content".into())
            .spawn(move || {
                let mut catalog = Libraries::default();
                let maintenance = cfg!(feature = "rg353v")
                    && root == Path::new("/storage/slotcontent")
                    && (Path::new("/usr/bin/slot-storage-tools").is_file()
                        || Path::new("/usr/bin/slot-sd-library").is_file());
                #[cfg(all(feature = "rg353v", target_os = "linux"))]
                let mut hotplug = (root == Path::new("/storage/slotcontent")
                    && Path::new("/usr/bin/slot-sd-library").is_file())
                .then(sd_hotplug::Monitor::new);
                #[cfg(all(feature = "rg353v", target_os = "linux"))]
                let mut pending_sd_refresh = false;
                while let Ok(force) = jobs.recv() {
                    #[cfg(all(feature = "rg353v", target_os = "linux"))]
                    if let Some(monitor) = &mut hotplug {
                        // This worker receives jobs only while the shelf is idle.
                        // Drain kernel events and coalesce bursts into one mount scan.
                        let change = monitor.changed();
                        pending_sd_refresh |= change.changed;
                        if change.inserted {
                            // Generation plus active bit preserves fast start/finish
                            // events even if both happen between UI frames.
                            worker_scan_activity
                                .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |state| {
                                    Some(((state >> 1).wrapping_add(1) << 1) | 1)
                                })
                                .ok();
                        }
                        if pending_sd_refresh && !Path::new("/run/slot-usb/active").exists() {
                            let ok = std::process::Command::new("/usr/bin/slot-sd-library")
                                .arg("hotplug-refresh")
                                .output()
                                .is_ok_and(|output| output.status.success());
                            if ok {
                                pending_sd_refresh = false;
                                catalog.invalidate();
                            }
                        }
                    }
                    if force {
                        #[cfg(feature = "rg353v")]
                        if root == Path::new("/storage/slotcontent")
                            && Path::new("/usr/bin/slot-sd-library").exists()
                        {
                            // Explicit refresh; automatic scans above run only after media changes.
                            let _ = std::process::Command::new("/usr/bin/slot-sd-library")
                                .arg("refresh")
                                .output();
                        }
                        catalog.invalidate();
                    }
                    // Serialize catalog reads/writes with explicit maintenance. The
                    // worker may wait; the UI never waits or holds this lock.
                    let _guard = if maintenance {
                        match maintenance_read_lock() {
                            Ok(lock) => Some(lock),
                            Err(e) => {
                                let _ = out.send(Err(e));
                                continue;
                            }
                        }
                    } else {
                        None
                    };
                    let result = catalog.poll(&root);
                    #[cfg(all(feature = "rg353v", target_os = "linux"))]
                    let discovery_ready = !pending_sd_refresh;
                    #[cfg(not(all(feature = "rg353v", target_os = "linux")))]
                    let discovery_ready = true;
                    if discovery_ready && catalog.settled() {
                        worker_scan_activity.fetch_and(!1, Ordering::SeqCst);
                    }
                    if out.send(result).is_err() {
                        break;
                    }
                }
            });
        Self {
            tx,
            rx,
            scan_activity,
            last_scan_activity: 0,
            busy: false,
            requested: false,
            next: Instant::now(),
        }
    }
    pub fn take_scan_activity(&mut self) -> Option<(bool, bool)> {
        let state = self.scan_activity.load(Ordering::SeqCst);
        if state == self.last_scan_activity {
            return None;
        }
        let started = state >> 1 != self.last_scan_activity >> 1;
        self.last_scan_activity = state;
        Some((started, state & 1 != 0))
    }

    pub fn poll(&mut self, allowed: bool, force: bool) -> Option<io::Result<Option<Refresh>>> {
        self.requested |= force;
        let result = self.rx.try_recv().ok();
        if result.is_some() {
            self.busy = false;
        }
        if allowed && !self.busy && Instant::now() >= self.next {
            self.busy = self.tx.send(self.requested).is_ok();
            self.requested = false;
            self.next = Instant::now() + INTERVAL;
        }
        result
    }
}

#[cfg(unix)]
fn changed(meta: &std::fs::Metadata) -> Option<(i64, i64, u64)> {
    use std::os::unix::fs::MetadataExt;
    Some((meta.ctime(), meta.ctime_nsec(), meta.ino()))
}
#[cfg(not(unix))]
fn changed(_: &std::fs::Metadata) -> Option<(i64, i64, u64)> {
    None
}

fn valid_png(path: &Path) -> bool {
    let Ok(file) = std::fs::File::open(path) else {
        return false;
    };
    let mut decoder = png::Decoder::new(std::io::BufReader::new(file.take(IMAGE_LIMIT + 1)));
    decoder.set_limits(png::Limits { bytes: 64 << 20 });
    let Ok(mut reader) = decoder.read_info() else {
        return false;
    };
    let info = reader.info();
    if info.width > 8192
        || info.height > 8192
        || (info.width as u64) * (info.height as u64) > 4096 * 4096
    {
        return false;
    }
    loop {
        match reader.next_row() {
            Ok(Some(_)) => {}
            Ok(None) => break,
            Err(_) => return false,
        }
    }
    reader.finish().is_ok()
}

#[cfg(unix)]
fn maintenance_read_lock() -> io::Result<std::fs::File> {
    use std::os::fd::AsRawFd;
    let base = Path::new("/run/slot-sd-library");
    std::fs::create_dir_all(base)?;
    let file = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(base.join("lock"))?;
    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_SH) } != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(file)
}
#[cfg(not(unix))]
fn maintenance_read_lock() -> io::Result<std::fs::File> {
    Err(io::Error::other("SD maintenance unavailable"))
}

#[cfg(test)]
mod scan_activity_tests {
    use super::*;
    #[test]
    fn fast_completion_is_not_lost_and_idle_polling_has_no_new_notice() {
        let (tx, _jobs) = mpsc::channel();
        let (_out, rx) = mpsc::channel();
        let state = Arc::new(AtomicU64::new(0));
        let mut watcher = Watcher {
            tx,
            rx,
            scan_activity: Arc::clone(&state),
            last_scan_activity: 0,
            busy: false,
            requested: false,
            next: Instant::now(),
        };
        assert_eq!(watcher.take_scan_activity(), None);
        state.store(3, Ordering::SeqCst);
        state.fetch_and(!1, Ordering::SeqCst);
        assert_eq!(watcher.take_scan_activity(), Some((true, false)));
        assert_eq!(watcher.take_scan_activity(), None);
        state.store(5, Ordering::SeqCst);
        assert_eq!(watcher.take_scan_activity(), Some((true, true)));
        state.store(4, Ordering::SeqCst);
        assert_eq!(watcher.take_scan_activity(), Some((false, false)));
    }
}
