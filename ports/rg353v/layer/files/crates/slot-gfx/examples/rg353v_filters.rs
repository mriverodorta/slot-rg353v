//! Native-size shader regression: run under Xvfb or on an idle RG353V.
#[cfg(feature = "sdl")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{
        game_panel_rect, integer_game_panel_rect, Compositor, ScreenEffect, SdlSurface, Surface,
        SRC_H, SRC_W,
    };
    let mut surface = SdlSurface::new()?;
    let panel = surface.window_size();
    assert_eq!(
        panel,
        (640, 480),
        "this regression targets the RG353V panel"
    );
    let mut compositor = Compositor::new(&surface)?;
    compositor.set_full_panel(true);
    compositor.fit(panel);
    compositor.set_screen_power(1.0);
    compositor.set_game_fills_frame(true);
    let paper: Vec<u8> = (0..64)
        .map(|i| if i % 3 == 0 { 170 } else { 245 })
        .collect();
    compositor.set_paper(8, &paper);
    let mut checked = 0;
    for (sw, sh) in [(240u32, 160u32), (160, 144)] {
        let (ox, oy) = ((SRC_W - sw) / 2, (SRC_H - sh) / 2);
        let mut game = vec![0u8; (SRC_W * SRC_H * 4) as usize];
        for y in 0..SRC_H {
            for x in 0..SRC_W {
                let rgb = if x < ox || x >= ox + sw || y < oy || y >= oy + sh {
                    [0, 0, 0]
                } else if (x + y) % 2 == 0 {
                    [240, 200, 160]
                } else {
                    [24, 48, 96]
                };
                let i = ((y * SRC_W + x) * 4) as usize;
                game[i..i + 4].copy_from_slice(&[rgb[2], rgb[1], rgb[0], 0]);
            }
        }
        compositor.upload_game(&game);
        let src = [
            ox as f32 / SRC_W as f32,
            oy as f32 / SRC_H as f32,
            sw as f32 / SRC_W as f32,
            sh as f32 / SRC_H as f32,
        ];
        compositor.set_game_source_rect(src);
        compositor.set_picture([src[0], src[1], src[0] + src[2], src[1] + src[3]]);
        for (stretch, integer) in [(false, false), (true, false), (false, true)] {
            compositor.set_integer_game(integer);
            let (left, bottom, w, h) = if integer {
                integer_game_panel_rect(panel, (sw, sh))
            } else {
                game_panel_rect(panel, (sw, sh), stretch)
            };
            let (w, h) = (w as u32, h as u32);
            compositor.set_game_panel(Some(((sw, sh), stretch)));
            let mut distinct = std::collections::HashSet::new();
            for effect in [
                ScreenEffect::None,
                ScreenEffect::Lcd3x,
                ScreenEffect::Grid,
                ScreenEffect::Dot,
                ScreenEffect::Simpletex,
                ScreenEffect::Shimmerless,
                ScreenEffect::ShimmerlessLcd,
            ] {
                compositor.set_screen_effect(effect);
                compositor.begin_frame();
                assert_eq!(compositor.frame_size(), (w, h), "{sw}x{sh} {effect:?}");
                compositor.draw_game();
                let filtered = compositor.read_frame();
                assert_eq!(filtered.len(), (w * h * 4) as usize);
                if effect == ScreenEffect::None {
                    for y in 0..h {
                        for x in 0..w {
                            let fx = (x as f32 + 0.5) * sw as f32 / w as f32;
                            let fy = (y as f32 + 0.5) * sh as f32 / h as f32;
                            // Exact source-cell boundaries can round either way in GLES.
                            if (fx - fx.round()).abs() < 0.001 || (fy - fy.round()).abs() < 0.001 {
                                continue;
                            }
                            let source = (((oy + fy as u32) * SRC_W + ox + fx as u32) * 4) as usize;
                            let target = ((y * w + x) * 4) as usize;
                            assert_eq!(
                                &filtered[target..target + 3],
                                &[game[source + 2], game[source + 1], game[source]],
                                "nearest source mismatch at {x},{y} in {sw}x{sh}"
                            );
                        }
                    }
                }
                compositor.end_frame(panel);
                let mut physical = vec![0u8; (panel.0 * panel.1 * 4) as usize];
                unsafe {
                    gl::BindFramebuffer(gl::FRAMEBUFFER, 0);
                    gl::ReadPixels(
                        0,
                        0,
                        panel.0 as i32,
                        panel.1 as i32,
                        gl::RGBA,
                        gl::UNSIGNED_BYTE,
                        physical.as_mut_ptr().cast(),
                    );
                    assert_eq!(gl::GetError(), gl::NO_ERROR);
                }
                for y in 0..panel.1 {
                    for x in 0..panel.0 {
                        let at = ((y * panel.0 + x) * 4) as usize;
                        if (left as u32..left as u32 + w).contains(&x)
                            && (bottom as u32..bottom as u32 + h).contains(&y)
                        {
                            let from = (((h - 1 - (y - bottom as u32)) * w + x - left as u32) * 4)
                                as usize;
                            assert_eq!(&physical[at..at + 4], &filtered[from..from + 4],
                                "filter resampled at {x},{y} for {sw}x{sh} stretch={stretch} {effect:?}");
                        } else {
                            assert_eq!(&physical[at..at + 4], &[0, 0, 0, 255], "letterbox changed");
                        }
                    }
                }
                if matches!(
                    effect,
                    ScreenEffect::Shimmerless | ScreenEffect::ShimmerlessLcd
                ) {
                    verify_box_filter(
                        &filtered,
                        (sw, sh),
                        (w, h),
                        (ox, oy),
                        effect == ScreenEffect::ShimmerlessLcd,
                    );
                }
                if !stretch && !integer && std::env::var_os("SLOT_SHADER_BENCH").is_some() {
                    let mut samples = Vec::new();
                    for i in 0..90 {
                        let start = std::time::Instant::now();
                        compositor.begin_frame();
                        compositor.draw_game();
                        unsafe {
                            gl::Finish();
                        }
                        if i >= 10 {
                            samples.push(start.elapsed().as_secs_f64() * 1000.0);
                        }
                    }
                    samples.sort_by(f64::total_cmp);
                    println!(
                        "BENCH {sw}x{sh} {effect:?}: render+finish median {:.3} ms, p95 {:.3} ms",
                        samples[40], samples[76]
                    );
                }
                distinct.insert(filtered);
                surface.swap()?;
                checked += 1;
            }
            // At integer scales the plain area filter is mathematically nearest;
            // driver rounding may still differ by a channel level at boundaries.
            assert!(
                if integer {
                    (6..=7).contains(&distinct.len())
                } else {
                    distinct.len() == 7
                },
                "an effect is missing or renders the same as Off"
            );
            if !stretch {
                // Even a fully opaque border must leave every game pixel untouched.
                let opaque = [13, 19, 29, 255].repeat(640 * 480);
                let tex = compositor.create_texture_nearest(640, 480, &opaque);
                compositor.set_game_border(Some(tex));
                compositor.set_screen_effect(ScreenEffect::None);
                compositor.begin_frame();
                compositor.draw_game();
                let filtered = compositor.read_frame();
                compositor.end_frame(panel);
                let mut physical = vec![0u8; 640 * 480 * 4];
                unsafe {
                    gl::ReadPixels(
                        0,
                        0,
                        640,
                        480,
                        gl::RGBA,
                        gl::UNSIGNED_BYTE,
                        physical.as_mut_ptr().cast(),
                    );
                }
                for y in 0..480u32 {
                    for x in 0..640u32 {
                        let at = ((y * 640 + x) * 4) as usize;
                        if (left as u32..left as u32 + w).contains(&x)
                            && (bottom as u32..bottom as u32 + h).contains(&y)
                        {
                            let from = (((h - 1 - (y - bottom as u32)) * w + x - left as u32) * 4)
                                as usize;
                            assert_eq!(
                                &physical[at..at + 4],
                                &filtered[from..from + 4],
                                "opaque border touched the game"
                            );
                        } else {
                            assert_eq!(&physical[at..at + 4], &[13, 19, 29, 255]);
                        }
                    }
                }
                compositor.set_game_border(None);
            }
            // Opening a menu must preserve the last game capture until its next frame.
            compositor.set_game_panel(None);
            assert_eq!(compositor.frame_size(), (w, h));
            assert_eq!(compositor.read_frame().len(), (w * h * 4) as usize);
            compositor.begin_frame();
            assert_eq!(
                compositor.frame_size(),
                panel,
                "menu lost its full-panel canvas"
            );
            compositor.end_frame(panel);
        }
    }
    println!("RG353V filters passed: {checked} final-panel pixel comparisons, fit, stretch and integer; clipped borders; GB/GBC and GBA");
    Ok(())
}
#[cfg(not(feature = "sdl"))]
fn main() {}

#[cfg(feature = "sdl")]
fn verify_box_filter(
    rgba: &[u8],
    source: (u32, u32),
    out: (u32, u32),
    offset: (u32, u32),
    grid: bool,
) {
    // Independent area integration: source texels are rectangles, optionally
    // containing a 30%-wide, 30%-opaque LCD line on each axis.
    fn weight(lo: f64, hi: f64, cell: u32, grid: bool) -> f64 {
        let a = lo.max(cell as f64);
        let b = hi.min(cell as f64 + 1.0);
        if b <= a {
            return 0.0;
        }
        if !grid {
            return b - a;
        }
        let bright = (b.min(cell as f64 + 0.7) - a).max(0.0);
        bright + 0.7 * (b - a - bright)
    }
    let (sw, sh) = source;
    let (w, h) = out;
    let (dx, dy) = (sw as f64 / w as f64, sh as f64 / h as f64);
    let mut max_error = 0;
    for y in 0..h {
        for x in 0..w {
            let (x0, y0) = (x as f64 * dx, y as f64 * dy);
            let (x1, y1) = (x0 + dx, y0 + dy);
            let mut expected = [0.0; 3];
            for sy in y0.floor() as u32..(y1.ceil() as u32).min(sh) {
                for sx in x0.floor() as u32..(x1.ceil() as u32).min(sw) {
                    let area = weight(x0, x1, sx, grid) * weight(y0, y1, sy, grid) / (dx * dy);
                    let color = if (sx + offset.0 + sy + offset.1) % 2 == 0 {
                        [240.0, 200.0, 160.0]
                    } else {
                        [24.0, 48.0, 96.0]
                    };
                    for c in 0..3 {
                        expected[c] += color[c] * area;
                    }
                }
            }
            let at = ((y * w + x) * 4) as usize;
            for c in 0..3 {
                let error = (rgba[at + c] as i32 - expected[c].round() as i32).abs();
                max_error = max_error.max(error);
                assert!(error <= 3, "area integration mismatch {source:?}->{out:?}, grid={grid}, at {x},{y} channel {c}: {} vs {}", rgba[at+c], expected[c]);
            }
        }
    }
    println!("Shimmerless area reference {source:?}->{out:?}, grid={grid}: max channel error {max_error}");
}
