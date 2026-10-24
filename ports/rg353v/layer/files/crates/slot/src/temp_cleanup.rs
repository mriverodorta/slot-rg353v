//! Bounded, best-effort housekeeping after the first displayed frame.
use std::{
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
pub fn start(root: &Path) {
    let root = root.to_owned();
    let _ = std::thread::Builder::new()
        .name("slot-temp-clean".into())
        .spawn(move || {
            std::thread::sleep(Duration::from_secs(2));
            sweep(&root, 20_000, Duration::from_millis(150), process_alive);
        });
}
fn process_alive(pid: u32) -> bool {
    #[cfg(unix)]
    {
        unsafe {
            libc::kill(pid as i32, 0) == 0
                || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
        }
    }
    #[cfg(not(unix))]
    {
        let _ = pid;
        true
    }
}
fn old_writer(name: &str) -> Option<u32> {
    let rest = name.strip_prefix('.')?.strip_suffix(".tmp")?;
    let mut parts = rest.rsplitn(3, '.');
    let seq = parts.next()?;
    let pid = parts.next()?;
    let file = parts.next()?;
    if file.is_empty()
        || seq.is_empty()
        || !seq.bytes().all(|c| c.is_ascii_digit())
        || !pid.bytes().all(|c| c.is_ascii_digit())
    {
        return None;
    }
    let pid = pid.parse::<u32>().ok()?;
    (pid > 0 && pid <= i32::MAX as u32 && pid != std::process::id()).then_some(pid)
}
pub fn sweep(root: &Path, limit: usize, budget: Duration, alive: impl Fn(u32) -> bool) -> usize {
    let started = Instant::now();
    let mut visited = 0;
    let mut removed = 0;
    // Never follow symbolic links, including removable-media redirections.
    let mut stack: Vec<(PathBuf, usize)> = ["Config", "Saves", "States"]
        .map(|s| (root.join(s), 0))
        .into();
    while let Some((dir, depth)) = stack.pop() {
        if started.elapsed() >= budget || visited >= limit {
            break;
        }
        let Ok(meta) = std::fs::symlink_metadata(&dir) else {
            continue;
        };
        if !meta.is_dir() || meta.file_type().is_symlink() {
            continue;
        }
        let Ok(entries) = std::fs::read_dir(dir) else {
            continue;
        };
        for entry in entries.flatten() {
            if started.elapsed() >= budget || visited >= limit {
                return removed;
            }
            visited += 1;
            let Ok(kind) = entry.file_type() else {
                continue;
            };
            if kind.is_dir() && depth < 8 {
                stack.push((entry.path(), depth + 1));
            } else if kind.is_file() {
                if let Some(pid) = old_writer(&entry.file_name().to_string_lossy()) {
                    if !alive(pid) && std::fs::remove_file(entry.path()).is_ok() {
                        removed += 1;
                    }
                }
            }
        }
    }
    removed
}
