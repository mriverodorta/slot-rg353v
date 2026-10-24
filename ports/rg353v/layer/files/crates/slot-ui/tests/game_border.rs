use slot_store::Platform;
use slot_ui::game_border_face;

#[test]
fn fit_and_integer_borders_clear_the_whole_game_and_keep_branding_outside() {
    for integer in [false, true] {
        for platform in Platform::ALL {
            let rgba = game_border_face(platform, integer).expect("built-in border should render");
            assert_eq!(rgba.len(), 640 * 480 * 4);
            let (left, bottom, width, height) = if integer {
                slot_gfx::integer_game_panel_rect((640, 480), platform.picture())
            } else {
                slot_gfx::game_panel_rect((640, 480), platform.picture(), false)
            };
            let top = 480 - bottom - height;
            for y in top..top + height {
                for x in left..left + width {
                    assert_eq!(
                        rgba[((y * 640 + x) * 4 + 3) as usize],
                        0,
                        "{platform:?} integer={integer}: border covers game at {x},{y}"
                    );
                }
            }
            if platform == Platform::Gba {
                let start = if integer { 388 } else { 441 };
                assert!(
                    (start..start + 30).any(|y| (180..460).any(|x| rgba[(y * 640 + x) * 4] > 100))
                );
            } else {
                let right = (left + width + 640) / 2;
                assert!(
                    (140..350).any(|y| (right - 18..right + 18)
                        .any(|x| rgba[((y * 640 + x) * 4) as usize] > 100)),
                    "missing vertical wordmark"
                );
                let power = ((232 * 640 + left / 2) * 4) as usize;
                assert!(
                    rgba[power] > 200 && rgba[power + 1] < rgba[power],
                    "missing red power light"
                );
            }
        }
    }
}

#[test]
fn gb_stripes_share_the_vertical_wordmarks_centerline() {
    for integer in [false, true] {
        let rgba = game_border_face(Platform::Gb, integer).unwrap();
        let (left, _, width, _) = if integer {
            slot_gfx::integer_game_panel_rect((640, 480), Platform::Gb.picture())
        } else {
            slot_gfx::game_panel_rect((640, 480), Platform::Gb.picture(), false)
        };
        let center = (left + width + 640) / 2;
        let lit: Vec<i32> = (left + width..640)
            .filter(|x| rgba[((80 * 640 + x) * 4 + 2) as usize] != 0)
            .collect();
        assert!(!lit.is_empty());
        // Pixel centers are at x + 0.5, so the stripe pair straddles `center`.
        assert_eq!(lit.first().unwrap() + lit.last().unwrap() + 1, center * 2);
    }
}

#[test]
fn perfect_art_has_a_translucent_game_texture_and_an_opaque_surround() {
    for platform in Platform::ALL {
        let rgba = slot_ui::perfect_overlay_face(platform).unwrap();
        assert_eq!(rgba.len(), 640 * 480 * 4);
        let (x, y, w, h) = match platform {
            Platform::Gba => (0, 0, 640, 427),
            _ => (54, 0, 532, 480),
        };
        for row in 0..480 {
            for col in 0..640 {
                let a = rgba[(row * 640 + col) * 4 + 3];
                if (x..x + w).contains(&col) && (y..y + h).contains(&row) {
                    assert!(a < 255, "opaque game pixel for {platform:?} at {col},{row}");
                } else {
                    assert_eq!(a, 255, "transparent border for {platform:?} at {col},{row}");
                }
            }
        }
    }
}
