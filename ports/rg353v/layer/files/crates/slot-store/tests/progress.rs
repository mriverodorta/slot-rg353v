use slot_store::{progress_root, SaveLocation};
#[test]
fn boot_system_and_rom_library_are_independent_for_all_consoles() {
    let emmc = tempfile::tempdir().unwrap();
    let sd = tempfile::tempdir().unwrap();
    std::fs::create_dir(emmc.path().join("Config")).unwrap();
    for p in ["GB", "GBC", "GBA"] {
        let rom = sd.path().join(format!("Games/{p}/Game.rom"));
        assert_eq!(SaveLocation::read(emmc.path()), SaveLocation::System);
        assert_eq!(progress_root(emmc.path(), &rom), emmc.path());
    }
    std::fs::write(emmc.path().join("Config/save-location"), "game\n").unwrap();
    for p in ["GB", "GBC", "GBA"] {
        assert_eq!(
            progress_root(emmc.path(), &sd.path().join(format!("Games/{p}/Game.rom"))),
            sd.path()
        );
        assert_eq!(
            progress_root(
                emmc.path(),
                &emmc.path().join(format!("Games/{p}/Game.rom"))
            ),
            emmc.path()
        );
    }
    // SD boot: System follows the boot SLOT partition, not an eMMC constant.
    let rom = emmc.path().join("Games/GBA/Game.gba");
    assert_eq!(progress_root(sd.path(), &rom), sd.path());
}
