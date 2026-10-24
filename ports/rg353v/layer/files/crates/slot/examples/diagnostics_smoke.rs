//! Exercise full-panel wallpaper/settings and live filesystem refresh through SDL/GLES.
#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot::audio::StubSink;
    use slot::frontend::Frontend;
    use slot_gfx::{Compositor, SdlSurface, Surface};
    use slot_input::{Btn, InputSource, Millis, RawEvent};
    use slot_power::SimPlatform;
    use slot_store::{SlotState, WallpaperPick};
    use std::collections::VecDeque;
    struct Input(VecDeque<Vec<RawEvent>>, Millis);
    impl InputSource for Input {
        fn poll(&mut self, _: Millis) -> Vec<RawEvent> {
            self.0.pop_front().unwrap_or_default()
        }
    }
    fn tap(f: &mut Frontend, i: &mut Input, b: Btn) {
        for e in [RawEvent::Down(b), RawEvent::Up(b)] {
            i.0.push_back(vec![e]);
            i.1 += 20;
            let now = i.1;
            f.advance_at(i, now, 0.02);
        }
    }
    fn open(f: &mut Frontend, i: &mut Input, target: slot_ui::QuickRow) {
        for _ in 0..12 {
            tap(f, i, Btn::B);
        }
        tap(f, i, Btn::Menu);
        let mut chain = vec![target];
        while let Some(parent) = chain.last().unwrap().parent() {
            chain.push(parent);
        }
        for row in chain.into_iter().rev() {
            for _ in 0..slot_ui::QuickRow::ALL.len() {
                if f.app().quick_menu() == Some(row) {
                    break;
                }
                tap(f, i, Btn::Down);
            }
            assert_eq!(f.app().quick_menu(), Some(row), "menu navigation");
            if row != target {
                tap(f, i, Btn::A);
            }
        }
    }
    fn tick(f: &mut Frontend, i: &mut Input) {
        i.1 += 20;
        let now = i.1;
        f.advance_at(i, now, 0.02);
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
    let d = tempfile::tempdir()?;
    for dir in ["Config", "Games/GBA", "Wallpapers"] {
        std::fs::create_dir_all(d.path().join(dir))?;
    }
    let helper = d.path().join("System");
    std::fs::create_dir_all(&helper)?;
    std::fs::write(
        helper.join("slot-diagnostics-ui"),
        "print('protocol\\t1\\nslot\\tslot-diagnostics-1\\nos\\tos-20261016-wifi-probe1\\nram\\t1.6 GiB\\nfree\\t36.5 GiB\\nip\\t192.0.2.10\\ntemperature\\t48.9 C')",
    )?;
    std::env::set_var("SLOT_CORE_DIR", &helper);
    let image = d.path().join("Wallpapers/Test.png");
    let file = std::fs::File::create(&image)?;
    let mut e = png::Encoder::new(file, 2, 2);
    e.set_color(png::ColorType::Rgb);
    e.write_header()?
        .write_image_data(&[120, 80, 200].repeat(4))?;
    slot_store::write_slot_state(
        d.path(),
        &SlotState {
            clock_set: true,
            wallpaper: WallpaperPick::File("Test.png".into()),
            ..SlotState::default()
        },
    )?;
    let mut surface = SdlSurface::new()?;
    let size = surface.window_size();
    assert_eq!(size, (640, 480));
    let mut c = Compositor::new(&surface)?;
    let mut f = Frontend::boot_with(
        Box::new(SimPlatform::at(d.path().to_path_buf()).stopped_at(1_790_000_000)),
        Box::new(StubSink::new()),
    );
    f.upload_faces(&mut c);
    let mut input = Input(VecDeque::new(), 0);
    type ReadPixels = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
    let read: ReadPixels = unsafe { std::mem::transmute(surface.proc_address("glReadPixels")) };
    tap(&mut f, &mut input, Btn::Menu);
    let mut screenshot = |f: &mut Frontend, name: &str| -> Result<(), Box<dyn std::error::Error>> {
        f.render(&mut c, size);
        let mut pixels = vec![0u8; 640 * 480 * 4];
        unsafe {
            read(0, 0, 640, 480, 0x1908, 0x1401, pixels.as_mut_ptr().cast());
        }
        for (x, y) in [(2, 2), (2, 475), (630, 240)] {
            let p = (y * 640 + x) * 4;
            let px = &pixels[p..p + 3];
            assert!(
                px[2] > px[0] && px[0] > px[1] && px[2] > 30,
                "{name}: wallpaper absent at {x},{y}: {px:?}"
            );
            for (channel, expected) in [120i16, 80, 200].into_iter().enumerate() {
                assert!(
                    (px[channel] as i16 - expected).abs() <= 2,
                    "{name}: wallpaper was dimmed at {x},{y}: {px:?}"
                );
            }
        }
        if let Ok(dir) = std::env::var("SCRATCH_PNG_DIR") {
            let top = pixels
                .chunks_exact(640 * 4)
                .rev()
                .flatten()
                .copied()
                .collect::<Vec<_>>();
            let file = std::fs::File::create(format!("{dir}/content-{name}.png"))?;
            let mut e = png::Encoder::new(file, 640, 480);
            e.set_color(png::ColorType::Rgba);
            e.write_header()?.write_image_data(&top)?;
        }
        surface.swap()?;
        Ok(())
    };
    screenshot(&mut f, "main")?;
    open(&mut f, &mut input, slot_ui::QuickRow::Diagnostics);
    tap(&mut f, &mut input, Btn::A);
    for _ in 0..8 {
        tick(&mut f, &mut input);
    }
    assert_eq!(f.app().diagnostics_view()[0], "Diagnostics");
    screenshot(&mut f, "diagnostics")?;
    tap(&mut f, &mut input, Btn::A);
    assert_eq!(f.app().diagnostics_view()[0], "Versions");
    screenshot(&mut f, "versions")?;
    tap(&mut f, &mut input, Btn::B);
    tap(&mut f, &mut input, Btn::Down);
    tap(&mut f, &mut input, Btn::A);
    screenshot(&mut f, "services")?;
    tap(&mut f, &mut input, Btn::B);
    tap(&mut f, &mut input, Btn::Down);
    tap(&mut f, &mut input, Btn::A);
    assert_eq!(f.app().diagnostics_view()[0], "Storage Diagnostics");
    screenshot(&mut f, "storage")?;
    tap(&mut f, &mut input, Btn::B);
    tap(&mut f, &mut input, Btn::Down);
    tap(&mut f, &mut input, Btn::A);
    assert_eq!(f.app().diagnostics_view()[0], "Versions");
    screenshot(&mut f, "wrapped-versions")?;
    tap(&mut f, &mut input, Btn::B);
    tap(&mut f, &mut input, Btn::B);
    assert_eq!(f.app().quick_menu(), Some(slot_ui::QuickRow::Diagnostics));
    println!("Diagnostics/versions/services rendered with original wallpaper and panel legends");
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
