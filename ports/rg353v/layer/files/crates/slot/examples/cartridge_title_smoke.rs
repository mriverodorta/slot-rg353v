//! Render cartridge titles through the real RG353V SDL/GLES panel path.
#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot::{audio::StubSink, frontend::Frontend};
    use slot_gfx::{Compositor, SdlSurface, Surface};
    use slot_input::{Btn, InputSource, Millis, RawEvent};
    use slot_power::SimPlatform;
    use slot_store::SlotState;
    use std::collections::VecDeque;
    struct Input(VecDeque<Vec<RawEvent>>);
    impl InputSource for Input {
        fn poll(&mut self, _: Millis) -> Vec<RawEvent> {
            self.0.pop_front().unwrap_or_default()
        }
    }
    let root = tempfile::tempdir()?;
    for dir in ["Config", "Games/GBA", "Games/GB"] {
        std::fs::create_dir_all(root.path().join(dir))?;
    }
    for stem in [
        "Alpha",
        "The Legend of Zelda - A Link to the Past and Four Swords (USA)",
        "Zzz",
    ] {
        let mut rom = vec![0u8; 1024];
        rom[3] = 0xea;
        rom[0xb2] = 0x96;
        std::fs::write(root.path().join(format!("Games/GBA/{stem}.gba")), rom)?;
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
    assert_eq!(size, (640, 480));
    let mut compositor = Compositor::new(&surface)?;
    let mut frontend = Frontend::boot_with(
        Box::new(SimPlatform::at(root.path().to_path_buf()).stopped_at(1_790_000_000)),
        Box::new(StubSink::new()),
    );
    frontend.upload_faces(&mut compositor);
    let mut input = Input(VecDeque::new());
    let frame = |f: &mut Frontend, c: &mut Compositor, i: &mut Input| {
        f.advance_at(i, 100, 0.016);
        f.render(c, size);
    };
    for _ in 0..220 {
        frame(&mut frontend, &mut compositor, &mut input);
    }
    for event in [RawEvent::Down(Btn::Right), RawEvent::Up(Btn::Right)] {
        input.0.push_back(vec![event]);
        frame(&mut frontend, &mut compositor, &mut input);
    }
    for _ in 0..70 {
        frame(&mut frontend, &mut compositor, &mut input);
    }
    type ReadPixels = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
    let read: ReadPixels = unsafe { std::mem::transmute(surface.proc_address("glReadPixels")) };
    let mut capture = |f: &mut Frontend,
                       c: &mut Compositor,
                       name: &str|
     -> Result<Vec<u8>, Box<dyn std::error::Error>> {
        f.render(c, size);
        let mut pixels = vec![0u8; 640 * 480 * 4];
        unsafe {
            read(0, 0, 640, 480, 0x1908, 0x1401, pixels.as_mut_ptr().cast());
        }
        let top = pixels
            .chunks_exact(640 * 4)
            .rev()
            .flatten()
            .copied()
            .collect::<Vec<_>>();
        if let Ok(dir) = std::env::var("SCRATCH_PNG_DIR") {
            std::fs::create_dir_all(&dir)?;
            let mut encoder = png::Encoder::new(
                std::fs::File::create(format!("{dir}/{name}.png"))?,
                640,
                480,
            );
            encoder.set_color(png::ColorType::Rgba);
            encoder.write_header()?.write_image_data(&top)?;
        }
        surface.swap()?;
        Ok(top)
    };
    let shown = capture(&mut frontend, &mut compositor, "title-visible")?;
    for _ in 0..170 {
        frame(&mut frontend, &mut compositor, &mut input);
    }
    let faded = capture(&mut frontend, &mut compositor, "title-faded")?;
    let changed = shown
        .chunks_exact(4)
        .zip(faded.chunks_exact(4))
        .enumerate()
        .filter_map(|(i, (a, b))| {
            (a[..3]
                .iter()
                .zip(&b[..3])
                .map(|(a, b)| (*a as i16 - *b as i16).abs())
                .sum::<i16>()
                > 30)
                .then_some((i % 640, i / 640))
        })
        .collect::<Vec<_>>();
    assert!(
        changed.len() > 100,
        "title did not appear and fade on panel"
    );
    let bounds = (
        changed.iter().map(|p| p.0).min().unwrap(),
        changed.iter().map(|p| p.1).min().unwrap(),
        changed.iter().map(|p| p.0).max().unwrap(),
        changed.iter().map(|p| p.1).max().unwrap(),
    );
    assert!(
        bounds.0 >= 20 && bounds.2 < 620,
        "title clipped at panel edge: {bounds:?}"
    );
    assert!(
        bounds.1 > 360 && bounds.3 < 440,
        "title overlaps cartridge or footer: {bounds:?}"
    );
    input.0.push_back(vec![
        RawEvent::Down(Btn::Left),
        RawEvent::Up(Btn::Left),
        RawEvent::Down(Btn::Right),
        RawEvent::Up(Btn::Right),
    ]);
    frame(&mut frontend, &mut compositor, &mut input);
    assert_eq!(
        frontend.app().slot_text().as_deref(),
        Some("The Legend of Zelda A Link to the Past and Four Swords")
    );
    assert!(
        !frontend.app().slot_text_needs_face(),
        "rapid back/forward left a missing title texture"
    );
    println!("Title appeared and faded; native 640x480 pixel bounds: {bounds:?}; rapid back/forward refreshed its texture");
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
