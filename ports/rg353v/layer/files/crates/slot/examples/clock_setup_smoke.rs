//! Silent first-run wallpaper regression through the actual SDL/GLES renderer.
#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot::{audio::StubSink, frontend::Frontend};
    use slot_gfx::{Compositor, SdlSurface, Surface};
    use slot_power::SimPlatform;
    use slot_store::WallpaperPick;
    let root = tempfile::tempdir()?;
    let stamp = slot_store::days_from_civil(2026, 10, 20) * 86_400 + 12 * 3600;
    let mut surface = SdlSurface::new()?;
    let size = surface.window_size();
    assert_eq!(size, (640, 480));
    let mut compositor = Compositor::new(&surface)?;
    let mut frontend = Frontend::boot_with(
        Box::new(SimPlatform::at(root.path().into()).stopped_at(stamp)),
        Box::new(StubSink::new()),
    );
    frontend.upload_faces(&mut compositor);
    assert_eq!(
        frontend.app().resolved_wallpaper(),
        WallpaperPick::QuietCurrent
    );
    assert_eq!(frontend.app().picker().unwrap().offset_min(), -240);
    frontend.render(&mut compositor, size);
    type ReadPixels = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
    let read: ReadPixels = unsafe { std::mem::transmute(surface.proc_address("glReadPixels")) };
    let mut pixels = vec![0u8; 640 * 480 * 4];
    unsafe {
        read(0, 0, 640, 480, 0x1908, 0x1401, pixels.as_mut_ptr().cast());
    }
    let top: Vec<u8> = pixels
        .chunks_exact(640 * 4)
        .rev()
        .flatten()
        .copied()
        .collect();
    let pixel = |x: usize, y: usize| {
        let at = (y * 640 + x) * 4;
        &top[at..at + 3]
    };
    assert_ne!(
        pixel(320, 32),
        pixel(320, 360),
        "wallpaper was replaced by a flat backdrop"
    );
    assert!(
        pixel(30, 30)[2] > pixel(30, 30)[0],
        "Quiet Current is missing"
    );
    assert!(
        top.chunks_exact(4)
            .filter(|p| p[0] > 200 && p[1] > 200 && p[2] > 200)
            .count()
            > 100,
        "clock/legend text is missing"
    );
    assert!(
        !slot_store::read_slot_state(root.path()).clock_set,
        "rendering confirmed the clock"
    );
    assert!(
        std::fs::read_dir(root.path().join("Wallpapers"))?
            .next()
            .is_none(),
        "preview requires a content wallpaper"
    );
    if let Ok(directory) = std::env::var("SCRATCH_PNG_DIR") {
        let file = std::fs::File::create(std::path::Path::new(&directory).join("clock-setup.png"))?;
        let mut encoder = png::Encoder::new(file, 640, 480);
        encoder.set_color(png::ColorType::Rgba);
        encoder.write_header()?.write_image_data(&top)?;
    }
    surface.swap()?;
    println!("PASS first-run clock: bundled Quiet Current, UTC-04:00, readable fields/legend, still awaiting confirmation, no content files or audio");
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
