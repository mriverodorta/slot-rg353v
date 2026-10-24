#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot::game_fps::{Hud, HEIGHT, MARGIN, WIDTH};
    use slot_gfx::{Compositor, SdlSurface, Surface};
    use std::time::Duration;
    let s = SdlSurface::new()?;
    let size = s.window_size();
    assert_eq!(size, (640, 480));
    let mut c = Compositor::new(&s)?;
    c.set_full_panel(true);
    c.fit(size);
    type Read = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
    let read: Read = unsafe { std::mem::transmute(s.proc_address("glReadPixels")) };
    for platform in slot_store::Platform::ALL {
        for perfect in [false, true] {
            let mut pixels = if perfect {
                slot_ui::perfect_overlay_face(platform).unwrap()
            } else {
                slot_ui::game_border_face(platform, false).unwrap()
            };
            let (gx, gy, gw, gh) = slot_gfx::game_panel_rect((640, 480), platform.picture(), false);
            let top = 480 - gy - gh;
            for y in top as usize..(top + gh) as usize {
                for x in gx as usize..(gx + gw) as usize {
                    pixels[(y * 640 + x) * 4..(y * 640 + x) * 4 + 4]
                        .copy_from_slice(&[24, 80, 32, 255]);
                }
            }
            let bg = c.create_texture_nearest(640, 480, &pixels);
            c.draw_boot_image(size, bg);
            let grab = || {
                let mut p = vec![0u8; 640 * 480 * 4];
                unsafe { read(0, 0, 640, 480, 0x1908, 0x1401, p.as_mut_ptr().cast()) };
                p
            };
            let before = grab();
            let mut hud = Hud::default();
            hud.meter.presented(Duration::ZERO, true, 0);
            for i in 1..=60 {
                hud.meter
                    .presented(Duration::from_secs_f64(i as f64 / 60.0), true, i);
            }
            hud.draw(&mut c, size);
            let after = grab();
            let mut changed = 0;
            for y in 0..480 {
                for x in 0..640 {
                    let at = ((479 - y) * 640 + x) * 4;
                    if before[at..at + 4] != after[at..at + 4] {
                        assert!((640 - MARGIN - WIDTH..640 - MARGIN).contains(&(x as u32)));
                        assert!((480 - MARGIN - HEIGHT..480 - MARGIN).contains(&(y as u32)));
                        assert_eq!(&after[at..at + 3], &[255; 3]);
                        changed += 1;
                    }
                }
            }
            assert!(changed > 20, "missing FPS glyphs: {changed}");
            // A changed number uploads into the same texture and must remain visible.
            hud.meter.presented(Duration::from_secs(2), true, 60);
            c.draw_boot_image(size, bg);
            hud.draw(&mut c, size);
            assert_ne!(grab(), after);
            println!("PASS FPS native pixels, platform={platform:?}, perfect={perfect}: {changed} white pixels, game/logo unchanged, texture updates visible");
        }
    }
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
