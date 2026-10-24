//! Run with `cargo run -p slot-gfx --no-default-features --features sdl --example sdl_smoke`.
//! Exercises real context creation, shader compilation, presentation and cleanup.
#[cfg(feature = "sdl")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{Compositor, Draw, SdlSurface, Surface, OUT_H, OUT_W};
    let mut surface = SdlSurface::new()?;
    let mut compositor = Compositor::new(&surface)?;
    let size = surface.window_size();
    for _ in 0..3 {
        compositor.begin_frame();
        compositor.draw_list(&[Draw::Rect {
            x: 0.0,
            y: 0.0,
            w: OUT_W as f32,
            h: OUT_H as f32,
            colour: [1.0, 0.0, 0.0, 1.0],
        }]);
        let pixels = compositor.read_frame();
        let center = ((OUT_H as usize / 2) * OUT_W as usize + OUT_W as usize / 2) * 4;
        assert_eq!(
            &pixels[center..center + 4],
            &[255, 0, 0, 255],
            "the GLES renderer did not draw the expected pixel"
        );
        compositor.end_frame(size);
        surface.swap()?;
    }
    // The SDL shelf does not compile the game shader. Its first use must still
    // honor settings made before compilation and render the correct channels.
    compositor.set_screen_effect(slot_gfx::ScreenEffect::None);
    let game = [255, 0, 0, 255].repeat((slot_gfx::SRC_W * slot_gfx::SRC_H) as usize);
    compositor.upload_game(&game);
    compositor.begin_frame();
    compositor.draw_list(&[Draw::Game]);
    let pixels = compositor.read_frame();
    let center = ((OUT_H as usize / 2) * OUT_W as usize + OUT_W as usize / 2) * 4;
    assert_eq!(&pixels[center..center + 4], &[0, 0, 255, 255]);
    compositor.end_frame(size);
    surface.swap()?;
    println!("SDL2 smoke passed: {}x{}", size.0, size.1);
    if std::env::args().any(|arg| arg == "--wait-for-termination") {
        use std::io::Write;
        std::io::stdout().flush()?;
        loop {
            compositor.begin_frame();
            compositor.end_frame(size);
            surface.swap()?;
            std::thread::sleep(std::time::Duration::from_millis(17));
        }
    }
    Ok(())
}

#[cfg(not(feature = "sdl"))]
fn main() {
    eprintln!("Enable slot-gfx's sdl feature to run this example.");
    std::process::exit(2);
}
