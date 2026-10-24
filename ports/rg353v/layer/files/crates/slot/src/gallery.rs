//! Gallery is opened explicitly. Catalogue, image decoding and deletion run on
//! a worker; GL textures are uploaded only on the frontend thread.
use crate::screenshots::{self, Entry};
use slot_gfx::{Draw, TexId, OUT_H, OUT_W};
use slot_input::Btn;
use slot_ui::CartFace;
use std::{path::PathBuf, thread::JoinHandle};
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum Sort {
    Game,
    Date,
    Platform,
}
impl Sort {
    pub fn cycle(self, right: bool) -> Self {
        let list = [Self::Game, Self::Date, Self::Platform];
        let at = list.iter().position(|x| *x == self).unwrap();
        list[(at + if right { 1 } else { 2 }) % 3]
    }
    pub fn label(self) -> &'static str {
        match self {
            Self::Game => "GAME",
            Self::Date => "DATE",
            Self::Platform => "PLATFORM",
        }
    }
}
pub fn sort(entries: &mut [Entry], by: Sort) {
    entries.sort_by(|a, b| {
        let newest = || b.date.cmp(&a.date).then(a.path.cmp(&b.path));
        match by {
            Sort::Game => a
                .game
                .to_lowercase()
                .cmp(&b.game.to_lowercase())
                .then(a.platform.cmp(&b.platform))
                .then_with(newest),
            Sort::Date => newest(),
            Sort::Platform => a
                .platform
                .cmp(&b.platform)
                .then(a.game.to_lowercase().cmp(&b.game.to_lowercase()))
                .then_with(newest),
        }
    });
}
struct Work {
    catalog: bool,
    removed: bool,
    revision: u64,
    entries: Vec<Entry>,
    frame: (CartFace, CartFace),
    error: Option<String>,
}
pub struct Gallery {
    root: PathBuf,
    entries: Vec<Entry>,
    pub selected: usize,
    pub sort: Sort,
    pub fullscreen: bool,
    pub confirm: bool,
    revision: u64,
    job: Option<JoinHandle<Work>>,
    dirty: bool,
    loaded: bool,
    delete: Option<Entry>,
    error: Option<String>,
    frame: Option<(CartFace, CartFace)>,
    textures: Option<(TexId, TexId)>,
    last_input: u64,
    fade_at: u64,
    fade_from: f32,
    held: Vec<Btn>,
}
impl Gallery {
    pub fn open(root: PathBuf, now: u64) -> Self {
        let mut g = Self {
            root,
            entries: vec![],
            selected: 0,
            sort: Sort::Date,
            fullscreen: false,
            confirm: false,
            revision: 0,
            job: None,
            dirty: true,
            loaded: false,
            delete: None,
            error: None,
            frame: None,
            textures: None,
            last_input: now,
            fade_at: now,
            fade_from: 1.0,
            held: vec![],
        };
        g.poll();
        g
    }
    pub fn len(&self) -> usize {
        self.entries.len()
    }
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
    pub fn refresh(&mut self) {
        self.loaded = false;
        self.changed();
    }
    pub fn alpha(&self, now: u64) -> f32 {
        if self.confirm {
            return 1.0;
        }
        let idle = if self.held.is_empty() {
            now.saturating_sub(self.last_input)
        } else {
            0
        };
        if idle <= 2000 {
            self.fade_from
                + (1.0 - self.fade_from)
                    * (now.saturating_sub(self.fade_at) as f32 / 150.0).min(1.0)
        } else {
            1.0 - (idle.saturating_sub(2000) as f32 / 250.0).min(1.0)
        }
    }
    pub fn activity(&mut self, now: u64) {
        self.fade_from = self.alpha(now);
        self.fade_at = now;
        self.last_input = now;
    }
    pub fn release(&mut self, b: Btn, now: u64) {
        self.held.retain(|x| *x != b);
        self.last_input = now;
    }
    fn changed(&mut self) {
        self.revision += 1;
        self.dirty = true;
    }
    pub fn button(&mut self, b: Btn, now: u64) -> bool {
        self.activity(now);
        if !self.held.contains(&b) {
            self.held.push(b);
        }
        if self.confirm {
            match b {
                Btn::B => {
                    self.confirm = false;
                    self.changed();
                }
                Btn::A if self.delete.is_none() => {
                    self.delete = self.entries.get(self.selected).cloned();
                    self.confirm = false;
                    self.changed();
                }
                _ => {}
            }
            return false;
        }
        if self.delete.is_some() {
            return false;
        }
        if b == Btn::B {
            if self.fullscreen {
                self.fullscreen = false;
                self.changed();
                return false;
            }
            return true;
        }
        if !self.fullscreen && matches!(b, Btn::L1 | Btn::R1) {
            let path = self.entries.get(self.selected).map(|e| e.path.clone());
            self.sort = self.sort.cycle(b == Btn::R1);
            sort(&mut self.entries, self.sort);
            self.selected = path
                .and_then(|p| self.entries.iter().position(|e| e.path == p))
                .unwrap_or(0);
            self.changed();
            return false;
        }
        if self.entries.is_empty() {
            return false;
        }
        match b {
            Btn::A => {
                self.fullscreen = true;
                self.changed();
            }
            Btn::X => {
                self.confirm = true;
                self.changed();
            }
            Btn::Left | Btn::Right | Btn::L1 | Btn::R1 | Btn::Up | Btn::Down => {
                let n = self.entries.len();
                let forward = matches!(b, Btn::Right | Btn::R1 | Btn::Down);
                let step = if !self.fullscreen && matches!(b, Btn::Up | Btn::Down) {
                    3.min(n)
                } else {
                    1
                };
                if self.fullscreen && matches!(b, Btn::Up | Btn::Down) {
                    return false;
                }
                self.selected = (self.selected + n + if forward { step } else { n - step }) % n;
                self.changed();
            }
            _ => {}
        }
        false
    }
    pub fn poll(&mut self) {
        if self.job.as_ref().is_some_and(|j| j.is_finished()) {
            match self.job.take().unwrap().join() {
                Ok(work) => {
                    if work.catalog {
                        self.entries = work.entries;
                        self.loaded = true;
                        if work.removed {
                            self.delete = None;
                        }
                        self.selected = self.selected.min(self.entries.len().saturating_sub(1));
                    }
                    if work.revision == self.revision {
                        self.frame = Some(work.frame);
                        self.error = work.error;
                    } else {
                        self.dirty = true;
                    }
                }
                Err(_) => {
                    self.error = Some("Gallery could not load".into());
                    self.loaded = true;
                    self.dirty = true;
                }
            }
        }
        if self.job.is_none() && self.dirty {
            self.dirty = false;
            let root = self.root.clone();
            let mut entries = self.entries.clone();
            let initial = !self.loaded;
            let remove = self.delete.clone();
            let revision = self.revision;
            let by = self.sort;
            let selected = self.selected;
            let full = self.fullscreen;
            let confirm = self.confirm;
            let previous_error = self.error.take();
            self.job = Some(std::thread::spawn(move || {
                let mut error = previous_error;
                if initial {
                    entries.clear();
                    for library in slot_store::library_roots(&root) {
                        match screenshots::scan(&library) {
                            Ok(e) => entries.extend(e),
                            Err(e) => error = Some(e.to_string()),
                        }
                    }
                }
                let removed = remove.is_some();
                if let Some(e) = remove {
                    let library = slot_store::library_roots(&root)
                        .into_iter()
                        .find(|r| e.path.starts_with(r.join("Screenshots")));
                    let deleted = library
                        .ok_or_else(|| std::io::Error::other("Screenshot storage unavailable"))
                        .and_then(|r| {
                            slot_store::ensure_progress_storage(&r, true)?;
                            screenshots::delete(&r, &e)
                        });
                    match deleted {
                        Ok(()) => entries.retain(|x| x.path != e.path),
                        Err(e) => error = Some(format!("Could not delete: {e}")),
                    }
                }
                sort(&mut entries, by);
                let frame = render(
                    &entries,
                    selected.min(entries.len().saturating_sub(1)),
                    by,
                    full,
                    confirm,
                    error.as_deref(),
                );
                Work {
                    catalog: initial || removed,
                    removed,
                    revision,
                    entries,
                    frame,
                    error,
                }
            }));
        }
    }
    pub fn take_frame(&mut self) -> Option<(CartFace, CartFace)> {
        self.frame.take()
    }
    pub fn set_textures(&mut self, image: TexId, legend: TexId) {
        self.textures = Some((image, legend));
    }
    pub fn draw(&self, now: u64, out: &mut Vec<Draw>) {
        out.push(Draw::Rect {
            x: 0.0,
            y: 0.0,
            w: OUT_W as f32,
            h: OUT_H as f32,
            colour: [0.035, 0.04, 0.05, 1.0],
        });
        if let Some((image, legend)) = self.textures {
            out.push(Draw::Tex {
                x: 0.0,
                y: 0.0,
                w: OUT_W as f32,
                h: OUT_H as f32,
                tex: image,
                alpha: 1.0,
            });
            out.push(Draw::Tex {
                x: 0.0,
                y: 0.0,
                w: OUT_W as f32,
                h: OUT_H as f32,
                tex: legend,
                alpha: self.alpha(now),
            });
        }
    }
}
fn canvas(transparent: bool) -> CartFace {
    let mut rgba = vec![0; 640 * 480 * 4];
    if !transparent {
        for p in rgba.chunks_exact_mut(4) {
            p.copy_from_slice(&[9, 11, 14, 255]);
        }
    }
    CartFace {
        rgba,
        w: 640,
        h: 480,
    }
}
fn rect(dst: &mut CartFace, x: u32, y: u32, w: u32, h: u32, c: [u8; 4]) {
    for yy in y..(y + h).min(dst.h) {
        for xx in x..(x + w).min(dst.w) {
            let at = ((yy * dst.w + xx) * 4) as usize;
            dst.rgba[at..at + 4].copy_from_slice(&c);
        }
    }
}
fn stamp(dst: &mut CartFace, src: &[u8], w: u32, h: u32, x: u32, y: u32) {
    for yy in 0..h.min(dst.h.saturating_sub(y)) {
        for xx in 0..w.min(dst.w.saturating_sub(x)) {
            let a = ((yy * w + xx) * 4) as usize;
            let b = (((yy + y) * dst.w + xx + x) * 4) as usize;
            let alpha = src[a + 3] as u32;
            for c in 0..3 {
                dst.rgba[b + c] = ((src[a + c] as u32 * alpha
                    + dst.rgba[b + c] as u32 * (255 - alpha))
                    / 255) as u8;
            }
            dst.rgba[b + 3] = dst.rgba[b + 3].max(src[a + 3]);
        }
    }
}
#[allow(clippy::too_many_arguments)]
fn label(dst: &mut CartFace, text: &str, x: u32, y: u32, w: u32, h: u32, px: f32, c: [u8; 3]) {
    if let Some(font) = slot_ui::text::label_font() {
        let mut fitted = text.to_uppercase();
        if slot_ui::text::line_width(font, &fitted, px, (px * 0.10).round()) > w as f32 {
            while !fitted.is_empty()
                && slot_ui::text::line_width(font, &format!("{fitted}…"), px, (px * 0.10).round())
                    > w as f32
            {
                fitted.pop();
            }
            fitted.push('…');
        }
        let layout = slot_ui::text::fit(font, &fitted, w as f32, 1, px, px);
        let mut rgba = vec![0; (w * h * 4) as usize];
        slot_ui::text::draw_centred(&mut rgba, w, h, &layout, c);
        stamp(dst, &rgba, w, h, x, y);
    }
}
fn picture(dst: &mut CartFace, entry: &Entry, x: u32, y: u32, w: u32, h: u32) -> bool {
    let Ok((iw, ih, rgba)) = screenshots::read(&entry.path) else {
        label(dst, "Unreadable image", x, y, w, h, 15.0, [230, 160, 150]);
        return false;
    };
    let scale = (w as f32 / iw as f32).min(h as f32 / ih as f32);
    let dw = (iw as f32 * scale).round().max(1.0) as u32;
    let dh = (ih as f32 * scale).round().max(1.0) as u32;
    let mut thumb = vec![0; (dw * dh * 4) as usize];
    for yy in 0..dh {
        for xx in 0..dw {
            let src = (((yy * ih / dh) * iw + xx * iw / dw) * 4) as usize;
            let at = ((yy * dw + xx) * 4) as usize;
            thumb[at..at + 4].copy_from_slice(&rgba[src..src + 4]);
        }
    }
    stamp(dst, &thumb, dw, dh, x + (w - dw) / 2, y + (h - dh) / 2);
    true
}
fn legends(items: &[(&str, &str)]) -> CartFace {
    let mut face = canvas(true);
    rect(&mut face, 0, 438, 640, 42, [10, 12, 16, 235]);
    let cell = 640 / items.len().max(1) as u32;
    for (i, (key, text)) in items.iter().enumerate() {
        let f = slot_ui::hint_face(key, text);
        let x = i as u32 * cell + (cell.saturating_sub(f.w)) / 2;
        stamp(&mut face, &f.rgba, f.w, f.h, x, 447);
    }
    face
}
fn render(
    entries: &[Entry],
    selected: usize,
    by: Sort,
    full: bool,
    confirm: bool,
    error: Option<&str>,
) -> (CartFace, CartFace) {
    let mut face = canvas(false);
    let count = entries.len();
    if let Some(e) = entries.get(selected) {
        if full {
            picture(&mut face, e, 0, 0, 640, 480);
        } else {
            label(
                &mut face,
                &format!("GALLERY  /  {}", by.label()),
                12,
                8,
                616,
                28,
                20.0,
                [240, 242, 246],
            );
            label(
                &mut face,
                &format!("{}  |  {} / {}", e.game, selected + 1, count),
                12,
                40,
                616,
                26,
                16.0,
                [150, 210, 232],
            );
            for (offset, e) in entries.iter().skip(selected / 6 * 6).take(6).enumerate() {
                let x = 14 + (offset % 3) as u32 * 208;
                let y = 82 + (offset / 3) as u32 * 174;
                let active = selected / 6 * 6 + offset == selected;
                rect(
                    &mut face,
                    x - 3,
                    y - 3,
                    202,
                    165,
                    if active {
                        [70, 180, 220, 255]
                    } else {
                        [35, 40, 49, 255]
                    },
                );
                rect(&mut face, x, y, 196, 159, [9, 11, 14, 255]);
                picture(&mut face, e, x, y, 196, 125);
                label(
                    &mut face,
                    &e.game,
                    x,
                    y + 128,
                    196,
                    19,
                    13.0,
                    [240, 242, 246],
                );
                label(
                    &mut face,
                    &format!("{}  {}", e.platform, e.date.get(..10).unwrap_or("")),
                    x,
                    y + 146,
                    196,
                    16,
                    11.0,
                    [165, 177, 188],
                );
            }
        }
    } else {
        label(&mut face, "Gallery", 20, 25, 600, 40, 24.0, [240, 242, 246]);
        label(
            &mut face,
            "No screenshots yet",
            20,
            188,
            600,
            35,
            22.0,
            [240, 242, 246],
        );
        label(
            &mut face,
            "Press Select + Start while playing",
            20,
            230,
            600,
            30,
            17.0,
            [160, 190, 210],
        );
    }
    if let Some(error) = error {
        rect(&mut face, 8, 398, 624, 32, [65, 25, 25, 255]);
        label(&mut face, error, 12, 400, 616, 28, 14.0, [255, 220, 220]);
    }
    let mut footer = if full {
        legends(&[
            ("D-PAD", "Browse"),
            ("L/R", "Browse"),
            ("X", "Delete"),
            ("B", "Grid"),
        ])
    } else {
        legends(&[
            ("A", "Open"),
            ("L/R", "Sort"),
            ("X", "Delete"),
            ("B", "Back"),
        ])
    };
    if confirm {
        rect(&mut face, 54, 153, 532, 166, [24, 28, 35, 255]);
        label(
            &mut face,
            "Delete this screenshot?",
            65,
            169,
            510,
            40,
            22.0,
            [255, 245, 240],
        );
        if let Some(e) = entries.get(selected) {
            label(&mut face, &e.game, 65, 214, 510, 27, 16.0, [175, 200, 215]);
        }
        label(
            &mut face,
            "This cannot be undone",
            65,
            254,
            510,
            28,
            16.0,
            [200, 180, 175],
        );
        footer = legends(&[("A", "Delete"), ("B", "Cancel")]);
    }
    (face, footer)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{fs, time::Duration};
    fn ready(g: &mut Gallery) {
        for _ in 0..500 {
            g.poll();
            if g.job.is_none() && !g.dirty {
                return;
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        panic!("gallery worker did not finish");
    }
    fn press(g: &mut Gallery, b: Btn, now: u64) -> bool {
        let back = g.button(b, now);
        g.release(b, now + 1);
        back
    }
    fn fixture() -> (tempfile::TempDir, Gallery) {
        let t = tempfile::tempdir().unwrap();
        for (i, p) in [
            slot_store::Platform::Gba,
            slot_store::Platform::Gb,
            slot_store::Platform::Gbc,
        ]
        .into_iter()
        .enumerate()
        {
            screenshots::save(
                &screenshots::Request {
                    root: t.path().to_owned(),
                    platform: p,
                    game: format!("Game {i}"),
                    shaders: false,
                    filters: false,
                    overlay: false,
                },
                2,
                2,
                &[180; 16],
            )
            .unwrap();
        }
        let mut g = Gallery::open(t.path().to_owned(), 0);
        ready(&mut g);
        (t, g)
    }
    #[test]
    fn sorting_keeps_current_image_and_fullscreen_shoulders_navigate() {
        let (_t, mut g) = fixture();
        let p = g.entries[g.selected].path.clone();
        press(&mut g, Btn::R1, 100);
        assert_eq!(g.sort, Sort::Platform);
        assert_eq!(g.entries[g.selected].path, p);
        press(&mut g, Btn::L1, 200);
        assert_eq!(g.sort, Sort::Date);
        press(&mut g, Btn::A, 300);
        assert!(g.fullscreen);
        let n = g.selected;
        for b in [Btn::Right, Btn::R1] {
            press(&mut g, b, 400);
            assert_eq!(g.selected, (n + 1) % 3);
            press(&mut g, Btn::Left, 500);
            assert_eq!(g.selected, n);
        }
        press(&mut g, Btn::L1, 600);
        assert_eq!(g.selected, (n + 2) % 3);
        assert_eq!(g.sort, Sort::Date);
        assert!(!press(&mut g, Btn::B, 700));
        assert!(!g.fullscreen);
        assert!(press(&mut g, Btn::B, 800));
    }
    #[test]
    fn deleting_requires_x_then_a_and_b_cancels_without_touching_any_file() {
        let (_t, mut g) = fixture();
        let p = g.entries[g.selected].path.clone();
        press(&mut g, Btn::X, 100);
        assert!(g.confirm);
        press(&mut g, Btn::Right, 120);
        assert!(g.confirm);
        assert_eq!(g.entries[g.selected].path, p);
        press(&mut g, Btn::B, 140);
        assert!(!g.confirm);
        assert!(p.exists());
        assert_eq!(g.len(), 3);
        // Queue a preview first: confirmation must survive a stale worker result.
        press(&mut g, Btn::A, 160);
        g.poll();
        press(&mut g, Btn::X, 170);
        press(&mut g, Btn::A, 180);
        ready(&mut g);
        assert!(!p.exists());
        assert_eq!(g.len(), 2);
        assert!(!g.confirm);
        assert!(g.fullscreen);
        for e in &g.entries {
            assert!(fs::metadata(&e.path).unwrap().is_file());
        }
    }
    #[test]
    fn legends_hide_after_two_seconds_hold_until_release_and_fade_back_in() {
        let (_t, mut g) = fixture();
        assert_eq!(g.alpha(2000), 1.0);
        assert!((g.alpha(2125) - 0.5).abs() < 0.01);
        assert_eq!(g.alpha(2250), 0.0);
        g.button(Btn::Right, 3000);
        assert_eq!(g.alpha(6000), 1.0);
        g.release(Btn::Right, 6000);
        assert_eq!(g.alpha(8000), 1.0);
        assert_eq!(g.alpha(8250), 0.0);
        g.activity(9000);
        assert_eq!(g.alpha(9000), 0.0);
        assert!((g.alpha(9075) - 0.5).abs() < 0.01);
        assert_eq!(g.alpha(9150), 1.0);
    }
    #[test]
    fn empty_gallery_is_safe_and_malformed_png_gets_a_placeholder() {
        let t = tempfile::tempdir().unwrap();
        let mut g = Gallery::open(t.path().to_owned(), 0);
        ready(&mut g);
        assert_eq!(g.len(), 0);
        for b in [Btn::A, Btn::X, Btn::Left, Btn::Right, Btn::L1, Btn::R1] {
            press(&mut g, b, 100);
            g.poll();
        }
        ready(&mut g);
        assert!(!g.confirm);
        assert!(!g.fullscreen);
    }
}
