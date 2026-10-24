mod common;
use slot::{
    app::{App, Phase},
    features::Features,
};
use slot_input::{Action, Btn};
use slot_store::{
    read_slot_state, write_slot_state, Core, Platform, PlayerFeature as F, PlayerFeatures,
    SlotState, StateRing,
};
use slot_ui::{QuickRow, QuickValue};
fn press(a: &mut App, b: Btn) {
    a.apply(Action::GbaDown(b));
    a.apply(Action::GbaUp(b));
}
fn open(a: &mut App, target: QuickRow) {
    while a.quick_menu().is_some() {
        press(a, Btn::B);
    }
    a.apply(Action::QuickMenu);
    let mut chain = vec![target];
    while let Some(p) = chain.last().unwrap().parent() {
        chain.push(p);
    }
    for r in chain.into_iter().rev() {
        for _ in 0..QuickRow::ALL.len() {
            if a.quick_menu() == Some(r) {
                break;
            }
            press(a, Btn::Down);
        }
        assert_eq!(a.quick_menu(), Some(r));
        if r != target {
            press(a, Btn::A);
        }
    }
}
fn policy_off(features: &[F]) -> PlayerFeatures {
    let mut p = PlayerFeatures::default();
    for f in features {
        p.toggle(*f);
    }
    p
}
fn playing(policy: PlayerFeatures) -> (tempfile::TempDir, App, common::Loaded) {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    write_slot_state(
        d.path(),
        &SlotState {
            cart: Some("Alpha".into()),
            clock_set: true,
            player_features: policy,
            ..Default::default()
        },
    )
    .unwrap();
    let (mut_snapshot, loaded) = common::StubSnapshot::pair();
    let mut a = App::boot(d.path());
    a.set_snapshot(mut_snapshot);
    a.on_core_ready();
    for _ in 0..120 {
        a.update(1.0 / 60.0);
    }
    assert!(matches!(a.phase(), Phase::Playing { .. }));
    (d, a, loaded)
}
#[test]
fn requested_order_toggle_methods_and_reboot_persistence() {
    assert_eq!(
        QuickRow::PLAYER_FEATURES.map(|r| r.label()),
        [
            "Save states browser",
            "Manual save states",
            "Favorites",
            "Core selection",
            "Fast-forward",
            "Rewind",
            "Shaders",
            "Palettes",
            "Color Correction"
        ]
    );
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    let mut a = App::boot(d.path());
    for (i, r) in QuickRow::PLAYER_FEATURES.into_iter().enumerate() {
        open(&mut a, r);
        assert_eq!(a.quick_value(r), Some(QuickValue::On));
        press(&mut a, [Btn::A, Btn::Left, Btn::Right][i % 3]);
        assert_eq!(a.quick_value(r), Some(QuickValue::Off));
    }
    a.poweroff();
    drop(a);
    let b = App::boot(d.path());
    for r in QuickRow::PLAYER_FEATURES {
        assert_eq!(b.quick_value(r), Some(QuickValue::Off));
    }
}
#[test]
fn browser_and_manual_shortcuts_are_independent_and_keep_state_files() {
    let (d, mut a, loaded) = playing(policy_off(&[F::ManualStates]));
    let ring = StateRing::new(d.path(), Platform::Gba, Core::Mgba, "Alpha");
    ring.push(&[1, 2, 3], &[], "2026-10-20_10-00-00").unwrap();
    a.apply(Action::SaveState);
    a.apply(Action::LoadState);
    assert_eq!(ring.list().unwrap().len(), 1);
    assert!(loaded.lock().unwrap().is_none());
    a.apply(Action::Polaroids);
    assert!(matches!(a.phase(), Phase::Polaroids { .. }));
    press(&mut a, Btn::A);
    assert_eq!(*loaded.lock().unwrap(), Some(vec![1, 2, 3]));
    let (d, mut a, loaded) = playing(policy_off(&[F::StateBrowser]));
    a.apply(Action::SaveState);
    let ring = StateRing::new(d.path(), Platform::Gba, Core::Mgba, "Alpha");
    assert_eq!(ring.list().unwrap().len(), 1);
    a.apply(Action::Polaroids);
    assert!(matches!(a.phase(), Phase::Playing { .. }));
    a.apply(Action::LoadState);
    assert!(loaded.lock().unwrap().is_some());
    a.apply(Action::QuickMenu);
    press(&mut a, Btn::Down);
    assert_eq!(a.in_game_menu(), Some(QuickRow::Settings)); // States hidden
}
#[test]
fn all_disabled_keeps_eject_resume_and_in_game_save_data() {
    let (d, mut a, _) = playing(policy_off(&F::ALL));
    let save = d.path().join("Saves/GBA/Alpha.sav");
    std::fs::create_dir_all(save.parent().unwrap()).unwrap();
    std::fs::write(&save, [7, 8, 9]).unwrap();
    for action in [
        Action::SaveState,
        Action::LoadState,
        Action::Polaroids,
        Action::FfStart,
        Action::RewindStart,
        Action::ShaderNext,
        Action::ShaderPrev,
        Action::PaletteNext,
        Action::PalettePrev,
        Action::ColourCorrectionToggle,
    ] {
        assert!(!a.action_enabled(action));
        a.apply(action);
    }
    for action in [
        Action::Eject,
        Action::QuickMenu,
        Action::PowerTap,
        Action::VolumeUp,
        Action::BrightnessUp,
        Action::GbaDown(Btn::Start),
    ] {
        assert!(a.action_enabled(action));
    }
    assert!(!a.may_fast_forward());
    assert!(!a.records_rewind());
    assert!(!a.may_rewind());
    a.apply(Action::Eject);
    for _ in 0..120 {
        a.update(1.0 / 60.0);
    }
    a.poweroff();
    assert!(StateRing::new(d.path(), Platform::Gba, Core::Mgba, "Alpha")
        .read_resume()
        .unwrap()
        .is_some());
    assert_eq!(std::fs::read(save).unwrap(), [7, 8, 9]);
}
#[test]
fn favorites_hide_and_return_without_losing_bookmarks_even_after_catalog_refresh() {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    let mut a = App::boot(d.path());
    a.apply(Action::Favorite);
    a.poweroff();
    let before = read_slot_state(d.path()).favorites;
    open(&mut a, QuickRow::FeatureFavorites);
    press(&mut a, Btn::A);
    while a.quick_menu().is_some() {
        press(&mut a, Btn::B);
    }
    a.apply(Action::Favorite);
    let carts = slot_store::scan_library(d.path()).unwrap();
    a.refresh_content(&slot::content::Refresh {
        carts,
        wallpapers: vec![],
        changed_labels: Default::default(),
        changed_wallpapers: Default::default(),
        issues: vec![],
    });
    for _ in 0..8 {
        a.apply(Action::NextShelf);
        assert_ne!(a.shelf_platform_name(), Some("Favorites"));
    }
    a.poweroff();
    assert_eq!(read_slot_state(d.path()).favorites, before);
    open(&mut a, QuickRow::FeatureFavorites);
    press(&mut a, Btn::A);
    while a.quick_menu().is_some() {
        press(&mut a, Btn::B);
    }
    let mut found = false;
    for _ in 0..8 {
        a.apply(Action::NextShelf);
        found |= a.shelf_platform_name() == Some("Favorites");
    }
    assert!(found);
}
#[test]
fn core_selection_off_preserves_selected_core_and_prevents_picker() {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    slot_store::write_selected_core(d.path(), "Alpha", Core::Gpsp).unwrap();
    let mut a = App::boot(d.path());
    assert!(a.core_switchable());
    open(&mut a, QuickRow::FeatureCoreSelection);
    press(&mut a, Btn::A);
    while a.quick_menu().is_some() {
        press(&mut a, Btn::B);
    }
    assert!(!a.core_switchable());
    press(&mut a, Btn::Start);
    assert!(a.core_picker().is_none());
    assert_eq!(a.resolve_core("Alpha", Platform::Gba), Some(Core::Gpsp));
}
#[test]
fn omitted_modules_cannot_be_enabled_through_player_features() {
    let f = Features::parse("slot-features-v1\nemulator-mgba\n");
    assert!(f.visible(QuickRow::FeatureStateBrowser));
    for row in [
        QuickRow::FeatureRewind,
        QuickRow::FeatureInGameShader,
        QuickRow::FeatureInGamePalette,
        QuickRow::FeatureInGameColor,
    ] {
        assert!(!f.visible(row));
    }
}
#[test]
fn picture_locks_keep_defaults_hide_pause_options_and_allow_shelf_settings() {
    let (_d, mut a, _) = playing(policy_off(&[
        F::InGameShader,
        F::InGamePalette,
        F::InGameColor,
    ]));
    let shader = a.screen_shader();
    let color = a.colour_correction();
    for action in [
        Action::ShaderNext,
        Action::ShaderPrev,
        Action::PaletteNext,
        Action::PalettePrev,
        Action::ColourCorrectionToggle,
    ] {
        a.apply(action);
    }
    assert_eq!(a.screen_shader(), shader);
    assert_eq!(a.colour_correction(), color);
    a.apply(Action::QuickMenu);
    // Resume, States, Settings -> Screen. Its first allowed field is Overlay.
    for b in [Btn::Down, Btn::Down, Btn::A, Btn::A, Btn::A] {
        press(&mut a, b);
    }
    assert_eq!(a.in_game_menu(), Some(QuickRow::GameBorder));
    a.apply(Action::Eject);
    for _ in 0..120 {
        a.update(1.0 / 60.0);
    }
    open(&mut a, QuickRow::GbaShader);
    let before = a.quick_value(QuickRow::GbaShader);
    press(&mut a, Btn::Right);
    assert_ne!(a.quick_value(QuickRow::GbaShader), before);
    open(&mut a, QuickRow::GbaColourCorrection);
    let before = a.quick_value(QuickRow::GbaColourCorrection);
    press(&mut a, Btn::Right);
    assert_ne!(a.quick_value(QuickRow::GbaColourCorrection), before);
}
#[test]
fn remapped_and_default_raw_shortcuts_are_blocked_without_breaking_game_controls() {
    use slot::{audio::StubSink, emu::Speed, session::Session};
    use slot_input::RawEvent as E;
    use slot_store::{write_shortcuts, Binding, Device, Modifier, Shortcut, ShortcutKeys};
    use std::time::{Duration, Instant};
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    write_slot_state(
        d.path(),
        &SlotState {
            cart: Some("Alpha".into()),
            clock_set: true,
            player_features: policy_off(&F::ALL),
            ..Default::default()
        },
    )
    .unwrap();
    let mut keys = ShortcutKeys::default();
    keys.set(
        Shortcut::SaveState,
        Binding::with(Modifier::Select, Device::Start),
    );
    keys.set(
        Shortcut::ShaderNext,
        Binding::with(Modifier::Menu, Device::X),
    );
    write_shortcuts(d.path(), &keys).unwrap();
    let mut s = Session::boot_with(d.path().into(), Box::new(StubSink::draining()));
    let deadline = Instant::now() + Duration::from_secs(5);
    while !matches!(s.app().phase(), Phase::Playing { .. }) {
        s.update(1.0 / 60.0);
        std::thread::sleep(Duration::from_millis(1));
        assert!(Instant::now() < deadline);
    }
    let shader = s.app().screen_shader();
    let color = s.app().colour_correction();
    let mut now = 2000;
    for (modifier, button) in [
        (Btn::Select, Btn::Start),
        (Btn::Select, Btn::L1),
        (Btn::Menu, Btn::X),
        (Btn::Select, Btn::Y),
    ] {
        s.feed([E::Down(modifier)], now);
        s.feed([E::Down(button)], now + 10);
        s.feed([E::Up(button), E::Up(modifier)], now + 20);
        now += 100;
    }
    // Fast-forward double-tap and rewind held must stay at normal speed.
    for events in [
        vec![E::Down(Btn::R2)],
        vec![E::Up(Btn::R2)],
        vec![E::Down(Btn::R2)],
        vec![E::Up(Btn::R2)],
        vec![E::Down(Btn::L2)],
    ] {
        s.feed(events, now);
        now += 30;
        s.update(1.0 / 60.0);
    }
    for _ in 0..30 {
        s.update(1.0 / 60.0);
        std::thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(s.observed_speed(), Some(Speed::Normal));
    s.feed([E::Up(Btn::L2)], now);
    assert_eq!(s.app().screen_shader(), shader);
    assert_eq!(s.app().colour_correction(), color);
    assert!(StateRing::new(d.path(), Platform::Gba, Core::Mgba, "Alpha")
        .list()
        .unwrap()
        .is_empty());
    s.feed([E::Down(Btn::A)], now + 50);
    assert_ne!(s.emu().unwrap().input().0 & slot_retro::ButtonMask::A, 0);
    s.feed([E::Up(Btn::A)], now + 60);
    assert_eq!(s.emu().unwrap().input().0 & slot_retro::ButtonMask::A, 0);
}
#[test]
fn game_boy_palette_can_still_be_configured_on_the_shelf_when_its_shortcut_is_off() {
    let d = common::tmp_root_with_gb_carts(&["Alpha", "Beta"]);
    write_slot_state(
        d.path(),
        &SlotState {
            clock_set: true,
            gb_palettes: true,
            player_features: policy_off(&[F::InGamePalette]),
            ..Default::default()
        },
    )
    .unwrap();
    let mut a = App::boot(d.path());
    let before = a.gb_palette();
    a.apply(Action::PaletteNext);
    assert_eq!(a.gb_palette(), before);
    open(&mut a, QuickRow::Palette);
    press(&mut a, Btn::Right);
    assert_ne!(a.gb_palette(), before);
}
#[test]
fn help_omits_disabled_shortcuts_but_keeps_eject_and_resume() {
    let mut m = slot::help::Menu::with_policy(Features::default(), policy_off(&F::ALL));
    m.button(Btn::Down);
    m.button(Btn::A); // Games & saves
    let labels = m.entries().iter().map(|e| e.label).collect::<Vec<_>>();
    assert!(labels.iter().any(|l| l.contains("save & eject")));
    assert!(labels.iter().any(|l| l.contains("resume saved session")));
    for label in labels {
        assert!(!label.contains("state browser"));
        assert_ne!(label, "Save state");
        assert_ne!(label, "Load state");
        assert!(!label.contains("rewind"));
        assert!(!label.contains("fast-forward"));
    }
}
