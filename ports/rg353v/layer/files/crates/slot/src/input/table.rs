use slot_input::{anywhere, Action, Contexts, Entry};
use slot_store::{Binding, CarouselAction, CarouselKeys, Controls, Modifier, ShortcutKeys};
use slot_ui::QuickRow;

use super::bind::{chord, shortcut_action};

#[derive(Copy, Clone, Debug)]
struct Row {
    row: QuickRow,
    binding: Binding,
    action: Option<Action>,
    contexts: Contexts,
}

pub struct Table {
    rows: Vec<Row>,
}

impl Table {
    pub fn new(
        controls: &Controls,
        shortcuts: &ShortcutKeys,
        carousel: &CarouselKeys,
        turbo: bool,
    ) -> Table {
        let rows = QuickRow::ALL
            .into_iter()
            .filter_map(|row| {
                if let Some(g) = row.game_button() {
                    let turbo_row = matches!(row, QuickRow::GameTurboA | QuickRow::GameTurboB);
                    if turbo_row && !turbo {
                        return None;
                    }
                    return controls.game(g).map(|binding| Row {
                        row,
                        binding,
                        action: None,
                        contexts: Contexts::GAME,
                    });
                }
                if let Some(s) = row.shortcut() {
                    let action = shortcut_action(s);
                    return shortcuts.get(s).map(|binding| Row {
                        row,
                        binding,
                        action: Some(action),
                        contexts: match (anywhere(action), binding.modifier) {
                            (false, _) => Contexts::GAME,
                            (true, None) => Contexts::GAME.with(Contexts::SHELF),
                            (true, Some(_)) => Contexts::ALL,
                        },
                    });
                }
                let a = row.carousel_action()?;
                carousel.get(a).map(|binding| Row {
                    row,
                    binding,
                    action: Some(shelf_action(a)),
                    contexts: Contexts::SHELF,
                })
            })
            .collect();
        Table { rows }
    }

    pub fn retain_visible(&mut self, visible: impl Fn(QuickRow) -> bool) {
        self.rows.retain(|r| visible(r.row));
    }

    pub fn entries(&self) -> Vec<Entry> {
        self.rows
            .iter()
            .filter_map(|r| {
                r.action.map(|action| Entry {
                    chord: chord(r.binding),
                    action,
                    contexts: r.contexts,
                })
            })
            .collect()
    }

    pub fn clash(&self, row: QuickRow) -> Option<QuickRow> {
        let mine = self.rows.iter().find(|r| r.row == row)?;
        let console = |r: &Row| r.action.is_none();
        self.rows
            .iter()
            .filter(|r| r.row != row && r.contexts.meets(mine.contexts))
            .find(|r| {
                r.binding == mine.binding
                    || (!console(mine)
                        && !console(r)
                        && (overlaps(mine.binding, r.binding) || overlaps(r.binding, mine.binding)))
            })
            .map(|r| r.row)
    }
}

fn shelf_action(a: CarouselAction) -> Action {
    match a {
        CarouselAction::PreviousShelf => Action::PreviousShelf,
        CarouselAction::NextShelf => Action::NextShelf,
        CarouselAction::Favorite => Action::Favorite,
    }
}

fn overlaps(pair: Binding, single: Binding) -> bool {
    let Some(Modifier::Button(first)) = pair.modifier else {
        return false;
    };
    single.modifier.is_none()
        && (single.button == first || (!first.leads() && single.button == pair.button))
}

#[cfg(test)]
mod screenshot_tests {
    use super::*;
    use slot_input::{Btn, Context, Gestures, RawEvent};
    #[test]
    fn select_start_captures_once_without_sending_start_or_select_to_the_game() {
        let table = Table::new(
            &Controls::default(),
            &ShortcutKeys::default(),
            &CarouselKeys::default(),
            false,
        );
        let mut keys = Gestures::new();
        keys.set_entries(table.entries());
        keys.set_context(Context::Game);
        let mut result = keys.feed(RawEvent::Down(Btn::Select), 0);
        result.extend(keys.feed(RawEvent::Down(Btn::Start), 30));
        result.extend(keys.feed(RawEvent::Up(Btn::Start), 50));
        result.extend(keys.feed(RawEvent::Up(Btn::Select), 60));
        assert_eq!(
            result.iter().filter(|x| **x == Action::Screenshot).count(),
            1
        );
        assert!(!result.contains(&Action::GbaDown(Btn::Select)));
        assert!(!result.contains(&Action::GbaDown(Btn::Start)));
    }
}

#[cfg(test)]
mod conflict_regressions {
    use super::*;
    use slot_store::Device;
    #[test]
    fn modifier_chords_do_not_warn_about_consumed_second_button() {
        let pair = |first, button| Binding {
            modifier: Some(Modifier::Button(first)),
            button,
        };
        assert!(!overlaps(
            pair(Device::Start, Device::X),
            Binding::plain(Device::X).unwrap()
        ));
        assert!(overlaps(
            pair(Device::Start, Device::X),
            Binding::plain(Device::Start).unwrap()
        ));
        assert!(overlaps(
            pair(Device::L1, Device::R1),
            Binding::plain(Device::R1).unwrap()
        ));
        assert!(overlaps(
            pair(Device::L1, Device::R1),
            Binding::plain(Device::L1).unwrap()
        ));
    }
}
