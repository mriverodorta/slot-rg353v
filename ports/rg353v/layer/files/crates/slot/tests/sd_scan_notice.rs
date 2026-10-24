mod common;
use slot::{app::App, content::Refresh};
use slot_gfx::{Draw, TexId};
use slot_input::Action;
use slot_store::{write_slot_state, SlotState};
use std::collections::BTreeSet;

#[test]
fn scan_reuses_the_name_area_survives_refresh_and_restores_the_current_name() {
    let root = common::tmp_root_with_carts(&["Alpha", "Bravo"]);
    write_slot_state(
        root.path(),
        &SlotState {
            clock_set: true,
            ..SlotState::default()
        },
    )
    .unwrap();
    let mut app = App::boot(root.path());
    app.apply(Action::ShelfRight);
    let normal = app.slot_text();
    assert!(app.showing_cart_name());
    app.set_sd_scan_activity(true, true);
    assert_eq!(
        app.slot_text().as_deref(),
        Some("Scanning SD card for games...")
    );
    assert!(!app.showing_cart_name());
    assert!(app.slot_text_needs_face());
    app.set_shelf_platform_face(TexId::from_raw(999), 420);
    app.update(250.0 / 1000.0);
    let mut draws = vec![];
    app.draw(&mut draws);
    assert!(draws
        .iter()
        .any(|d| matches!(d, Draw::Tex {tex,x,y,alpha,..}
        if *tex==TexId::from_raw(999) && *x==(slot_gfx::OUT_W as f32-420.0)/2.0 && *y==slot_ui::slot_name_y() && *alpha==1.0)));
    let carts = app.carts().cloned().collect();
    app.refresh_content(&Refresh {
        carts,
        wallpapers: vec![],
        changed_labels: BTreeSet::new(),
        changed_wallpapers: BTreeSet::new(),
        issues: vec![],
    });
    assert_eq!(
        app.slot_text().as_deref(),
        Some("Scanning SD card for games...")
    );
    app.update(5000.0 / 1000.0);
    assert_eq!(
        app.slot_text().as_deref(),
        Some("Scanning SD card for games...")
    );
    app.set_sd_scan_activity(false, false);
    app.update(400.0 / 1000.0);
    app.update(400.0 / 1000.0);
    assert_eq!(app.slot_text(), normal);
    assert!(app.showing_cart_name());
    assert!(app.slot_text_needs_face());
}

#[test]
fn ordinary_boot_does_not_show_scan_feedback_or_change_saved_settings() {
    let root = common::tmp_root_with_carts(&["Alpha", "Bravo"]);
    write_slot_state(
        root.path(),
        &SlotState {
            clock_set: true,
            ..SlotState::default()
        },
    )
    .unwrap();
    let before = std::fs::read(root.path().join("Config/slot.state")).unwrap();
    let mut app = App::boot(root.path());
    assert_ne!(
        app.slot_text().as_deref(),
        Some("Scanning SD card for games...")
    );
    app.set_sd_scan_activity(true, false); // Start and completion between frames.
    app.update(1200.0 / 1000.0);
    assert_eq!(
        app.slot_text().as_deref(),
        Some("Scanning SD card for games...")
    );
    app.update(800.0 / 1000.0);
    assert_ne!(
        app.slot_text().as_deref(),
        Some("Scanning SD card for games...")
    );
    assert_eq!(
        before,
        std::fs::read(root.path().join("Config/slot.state")).unwrap()
    );
}
