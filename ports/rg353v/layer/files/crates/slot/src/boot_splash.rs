//! First-boot handoff from the framebuffer splash to Slot's GLES display.
use std::io::{self, Write};
use std::path::Path;
use std::time::{Duration, Instant};

use slot_gfx::{Compositor, Surface, TexId};

const ROOT: &str = "/run/slot-boot";
const FRAME_BYTES: usize = 640 * 480 * 4;

pub fn enabled() -> bool {
    std::env::var_os("SLOT_BOOT_SPLASH").is_some()
        && Path::new(ROOT).join("events").is_dir()
        && !Path::new(ROOT).join("frontend.displayed").exists()
        && !Path::new(ROOT).join("failed").exists()
}

pub fn mark(phase: &str) {
    // A normal frontend restart also needs to retire a splash left by an older
    // frontend in this boot. Only run after the actual first scene was swapped.
    if phase == "first frame" && std::env::var_os("SLOT_BOOT_SPLASH").is_some() {
        if enabled() {
            let _ = std::fs::write(Path::new(ROOT).join("handoff"), b"ready\n");
            let _ = std::fs::write(Path::new(ROOT).join("frontend.displayed"), b"ready\n");
        }
        match clear_retired_framebuffer(
            Path::new(ROOT),
            Path::new("/sys/class/graphics/fb0"),
            Path::new("/dev/fb0"),
        ) {
            Ok(true) => eprintln!("slot: boot: retired console framebuffer cleared"),
            Ok(false) => {}
            Err(error) => eprintln!("slot: boot: could not clear retired framebuffer: {error}"),
        }
        return;
    }
    if !enabled() {
        return;
    }
    let root = Path::new(ROOT);
    if matches!(
        phase,
        "start"
            | "surface"
            | "compositor"
            | "platform"
            | "audio"
            | "frontend"
            | "faces"
            | "bezel"
            | "input"
            | "ready"
    ) {
        let _ = std::fs::write(root.join("events").join(format!("frontend-{phase}")), b"");
    }
}

// fbdev's console buffer is separate from Slot's GBM scanout. Keeping its last
// boot image lets DRM teardown expose that image again at shutdown. Clear all
// advertised virtual rows, including a possible panned page, without changing
// console mode, blanking the panel, or taking DRM ownership from Slot.
fn clear_retired_framebuffer(root: &Path, graphics: &Path, framebuffer: &Path) -> io::Result<bool> {
    if !["handoff", "frontend.displayed", "renderer.stopped"]
        .iter()
        .all(|name| root.join(name).exists())
        || root.join("failed").exists()
    {
        return Ok(false);
    }
    let dimensions = std::fs::read_to_string(graphics.join("virtual_size"))?;
    let Some((width, height)) = dimensions.trim().split_once(',') else {
        return Ok(false);
    };
    let width = width.parse::<usize>().unwrap_or(0);
    let height = height.parse::<usize>().unwrap_or(0);
    let stride = std::fs::read_to_string(graphics.join("stride"))?
        .trim()
        .parse::<usize>()
        .unwrap_or(0);
    let bits = std::fs::read_to_string(graphics.join("bits_per_pixel"))?;
    let Some(bytes) = stride.checked_mul(height) else {
        return Ok(false);
    };
    if width != 640
        || !(480..=1920).contains(&height)
        || bits.trim() != "32"
        || !(640 * 4..=8192).contains(&stride)
        || bytes > 16 * 1024 * 1024
    {
        return Ok(false);
    }
    // Open an existing device only: never create/truncate a path on error.
    let mut output = std::fs::OpenOptions::new().write(true).open(framebuffer)?;
    let black = [0; 8192];
    let mut remaining = bytes;
    while remaining != 0 {
        let n = remaining.min(black.len());
        output.write_all(&black[..n])?;
        remaining -= n;
    }
    Ok(true)
}

pub struct Splash {
    texture: TexId,
    complete: Vec<u8>,
}

impl Splash {
    pub fn new(compositor: &mut Compositor) -> Option<Self> {
        if !enabled() || Path::new(ROOT).join("handoff").exists() {
            return None;
        }
        let complete = std::fs::read("/usr/share/slot/boot-complete.rgba").ok()?;
        if complete.len() != FRAME_BYTES {
            return None;
        }
        let texture = compositor.create_texture(640, 480, &complete);
        Some(Self { texture, complete })
    }

    pub fn refresh(
        &self,
        compositor: &mut Compositor,
        surface: &mut dyn Surface,
        window: (u32, u32),
    ) {
        if let Ok(frame) = std::fs::read(Path::new(ROOT).join("frame.rgba")) {
            if frame.len() == FRAME_BYTES {
                compositor.update_texture(self.texture, 640, 480, &frame);
                compositor.draw_boot_image(window, self.texture);
                let _ = surface.swap();
            }
        }
    }

    pub fn finish(
        self,
        compositor: &mut Compositor,
        surface: &mut dyn Surface,
        window: (u32, u32),
    ) {
        mark("ready");
        let _ = std::fs::write(Path::new(ROOT).join("handoff"), b"ready\n");
        let start = Instant::now();
        while !Path::new(ROOT).join("renderer.stopped").exists()
            && start.elapsed() < Duration::from_millis(250)
        {
            std::thread::sleep(Duration::from_millis(5));
        }
        compositor.update_texture(self.texture, 640, 480, &self.complete);
        compositor.draw_boot_image(window, self.texture);
        // One latched 100% frame is enough; no fixed presentation delay belongs
        // on the shelf's critical path.
        let _ = surface.swap();
        compositor.update_texture(self.texture, 1, 1, &[0, 0, 0, 0]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        std::fs::create_dir(root.join("graphics")).unwrap();
        std::fs::write(root.join("graphics/virtual_size"), "640,960\n").unwrap();
        std::fs::write(root.join("graphics/stride"), "2624\n").unwrap();
        std::fs::write(root.join("graphics/bits_per_pixel"), "32\n").unwrap();
        for name in ["handoff", "frontend.displayed", "renderer.stopped"] {
            std::fs::write(root.join(name), b"").unwrap();
        }
        std::fs::write(root.join("fb"), vec![0x7f; 2624 * 960 + 64]).unwrap();
        dir
    }

    fn clear(root: &Path) -> io::Result<bool> {
        clear_retired_framebuffer(root, &root.join("graphics"), &root.join("fb"))
    }

    #[test]
    fn retired_console_pages_are_black_before_drm_teardown() {
        let dir = fixture();
        assert!(clear(dir.path()).unwrap());
        let data = std::fs::read(dir.path().join("fb")).unwrap();
        assert!(data[..2624 * 960].iter().all(|byte| *byte == 0));
        assert_eq!(&data[2624 * 960..], &[0x7f; 64]);
    }

    #[test]
    fn active_boot_and_error_console_are_never_cleared() {
        let dir = fixture();
        for name in ["handoff", "frontend.displayed", "renderer.stopped"] {
            std::fs::remove_file(dir.path().join(name)).unwrap();
            assert!(!clear(dir.path()).unwrap());
            std::fs::write(dir.path().join(name), b"").unwrap();
        }
        std::fs::write(dir.path().join("failed"), b"").unwrap();
        assert!(!clear(dir.path()).unwrap());
        assert!(std::fs::read(dir.path().join("fb"))
            .unwrap()
            .iter()
            .all(|b| *b == 0x7f));
    }

    #[test]
    fn unsupported_geometry_does_not_touch_the_framebuffer() {
        for (name, value) in [
            ("virtual_size", "320,240"),
            ("virtual_size", "640,99999999999999999999999999"),
            ("virtual_size", "640,broken"),
            ("stride", "1"),
            ("stride", "18446744073709551615"),
            ("bits_per_pixel", "16"),
        ] {
            let dir = fixture();
            std::fs::write(dir.path().join("graphics").join(name), value).unwrap();
            assert!(!clear(dir.path()).unwrap());
            assert!(std::fs::read(dir.path().join("fb"))
                .unwrap()
                .iter()
                .all(|b| *b == 0x7f));
        }
    }

    #[test]
    fn missing_framebuffer_is_not_created() {
        let dir = fixture();
        std::fs::remove_file(dir.path().join("fb")).unwrap();
        assert_eq!(
            clear(dir.path()).unwrap_err().kind(),
            io::ErrorKind::NotFound
        );
        assert!(!dir.path().join("fb").exists());
    }
}
