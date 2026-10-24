//! Real-core regression for the save-corruption class behind upstream #104.
#[cfg(all(target_os = "linux", feature = "rg353v"))]
mod real_flash {
    use slot::{
        audio::{AudioSink, StubSink},
        emu::{CoreState, EmuHandle, Speed},
        persist::{self, Snapshot},
    };
    use slot_retro::{ButtonMask, LibretroCore};
    use slot_store::{Core, Platform, RUN_AHEAD_MAX};
    use std::{
        path::{Path, PathBuf},
        time::{Duration, Instant},
    };
    const PANEL: Duration = Duration::from_micros(16760);
    fn library() -> PathBuf {
        PathBuf::from(std::env::var_os("SLOT_TEST_CORE_DIR").expect("set packaged core directory"))
            .join("mgba_libretro.so")
    }
    fn core() -> LibretroCore {
        let mut c = LibretroCore::open(&library()).unwrap();
        c.set_option("mgba_skip_bios", "ON");
        c.set_option("mgba_frameskip", "disabled");
        c
    }
    fn wait(test: impl Fn() -> bool) {
        let end = Instant::now() + Duration::from_secs(5);
        while !test() {
            assert!(Instant::now() < end, "worker did not settle");
            std::thread::sleep(Duration::from_millis(1));
        }
    }
    fn spawn(
        rom: &Path,
        ahead: u8,
        sav: Option<Vec<u8>>,
        resume: Option<Vec<u8>>,
    ) -> (EmuHandle, StubSink) {
        let mut sink = StubSink::new();
        sink.open(32768).unwrap();
        sink.start_drain();
        let emu = EmuHandle::spawn(Box::new(core()), rom.to_owned(), sink.ring(), sav, resume);
        emu.set_driven(true);
        emu.set_runahead(ahead);
        emu.set_speed(Speed::Normal);
        wait(|| emu.state() != CoreState::Loading);
        assert_eq!(emu.state(), CoreState::Ready);
        wait(|| emu.locked());
        (emu, sink)
    }
    fn tick(emu: &EmuHandle) {
        emu.tick(PANEL);
        assert!(emu.wait_frame(Duration::from_secs(3)));
    }
    fn good(bytes: &[u8], seed: &[u8]) {
        assert_eq!(bytes.len(), 131072);
        assert_eq!(bytes[0x123], seed[0x123], "wrote into wrong bank");
        assert_eq!(bytes[0x10123], 0x5a, "bank one write lost");
        for (i, (&actual, &old)) in bytes.iter().zip(seed).enumerate() {
            if i != 0x10123 {
                assert_eq!(actual, old, "save byte {i:#x} changed");
            }
        }
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
    #[ignore = "requires exact packaged ARM64 core; runs silently on host or RG353V"]
    fn flash128_runahead_matches_off_through_states_rewind_resume_and_fresh_save_load() {
        let t = tempfile::tempdir().unwrap();
        let rom = t.path().join("flash.gba");
        flash_rom(&rom);
        let mut seed = vec![0xff; 131072];
        for (i, b) in seed[..65536].iter_mut().enumerate() {
            *b = (i % 251) as u8;
        }
        let mut reference: Option<Vec<Vec<u8>>> = None;
        for ahead in 0..=RUN_AHEAD_MAX {
            let (emu, _sink) = spawn(&rom, ahead, Some(seed.clone()), None);
            let snapshot = emu.snapshot();
            let mut history = slot::rewind::Rewind::new(20 * 1024 * 1024);
            let mut states = Vec::new();
            // Save/restore both before and during writes; every presented frame must
            // preserve both banks; settled saves must match Run-Ahead Off.
            for n in 0..180 {
                emu.set_input(ButtonMask(if (30..90).contains(&n) || n >= 140 {
                    ButtonMask::A
                } else {
                    0
                }));
                tick(&emu);
                let state = snapshot.state().unwrap();
                history.push(&state);
                let sav = snapshot.save_ram().unwrap();
                states.push(sav);
                if n % 11 == 0 {
                    snapshot.load(state);
                    tick(&emu);
                }
            }
            let saved = snapshot.state().unwrap();
            let sav = snapshot.save_ram().unwrap();
            good(&sav, &seed);
            if let Some(ref expected) = reference {
                for (frame, (actual, want)) in states.iter().zip(expected).enumerate() {
                    // mGBA exports the backing save buffer. State loads mask SRAM
                    // and commit after clean frames; a speculative frame can move
                    // that commit one present earlier. This is not an authoritative
                    // byte difference: only the ROM's programmed byte may differ,
                    // and only before the quiet/writeback fence.
                    for (i, (&value, &original)) in actual.iter().zip(&seed).enumerate() {
                        if i == 0x10123 {
                            assert!(value == 0xff || value == 0x5a);
                        } else {
                            assert_eq!(value,original,"Run-Ahead {ahead} modified unrelated byte {i:#x} at present {frame}");
                        }
                    }
                    if frame >= 110 {
                        assert!(
                            actual == want,
                            "Run-Ahead {ahead} changed a settled save at present {frame}"
                        );
                        good(actual, &seed);
                    }
                }
            } else {
                reference = Some(states);
            }
            // Exercise actual worker rewind while writes are active, then allow a
            // write to commit again. Flash contents must never migrate into bank 0.
            emu.set_rewinding(true);
            wait(|| !emu.locked());
            let before = emu.published_count();
            wait(|| emu.published_count() >= before + 20);
            emu.set_rewinding(false);
            wait(|| emu.locked());
            emu.set_input(ButtonMask(ButtonMask::A));
            for _ in 0..30 {
                tick(&emu);
            }
            good(&snapshot.save_ram().unwrap(), &seed);
            // Restore several compressed rewind snapshots through the same worker.
            for _ in 0..12 {
                snapshot.load(history.pop().unwrap());
                tick(&emu);
                good(&snapshot.save_ram().unwrap(), &seed);
            }
            snapshot.load(saved);
            tick(&emu);
            // Use production persistence (same path used for suspend/eject), then
            // reopen in a new core with both resume and save, and save-only fresh boot.
            let sav = snapshot.save_ram().unwrap();
            let state = snapshot.state().unwrap();
            persist::flush(
                t.path(),
                Platform::Gba,
                Core::Mgba,
                "Flash",
                Some(&state),
                Some(&sav),
            )
            .unwrap();
            drop(snapshot);
            drop(emu);
            let disk = persist::read_sav_checked(t.path(), Platform::Gba, "Flash")
                .unwrap()
                .unwrap();
            good(&disk, &seed);
            for resume in [
                persist::read_resume_checked(t.path(), Platform::Gba, Core::Mgba, "Flash").unwrap(),
                None,
            ] {
                let (reopened, _sink) = spawn(&rom, ahead, Some(disk.clone()), resume);
                reopened.set_input(ButtonMask(ButtonMask::A));
                for _ in 0..60 {
                    tick(&reopened);
                }
                good(&reopened.snapshot().save_ram().unwrap(), &seed);
            }
            println!("PASS Run-Ahead {ahead}: all 131072 save bytes, manual states, worker rewind, compressed rewind, resume and fresh save loading");
        }
    }
}
