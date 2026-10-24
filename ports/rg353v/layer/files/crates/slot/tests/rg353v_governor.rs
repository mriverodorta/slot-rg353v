#![cfg(feature = "rg353v")]
use slot::rg353v_governor::apply_at;
#[test]
fn updates_only_ondemand_cadence_and_is_idempotent() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join("policy0")).unwrap();
    std::fs::create_dir(root.path().join("ondemand")).unwrap();
    for (path, value) in [
        ("policy0/scaling_governor", "ondemand"),
        ("policy0/scaling_min_freq", "408000"),
        ("policy0/scaling_max_freq", "1800000"),
        ("ondemand/up_threshold", "95"),
        ("ondemand/sampling_rate", "8000"),
    ] {
        std::fs::write(root.path().join(path), value).unwrap();
    }
    assert!(apply_at(root.path()).unwrap());
    assert!(!apply_at(root.path()).unwrap());
    for (path, value) in [
        ("ondemand/sampling_rate", "20000"),
        ("policy0/scaling_governor", "ondemand"),
        ("policy0/scaling_min_freq", "408000"),
        ("policy0/scaling_max_freq", "1800000"),
        ("ondemand/up_threshold", "95"),
    ] {
        assert_eq!(
            std::fs::read_to_string(root.path().join(path)).unwrap(),
            value
        );
    }
    std::fs::write(root.path().join("policy0/scaling_governor"), "performance").unwrap();
    std::fs::write(root.path().join("ondemand/sampling_rate"), "8000").unwrap();
    assert!(!apply_at(root.path()).unwrap());
    assert_eq!(
        std::fs::read_to_string(root.path().join("ondemand/sampling_rate")).unwrap(),
        "8000"
    );
}

#[test]
fn switching_governors_preserves_frequency_limits_and_restores_20ms() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join("policy0")).unwrap();
    std::fs::create_dir(root.path().join("ondemand")).unwrap();
    for (path, value) in [
        (
            "policy0/scaling_available_governors",
            "ondemand schedutil performance",
        ),
        ("policy0/scaling_governor", "performance"),
        ("policy0/scaling_min_freq", "408000"),
        ("policy0/scaling_max_freq", "1800000"),
        ("ondemand/sampling_rate", "8000"),
    ] {
        std::fs::write(root.path().join(path), value).unwrap();
    }
    assert!(slot::rg353v_governor::select_at(root.path(), true).unwrap());
    assert_eq!(
        std::fs::read_to_string(root.path().join("policy0/scaling_governor")).unwrap(),
        "schedutil\n"
    );
    assert_eq!(
        std::fs::read_to_string(root.path().join("ondemand/sampling_rate")).unwrap(),
        "8000"
    );
    assert!(!slot::rg353v_governor::select_at(root.path(), true).unwrap());
    assert!(slot::rg353v_governor::select_at(root.path(), false).unwrap());
    assert_eq!(
        std::fs::read_to_string(root.path().join("ondemand/sampling_rate")).unwrap(),
        "20000"
    );
    assert!(!slot::rg353v_governor::select_at(root.path(), false).unwrap());
    assert_eq!(
        std::fs::read_to_string(root.path().join("policy0/scaling_min_freq")).unwrap(),
        "408000"
    );
    assert_eq!(
        std::fs::read_to_string(root.path().join("policy0/scaling_max_freq")).unwrap(),
        "1800000"
    );
    std::fs::write(
        root.path().join("policy0/scaling_available_governors"),
        "ondemand",
    )
    .unwrap();
    assert!(slot::rg353v_governor::select_at(root.path(), true).is_err());
    assert_eq!(
        std::fs::read_to_string(root.path().join("policy0/scaling_governor")).unwrap(),
        "ondemand\n"
    );
}

#[test]
fn a_pending_boot_handoff_cannot_override_the_new_user_choice() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join("policy0")).unwrap();
    std::fs::create_dir(root.path().join("ondemand")).unwrap();
    std::fs::write(
        root.path().join("policy0/scaling_available_governors"),
        "ondemand schedutil performance",
    )
    .unwrap();
    let governor = root.path().join("policy0/scaling_governor");
    std::fs::write(&governor, "performance").unwrap();
    std::fs::write(root.path().join("ondemand/sampling_rate"), "8000").unwrap();
    let pending = root.path().join("pending");
    std::fs::write(&pending, "ondemand").unwrap();
    assert_eq!(
        slot::rg353v_governor::select_after_boost_at(root.path(), &pending, true).unwrap(),
        None
    );
    assert_eq!(std::fs::read_to_string(&governor).unwrap(), "performance");
    // The old release finishes first; the new preference is applied afterward.
    std::fs::write(&governor, "ondemand").unwrap();
    std::fs::remove_file(&pending).unwrap();
    assert_eq!(
        slot::rg353v_governor::select_after_boost_at(root.path(), &pending, true).unwrap(),
        Some(true)
    );
    assert_eq!(std::fs::read_to_string(&governor).unwrap(), "schedutil\n");
}
