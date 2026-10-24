//! Silent, original homebrew probes against the exact packaged ARM64 cores.
#[cfg(all(target_os = "linux", feature = "rg353v"))]
mod probes {
    use slot_retro::{ButtonMask, LibretroCore, RetroCore};
    use slot_store::{Blending, Core, Platform};
    use std::{
        path::{Path, PathBuf},
        sync::Mutex,
    };
    static LOCK: Mutex<()> = Mutex::new(());
    fn library(which: Core) -> PathBuf {
        PathBuf::from(
            std::env::var_os("SLOT_TEST_CORE_DIR")
                .expect("set SLOT_TEST_CORE_DIR to the packaged cores"),
        )
        .join(format!("{}_libretro.so", which.as_str()))
    }
    fn open(which: Core, mode: Blending, rom: &Path) -> LibretroCore {
        let mut c = LibretroCore::open(&library(which)).unwrap();
        let (key, value) = slot::core::blend_option(which, mode);
        assert!(
            c.declared_options()
                .get(key)
                .is_some_and(|choices| choices.iter().any(|v| v == value)),
            "core does not declare {key}={value}"
        );
        c.set_option(key, value);
        if which == Core::Mgba {
            c.set_option("mgba_skip_bios", "ON");
            c.set_option("mgba_frameskip", "disabled");
        } else {
            c.set_option("gpsp_frameskip", "disabled");
        }
        c.load(rom).unwrap();
        c
    }
    fn gba(rom: &Path, delayed_sram: bool) {
        let mut b = vec![0u8; 32768];
        b[0..4].copy_from_slice(&0xea00002eu32.to_le_bytes());
        b[0xa0..0xac].copy_from_slice(b"SLOT PROBE\0\0");
        b[0xac..0xb0].copy_from_slice(b"SLTE");
        b[0xb2] = 0x96;
        b[0xbd] = b[0xa0..0xbd]
            .iter()
            .fold(0u8, |a, v| a.wrapping_sub(*v))
            .wrapping_sub(0x19);
        let code: Vec<u32> = if delayed_sram {
            vec![
                0xe59f4030, 0xe3a0200a, 0xe1d400b0, 0xe35000a0, 0x1afffffc, 0xe1d400b0, 0xe35000a0,
                0x0afffffc, 0xe2522001, 0x1afffff7, 0xe3a0140e, 0xe3a0005a, 0xe5c10000, 0xeafffffe,
                0x04000006,
            ]
        } else {
            vec![
                0xe3a00404, 0xe3a01c04, 0xe3811003, 0xe5801000, 0xe3a02406, 0xe3a03000, 0xe1d040b6,
                0xe35400a0, 0x1afffffc, 0xe223301f, 0xe1c230b0, 0xe1d040b6, 0xe35400a0, 0x0afffffc,
                0xeafffff6,
            ]
        };
        for (i, w) in code.into_iter().enumerate() {
            b[0xc0 + i * 4..0xc4 + i * 4].copy_from_slice(&w.to_le_bytes());
        }
        std::fs::write(rom, b).unwrap();
    }
    fn gb(rom: &Path, color: bool) {
        let mut b = vec![0u8; 32768];
        b[0x100..0x104].copy_from_slice(&[0, 0xc3, 0x50, 0x01]);
        b[0x104..0x108].copy_from_slice(&[0xce, 0xed, 0x66, 0x66]);
        b[0x134..0x13e].copy_from_slice(b"BLEND TEST");
        b[0x143] = if color { 0x80 } else { 0 };
        let mut code = vec![0x3e, 0x91, 0xe0, 0x40, 0x06, 0x00];
        let loop_at = code.len();
        code.extend_from_slice(&[0xf0, 0x44, 0xfe, 0x90, 0x20, 0xfa, 0x78, 0xee, 0xff, 0x47]);
        if color {
            code.extend_from_slice(&[
                0x3e, 0x80, 0xe0, 0x68, 0x78, 0xe0, 0x69, 0xe6, 0x7f, 0xe0, 0x69,
            ]);
        } else {
            code.extend_from_slice(&[0xe0, 0x47]);
        }
        code.extend_from_slice(&[0xf0, 0x44, 0xfe, 0x90, 0x28, 0xfa, 0x18]);
        let next = code.len() + 1;
        code.push((loop_at as isize - next as isize) as i8 as u8);
        b[0x150..0x150 + code.len()].copy_from_slice(&code);
        b[0x14d] = b[0x134..0x14d]
            .iter()
            .fold(0u8, |sum, x| sum.wrapping_sub(*x).wrapping_sub(1));
        std::fs::write(rom, b).unwrap();
    }
    fn run(c: &mut LibretroCore, count: usize) {
        for _ in 0..count {
            c.run_frame(ButtonMask::default());
            let _ = c.take_audio();
        }
    }
    #[test]
    #[ignore = "requires packaged ARM64 mGBA and gpSP"]
    fn packaged_modes_blend_original_gb_gbc_and_gba_frames() {
        let _guard = LOCK.lock().unwrap();
        let t = tempfile::tempdir().unwrap();
        for (platform, which) in [
            (Platform::Gb, Core::Mgba),
            (Platform::Gbc, Core::Mgba),
            (Platform::Gba, Core::Mgba),
            (Platform::Gba, Core::Gpsp),
        ] {
            let rom = t.path().join(format!(
                "probe.{}",
                platform.dir_name().to_ascii_lowercase()
            ));
            if platform == Platform::Gba {
                gba(&rom, false)
            } else {
                gb(&rom, platform == Platform::Gbc)
            }
            let mut outputs = Vec::new();
            for &mode in Blending::choices(which) {
                let mut c = open(which, mode, &rom);
                run(&mut c, 60);
                let previous = c.video_xrgb8888().to_vec();
                run(&mut c, 1);
                let image = c.video_xrgb8888().to_vec();
                if mode == Blending::Off {
                    assert_ne!(previous, image, "{platform:?} probe is not alternating");
                }
                outputs.push(image);
                eprintln!(
                    "{platform:?} {which:?} {mode:?}: {} pixels",
                    c.video_xrgb8888().len() / 4
                );
            }
            assert_ne!(
                outputs[0], outputs[1],
                "{platform:?} {which:?} Mix had no visible effect"
            );
            if outputs.len() == 3 {
                assert_ne!(
                    outputs[0], outputs[2],
                    "{platform:?} Ghosting had no visible effect"
                );
            }
        }
    }
    #[test]
    #[ignore = "requires packaged ARM64 mGBA"]
    fn paused_blending_preview_is_not_white_and_preserves_state_and_sram() {
        use slot::{
            audio::{AudioSink, StubSink},
            emu::{CoreState, EmuHandle, Speed},
            persist::Snapshot,
        };
        use std::time::{Duration, Instant};
        fn wait(f: impl Fn() -> bool) {
            let until = Instant::now() + Duration::from_secs(3);
            while !f() {
                assert!(Instant::now() < until, "emulator did not respond");
                std::thread::sleep(Duration::from_millis(2));
            }
        }
        let _guard = LOCK.lock().unwrap();
        let t = tempfile::tempdir().unwrap();
        let rom = t.path().join("picture.gba");
        gba(&rom, false);
        let mut c = LibretroCore::open(&library(Core::Mgba)).unwrap();
        c.set_option("mgba_skip_bios", "ON");
        c.set_option("mgba_color_correction", "OFF");
        c.set_option("mgba_frameskip", "disabled");
        let sink = StubSink::draining();
        let emu = EmuHandle::spawn(Box::new(c), rom, sink.ring(), None, None);
        emu.set_speed(Speed::Normal);
        wait(|| emu.state() == CoreState::Ready);
        std::thread::sleep(Duration::from_millis(100));
        emu.set_speed(Speed::Paused);
        wait(|| emu.observed_speed() == Speed::Paused);
        let snapshot = emu.snapshot();
        for mode in [Blending::Mix, Blending::Ghosting] {
            let before = snapshot.state();
            let before_sav = snapshot.save_ram();
            let (key, value) = slot::core::blend_option(Core::Mgba, mode);
            emu.set_option(key, value);
            let count = emu.published_count();
            emu.refresh_frames(mode.preview_frames());
            wait(|| emu.published_count() > count);
            let frame = emu.latest_frame().unwrap();
            let pixel = &frame[..3];
            assert_eq!(pixel[0], 0, "{mode:?}: blue retained white initialization");
            assert_eq!(pixel[1], 0, "{mode:?}: green retained white initialization");
            assert!(
                pixel[2] > 0 && pixel[2] < 255,
                "{mode:?}: expected blended red, got {pixel:?}"
            );
            assert_eq!(before, snapshot.state(), "preview changed state");
            assert_eq!(before_sav, snapshot.save_ram(), "preview changed save RAM");
        }
    }
    #[test]
    #[ignore = "requires packaged ARM64 mGBA"]
    fn chip_detection_shrinks_states_and_legacy_padding_still_loads() {
        let _guard = LOCK.lock().unwrap();
        let t = tempfile::tempdir().unwrap();
        let rom = t.path().join("delayed.gba");
        gba(&rom, true);
        let mut c = open(Core::Mgba, Blending::Off, &rom);
        let undetected = c.serialize().unwrap();
        run(&mut c, 30);
        let save = c.save_ram().unwrap();
        assert_eq!(save.len(), 32768, "fixture did not detect SRAM");
        assert_eq!(save[0], 0x5a);
        let exact = c.serialize().unwrap();
        assert!(
            exact.len() < undetected.len(),
            "cached initial padding was retained: {} -> {}",
            undetected.len(),
            exact.len()
        );
        assert_eq!(c.serialize().unwrap(), exact, "same-frame states differ");
        run(&mut c, 1);
        let expected = c.video_xrgb8888().to_vec();
        let mut legacy = exact.clone();
        legacy.resize(undetected.len(), 0);
        c.unserialize(&legacy).unwrap();
        run(&mut c, 1);
        assert_eq!(expected, c.video_xrgb8888());
        c.unserialize(&undetected).unwrap();
        assert_eq!(
            c.serialize().unwrap().len(),
            undetected.len(),
            "cached size did not grow when restoring an undetected save chip"
        );
        run(&mut c, 30);
        assert_eq!(
            c.serialize().unwrap().len(),
            exact.len(),
            "old undetected state did not re-detect its save chip"
        );
        let mut exact_history = slot::rewind::Rewind::new(20 * 1024 * 1024);
        let mut old_history = slot::rewind::Rewind::new(20 * 1024 * 1024);
        for _ in 0..120 {
            run(&mut c, 2);
            let state = c.serialize().unwrap();
            let mut padded = state.clone();
            padded.resize(undetected.len(), 0);
            exact_history.push(&state);
            old_history.push(&padded);
        }
        assert!(
            exact_history.bytes_used() < old_history.bytes_used(),
            "padding did not consume extra rewind memory"
        );
        eprintln!(
            "120 rewind snapshots: {} exact delta bytes vs {} padded",
            exact_history.bytes_used(),
            old_history.bytes_used()
        );
        assert_eq!(exact_history.pop().unwrap().len(), exact.len());
        assert_eq!(old_history.pop().unwrap().len(), undetected.len());
        eprintln!(
            "Detected SRAM: {} -> {} bytes ({} fewer per state)",
            undetected.len(),
            exact.len(),
            undetected.len() - exact.len()
        );
    }
}
