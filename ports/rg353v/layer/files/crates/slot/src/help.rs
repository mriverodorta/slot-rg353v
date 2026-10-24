//! Local controls reference. No jobs, disk reads or services are started by Help.
use slot_input::Btn;
use std::ops::Range;
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Entry {
    pub keys: &'static [&'static str],
    pub label: &'static str,
}
macro_rules! entry { ($label:literal; $($key:literal),* ) => { Entry { keys: &[$($key),*], label: $label } }; }
const TOPICS: &[Entry] = &[
    entry!("Navigation";),
    entry!("Games & saves";),
    entry!("Picture & filters";),
    entry!("Volume & display";),
    entry!("Power & network";),
    entry!("Keyboard";),
];
const GUIDES: &[&[Entry]] = &[
    &[
        entry!("Move through games / menus"; "D-PAD"),
        entry!("Open game / confirm"; "A"),
        entry!("Go back / cancel"; "B"),
        entry!("Previous system"; "L1"),
        entry!("Next system"; "R1"),
        entry!("On shelf: open Settings"; "F"),
        entry!("Mark / unmark favorite (default)"; "Y"),
        entry!("Controls: customize buttons & shortcuts";),
        entry!("Also moves in games"; "STICK"),
    ],
    &[
        entry!("Hold 1 second: save & eject"; "F"),
        entry!("Open: resume saved session"; "A"),
        entry!("Hold while opening: fresh start"; "A"),
        entry!("Pause / game settings"; "F"),
        entry!("Link menu (default)"; "SELECT", "F"),
        entry!("Save state"; "SELECT", "R1"),
        entry!("Screenshot (default)"; "SELECT", "START"),
        entry!("Load state"; "SELECT", "L1"),
        entry!("Double tap: state browser"; "F"),
        entry!("Hold: rewind (when enabled)"; "L2"),
        entry!("Hold: fast-forward"; "R2"),
        entry!("Double tap: latch fast-forward"; "R2"),
    ],
    &[
        entry!("Next shader (default)"; "SELECT", "A"),
        entry!("Previous shader (default)"; "SELECT", "B"),
        entry!("Toggle color correction"; "SELECT", "Y"),
        entry!("Toggle frame counter (Overlay On)"; "SELECT", "X"),
        entry!("Previous GB palette"; "SELECT", "L2"),
        entry!("Next GB palette"; "SELECT", "R2"),
        entry!("GB/GBC fill height (Overlay Off)"; "L1"),
        entry!("GB/GBC integer (Overlay Off)"; "R1"),
    ],
    &[
        entry!("Adjust volume"; "VOL +/-"),
        entry!("Together: mute / unmute"; "VOL +", "VOL -"),
        entry!("Raise brightness"; "SELECT", "UP"),
        entry!("Lower brightness"; "SELECT", "DOWN"),
        entry!("Less blue-light filter"; "SELECT", "LEFT"),
        entry!("More blue-light filter"; "SELECT", "RIGHT"),
        entry!("Plug in: automatic audio routing"; "JACK"),
    ],
    &[
        entry!("Tap: sleep / wake to shelf"; "POWER"),
        entry!("Hold 1 second: power menu"; "POWER"),
        entry!("Cancel power menu"; "B"),
        entry!("Connections: network tools";),
        entry!("Normal boot starts offline";),
        entry!("Developer Mode keeps tools on";),
        entry!("USB: eject on computer first";),
    ],
    &[
        entry!("Choose a key"; "D-PAD"),
        entry!("Add character"; "A"),
        entry!("Delete character"; "Y"),
        entry!("Cancel editing"; "B"),
        entry!("Previous keyboard section"; "L1"),
        entry!("Next keyboard section"; "R1"),
        entry!("Show / hide password"; "X"),
    ],
];
pub struct Menu {
    page: Option<usize>,
    selected: usize,
    first: usize,
    topic: usize,
    guides: Vec<Vec<Entry>>,
    topics: Vec<Entry>,
    topic_ids: Vec<usize>,
}
impl Menu {
    pub fn open() -> Self {
        Self::with_features(crate::features::Features::default())
    }
    pub fn with_features(features: crate::features::Features) -> Self {
        Self::with_policy(features, slot_store::PlayerFeatures::default())
    }
    pub fn with_policy(
        features: crate::features::Features,
        policy: slot_store::PlayerFeatures,
    ) -> Self {
        let guides = GUIDES
            .iter()
            .enumerate()
            .map(|(topic, entries)| {
                entries
                    .iter()
                    .copied()
                    .filter(|entry| {
                        let label = entry.label;
                        use slot_store::PlayerFeature::*;
                        let feature = if label.contains("favorite") {
                            Some(Favorites)
                        } else if label.contains("state browser") {
                            Some(StateBrowser)
                        } else if label == "Save state" || label == "Load state" {
                            Some(ManualStates)
                        } else if label.contains("fast-forward") {
                            Some(FastForward)
                        } else if label.contains("rewind") {
                            Some(Rewind)
                        } else if label.contains("shader") {
                            Some(InGameShader)
                        } else if label.contains("palette") {
                            Some(InGamePalette)
                        } else if label.contains("color correction") {
                            Some(InGameColor)
                        } else {
                            None
                        };
                        if feature.is_some_and(|f| !policy.enabled(f)) {
                            return false;
                        }
                        if label.contains("Screenshot") && !features.has("screenshots") {
                            return false;
                        }
                        !(topic == 2
                            && ((!features.has("filters")
                                && (label.contains("shader")
                                    || label.contains("correction")
                                    || label.contains("palette")))
                                || (!features.has("frame-counter") && label.contains("counter"))
                                || (!features.has("overlays") && label.contains("Overlay"))))
                            && (!label.contains("rewind") || features.has("rewind"))
                            && (!label.contains("Connections:")
                                || ["wifi", "ssh", "sharing", "usb-network"]
                                    .iter()
                                    .any(|s| features.has(s)))
                            && (!label.contains("Developer Mode") || features.has("developer"))
                            && (!label.contains("USB:") || features.has("usb-storage"))
                    })
                    .collect()
            })
            .collect();
        let topic_ids: Vec<_> = (0..TOPICS.len())
            .filter(|i| *i != 5 || features.has("wifi") || features.has("ssh"))
            .collect();
        let topics = topic_ids
            .iter()
            .map(|i| {
                let mut topic = TOPICS[*i];
                if *i == 2 && !features.has("filters") {
                    topic.label = "Picture";
                }
                if *i == 4
                    && !["wifi", "usb-network", "sharing", "ssh"]
                        .iter()
                        .any(|f| features.has(f))
                {
                    topic.label = "Power";
                }
                topic
            })
            .collect();
        Self {
            topics,
            topic_ids,
            guides,
            page: None,
            selected: 0,
            first: 0,
            topic: 0,
        }
    }
    pub fn title(&self) -> &'static str {
        self.page
            .map(|_| self.topics[self.topic].label)
            .unwrap_or("Help")
    }
    pub fn entries(&self) -> &[Entry] {
        self.page
            .map(|i| self.guides[i].as_slice())
            .unwrap_or(&self.topics)
    }
    pub fn selected(&self) -> usize {
        self.selected
    }
    pub fn window(&self) -> Range<usize> {
        slot_ui::menu_window(self.entries().len(), self.selected, 8, self.first)
    }
    pub fn button(&mut self, button: Btn) -> bool {
        let count = self.entries().len();
        match button {
            Btn::Up => self.selected = (self.selected + count - 1) % count,
            Btn::Down => self.selected = (self.selected + 1) % count,
            Btn::A if self.page.is_none() => {
                self.topic = self.selected;
                self.page = Some(self.topic_ids[self.topic]);
                self.selected = 0;
                self.first = 0;
            }
            Btn::B => {
                if self.page.is_none() {
                    return true;
                }
                self.page = None;
                self.selected = self.topic;
                self.first = 0;
            }
            Btn::L1 | Btn::R1 if self.page.is_some() => {
                self.topic = (self.topic
                    + if button == Btn::R1 {
                        1
                    } else {
                        self.topics.len() - 1
                    })
                    % self.topics.len();
                self.page = Some(self.topic_ids[self.topic]);
                self.selected = 0;
                self.first = 0;
            }
            _ => {}
        }
        self.first = self.window().start;
        false
    }
    pub fn legend(&self) -> Vec<slot_ui::Hint> {
        if self.page.is_none() {
            slot_ui::hint_row(&[("B", "Back"), ("A", "Open")])
        } else {
            slot_ui::hint_row(&[("B", "Back"), ("D-PAD", "Scroll"), ("L/R", "Section")])
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn screenshot_help_follows_capture_capability_and_not_gallery() {
        for (capture, gallery) in [(false, false), (true, false), (false, true), (true, true)] {
            let text = format!(
                "slot-features-v1\nemulator-mgba\n{}{}",
                if capture { "screenshots\n" } else { "" },
                if gallery { "gallery\n" } else { "" }
            );
            let menu = Menu::with_features(crate::features::Features::parse(&text));
            assert_eq!(
                menu.guides
                    .iter()
                    .flatten()
                    .any(|entry| entry.label.contains("Screenshot")),
                capture
            );
        }
    }
    #[test]
    fn guide_scrolls_and_back_restores_topic() {
        let mut menu = Menu::open();
        menu.button(Btn::Down);
        menu.button(Btn::A);
        assert_eq!(menu.title(), "Games & saves");
        for _ in 0..menu.entries().len() - 1 {
            menu.button(Btn::Down);
        }
        assert_eq!(menu.window().end, menu.entries().len());
        menu.button(Btn::Down);
        assert_eq!(menu.window(), 0..8);
        menu.button(Btn::B);
        assert_eq!(menu.title(), "Help");
        assert_eq!(menu.selected(), 1);
        assert!(menu.button(Btn::B));
    }
    #[test]
    fn sections_cycle_and_reset_scroll() {
        let mut menu = Menu::open();
        menu.button(Btn::A);
        menu.button(Btn::L1);
        assert_eq!(menu.title(), "Keyboard");
        menu.button(Btn::R1);
        assert_eq!(menu.title(), "Navigation");
        assert_eq!(menu.selected(), 0);
    }
}
