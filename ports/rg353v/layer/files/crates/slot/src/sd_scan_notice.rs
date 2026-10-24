//! Temporary shelf-name feedback; never persisted in user settings.
use slot_input::Millis;

pub const TEXT: &str = "Scanning SD card for games...";
const IN_MS: Millis = 200;
const MIN_MS: Millis = 1200;
const OUT_MS: Millis = 800;

#[derive(Default)]
pub struct Notice {
    started: Option<Millis>,
    finished: Option<Millis>,
}

impl Notice {
    pub fn start(&mut self, now: Millis) {
        self.started = Some(now);
        self.finished = None;
    }

    pub fn finish(&mut self, now: Millis) {
        if self.finished.is_none() {
            self.finished = self
                .started
                .map(|start| now.max(start.saturating_add(MIN_MS)));
        }
    }

    pub fn alpha(&self, now: Millis) -> Option<f32> {
        let start = self.started?;
        let entrance = (now.saturating_sub(start) as f32 / IN_MS as f32).min(1.0);
        let exit = self.finished.map_or(1.0, |end| {
            1.0 - (now.saturating_sub(end) as f32 / OUT_MS as f32).min(1.0)
        });
        Some(slot_ui::ease(entrance.min(exit)))
    }

    pub fn expire(&mut self, now: Millis) -> bool {
        if self
            .finished
            .is_some_and(|end| now >= end.saturating_add(OUT_MS))
        {
            self.started = None;
            self.finished = None;
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn idle_boot_has_no_notice_and_long_scans_stay_visible() {
        let mut notice = Notice::default();
        assert_eq!(notice.alpha(1000), None);
        notice.start(1000);
        assert_eq!(notice.alpha(1000), Some(0.0));
        assert_eq!(notice.alpha(1200), Some(1.0));
        assert_eq!(notice.alpha(90_000), Some(1.0));
        assert!(!notice.expire(90_000));
        notice.finish(90_000);
        assert!(notice.alpha(90_400).is_some_and(|a| a > 0.0 && a < 1.0));
        assert!(notice.expire(90_800));
        assert_eq!(notice.alpha(90_800), None);
    }

    #[test]
    fn fast_scans_are_readable_and_repeated_completion_does_not_extend_them() {
        let mut notice = Notice::default();
        notice.start(0);
        notice.finish(10);
        notice.finish(5000);
        assert_eq!(notice.alpha(1200), Some(1.0));
        assert!(!notice.expire(1999));
        assert!(notice.expire(2000));
    }

    #[test]
    fn reinsertion_restarts_a_fading_notice_without_restoring_stale_text() {
        let mut notice = Notice::default();
        notice.start(0);
        notice.finish(20);
        notice.start(1600);
        assert!(!notice.expire(2000));
        assert_eq!(notice.alpha(2000), Some(1.0));
        notice.finish(2100);
        assert!(notice.expire(3600));
    }
}
