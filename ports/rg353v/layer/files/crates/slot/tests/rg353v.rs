use slot::input::evdev::{code_to_btn_with_profile, to_raw_with_profile, Ev, InputProfile, EV_KEY};
use slot_input::{Btn, RawEvent};

fn stick_pad() -> slot::input::evdev::DeviceEvents {
    slot::input::evdev::DeviceEvents::new(InputProfile::Rg353v, "retrogame_joypad")
}

fn axis(code: u16, value: i32) -> Ev {
    Ev {
        kind: slot::input::evdev::EV_ABS,
        code,
        value,
    }
}

fn key(code: u16, value: i32) -> Ev {
    Ev {
        kind: EV_KEY,
        code,
        value,
    }
}

#[test]
fn left_stick_supports_four_directions_and_diagonals() {
    let mut pad = stick_pad();
    assert_eq!(pad.feed(axis(0, -1800)), vec![RawEvent::Down(Btn::Left)]);
    assert_eq!(pad.feed(axis(1, -1800)), vec![RawEvent::Down(Btn::Up)]);
    assert_eq!(pad.feed(axis(0, 0)), vec![RawEvent::Up(Btn::Left)]);
    assert_eq!(pad.feed(axis(1, 0)), vec![RawEvent::Up(Btn::Up)]);
    assert_eq!(pad.feed(axis(0, 1800)), vec![RawEvent::Down(Btn::Right)]);
    assert_eq!(pad.feed(axis(1, 1800)), vec![RawEvent::Down(Btn::Down)]);
    assert_eq!(pad.feed(axis(0, 0)), vec![RawEvent::Up(Btn::Right)]);
    assert_eq!(pad.feed(axis(1, 0)), vec![RawEvent::Up(Btn::Down)]);
}

#[test]
fn left_stick_dead_zone_and_hysteresis_prevent_drift_and_chatter() {
    for (code, negative, positive) in [(0, Btn::Left, Btn::Right), (1, Btn::Up, Btn::Down)] {
        let mut pad = stick_pad();
        for value in [-599, -32, 0, 32, 599] {
            assert!(pad.feed(axis(code, value)).is_empty());
        }
        assert_eq!(pad.feed(axis(code, 600)), vec![RawEvent::Down(positive)]);
        for value in [1800, 610, 590, 401, 400] {
            assert!(pad.feed(axis(code, value)).is_empty());
        }
        assert_eq!(pad.feed(axis(code, 399)), vec![RawEvent::Up(positive)]);
        assert_eq!(pad.feed(axis(code, -600)), vec![RawEvent::Down(negative)]);
        for value in [-1800, -590, -400] {
            assert!(pad.feed(axis(code, value)).is_empty());
        }
        assert_eq!(pad.feed(axis(code, -399)), vec![RawEvent::Up(negative)]);
    }
}

#[test]
fn stick_reversal_releases_before_pressing_and_repeated_samples_are_not_presses() {
    let mut pad = stick_pad();
    assert_eq!(pad.feed(axis(0, -1200)), vec![RawEvent::Down(Btn::Left)]);
    assert!(pad.feed(axis(0, -1600)).is_empty());
    assert_eq!(
        pad.feed(axis(0, 1200)),
        vec![RawEvent::Up(Btn::Left), RawEvent::Down(Btn::Right)]
    );
    assert!(pad.feed(axis(0, 1600)).is_empty());
}

#[test]
fn releasing_either_stick_or_dpad_keeps_the_other_held() {
    for stick_first in [false, true] {
        for release_stick_first in [false, true] {
            let mut pad = stick_pad();
            let stick = axis(0, -1800);
            let dpad = key(546, 1);
            let (first, second) = if stick_first {
                (stick, dpad)
            } else {
                (dpad, stick)
            };
            assert_eq!(pad.feed(first), vec![RawEvent::Down(Btn::Left)]);
            assert!(pad.feed(second).is_empty());
            let (first, last) = if release_stick_first {
                (axis(0, 0), key(546, 0))
            } else {
                (key(546, 0), axis(0, 0))
            };
            assert!(pad.feed(first).is_empty());
            assert_eq!(pad.feed(last), vec![RawEvent::Up(Btn::Left)]);
        }
    }
}

#[test]
fn hat_and_stick_sources_do_not_release_each_other() {
    let mut pad = stick_pad();
    assert_eq!(pad.feed(axis(0, -1800)), vec![RawEvent::Down(Btn::Left)]);
    assert!(pad.feed(axis(0x10, -1)).is_empty());
    assert!(pad.feed(axis(0, 0)).is_empty());
    assert_eq!(pad.feed(axis(0x10, 0)), vec![RawEvent::Up(Btn::Left)]);
}

#[test]
fn right_stick_and_stick_clicks_do_not_generate_game_buttons() {
    let mut pad = stick_pad();
    for code in [3, 4] {
        for value in [-1800, 1800, 0] {
            assert!(pad.feed(axis(code, value)).is_empty());
        }
    }
    for code in [317, 318] {
        assert!(pad.feed(key(code, 1)).is_empty());
        assert!(pad.feed(key(code, 0)).is_empty());
    }
}

#[test]
fn analog_mapping_is_limited_to_the_rg353v_builtin_gamepad() {
    for (profile, name) in [
        (InputProfile::H700, "retrogame_joypad"),
        (InputProfile::Rg353v, "Hynitron cst3xx Touchscreen"),
    ] {
        let mut pad = slot::input::evdev::DeviceEvents::new(profile, name);
        for code in [0, 1] {
            assert!(pad.feed(axis(code, 1800)).is_empty());
        }
    }
    let mut pad = stick_pad();
    for (code, btn) in [(305, Btn::A), (316, Btn::Menu), (116, Btn::Power)] {
        assert_eq!(pad.feed(key(code, 1)), vec![RawEvent::Down(btn)]);
        assert_eq!(pad.feed(key(code, 0)), vec![RawEvent::Up(btn)]);
    }
}

#[test]
fn left_stick_reaches_the_same_emulator_button_mask_as_dpad() {
    use slot_input::Gestures;
    use slot_retro::ButtonMask;
    let mut buttons = stick_pad();
    let mut gestures = Gestures::new();
    let mut pad = slot::input::Pad::default();
    for ev in [axis(0, 1800), axis(1, -1800)] {
        for raw in buttons.feed(ev) {
            for action in gestures.feed(raw, 100) {
                pad.apply(action);
            }
        }
    }
    assert_eq!(pad.mask().0, ButtonMask::RIGHT | ButtonMask::UP);
    for ev in [axis(0, 0), axis(1, 0)] {
        for raw in buttons.feed(ev) {
            for action in gestures.feed(raw, 110) {
                pad.apply(action);
            }
        }
    }
    assert_eq!(pad.mask().0, 0);
}

#[test]
fn rg353v_f_button_hold_reaches_eject_without_forwarding_to_game() {
    use slot_input::{Action, Gestures};
    for code in [316, 33] {
        let mut gestures = Gestures::new();
        let event = |value| {
            to_raw_with_profile(
                Ev {
                    kind: EV_KEY,
                    code,
                    value,
                },
                InputProfile::Rg353v,
            )
            .unwrap()
        };
        assert!(gestures.feed(event(1), 100).is_empty());
        assert!(gestures.tick(1099).is_empty());
        assert_eq!(gestures.tick(1100), vec![Action::Eject]);
        assert!(gestures.tick(2100).is_empty());
        assert!(gestures.feed(event(0), 2100).is_empty());
    }
}

#[test]
fn rg353v_buttons_use_mainline_codes_without_changing_h700() {
    // Independent hardware reference: Linux rk3566-anbernic-rgxx3.dtsi
    // and MyMinUI workspace/r36s/platform/platform.c (RG353V map).
    let buttons = [
        (304, Btn::B),
        (305, Btn::A),
        (307, Btn::X),
        (308, Btn::Y),
        (310, Btn::L1),
        (311, Btn::R1),
        (312, Btn::L2),
        (313, Btn::R2),
        (314, Btn::Select),
        (315, Btn::Start),
        (316, Btn::Menu),
        (544, Btn::Up),
        (545, Btn::Down),
        (546, Btn::Left),
        (547, Btn::Right),
        (114, Btn::VolDown),
        (115, Btn::VolUp),
        (116, Btn::Power),
    ];
    for (code, btn) in buttons {
        for (value, expected) in [
            (1, Some(RawEvent::Down(btn))),
            (0, Some(RawEvent::Up(btn))),
            (2, None),
        ] {
            assert_eq!(
                to_raw_with_profile(
                    Ev {
                        kind: EV_KEY,
                        code,
                        value
                    },
                    InputProfile::Rg353v
                ),
                expected,
                "code {code}, value {value}"
            );
        }
    }
    assert_eq!(
        code_to_btn_with_profile(304, InputProfile::H700),
        Some(Btn::A)
    );
    assert_eq!(
        code_to_btn_with_profile(310, InputProfile::H700),
        Some(Btn::Select)
    );
    assert_eq!(
        code_to_btn_with_profile(312, InputProfile::H700),
        Some(Btn::Menu)
    );
    assert_eq!(
        code_to_btn_with_profile(317, InputProfile::Rg353v),
        None,
        "stick clicks must not become SELECT/START"
    );
}

#[test]
fn rg353v_traces_name_the_action_that_will_actually_run() {
    let line = slot::input::trace::event_line_with_profile(
        "event4",
        10,
        Ev {
            kind: EV_KEY,
            code: 312,
            value: 1,
        },
        InputProfile::Rg353v,
    );
    assert!(line.ends_with("-> L2"), "{line}");
}

#[test]
fn the_separate_mainline_menu_node_is_discovered() {
    let tree = tempfile::tempdir().unwrap();
    let dev = tree.path().join("dev/input");
    let sys = tree.path().join("sys/class/input");
    std::fs::create_dir_all(&dev).unwrap();
    std::fs::write(dev.join("event2"), "").unwrap();
    let capabilities = sys.join("event2/device/capabilities");
    std::fs::create_dir_all(&capabilities).unwrap();
    // BTN_MODE = 316 = word four, bit 60 in a 64-bit sysfs key mask.
    std::fs::write(capabilities.join("key"), "1000000000000000 0 0 0 0\n").unwrap();
    assert_eq!(
        slot::input::evdev::pick_devices(&dev, &sys),
        vec![dev.join("event2")]
    );
}
