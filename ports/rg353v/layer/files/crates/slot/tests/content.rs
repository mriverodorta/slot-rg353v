use slot::content::{Catalog, Refresh};
use slot_gfx::TexId;
use slot_store::Platform;
use std::collections::BTreeSet;
use std::path::Path;
fn root() -> tempfile::TempDir {
    let d = tempfile::tempdir().unwrap();
    for dir in [
        "Config",
        "Games/GBA",
        "Games/GB",
        "Labels/GBA",
        "Wallpapers",
    ] {
        std::fs::create_dir_all(d.path().join(dir)).unwrap();
    }
    d
}
fn gba(path: &Path) {
    let mut b = vec![0; 1024];
    b[3] = 0xea;
    b[0xb2] = 0x96;
    std::fs::write(path, b).unwrap();
}
fn png(path: &Path, rgb: [u8; 3]) {
    let f = std::fs::File::create(path).unwrap();
    let mut e = png::Encoder::new(f, 2, 2);
    e.set_color(png::ColorType::Rgb);
    e.write_header()
        .unwrap()
        .write_image_data(&rgb.repeat(4))
        .unwrap();
}
fn settle(c: &mut Catalog, p: &Path) -> Refresh {
    assert!(c.poll(p).unwrap().is_none());
    c.poll(p).unwrap().unwrap()
}
#[test]
fn additions_deletions_are_debounced() {
    let d = root();
    let mut c = Catalog::default();
    assert!(settle(&mut c, d.path()).carts.is_empty());
    let p = d.path().join("Games/GBA/Test.gba");
    gba(&p);
    assert_eq!(settle(&mut c, d.path()).carts.len(), 1);
    assert!(c.poll(d.path()).unwrap().is_none());
    std::fs::remove_file(p).unwrap();
    assert!(settle(&mut c, d.path()).carts.is_empty());
}
#[test]
fn short_copy_is_rejected_then_repaired() {
    let d = root();
    let mut c = Catalog::default();
    settle(&mut c, d.path());
    let p = d.path().join("Games/GBA/Copy.gba");
    std::fs::write(&p, b"partial").unwrap();
    let r = settle(&mut c, d.path());
    assert!(r.carts.is_empty());
    assert_eq!(r.issues.len(), 1);
    gba(&p);
    let r = settle(&mut c, d.path());
    assert_eq!(r.carts.len(), 1);
    assert!(r.issues.is_empty());
}
#[test]
fn metadata_and_staging_are_silent() {
    let d = root();
    for n in [
        "._Test.gba",
        ".DS_Store",
        "copy.gba.part",
        "copy.tmp",
        "copy.filepart",
    ] {
        std::fs::write(d.path().join("Games/GBA").join(n), b"x").unwrap();
    }
    let r = settle(&mut Catalog::default(), d.path());
    assert!(r.carts.is_empty());
    assert!(r.issues.is_empty());
}
#[test]
fn same_name_and_mtime_image_replacement_is_detected() {
    let d = root();
    let mut c = Catalog::default();
    let p = d.path().join("Wallpapers/Blue.PNG");
    png(&p, [255, 0, 0]);
    let t = std::fs::metadata(&p).unwrap().modified().unwrap();
    assert_eq!(settle(&mut c, d.path()).wallpapers, vec!["Blue.PNG"]);
    png(&p, [0, 0, 255]);
    std::fs::File::options()
        .write(true)
        .open(&p)
        .unwrap()
        .set_times(std::fs::FileTimes::new().set_modified(t))
        .unwrap();
    assert!(settle(&mut c, d.path()).changed_wallpapers.contains(&p));
}
#[test]
fn invalid_replacement_keeps_valid_cache_and_reports_until_fixed() {
    let d = root();
    let mut c = Catalog::default();
    gba(&d.path().join("Games/GBA/Test.gba"));
    let p = d.path().join("Labels/GBA/Test.png");
    png(&p, [255, 0, 0]);
    let r = settle(&mut c, d.path());
    let cart = r.carts[0].clone();
    let art = slot::label_cache::label_art(d.path(), &cart).unwrap();
    let cache = std::fs::read(slot::label_cache::cache_path(d.path(), &cart)).unwrap();
    std::fs::write(&p, b"bad").unwrap();
    let r = settle(&mut c, d.path());
    assert_eq!(r.issues.len(), 1);
    assert!(r.changed_labels.is_empty());
    assert_eq!(
        slot::label_cache::label_art(d.path(), &r.carts[0]),
        Some(art)
    );
    assert_eq!(
        std::fs::read(slot::label_cache::cache_path(d.path(), &cart)).unwrap(),
        cache
    );
    gba(&d.path().join("Games/GBA/Other.gba"));
    assert_eq!(settle(&mut c, d.path()).issues.len(), 1);
    png(&p, [0, 255, 0]);
    let r = settle(&mut c, d.path());
    assert!(r.issues.is_empty());
    assert!(r.changed_labels.contains(&p));
}
#[test]
fn bad_files_and_missing_mount_report_errors() {
    let d = root();
    std::fs::write(d.path().join("Games/GBA/Zipped.zip"), b"zip").unwrap();
    std::fs::write(d.path().join("Wallpapers/Bad.png"), b"bad").unwrap();
    let mut c = Catalog::default();
    let r = settle(&mut c, d.path());
    assert_eq!(r.issues.len(), 2);
    assert!(r.wallpapers.is_empty());
    assert!(
        std::fs::read_to_string(d.path().join("Diagnostics/content.log"))
            .unwrap()
            .contains("Invalid PNG")
    );
    std::fs::rename(d.path().join("Games"), d.path().join("Games.off")).unwrap();
    assert!(c.poll(d.path()).is_err());
}
#[test]
fn gb_size_field_rejects_incomplete_roms() {
    let d = root();
    let mut b = vec![0; 0x150];
    b[0x148] = 1;
    let p = d.path().join("Games/GB/Game.gb");
    std::fs::write(&p, &b).unwrap();
    let mut c = Catalog::default();
    assert!(settle(&mut c, d.path()).carts.is_empty());
    b.resize(65536, 0);
    std::fs::write(&p, b).unwrap();
    assert_eq!(settle(&mut c, d.path()).carts[0].platform, Platform::Gb);
}
#[test]
fn shelf_preserves_selection_faces_and_nearest_survivor() {
    let d = root();
    for n in ["A", "B", "C"] {
        gba(&d.path().join(format!("Games/GBA/{n}.gba")));
    }
    let carts = settle(&mut Catalog::default(), d.path()).carts;
    let mut s = slot_ui::Shelf::new(carts.clone());
    s.select(1);
    s.set_face(1, TexId::from_raw(42));
    let mut next = carts;
    next.remove(0);
    assert!(s.refresh(next.clone(), &BTreeSet::new()).is_empty());
    assert_eq!(s.index, 0);
    assert_eq!(s.carts[0].stem, "B");
    assert_eq!(s.face(0), Some(TexId::from_raw(42)));
    next.remove(0);
    assert_eq!(s.refresh(next, &BTreeSet::new()), vec![TexId::from_raw(42)]);
    assert_eq!(s.carts[s.index].stem, "C");
    s.refresh(Vec::new(), &BTreeSet::new());
    assert_eq!(s.index, 0);
}

#[test]
fn a_png_with_missing_end_chunk_is_rejected_and_recovers() {
    let d = root();
    let p = d.path().join("Wallpapers/Copy.png");
    png(&p, [10, 20, 30]);
    let bytes = std::fs::read(&p).unwrap();
    std::fs::write(&p, &bytes[..bytes.len() - 12]).unwrap();
    let mut c = Catalog::default();
    let r = settle(&mut c, d.path());
    assert!(r.wallpapers.is_empty());
    assert_eq!(r.issues.len(), 1);
    std::fs::write(&p, bytes).unwrap();
    let r = settle(&mut c, d.path());
    assert_eq!(r.wallpapers, vec!["Copy.png"]);
    assert!(r.issues.is_empty());
}

#[test]
fn mac_unsafe_stem_warns_without_hiding_progress_and_clears_after_repair() {
    let d = root();
    let bad = d.path().join("Games/GBA/Zelda .gba");
    gba(&bad);
    let mut c = Catalog::default();
    let r = settle(&mut c, d.path());
    assert_eq!(r.carts[0].stem, "Zelda ");
    assert_eq!(r.issues.len(), 1);
    assert!(r.issues[0].contains("slot-fix-mac-names"));
    gba(&d.path().join("Games/GBA/Other.gba"));
    let r = settle(&mut c, d.path());
    assert_eq!(r.carts.len(), 2);
    assert_eq!(r.issues.len(), 1);
    std::fs::rename(bad, d.path().join("Games/GBA/Zelda.gba")).unwrap();
    let r = settle(&mut c, d.path());
    assert_eq!(r.carts.len(), 2);
    assert!(r.issues.is_empty());
}

#[test]
fn removable_libraries_keep_local_settings_and_allow_games_without_config() {
    let local = root();
    let card = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(card.path().join("Games/GBA")).unwrap();
    std::fs::create_dir_all(card.path().join("Labels/GBA")).unwrap();
    gba(&local.path().join("Games/GBA/Local.gba"));
    gba(&card.path().join("Games/GBA/Card.gba"));
    png(&card.path().join("Labels/GBA/Card.png"), [255, 0, 0]);
    let roots = vec![card.path().to_path_buf()];
    let mut libraries = slot::content::Libraries::default();
    assert!(libraries
        .poll_roots(local.path(), &roots)
        .unwrap()
        .is_none());
    let r = libraries.poll_roots(local.path(), &roots).unwrap().unwrap();
    assert_eq!(r.carts.len(), 2);
    let game = r.carts.iter().find(|c| c.stem == "Card").unwrap();
    assert!(game.rom.starts_with(card.path()));
    assert!(game.label.as_ref().unwrap().starts_with(card.path()));
    assert!(!card.path().join("Diagnostics").exists());
    assert!(!card.path().join("Config").exists());
    let r = libraries.poll_roots(local.path(), &[]).unwrap().unwrap();
    assert_eq!(r.carts.len(), 1);
    assert_eq!(r.carts[0].stem, "Local");
}

#[test]
fn library_priority_prevents_ambiguous_shared_save_names() {
    let a = root();
    let b = root();
    gba(&a.path().join("Games/GBA/Same.gba"));
    gba(&b.path().join("Games/GBA/same.gba"));
    gba(&b.path().join("Games/GBA/Unique.gba"));
    let merged = slot_store::merge_libraries([
        slot_store::scan_library(a.path()).unwrap(),
        slot_store::scan_library(b.path()).unwrap(),
    ]);
    assert_eq!(merged.len(), 2);
    assert!(merged
        .iter()
        .find(|c| c.stem == "Same")
        .unwrap()
        .rom
        .starts_with(a.path()));
    assert!(merged.iter().any(|c| c.stem == "Unique"));
}

#[test]
fn disconnected_library_does_not_poison_reinserted_catalog() {
    let local = root();
    let card = root();
    gba(&local.path().join("Games/GBA/Local.gba"));
    gba(&card.path().join("Games/GBA/Card.gba"));
    let roots = vec![card.path().to_path_buf()];
    let mut libraries = slot::content::Libraries::default();
    for _ in 0..3 {
        libraries.poll_roots(local.path(), &roots).unwrap();
    }
    std::fs::rename(card.path().join("Games"), card.path().join("Hidden")).unwrap();
    assert_eq!(
        libraries
            .poll_roots(local.path(), &roots)
            .unwrap()
            .unwrap()
            .carts
            .len(),
        1
    );
    std::fs::rename(card.path().join("Hidden"), card.path().join("Games")).unwrap();
    assert!(libraries
        .poll_roots(local.path(), &roots)
        .unwrap()
        .is_none());
    assert_eq!(
        libraries
            .poll_roots(local.path(), &roots)
            .unwrap()
            .unwrap()
            .carts
            .len(),
        2
    );
}
