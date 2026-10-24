//! On-demand PNG capture storage. No scanning, worker or files at startup.
use slot_store::Platform;
use std::{
    fs::{self, File, OpenOptions},
    io::{self, BufReader, BufWriter, Write},
    path::{Path, PathBuf},
    thread::JoinHandle,
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Clone, Debug)]
pub struct Request {
    pub root: PathBuf,
    pub platform: Platform,
    pub game: String,
    pub shaders: bool,
    pub filters: bool,
    pub overlay: bool,
}
#[derive(Default)]
pub struct Writer {
    job: Option<JoinHandle<io::Result<PathBuf>>>,
}
impl Writer {
    pub fn busy(&self) -> bool {
        self.job.is_some()
    }
    pub fn save(&mut self, request: Request, w: u32, h: u32, rgba: Vec<u8>) {
        if self.busy() {
            return;
        }
        self.job = Some(std::thread::spawn(move || save(&request, w, h, &rgba)));
    }
    pub fn poll(&mut self) -> Option<io::Result<PathBuf>> {
        if !self.job.as_ref().is_some_and(|j| j.is_finished()) {
            return None;
        }
        Some(
            self.job
                .take()
                .unwrap()
                .join()
                .unwrap_or_else(|_| Err(io::Error::other("Capture worker stopped"))),
        )
    }
}
pub fn component(s: &str) -> String {
    let mut out = Vec::new();
    for (i, &b) in s.as_bytes().iter().enumerate() {
        if b < 32
            || b == 127
            || b"%/\\:*?\"<>|".contains(&b)
            || (i + 1 == s.len() && b" .".contains(&b))
        {
            out.extend_from_slice(format!("%{b:02X}").as_bytes());
        } else {
            out.push(b);
        }
    }
    format!("game-{}", String::from_utf8(out).unwrap_or_default())
}
pub fn game_name(s: &str) -> String {
    let b = s.strip_prefix("game-").unwrap_or(s).as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let Ok(n) =
                u8::from_str_radix(std::str::from_utf8(&b[i + 1..i + 3]).unwrap_or(""), 16)
            {
                out.push(n);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}
pub fn save(request: &Request, w: u32, h: u32, rgba: &[u8]) -> io::Result<PathBuf> {
    if w == 0 || h == 0 || w > 2048 || h > 2048 || rgba.len() != w as usize * h as usize * 4 {
        return Err(io::Error::other("Invalid capture dimensions"));
    }
    let base = request.root.join("Screenshots");
    // Never follow a computer-created link outside the content tree.
    let folder = base
        .join(request.platform.dir_name())
        .join(component(&request.game));
    let mut current = request.root.clone();
    for part in folder
        .strip_prefix(&request.root)
        .map_err(io::Error::other)?
        .components()
    {
        current.push(part);
        match fs::symlink_metadata(&current) {
            Ok(m) if m.file_type().is_symlink() || !m.is_dir() => {
                return Err(io::Error::other("Invalid screenshots directory"))
            }
            Ok(_) => {}
            Err(e) if e.kind() == io::ErrorKind::NotFound => fs::create_dir(&current)?,
            Err(e) => return Err(e),
        }
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(io::Error::other)?;
    let stem = format!(
        "{}-{:09}",
        slot_store::format_stamp(now.as_secs() as i64),
        now.subsec_nanos()
    );
    let tmp = folder.join(format!(".{stem}.partial"));
    let target = folder.join(format!("{stem}.png"));
    let result = (|| {
        let file = OpenOptions::new().write(true).create_new(true).open(&tmp)?;
        let mut output = BufWriter::new(file);
        {
            let mut encoder = png::Encoder::new(&mut output, w, h);
            encoder.set_color(png::ColorType::Rgba);
            encoder.set_depth(png::BitDepth::Eight);
            encoder
                .add_itxt_chunk("Game".into(), request.game.clone())
                .map_err(io::Error::other)?;
            encoder
                .add_text_chunk("Platform".into(), request.platform.dir_name().into())
                .map_err(io::Error::other)?;
            encoder
                .add_text_chunk("Shaders".into(), request.shaders.to_string())
                .map_err(io::Error::other)?;
            encoder
                .add_text_chunk("Filters".into(), request.filters.to_string())
                .map_err(io::Error::other)?;
            encoder
                .add_text_chunk("Overlay".into(), request.overlay.to_string())
                .map_err(io::Error::other)?;
            let mut writer = encoder.write_header().map_err(io::Error::other)?;
            writer.write_image_data(rgba).map_err(io::Error::other)?;
            writer.finish().map_err(io::Error::other)?;
        }
        output.flush()?;
        output.get_ref().sync_all()?;
        fs::rename(&tmp, &target)?;
        File::open(&folder)?.sync_all()?;
        Ok(target.clone())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&tmp);
    }
    result
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Entry {
    pub path: PathBuf,
    pub game: String,
    pub platform: String,
    pub date: String,
}
/// Only enumerate the three levels written by capture. Never recurse into links.
pub fn scan(root: &Path) -> io::Result<Vec<Entry>> {
    let base = root.join("Screenshots");
    let mut entries = Vec::new();
    if !base.exists() {
        return Ok(entries);
    }
    if fs::symlink_metadata(&base)?.file_type().is_symlink() {
        return Err(io::Error::other("Invalid screenshots directory"));
    }
    for platform in Platform::ALL {
        let p = base.join(platform.dir_name());
        if !p.is_dir() || fs::symlink_metadata(&p)?.file_type().is_symlink() {
            continue;
        }
        for dir in fs::read_dir(&p)? {
            let dir = dir?;
            if !dir.file_type()?.is_dir() {
                continue;
            }
            let game = game_name(&dir.file_name().to_string_lossy());
            for image in fs::read_dir(dir.path())? {
                let image = image?;
                if !image.file_type()?.is_file()
                    || image.path().extension().is_none_or(|e| e != "png")
                {
                    continue;
                }
                let filename = image.file_name().to_string_lossy().into_owned();
                let Some(date) = filename.get(..19) else {
                    continue;
                };
                if slot_store::parse_stamp(date).is_none() {
                    continue;
                }
                entries.push(Entry {
                    path: image.path(),
                    game: game.clone(),
                    platform: platform.dir_name().to_uppercase(),
                    date: filename,
                });
                if entries.len() >= 4096 {
                    return Ok(entries);
                }
            }
        }
    }
    Ok(entries)
}
pub fn read(path: &Path) -> io::Result<(u32, u32, Vec<u8>)> {
    if fs::symlink_metadata(path)?.file_type().is_symlink() {
        return Err(io::Error::other("Invalid screenshot"));
    }
    let mut decoder = png::Decoder::new(BufReader::new(File::open(path)?));
    decoder.set_transformations(png::Transformations::EXPAND | png::Transformations::STRIP_16);
    decoder.set_limits(png::Limits {
        bytes: 32 * 1024 * 1024,
    });
    let mut reader = decoder.read_info().map_err(io::Error::other)?;
    let info = reader.info();
    if info.width == 0 || info.height == 0 || info.width > 2048 || info.height > 2048 {
        return Err(io::Error::other("Screenshot too large"));
    }
    let mut bytes = vec![0; reader.output_buffer_size()];
    let info = reader.next_frame(&mut bytes).map_err(io::Error::other)?;
    bytes.truncate(info.buffer_size());
    let channels = info.color_type.samples();
    let mut rgba = Vec::with_capacity(info.width as usize * info.height as usize * 4);
    for pixel in bytes.chunks_exact(channels) {
        match info.color_type {
            png::ColorType::Rgba => rgba.extend_from_slice(pixel),
            png::ColorType::Rgb => rgba.extend_from_slice(&[pixel[0], pixel[1], pixel[2], 255]),
            png::ColorType::Grayscale => {
                rgba.extend_from_slice(&[pixel[0], pixel[0], pixel[0], 255])
            }
            png::ColorType::GrayscaleAlpha => {
                rgba.extend_from_slice(&[pixel[0], pixel[0], pixel[0], pixel[1]])
            }
            _ => return Err(io::Error::other("Unsupported screenshot")),
        }
    }
    Ok((info.width, info.height, rgba))
}
pub fn delete(root: &Path, entry: &Entry) -> io::Result<()> {
    let base = root.join("Screenshots").canonicalize()?;
    let path = entry.path.canonicalize()?;
    if !path.starts_with(&base) || fs::symlink_metadata(&entry.path)?.file_type().is_symlink() {
        return Err(io::Error::other("Invalid screenshot path"));
    }
    fs::remove_file(&entry.path)?;
    File::open(entry.path.parent().unwrap())?.sync_all()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn png_round_trip_metadata_scan_and_delete_preserve_other_content() {
        let t = tempfile::tempdir().unwrap();
        let request = Request {
            root: t.path().to_owned(),
            platform: Platform::Gba,
            game: "Zelda: 雨 / test. ".into(),
            shaders: true,
            filters: true,
            overlay: false,
        };
        let pixels = [
            255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 99, 88, 77, 255,
        ];
        let path = save(&request, 2, 2, &pixels).unwrap();
        assert_eq!(read(&path).unwrap(), (2, 2, pixels.to_vec()));
        let files = scan(t.path()).unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].game, request.game);
        assert_eq!(files[0].platform, "GBA");
        assert_eq!(game_name(&component(&request.game)), request.game);
        let reader = png::Decoder::new(File::open(&path).unwrap())
            .read_info()
            .unwrap();
        assert!(reader
            .info()
            .uncompressed_latin1_text
            .iter()
            .any(|x| x.keyword == "Filters" && x.text == "true"));
        fs::write(t.path().join("save.sav"), b"keep").unwrap();
        delete(t.path(), &files[0]).unwrap();
        assert!(scan(t.path()).unwrap().is_empty());
        assert_eq!(fs::read(t.path().join("save.sav")).unwrap(), b"keep");
    }
    #[cfg(unix)]
    #[test]
    fn symlink_capture_scan_and_delete_are_refused() {
        let t = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        std::os::unix::fs::symlink(outside.path(), t.path().join("Screenshots")).unwrap();
        let request = Request {
            root: t.path().to_owned(),
            platform: Platform::Gb,
            game: "game".into(),
            shaders: false,
            filters: false,
            overlay: false,
        };
        assert!(save(&request, 1, 1, &[0, 0, 0, 255]).is_err());
        assert!(scan(t.path()).is_err());
        assert!(fs::read_dir(outside.path()).unwrap().next().is_none());
    }
    #[test]
    fn malformed_and_oversized_images_do_not_allocate_unbounded_buffers() {
        let t = tempfile::tempdir().unwrap();
        let p = t.path().join("bad.png");
        fs::write(&p, b"not PNG").unwrap();
        assert!(read(&p).is_err());
        assert!(save(
            &Request {
                root: t.path().to_owned(),
                platform: Platform::Gb,
                game: "g".into(),
                shaders: false,
                filters: false,
                overlay: false
            },
            3000,
            3000,
            &[]
        )
        .is_err());
    }
}
