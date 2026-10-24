#![cfg(feature = "rg353v")]

mod common;
use slot::{
    app::{App, Phase},
    audio::StubSink,
    session::Session,
};
use slot_input::{Action, Btn, RawEvent};
use slot_store::{
    read_controls, read_shortcuts, read_slot_state, write_slot_state, Binding, Device, GameButton,
    Modifier, Shader, Shortcut, SlotState,
};
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

fn shelf() -> (tempfile::TempDir, App) {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    let a = App::boot(d.path());
    (d, a)
}
#[test]
fn hold_direction_repeats_menus_and_stops_on_release() {
    let (_d, mut a) = shelf();
    a.apply(Action::QuickMenu);
    a.apply_at(Action::GbaDown(Btn::Down), 100);
    let first = a.quick_menu();
    a.tick_ms(499);
    assert_eq!(a.quick_menu(), first);
    a.tick_ms(501);
    assert_ne!(a.quick_menu(), first);
    a.apply_at(Action::GbaUp(Btn::Down), 502);
    let last = a.quick_menu();
    a.tick_ms(1500);
    assert_eq!(a.quick_menu(), last);
}
#[test]
fn favorites_and_browsed_selection_survive_power_off_and_missing_games() {
    let (d, mut a) = shelf();
    a.apply(Action::Favorite);
    assert!(read_after(&mut a, d.path())
        .favorites
        .iter()
        .any(|r| r.stem == "Alpha"));
    a.apply(Action::NextShelf); // Favorites precedes console shelves.
    for _ in 0..5 {
        if a.shelf_platform_name() == Some("Favorites") {
            break;
        }
        a.apply(Action::NextShelf);
    }
    assert_eq!(a.shelf_platform_name(), Some("Favorites"));
    assert_eq!(a.selected_stem(), Some("Alpha"));
    a.apply(Action::PowerHold);
    press(&mut a, Btn::Down);
    press(&mut a, Btn::A);
    a.poweroff();
    drop(a);
    let b = App::boot(d.path());
    assert_eq!(b.shelf_platform_name(), Some("Favorites"));
    assert_eq!(b.selected_stem(), Some("Alpha"));
    drop(b);
    std::fs::remove_file(d.path().join("Games/GBA/Alpha.gba")).unwrap();
    let c = App::boot(d.path());
    assert_eq!(c.selected_stem(), Some("Beta"));
}
fn read_after(a: &mut App, p: &std::path::Path) -> SlotState {
    a.poweroff();
    read_slot_state(p)
}
#[test]
fn legacy_shared_screen_choices_migrate_and_each_console_keeps_its_own_choice() {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    write_slot_state(
        d.path(),
        &SlotState {
            clock_set: true,
            shader_gb: Shader::ShimmerlessLcd,
            colour_correction: false,
            ..Default::default()
        },
    )
    .unwrap();
    let mut a = App::boot(d.path());
    open(&mut a, QuickRow::GbcShader);
    assert_eq!(
        a.quick_value(QuickRow::GbcShader),
        a.quick_value(QuickRow::GbShader)
    );
    press(&mut a, Btn::Right);
    assert_ne!(
        a.quick_value(QuickRow::GbcShader),
        a.quick_value(QuickRow::GbShader)
    );
    open(&mut a, QuickRow::GbColourCorrection);
    press(&mut a, Btn::Right);
    assert!(!a.colour_correction_for(slot_store::Platform::Gba));
    assert!(a.colour_correction_for(slot_store::Platform::Gb));
    assert!(!a.colour_correction_for(slot_store::Platform::Gbc));
    a.poweroff();
    let saved = read_slot_state(d.path());
    assert!(saved.shader_gbc.is_some());
    assert_eq!(saved.colour_correction_gb, Some(true));
    assert!(!saved.colour_correction);
}
#[test]
fn pause_navigation_uses_existing_hierarchy_and_keeps_overlay_scaling_locked() {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    let mut a = common::app_playing_in(d.path(), "Alpha");
    a.apply(Action::QuickMenu);
    assert_eq!(a.in_game_menu(), Some(QuickRow::Resume));
    press(&mut a, Btn::Down);
    press(&mut a, Btn::Down);
    press(&mut a, Btn::A);
    assert_eq!(a.in_game_menu(), Some(QuickRow::PlayScreen));
    press(&mut a, Btn::A);
    assert_eq!(a.in_game_menu(), Some(QuickRow::Shader));
    let before = a.picture_rect();
    a.apply(Action::GbaDown(Btn::L1));
    assert_eq!(a.picture_rect(), before);
    press(&mut a, Btn::B);
    assert_eq!(a.in_game_menu(), Some(QuickRow::PlayScreen));
    press(&mut a, Btn::B);
    assert_eq!(a.in_game_menu(), Some(QuickRow::Settings));
    press(&mut a, Btn::B);
    assert_eq!(a.in_game_menu(), None);
    assert!(matches!(a.phase(), Phase::Playing { .. }));
}
#[test]
fn controls_bind_clear_reset_and_warn_about_conflicting_shortcuts() {
    let (d, mut a) = shelf();
    open(&mut a, QuickRow::GameA);
    press(&mut a, Btn::A);
    assert!(a.capturing());
    a.capture_input(RawEvent::Down(Btn::Y));
    assert_eq!(
        read_controls(d.path()).game(GameButton::A),
        Binding::plain(Device::Y)
    );
    press(&mut a, Btn::X);
    assert_eq!(a.controls().game(GameButton::A), None);
    press(&mut a, Btn::Y);
    press(&mut a, Btn::A);
    assert_eq!(a.controls().game(GameButton::A), Binding::plain(Device::A));
    open(&mut a, QuickRow::ScSave);
    press(&mut a, Btn::A);
    a.capture_input(RawEvent::Down(Btn::Select));
    a.capture_input(RawEvent::Down(Btn::X));
    assert_eq!(
        read_shortcuts(d.path()).get(Shortcut::SaveState),
        Binding::with(Modifier::Select, Device::X)
    );
    assert_eq!(a.clash(QuickRow::ScSave), Some(QuickRow::ScFps));
    assert_eq!(a.clash(QuickRow::ScFps), Some(QuickRow::ScSave));
    assert!(a
        .quick_numbers()
        .iter()
        .any(|(r, s)| *r == QuickRow::Controls && s.contains("Frame Counter")));
}
#[test]
fn default_select_x_still_toggles_the_counter_and_f_still_ejects() {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    let mut s = Session::boot_with(d.path().into(), Box::new(StubSink::draining()));
    s.app_mut().apply(Action::Insert);
    let until = std::time::Instant::now() + std::time::Duration::from_secs(3);
    while !matches!(s.app().phase(), Phase::Playing { .. }) {
        s.update(1.0 / 60.0);
        std::thread::sleep(std::time::Duration::from_millis(1));
        assert!(std::time::Instant::now() < until);
    }
    let before = s.app().show_fps();
    s.feed([RawEvent::Down(Btn::Select), RawEvent::Down(Btn::X)], 2000);
    assert_ne!(s.app().show_fps(), before);
    s.feed(
        [
            RawEvent::Up(Btn::X),
            RawEvent::Up(Btn::Select),
            RawEvent::Down(Btn::Menu),
        ],
        2100,
    );
    s.feed([], 3200);
    assert!(matches!(s.app().phase(), Phase::Ejecting { .. }));
}

#[test]
fn enhanced_audio_is_opt_in_and_keeps_the_standard_boot_default() {
    let (d, mut a) = shelf();
    assert_eq!(a.audio_rate(), 32768);
    open(&mut a, QuickRow::EnhancedAudio);
    press(&mut a, Btn::Right);
    assert_eq!(a.audio_rate(), 48000);
    a.poweroff();
    assert!(read_slot_state(d.path()).enhanced_audio);
    assert_eq!(App::boot(d.path()).audio_rate(), 48000);
}
#[test]
fn editing_gb_first_does_not_change_the_migrated_gbc_shader() {
    let (d, mut a) = shelf();
    let before = a.quick_value(QuickRow::GbcShader);
    open(&mut a, QuickRow::GbShader);
    press(&mut a, Btn::Right);
    assert_eq!(a.quick_value(QuickRow::GbcShader), before);
    assert_ne!(a.quick_value(QuickRow::GbShader), before);
    assert!(read_slot_state(d.path()).shader_gbc.is_some());
}

#[test]
fn remapped_console_buttons_and_f_chords_reach_the_running_core() {
    use slot_retro::ButtonMask;
    use slot_store::{write_controls, Controls};
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    common::clocked(d.path());
    let mut controls = Controls::default();
    controls.set_game(GameButton::A, Binding::plain(Device::X));
    controls.set_game(GameButton::TurboA, None);
    controls.set_game(GameButton::B, Binding::with(Modifier::Menu, Device::Y));
    write_controls(d.path(), &controls).unwrap();
    let mut s = Session::boot_with(d.path().into(), Box::new(StubSink::draining()));
    s.app_mut().apply(Action::Insert);
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
    while !matches!(s.app().phase(), Phase::Playing { .. }) {
        s.update(1.0 / 60.0);
        std::thread::sleep(std::time::Duration::from_millis(1));
        assert!(std::time::Instant::now() < deadline);
    }
    s.feed([RawEvent::Down(Btn::X)], 2000);
    assert_eq!(s.emu().unwrap().input().0, ButtonMask::A);
    s.feed(
        [
            RawEvent::Up(Btn::X),
            RawEvent::Down(Btn::Menu),
            RawEvent::Down(Btn::Y),
        ],
        2100,
    );
    assert_eq!(s.emu().unwrap().input().0, ButtonMask::B);
    s.feed([RawEvent::Up(Btn::Y), RawEvent::Up(Btn::Menu)], 2200);
    assert_eq!(s.emu().unwrap().input().0, 0);
    assert!(s.app().in_game_menu().is_none());
    assert!(matches!(s.app().phase(), Phase::Playing { .. }));
}
#[test]
fn remapped_shortcut_and_favorite_are_used_by_real_raw_input() {
    use slot_store::{write_carousel, write_shortcuts, CarouselAction, CarouselKeys, ShortcutKeys};
    let (d, _) = shelf();
    let mut shortcuts = ShortcutKeys::default();
    shortcuts.set(
        Shortcut::FrameCounter,
        Binding::with(Modifier::Select, Device::Start),
    );
    write_shortcuts(d.path(), &shortcuts).unwrap();
    let mut carousel = CarouselKeys::default();
    carousel.set(CarouselAction::Favorite, Binding::plain(Device::X));
    write_carousel(d.path(), &carousel).unwrap();
    let mut s = Session::boot_with(d.path().into(), Box::new(StubSink::draining()));
    s.feed([RawEvent::Down(Btn::X), RawEvent::Up(Btn::X)], 0);
    assert_eq!(read_slot_state(d.path()).favorites.len(), 1);
    s.feed([RawEvent::Down(Btn::Y), RawEvent::Up(Btn::Y)], 20);
    assert_eq!(read_slot_state(d.path()).favorites.len(), 1);
    s.app_mut().apply(Action::Insert);
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
    while !matches!(s.app().phase(), Phase::Playing { .. }) {
        s.update(1.0 / 60.0);
        std::thread::sleep(std::time::Duration::from_millis(1));
        assert!(std::time::Instant::now() < deadline);
    }
    let before = s.app().show_fps();
    s.feed(
        [RawEvent::Down(Btn::Select), RawEvent::Down(Btn::Start)],
        2000,
    );
    assert_ne!(s.app().show_fps(), before);
    s.feed([RawEvent::Up(Btn::Start), RawEvent::Up(Btn::Select)], 2010);
    s.feed([RawEvent::Down(Btn::Select), RawEvent::Down(Btn::X)], 2100);
    assert_ne!(s.app().show_fps(), before, "old shortcut still active");
}

#[test]
fn pause_never_overrides_the_power_dialog_and_sleep_closes_pause_settings() {
    let d = common::tmp_root_with_real_carts(&["Alpha", "Beta"]);
    let mut a = common::app_playing_in(d.path(), "Alpha");
    a.apply(Action::PowerHold);
    assert!(a.power_menu().is_some());
    a.apply(Action::QuickMenu);
    assert!(a.in_game_menu().is_none());
    assert!(a.power_menu().is_some());
    press(&mut a, Btn::B);
    a.apply(Action::QuickMenu);
    assert!(a.in_game_menu().is_some());
    a.apply(Action::PowerPress);
    a.apply(Action::PowerTap);
    assert!(matches!(a.phase(), Phase::Doze { .. }));
    assert!(a.in_game_menu().is_none());
    a.apply(Action::PowerPress);
    a.apply(Action::PowerTap);
    assert!(matches!(a.phase(), Phase::Playing { .. }));
    assert!(a.in_game_menu().is_none());
}

#[test]
fn optional_cpu_governor_choice_is_saved_independently_and_defaults_off() {
    let (d, mut a) = shelf();
    assert!(!a.schedutil_governor());
    open(&mut a, QuickRow::SchedutilGovernor);
    press(&mut a, Btn::Right);
    assert!(a.schedutil_governor());
    assert_eq!(a.audio_rate(), 32768);
    a.poweroff();
    assert!(read_slot_state(d.path()).schedutil_governor);
    let mut a = App::boot(d.path());
    assert!(a.schedutil_governor());
    open(&mut a, QuickRow::SchedutilGovernor);
    press(&mut a, Btn::Left);
    a.poweroff();
    assert!(!App::boot(d.path()).schedutil_governor());
}
