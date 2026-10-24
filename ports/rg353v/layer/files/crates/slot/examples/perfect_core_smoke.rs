//! Read-only core compatibility probe. No sound sink or save writer is opened.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_retro::{ButtonMask, LibretroCore, RetroCore};
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    assert!(args.len() >= 3, "old-core new-core ROM [ROM...]");
    for rom in &args[2..] {
        let rom = std::path::Path::new(rom);
        let open = |library: &std::ffi::OsStr| -> Result<LibretroCore, Box<dyn std::error::Error>> {
            let mut core = LibretroCore::open(std::path::Path::new(library))?;
            for (key, value) in [
                ("mgba_skip_bios", "ON"),
                ("mgba_frameskip", "disabled"),
                ("mgba_color_correction", "OFF"),
                ("mgba_interframe_blending", "OFF"),
                ("mgba_gb_colors_preset", "0"),
                ("mgba_gb_colors", "Grayscale"),
            ] {
                core.set_option(key, value);
            }
            core.load(rom)?;
            Ok(core)
        };
        let (old_state, expected, size) = {
            let mut core = open(&args[0])?;
            for _ in 0..90 {
                core.run_frame(ButtonMask::default());
            }
            let state = core.serialize()?;
            for _ in 0..20 {
                core.run_frame(ButtonMask::default());
            }
            let frame = core.video_xrgb8888().to_vec();
            let size = state.len();
            (state, frame, size)
        };
        let (new_state, reverse_expected) = {
            let mut core = open(&args[1])?;
            core.unserialize(&old_state)?;
            for _ in 0..20 {
                core.run_frame(ButtonMask::default());
            }
            assert_eq!(
                core.video_xrgb8888(),
                expected,
                "old-to-new changed pixels for {}",
                rom.display()
            );
            let state = core.serialize()?;
            assert_eq!(state.len(), size);
            for _ in 0..20 {
                core.run_frame(ButtonMask::default());
            }
            (state, core.video_xrgb8888().to_vec())
        };
        let mut old = open(&args[0])?;
        old.unserialize(&new_state)?;
        assert_eq!(old.serialize()?.len(), size);
        for _ in 0..20 {
            old.run_frame(ButtonMask::default());
        }
        assert_eq!(
            old.video_xrgb8888(),
            reverse_expected,
            "new-to-old changed pixels for {}",
            rom.display()
        );
        println!("{}: old/new frames identical after restore; bidirectional states compatible ({size} bytes)",rom.display());
    }
    Ok(())
}
