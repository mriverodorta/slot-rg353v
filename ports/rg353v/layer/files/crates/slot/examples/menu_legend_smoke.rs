//! Verify native and custom footers on the RG353V's real 640x480 presentation path.
#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{Compositor, Draw, SdlSurface, Surface, OUT_H, OUT_W};
    use slot_ui::{draw_menu_legend, hint_face, MENU_LEGEND_Y};
    let mut surface = SdlSurface::new()?;
    let size = surface.window_size();
    assert_eq!(size, (640, 480));
    let mut compositor = Compositor::new(&surface)?;
    compositor.set_full_panel(true);
    compositor.fit(size);
    type ReadPixels = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
    let pointer = surface.proc_address("glReadPixels");
    assert!(!pointer.is_null());
    let read_pixels: ReadPixels = unsafe { std::mem::transmute(pointer) };
    let mut reference = None;
    for (name, entries) in [
        ("native-settings", vec![("B", "Back"), ("A", "Open")]),
        (
            "updates",
            vec![("B", "Back"), ("X", "Notes"), ("A", "Select")],
        ),
        (
            "network-picker",
            vec![("B", "Back"), ("X", "Rescan"), ("A", "Select")],
        ),
        (
            "password",
            vec![
                ("D-pad", "Move"),
                ("L/R", "Case"),
                ("Y", "Delete"),
                ("B", "Back"),
                ("A", "Add"),
                ("START", "Connect"),
            ],
        ),
    ] {
        let faces = entries
            .iter()
            .map(|(key, label)| {
                let face = hint_face(key, label);
                (
                    compositor.create_texture(face.w, face.h, &face.rgba),
                    face.w,
                )
            })
            .collect::<Vec<_>>();
        let draws = vec![Draw::Rect {
            x: 0.0,
            y: 0.0,
            w: OUT_W as f32,
            h: OUT_H as f32,
            colour: [0.0, 0.0, 0.0, 1.0],
        }];
        let mut footer = Vec::new();
        draw_menu_legend(&faces, &mut footer);
        compositor.set_frame_split((name == "native-settings").then_some(MENU_LEGEND_Y - 2.0));
        compositor.begin_frame();
        compositor.draw_list(&draws);
        compositor.end_frame(size);
        compositor.draw_footer_overlay(size, &footer);
        let mut pixels = vec![0u8; (size.0 * size.1 * 4) as usize];
        unsafe {
            read_pixels(
                0,
                0,
                size.0 as i32,
                size.1 as i32,
                0x1908,
                0x1401,
                pixels.as_mut_ptr().cast(),
            );
        }
        let ink_rows = pixels
            .chunks_exact(size.0 as usize * 4)
            .enumerate()
            .filter(|(_, row)| {
                row.chunks_exact(4)
                    .any(|p| p[0] > 200 && p[1] > 200 && p[2] > 200)
            })
            .map(|(y, _)| y)
            .collect::<Vec<_>>();
        let gap = *ink_rows.first().expect("legend disappeared");
        assert!(
            (24..=34).contains(&gap),
            "{name}: footer floated {gap}px above bottom"
        );
        let expected = *reference.get_or_insert(gap);
        assert_eq!(
            gap, expected,
            "{name}: different bottom inset from original settings"
        );
        if let Ok(folder) = std::env::var("SCRATCH_PNG_DIR") {
            let top_down = pixels
                .chunks_exact(size.0 as usize * 4)
                .rev()
                .flatten()
                .copied()
                .collect::<Vec<_>>();
            let file = std::fs::File::create(format!("{folder}/footer-{name}-640x480.png"))?;
            let mut encoder = png::Encoder::new(file, size.0, size.1);
            encoder.set_color(png::ColorType::Rgba);
            encoder.set_depth(png::BitDepth::Eight);
            encoder.write_header()?.write_image_data(&top_down)?;
        }
        println!("{name}: {gap}px bottom inset, matching native settings");
        surface.swap()?;
    }
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
