//! Observe real directory opens: empty consoles must not read unused artwork.
#![cfg(target_os = "linux")]
use std::{
    ffi::{c_char, c_int, c_void, CString},
    io,
    os::{
        fd::{AsRawFd, FromRawFd, OwnedFd},
        unix::ffi::OsStrExt,
    },
    path::Path,
};

unsafe extern "C" {
    fn inotify_init1(flags: c_int) -> c_int;
    fn inotify_add_watch(fd: c_int, pathname: *const c_char, mask: u32) -> c_int;
    fn read(fd: c_int, buf: *mut c_void, count: usize) -> isize;
}
struct Opens(OwnedFd);
impl Opens {
    fn watch(path: &Path) -> Self {
        // Linux O_NONBLOCK | O_CLOEXEC and IN_OPEN; no runtime dependency.
        let fd = unsafe { inotify_init1(0x800 | 0x80000) };
        assert!(fd >= 0, "{}", io::Error::last_os_error());
        let fd = unsafe { OwnedFd::from_raw_fd(fd) };
        let name = CString::new(path.as_os_str().as_bytes()).unwrap();
        assert!(unsafe { inotify_add_watch(fd.as_raw_fd(), name.as_ptr(), 0x20) } >= 0);
        Self(fd)
    }
    fn any(&self) -> bool {
        let mut buffer = [0u8; 4096];
        let count = unsafe { read(self.0.as_raw_fd(), buffer.as_mut_ptr().cast(), buffer.len()) };
        if count < 0 {
            assert_eq!(io::Error::last_os_error().kind(), io::ErrorKind::WouldBlock);
        }
        count > 0
    }
}
#[test]
fn empty_and_invalid_only_consoles_leave_artwork_and_shell_files_unopened() {
    let d = tempfile::tempdir().unwrap();
    let root = d.path();
    for platform in ["GB", "GBC", "GBA"] {
        std::fs::create_dir_all(root.join("Games").join(platform)).unwrap();
        std::fs::create_dir_all(root.join("Labels").join(platform)).unwrap();
    }
    std::fs::create_dir_all(root.join("Config")).unwrap();
    for path in [slot_store::CART_SHELL_FILE, slot_store::LABELS_SHELL_FILE] {
        std::fs::write(root.join(path), "").unwrap();
    }
    std::fs::write(root.join("Games/GB/._Hidden.gb"), b"metadata").unwrap();
    std::fs::write(root.join("Games/GBA/notes.txt"), b"notes").unwrap();
    std::fs::create_dir(root.join("Games/GBC/Folder.gbc")).unwrap();
    let gb = Opens::watch(&root.join("Labels/GB"));
    let gbc = Opens::watch(&root.join("Labels/GBC"));
    let gba = Opens::watch(&root.join("Labels/GBA"));
    let shell = Opens::watch(&root.join(slot_store::CART_SHELL_FILE));
    let label_shell = Opens::watch(&root.join(slot_store::LABELS_SHELL_FILE));
    assert!(slot_store::scan_library(root).unwrap().is_empty());
    for watcher in [&gb, &gbc, &gba, &shell, &label_shell] {
        assert!(!watcher.any(), "unused artwork/settings were opened");
    }
    // A new game is discovered on the next fresh scan, including its label.
    std::fs::write(root.join("Games/GB/Valid.gb"), b"rom").unwrap();
    std::fs::write(root.join("Labels/GB/VALID.PNG"), b"art").unwrap();
    let carts = slot_store::scan_library(root).unwrap();
    assert_eq!(carts.len(), 1);
    assert_eq!(
        carts[0].label.as_deref(),
        Some(root.join("Labels/GB/VALID.PNG").as_path())
    );
    for watcher in [&gb, &shell, &label_shell] {
        assert!(watcher.any());
    }
    for watcher in [&gbc, &gba] {
        assert!(!watcher.any());
    }
}

#[test]
fn split_file_discovery_leaves_shell_reads_until_resolution() {
    let d = tempfile::tempdir().unwrap();
    let root = d.path();
    for sub in ["Games/GBA", "Labels/GBA", "Config"] {
        std::fs::create_dir_all(root.join(sub)).unwrap();
    }
    std::fs::write(root.join("Games/GBA/Local.gba"), b"rom").unwrap();
    std::fs::write(root.join("Labels/GBA/Local.png"), b"art").unwrap();
    for path in [slot_store::CART_SHELL_FILE, slot_store::LABELS_SHELL_FILE] {
        std::fs::write(root.join(path), "").unwrap();
    }
    let config = Opens::watch(&root.join(slot_store::CART_SHELL_FILE));
    let labels = Opens::watch(&root.join(slot_store::LABELS_SHELL_FILE));
    let mut carts = slot_store::scan_library_files(root).unwrap();
    assert_eq!(carts.len(), 1);
    assert!(carts[0].label.is_some());
    assert!(carts[0].shell.is_none());
    assert!(
        !config.any() && !labels.any(),
        "preferences were read before migration"
    );
    slot_store::resolve_library_shells(root, &mut carts);
    assert!(config.any() && labels.any());
    assert_eq!(carts, slot_store::scan_library(root).unwrap());
}
