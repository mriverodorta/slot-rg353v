use slot_store::Platform;

/// Physical 640x480 artwork, loaded only when that system first enters gameplay.
/// GB/GBC reuse cartridge lettering; GBA uses native-size vector outlines.
pub fn game_border_face(platform: Platform, integer: bool) -> Option<Vec<u8>> {
    let source = platform.picture();
    let (left, bottom, width, height) = if integer {
        slot_gfx::integer_game_panel_rect((640, 480), source)
    } else {
        slot_gfx::game_panel_rect((640, 480), source, false)
    };
    let top = 480 - bottom - height;
    let power_x = left / 2;
    let right_x = (left + width + 640) / 2;
    let window = format!("M{left} {top}V{}H{}V{top}Z", top + height, left + width);
    if platform == Platform::Gba {
        // Rasterize vector paths once at final panel resolution, without an
        // enlarged bitmap or a second texture resize. Keep the logo in the footer.
        let logo_y = if integer { 400.0 } else { 453.0 } - 288.0 * 36.0 / 392.0 / 2.0;
        let logo = include_str!("../assets/gba-wordmark.svg").replacen(
            "<svg ",
            &format!(
                "<svg x=\"176\" y=\"{logo_y}\" width=\"288\" height=\"{}\" ",
                288.0 * 36.0 / 392.0
            ),
            1,
        );
        let svg = include_str!("../assets/border-gba.svg")
            .replace("__WINDOW__", &window)
            .replace("__LOGO__", &logo);
        return crate::art::render_svg(&svg, 640, 480);
    }
    let (svg, logo, logo_center_y, logo_w, ink) = match platform {
        Platform::Gb => (
            include_str!("../assets/border-gb.svg"),
            include_bytes!("../assets/lettering_gb.png").as_slice(),
            468,
            if integer { 144 } else { 128 },
            [140, 140, 144],
        ),
        Platform::Gbc => (
            include_str!("../assets/border-gbc.svg"),
            include_bytes!("../assets/lettering_gbc.png").as_slice(),
            468,
            if integer { 184 } else { 156 },
            [140, 140, 144],
        ),
        Platform::Gba => unreachable!("GBA is rendered as vector artwork above"),
    };
    let svg = svg
        .replace("__WINDOW__", &window)
        .replace("__POWER_X__", &power_x.to_string())
        .replace("__GLOW_R__", if integer { "27" } else { "22" })
        .replace("__STRIPE_1__", &(right_x - 3).to_string())
        .replace("__STRIPE_2__", &(right_x + 3).to_string());
    let mut rgba = crate::art::render_svg(&svg, 640, 480)?;
    let mut reader = png::Decoder::new(std::io::Cursor::new(logo))
        .read_info()
        .ok()?;
    let mut mask = vec![0; reader.output_buffer_size()];
    let info = reader.next_frame(&mut mask).ok()?;
    if info.color_type != png::ColorType::Grayscale || info.bit_depth != png::BitDepth::Eight {
        return None;
    }
    let sw = info.width;
    let lit: Vec<_> = mask[..info.buffer_size()]
        .iter()
        .enumerate()
        .filter(|(i, v)| **v > 0 && (platform != Platform::Gb || *i as u32 % sw >= 103))
        .map(|(i, _)| (i as u32 % sw, i as u32 / sw))
        .collect();
    let x0 = lit.iter().map(|p| p.0).min()?;
    let y0 = lit.iter().map(|p| p.1).min()?;
    let w = lit.iter().map(|p| p.0).max()? - x0 + 1;
    let h = lit.iter().map(|p| p.1).max()? - y0 + 1;
    let dw = logo_w;
    let dh = (h * dw + w / 2) / w;
    let logo_y = (logo_center_y as u32).checked_sub(dh / 2)?;
    if logo_y + dh > 480 || dw > 640 {
        return None;
    }
    // Bilinear resampling is confined to the lettering, never the game image.
    for y in 0..dh {
        for x in 0..dw {
            let sx = ((x as f32 + 0.5) * w as f32 / dw as f32 - 0.5).clamp(0.0, (w - 1) as f32);
            let sy = ((y as f32 + 0.5) * h as f32 / dh as f32 - 0.5).clamp(0.0, (h - 1) as f32);
            let (ix, iy) = (sx as u32, sy as u32);
            let sample = |dx: u32, dy: u32| {
                mask[((y0 + dy.min(h - 1)) * sw + x0 + dx.min(w - 1)) as usize] as f32
            };
            let upper = sample(ix, iy) * (1.0 - sx.fract()) + sample(ix + 1, iy) * sx.fract();
            let lower =
                sample(ix, iy + 1) * (1.0 - sx.fract()) + sample(ix + 1, iy + 1) * sx.fract();
            let alpha = (upper * (1.0 - sy.fract()) + lower * sy.fract()) / 255.0;
            let (dx, dy) = (right_x as u32 - dh / 2 + dh - 1 - y, 240 - dw / 2 + x);
            let ink = if platform == Platform::Gbc && x0 as f32 + sx >= 127.0 {
                match x0 + sx as u32 {
                    0..=140 => [169, 77, 110],
                    141..=153 => [118, 88, 146],
                    154..=165 => [145, 163, 94],
                    166..=178 => [190, 147, 66],
                    _ => [82, 148, 166],
                }
            } else {
                ink
            };
            let at = ((dy * 640 + dx) * 4) as usize;
            for c in 0..3 {
                rgba[at + c] =
                    (rgba[at + c] as f32 * (1.0 - alpha) + ink[c] as f32 * alpha).round() as u8;
            }
        }
    }
    if platform != Platform::Gba {
        let layout = crate::text::Layout {
            lines: vec!["POWER".into()],
            px: 10.0,
            tracking: 0.2,
        };
        let mut label = vec![0u8; 50 * 16 * 4];
        crate::text::draw_centred(&mut label, 50, 16, &layout, [156, 156, 160]);
        for y in 0..16 {
            for x in 0..50 {
                let from = (y * 50 + x) * 4;
                let at = ((244 + y) * 640 + power_x as usize - 25 + x) * 4;
                let alpha = label[from + 3] as f32 / 255.0;
                for c in 0..3 {
                    rgba[at + c] = (rgba[at + c] as f32 * (1.0 - alpha)
                        + label[from + c] as f32 * alpha)
                        .round() as u8;
                }
            }
        }
    }
    Some(rgba)
}

/// RGC v1.0 artwork at its original 640x480 resolution; no resizing or recoloring.
pub fn perfect_overlay_face(platform: Platform) -> Option<Vec<u8>> {
    let bytes = match platform {
        Platform::Gb => include_bytes!("../assets/perfect/Perfect_GB-DMG.png").as_slice(),
        Platform::Gbc => include_bytes!("../assets/perfect/Perfect_GBC.png").as_slice(),
        Platform::Gba => include_bytes!("../assets/perfect/Perfect_GBA.png").as_slice(),
    };
    let mut decoder = png::Decoder::new(std::io::Cursor::new(bytes));
    decoder.set_transformations(png::Transformations::EXPAND | png::Transformations::STRIP_16);
    let mut reader = decoder.read_info().ok()?;
    let mut rgba = vec![0; reader.output_buffer_size()];
    let info = reader.next_frame(&mut rgba).ok()?;
    if info.width != 640 || info.height != 480 || info.color_type != png::ColorType::Rgba {
        return None;
    }
    rgba.truncate(info.buffer_size());
    Some(rgba)
}

pub fn perfect_overlay_opacity(platform: Platform) -> f32 {
    match platform {
        Platform::Gbc => 0.8,
        _ => 1.0,
    }
}
