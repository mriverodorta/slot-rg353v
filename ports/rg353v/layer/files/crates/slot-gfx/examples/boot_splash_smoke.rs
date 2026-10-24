#[cfg(feature = "sdl")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{Compositor, SdlSurface, Surface};
    let mut surface = SdlSurface::new()?;
    let mut compositor = Compositor::new(&surface)?;
    let size = surface.window_size();
    assert_eq!(size, (640, 480));
    let mut image = vec![255u8; 640 * 480 * 4];
    for y in 0..480 {
        for x in 0..640 {
            let p = (y * 640 + x) * 4;
            image[p..p + 3].copy_from_slice(if y < 240 { &[255, 0, 0] } else { &[0, 0, 255] });
        }
    }
    let texture = compositor.create_texture(640, 480, &image);
    for lift in [0.0, 1.0] {
        compositor.set_frame_lift(lift);
        compositor.set_full_panel(true);
        compositor.draw_boot_image(size, texture);
        let mut pixels = vec![0u8; 640 * 480 * 4];
        unsafe {
            gl::ReadPixels(
                0,
                0,
                640,
                480,
                gl::RGBA,
                gl::UNSIGNED_BYTE,
                pixels.as_mut_ptr().cast(),
            );
        }
        assert_eq!(
            &pixels[(479 * 640 + 320) * 4..][..3],
            &[255, 0, 0],
            "top edge"
        );
        assert_eq!(&pixels[(320 * 4)..][..3], &[0, 0, 255], "bottom edge");
        surface.swap()?;
    }
    compositor.update_texture(texture, 1, 1, &[0, 0, 0, 0]);
    println!("Boot image covers the physical panel without shelf lift or aspect distortion");
    Ok(())
}
#[cfg(not(feature = "sdl"))]
fn main() {}
