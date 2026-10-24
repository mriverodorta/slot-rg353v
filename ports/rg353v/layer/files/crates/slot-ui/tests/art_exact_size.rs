use std::path::Path;

fn png(path: &Path, w: u32, h: u32, colour: png::ColorType, pixels: &[u8]) {
    let mut encoder = png::Encoder::new(std::fs::File::create(path).unwrap(), w, h);
    encoder.set_color(colour);
    encoder.set_depth(png::BitDepth::Eight);
    encoder
        .write_header()
        .unwrap()
        .write_image_data(pixels)
        .unwrap();
}

#[test]
fn exact_canvas_preserves_every_rgba_byte() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("canvas.png");
    let pixels: Vec<u8> = (0..720 * 480 * 4)
        .map(|n| ((n * 37 + n / 7) % 256) as u8)
        .collect();
    png(&path, 720, 480, png::ColorType::Rgba, &pixels);
    assert_eq!(slot_ui::cover(&path, 720, 480).unwrap(), pixels);
}

#[test]
fn exact_rgb_image_keeps_opaque_alpha() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("rgb.png");
    let pixels: Vec<u8> = (0..8 * 5 * 3).map(|n| ((n * 17) % 256) as u8).collect();
    png(&path, 8, 5, png::ColorType::Rgb, &pixels);
    let expected: Vec<u8> = pixels
        .chunks_exact(3)
        .flat_map(|p| [p[0], p[1], p[2], 255])
        .collect();
    assert_eq!(slot_ui::cover(&path, 8, 5).unwrap(), expected);
}

#[test]
fn exact_grayscale_image_keeps_transparency() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("gray.png");
    let pixels = [0, 0, 23, 63, 41, 127, 100, 200, 180, 240, 255, 255];
    png(&path, 2, 3, png::ColorType::GrayscaleAlpha, &pixels);
    let expected: Vec<u8> = pixels
        .chunks_exact(2)
        .flat_map(|p| [p[0], p[0], p[0], p[1]])
        .collect();
    assert_eq!(slot_ui::cover(&path, 2, 3).unwrap(), expected);
}

#[test]
fn differently_sized_images_keep_the_cover_scaler() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("scaled.png");
    let pixels = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
    png(&path, 2, 2, png::ColorType::Rgb, &pixels);
    let expected: Vec<u8> = (0..4)
        .flat_map(|y| {
            (0..4).flat_map(move |x| {
                let at = ((y / 2) * 2 + x / 2) * 3;
                [pixels[at], pixels[at + 1], pixels[at + 2], 255]
            })
        })
        .collect();
    assert_eq!(slot_ui::cover(&path, 4, 4).unwrap(), expected);
}
