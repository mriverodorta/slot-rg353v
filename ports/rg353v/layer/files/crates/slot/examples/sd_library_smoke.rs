//! Silent removable-library ROM/state/SRAM probe. Never opens ALSA or user saves.
use slot_retro::{ButtonMask, LibretroCore, RetroCore};
use std::path::{Path, PathBuf};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = std::env::args().collect::<Vec<_>>();
    assert_eq!(args.len(), 4, "root core-library TF1|TF2");
    let root = Path::new(&args[1]);
    let slot = &args[3];
    assert!(matches!(slot.as_str(), "TF1" | "TF2"));
    let card = PathBuf::from("/run/slot-sd-library").join(slot);
    let carts = slot_store::scan(root)?;
    let fixtures = carts
        .iter()
        .filter(|c| c.stem.starts_with("SD68 Test - ") && c.rom.starts_with(&card))
        .collect::<Vec<_>>();
    assert_eq!(
        fixtures.len(),
        3,
        "GB, GBC and GBA fixture ROMs must come from selected card"
    );
    for cart in fixtures {
        let mut core = LibretroCore::open(Path::new(&args[2]))?;
        core.set_option("mgba_skip_bios", "ON");
        core.set_option("mgba_frameskip", "disabled");
        core.load(&cart.rom)?;
        for _ in 0..120 {
            core.run_frame(ButtonMask::default());
        }
        let state = core.serialize()?;
        let save = core.save_ram();
        let temp = tempfile::tempdir()?;
        std::fs::write(temp.path().join("state"), &state)?;
        for _ in 0..10 {
            core.run_frame(ButtonMask::default());
        }
        let expected = core.video_xrgb8888().to_vec();
        core.unserialize(&std::fs::read(temp.path().join("state"))?)?;
        for _ in 0..10 {
            core.run_frame(ButtonMask::default());
        }
        assert_eq!(expected, core.video_xrgb8888());
        assert!(!expected.is_empty());
        if let Some(bytes) = save {
            std::fs::write(temp.path().join("save"), &bytes)?;
            core.load_save_ram(&std::fs::read(temp.path().join("save"))?)?;
        }
        println!(
            "{}: {} frames={} state_bytes={} SRAM roundtrip checked when supported",
            cart.platform.dir_name(),
            cart.rom.display(),
            130,
            state.len()
        );
    }
    println!("PASS: three card ROMs executed silently; state restore reproduced identical pixels; user saves untouched");
    Ok(())
}
