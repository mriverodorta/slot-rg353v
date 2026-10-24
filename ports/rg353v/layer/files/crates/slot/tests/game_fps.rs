#![cfg(feature = "rg353v")]
use slot::game_fps::{face, placement, Meter, HEIGHT, WIDTH};
use std::time::Duration;
#[test]
fn counts_only_fresh_presented_game_frames_and_uses_elapsed_time() {
    let mut m = Meter::default();
    m.presented(Duration::ZERO, true, 0);
    for i in 1..=60 {
        m.presented(Duration::from_secs_f64(i as f64 / 60.0), true, i);
    }
    assert_eq!(m.tenths(), Some(600));
    // Sixty swaps containing just ten new game frames must read 10, not 60.
    for i in 1..=60 {
        m.presented(
            Duration::from_secs_f64(1.0 + i as f64 / 60.0),
            true,
            60 + i / 6,
        );
    }
    assert_eq!(m.tenths(), Some(100));
    m.presented(Duration::from_secs(3), true, 70);
    assert_eq!(m.tenths(), Some(0));
}
#[test]
fn fast_forward_does_not_count_unpresented_core_frames() {
    let mut m = Meter::default();
    m.presented(Duration::ZERO, true, 0);
    for i in 1..=60 {
        m.presented(Duration::from_secs_f64(i as f64 / 60.0), true, i * 6);
    }
    assert_eq!(m.tenths(), Some(600));
}
#[test]
fn menus_suspend_and_new_sessions_discard_stale_samples() {
    let mut m = Meter::default();
    m.presented(Duration::ZERO, true, 10);
    m.presented(Duration::from_secs(1), true, 11);
    assert!(m.tenths().is_some());
    m.presented(Duration::from_secs(2), false, 11);
    assert_eq!(m.tenths(), None);
    m.presented(Duration::from_secs(100), true, 1);
    assert_eq!(m.tenths(), None);
    m.presented(Duration::from_secs(101), true, 2);
    assert_eq!(m.tenths(), Some(10));
    m.presented(Duration::from_secs(102), true, 0);
    assert_eq!(m.tenths(), None);
    m.reset();
    assert_eq!(m.tenths(), None);
}
#[test]
fn integer_digits_fit_the_corner_outside_every_game_and_border_style() {
    assert_eq!(slot::game_fps::integer(Some(599)), Some(60));
    assert_eq!(slot::game_fps::integer(Some(594)), Some(59));
    assert_eq!(slot::game_fps::integer(Some(9999)), Some(999));
    assert_eq!(slot::game_fps::integer(None), None);
    let (x, y, w, h) = placement((640, 480)).unwrap();
    let (x, w) = (x * 640.0 / 720.0, w * 640.0 / 720.0);
    assert_eq!((x, y, w, h), (606.0, 464.0, 31.0, 13.0));
    for platform in slot_store::Platform::ALL {
        for integer in [false, true] {
            let (gx, gy, gw, gh) = if integer {
                slot_gfx::integer_game_panel_rect((640, 480), platform.picture())
            } else {
                slot_gfx::game_panel_rect((640, 480), platform.picture(), false)
            };
            let top = 480 - gy - gh;
            assert!(x >= ((gx + gw) as f32) || y >= ((top + gh) as f32));
        }
    }
    for value in [None, Some(0), Some(59), Some(60), Some(999)] {
        let rgba = face(value);
        assert_eq!(rgba.len(), (WIDTH * HEIGHT * 4) as usize);
        assert!(rgba.chunks_exact(4).any(|p| p == [255; 4]));
        assert!(rgba.chunks_exact(4).all(|p| p == [0; 4] || p == [255; 4]));
    }
    assert!(placement((720, 480)).is_none());
}

#[test]
fn counter_toggle_persists_and_does_not_change_on_the_shelf() {
    use slot::{app::App, app::Phase};
    use slot_store::{read_slot_state, write_slot_state, SlotState};
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(root.path().join("Games/GBA")).unwrap();
    std::fs::create_dir_all(root.path().join("Config")).unwrap();
    let mut rom = vec![0u8; 1024];
    rom[3] = 0xea;
    rom[0xb2] = 0x96;
    std::fs::write(root.path().join("Games/GBA/Test.gba"), rom).unwrap();
    write_slot_state(
        root.path(),
        &SlotState {
            cart: Some("Test".into()),
            clock_set: true,
            ..SlotState::default()
        },
    )
    .unwrap();
    let mut app = App::boot(root.path());
    app.on_core_ready();
    for _ in 0..120 {
        app.update(1.0 / 60.0);
    }
    assert!(matches!(app.phase(), Phase::Playing { .. }));
    assert!(app.show_fps());
    app.apply(slot_input::Action::FpsToggle);
    assert!(!app.show_fps());
    assert!(!read_slot_state(root.path()).show_fps);
    assert!(!App::boot(root.path()).show_fps());
    app.apply(slot_input::Action::FpsToggle);
    assert!(app.show_fps());
    let root2 = tempfile::tempdir().unwrap();
    let mut shelf = App::boot(root2.path());
    shelf.apply(slot_input::Action::FpsToggle);
    assert!(shelf.show_fps());
}
