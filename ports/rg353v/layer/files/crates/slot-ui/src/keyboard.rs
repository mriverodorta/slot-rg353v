//! Reusable borderless text entry with alphabet grids and a numeric pad.
//! Views contain display text only:
//! hidden passwords never copy plaintext into texture caches or debug output.
use crate::{centred_hints, text, Draw, TexId, UndoFace, HINT_H, MENU_LEGEND_Y, OUT_W};

const SECTIONS: [&str; 4] = [
    "abcdefghijklmnopqrstuvwxyz",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "1234567890",
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
];
const TABS: [&str; 4] = ["abc", "ABC", "123", "!?#"];
const COLS: usize = 6;
const PAD: u32 = 32;
const WIDTH: u32 = OUT_W - PAD * 2;
const INK: [u8; 3] = [246, 244, 239];
const DIM: [u8; 3] = [160, 159, 169];
const DARK: [u8; 3] = [26, 25, 23];

fn columns(section: usize) -> usize {
    if section == 2 {
        3
    } else {
        COLS
    }
}

/// Shared label/focus geometry keeps the numeric pad compact and left aligned.
fn key_box(section: usize, count: usize, key: usize) -> (u32, u32, u32, u32) {
    let cols = columns(section);
    let pitch = (210 / count.div_ceil(cols) as u32).min(42);
    let cell_width = WIDTH / COLS as u32;
    let width = if section == 2 { cell_width * 3 } else { WIDTH };
    let x = PAD + key as u32 % cols as u32 * cell_width;
    let w = if key == count - 1 {
        PAD + width - x
    } else {
        cell_width
    };
    (x, 182 + key as u32 / cols as u32 * pitch, w, pitch - 4)
}

#[derive(Clone, Copy)]
pub enum KeyboardAction {
    Left,
    Right,
    Up,
    Down,
    PreviousSection,
    NextSection,
    Add,
    Delete,
    ToggleVisibility,
}

// Deliberately no Debug implementation: this owns potentially secret text.
pub struct Keyboard {
    value: String,
    max_bytes: usize,
    secret: bool,
    revealed: bool,
    section: usize,
    key: usize,
    column: usize,
}

impl Keyboard {
    pub fn new(max_bytes: usize, secret: bool) -> Self {
        Self {
            value: String::new(),
            max_bytes,
            secret,
            revealed: false,
            section: 0,
            key: 0,
            column: 0,
        }
    }

    pub fn value(&self) -> &str {
        &self.value
    }

    pub fn clear(&mut self) {
        self.value.clear();
        self.revealed = false;
        self.section = 0;
        self.key = 0;
        self.column = 0;
    }

    fn count(&self) -> usize {
        SECTIONS[self.section].len() + 1
    }

    fn horizontal(&mut self, forward: bool) {
        self.key = (self.key + if forward { 1 } else { self.count() - 1 }) % self.count();
        self.column = self.key % columns(self.section);
    }

    fn vertical(&mut self, forward: bool) {
        let cols = columns(self.section);
        let rows = self.count().div_ceil(cols);
        let row = (self.key / cols + if forward { 1 } else { rows - 1 }) % rows;
        // A short final row has a wide SPACE cell. Keep the preferred column
        // so moving back up returns to the same column rather than drifting.
        self.key = (row * cols + self.column).min(self.count() - 1);
    }

    pub fn apply(&mut self, action: KeyboardAction) {
        match action {
            KeyboardAction::Left => self.horizontal(false),
            KeyboardAction::Right => self.horizontal(true),
            KeyboardAction::Up => self.vertical(false),
            KeyboardAction::Down => self.vertical(true),
            KeyboardAction::PreviousSection | KeyboardAction::NextSection => {
                self.section = (self.section
                    + if matches!(action, KeyboardAction::NextSection) {
                        1
                    } else {
                        3
                    })
                    % 4;
                self.key = self.key.min(self.count() - 1);
                self.column = self.key % columns(self.section);
            }
            KeyboardAction::Add => {
                let ch = SECTIONS[self.section].chars().nth(self.key).unwrap_or(' ');
                if self.value.len() + ch.len_utf8() <= self.max_bytes {
                    self.value.push(ch);
                }
            }
            KeyboardAction::Delete => {
                self.value.pop();
            }
            KeyboardAction::ToggleVisibility if self.secret => {
                self.revealed = !self.revealed;
            }
            KeyboardAction::ToggleVisibility => {}
        }
    }

    pub fn legend(&self, submit: &str) -> Vec<crate::Hint> {
        let mut hints = Vec::new();
        if self.secret {
            hints.push(crate::Hint {
                key: "X",
                label: if self.revealed { "Hide" } else { "Show" }.into(),
            });
        }
        hints.extend(crate::hint_row(&[
            ("Y", "Delete"),
            ("B", "Back"),
            ("A", "Add"),
        ]));
        hints.push(crate::Hint {
            key: "START",
            label: submit.into(),
        });
        hints
    }

    pub fn view(&self, title: &str, context: &str, status: &str) -> KeyboardView {
        let mut labels = vec![
            Label::left(title, PAD, 12, WIDTH, 32, 28, INK),
            Label::left(context, PAD, 49, WIDTH, 24, 20, DIM),
        ];
        let shown = if self.secret && !self.revealed {
            "•".repeat(self.value.chars().count().min(28))
        } else {
            self.value
                .chars()
                .rev()
                .take(35)
                .collect::<String>()
                .chars()
                .rev()
                .collect()
        };
        labels.push(Label::left(
            &format!("{shown}|"),
            PAD + 12,
            86,
            WIDTH - 24,
            34,
            24,
            INK,
        ));
        // Native controller badges beside the four section labels.
        let tab_width = (WIDTH - 80) / 4;
        for (i, tab) in TABS.iter().enumerate() {
            labels.push(Label::centred(
                tab,
                PAD + 40 + i as u32 * tab_width,
                140,
                tab_width,
                32,
                22,
                if i == self.section { INK } else { DIM },
            ));
        }
        labels.extend([
            Label::centred("L", PAD, 146, 20, 20, 14, DARK),
            Label::centred("‹", PAD + 20, 140, 20, 32, 26, INK),
            Label::centred("›", PAD + WIDTH - 40, 140, 20, 32, 26, INK),
            Label::centred("R", PAD + WIDTH - 20, 146, 20, 20, 14, DARK),
        ]);
        for (i, ch) in SECTIONS[self.section]
            .chars()
            .chain(std::iter::once(' '))
            .enumerate()
        {
            let (x, y, w, h) = key_box(self.section, self.count(), i);
            labels.push(Label::centred(
                if ch == ' ' {
                    "SPACE".into()
                } else {
                    ch.to_string()
                }
                .as_str(),
                x,
                y,
                w,
                h,
                if ch == ' ' { 20 } else { 30 },
                if i == self.key { DARK } else { INK },
            ));
        }
        if !status.is_empty() {
            labels.push(Label::left(status, PAD, 394, WIDTH, 24, 16, DIM));
        }
        KeyboardView {
            labels,
            section: self.section,
            key: self.key,
            count: self.count(),
        }
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct Label {
    pub text: String,
    pub x: u32,
    pub y: u32,
    pub w: u32,
    pub h: u32,
    px: u32,
    ink: [u8; 3],
    centred: bool,
}

impl Label {
    #[allow(clippy::too_many_arguments)]
    fn left(text: &str, x: u32, y: u32, w: u32, h: u32, px: u32, ink: [u8; 3]) -> Self {
        Self {
            text: text.into(),
            x,
            y,
            w,
            h,
            px,
            ink,
            centred: false,
        }
    }
    #[allow(clippy::too_many_arguments)]
    fn centred(text: &str, x: u32, y: u32, w: u32, h: u32, px: u32, ink: [u8; 3]) -> Self {
        Self {
            centred: true,
            ..Self::left(text, x, y, w, h, px, ink)
        }
    }
    pub fn face(&self) -> UndoFace {
        let mut rgba = vec![0; (self.w * self.h * 4) as usize];
        if let Some(font) = text::label_font() {
            let mut px = self.px as f32;
            while px > 12.0 && text::line_width(font, &self.text, px, 1.0) > self.w as f32 - 8.0 {
                px -= 1.0;
            }
            let mut line = self.text.clone();
            while text::line_width(font, &line, px, 1.0) > self.w as f32 - 8.0 && !line.is_empty() {
                line.pop();
            }
            // text::fit uppercases native menu labels. Keyboard glyphs and
            // reusable plain text input must preserve the user's exact case.
            let layout = text::Layout {
                lines: vec![line.clone()],
                px,
                tracking: 1.0,
            };
            if self.centred {
                text::draw_centred(&mut rgba, self.w, self.h, &layout, self.ink);
            } else {
                let w = (text::line_width(font, &line, px, 1.0).ceil() as u32 + 8).min(self.w);
                let mut band = vec![0; (w * self.h * 4) as usize];
                text::draw_centred(&mut band, w, self.h, &layout, self.ink);
                crate::plate::blit(&mut rgba, self.w, &band, w, self.h, 0, 0);
            }
        }
        UndoFace {
            rgba,
            w: self.w,
            h: self.h,
        }
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct KeyboardView {
    pub labels: Vec<Label>,
    section: usize,
    key: usize,
    count: usize,
}

impl KeyboardView {
    pub fn draw(&self, faces: &[(TexId, u32, u32)], out: &mut Vec<Draw>) {
        let rect = |x: u32, y: u32, w: u32, h: u32, colour| Draw::Rect {
            x: x as f32,
            y: y as f32,
            w: w as f32,
            h: h as f32,
            colour,
        };
        out.push(rect(PAD, 82, WIDTH, 42, [0.20, 0.20, 0.23, 1.0]));
        out.push(rect(
            PAD,
            146,
            20,
            20,
            [246.0 / 255.0, 244.0 / 255.0, 239.0 / 255.0, 1.0],
        ));
        out.push(rect(
            PAD + WIDTH - 20,
            146,
            20,
            20,
            [246.0 / 255.0, 244.0 / 255.0, 239.0 / 255.0, 1.0],
        ));
        let tab_width = (WIDTH - 80) / 4;
        out.push(rect(
            PAD + 40 + self.section as u32 * tab_width,
            140,
            tab_width,
            32,
            crate::edge(),
        ));
        let (x, y, w, h) = key_box(self.section, self.count, self.key);
        out.push(rect(
            x + 4,
            y,
            w - 8,
            h,
            [
                INK[0] as f32 / 255.0,
                INK[1] as f32 / 255.0,
                INK[2] as f32 / 255.0,
                1.0,
            ],
        ));
        for (label, &(tex, w, h)) in self.labels.iter().zip(faces) {
            out.push(Draw::Tex {
                x: label.x as f32,
                y: label.y as f32,
                w: w as f32,
                h: h as f32,
                tex,
                alpha: 1.0,
            });
        }
    }
}

/// Keep the keyboard's concise actions on one native footer row.
pub fn draw_keyboard_legend(faces: &[(TexId, u32)], out: &mut Vec<Draw>) {
    for (tex, w, x) in centred_hints(faces, 28.0) {
        out.push(Draw::Tex {
            x,
            y: MENU_LEGEND_Y,
            w: w as f32,
            h: HINT_H as f32,
            tex,
            alpha: 1.0,
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use KeyboardAction::*;

    #[test]
    fn font_preserves_case_and_covers_every_input_glyph() {
        let font = text::label_font().unwrap();
        for ch in SECTIONS.concat().chars().chain("•‹›".chars()) {
            assert_ne!(font.lookup_glyph_index(ch), 0, "missing glyph {ch}");
        }
        let lower = Label::centred("a", 0, 0, 50, 40, 30, INK).face();
        let upper = Label::centred("A", 0, 0, 50, 40, 30, INK).face();
        assert_ne!(
            lower.rgba, upper.rgba,
            "lowercase was converted to uppercase"
        );
    }

    #[test]
    fn four_sections_wrap_both_directions_and_keep_characters_separate() {
        let mut k = Keyboard::new(64, true);
        for expected in ["a", "A", "1", "!"] {
            k.apply(Add);
            assert!(k.value().ends_with(expected));
            k.apply(NextSection);
        }
        assert_eq!(k.section, 0);
        k.apply(PreviousSection);
        assert_eq!(k.section, 3);
        let all: String = SECTIONS.concat();
        assert_eq!(all.len(), 94);
        for ch in '!'..='~' {
            assert_eq!(all.matches(ch).count(), 1);
        }
    }

    #[test]
    fn vertical_navigation_wraps_rows_and_wide_space_preserves_column() {
        let mut k = Keyboard::new(64, true);
        for _ in 0..5 {
            k.apply(Right);
        }
        for expected in [11, 17, 23, 26, 5] {
            k.apply(Down);
            assert_eq!(k.key, expected);
        }
        k.apply(Up);
        assert_eq!(k.key, 26);
        k.apply(Up);
        assert_eq!(k.key, 23);
        k.key = 26;
        k.apply(Add);
        assert_eq!(k.value(), " ");
    }

    #[test]
    fn numpad_types_with_three_columns_and_zero_beside_space() {
        let mut k = Keyboard::new(64, false);
        k.apply(NextSection);
        k.apply(NextSection);
        for action in [
            Add, Down, Right, Add, Down, Right, Add, Down, Left, Add, Right, Add,
        ] {
            k.apply(action);
        }
        assert_eq!(k.value(), "1590 ");
        let view = k.view("NUMBER", "", "");
        let find = |ch: &str| view.labels.iter().find(|label| label.text == ch).unwrap();
        for row in [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]] {
            let cells = row.map(find);
            assert_eq!(cells[0].y, cells[1].y);
            assert_eq!(cells[1].y, cells[2].y);
            assert!(cells[0].x < cells[1].x && cells[1].x < cells[2].x);
        }
        assert!(find("4").y > find("1").y);
        assert!(find("7").y > find("4").y);
        assert!(find("0").y > find("7").y);
        assert_eq!(find("0").x, find("1").x);
        assert_eq!(find("0").y, find("SPACE").y);
        assert_eq!(find("SPACE").w, 2 * find("0").w);
    }

    #[test]
    fn numpad_space_preserves_right_column_when_moving_vertically() {
        let mut k = Keyboard::new(64, false);
        for action in [NextSection, NextSection, Right, Right] {
            k.apply(action);
        }
        for expected in [5, 8, 10, 2] {
            k.apply(Down);
            assert_eq!(k.key, expected);
        }
        k.apply(Up);
        k.apply(Up);
        assert_eq!(k.key, 8);
    }

    #[test]
    fn every_key_is_reachable_and_cross_section_clamps_are_safe() {
        let mut k = Keyboard::new(128, false);
        for section in 0..4 {
            assert_eq!(k.section, section);
            k.key = 0;
            for _ in 0..k.count() {
                k.apply(Add);
                k.apply(Right);
            }
            assert_eq!(k.key, 0);
            k.key = k.count() - 1;
            k.apply(NextSection);
            assert!(k.key < k.count());
        }
        assert_eq!(k.value(), format!("{} ", SECTIONS.join(" ")));
    }

    #[test]
    fn secret_view_never_exposes_value_and_limit_delete_and_clear_work() {
        let mut k = Keyboard::new(3, true);
        for _ in 0..4 {
            k.apply(Add);
        }
        assert_eq!(k.value(), "aaa");
        let view = k.view("PASSWORD", "NETWORK", "");
        assert_eq!(view.labels[2].text, "•••|");
        assert!(!view.labels.iter().any(|l| l.text.contains("aaa")));
        k.apply(Delete);
        assert_eq!(k.value(), "aa");
        k.clear();
        k.apply(Delete);
        assert_eq!(k.value(), "");
        assert_eq!((k.key, k.section), (0, 0));
    }

    #[test]
    fn password_visibility_toggles_without_changing_text_or_selection_and_resets_on_clear() {
        let mut k = Keyboard::new(64, true);
        for action in [Add, NextSection, Add, NextSection, Add, NextSection, Add] {
            k.apply(action);
        }
        let cursor = (k.section, k.key, k.column);
        assert_eq!(k.value(), "aA1!");
        assert_eq!(k.view("", "", "").labels[2].text, "••••|");
        assert_eq!(
            k.legend("Connect")[0],
            crate::Hint {
                key: "X",
                label: "Show".into()
            }
        );
        k.apply(ToggleVisibility);
        assert_eq!(k.view("", "", "").labels[2].text, "aA1!|");
        assert_eq!(
            k.legend("Connect")[0],
            crate::Hint {
                key: "X",
                label: "Hide".into()
            }
        );
        assert_eq!((k.section, k.key, k.column), cursor);
        k.apply(PreviousSection);
        assert_eq!(k.view("", "", "").labels[2].text, "aA1!|");
        k.apply(ToggleVisibility);
        assert_eq!(k.view("", "", "").labels[2].text, "••••|");
        assert_eq!(k.value(), "aA1!");
        k.apply(ToggleVisibility);
        k.clear();
        k.apply(Add);
        assert_eq!(k.view("", "", "").labels[2].text, "•|");
        assert_eq!(k.legend("Done")[0].label, "Show");
        let mut plain = Keyboard::new(64, false);
        plain.apply(Add);
        plain.apply(ToggleVisibility);
        assert_eq!(plain.view("", "", "").labels[2].text, "a|");
        assert!(!plain.legend("Done").iter().any(|hint| hint.key == "X"));
    }
}
