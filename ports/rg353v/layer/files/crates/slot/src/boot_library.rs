//! Fresh boot scans overlap graphics. The first scene still waits for complete
//! libraries; primary settings are resolved only after legacy migration.
use slot_store::{Cart, Platform, StoreError};
use std::{
    path::{Path, PathBuf},
    thread::{self, JoinHandle},
    time::SystemTime,
};

#[derive(PartialEq, Eq)]
struct DirectoryStamp {
    modified: Option<SystemTime>,
    created: Option<SystemTime>,
    len: u64,
    is_dir: bool,
    #[cfg(unix)]
    identity: (u64, u64),
}
type Stamp = Vec<Option<DirectoryStamp>>;
fn library_stamp(root: &Path) -> Stamp {
    std::iter::once(root.join("Games"))
        .chain(Platform::ALL.into_iter().flat_map(|platform| {
            ["Games", "Labels"].map(|folder| root.join(folder).join(platform.dir_name()))
        }))
        .map(|path| {
            let meta = std::fs::metadata(path).ok()?;
            Some(DirectoryStamp {
                modified: meta.modified().ok(),
                created: meta.created().ok(),
                len: meta.len(),
                is_dir: meta.is_dir(),
                #[cfg(unix)]
                identity: {
                    use std::os::unix::fs::MetadataExt;
                    (meta.dev(), meta.ino())
                },
            })
        })
        .collect()
}
fn fresh_scan(root: &Path, roots: &[PathBuf]) -> Result<Vec<Cart>, StoreError> {
    if roots.first().map(PathBuf::as_path) != Some(root) {
        return slot_store::scan(root);
    }
    let libraries = roots
        .iter()
        .map(|path| slot_store::scan_library(path))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(slot_store::merge_libraries(libraries))
}

struct Primary {
    carts: Vec<Cart>,
    stamp: Stamp,
}
type Libraries = Result<Vec<Vec<Cart>>, StoreError>;
pub struct Scan {
    root: PathBuf,
    roots: Vec<PathBuf>,
    primary: JoinHandle<Result<Primary, StoreError>>,
    worker: Option<JoinHandle<Libraries>>,
}
impl Scan {
    pub fn start(root: &Path) -> Option<Self> {
        Self::start_roots(root, slot_store::library_roots(root))
    }
    fn start_roots(root: &Path, roots: Vec<PathBuf>) -> Option<Self> {
        if roots.first().map(PathBuf::as_path) != Some(root) {
            return None;
        }
        let primary_root = root.to_owned();
        let primary = thread::Builder::new()
            .name("slot-boot-primary".into())
            .spawn(move || {
                crate::boot_time::mark("primary scan started");
                // Record before enumeration, so changes during or after it
                // cause a fresh serial scan rather than reuse a partial view.
                let stamp = library_stamp(&primary_root);
                let carts = slot_store::scan_library_files(&primary_root)?;
                crate::boot_time::mark("primary scan finished");
                Ok(Primary { carts, stamp })
            })
            .ok()?;
        let worker = if roots.len() > 1 {
            let cards = roots[1..].to_vec();
            Some(
                thread::Builder::new()
                    .name("slot-boot-library".into())
                    .spawn(move || {
                        crate::boot_time::mark("sd scan started");
                        let libraries = cards
                            .iter()
                            .map(|card| slot_store::scan_library(card))
                            .collect();
                        crate::boot_time::mark("sd scan finished");
                        libraries
                    })
                    .ok()?,
            )
        } else {
            None
        };
        Some(Self {
            root: root.into(),
            roots,
            primary,
            worker,
        })
    }
    pub fn finish(self, root: &Path) -> Result<Vec<Cart>, StoreError> {
        let roots = slot_store::library_roots(root);
        self.finish_roots(root, &roots)
    }
    fn finish_roots(self, root: &Path, roots: &[PathBuf]) -> Result<Vec<Cart>, StoreError> {
        // Join even discarded work; no scan thread outlives its root on a
        // changed mount list, worker failure, or test-directory cleanup.
        let primary = self.primary.join().ok().and_then(Result::ok);
        let libraries = self
            .worker
            .map(|worker| worker.join().ok().and_then(Result::ok))
            .unwrap_or_else(|| Some(Vec::new()));
        if self.root != root || self.roots != roots {
            return fresh_scan(root, roots);
        }
        match (primary, libraries) {
            (Some(mut primary), Some(mut libraries)) => {
                if primary.stamp != library_stamp(root) {
                    return fresh_scan(root, roots);
                }
                // The caller has now migrated preferences. Never cache old
                // shell settings just because file enumeration ran earlier.
                slot_store::resolve_library_shells(root, &mut primary.carts);
                libraries.insert(0, primary.carts);
                Ok(slot_store::merge_libraries(libraries))
            }
            _ => fresh_scan(root, roots),
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn library(root: &Path, name: &str) {
        std::fs::create_dir_all(root.join("Games/GBA")).unwrap();
        std::fs::write(root.join("Games/GBA").join(name), b"rom").unwrap();
    }
    fn wait_for_primary(scan: &Scan) {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
        while !scan.primary.is_finished() {
            assert!(std::time::Instant::now() < deadline);
            thread::sleep(std::time::Duration::from_millis(1));
        }
    }
    #[test]
    fn single_library_also_overlaps_graphics() {
        let d = tempfile::tempdir().unwrap();
        library(d.path(), "Local.gba");
        let scan = Scan::start(d.path()).unwrap();
        assert!(scan.worker.is_none());
        assert_eq!(
            scan.finish(d.path()).unwrap(),
            slot_store::scan(d.path()).unwrap()
        );
    }
    #[test]
    fn background_result_matches_serial_merge_including_labels_and_duplicates() {
        let d = tempfile::tempdir().unwrap();
        let card = tempfile::tempdir().unwrap();
        library(d.path(), "Local.gba");
        library(card.path(), "Local.gba");
        library(card.path(), "Remote.GBA");
        library(card.path(), "._Remote.gba");
        std::fs::create_dir_all(card.path().join("Labels/GBA")).unwrap();
        std::fs::write(card.path().join("Labels/GBA/remote.PNG"), b"art").unwrap();
        let roots = vec![d.path().into(), card.path().into()];
        let scan = Scan::start_roots(d.path(), roots.clone()).unwrap();
        let expected =
            slot_store::merge_libraries(roots.iter().map(|p| slot_store::scan_library(p).unwrap()));
        let actual = scan.finish_roots(d.path(), &roots).unwrap();
        assert_eq!(actual, expected);
        assert_eq!(actual.len(), 2);
        assert!(actual.iter().all(|c| c.title.is_empty()));
        assert_eq!(actual[0].rom, d.path().join("Games/GBA/Local.gba"));
        assert_eq!(
            actual[1].label,
            Some(card.path().join("Labels/GBA/remote.PNG"))
        );
    }
    #[test]
    fn primary_changes_after_the_worker_finishes_are_discovered() {
        let d = tempfile::tempdir().unwrap();
        let card = tempfile::tempdir().unwrap();
        library(d.path(), "Local.gba");
        library(card.path(), "Remote.gba");
        let roots = vec![d.path().into(), card.path().into()];
        let scan = Scan::start_roots(d.path(), roots.clone()).unwrap();
        wait_for_primary(&scan);
        library(d.path(), "Added.gba");
        assert_eq!(scan.finish_roots(d.path(), &roots).unwrap().len(), 3);
    }
    #[test]
    fn migration_resolves_current_primary_shells_after_file_enumeration() {
        let d = tempfile::tempdir().unwrap();
        library(d.path(), "Local.gba");
        std::fs::create_dir_all(d.path().join("System")).unwrap();
        let choice = "auto aabbcc clear";
        std::fs::write(
            d.path().join("System/cart_shell.ini"),
            format!("Local={choice}\n"),
        )
        .unwrap();
        let scan = Scan::start(d.path()).unwrap();
        wait_for_primary(&scan);
        crate::root::prepare_boot(d.path());
        let actual = scan.finish(d.path()).unwrap();
        assert_eq!(actual, slot_store::scan(d.path()).unwrap());
        assert_eq!(actual[0].shell, slot_store::ShellChoice::parse(choice));
    }
    #[test]
    fn changed_root_or_mount_list_never_returns_the_previous_card() {
        let d = tempfile::tempdir().unwrap();
        let card = tempfile::tempdir().unwrap();
        let other = tempfile::tempdir().unwrap();
        library(d.path(), "Local.gba");
        library(card.path(), "Remote.gba");
        library(other.path(), "Other.gba");
        let roots = vec![d.path().into(), card.path().into()];
        let result = Scan::start_roots(d.path(), roots.clone())
            .unwrap()
            .finish_roots(d.path(), &roots[..1])
            .unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].stem, "Local");
        let result = Scan::start_roots(d.path(), roots)
            .unwrap()
            .finish(other.path())
            .unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].stem, "Other");
    }
    #[test]
    fn first_shelf_waits_for_worker_and_worker_failure_falls_back() {
        let d = tempfile::tempdir().unwrap();
        let card = tempfile::tempdir().unwrap();
        library(d.path(), "Local.gba");
        library(card.path(), "Remote.gba");
        let roots = vec![d.path().into(), card.path().into()];
        let mut scan = Scan::start_roots(d.path(), roots.clone()).unwrap();
        let path = card.path().to_owned();
        let (send, recv) = std::sync::mpsc::channel();
        // Keep the real primary worker and replace only the removable result.
        scan.worker.take().unwrap().join().unwrap().unwrap();
        scan.worker = Some(thread::spawn(move || {
            recv.recv().unwrap();
            Ok(vec![slot_store::scan_library(&path)?])
        }));
        let root = d.path().to_owned();
        let copy = roots.clone();
        let result = thread::spawn(move || scan.finish_roots(&root, &copy));
        assert!(!result.is_finished());
        send.send(()).unwrap();
        assert_eq!(result.join().unwrap().unwrap().len(), 2);
        let mut scan = Scan::start_roots(d.path(), roots.clone()).unwrap();
        scan.worker.take().unwrap().join().unwrap().unwrap();
        scan.worker = Some(thread::spawn(|| panic!("test worker failure")));
        assert_eq!(scan.finish_roots(d.path(), &roots).unwrap().len(), 2);
        let mut scan = Scan::start(d.path()).unwrap();
        scan.primary.join().unwrap().unwrap();
        scan.primary = thread::spawn(|| panic!("test primary failure"));
        assert_eq!(scan.finish(d.path()).unwrap().len(), 1);
    }
}
