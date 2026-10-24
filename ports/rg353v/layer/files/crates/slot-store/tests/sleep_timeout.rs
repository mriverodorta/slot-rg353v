use slot_store::{read_slot_state, write_slot_state, SlotState, SLEEP_TIMEOUT_MINUTES};

#[test]
fn sleep_timeout_roundtrips_and_old_or_invalid_settings_keep_preferences() {
    let d = tempfile::tempdir().unwrap();
    std::fs::create_dir(d.path().join("Config")).unwrap();
    let mut state = SlotState {
        brightness: 9,
        volume: 30,
        ..SlotState::default()
    };
    for minutes in SLEEP_TIMEOUT_MINUTES {
        state.sleep_shutdown_minutes = minutes;
        write_slot_state(d.path(), &state).unwrap();
        assert_eq!(read_slot_state(d.path()), state);
    }
    let p = d.path().join("Config/slot.state");
    let text = std::fs::read_to_string(&p).unwrap();
    for value in [None, Some("-1"), Some("garbage"), Some("2"), Some("255")] {
        let old = text
            .lines()
            .filter(|l| !l.starts_with("sleep_shutdown_minutes="))
            .collect::<Vec<_>>()
            .join("\n");
        let text = match value {
            Some(v) => format!("{old}\nsleep_shutdown_minutes={v}\n"),
            None => format!("{old}\n"),
        };
        std::fs::write(&p, text).unwrap();
        state.sleep_shutdown_minutes = 3;
        assert_eq!(read_slot_state(d.path()), state);
    }
}
