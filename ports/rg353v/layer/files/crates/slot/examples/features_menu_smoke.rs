//! Silent visual regression of the RG353V menu hierarchy and Perfect-overlay pause UI.
#[cfg(feature = "rg353v")]
#[path = "../tests/common/mod.rs"]
mod common;
#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot::{audio::StubSink, frontend::Frontend};
    use slot_gfx::{Compositor, SdlSurface, Surface};
    use slot_input::{Btn, InputSource, Millis, RawEvent};
    use slot_power::SimPlatform;
    use slot_store::{write_slot_state, SlotState};
    use slot_ui::QuickRow;
    struct Input(Vec<RawEvent>);
    impl InputSource for Input {
        fn poll(&mut self, _: Millis) -> Vec<RawEvent> {
            std::mem::take(&mut self.0)
        }
    }
    struct Ui {
        f: Frontend,
        c: Compositor,
        s: SdlSurface,
        now: u64,
    }
    impl Ui {
        fn step(&mut self, events: Vec<RawEvent>) {
            self.now += 16;
            self.f.advance_at(&mut Input(events), self.now, 1.0 / 60.0);
            self.f.render(&mut self.c, (640, 480));
            self.s.swap().unwrap();
            self.f.frame_presented();
            self.f.finish_boot_assets(&mut self.c);
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
        fn tap(&mut self, b: Btn) {
            self.step(vec![RawEvent::Down(b)]);
            self.step(vec![RawEvent::Up(b)]);
        }
        fn open(&mut self, r: QuickRow) {
            while self.f.app().quick_menu().is_some() {
                self.tap(Btn::B);
            }
            for _ in 0..24 {
                self.step(vec![]);
            }
            self.tap(Btn::Menu);
            let mut chain = vec![r];
            while let Some(p) = chain.last().unwrap().parent() {
                chain.push(p);
            }
            for target in chain.into_iter().rev() {
                for _ in 0..QuickRow::ALL.len() {
                    if self.f.app().quick_menu() == Some(target) {
                        break;
                    }
                    self.tap(Btn::Down);
                }
                assert_eq!(self.f.app().quick_menu(), Some(target));
                if target != r {
                    self.tap(Btn::A);
                }
            }
        }
        fn shot(&mut self, name: &str) {
            self.step(vec![]);
            self.f.render(&mut self.c, (640, 480));
            type Read = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
            let read: Read = unsafe { std::mem::transmute(self.s.proc_address("glReadPixels")) };
            let mut px = vec![0u8; 640 * 480 * 4];
            unsafe {
                read(0, 0, 640, 480, 0x1908, 0x1401, px.as_mut_ptr().cast());
            }
            let top: Vec<u8> = px.chunks_exact(640 * 4).rev().flatten().copied().collect();
            assert!(
                top.chunks_exact(4)
                    .filter(|p| p[0] > 200 && p[1] > 200 && p[2] > 200)
                    .count()
                    > 100,
                "missing text: {name}"
            );
            let out = std::path::PathBuf::from(std::env::var("SCRATCH_PNG_DIR").unwrap());
            std::fs::create_dir_all(&out).unwrap();
            let mut enc = png::Encoder::new(
                std::fs::File::create(out.join(format!("{name}.png"))).unwrap(),
                640,
                480,
            );
            enc.set_color(png::ColorType::Rgba);
            enc.write_header().unwrap().write_image_data(&top).unwrap();
            println!("PASS native menu {name}");
        }
    }
    let root = common::tmp_root_with_real_carts(&["Calibration", "Pattern"]);
    write_slot_state(
        root.path(),
        &SlotState {
            clock_set: true,
            perfect_overlay: true,
            game_border: true,
            ..Default::default()
        },
    )?;
    let s = SdlSurface::new()?;
    let c = Compositor::new(&s)?;
    let f = Frontend::boot_with(
        Box::new(SimPlatform::at(root.path().into()).stopped_at(1790000000)),
        Box::new(StubSink::draining()),
    );
    let mut u = Ui { f, c, s, now: 0 };
    u.f.upload_faces(&mut u.c);
    for _ in 0..10 {
        u.step(vec![]);
    }
    u.open(QuickRow::FeatureStateBrowser);
    u.shot("features-top");
    u.open(QuickRow::FeatureInGameColor);
    u.shot("features-bottom");
    for row in QuickRow::PLAYER_FEATURES {
        u.open(row);
        u.tap(Btn::A);
        assert_eq!(u.f.app().quick_value(row), Some(slot_ui::QuickValue::Off));
    }
    u.open(QuickRow::FeatureInGameColor);
    u.shot("features-off-bottom");
    u.open(QuickRow::FeatureStateBrowser);
    u.shot("features-off-top");
    for row in QuickRow::PLAYER_FEATURES {
        u.open(row);
        u.tap(Btn::Right);
        assert_eq!(u.f.app().quick_value(row), Some(slot_ui::QuickValue::On));
    }
    for (r, n) in [
        (QuickRow::Appearance, "settings"),
        (QuickRow::Brightness, "screen"),
        (QuickRow::GbaShader, "gba-screen"),
        (QuickRow::GbcShader, "gbc-screen"),
        (QuickRow::GbShader, "gb-screen"),
        (QuickRow::EnhancedAudio, "audio"),
        (QuickRow::SchedutilGovernor, "cpu-governor"),
        (QuickRow::GameA, "controls"),
        (QuickRow::ScFps, "shortcuts"),
    ] {
        u.open(r);
        u.shot(n);
        if r == QuickRow::EnhancedAudio {
            assert_eq!(u.f.app().audio_rate(), 32768);
            u.tap(Btn::Right);
            assert_eq!(u.f.app().audio_rate(), 48000);
            u.shot("audio-enhanced-on");
            u.tap(Btn::Left);
            assert_eq!(u.f.app().audio_rate(), 32768);
            u.shot("audio-enhanced-off");
        }
    }
    u.tap(Btn::A);
    assert!(u.f.app().capturing());
    u.shot("binding-capture");
    u.tap(Btn::Menu);
    assert!(!u.f.app().capturing());
    u.tap(Btn::Y);
    u.shot("binding-reset");
    u.tap(Btn::B);
    u.open(QuickRow::ScSave);
    u.tap(Btn::A);
    u.step(vec![RawEvent::Down(Btn::Select)]);
    u.step(vec![RawEvent::Down(Btn::X)]);
    u.step(vec![RawEvent::Up(Btn::X), RawEvent::Up(Btn::Select)]);
    assert_eq!(u.f.app().clash(QuickRow::ScSave), Some(QuickRow::ScFps));
    u.shot("binding-conflict");
    u.tap(Btn::Y);
    u.tap(Btn::A);
    while u.f.app().quick_menu().is_some() {
        u.tap(Btn::B);
    }
    u.open(QuickRow::WallpaperDimming);
    u.tap(Btn::Right);
    u.tap(Btn::Right);
    u.shot("appearance-dimming");
    u.tap(Btn::Left);
    u.tap(Btn::Left);
    u.open(QuickRow::StorageTools);
    u.tap(Btn::A);
    for _ in 0..30 {
        u.step(vec![]);
    }
    assert_eq!(u.f.app().diagnostics_view()[0], "Storage");
    u.shot("storage");
    u.tap(Btn::A);
    u.shot("eject-confirmation");
    u.tap(Btn::A);
    for _ in 0..30 {
        u.step(vec![]);
    }
    assert!(u
        .f
        .app()
        .diagnostics_view()
        .iter()
        .any(|s| s.contains("Safe to remove")));
    u.shot("card-ejected");
    u.tap(Btn::A);
    for _ in 0..30 {
        u.step(vec![]);
    }
    u.shot("card-mounted-again");
    u.tap(Btn::Down);
    u.tap(Btn::Down);
    u.tap(Btn::A);
    u.tap(Btn::A);
    for _ in 0..30 {
        u.step(vec![]);
    }
    u.shot("storage-tools");
    u.tap(Btn::Down);
    u.tap(Btn::Down);
    u.tap(Btn::A);
    u.shot("repair-confirmation");
    u.tap(Btn::B);
    u.tap(Btn::B);
    u.tap(Btn::B);
    u.open(QuickRow::Diagnostics);
    u.tap(Btn::A);
    u.tap(Btn::Down);
    u.tap(Btn::Down);
    u.tap(Btn::A);
    for _ in 0..30 {
        u.step(vec![]);
    }
    u.shot("storage-diagnostics");
    u.tap(Btn::B);
    u.tap(Btn::B);
    while u.f.app().quick_menu().is_some() {
        u.tap(Btn::B);
    }
    u.tap(Btn::Y);
    for _ in 0..5 {
        u.tap(Btn::R1);
        if u.f.app().shelf_platform_name() == Some("Favorites") {
            break;
        }
    }
    assert_eq!(u.f.app().shelf_platform_name(), Some("Favorites"));
    u.shot("favorites");
    u.tap(Btn::A);
    for _ in 0..100 {
        u.step(vec![]);
    }
    assert!(matches!(
        u.f.app().phase(),
        slot::app::Phase::Playing { .. }
    ));
    u.tap(Btn::Menu);
    assert_eq!(u.f.app().in_game_menu(), Some(QuickRow::Resume));
    for _ in 0..15 {
        u.step(vec![]);
    }
    u.shot("pause");
    u.tap(Btn::Down);
    u.tap(Btn::Down);
    u.tap(Btn::A);
    u.shot("pause-settings");
    u.tap(Btn::A);
    u.shot("pause-screen");
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
