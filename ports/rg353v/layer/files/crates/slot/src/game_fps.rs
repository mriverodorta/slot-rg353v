//! RG353V border HUD. Counts fresh game images after successful swaps.
use slot_gfx::{Compositor, Draw, TexId, OUT_H, OUT_W};
use std::time::Duration;

#[derive(Default)]
pub struct Meter {
    start: Option<Duration>,
    last_taken: u64,
    fresh: u64,
    tenths: Option<u16>,
}
impl Meter {
    pub fn reset(&mut self) {
        *self = Self::default();
    }
    pub fn tenths(&self) -> Option<u16> {
        self.tenths
    }
    pub fn presented(&mut self, now: Duration, active: bool, taken: u64) {
        if !active {
            self.reset();
            return;
        }
        let Some(start) = self.start else {
            self.start = Some(now);
            self.last_taken = taken;
            return;
        };
        if now < start || taken < self.last_taken {
            self.reset();
            self.start = Some(now);
            self.last_taken = taken;
            return;
        }
        self.fresh += u64::from(taken != self.last_taken);
        self.last_taken = taken;
        let elapsed = now - start;
        if elapsed >= Duration::from_secs(1) {
            self.tenths = Some(
                (self.fresh as f64 * 10.0 / elapsed.as_secs_f64())
                    .round()
                    .clamp(0.0, 9999.0) as u16,
            );
            // Opt-in sample logging is independent of digit texture uploads:
            // a stable 60 must still produce a complete profiling time series.
            static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
            if *TRACE.get_or_init(|| std::env::var_os("SLOT_TRACE_FRAME_SAMPLES").is_some()) {
                eprintln!(
                    "slot: frame sample: fresh={} elapsed_ns={} rate={:.3}",
                    self.fresh,
                    elapsed.as_nanos(),
                    self.fresh as f64 / elapsed.as_secs_f64()
                );
            }
            self.start = Some(now);
            self.fresh = 0;
        }
    }
}

pub const WIDTH: u32 = 31;
pub const HEIGHT: u32 = 13;
pub const MARGIN: u32 = 3;

/// Round the measured rate for display; keep the meter's higher precision.
pub fn integer(tenths: Option<u16>) -> Option<u16> {
    tenths.map(|n| ((u32::from(n) + 5) / 10).min(999) as u16)
}

/// Three right-aligned integer digits, without a unit label or decimal point.
pub fn face(value: Option<u16>) -> Vec<u8> {
    let value = value.map_or_else(|| "--".to_owned(), |n| n.min(999).to_string());
    let label = format!("{value:>3}");
    let mut rgba = vec![0; (WIDTH * HEIGHT * 4) as usize];
    for (at, ch) in label.chars().take(3).enumerate() {
        let rows = match ch {
            '0' => [14, 17, 19, 21, 25, 17, 14],
            '1' => [4, 12, 4, 4, 4, 4, 14],
            '2' => [14, 17, 1, 2, 4, 8, 31],
            '3' => [30, 1, 1, 14, 1, 1, 30],
            '4' => [2, 6, 10, 18, 31, 2, 2],
            '5' => [31, 16, 16, 30, 1, 1, 30],
            '6' => [14, 16, 16, 30, 17, 17, 14],
            '7' => [31, 1, 2, 4, 8, 8, 8],
            '8' => [14, 17, 17, 14, 17, 17, 14],
            '9' => [14, 17, 17, 15, 1, 1, 14],
            '-' => [0, 0, 0, 31, 0, 0, 0],
            _ => [0; 7],
        };
        // Rasterize directly at 13 native pixels; no filtered text resizing.
        for y in 0..HEIGHT {
            for x in 0..9 {
                if rows[(y * 7 / HEIGHT) as usize] & (1 << (4 - x * 5 / 9)) == 0 {
                    continue;
                }
                let px = at as u32 * 11 + x;
                let p = ((y * WIDTH + px) * 4) as usize;
                rgba[p..p + 4].copy_from_slice(&[255; 4]);
            }
        }
    }
    rgba
}

/// Scene coordinates for a native-pixel HUD on the fixed physical panel.
pub fn placement(panel: (u32, u32)) -> Option<(f32, f32, f32, f32)> {
    if panel != (640, 480) {
        return None;
    }
    let sx = OUT_W as f32 / panel.0 as f32;
    let sy = OUT_H as f32 / panel.1 as f32;
    Some((
        (panel.0 - MARGIN - WIDTH) as f32 * sx,
        (panel.1 - MARGIN - HEIGHT) as f32 * sy,
        WIDTH as f32 * sx,
        HEIGHT as f32 * sy,
    ))
}

#[derive(Default)]
pub struct Hud {
    pub meter: Meter,
    texture: Option<TexId>,
    uploaded: Option<Option<u16>>,
}
impl Hud {
    pub fn draw(&mut self, c: &mut Compositor, panel: (u32, u32)) {
        let Some((x, y, w, h)) = placement(panel) else {
            return;
        };
        let value = integer(self.meter.tenths());
        if self.uploaded != Some(value) {
            static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
            if *TRACE.get_or_init(|| std::env::var_os("SLOT_TRACE_FPS").is_some()) {
                eprintln!("slot: fps: {:?} whole", value);
            }
            let pixels = face(value);
            match self.texture {
                Some(id) => c.update_texture(id, WIDTH, HEIGHT, &pixels),
                None => self.texture = Some(c.create_texture_nearest(WIDTH, HEIGHT, &pixels)),
            }
            self.uploaded = Some(value);
        }
        if let Some(tex) = self.texture {
            c.draw_panel_overlay(
                panel,
                &[Draw::Tex {
                    x,
                    y,
                    w,
                    h,
                    tex,
                    alpha: 1.0,
                }],
            );
        }
    }
}
