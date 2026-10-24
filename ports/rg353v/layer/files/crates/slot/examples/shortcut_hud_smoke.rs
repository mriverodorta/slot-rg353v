#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot::{audio::StubSink, frontend::Frontend};
    use slot_gfx::{Compositor, SdlSurface, Surface};
    use slot_input::{Btn, InputSource, Millis, RawEvent};
    use slot_power::SimPlatform;
    use slot_ui::Toast;
    use std::{
        path::PathBuf,
        time::{Duration, Instant},
    };
    struct Input(Vec<RawEvent>);
    impl InputSource for Input {
        fn poll(&mut self, _: Millis) -> Vec<RawEvent> {
            std::mem::take(&mut self.0)
        }
    }
    let root = PathBuf::from(std::env::var("SLOT_ROOT")?);
    let mut surface = SdlSurface::new()?;
    let size = surface.window_size();
    let mut compositor = Compositor::new(&surface)?;
    let mut frontend = Frontend::boot_with(
        Box::new(SimPlatform::at(root).stopped_at(1_790_000_000)),
        Box::new(StubSink::new()),
    );
    frontend.upload_boot_faces(&mut compositor);
    let start = Instant::now();
    let mut input = Input(Vec::new());
    type Read = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
    // The SDL context remains current across swaps.
    let read: Read =
        unsafe { std::mem::transmute(slot_gfx::Surface::proc_address(&surface, "glReadPixels")) };
    let mut step = |f: &mut Frontend,
                    c: &mut Compositor,
                    input: &mut Input|
     -> Result<(), Box<dyn std::error::Error>> {
        f.advance_at(input, start.elapsed().as_millis() as u64, 1.0 / 60.0);
        f.render(c, size);
        surface.swap()?;
        f.frame_presented();
        f.finish_boot_assets(c);
        std::thread::sleep(Duration::from_millis(16));
        Ok(())
    };
    for _ in 0..90 {
        step(&mut frontend, &mut compositor, &mut input)?;
    }
    assert!(frontend.app().perfect_overlay());
    assert!(matches!(
        frontend.app().phase(),
        slot::app::Phase::Playing { .. }
    ));
    let folder = PathBuf::from(std::env::var("SCRATCH_PNG_DIR")?);
    std::fs::create_dir_all(&folder)?;
    let before = frontend.app().screen_shader();
    // Feed real raw button chords through the gesture interpreter, not App::apply.
    for (button, name, toast) in [
        (Btn::A, "shader-next", Toast::ShaderShimmerlessLcd),
        (Btn::B, "shader-prev", Toast::ShaderShimmerless),
        (
            Btn::Y,
            "colour",
            if frontend.app().colour_correction() {
                Toast::ColourOff
            } else {
                Toast::ColourOn
            },
        ),
        (Btn::R1, "saved", Toast::StateSaved),
        (Btn::L1, "loaded", Toast::StateLoaded),
    ] {
        input.0 = vec![
            RawEvent::Down(Btn::Select),
            RawEvent::Down(button),
            RawEvent::Up(button),
            RawEvent::Up(Btn::Select),
        ];
        step(&mut frontend, &mut compositor, &mut input)?;
        assert_eq!(frontend.app().toast(), Some(toast), "{name}");
        frontend.render(&mut compositor, size);
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
        let mut encoder = png::Encoder::new(
            std::fs::File::create(folder.join(format!("{name}.png")))?,
            640,
            480,
        );
        encoder.set_color(png::ColorType::Rgba);
        encoder.write_header()?.write_image_data(&top)?;
        let mut scene = Vec::new();
        let mut hud = Vec::new();
        frontend.app().draw_panel(&mut scene, &mut hud);
        assert!(
            hud.iter().any(|d| matches!(d, slot_gfx::Draw::Tex { .. })),
            "{name}: bar exists but toast text was never uploaded on deferred startup"
        );
        println!(
            "PASS raw shortcut {name}, toast {toast:?}, shader {:?}, Perfect artwork retained",
            frontend.app().screen_shader()
        );
    }
    assert_eq!(frontend.app().screen_shader(), before);
    for visible in [false, true] {
        input.0 = vec![
            RawEvent::Down(Btn::Select),
            RawEvent::Down(Btn::X),
            RawEvent::Up(Btn::X),
            RawEvent::Up(Btn::Select),
        ];
        step(&mut frontend, &mut compositor, &mut input)?;
        assert_eq!(frontend.app().show_fps(), visible);
        frontend.render(&mut compositor, size);
        let mut pixels = vec![0u8; 640 * 480 * 4];
        unsafe {
            read(0, 0, 640, 480, 0x1908, 0x1401, pixels.as_mut_ptr().cast());
        }
        let white = (464..477)
            .flat_map(|y| (606..637).map(move |x| (x, y)))
            .filter(|&(x, y)| {
                let at = ((479 - y) * 640 + x) * 4;
                pixels[at..at + 3] == [255; 3]
            })
            .count();
        assert_eq!(
            white > 20,
            visible,
            "counter corner visibility: {white} white pixels"
        );
        assert_eq!(
            slot_store::read_slot_state(&PathBuf::from(std::env::var("SLOT_ROOT")?)).show_fps,
            visible
        );
    }
    println!("PASS raw Select+X off/on, native corner pixels and persistence");
    for _ in 0..100 {
        step(&mut frontend, &mut compositor, &mut input)?;
    }
    assert!(frontend.app().toast().is_none());
    let mut scene = Vec::new();
    let mut hud = Vec::new();
    frontend.app().draw_panel(&mut scene, &mut hud);
    assert!(hud.is_empty(), "notification did not fade away");
    println!("PASS notification text and plate fade together");
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
