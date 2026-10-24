//! Silent, disposable save/state checks on the actual two library filesystems.
//! Never opens ALSA or writes into a real game's Saves/States directory.
use slot::{persist, root};
use slot_retro::{ButtonMask, LibretroCore, RetroCore};
use slot_store::{Core, Platform, StateRing};
use std::path::Path;
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    assert_eq!(args.len(), 4, "system-root card-root verified-mgba-library");
    let system = Path::new(&args[1]);
    let card = Path::new(&args[2]);
    slot_store::ensure_progress_storage(card, true)?;
    assert!(matches!(
        card.to_str(),
        Some("/run/slot-sd-library/TF1" | "/run/slot-sd-library/TF2")
    ));
    let internal = tempfile::Builder::new()
        .prefix(".slot-progress-check-")
        .tempdir_in(system)?;
    let portable = tempfile::Builder::new()
        .prefix(".slot-progress-check-")
        .tempdir_in(card)?;
    std::fs::create_dir(internal.path().join("Config"))?;
    // exFAT does not support symlinks. Copy just three disposable fixtures,
    // never the personal library or any of its progress.
    let source = slot_store::scan_library(card)?;
    for platform in [Platform::Gb, Platform::Gbc, Platform::Gba] {
        let cart = source
            .iter()
            .find(|c| c.platform == platform && c.stem.to_lowercase().contains("zelda"))
            .or_else(|| source.iter().find(|c| c.platform == platform))
            .ok_or("Missing console fixture")?;
        let dir = portable.path().join("Games").join(platform.dir_name());
        std::fs::create_dir_all(&dir)?;
        std::fs::copy(&cart.rom, dir.join(cart.rom.file_name().unwrap()))?;
    }
    let carts = slot_store::scan_library(portable.path())?;
    for location in ["system", "game"] {
        std::fs::write(
            internal.path().join("Config/save-location"),
            format!("{location}\n"),
        )?;
        for platform in [Platform::Gb, Platform::Gbc, Platform::Gba] {
            let cart = carts
                .iter()
                .find(|c| c.platform == platform && c.stem.to_lowercase().contains("zelda"))
                .or_else(|| carts.iter().find(|c| c.platform == platform))
                .ok_or("Missing console fixture")?;
            let progress = slot_store::progress_root(internal.path(), &cart.rom);
            assert_eq!(
                progress,
                if location == "game" {
                    portable.path()
                } else {
                    internal.path()
                }
            );
            let mut core = LibretroCore::open_with(
                Path::new(&args[3]),
                &root::bios_dir(system),
                &progress.join("Saves"),
            )?;
            core.set_option("mgba_skip_bios", "ON");
            core.set_option("mgba_frameskip", "disabled");
            core.load(&cart.rom)?;
            for _ in 0..120 {
                core.run_frame(ButtonMask::default());
            }
            let state = core.serialize()?;
            let sav = core.save_ram();
            persist::flush(
                &progress,
                platform,
                Core::Mgba,
                &cart.stem,
                Some(&state),
                sav.as_deref(),
            )?;
            assert_eq!(
                persist::read_resume_checked(&progress, platform, Core::Mgba, &cart.stem)?
                    .as_deref(),
                Some(state.as_slice())
            );
            if let Some(sav) = sav.as_deref() {
                assert_eq!(
                    persist::read_sav_checked(&progress, platform, &cart.stem)?.as_deref(),
                    Some(sav)
                );
                core.load_save_ram(sav)?;
            }
            let ring = StateRing::new(&progress, platform, Core::Mgba, &cart.stem);
            ring.push(&state, &[], "2026-10-22_12-00-00")?;
            assert_eq!(ring.list()?.len(), 1);
            for _ in 0..10 {
                core.run_frame(ButtonMask::default());
            }
            let expected = core.video_xrgb8888().to_vec();
            core.unserialize(&ring.read("2026-10-22_12-00-00")?.0)?;
            for _ in 0..10 {
                core.run_frame(ButtonMask::default());
            }
            assert_eq!(expected, core.video_xrgb8888());
            persist::eject_to(
                internal.path(),
                &progress,
                platform,
                Core::Mgba,
                &cart.stem,
                Some(&state),
                sav.as_deref(),
            )?;
            assert!(slot_store::read_slot_state(internal.path()).cart.is_none());
            assert!(!portable.path().join("Config").exists());
            println!(
                "PASS {location} {}: SRAM, resume, manual state and deterministic restore; {}",
                platform.dir_name(),
                progress.display()
            );
        }
    }
    portable.close()?;
    internal.close()?;
    println!("PASS: isolated eMMC/SD outputs removed; personal progress untouched");
    Ok(())
}
