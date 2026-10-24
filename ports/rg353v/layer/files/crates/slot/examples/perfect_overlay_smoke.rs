//! Compare native overlay blending and presentation with an independent pixel reference.
#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{Compositor, ScreenEffect, SdlSurface, Surface, SRC_H, SRC_W};
    use slot_store::Platform;
    let mut surface = SdlSurface::new()?;
    let panel = surface.window_size();
    assert_eq!(panel, (640, 480));
    let mut compositor = Compositor::new(&surface)?;
    compositor.set_full_panel(true);
    compositor.fit(panel);
    compositor.set_game_fills_frame(true);
    compositor.set_screen_power(1.0);
    compositor.set_screen_effect(ScreenEffect::Shimmerless);
    let read: unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void) =
        unsafe { std::mem::transmute(surface.proc_address("glReadPixels")) };
    for platform in Platform::ALL {
        let (sw, sh) = platform.picture();
        let (ox, oy) = ((SRC_W - sw) / 2, (SRC_H - sh) / 2);
        let mut game = vec![0; (SRC_W * SRC_H * 4) as usize];
        for y in 0..sh {
            for x in 0..sw {
                let at = (((y + oy) * SRC_W + x + ox) * 4) as usize;
                game[at..at + 4].copy_from_slice(&[
                    (x * 7) as u8,
                    (y * 11) as u8,
                    (x ^ y) as u8,
                    0,
                ]);
            }
        }
        let src = [
            ox as f32 / SRC_W as f32,
            oy as f32 / SRC_H as f32,
            sw as f32 / SRC_W as f32,
            sh as f32 / SRC_H as f32,
        ];
        compositor.upload_game(&game);
        compositor.set_game_panel(Some(((sw, sh), false)));
        compositor.set_game_source_rect(src);
        compositor.set_picture([src[0], src[1], src[0] + src[2], src[1] + src[3]]);
        let rgba = slot_ui::perfect_overlay_face(platform).unwrap();
        let tex = compositor.create_texture_nearest(640, 480, &rgba);
        compositor.set_game_border(Some(tex));
        compositor.set_game_overlay(Some((tex, 0.0)));
        compositor.begin_frame();
        compositor.draw_game();
        let plain = compositor.read_frame();
        let (w, h) = compositor.frame_size();
        let (left, top) = if platform == Platform::Gba {
            (0, 0)
        } else {
            (54, 0)
        };
        assert_eq!(
            (w, h),
            if platform == Platform::Gba {
                (640, 427)
            } else {
                (532, 480)
            }
        );
        let alpha = slot_ui::perfect_overlay_opacity(platform);
        compositor.set_game_overlay(Some((tex, alpha)));
        compositor.begin_frame();
        compositor.draw_game();
        let filtered = compositor.read_frame();
        let mut changed = 0;
        let mut max_error = 0;
        for y in 0..h {
            for x in 0..w {
                let from = ((y * w + x) * 4) as usize;
                let art = (((top + y) * 640 + left + x) * 4) as usize;
                let a = rgba[art + 3] as f32 / 255.0 * alpha;
                for c in 0..3 {
                    let want = (plain[from + c] as f32 * (1.0 - a) + rgba[art + c] as f32 * a)
                        .round() as u8;
                    let err = filtered[from + c].abs_diff(want);
                    max_error = max_error.max(err);
                    assert!(
                        err <= 2,
                        "{platform:?} game blend at {x},{y}, channel {c}: {} != {want}",
                        filtered[from + c]
                    );
                    changed += usize::from(filtered[from + c] != plain[from + c]);
                }
            }
        }
        assert!(
            changed > (w * h) as usize,
            "overlay did not affect gameplay"
        );
        compositor.end_frame(panel);
        let mut physical = vec![0; 640 * 480 * 4];
        unsafe {
            read(0, 0, 640, 480, 0x1908, 0x1401, physical.as_mut_ptr().cast());
        }
        for y in 0..480 {
            for x in 0..640 {
                let at = ((y * 640 + x) * 4) as usize;
                let got = ((479 - y) * 640 + x) * 4;
                if (left..left + w).contains(&x) && (top..top + h).contains(&y) {
                    let src = (((y - top) * w + x - left) * 4) as usize;
                    assert_eq!(
                        &physical[got as usize..got as usize + 3],
                        &filtered[src..src + 3],
                        "game resized on presentation"
                    );
                } else {
                    for c in 0..3 {
                        let want = (rgba[at + c] as f32 * alpha).round() as u8;
                        assert!(
                            physical[got as usize + c].abs_diff(want) <= 1,
                            "border misplaced"
                        );
                    }
                }
            }
        }
        if let Some(folder) = std::env::args().nth(1) {
            std::fs::create_dir_all(&folder)?;
            let mut top_down = Vec::new();
            for row in physical.chunks_exact(640 * 4).rev() {
                top_down.extend_from_slice(row);
            }
            let path = std::path::Path::new(&folder).join(format!(
                "perfect-{}.png",
                platform.dir_name().to_lowercase()
            ));
            let mut png = png::Encoder::new(std::fs::File::create(path)?, 640, 480);
            png.set_color(png::ColorType::Rgba);
            png.set_depth(png::BitDepth::Eight);
            png.write_header()?.write_image_data(&top_down)?;
        }
        println!("{platform:?}: exact asset/alpha, full game, native presentation passed; max blend error {max_error}");
        compositor.set_game_overlay(None);
        compositor.set_game_border(None);
        compositor.begin_frame();
        assert_eq!(
            compositor.frame_size(),
            if platform == Platform::Gba {
                (640, 427)
            } else {
                (533, 480)
            }
        );
        compositor.draw_game();
        let restored = compositor.read_frame();
        assert_ne!(restored, filtered);
        compositor.set_game_panel(None);
        compositor.begin_frame();
        compositor.draw_game();
        let menu = compositor.read_frame();
        compositor.set_game_overlay(Some((tex, alpha)));
        compositor.begin_frame();
        compositor.draw_game();
        assert_eq!(
            compositor.read_frame(),
            menu,
            "overlay leaked into menu/capture"
        );
        compositor.set_game_overlay(None);
        surface.swap()?;
    }
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
