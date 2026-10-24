#[cfg(all(feature = "rg353v", target_os = "linux"))]
fn main() {
    use std::{fs, path::Path, thread, time::Duration};
    let root = Path::new("/run/slot-usb");
    assert!(
        !root.exists(),
        "Run this smoke test in its isolated build container"
    );
    fs::create_dir(root).unwrap();
    fs::write(root.join("active"), b"test").unwrap();
    fs::write(root.join("phase"), b"waiting\n").unwrap();
    fs::write(root.join("status"), "Connected to computer\nOpen SLOT on your computer\n\nEject SLOT before unplugging\nSlot resumes after ejecting\n").unwrap();
    let check = thread::spawn(move || {
        thread::sleep(Duration::from_secs(1));
        fs::write(root.join("phase"), b"shared\n").unwrap();
        thread::sleep(Duration::from_secs(1));
        fs::write(root.join("phase"), b"restoring\n").unwrap();
        thread::sleep(Duration::from_secs(1));
        let ready = root.join("screen-ready").exists();
        fs::remove_file(root.join("active")).unwrap();
        ready
    });
    slot::usb_storage::screen().unwrap();
    assert!(
        check.join().unwrap(),
        "USB storage screen did not present a frame"
    );
    fs::remove_dir_all(root).unwrap();
}
#[cfg(not(all(feature = "rg353v", target_os = "linux")))]
fn main() {}
