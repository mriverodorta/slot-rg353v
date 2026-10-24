#[cfg(feature = "sdl")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{Compositor, Draw, SdlSurface, Surface, OUT_H, OUT_W};
    let mut surface = SdlSurface::new()?;
    let mut compositor = Compositor::new(&surface)?;
    let size = surface.window_size();
    compositor.fit(size);
    compositor.set_screen_power(1.0);
    let green = [Draw::Rect {
        x: 0.0,
        y: 0.0,
        w: OUT_W as f32,
        h: OUT_H as f32,
        colour: [0.0, 1.0, 0.0, 1.0],
    }];
    let check = |expected: [u8; 3]| {
        let mut pixel = [0u8; 4];
        unsafe {
            gl::ReadPixels(
                (size.0 / 2) as i32,
                (size.1 / 2) as i32,
                1,
                1,
                gl::RGBA,
                gl::UNSIGNED_BYTE,
                pixel.as_mut_ptr().cast(),
            );
            assert_eq!(gl::GetError(), gl::NO_ERROR);
        }
        for i in 0..3 {
            assert!(
                pixel[i].abs_diff(expected[i]) <= 2,
                "{pixel:?} != {expected:?}"
            );
        }
    };
    compositor.set_full_panel(true);
    compositor.begin_frame();
    compositor.draw_list(&green);
    compositor.end_frame(size);
    check([0, 255, 0]);
    surface.swap()?;

    let red: Vec<_> = (0..size.0 * size.1)
        .flat_map(|_| [255, 0, 0, 255])
        .collect();
    compositor.set_bezel(size.0, size.1, &red)?;
    compositor.set_full_panel(false);
    compositor.begin_frame();
    compositor.draw_list(&green);
    compositor.end_frame(size);
    check([255, 0, 0]);
    surface.swap()?;

    compositor.set_full_panel(true);
    compositor.begin_frame();
    compositor.draw_list(&green);
    compositor.end_frame(size);
    check([0, 255, 0]);
    surface.swap()?;
    println!("PASS lazy legacy bezel and full-panel exclusion with real GLES readback");
    Ok(())
}
#[cfg(not(feature = "sdl"))]
fn main() {}
