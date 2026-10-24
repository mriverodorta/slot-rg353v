use std::collections::hash_map::DefaultHasher;
use std::hash::Hasher;
use std::path::{Path, PathBuf};

#[allow(dead_code)]
#[path = "src/template_catalog.rs"]
mod template_catalog;
#[path = "src/template_pixels.rs"]
mod template_pixels;

fn files(path: &Path, out: &mut Vec<PathBuf>) {
    for entry in std::fs::read_dir(path).unwrap() {
        let p = entry.unwrap().path();
        if p.is_dir() {
            files(&p, out);
        } else {
            out.push(p);
        }
    }
}
fn main() {
    let mut sources = Vec::new();
    for directory in ["src", "assets", "../../assets", "../slot-store/src"] {
        files(Path::new(directory), &mut sources);
    }
    for name in ["build.rs", "../../Cargo.lock", "../slot/src/face_cache.rs"] {
        sources.push(PathBuf::from(name));
    }
    sources.sort();
    let (mut a, mut b) = (DefaultHasher::new(), DefaultHasher::new());
    b.write(b"slot-art-epoch-v1");
    for p in sources {
        println!("cargo:rerun-if-changed={}", p.display());
        let name = p.to_string_lossy();
        let bytes = std::fs::read(&p).unwrap();
        for h in [&mut a, &mut b] {
            h.write(&(name.len() as u64).to_le_bytes());
            h.write(name.as_bytes());
            h.write(&(bytes.len() as u64).to_le_bytes());
            h.write(&bytes);
        }
    }
    let compiler = std::process::Command::new(std::env::var_os("RUSTC").unwrap())
        .arg("--version")
        .output()
        .unwrap();
    a.write(&compiler.stdout);
    b.write(&compiler.stdout);
    println!(
        "cargo:rustc-env=SLOT_UI_ART_EPOCH={:016x}{:016x}",
        a.finish(),
        b.finish()
    );
    if std::env::var_os("CARGO_FEATURE_PREPARED_ART").is_none() {
        return;
    }
    let out = PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    let mut code =
        String::from("fn prepared(name: &str) -> Option<&'static [u8]> {\n    match name {\n");
    for t in template_catalog::ALL {
        let pixels = template_pixels::prepare(t.bytes, t.w, t.h).unwrap();
        let filename = format!("{}.lz4", t.name);
        std::fs::write(out.join(&filename), lz4_flex::block::compress(&pixels)).unwrap();
        code.push_str(&format!(
            "        {:?} => Some(include_bytes!(concat!(env!(\"OUT_DIR\"), \"/{}\"))),\n",
            t.name, filename
        ));
    }
    code.push_str("        _ => None,\n    }\n}\n");
    std::fs::write(out.join("prepared_templates.rs"), code).unwrap();
}
