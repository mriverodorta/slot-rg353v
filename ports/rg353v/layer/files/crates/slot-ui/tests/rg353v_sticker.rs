use slot_ui::{rg353v_sticker_face, rg353v_sticker_lines, Rg353vStickerFields, RG353V_CREDITS};
fn fields() -> Rg353vStickerFields<'static> {
    Rg353vStickerFields {
        battery: Some(52),
        firmware: "os-20261019-game-start3",
        kernel: "7.0.2",
        frontend: "slot-20261019-about3",
    }
}
#[test]
fn current_device_versions_and_original_credits_are_present() {
    let lines = rg353v_sticker_lines(&fields()).join("\n");
    for text in [
        "RG353V",
        "RK3566",
        "52%",
        "os-20261019-game-start3",
        "7.0.2",
        "slot-20261019-about3",
        "BRANDON",
        "MARKUS",
        "MGBA",
        "GPSP",
        "RYAN",
        "GIGAHERZ",
        "1PLAYERINSERTCOIN",
        "MUGWOMP93",
        "RETRO GAME CORPS",
        "ROCKNIX",
    ] {
        assert!(lines.contains(text), "{text}");
    }
    for old in [
        "AGS-102",
        "BASEOS",
        "ITHACA",
        "5V",
        "SEE README",
        "S/LOT-USA",
    ] {
        assert!(!lines.contains(old), "{old}");
    }
    assert_eq!(RG353V_CREDITS.len(), 11);
}
#[test]
fn original_sticker_dimensions_and_unknown_battery_are_preserved() {
    let mut f = fields();
    f.battery = None;
    let lines = rg353v_sticker_lines(&f).join("\n");
    assert!(!lines.contains("0%"));
    let face = rg353v_sticker_face(&f);
    assert_eq!((face.w, face.h), (660, 228));
    assert_eq!(face.rgba.len(), 660 * 228 * 4);
    if let Ok(path) = std::env::var("SLOT_ABOUT_PREVIEW") {
        let file = std::fs::File::create(path).unwrap();
        let mut enc = png::Encoder::new(file, face.w, face.h);
        enc.set_color(png::ColorType::Rgba);
        enc.set_depth(png::BitDepth::Eight);
        enc.write_header()
            .unwrap()
            .write_image_data(&face.rgba)
            .unwrap();
    }
}

#[test]
fn all_ink_stays_inside_the_original_sticker_silhouette() {
    let mut decoder = png::Decoder::new(std::io::Cursor::new(include_bytes!(
        "../../../assets/sticker.png"
    )));
    decoder.set_transformations(png::Transformations::normalize_to_color8());
    let mut reader = decoder.read_info().unwrap();
    let mut bytes = vec![0; reader.output_buffer_size()];
    let info = reader.next_frame(&mut bytes).unwrap();
    assert_eq!(info.color_type, png::ColorType::Rgba);
    let original = &bytes[..info.buffer_size()];
    let face = rg353v_sticker_face(&fields());
    let mut outside = Vec::new();
    for (i, (a, b)) in original
        .chunks_exact(4)
        .zip(face.rgba.chunks_exact(4))
        .enumerate()
    {
        if a[3] < 250 && a[3] != b[3] {
            outside.push((i % 660, i / 660));
        }
    }
    assert!(
        outside.is_empty(),
        "Text or artwork outside label: {:?}",
        &outside[..outside.len().min(20)]
    );
}
