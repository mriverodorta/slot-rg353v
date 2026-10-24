//! RG353V suspend adapter. Slot owns pause, saves, backlight and wake input;
//! the generic ROCKNIX system-sleep hook would restart its competing input reader.
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

pub struct Sleeper {
    enabled: bool,
    ready_at: Instant,
}

impl Sleeper {
    pub fn from_env() -> Self {
        Self {
            enabled: std::env::var("SLOT_RG353V_SLEEP").as_deref() == Ok("deep"),
            ready_at: Instant::now(),
        }
    }

    // Recovery may happen after Slot starts, so inspect the boot-local marker
    // on every entry, rather than caching its absence during construction.
    fn may_suspend(&mut self, now: Instant, runtime: &Path) -> bool {
        if !self.enabled {
            return false;
        }
        if runtime.join("slot-wifi-probe-recovery.attempt").exists() {
            eprintln!("slot: Wi-Fi controller recovered this boot; using screen-off doze until a clean boot");
            self.enabled = false;
            return false;
        }
        now >= self.ready_at
    }

    pub fn sleep(&mut self, remaining: Option<Duration>) -> Option<Duration> {
        if !self.may_suspend(Instant::now(), Path::new("/run"))
            || remaining.is_some_and(|v| v < Duration::from_millis(100))
        {
            return None;
        }
        match suspend_at(Path::new("/sys"), remaining) {
            Ok(elapsed) if elapsed >= Duration::from_millis(250) => {
                // SDIO/Bluetooth resume work continues after userspace thaws.
                self.ready_at = Instant::now() + Duration::from_secs(5);
                eprintln!("slot: suspended for {:.3}s", elapsed.as_secs_f64());
                Some(elapsed)
            }
            result => {
                eprintln!("slot: suspend unavailable ({result:?}); using screen-off doze");
                self.enabled = false;
                result.ok()
            }
        }
    }
}

struct Alarm(PathBuf);

impl Drop for Alarm {
    fn drop(&mut self) {
        if let Err(e) = fs::write(&self.0, "0") {
            eprintln!("slot: clear sleep alarm: {e}");
        }
    }
}

fn suspend_at(sys: &Path, remaining: Option<Duration>) -> io::Result<Duration> {
    if !fs::read_to_string(sys.join("power/mem_sleep"))?.contains("[deep]") {
        return Err(io::Error::other("deep suspend is not selected"));
    }
    // Read before preparing; a new wake event makes the later write fail and
    // returns control to input polling instead of losing a rapid wake press.
    let count = fs::read_to_string(sys.join("power/wakeup_count"))?;
    let alarm_path = sys.join("class/rtc/rtc0/wakealarm");
    if !fs::read_to_string(&alarm_path)?.trim().is_empty() {
        return Err(io::Error::other("RTC alarm already reserved"));
    }
    let timeout = remaining
        .unwrap_or(Duration::from_secs(300))
        .min(Duration::from_secs(300));
    if fs::read_to_string(sys.join("class/rtc/rtc0/device/power/wakeup"))?.trim() != "enabled" {
        return Err(io::Error::other("RTC wake is not enabled"));
    }
    let seconds = timeout
        .as_secs()
        .saturating_add(u64::from(timeout.subsec_nanos() > 0))
        .max(1);
    let _alarm = Alarm(alarm_path.clone());
    fs::write(&alarm_path, format!("+{seconds}"))?;
    // The app has already flushed its writers and paused the emulator.
    unsafe { libc::sync() };
    fs::write(sys.join("power/wakeup_count"), count.trim())?;
    let before = clocks()?;
    fs::write(sys.join("power/state"), "mem")?;
    let after = clocks()?;
    Ok(after
        .0
        .saturating_sub(before.0)
        .saturating_sub(after.1.saturating_sub(before.1)))
}

fn clocks() -> io::Result<(Duration, Duration)> {
    fn read(id: libc::clockid_t) -> io::Result<Duration> {
        let mut value = libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };
        if unsafe { libc::clock_gettime(id, &mut value) } != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Duration::new(value.tv_sec as u64, value.tv_nsec as u32))
    }
    Ok((read(libc::CLOCK_BOOTTIME)?, read(libc::CLOCK_MONOTONIC)?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clean_boot_keeps_deep_sleep_and_its_resume_settling_interval() {
        let runtime = tempfile::tempdir().unwrap();
        let now = Instant::now();
        let mut sleeper = Sleeper {
            enabled: true,
            ready_at: now + Duration::from_secs(5),
        };
        assert!(!sleeper.may_suspend(now, runtime.path()));
        assert!(sleeper.may_suspend(now + Duration::from_secs(5), runtime.path()));
    }

    #[test]
    fn a_controller_recovery_after_frontend_start_blocks_deep_sleep() {
        let runtime = tempfile::tempdir().unwrap();
        let now = Instant::now();
        let mut sleeper = Sleeper {
            enabled: true,
            ready_at: now,
        };
        assert!(sleeper.may_suspend(now, runtime.path()));
        fs::write(
            runtime.path().join("slot-wifi-probe-recovery.attempt"),
            "fe000000.mmc\n",
        )
        .unwrap();
        assert!(!sleeper.may_suspend(now, runtime.path()));
        // A retry in this process must remain in the responsive doze fallback.
        fs::remove_file(runtime.path().join("slot-wifi-probe-recovery.attempt")).unwrap();
        assert!(!sleeper.may_suspend(now + Duration::from_secs(10), runtime.path()));
        let mut clean = Sleeper {
            enabled: true,
            ready_at: now,
        };
        assert!(clean.may_suspend(now, runtime.path()));
    }

    #[test]
    fn a_recovery_marker_blocks_the_first_sleep_even_during_cooldown() {
        let runtime = tempfile::tempdir().unwrap();
        let now = Instant::now();
        fs::write(
            runtime.path().join("slot-wifi-probe-recovery.attempt"),
            "fe000000.mmc\n",
        )
        .unwrap();
        let mut sleeper = Sleeper {
            enabled: true,
            ready_at: now + Duration::from_secs(5),
        };
        assert!(!sleeper.may_suspend(now, runtime.path()));
        assert!(!sleeper.enabled);
    }

    #[test]
    fn unrelated_runtime_files_do_not_disable_deep_sleep() {
        let runtime = tempfile::tempdir().unwrap();
        let now = Instant::now();
        fs::write(runtime.path().join("slot-wifi-probe-recovery.lock"), "").unwrap();
        let mut sleeper = Sleeper {
            enabled: true,
            ready_at: now,
        };
        assert!(sleeper.may_suspend(now, runtime.path()));
        sleeper.enabled = false;
        assert!(!sleeper.may_suspend(now, runtime.path()));
    }

    fn sys() -> tempfile::TempDir {
        let d = tempfile::tempdir().unwrap();
        for path in ["power", "class/rtc/rtc0/device/power"] {
            fs::create_dir_all(d.path().join(path)).unwrap();
        }
        for (path, value) in [
            ("power/mem_sleep", "s2idle [deep]"),
            ("power/wakeup_count", "4"),
            ("class/rtc/rtc0/wakealarm", ""),
            ("class/rtc/rtc0/device/power/wakeup", "enabled"),
        ] {
            fs::write(d.path().join(path), value).unwrap();
        }
        d
    }

    #[test]
    fn reserved_alarm_is_preserved_and_failed_suspend_clears_our_alarm() {
        let d = sys();
        let alarm = d.path().join("class/rtc/rtc0/wakealarm");
        fs::write(&alarm, "12345").unwrap();
        assert!(suspend_at(d.path(), Some(Duration::from_secs(180))).is_err());
        assert_eq!(fs::read_to_string(&alarm).unwrap(), "12345");
        fs::write(&alarm, "").unwrap();
        fs::create_dir(d.path().join("power/state")).unwrap();
        assert!(suspend_at(d.path(), Some(Duration::from_secs(180))).is_err());
        assert_eq!(fs::read_to_string(&alarm).unwrap(), "0");
    }

    #[test]
    fn wrong_suspend_mode_does_not_touch_alarm_or_state() {
        let d = sys();
        fs::write(d.path().join("power/mem_sleep"), "[s2idle] deep").unwrap();
        assert!(suspend_at(d.path(), None).is_err());
        assert_eq!(
            fs::read_to_string(d.path().join("class/rtc/rtc0/wakealarm")).unwrap(),
            ""
        );
        assert!(!d.path().join("power/state").exists());
    }
}
