use crate::{Draw, UndoFace, OUT_W};
use std::ops::Range;

/// Keep the cursor visible without moving a list until it reaches an edge.
pub fn menu_window(total: usize, selected: usize, capacity: usize, first: usize) -> Range<usize> {
    if total == 0 || capacity == 0 {
        return 0..0;
    }
    let selected = selected.min(total - 1);
    let mut first = first.min(total.saturating_sub(capacity));
    if selected < first {
        first = selected;
    }
    if selected >= first + capacity {
        first = selected + 1 - capacity;
    }
    first..(first + capacity).min(total)
}

pub fn draw_menu_scrollbar(
    total: usize,
    window: Range<usize>,
    y: f32,
    h: f32,
    out: &mut Vec<Draw>,
) {
    if total <= window.len() || window.is_empty() {
        return;
    }
    let x = OUT_W as f32 - 10.0;
    out.push(Draw::Rect {
        x,
        y,
        w: 3.0,
        h,
        colour: [1.0, 1.0, 1.0, 0.16],
    });
    let thumb = h * window.len() as f32 / total as f32;
    let top = y + (h - thumb) * window.start as f32 / (total - window.len()) as f32;
    out.push(Draw::Rect {
        x,
        y: top,
        w: 3.0,
        h: thumb,
        colour: [1.0, 1.0, 1.0, 0.8],
    });
}

/// Native white button caps beside a readable, left-aligned control description.
pub fn help_entry_face(keys: &[&str], label: &str) -> UndoFace {
    let (w, h) = (OUT_W - 64 + 2 * crate::MENU_PAD, 40);
    let mut rgba = vec![0; (w * h * 4) as usize];
    let mut x = crate::MENU_PAD;
    for (index, key) in keys.iter().enumerate() {
        if index > 0 {
            let plus = crate::word_face("+");
            blit(&mut rgba, w, h, &plus, plus.w, x, (h - plus.h) / 2);
            x += plus.w + 5;
        }
        let cap = crate::hint_face(key, "");
        let width = crate::cap_width(key);
        blit(&mut rgba, w, h, &cap, width, x, (h - cap.h) / 2);
        x += width + 5;
    }
    x += 10;
    let available = w.saturating_sub(x + crate::MENU_PAD);
    if available > 0 {
        if let Some(font) = crate::text::label_font() {
            let layout = crate::text::fit(font, label, available as f32 - 4.0, 1, 24.0, 18.0);
            let ink = layout
                .lines
                .iter()
                .map(|line| crate::text::line_width(font, line, layout.px, layout.tracking))
                .fold(0.0, f32::max);
            let width = (ink.ceil() as u32 + 4).min(available);
            let mut text = UndoFace {
                rgba: vec![0; (width * h * 4) as usize],
                w: width,
                h,
            };
            crate::text::draw_centred(&mut text.rgba, width, h, &layout, [246, 244, 239]);
            blit(&mut rgba, w, h, &text, width, x, 0);
        }
    }
    UndoFace { rgba, w, h }
}
fn blit(dst: &mut [u8], w: u32, h: u32, face: &UndoFace, width: u32, x: u32, y: u32) {
    for row in 0..face.h.min(h.saturating_sub(y)) {
        let count = width.min(w.saturating_sub(x));
        if count == 0 {
            continue;
        }
        let from = (row * face.w * 4) as usize;
        let to = ((row + y) * w * 4 + x * 4) as usize;
        dst[to..to + count as usize * 4]
            .copy_from_slice(&face.rgba[from..from + count as usize * 4]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn viewport_tracks_edges_wraps_and_clamps() {
        assert_eq!(menu_window(8, 6, 7, 0), 0..7);
        assert_eq!(menu_window(8, 7, 7, 0), 1..8);
        assert_eq!(menu_window(8, 6, 7, 1), 1..8);
        assert_eq!(menu_window(8, 0, 7, 1), 0..7);
        assert_eq!(menu_window(0, 99, 7, 99), 0..0);
        assert_eq!(menu_window(8, 7, 0, 1), 0..0);
        for total in 1..40 {
            for selected in 0..total {
                for first in 0..40 {
                    let range = menu_window(total, selected, 7, first);
                    assert!(range.contains(&selected));
                    assert!(range.len() <= 7 && range.end <= total);
                }
            }
        }
    }
    #[test]
    fn scrollbar_ends_at_viewport_edges() {
        let mut draws = Vec::new();
        draw_menu_scrollbar(8, 1..8, 56.0, 356.0, &mut draws);
        assert!(matches!(draws[1], Draw::Rect { y, h, .. } if (y + h - 412.0).abs() < 0.001));
    }
    #[test]
    fn help_uses_native_caps_and_visible_text() {
        let face = help_entry_face(&["SELECT", "X"], "Toggle frame counter");
        assert_eq!((face.w, face.h), (OUT_W - 64 + 2 * crate::MENU_PAD, 40));
        assert!(face
            .rgba
            .chunks_exact(4)
            .any(|pixel| pixel == [246, 244, 239, 255]));
        assert!(face
            .rgba
            .chunks_exact(4)
            .enumerate()
            .any(|(i, p)| i % face.w as usize > 200 && p[3] > 0));
    }
}
