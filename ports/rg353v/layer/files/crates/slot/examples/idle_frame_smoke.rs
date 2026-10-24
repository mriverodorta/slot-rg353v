//! Real GLES proof that unchanged shelf reuse preserves pixels and interactive views.
#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot::{audio::StubSink, frontend::Frontend};
    use slot_gfx::{Compositor, SdlSurface, Surface};
    use slot_input::{Btn, InputSource, Millis, RawEvent};
    use slot_power::SimPlatform;
    use slot_store::SlotState;
    struct Input(Vec<RawEvent>);
    impl InputSource for Input {
        fn poll(&mut self, _: Millis) -> Vec<RawEvent> {
            std::mem::take(&mut self.0)
        }
    }
    let root = tempfile::tempdir()?;
    std::fs::create_dir_all(root.path().join("Games/GBA"))?;
    std::fs::create_dir_all(root.path().join("Config"))?;
    for name in ["First", "Second", "Third"] {
        std::fs::write(root.path().join(format!("Games/GBA/{name}.gba")), [0; 512])?;
    }
    slot_store::write_slot_state(
        root.path(),
        &SlotState {
            clock_set: true,
            ..SlotState::default()
        },
    )?;
    let mut surface = SdlSurface::new()?;
    let size = surface.window_size();
    let mut c = Compositor::new(&surface)?;
    let mut f = Frontend::boot_with(
        Box::new(SimPlatform::at(root.path().into()).stopped_at(1_790_000_000)),
        Box::new(StubSink::new()),
    );
    f.upload_faces(&mut c);
    let mut input = Input(Vec::new());
    let mut now = 0;
    let mut skips = 0;
    for _ in 0..240 {
        now += 17;
        f.advance_at(&mut input, now, 0.017);
        if f.render_shelf_if_changed(&mut c, size) {
            surface.swap()?;
        } else {
            surface.pump_events();
            skips += 1;
        }
    }
    assert!(skips > 100, "stationary shelf kept drawing: {skips} skips");
    type Read = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
    let read: Read = unsafe { std::mem::transmute(surface.proc_address("glReadPixels")) };
    // Force a fresh render, compare the exact physical-panel pixels against the old path.
    f.invalidate_idle_frame();
    assert!(f.render_shelf_if_changed(&mut c, size));
    let pixels = || {
        let mut out = vec![0u8; 640 * 480 * 4];
        unsafe { read(0, 0, 640, 480, 0x1908, 0x1401, out.as_mut_ptr().cast()) };
        out
    };
    let actual = pixels();
    f.render(&mut c, size);
    assert_eq!(pixels(), actual, "cached path changed pixels");
    assert!(f.render_shelf_if_changed(&mut c, size));
    assert!(!f.render_shelf_if_changed(&mut c, size));
    // An upload into an existing texture name must still invalidate scanout.
    let tex = c.create_texture(1, 1, &[255; 4]);
    assert!(f.render_shelf_if_changed(&mut c, size));
    assert!(!f.render_shelf_if_changed(&mut c, size));
    c.update_texture(tex, 1, 1, &[0; 4]);
    assert!(f.render_shelf_if_changed(&mut c, size));
    for button in [Btn::Right, Btn::Left, Btn::Menu, Btn::Down, Btn::B] {
        for event in [RawEvent::Down(button), RawEvent::Up(button)] {
            input.0.push(event);
            now += 17;
            f.advance_at(&mut input, now, 0.017);
        }
        assert!(
            f.render_shelf_if_changed(&mut c, size),
            "input {button:?} didn't redraw"
        );
        surface.swap()?;
    }
    f.account_suspend(std::time::Duration::from_secs(5));
    assert!(
        f.render_shelf_if_changed(&mut c, size),
        "wake didn't redraw"
    );
    println!("PASS idle shelf: {skips}/240 frames reused; exact pixels, textures, controls, menus and wake invalidation");
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
