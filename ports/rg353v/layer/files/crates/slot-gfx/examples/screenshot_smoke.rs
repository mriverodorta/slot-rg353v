#[cfg(feature = "sdl")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{Compositor, ScreenEffect, SdlSurface, Surface, SRC_H, SRC_W};
    let surface = SdlSurface::new()?;
    let panel = surface.window_size();
    assert_eq!(panel, (640, 480));
    let mut c = Compositor::new(&surface)?;
    c.set_full_panel(true);
    c.fit(panel);
    c.set_game_fills_frame(true);
    c.set_screen_power(1.0);
    let mut pixels = vec![0; (SRC_W * SRC_H * 4) as usize];
    for y in 0..SRC_H {
        for x in 0..SRC_W {
            let i = ((y * SRC_W + x) * 4) as usize;
            let color = if y < SRC_H / 2 {
                [0, 0, 230, 0]
            } else {
                [230, 0, 0, 0]
            };
            pixels[i..i + 4].copy_from_slice(&color);
        }
    }
    c.upload_game(&pixels);
    c.set_game_panel(Some(((240, 160), false)));
    c.set_game_source_rect([0., 0., 1., 1.]);
    c.set_picture([0., 0., 1., 1.]);
    c.set_screen_effect(ScreenEffect::Lcd3x);
    let border = vec![255u8; 640 * 480 * 4];
    let tex = c.create_texture_nearest(640, 480, &border);
    c.set_game_border(Some(tex));
    let (w, h, plain) = c.capture_game(false, false, false);
    assert_eq!((w, h), (640, 427));
    let at = (w as usize / 2) * 4;
    assert!(plain[at] > plain[at + 2]);
    let at = ((h as usize - 2) * w as usize + w as usize / 2) * 4;
    assert!(plain[at + 2] > plain[at]);
    let (_, _, filtered) = c.capture_game(true, true, false);
    assert_ne!(plain, filtered);
    let (w, h, full) = c.capture_game(false, false, true);
    assert_eq!((w, h), (640, 480));
    assert_eq!(
        &full[((479 * 640 + 320) * 4)..((479 * 640 + 320) * 4 + 3)],
        &[255, 255, 255]
    );
    let (_, _, plain_again) = c.capture_game(false, false, false);
    assert_eq!(plain, plain_again);
    c.set_blue_light(4);
    let (_, _, shaders_only) = c.capture_game(true, false, false);
    let (_, _, filters_only) = c.capture_game(false, true, false);
    let (_, _, both) = c.capture_game(true, true, false);
    let (_, _, neither) = c.capture_game(false, false, false);
    assert_eq!(shaders_only, filtered);
    assert_eq!(neither, plain);
    assert_ne!(filters_only, plain);
    assert_ne!(both, shaders_only);
    assert_ne!(both, filters_only);
    let (_, _, both_again) = c.capture_game(true, true, false);
    assert_eq!(both, both_again);
    // Perfect texture has marks inside the game as well as the border.
    c.set_game_overlay(Some((tex, 0.3)));
    let (_, _, perfect) = c.capture_game(true, true, true);
    let (_, _, no_overlay) = c.capture_game(true, true, false);
    assert_ne!(&perfect[..no_overlay.len()], &no_overlay);
    println!("Screenshot shader/filter/overlay toggles, native geometry, top-down orientation and state restoration passed");
    Ok(())
}
#[cfg(not(feature = "sdl"))]
fn main() {}
