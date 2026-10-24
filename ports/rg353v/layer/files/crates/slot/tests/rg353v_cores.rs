#[cfg(all(target_os = "linux", feature = "rg353v"))]
mod common;

#[cfg(all(target_os = "linux", feature = "rg353v"))]
mod linux {
    use super::common;

    use slot_retro::{ButtonMask, LibretroCore, RetroCore};

    fn library(name: &str) -> std::path::PathBuf {
        std::env::var_os("SLOT_TEST_CORE_DIR")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| common::repo_root().join("vendor/rg353v"))
            .join(format!("{name}_libretro.so"))
    }

    #[test]
    #[ignore = "requires built ARM64 mGBA; run scripts/test-rg353v-cores.sh"]
    fn mbc2_fresh_boot_keeps_save_banks_valid_after_deferred_setup() {
        let _guard = common::core_lock();
        let root = tempfile::tempdir().unwrap();
        let rom = root.path().join("MBC2 probe.gb");
        let mut bytes = vec![0; 32768];
        bytes[0x100..0x104].copy_from_slice(&[0, 0xc3, 0x50, 0x01]);
        bytes[0x104..0x108].copy_from_slice(&[0xce, 0xed, 0x66, 0x66]); // core format signature
        bytes[0x134..0x13e].copy_from_slice(b"MBC2 PROBE");
        bytes[0x147] = 0x06; // MBC2 with battery, 512 packed four-bit cells.
        let program = [
            0x3e, 0x0a, 0xea, 0x00, 0x00, // enable cartridge RAM
            0x3e, 0x05, 0xea, 0x00, 0xa0, // even cell
            0x3e, 0x06, 0xea, 0x01, 0xa0, // odd cell
            0xfa, 0x00, 0xa0, 0xe6, 0x0f, 0xea, 0x02, 0xa0, 0xfa, 0x01, 0xa0, 0xe6, 0x0f, 0xea,
            0x03, 0xa0, 0x18, 0xfe,
        ];
        bytes[0x150..0x150 + program.len()].copy_from_slice(&program);
        bytes[0x14d] = bytes[0x134..0x14d]
            .iter()
            .fold(0u8, |sum, byte| sum.wrapping_sub(*byte).wrapping_sub(1));
        std::fs::write(&rom, bytes).unwrap();
        let library = library("mgba");
        for _ in 0..3 {
            let mut core = LibretroCore::open(&library).unwrap();
            core.set_option("mgba_skip_bios", "ON");
            core.load(&rom).unwrap();
            core.load_save_ram(&[0xff; 256]).unwrap();
            let initial_state = core.serialize().unwrap();
            for _ in 0..120 {
                core.run_frame(ButtonMask::default());
            }
            let sav = core.save_ram().unwrap();
            assert_eq!(sav.len(), 256);
            assert_eq!(&sav[..2], &[0x65, 0x65], "MBC2 read/write cells disagree");
            core.unserialize(&initial_state).unwrap();
            // State restore masks SRAM. Replay the writes, then wait for
            // dirty-save writeback/unmask before reading the public save RAM.
            for _ in 0..1200 {
                core.run_frame(ButtonMask::default());
            }
            assert_eq!(&core.save_ram().unwrap()[..2], &[0x65, 0x65]);
        }
    }

    #[test]
    #[ignore = "requires scripts/build-rg353v-cores.sh; run scripts/test-rg353v-cores.sh"]
    fn packaged_arm64_cores_run_a_homebrew_probe_and_restore_state() {
        let _guard = common::core_lock();
        let root = common::tmp_root_with_real_carts(&["Probe"]);
        let rom = root.path().join("Games/GBA/Probe.gba");
        for name in ["mgba", "gpsp"] {
            let library = library(name);
            assert!(
                library.is_file(),
                "build the required core: {}",
                library.display()
            );
            let mut core = LibretroCore::open(&library).expect("open built ARM64 core");
            if name == "mgba" {
                core.set_option("mgba_skip_bios", "ON");
                core.set_option("mgba_frameskip", "disabled");
            }
            core.load(&rom)
                .expect("load original homebrew test program");
            for _ in 0..90 {
                core.run_frame(ButtonMask::default());
            }
            assert_eq!(
                core.video_xrgb8888().len(),
                240 * 160 * 4,
                "{name} did not produce a GBA frame"
            );
            let state = core.serialize().expect("serialize running core");
            assert!(!state.is_empty());
            for _ in 0..20 {
                core.run_frame(ButtonMask::default());
            }
            let expected = core.video_xrgb8888().to_vec();
            core.unserialize(&state).expect("restore running core");
            for _ in 0..20 {
                core.run_frame(ButtonMask::default());
            }
            assert_eq!(
                core.video_xrgb8888(),
                expected,
                "{name} did not reproduce the frame after restoring state"
            );
        }
    }
    #[test]
    #[ignore = "requires built ARM64 mGBA; run scripts/test-rg353v-cores.sh"]
    fn perfect_dmg_palette_renders_all_four_pack_colors_and_restores_states() {
        let _guard = common::core_lock();
        let root = tempfile::tempdir().unwrap();
        let rom = root.path().join("Palette probe.gb");
        let mut bytes = vec![0; 32768];
        bytes[0x100..0x104].copy_from_slice(&[0, 0xc3, 0x50, 0x01]);
        bytes[0x104..0x108].copy_from_slice(&[0xce, 0xed, 0x66, 0x66]);
        bytes[0x134..0x13e].copy_from_slice(b"PERFECT GB");
        let program = [
            0xf3, 0xaf, 0xe0, 0x40, // LCD off
            0x21, 0x00, 0x80, 0x06, 0x08, // tile 0, eight rows
            0x3e, 0x55, 0x22, 0x3e, 0x33, 0x22, 0x05, 0x20, 0xf7, 0x3e, 0xe4, 0xe0,
            0x47, // identity BGP
            0x3e, 0x91, 0xe0, 0x40, 0x18, 0xfe,
        ];
        bytes[0x150..0x150 + program.len()].copy_from_slice(&program);
        bytes[0x14d] = bytes[0x134..0x14d]
            .iter()
            .fold(0u8, |sum, byte| sum.wrapping_sub(*byte).wrapping_sub(1));
        std::fs::write(&rom, bytes).unwrap();
        let library = library("mgba");
        let mut core = LibretroCore::open(&library).unwrap();
        core.set_option("mgba_skip_bios", "ON");
        core.set_option("mgba_frameskip", "disabled");
        core.set_option("mgba_gb_model", "Game Boy");
        core.set_option("mgba_gb_colors_preset", "0");
        core.set_option("mgba_gb_colors", "Perfect DMG");
        core.set_option("mgba_color_correction", "OFF");
        core.load(&rom).unwrap();
        for _ in 0..60 {
            core.run_frame(ButtonMask::default());
        }
        fn game_colors(frame: &[u8]) -> std::collections::BTreeSet<[u8; 3]> {
            frame
                .chunks_exact(240 * 4)
                .skip(8)
                .take(144)
                .flat_map(|row| row[40 * 4..200 * 4].chunks_exact(4))
                .map(|p| [p[2], p[1], p[0]])
                .collect()
        }
        let colors = game_colors(core.video_xrgb8888());
        let palette = [0x75da76u32, 0x289f8c, 0x066d8c, 0x003e85];
        assert_eq!(colors.len(), 4, "{colors:?}");
        for color in palette {
            let rgb = [
                ((color >> 16) & 255) as u8,
                ((color >> 8) & 255) as u8,
                (color & 255) as u8,
            ];
            assert!(
                colors
                    .iter()
                    .any(|got| got.iter().zip(rgb).all(|(a, b)| a.abs_diff(b) <= 7)),
                "missing {rgb:?}: {colors:?}"
            );
        }
        let state = core.serialize().unwrap();
        core.unserialize(&state).unwrap();
        for _ in 0..5 {
            core.run_frame(ButtonMask::default());
        }
        let restored = game_colors(core.video_xrgb8888());
        assert_eq!(restored, colors);
        println!("Perfect DMG pack RGB555 palette and state restore passed: {colors:?}");
    }
    fn flash_rom(path: &std::path::Path) {
        let mut rom = vec![0; 32768];
        rom[..4].copy_from_slice(&0xea00002eu32.to_le_bytes());
        rom[0xa0..0xac].copy_from_slice(b"FLASH PROBE ");
        rom[0xac..0xb0].copy_from_slice(b"SLTE");
        rom[0xb2] = 0x96;
        rom[0xbd] = rom[0xa0..0xbd]
            .iter()
            .fold(0u8, |n, v| n.wrapping_sub(*v))
            .wrapping_sub(0x19);
        // Original ARMv4T program: select bank 1 once, then program its byte
        // 0x123 each VBlank while A is held. Restoring a state must retain that selected bank.
        let code: [u32; 37] = [
            0xe59f4078, 0xe59f5078, 0xe3a0640e, 0xe3a000aa, 0xe5c40000, 0xe3a00055, 0xe5c50000,
            0xe3a000b0, 0xe5c40000, 0xe3a00001, 0xe5c60000, 0xe59f7054, 0xe59f8054, 0xe59fa054,
            0xe1d700b0, 0xe35000a0, 0x1afffffc, 0xe1da00b0, 0xe3100001, 0x1a000007, 0xe3a000aa,
            0xe5c40000, 0xe3a00055, 0xe5c50000, 0xe3a000a0, 0xe5c40000, 0xe3a0005a, 0xe5c80000,
            0xe1d700b0, 0xe35000a0, 0x0afffffc, 0xeaffffed, 0x0e005555, 0x0e002aaa, 0x04000006,
            0x0e000123, 0x04000130,
        ];
        for (i, word) in code.iter().enumerate() {
            rom[0xc0 + i * 4..0xc4 + i * 4].copy_from_slice(&word.to_le_bytes());
        }
        rom[0x1000..0x100c].copy_from_slice(b"FLASH1M_V103");
        std::fs::write(path, rom).unwrap();
    }

    #[test]
    #[ignore = "requires built ARM64 mGBA"]
    fn flash_bank_one_survives_repeated_state_restore() {
        let _guard = common::core_lock();
        let root = tempfile::tempdir().unwrap();
        let rom = root.path().join("flash.gba");
        flash_rom(&rom);
        let library = std::env::var_os("SLOT_TEST_MGBA")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| library("mgba"));
        let run = |reload| {
            let mut core = LibretroCore::open(&library).unwrap();
            core.set_option("mgba_skip_bios", "ON");
            core.load(&rom).unwrap();
            for _ in 0..120 {
                core.run_frame(ButtonMask(ButtonMask::A));
                let _ = core.take_audio();
                if reload {
                    let state = core.serialize().unwrap();
                    core.unserialize(&state).unwrap();
                }
            }
            // Releasing A stops writes and lets the mask commit. Program
            // again afterward: the bank must survive both mask and unmask.
            for _ in 0..1200 {
                core.run_frame(ButtonMask::default());
                let _ = core.take_audio();
            }
            for _ in 0..120 {
                core.run_frame(ButtonMask(ButtonMask::A));
                let _ = core.take_audio();
            }
            for _ in 0..1200 {
                core.run_frame(ButtonMask::default());
                let _ = core.take_audio();
            }
            core.save_ram().unwrap()
        };
        let straight = run(false);
        assert_eq!(straight.len(), 128 * 1024);
        assert_eq!(
            straight[0x123], 0xff,
            "program touched the wrong flash bank"
        );
        assert_eq!(straight[0x10123], 0x5a, "fixture never programmed bank one");
        let reloaded = run(true);
        let different: Vec<_> = reloaded
            .iter()
            .zip(&straight)
            .enumerate()
            .filter(|(_, (a, b))| a != b)
            .map(|(i, (a, b))| (i, *a, *b))
            .collect();
        assert!(
            different.is_empty(),
            "state restores changed flash bytes: {different:?}"
        );
    }

    #[test]
    #[ignore = "requires old and updated ARM64 cores"]
    fn existing_states_and_battery_saves_load_in_updated_cores_with_audio() {
        let _guard = common::core_lock();
        let Some(baseline) = std::env::var_os("SLOT_BASELINE_CORE_DIR") else {
            eprintln!("SLOT_BASELINE_CORE_DIR is required for the old-core compatibility check");
            return;
        };
        let baseline = std::path::PathBuf::from(baseline);
        let root = common::tmp_root_with_real_carts(&["Probe"]);
        let rom = root.path().join("Games/GBA/Probe.gba");
        for name in ["mgba", "gpsp"] {
            let mut old =
                LibretroCore::open(&baseline.join(format!("{name}_libretro.so"))).unwrap();
            old.set_option("mgba_skip_bios", "ON");
            old.load(&rom).unwrap();
            for _ in 0..90 {
                old.run_frame(ButtonMask::default());
                let _ = old.take_audio();
            }
            let state = old.serialize().unwrap();
            let saved = old.save_ram().unwrap();
            for _ in 0..20 {
                old.run_frame(ButtonMask::default());
            }
            let expected = old.video_xrgb8888().to_vec();
            drop(old);
            let library = library(name);
            let mut new = LibretroCore::open(&library).unwrap();
            new.set_option("mgba_skip_bios", "ON");
            new.load(&rom).unwrap();
            for _ in 0..90 {
                new.run_frame(ButtonMask::default());
                let _ = new.take_audio();
            }
            new.load_save_ram(&saved).unwrap();
            assert_eq!(new.save_ram().unwrap(), saved);
            new.unserialize(&state).unwrap();
            for _ in 0..20 {
                new.run_frame(ButtonMask::default());
                let _ = new.take_audio();
            }
            assert_eq!(
                new.video_xrgb8888(),
                expected,
                "{name}: old state replay changed"
            );
            // Repeated capture exercises the cached serialize size. A padded
            // state still loads and returns the same next frame.
            let state = new.serialize().unwrap();
            assert_eq!(new.serialize().unwrap(), state);
            new.run_frame(ButtonMask::default());
            let next = new.video_xrgb8888().to_vec();
            let mut padded = state;
            if name == "mgba" {
                padded.extend_from_slice(&[0; 4096]);
            }
            new.unserialize(&padded).unwrap();
            new.run_frame(ButtonMask::default());
            assert_eq!(new.video_xrgb8888(), next);
            let _ = new.take_audio();
            let mut samples = 0;
            for _ in 0..120 {
                new.run_frame(ButtonMask::default());
                samples += new.take_audio().len();
            }
            let expected_samples = new.av_info().sample_rate * 2.0 * 120.0 / new.av_info().fps;
            assert!(
                (samples as f64 - expected_samples).abs() < expected_samples * 0.02,
                "{name}: {samples} audio samples, expected {expected_samples}"
            );
        }
    }
    #[test]
    #[ignore = "requires built ARM64 mGBA"]
    fn asynchronous_core_open_launches_ejects_and_resumes_without_real_audio() {
        use slot::{app::Phase, audio::StubSink, session::Session};
        use slot_input::Action;
        use std::time::{Duration, Instant};
        let _guard = common::core_lock();
        let root = common::tmp_root_with_real_carts(&["Probe", "Second"]);
        common::clocked(root.path());
        std::fs::copy(library("mgba"), root.path().join("System/mgba_libretro.so")).unwrap();
        let sink = StubSink::draining();
        let mut session = Session::boot_with(root.path().into(), Box::new(sink));
        let pump = |s: &mut Session, ready: &dyn Fn(&Session) -> bool| {
            let deadline = Instant::now() + Duration::from_secs(5);
            while !ready(s) {
                assert!(
                    Instant::now() < deadline,
                    "core never settled: {:?}",
                    s.app().phase()
                );
                s.update(1.0 / 60.0);
                std::thread::sleep(Duration::from_millis(1));
            }
        };
        for _ in 0..2 {
            session.app_mut().apply(Action::Insert);
            pump(&mut session, &|s| {
                matches!(s.app().phase(), Phase::Playing { .. }) && s.frame_ready()
            });
            assert!(
                session
                    .emu()
                    .unwrap()
                    .request_state()
                    .recv_timeout(Duration::from_secs(2))
                    .unwrap()
                    .len()
                    > 100_000,
                "mock core used in the launch test"
            );
            session.app_mut().apply(Action::SaveState);
            session.app_mut().apply(Action::LoadState);
            session.app_mut().apply(Action::Eject);
            pump(&mut session, &|s| {
                matches!(s.app().phase(), Phase::Shelf) && !s.has_core()
            });
        }
        assert!(root
            .path()
            .join("States/GBA/mgba/Probe/resume.state")
            .is_file());
    }
    #[test]
    #[ignore = "requires updated ARM64 mGBA"]
    fn selected_dmg_palette_changes_pixels_and_survives_an_older_state() {
        let _guard = common::core_lock();
        let root = tempfile::tempdir().unwrap();
        let rom = root.path().join("palette.gb");
        let mut bytes = vec![0; 32768];
        bytes[0x100..0x104].copy_from_slice(&[0, 0xc3, 0x50, 0x01]);
        bytes[0x104..0x108].copy_from_slice(&[0xce, 0xed, 0x66, 0x66]);
        bytes[0x134..0x13e].copy_from_slice(b"PALETTE GB");
        let program = [
            0xf3, 0xaf, 0xe0, 0x40, 0x21, 0x00, 0x80, 0x06, 0x08, 0x3e, 0x55, 0x22, 0x3e, 0x33,
            0x22, 0x05, 0x20, 0xf7, 0x3e, 0xe4, 0xe0, 0x47, 0x3e, 0x91, 0xe0, 0x40, 0x18, 0xfe,
        ];
        bytes[0x150..0x150 + program.len()].copy_from_slice(&program);
        bytes[0x14d] = bytes[0x134..0x14d]
            .iter()
            .fold(0u8, |s, b| s.wrapping_sub(*b).wrapping_sub(1));
        std::fs::write(&rom, bytes).unwrap();
        let mut core = LibretroCore::open(&library("mgba")).unwrap();
        for (k, v) in [
            ("mgba_skip_bios", "ON"),
            ("mgba_frameskip", "disabled"),
            ("mgba_gb_model", "Game Boy"),
            ("mgba_gb_colors_preset", "0"),
            ("mgba_gb_colors", "Grayscale"),
            ("mgba_color_correction", "OFF"),
        ] {
            core.set_option(k, v);
        }
        core.load(&rom).unwrap();
        for _ in 0..60 {
            core.run_frame(ButtonMask::default());
            let _ = core.take_audio();
        }
        let old = core.serialize().unwrap();
        let before = core.video_xrgb8888().to_vec();
        core.set_option("mgba_gb_colors", "Perfect DMG");
        for _ in 0..5 {
            core.run_frame(ButtonMask::default());
            let _ = core.take_audio();
        }
        let changed = core.video_xrgb8888().to_vec();
        let live = before != changed;
        core.unserialize(&old).unwrap();
        for _ in 0..5 {
            core.run_frame(ButtonMask::default());
            let _ = core.take_audio();
        }
        let survives = core.video_xrgb8888() == changed;
        println!("live_palette_changes_pixels={live}; selected_palette_survives_state={survives}");
        assert!(
            live,
            "selected palette name changes, but live DMG pixels keep the previous palette"
        );
        assert!(survives,"loading an older state restores old DMG colours despite the currently selected palette");
    }
    #[test]
    #[ignore = "requires exact packaged ARM64 mGBA"]
    fn auto_and_grayscale_change_live_without_breaking_perfect_or_state_palette() {
        let _guard = common::core_lock();
        let root = tempfile::tempdir().unwrap();
        let rom = root.path().join("Palette probe.gb");
        let mut bytes = vec![0; 32768];
        bytes[0x100..0x104].copy_from_slice(&[0, 0xc3, 0x50, 0x01]);
        bytes[0x104..0x108].copy_from_slice(&[0xce, 0xed, 0x66, 0x66]);
        bytes[0x134..0x13e].copy_from_slice(b"PERFECT GB");
        let program = [
            0xf3, 0xaf, 0xe0, 0x40, // LCD off
            0x21, 0x00, 0x80, 0x06, 0x08, // tile 0, eight rows
            0x3e, 0x55, 0x22, 0x3e, 0x33, 0x22, 0x05, 0x20, 0xf7, 0x3e, 0xe4, 0xe0,
            0x47, // identity BGP
            0x3e, 0x91, 0xe0, 0x40, 0x18, 0xfe,
        ];
        bytes[0x150..0x150 + program.len()].copy_from_slice(&program);
        bytes[0x14d] = bytes[0x134..0x14d]
            .iter()
            .fold(0u8, |sum, byte| sum.wrapping_sub(*byte).wrapping_sub(1));
        std::fs::write(&rom, bytes).unwrap();

        let mut core = LibretroCore::open(&library("mgba")).unwrap();
        core.set_option("mgba_skip_bios", "ON");
        core.set_option("mgba_gb_model", "Game Boy");
        core.set_option("mgba_gb_colors_preset", "0");
        core.set_option("mgba_color_correction", "OFF");
        core.set_option("mgba_gb_colors", "Auto");
        core.load(&rom).unwrap();
        for _ in 0..30 {
            core.run_frame(ButtonMask::default());
            let _ = core.take_audio();
        }
        let old = core.serialize().unwrap();
        for mode in ["Grayscale", "DMG Green", "Perfect DMG", "Auto"] {
            core.set_option("mgba_gb_colors", mode);
            for _ in 0..4 {
                core.run_frame(ButtonMask::default());
                let _ = core.take_audio();
            }
            let before = core.video_xrgb8888().to_vec();
            let colors = before
                .chunks_exact(240 * 4)
                .skip(8)
                .take(144)
                .flat_map(|row| row[40 * 4..200 * 4].chunks_exact(4))
                .map(|p| [p[2], p[1], p[0]])
                .collect::<std::collections::BTreeSet<_>>();
            assert!(colors.len() >= 3, "{mode}: missing tile colors");
            if mode == "Grayscale" {
                for pixel in before.chunks_exact(4) {
                    assert_eq!(pixel[0] >> 3, pixel[1] >> 3);
                    assert_eq!(pixel[1] >> 3, pixel[2] >> 3);
                }
            }
            core.unserialize(&old).unwrap();
            for _ in 0..4 {
                core.run_frame(ButtonMask::default());
                let _ = core.take_audio();
            }
            assert_eq!(
                core.video_xrgb8888(),
                before,
                "state changed the selected {mode} palette"
            );
            println!("PASS live {mode} and state palette persistence");
        }
    }
}
