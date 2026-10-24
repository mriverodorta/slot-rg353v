//! Player-facing feature switches, independent of installed modules.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlayerFeature {
    StateBrowser,
    ManualStates,
    Favorites,
    CoreSelection,
    FastForward,
    Rewind,
    InGameShader,
    InGamePalette,
    InGameColor,
}
impl PlayerFeature {
    pub const ALL: [Self; 9] = [
        Self::StateBrowser,
        Self::ManualStates,
        Self::Favorites,
        Self::CoreSelection,
        Self::FastForward,
        Self::Rewind,
        Self::InGameShader,
        Self::InGamePalette,
        Self::InGameColor,
    ];
    pub fn key(self) -> &'static str {
        match self {
            Self::StateBrowser => "feature_state_browser",
            Self::ManualStates => "feature_manual_states",
            Self::Favorites => "feature_favorites",
            Self::CoreSelection => "feature_core_selection",
            Self::FastForward => "feature_fast_forward",
            Self::Rewind => "feature_rewind",
            Self::InGameShader => "feature_ingame_shader",
            Self::InGamePalette => "feature_ingame_palette",
            Self::InGameColor => "feature_ingame_color",
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PlayerFeatures([bool; 9]);
impl Default for PlayerFeatures {
    fn default() -> Self {
        Self([true; 9])
    }
}
impl PlayerFeatures {
    pub fn enabled(self, feature: PlayerFeature) -> bool {
        self.0[feature as usize]
    }
    pub fn toggle(&mut self, feature: PlayerFeature) {
        self.0[feature as usize] = !self.enabled(feature);
    }
    pub fn parse_line(&mut self, key: &str, value: &str) {
        if let Some(feature) = PlayerFeature::ALL.into_iter().find(|f| f.key() == key) {
            if let Some(on) = match value {
                "0" => Some(false),
                "1" => Some(true),
                _ => None,
            } {
                self.0[feature as usize] = on;
            }
        }
    }
}
