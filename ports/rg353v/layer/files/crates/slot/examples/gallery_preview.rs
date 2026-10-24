use slot::{
    gallery::Gallery,
    screenshots::{self, Request},
};
use slot_input::Btn;
use slot_store::Platform;
use slot_ui::CartFace;
use std::{fs::File, path::Path, time::Duration};
fn frame(g: &mut Gallery) -> (CartFace, CartFace) {
    for _ in 0..500 {
        g.poll();
        if let Some(f) = g.take_frame() {
            return f;
        }
        std::thread::sleep(Duration::from_millis(2));
    }
    panic!("no frame");
}
fn output(path: &Path, mut f: CartFace, legend: &CartFace, alpha: f32) {
    for (d, s) in f.rgba.chunks_exact_mut(4).zip(legend.rgba.chunks_exact(4)) {
        let a = s[3] as f32 / 255.0 * alpha;
        for c in 0..3 {
            d[c] = (s[c] as f32 * a + d[c] as f32 * (1.0 - a)).round() as u8;
        }
    }
    let mut e = png::Encoder::new(File::create(path).unwrap(), f.w, f.h);
    e.set_color(png::ColorType::Rgba);
    e.set_depth(png::BitDepth::Eight);
    e.write_header().unwrap().write_image_data(&f.rgba).unwrap();
}
fn main() {
    let out = std::env::args().nth(1).unwrap();
    let out = Path::new(&out);
    std::fs::create_dir_all(out).unwrap();
    let root = tempfile::tempdir().unwrap();
    for (i, (p, name)) in [
        (Platform::Gba, "The Legend of Zelda - A Link to the Past"),
        (Platform::Gb, "Pokemon Blue"),
        (Platform::Gbc, "The Legend of Zelda - Link's Awakening DX"),
        (Platform::Gba, "Golden Sun - The Lost Age"),
        (Platform::Gba, "Advance Wars"),
        (Platform::Gb, "Super Mario Land"),
    ]
    .into_iter()
    .enumerate()
    {
        let (w, h) = p.picture();
        let mut rgba = vec![0; (w * h * 4) as usize];
        for y in 0..h {
            for x in 0..w {
                let n = ((y * w + x) * 4) as usize;
                let tile = (x / 8 + y / 8) % 2;
                rgba[n..n + 4].copy_from_slice(&[
                    (45 + i * 18) as u8,
                    (95 + tile * 65) as u8,
                    (75 + ((x + y) % 100)) as u8,
                    255,
                ]);
            }
        }
        screenshots::save(
            &Request {
                root: root.path().to_owned(),
                platform: p,
                game: name.into(),
                shaders: false,
                filters: false,
                overlay: false,
            },
            w,
            h,
            &rgba,
        )
        .unwrap();
    }
    let mut g = Gallery::open(root.path().to_owned(), 0);
    let (a, b) = frame(&mut g);
    output(&out.join("gallery-grid.png"), a, &b, 1.0);
    g.button(Btn::A, 100);
    g.release(Btn::A, 101);
    let (a, b) = frame(&mut g);
    output(
        &out.join("gallery-image.png"),
        CartFace {
            rgba: a.rgba.clone(),
            w: a.w,
            h: a.h,
        },
        &b,
        1.0,
    );
    output(&out.join("gallery-image-hidden.png"), a, &b, 0.0);
    g.button(Btn::X, 200);
    g.release(Btn::X, 201);
    let (a, b) = frame(&mut g);
    output(&out.join("gallery-delete.png"), a, &b, 1.0);
}
