mod common;
use slot::{app::App, features::Features};
use slot_input::{Action, Btn};
use slot_store::{read_slot_state, write_slot_state, SlotState, WallpaperPick};
use slot_ui::QuickRow;
fn press(a: &mut App, b: Btn) {
    a.apply(Action::GbaDown(b));
    a.apply(Action::GbaUp(b));
}
fn open(a: &mut App, row: QuickRow) {
    while a.quick_menu().is_some() {
        press(a, Btn::B);
    }
    a.apply(Action::QuickMenu);
    let mut chain = vec![row];
    while let Some(p) = chain.last().unwrap().parent() {
        chain.push(p);
    }
    for target in chain.into_iter().rev() {
        for _ in 0..QuickRow::ALL.len() {
            if a.quick_menu() == Some(target) {
                break;
            }
            press(a, Btn::Down);
        }
        assert_eq!(a.quick_menu(), Some(target));
        if target != row {
            press(a, Btn::A);
        }
    }
}
#[test]
fn random_wallpaper_is_opt_in_stable_and_survives_restart() {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    std::fs::create_dir_all(d.path().join("Wallpapers")).unwrap();
    for name in ["one.png", "two.png"] {
        std::fs::write(d.path().join("Wallpapers").join(name), b"fixture").unwrap();
    }
    let mut a = App::boot(d.path());
    assert_eq!(a.shown_wallpaper(), WallpaperPick::QuietCurrent);
    assert!(!d.path().join("Config/wallpaper.deck").exists());
    drop(a);
    let state = SlotState {
        clock_set: true,
        wallpaper: WallpaperPick::Random,
        wallpaper_dimming: 40,
        ..Default::default()
    };
    write_slot_state(d.path(), &state).unwrap();
    let mut a = App::boot(d.path());
    let first = a.shown_wallpaper();
    assert!(matches!(first, WallpaperPick::File(_)));
    for _ in 0..10 {
        assert_eq!(first, a.shown_wallpaper());
    }
    a.poweroff();
    drop(a);
    let saved = read_slot_state(d.path());
    assert_eq!(saved.wallpaper, WallpaperPick::Random);
    assert_eq!(saved.wallpaper_dimming, 40);
    let mut a = App::boot(d.path());
    assert_ne!(
        first,
        a.shown_wallpaper(),
        "deck must avoid immediate repeats"
    );
}
#[test]
fn empty_random_deck_falls_back_and_dimming_wraps() {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    write_slot_state(
        d.path(),
        &SlotState {
            clock_set: true,
            wallpaper: WallpaperPick::Random,
            ..Default::default()
        },
    )
    .unwrap();
    let mut a = App::boot(d.path());
    assert_eq!(a.shown_wallpaper(), WallpaperPick::QuietCurrent);
    open(&mut a, QuickRow::WallpaperDimming);
    assert_eq!(
        a.quick_numbers()
            .into_iter()
            .find(|(r, _)| *r == QuickRow::WallpaperDimming)
            .unwrap()
            .1,
        "Off"
    );
    for value in ["20%", "40%", "60%", "Off"] {
        press(&mut a, Btn::Right);
        assert_eq!(
            a.quick_numbers()
                .into_iter()
                .find(|(r, _)| *r == QuickRow::WallpaperDimming)
                .unwrap()
                .1,
            value
        );
    }
    press(&mut a, Btn::Left);
    assert_eq!(
        a.quick_numbers()
            .into_iter()
            .find(|(r, _)| *r == QuickRow::WallpaperDimming)
            .unwrap()
            .1,
        "60%"
    );
}
#[test]
fn pause_is_logical_immediately_but_only_reveals_after_180ms_or_navigation() {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    let mut a = common::app_playing_in(d.path(), "Alpha");
    a.apply_at(Action::QuickMenu, 2000);
    assert!(a.in_game_menu().is_some());
    assert!(!a.pause_visible());
    a.tick_ms(2179);
    assert!(!a.pause_visible());
    a.tick_ms(2180);
    assert!(a.pause_visible());
    press(&mut a, Btn::B);
    a.apply_at(Action::QuickMenu, 3000);
    assert!(!a.pause_visible());
    press(&mut a, Btn::Down);
    assert!(a.pause_visible());
    press(&mut a, Btn::B);
    a.apply_at(Action::QuickMenu, 4000);
    assert!(!a.pause_visible());
    a.apply_at(Action::Polaroids, 4100);
    assert!(a.in_game_menu().is_none());
    assert!(!a.pause_visible());
}
#[test]
fn storage_tool_is_an_optional_direct_system_row() {
    assert_eq!(QuickRow::StorageTools.parent(), Some(QuickRow::System));
    assert!(QuickRow::StorageTools.opens());
    let minimal = Features::parse("slot-features-v1\nemulator-mgba\n");
    assert!(!minimal.visible(QuickRow::StorageTools));
    let tools = Features::parse("slot-features-v1\nemulator-mgba\nstorage-tools\n");
    assert!(tools.visible(QuickRow::StorageTools));
    assert!(!tools.visible(QuickRow::Diagnostics));
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    let mut a = App::boot(d.path());
    open(&mut a, QuickRow::StorageTools);
    press(&mut a, Btn::A);
    assert!(a.diagnostics_view()[0].contains("Storage"));
    press(&mut a, Btn::B);
    assert!(a.diagnostics_view().is_empty());
}
