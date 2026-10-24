use slot_store::gb::{self, Class};
#[test]
fn cached_header_and_shell_class_share_one_generation_including_missing_and_short_files() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("game.gbc");
    gb::clear_header_cache();
    let mut bytes = vec![0u8; gb::HEADER_LEN];
    bytes[0x143] = 0xc0;
    bytes[0x134..0x139].copy_from_slice(b"COLOR");
    std::fs::write(&p, &bytes).unwrap();
    assert_eq!(gb::cached_header(&p).unwrap().title, "COLOR");
    std::fs::remove_file(&p).unwrap();
    assert_eq!(gb::cached_class(&p), Class::ColourOnly);
    gb::clear_header_cache();
    assert!(gb::cached_header(&p).is_none());
    std::fs::write(&p, &bytes).unwrap();
    assert_eq!(
        gb::cached_class(&p),
        Class::Original,
        "missing file must also be cached until refresh"
    );
    gb::clear_header_cache();
    assert_eq!(gb::cached_class(&p), Class::ColourOnly);
    std::fs::write(&p, &bytes[..0x144]).unwrap();
    gb::clear_header_cache();
    assert!(gb::cached_header(&p).is_none());
    assert_eq!(
        gb::cached_class(&p),
        Class::ColourOnly,
        "short ROMs preserve the readable CGB flag"
    );
}
#[test]
fn failed_atomic_save_has_path_operation_errno_and_timestamp_but_success_does_not_add_faults() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("missing/save.sav");
    let error = slot_store::atomic_write(&path, b"save").unwrap_err();
    let faults = slot_store::storage_faults();
    let fault = faults
        .iter()
        .find(|f| f.path == path.to_string_lossy())
        .unwrap();
    assert_eq!(fault.errno, error.raw_os_error());
    assert_eq!(fault.operation, "Create temporary save");
    assert!(fault.timestamp > 0);
    assert!(!fault.reason.is_empty());
    let before = faults.len();
    slot_store::atomic_write(&d.path().join("valid.sav"), b"save").unwrap();
    assert_eq!(slot_store::storage_faults().len(), before);
}
