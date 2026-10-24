mod common;
use slot::{app::Phase, card_writes::CardWrites, persist, temp_cleanup};
use slot_input::{Action, Btn};
use slot_store::{Core, Platform, StateRing};
use std::{fs, io, time::Duration};
#[test]
fn unrelated_successes_cannot_hide_a_save_failure() {
    let writes = CardWrites::default();
    writes.wrote("cart:save", &Err::<(), _>(io::Error::from_raw_os_error(5)));
    writes.wrote("slot.state", &Ok::<(), io::Error>(()));
    assert!(writes.failing());
    writes.wrote("other-cart:save", &Ok::<(), io::Error>(()));
    assert!(writes.failing());
    writes.wrote("cart:save", &Ok::<(), io::Error>(()));
    assert!(!writes.failing());
}
#[test]
fn unreadable_sav_does_not_fall_back_to_srm_or_get_overwritten() {
    let t = common::tmp_root_with_carts(&["Alpha"]);
    let dir = t.path().join("Saves/GBA");
    fs::create_dir_all(&dir).unwrap();
    fs::create_dir(dir.join("Alpha.sav")).unwrap();
    fs::write(dir.join("Alpha.srm"), b"original").unwrap();
    assert!(persist::read_sav_checked(t.path(), Platform::Gba, "Alpha").is_err());
    assert!(persist::write_sav(t.path(), Platform::Gba, "Alpha", b"replacement").is_err());
    assert!(dir.join("Alpha.sav").is_dir());
    assert_eq!(fs::read(dir.join("Alpha.srm")).unwrap(), b"original");
    assert!(
        persist::read_sav_checked(t.path(), Platform::Gba, "Missing")
            .unwrap()
            .is_none()
    );
}
#[test]
fn unchanged_resume_keeps_the_same_file_and_unreadable_resume_is_preserved() {
    let t = common::tmp_root_with_carts(&["Alpha"]);
    let ring = StateRing::new(t.path(), Platform::Gba, Core::Mgba, "Alpha");
    ring.write_resume(b"original").unwrap();
    let path = t.path().join("States/GBA/mgba/Alpha/resume.state");
    let before = fs::metadata(&path).unwrap();
    persist::flush(
        t.path(),
        Platform::Gba,
        Core::Mgba,
        "Alpha",
        Some(b"original"),
        None,
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        assert_eq!(before.ino(), fs::metadata(&path).unwrap().ino());
    }
    fs::remove_file(&path).unwrap();
    fs::create_dir(&path).unwrap();
    assert!(persist::read_resume_checked(t.path(), Platform::Gba, Core::Mgba, "Alpha").is_err());
    assert!(persist::flush(
        t.path(),
        Platform::Gba,
        Core::Mgba,
        "Alpha",
        Some(b"new"),
        None
    )
    .is_err());
    assert!(path.is_dir());
}
#[test]
fn cleanup_leaves_live_writers_links_and_games_alone_and_is_bounded() {
    let t = tempfile::tempdir().unwrap();
    let dir = t.path().join("States/GB/mgba/Alpha");
    fs::create_dir_all(&dir).unwrap();
    let old = dir.join(".resume.state.4242.7.tmp");
    let live = dir.join(".resume.state.4243.7.tmp");
    let mine = dir.join(format!(".resume.state.{}.2.tmp", std::process::id()));
    for p in [&old, &live, &mine] {
        fs::write(p, b"bytes").unwrap();
    }
    let notes = dir.join(".notes.tmp");
    fs::write(&notes, b"user").unwrap();
    fs::create_dir_all(t.path().join("Games")).unwrap();
    let game = t.path().join("Games/.game.4242.7.tmp");
    fs::write(&game, b"user").unwrap();
    assert_eq!(
        temp_cleanup::sweep(t.path(), 0, Duration::from_secs(1), |p| p == 4243),
        0
    );
    assert!(old.exists());
    #[cfg(unix)]
    {
        use std::os::unix::fs::symlink;
        let outside = tempfile::tempdir().unwrap();
        let target = outside.path().join(".resume.4242.7.tmp");
        fs::write(&target, b"outside").unwrap();
        symlink(outside.path(), dir.join("link")).unwrap();
        assert_eq!(
            temp_cleanup::sweep(t.path(), 100, Duration::from_secs(1), |p| p == 4243),
            1
        );
        assert!(target.exists());
    }
    assert!(!old.exists());
    for p in [live, mine, notes, game] {
        assert!(p.exists());
    }
}
#[test]
fn delete_requires_confirmation_freezes_navigation_and_b_preserves_files() {
    let t = common::tmp_root_with_carts(&["Alpha"]);
    let ring = StateRing::new(t.path(), Platform::Gba, Core::Mgba, "Alpha");
    for n in 0..3 {
        ring.push(&[n; 8], b"png", &format!("2026-10-21_00-00-0{n}"))
            .unwrap();
    }
    let mut app = common::app_in_switcher(t.path(), "Alpha");
    app.apply(Action::GbaDown(Btn::Y));
    assert!(app.state_delete_prompt());
    assert_eq!(ring.list().unwrap().len(), 3);
    app.apply(Action::ShelfRight);
    app.apply(Action::GbaDown(Btn::B));
    assert!(!app.state_delete_prompt());
    assert_eq!(ring.list().unwrap().len(), 3);
    app.apply(Action::GbaDown(Btn::Y));
    assert_eq!(app.menu_legend()[1].key, "A");
    app.apply(Action::GbaDown(Btn::A));
    let list = ring.list().unwrap();
    assert_eq!(list.len(), 2);
    assert!(!list.iter().any(|e| e.stamp.ends_with("02")));
    assert!(matches!(app.phase(), Phase::Polaroids { .. }));
}
#[test]
fn manual_state_failure_stays_alarmed_after_an_unrelated_settings_write() {
    let t = common::tmp_root_with_carts(&["Alpha"]);
    fs::remove_dir_all(t.path().join("States")).unwrap();
    fs::write(t.path().join("States"), b"blocked").unwrap();
    let mut app = common::app_playing_in(t.path(), "Alpha");
    app.apply(Action::SaveState);
    app.tick_ms(2000);
    assert!(app.card_alarm());
    app.apply(Action::VolumeUp);
    app.flush_state();
    app.tick_ms(2100);
    assert!(app.card_alarm());
}
