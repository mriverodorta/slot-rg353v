use slot_store::{
    read_slot_state, write_slot_state, Platform, PlayerFeature, PlayerFeatures, Recent, SlotState,
};
fn root() -> tempfile::TempDir {
    let d = tempfile::tempdir().unwrap();
    std::fs::create_dir(d.path().join("Config")).unwrap();
    d
}
#[test]
fn all_switches_default_on_and_legacy_settings_keep_that_behavior() {
    let d = root();
    write_slot_state(d.path(), &SlotState::default()).unwrap();
    let file = d.path().join("Config/slot.state");
    let legacy = std::fs::read_to_string(&file)
        .unwrap()
        .lines()
        .filter(|l| !l.starts_with("feature_"))
        .collect::<Vec<_>>()
        .join("\n");
    std::fs::write(file, legacy + "\n").unwrap();
    let s = read_slot_state(d.path());
    for f in PlayerFeature::ALL {
        assert!(s.player_features.enabled(f));
    }
}
#[test]
fn independent_switches_round_trip_without_removing_bookmarks_or_resume() {
    let d = root();
    let mut s = SlotState {
        cart: Some("Zelda".into()),
        ..Default::default()
    };
    s.favorites.push(Recent {
        platform: Platform::Gba,
        stem: "Zelda".into(),
    });
    for f in PlayerFeature::ALL {
        let before = s.player_features;
        s.player_features.toggle(f);
        write_slot_state(d.path(), &s).unwrap();
        let r = read_slot_state(d.path());
        assert_eq!(r.player_features, s.player_features);
        assert_eq!(r.cart, s.cart);
        assert_eq!(r.favorites, s.favorites);
        s.player_features.toggle(f);
        assert_eq!(s.player_features, before);
    }
}
#[test]
fn invalid_or_future_policy_keys_do_not_disable_features() {
    let mut p = PlayerFeatures::default();
    p.parse_line("feature_future", "0");
    p.parse_line("feature_manual_states", "bad");
    for f in PlayerFeature::ALL {
        assert!(p.enabled(f));
    }
}
