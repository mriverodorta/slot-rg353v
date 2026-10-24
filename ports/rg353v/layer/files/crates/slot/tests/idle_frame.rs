#![cfg(feature = "rg353v")]
use slot::idle_frame::{IdleFrame, State};
use slot_gfx::Draw;
fn state() -> State {
    State {
        window: (640, 480),
        texture_epoch: 1,
        blue_light: 0,
        screen_power: 1.0,
        shake: 0.0,
        lift: 1.0,
        split: None,
    }
}
fn rect(x: f32) -> Draw {
    Draw::Rect {
        x,
        y: 0.0,
        w: 10.0,
        h: 10.0,
        colour: [1.0; 4],
    }
}
#[test]
fn only_identical_complete_shelf_frames_can_reuse_scanout() {
    let mut m = IdleFrame::default();
    let s = state();
    let d = [rect(0.0)];
    assert!(m.changed(true, s, &d, &[], &[]));
    assert!(!m.changed(true, s, &d, &[], &[]));
    assert!(m.changed(true, s, &[rect(0.0001)], &[], &[]));
    assert!(m.changed(true, s, &d, &[], &[]));
    assert!(m.changed(true, s, &d, &[rect(2.0)], &[]));
    assert!(m.changed(true, s, &d, &[rect(2.0)], &[rect(4.0)]));
    assert!(!m.changed(true, s, &d, &[rect(2.0)], &[rect(4.0)]));
}
#[test]
fn texture_uploads_and_presentation_changes_invalidate_even_with_same_draws() {
    let mut m = IdleFrame::default();
    let s = state();
    let variants = [
        State {
            texture_epoch: 2,
            ..s
        },
        State {
            window: (320, 240),
            ..s
        },
        State { blue_light: 1, ..s },
        State {
            screen_power: 0.9,
            ..s
        },
        State { shake: 0.1, ..s },
        State { lift: 0.9, ..s },
        State {
            split: Some(400.0),
            ..s
        },
    ];
    for changed in variants {
        assert!(m.changed(true, s, &[], &[], &[]));
        assert!(m.changed(true, changed, &[], &[], &[]));
        assert!(!m.changed(true, changed, &[], &[], &[]));
    }
}
#[test]
fn gameplay_and_wake_never_depend_on_stale_shelf_contents() {
    let mut m = IdleFrame::default();
    let s = state();
    assert!(m.changed(true, s, &[], &[], &[]));
    assert!(!m.changed(true, s, &[], &[], &[]));
    for _ in 0..10 {
        assert!(m.changed(false, s, &[], &[], &[]));
    }
    assert!(m.changed(true, s, &[], &[], &[]));
    m.reset();
    assert!(m.changed(true, s, &[], &[], &[]));
}
