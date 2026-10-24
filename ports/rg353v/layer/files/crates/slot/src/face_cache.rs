//! Disposable rendered pixels; never a source of game, settings or executable data.
use slot_store::Cart;
use slot_ui::CartFace;
use std::collections::hash_map::DefaultHasher;
use std::fs::{File, OpenOptions};
use std::hash::Hasher;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

const HEAD: usize = 64;
const MAX: u64 = 2 << 20;
const MAGIC: &[u8; 8] = b"SLOTFCE1";
static SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn fingerprint(bytes: &[u8]) -> [u8; 16] {
    let (mut a, mut b) = (DefaultHasher::new(), DefaultHasher::new());
    a.write(bytes);
    b.write(b"slot-face-pixels-v1");
    b.write(bytes);
    let mut out = [0; 16];
    out[..8].copy_from_slice(&a.finish().to_le_bytes());
    out[8..].copy_from_slice(&b.finish().to_le_bytes());
    out
}
fn stamp(cart: &Cart) -> Option<[u8; 16]> {
    // Full label contents catch replacements with equal sizes/timestamps.
    // The header supplies every ROM field used to choose the cartridge shell.
    let mut key = format!("{}\n{cart:?}", slot_ui::ART_EPOCH).into_bytes();
    let mut header = Vec::new();
    File::open(&cart.rom)
        .ok()?
        .take(0x150)
        .read_to_end(&mut header)
        .ok()?;
    key.extend_from_slice(&header);
    if let Some(label) = &cart.label {
        match File::open(label) {
            Ok(file) => {
                let mut bytes = Vec::new();
                file.take((16 << 20) + 1).read_to_end(&mut bytes).ok()?;
                if bytes.len() > 16 << 20 {
                    return None;
                }
                key.extend_from_slice(&fingerprint(&bytes));
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                key.extend_from_slice(b"no-label")
            }
            Err(_) => return None,
        }
    }
    Some(fingerprint(&key))
}
fn path(root: &Path, cart: &Cart) -> PathBuf {
    let id = fingerprint(format!("{:?}:{}", cart.platform, cart.rom.display()).as_bytes());
    let name = id.iter().map(|v| format!("{v:02x}")).collect::<String>();
    root.join("System/Cache/Faces").join(name + ".face")
}
fn read(path: &Path, key: [u8; 16]) -> Option<CartFace> {
    use std::os::unix::fs::OpenOptionsExt;
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .ok()?;
    let metadata = file.metadata().ok()?;
    if !metadata.is_file() {
        return None;
    }
    let len = metadata.len();
    if !(HEAD as u64..=MAX).contains(&len) {
        return None;
    }
    let mut bytes = Vec::new();
    file.take(MAX + 1).read_to_end(&mut bytes).ok()?;
    if bytes.len() != len as usize || bytes.get(..8)? != MAGIC || bytes.get(8..24)? != key {
        return None;
    }
    let w = u32::from_le_bytes(bytes.get(24..28)?.try_into().ok()?);
    let h = u32::from_le_bytes(bytes.get(28..32)?.try_into().ok()?);
    if !matches!((w, h), (360, 212) | (312, 337)) {
        return None;
    }
    if bytes[48..HEAD].iter().any(|b| *b != 0) || bytes[32..48] != fingerprint(&bytes[HEAD..]) {
        return None;
    }
    let rgba = lz4_flex::block::decompress(&bytes[HEAD..], (w * h * 4) as usize).ok()?;
    if rgba.len() != (w * h * 4) as usize {
        return None;
    }
    Some(CartFace { rgba, w, h })
}
fn write(path: &Path, key: [u8; 16], face: &CartFace) -> std::io::Result<()> {
    let parent = path.parent().unwrap();
    std::fs::create_dir_all(parent)?;
    let compressed = lz4_flex::block::compress(&face.rgba);
    let mut bytes = Vec::with_capacity(HEAD + compressed.len());
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&key);
    bytes.extend_from_slice(&face.w.to_le_bytes());
    bytes.extend_from_slice(&face.h.to_le_bytes());
    bytes.extend_from_slice(&fingerprint(&compressed));
    bytes.resize(HEAD, 0);
    bytes.extend_from_slice(&compressed);
    let temp = parent.join(format!(
        ".face-{}-{}.tmp",
        std::process::id(),
        SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let result = (|| {
        let mut f = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        f.write_all(&bytes)?;
        drop(f);
        std::fs::rename(&temp, path)
    })();
    let _ = std::fs::remove_file(&temp);
    result
}
pub fn render(root: &Path, cart: &Cart) -> CartFace {
    let key = stamp(cart);
    let cached = path(root, cart);
    if let Some(key) = key {
        if let Some(face) = read(&cached, key) {
            if crate::latency::tracing() {
                eprintln!("slot: face cache hit: {}", cart.stem);
            }
            return face;
        }
    }
    // Use current artwork directly on a miss, rather than a legacy mtime cache.
    if crate::latency::tracing() {
        eprintln!("slot: face cache miss: {}", cart.stem);
    }
    let face = slot_ui::cart_face(cart);
    if let Some(key) = key.filter(|key| Some(*key) == stamp(cart)) {
        let _ = write(&cached, key, &face);
    }
    face
}

// Cache files have one fixed filename per game, so edits replace rather than
// accumulate versions. Removed games are reclaimed under a bounded idle budget.
pub fn maintain(root: &Path) {
    static STARTED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
    if STARTED.swap(true, Ordering::Relaxed) {
        return;
    }
    let dir = root.join("System/Cache/Faces");
    let _ = std::thread::Builder::new()
        .name("slot-art-prune".into())
        .spawn(move || {
            let Ok(entries) = std::fs::read_dir(&dir) else {
                return;
            };
            let mut rows: Vec<_> = entries
                .filter_map(Result::ok)
                .filter_map(|e| {
                    let p = e.path();
                    if p.file_name()?.to_str()?.starts_with(".face-")
                        && p.extension()?.to_str()? == "tmp"
                    {
                        if e.metadata()
                            .ok()?
                            .modified()
                            .ok()?
                            .elapsed()
                            .ok()?
                            .as_secs()
                            > 600
                        {
                            let _ = std::fs::remove_file(&p);
                        }
                        return None;
                    }
                    if p.extension()?.to_str()? != "face" {
                        return None;
                    }
                    let m = e.metadata().ok()?;
                    if !m.is_file() {
                        return None;
                    }
                    Some((m.modified().ok()?, m.len(), p))
                })
                .collect();
            let mut total = rows.iter().fold(0u64, |sum, r| sum.saturating_add(r.1));
            if total <= 64 << 20 {
                return;
            }
            rows.sort_by_key(|r| r.0);
            for (_, len, p) in rows {
                if total <= 48 << 20 {
                    break;
                }
                if std::fs::remove_file(p).is_ok() {
                    total = total.saturating_sub(len);
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    fn cart(root: &Path) -> Cart {
        let rom = root.join("test.gba");
        std::fs::write(&rom, vec![0; 0x150]).unwrap();
        Cart {
            platform: slot_store::Platform::Gba,
            stem: "Test".into(),
            rom,
            label: None,
            title: "Test".into(),
            code: String::new(),
            shell: None,
        }
    }
    #[test]
    fn all_console_shells_and_real_label_replacements_remain_pixel_exact() {
        let dir = tempfile::tempdir().unwrap();
        let mut cart = cart(dir.path());
        for platform in [
            slot_store::Platform::Gba,
            slot_store::Platform::Gb,
            slot_store::Platform::Gbc,
        ] {
            cart.platform = platform;
            for shell in [
                None,
                slot_store::ShellChoice::parse("rounded 32a0e0 clear"),
                slot_store::ShellChoice::parse("notched da4020 glitter"),
            ] {
                cart.shell = shell;
                let source = slot_ui::cart_face(&cart);
                assert_eq!(render(dir.path(), &cart).rgba, source.rgba);
                assert_eq!(render(dir.path(), &cart).rgba, source.rgba);
            }
        }
        let label = dir.path().join("portrait.png");
        cart.label = Some(label.clone());
        let mut previous = None;
        for colour in [[220u8, 40, 80], [40u8, 220, 80]] {
            let file = File::create(&label).unwrap();
            let mut enc = png::Encoder::new(file, 32, 32);
            enc.set_color(png::ColorType::Rgb);
            enc.set_filter(png::FilterType::NoFilter);
            enc.write_header()
                .unwrap()
                .write_image_data(&colour.repeat(32 * 32))
                .unwrap();
            let file = File::options().write(true).open(&label).unwrap();
            file.set_times(
                std::fs::FileTimes::new().set_modified(
                    std::time::UNIX_EPOCH + std::time::Duration::from_secs(123456789),
                ),
            )
            .unwrap();
            let face = render(dir.path(), &cart);
            assert_eq!(face.rgba, slot_ui::cart_face(&cart).rgba);
            if let Some(before) = previous {
                assert_ne!(face.rgba, before);
            }
            previous = Some(face.rgba);
        }
    }

    #[test]
    fn cached_pixels_equal_original_and_corruption_is_rebuilt() {
        let dir = tempfile::tempdir().unwrap();
        let cart = cart(dir.path());
        let expected = slot_ui::cart_face(&cart);
        let first = render(dir.path(), &cart);
        assert_eq!(first.rgba, expected.rgba);
        let file = path(dir.path(), &cart);
        let mut bytes = std::fs::read(&file).unwrap();
        assert_eq!(render(dir.path(), &cart).rgba, expected.rgba);
        bytes[HEAD + 5] ^= 1;
        std::fs::write(&file, bytes).unwrap();
        assert_eq!(render(dir.path(), &cart).rgba, expected.rgba);
        assert!(read(&file, stamp(&cart).unwrap()).is_some());
    }
    #[test]
    fn label_shell_and_header_changes_invalidate_without_relying_on_mtime() {
        let dir = tempfile::tempdir().unwrap();
        let mut cart = cart(dir.path());
        let before = stamp(&cart).unwrap();
        let label = dir.path().join("label.png");
        std::fs::write(&label, b"equal-size-A").unwrap();
        cart.label = Some(label.clone());
        let a = stamp(&cart).unwrap();
        assert_ne!(a, before);
        std::fs::write(&label, b"equal-size-B").unwrap();
        assert_ne!(stamp(&cart).unwrap(), a);
        let a = stamp(&cart).unwrap();
        cart.title = "Different".into();
        assert_ne!(stamp(&cart).unwrap(), a);
        let a = stamp(&cart).unwrap();
        let mut header = vec![0; 0x150];
        header[0x143] = 0x80;
        std::fs::write(&cart.rom, header).unwrap();
        assert_ne!(stamp(&cart).unwrap(), a);
    }
    #[test]
    fn malformed_or_truncated_cache_never_controls_dimensions() {
        let dir = tempfile::tempdir().unwrap();
        let cart = cart(dir.path());
        let file = path(dir.path(), &cart);
        let face = render(dir.path(), &cart);
        let original = std::fs::read(&file).unwrap();
        for length in [0, 7, HEAD - 1, HEAD, original.len() - 1] {
            std::fs::write(&file, &original[..length]).unwrap();
            assert!(read(&file, stamp(&cart).unwrap()).is_none());
        }
        let short = lz4_flex::block::compress(&[1, 2, 3, 4]);
        let mut bytes = original[..HEAD].to_vec();
        bytes[32..48].copy_from_slice(&fingerprint(&short));
        bytes.extend_from_slice(&short);
        std::fs::write(&file, bytes).unwrap();
        assert!(read(&file, stamp(&cart).unwrap()).is_none());
        let mut bytes = original.clone();
        bytes[24..28].copy_from_slice(&u32::MAX.to_le_bytes());
        std::fs::write(&file, bytes).unwrap();
        assert!(read(&file, stamp(&cart).unwrap()).is_none());
        std::fs::remove_file(&file).unwrap();
        std::fs::create_dir(&file).unwrap();
        assert_eq!(render(dir.path(), &cart).rgba, face.rgba);
    }
}
