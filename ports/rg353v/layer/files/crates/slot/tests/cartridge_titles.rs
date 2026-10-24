use slot::app::App;
use slot::content::Refresh;
use slot_gfx::{Draw, TexId};
use slot_input::{Action, Btn};
use slot_store::{Cart, Platform};

fn cart(stem: &str, platform: Platform) -> Cart {
    Cart {
        platform,
        stem: stem.into(),
        rom: format!("Games/{}/{stem}.rom", platform.name()).into(),
        label: None,
        title: "SHORT HEADER".into(),
        code: String::new(),
        shell: None,
    }
}
fn app(names: &[&str]) -> App {
    App::new(names.iter().map(|name| cart(name, Platform::Gba)).collect())
}
fn alpha(a: &App, tex: TexId) -> f32 {
    let mut draws = Vec::new();
    a.draw(&mut draws);
    draws
        .iter()
        .find_map(|d| match d {
            Draw::Tex {
                tex: face, alpha, ..
            } if *face == tex => Some(*alpha),
            _ => None,
        })
        .unwrap_or(0.0)
}
fn release(a: &mut App, button: Btn) {
    a.apply(Action::GbaUp(button));
}

#[test]
fn horizontal_navigation_names_the_selected_game_instead_of_its_short_header() {
    let mut a = app(&[
        "Alpha",
        "The Legend of Zelda - A Link to the Past (USA) [!]",
        "Zzz",
    ]);
    a.apply(Action::GbaDown(Btn::Right));
    assert_eq!(
        a.slot_text().as_deref(),
        Some("The Legend of Zelda A Link to the Past")
    );
    assert!(a.showing_cart_name());
    release(&mut a, Btn::Right);
    a.apply(Action::GbaDown(Btn::Left));
    assert_eq!(a.slot_text().as_deref(), Some("Alpha"));
    release(&mut a, Btn::Left);
    a.apply(Action::ShelfLeft);
    assert_eq!(a.slot_text().as_deref(), Some("Zzz"));
}

#[test]
fn the_title_uses_the_system_labels_fade_and_restarts_for_each_new_selection() {
    let mut a = app(&["Alpha", "Bravo", "Charlie"]);
    a.apply(Action::ShelfRight);
    release(&mut a, Btn::Right);
    let face = TexId::from_raw(7001);
    a.set_shelf_platform_face(face, 100);
    a.update(0.0);
    a.update(0.1);
    assert!((alpha(&a, face) - 0.5).abs() < 0.02);
    a.update(0.1);
    assert_eq!(alpha(&a, face), 1.0);
    a.update(1.2);
    assert_eq!(alpha(&a, face), 1.0);
    a.update(0.4);
    assert!((alpha(&a, face) - 0.5).abs() < 0.02);
    a.update(0.4);
    assert_eq!(alpha(&a, face), 0.0);
    a.apply(Action::ShelfRight);
    release(&mut a, Btn::Right);
    assert_eq!(a.slot_text().as_deref(), Some("Charlie"));
    a.set_shelf_platform_face(face, 100);
    a.update(0.0);
    a.update(0.3);
    assert_eq!(alpha(&a, face), 1.0);
}

#[test]
fn held_scrolling_updates_the_title_and_stops_updating_on_release() {
    let mut a = app(&["Alpha", "Bravo", "Charlie", "Delta"]);
    a.apply(Action::ShelfRight);
    assert_eq!(a.slot_text().as_deref(), Some("Bravo"));
    a.update(0.41);
    assert_eq!(a.slot_text().as_deref(), Some("Charlie"));
    a.update(0.12);
    assert_eq!(a.slot_text().as_deref(), Some("Delta"));
    release(&mut a, Btn::Right);
    a.update(1.0);
    assert_eq!(a.slot_text().as_deref(), Some("Delta"));
}

#[test]
fn equal_cleaned_titles_reuse_the_face_and_still_restart_the_timer() {
    let mut a = app(&["Alpha (USA)", "Alpha (Europe)"]);
    a.apply(Action::ShelfRight);
    release(&mut a, Btn::Right);
    let face = TexId::from_raw(7002);
    a.set_shelf_platform_face(face, 100);
    a.update(0.0);
    a.update(3.0);
    assert_eq!(alpha(&a, face), 0.0);
    a.apply(Action::ShelfRight);
    release(&mut a, Btn::Right);
    assert_eq!(a.slot_text().as_deref(), Some("Alpha"));
    a.update(0.0);
    a.update(0.3);
    assert_eq!(alpha(&a, face), 1.0);
}

#[test]
fn system_and_alphabet_navigation_keep_their_original_labels() {
    let mut a = App::new(vec![
        cart("Alpha", Platform::Gba),
        cart("Bravo", Platform::Gba),
        cart("Grey", Platform::Gb),
    ]);
    a.apply(Action::ShelfRight);
    release(&mut a, Btn::Right);
    a.apply(Action::GbaDown(Btn::Down));
    assert_eq!(a.slot_text().as_deref(), Some("A"));
    assert!(!a.showing_cart_name());
    a.apply(Action::NextShelf);
    assert_eq!(a.slot_text().as_deref(), a.shelf_platform_name());
    assert!(!a.showing_cart_name());
}

#[test]
fn a_single_cartridge_does_not_trigger_a_label_without_a_selection_change() {
    let mut a = app(&["Alpha"]);
    a.apply(Action::ShelfRight);
    a.update(0.5);
    assert_eq!(a.slot_text(), None);
    assert!(!a.showing_cart_name());
}

#[test]
fn menus_and_game_insertion_do_not_draw_the_cartridge_title() {
    let mut a = app(&["Alpha", "Bravo"]);
    a.apply(Action::ShelfRight);
    release(&mut a, Btn::Right);
    let face = TexId::from_raw(7003);
    a.set_shelf_platform_face(face, 100);
    a.update(0.0);
    a.update(0.3);
    assert_eq!(alpha(&a, face), 1.0);
    a.apply(Action::QuickMenu);
    assert_eq!(alpha(&a, face), 0.0);
    a.apply(Action::QuickMenu);
    a.apply(Action::Insert);
    assert_eq!(alpha(&a, face), 0.0);
}

#[test]
fn removing_the_selected_game_does_not_leave_its_title_on_the_replacement() {
    let mut a = app(&["Alpha", "Bravo", "Charlie"]);
    a.apply(Action::ShelfRight);
    release(&mut a, Btn::Right);
    a.refresh_content(&Refresh {
        carts: vec![cart("Alpha", Platform::Gba), cart("Charlie", Platform::Gba)],
        wallpapers: Vec::new(),
        changed_labels: Default::default(),
        changed_wallpapers: Default::default(),
        issues: Vec::new(),
    });
    assert_eq!(a.slot_text().as_deref(), Some("Charlie"));
}

#[test]
fn title_text_fits_the_native_label_band_and_the_available_panel_width() {
    for title in [
        "Metroid Fusion",
        "The Legend of Zelda A Link to the Past and Four Swords",
        &"Long game title ".repeat(40),
        "Pokémon Édition Française",
    ] {
        let face = slot_ui::cartridge_title_face(title);
        assert!(face.w <= slot_gfx::OUT_W - 48);
        assert_eq!(face.h, slot_ui::HINT_H);
        assert_eq!(face.rgba.len(), (face.w * face.h * 4) as usize);
        assert!(face.rgba.chunks_exact(4).any(|p| p[3] > 0));
        assert!(slot_ui::slot_name_y() + (face.h as f32) < slot_ui::FOOTER_Y);
    }
}
