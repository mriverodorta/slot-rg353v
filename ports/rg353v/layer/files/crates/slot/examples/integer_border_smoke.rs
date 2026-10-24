//! Border preview and physical-pixel regression; no emulator, audio or user content.
#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{Compositor, SdlSurface, Surface, SRC_H, SRC_W};
    use slot_store::Platform;
    let mut surface = SdlSurface::new()?;
    let panel = surface.window_size();
    assert_eq!(panel, (640, 480));
    let mut compositor = Compositor::new(&surface)?;
    compositor.set_full_panel(true);
    compositor.fit(panel);
    compositor.set_screen_power(1.0);

    compositor.set_game_fills_frame(true);
    for integer in [false, true] {
        compositor.set_integer_game(integer);
        for platform in Platform::ALL {
            let (sw, sh) = platform.picture();
            let (ox, oy) = ((SRC_W - sw) / 2, (SRC_H - sh) / 2);
            let mut game = vec![0; (SRC_W * SRC_H * 4) as usize];
            for y in 0..sh {
                for x in 0..sw {
                    let rgb = if platform == Platform::Gb {
                        if (x / 8 + y / 8) % 2 == 0 {
                            [128, 145, 88]
                        } else {
                            [69, 86, 55]
                        }
                    } else if (x / 8 + y / 8) % 2 == 0 {
                        [60, 109, 154]
                    } else {
                        [27, 53, 87]
                    };
                    let at = (((oy + y) * SRC_W + ox + x) * 4) as usize;
                    game[at..at + 4].copy_from_slice(&[rgb[2], rgb[1], rgb[0], 0]);
                }
            }
            let source = [
                ox as f32 / SRC_W as f32,
                oy as f32 / SRC_H as f32,
                sw as f32 / SRC_W as f32,
                sh as f32 / SRC_H as f32,
            ];
            compositor.upload_game(&game);
            compositor.set_game_source_rect(source);
            compositor.set_picture([
                source[0],
                source[1],
                source[0] + source[2],
                source[1] + source[3],
            ]);
            compositor.set_game_panel(Some(((sw, sh), false)));
            let border = slot_ui::game_border_face(platform, integer).ok_or("missing border")?;
            let tex = compositor.create_texture_nearest(640, 480, &border);
            compositor.set_game_border(Some(tex));
            compositor.begin_frame();
            compositor.draw_game();
            let filtered = compositor.read_frame();
            compositor.end_frame(panel);
            let read: unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void) =
                unsafe { std::mem::transmute(surface.proc_address("glReadPixels")) };
            let mut pixels = vec![0u8; 640 * 480 * 4];
            unsafe {
                read(0, 0, 640, 480, 0x1908, 0x1401, pixels.as_mut_ptr().cast());
            }
            let (left, bottom, w, h) = if integer {
                slot_gfx::integer_game_panel_rect(panel, (sw, sh))
            } else {
                slot_gfx::game_panel_rect(panel, (sw, sh), false)
            };
            for y in 0..480i32 {
                for x in 0..640i32 {
                    let at = ((y * 640 + x) * 4) as usize;
                    if (left..left + w).contains(&x) && (bottom..bottom + h).contains(&y) {
                        let from = (((h - 1 - y + bottom) * w + x - left) * 4) as usize;
                        assert_eq!(
                            &pixels[at..at + 4],
                            &filtered[from..from + 4],
                            "{platform:?} border changed a game pixel"
                        );
                    } else {
                        let from = (((479 - y) * 640 + x) * 4) as usize;
                        assert_eq!(
                            &pixels[at..at + 4],
                            &border[from..from + 4],
                            "{platform:?} artwork is misplaced"
                        );
                    }
                }
            }
            if let Some(folder) = std::env::args().nth(1) {
                std::fs::create_dir_all(&folder)?;
                let path = std::path::Path::new(&folder).join(format!(
                    "{}{}.png",
                    platform.dir_name().to_lowercase(),
                    if integer { "-integer" } else { "" }
                ));
                let file = std::fs::File::create(path)?;
                let mut encoder = png::Encoder::new(file, 640, 480);
                encoder.set_color(png::ColorType::Rgba);
                encoder.set_depth(png::BitDepth::Eight);
                let mut writer = encoder.write_header()?;
                let top_down: Vec<u8> = pixels
                    .chunks_exact(640 * 4)
                    .rev()
                    .flatten()
                    .copied()
                    .collect();
                writer.write_image_data(&top_down)?;
            }
            surface.swap()?;
        }
    }
    println!("GB, GBC and GBA fit/integer borders passed every physical pixel comparison");
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
