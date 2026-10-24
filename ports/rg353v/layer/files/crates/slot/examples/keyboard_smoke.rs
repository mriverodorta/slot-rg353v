//! Render the reusable keyboard through the actual RG353V 640x480 SDL path.
#[cfg(feature = "rg353v")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use slot_gfx::{Compositor, Draw, SdlSurface, Surface, OUT_H, OUT_W};
    use slot_ui::{draw_keyboard_legend, hint_face, Keyboard, KeyboardAction};
    let mut surface = SdlSurface::new()?;
    let size = surface.window_size();
    assert_eq!(size, (640, 480));
    let mut compositor = Compositor::new(&surface)?;
    compositor.set_full_panel(true);
    compositor.fit(size);
    compositor.set_frame_lift(1.0);
    type ReadPixels = unsafe extern "C" fn(i32, i32, i32, i32, u32, u32, *mut std::ffi::c_void);
    let read_pixels: ReadPixels =
        unsafe { std::mem::transmute(surface.proc_address("glReadPixels")) };
    let mut keyboard = Keyboard::new(64, true);
    for _ in 0..6 {
        keyboard.apply(KeyboardAction::Add);
    }
    keyboard.apply(KeyboardAction::Down);
    for (page, name) in [
        "lowercase",
        "uppercase",
        "numbers",
        "symbols",
        "password-shown",
        "password-hidden",
    ]
    .iter()
    .enumerate()
    {
        match page {
            1..=3 => keyboard.apply(KeyboardAction::NextSection),
            4 => {
                keyboard.apply(KeyboardAction::NextSection);
                keyboard.apply(KeyboardAction::ToggleVisibility);
            }
            5 => keyboard.apply(KeyboardAction::ToggleVisibility),
            _ => {}
        }
        let legends = keyboard
            .legend("Connect")
            .iter()
            .map(|hint| {
                let f = hint_face(hint.key, &hint.label);
                (compositor.create_texture(f.w, f.h, &f.rgba), f.w)
            })
            .collect::<Vec<_>>();
        let mut footer = Vec::new();
        draw_keyboard_legend(&legends, &mut footer);
        assert!(footer.iter().all(|d| matches!(*d, Draw::Tex { x, w, .. } if x >= 16.0 && x + w <= OUT_W as f32 - 16.0)), "five-action footer exceeds screen width");
        let view = keyboard.view(
            "WI-FI PASSWORD",
            "Example Wi-Fi",
            if page == 3 {
                "Could not connect. Check the password and try again."
            } else {
                ""
            },
        );
        let faces = view
            .labels
            .iter()
            .map(|label| {
                let f = label.face();
                (compositor.create_texture(f.w, f.h, &f.rgba), f.w, f.h)
            })
            .collect::<Vec<_>>();
        let mut draws = vec![Draw::Rect {
            x: 0.0,
            y: 0.0,
            w: OUT_W as f32,
            h: OUT_H as f32,
            colour: slot_ui::opening(),
        }];
        view.draw(&faces, &mut draws);
        assert_eq!(
            draws
                .iter()
                .filter(|d| matches!(d, Draw::Rect { .. }))
                .count(),
            6,
            "unexpected borders/grid lines"
        );
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
        let gap = pixels
            .chunks_exact(size.0 as usize * 4)
            .position(|row| {
                row.chunks_exact(4)
                    .any(|p| p[0] > 200 && p[1] > 200 && p[2] > 200)
            })
            .expect("keyboard disappeared");
        assert_eq!(gap, 28, "footer not anchored to native bottom inset");
        if let Ok(folder) = std::env::var("SCRATCH_PNG_DIR") {
            let top_down = pixels
                .chunks_exact(size.0 as usize * 4)
                .rev()
                .flatten()
                .copied()
                .collect::<Vec<_>>();
            let file = std::fs::File::create(format!("{folder}/keyboard-{name}-640x480.png"))?;
            let mut e = png::Encoder::new(file, size.0, size.1);
            e.set_color(png::ColorType::Rgba);
            e.set_depth(png::BitDepth::Eight);
            e.write_header()?.write_image_data(&top_down)?;
        }
        println!("{name}: borderless 640x480 keyboard, native footer inset {gap}px");
        surface.swap()?;
    }
    Ok(())
}
#[cfg(not(feature = "rg353v"))]
fn main() {}
