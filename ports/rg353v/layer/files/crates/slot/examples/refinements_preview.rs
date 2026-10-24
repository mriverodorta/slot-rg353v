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
    u.open(QuickRow::OverlayStyle);
    u.tap(Btn::Right);
    u.open(QuickRow::Palette);
    u.shot("gb-palette-auto");
    u.tap(Btn::Right);
    u.shot("gb-palette-grayscale");
    u.open(QuickRow::GameA);
    u.tap(Btn::A);
    u.shot("controls-recording");
    u.tap(Btn::Menu);
    while u.f.app().quick_menu().is_some() {
        u.tap(Btn::B);
    }
    // The preview uses original test carts and a stub sink, never user content.
    let ring = slot_store::StateRing::new(
        root.path(),
        slot_store::Platform::Gba,
        slot_store::Core::Mgba,
        "Calibration",
    );
    ring.push(&[0; 8], b"png", "2026-10-21_00-00-00")?;
    u.tap(Btn::A);
    for _ in 0..180 {
        u.step(vec![]);
        if matches!(u.f.app().phase(), slot::app::Phase::Playing { .. }) {
            break;
        }
    }
    assert!(matches!(
        u.f.app().phase(),
        slot::app::Phase::Playing { .. }
    ));
    u.tap(Btn::Menu);
    u.tap(Btn::Menu);
    u.tap(Btn::Y);
    assert!(u.f.app().state_delete_prompt());
    u.shot("delete-state-confirmation");
    u.tap(Btn::B);
    assert!(!u.f.app().state_delete_prompt());
    assert_eq!(ring.list()?.len(), 1);
    println!("PASS palette, recording, deletion prompt and safe cancellation");
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
