//! Installed capabilities, separate from session On/Off settings. Read only on
//! starting the app and opening Settings; never in the render loop.
use slot_store::{Core, Platform};
use slot_ui::QuickRow;
use std::path::Path;
#[derive(Clone, Debug)]
pub struct Features {
    names: Vec<String>,
}
pub const ALL: &[&str] = &[
    "emulator-mgba",
    "emulator-gpsp",
    "wifi",
    "usb-storage",
    "usb-network",
    "sharing",
    "ssh",
    "network-time",
    "updates",
    "diagnostics",
    "storage-tools",
    "profilers",
    "external-sd",
    "enhanced-audio",
    "schedutil-governor",
    "filters",
    "overlays",
    "frame-counter",
    "screenshots",
    "gallery",
    "rewind",
    "runahead",
    "developer",
];
impl Default for Features {
    fn default() -> Self {
        Self {
            names: ALL.iter().map(|s| s.to_string()).collect(),
        }
    }
}
impl Features {
    pub fn parse(text: &str) -> Self {
        let mut lines = text
            .lines()
            .map(str::trim)
            .filter(|s| !s.is_empty() && !s.starts_with('#'));
        if lines.next() != Some("slot-features-v1") {
            return Self { names: Vec::new() };
        }
        let mut names: Vec<String> = lines
            .filter(|s| ALL.contains(s))
            .map(str::to_string)
            .collect();
        // v1 manifests written before emulator modules imply the original pair.
        // New installers always write at least one explicit emulator capability.
        if !names.iter().any(|s| s.starts_with("emulator-")) {
            names.extend(["emulator-mgba".into(), "emulator-gpsp".into()]);
        }
        Self { names }
    }

    pub fn load_from(package: &Path, selected: &Path) -> Self {
        let read = |p: &Path| match std::fs::read_to_string(p) {
            Ok(s) => Self::parse(&s),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Self::default(),
            Err(_) => Self { names: Vec::new() },
        };
        let mut installed = read(package);
        let wanted = read(selected);
        installed.names.retain(|s| wanted.has(s));
        installed
    }
    pub fn load() -> Self {
        Self::load_from(
            Path::new("/usr/share/slot/features-v1"),
            Path::new("/storage/.config/slot/features-v1"),
        )
    }
    pub fn has(&self, name: &str) -> bool {
        self.names.iter().any(|s| s == name)
    }
    pub fn core_installed(&self, core: Core) -> bool {
        self.has(match core {
            Core::Mgba => "emulator-mgba",
            Core::Gpsp => "emulator-gpsp",
        })
    }
    pub fn core_count(&self, platform: Platform) -> usize {
        Core::ALL
            .into_iter()
            .filter(|c| self.core_installed(*c) && c.runs(platform))
            .count()
    }
    pub fn supports(&self, platform: Platform) -> bool {
        self.core_count(platform) > 0
    }
    pub fn resolve_core(&self, platform: Platform, preferred: Core) -> Option<Core> {
        if self.core_installed(preferred) && preferred.runs(platform) {
            return Some(preferred);
        }
        Core::ALL
            .into_iter()
            .find(|c| self.core_installed(*c) && c.runs(platform))
    }
    pub fn visible(&self, row: QuickRow) -> bool {
        if row == QuickRow::GbPalettes {
            return false;
        }
        use QuickRow::*;
        if matches!(
            row,
            GbShader | GbPalettes | ScPaletteBack | ScPaletteNext | RunAhead
        ) && !self.core_installed(Core::Mgba)
        {
            return false;
        }
        if matches!(
            row,
            ScreenGb | GbShader | GbColourCorrection | GbBlending | GbPalettes | Palette
        ) && !self.supports(Platform::Gb)
        {
            return false;
        }
        if matches!(
            row,
            ScreenGbc | GbcShader | GbcColourCorrection | GbcBlending
        ) && !self.supports(Platform::Gbc)
        {
            return false;
        }
        if matches!(
            row,
            ScreenGba | GbaShader | GbaColourCorrection | GbaBlending
        ) && !self.supports(Platform::Gba)
        {
            return false;
        }
        let feature = match row {
            ScColour | ScPaletteBack | ScPaletteNext | ScShaderNext | ScShaderBack => {
                Some("filters")
            }
            FrameBlending | GbaBlending | GbBlending | GbcBlending => Some("filters"),
            ScFps => Some("frame-counter"),
            Gallery => Some("gallery"),
            Screenshots | ScreenshotShaders | ScreenshotFilters | ScreenshotOverlay
            | ScScreenshot => Some("screenshots"),
            ScRewind => Some("rewind"),
            Network => Some("wifi"),
            UsbStorage => Some("usb-storage"),
            UsbNetwork => Some("usb-network"),
            Sharing => Some("sharing"),
            Ssh => Some("ssh"),
            NetworkTime => Some("network-time"),
            Updates => Some("updates"),
            Diagnostics => Some("diagnostics"),
            StorageTools => return self.has("storage-tools") || self.has("external-sd"),
            Developer => Some("developer"),
            Filters | ScreenGba | ScreenGbc | ScreenGb | GbaShader | GbShader | GbcShader
            | GbaColourCorrection | GbColourCorrection | GbcColourCorrection | ColourCorrection
            | GbPalettes | Shader | Palette => Some("filters"),
            Overlays | GameBorder | OverlayStyle => Some("overlays"),
            FeatureInGameShader | FeatureInGamePalette | FeatureInGameColor => Some("filters"),
            EnhancedAudio => Some("enhanced-audio"),
            SchedutilGovernor => Some("schedutil-governor"),
            FrameCounter => Some("frame-counter"),
            Rewind | FeatureRewind => Some("rewind"),
            RunAhead => Some("runahead"),
            _ => None,
        };
        if feature.is_some_and(|s| !self.has(s)) {
            return false;
        }
        if row == NetworkTime && !self.has("wifi") && !self.has("usb-network") {
            return false;
        }
        if row == Developer && !self.has("wifi") && !self.has("usb-network") {
            return false;
        }
        row.children()
            .is_none_or(|children| children.iter().any(|r| self.visible(*r)))
    }
    pub fn rows(&self, row: QuickRow) -> Vec<QuickRow> {
        row.page()
            .iter()
            .copied()
            .filter(|r| self.visible(*r))
            .collect()
    }
    pub fn child(&self, row: QuickRow) -> Option<QuickRow> {
        row.children()?.iter().copied().find(|r| self.visible(*r))
    }
    pub fn step(&self, row: QuickRow, right: bool) -> QuickRow {
        let rows = self.rows(row);
        let at = rows.iter().position(|r| *r == row).unwrap_or(0);
        rows[(at + if right { 1 } else { rows.len() - 1 }) % rows.len()]
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn core_only_has_no_empty_connections_or_missing_navigation_targets() {
        let f = Features::parse("slot-features-v1\n");
        assert!(!f.visible(QuickRow::Connections));
        assert!(!f.visible(QuickRow::Filters));
        for row in QuickRow::ALL {
            if f.visible(row) {
                for r in f.rows(row) {
                    assert!(f.visible(f.step(r, true)));
                    assert!(f.visible(f.step(r, false)));
                }
            }
        }
    }
    #[test]
    fn network_time_is_available_with_either_transport_but_not_without_one() {
        for transport in ["wifi", "usb-network"] {
            let f = Features::parse(&format!(
                "slot-features-v1\nemulator-mgba\nnetwork-time\n{transport}\n"
            ));
            assert!(f.visible(QuickRow::NetworkTime));
        }
        let f = Features::parse("slot-features-v1\nemulator-mgba\nnetwork-time\n");
        assert!(!f.visible(QuickRow::NetworkTime));
    }
    #[test]
    fn storage_menu_is_available_for_either_independent_storage_module() {
        for module in ["external-sd", "storage-tools"] {
            let f = Features::parse(&format!("slot-features-v1\nemulator-mgba\n{module}\n"));
            assert!(f.visible(QuickRow::StorageTools));
            assert!(!f.visible(QuickRow::Diagnostics));
        }
        assert!(
            !Features::parse("slot-features-v1\nemulator-mgba\n").visible(QuickRow::StorageTools)
        );
    }
    #[test]
    fn runtime_off_does_not_mean_uninstalled() {
        let f = Features::default();
        assert!(f.visible(QuickRow::Ssh));
    }
    #[test]
    fn future_names_are_not_enabled_and_bad_header_fails_closed() {
        assert!(!Features::parse("bad\nssh").has("ssh"));
        assert!(!Features::parse("slot-features-v1\nunknown").has("ssh"));
    }
    #[test]
    fn nested_back_links_and_diagnostics_location_are_consistent() {
        for row in QuickRow::ALL {
            if let Some(parent) = row.parent() {
                assert!(parent.children().unwrap().contains(&row));
            }
        }
        let s = &QuickRow::SYSTEM;
        let at = s.iter().position(|r| *r == QuickRow::Diagnostics).unwrap();
        assert_eq!(s[at + 1], QuickRow::About);
    }
    #[test]
    fn single_core_capabilities_filter_platforms_settings_and_fallback() {
        let gpsp = Features::parse("slot-features-v1\nemulator-gpsp\nfilters\nrunahead\n");
        assert!(!gpsp.supports(Platform::Gb));
        assert!(!gpsp.supports(Platform::Gbc));
        assert!(gpsp.supports(Platform::Gba));
        assert_eq!(gpsp.core_count(Platform::Gba), 1);
        assert_eq!(
            gpsp.resolve_core(Platform::Gba, Core::Mgba),
            Some(Core::Gpsp)
        );
        assert_eq!(gpsp.resolve_core(Platform::Gb, Core::Mgba), None);
        assert!(!gpsp.visible(QuickRow::GbShader));
        assert!(!gpsp.visible(QuickRow::GbPalettes));
        assert!(!gpsp.visible(QuickRow::RunAhead));
        assert!(gpsp.visible(QuickRow::GbaShader));
        let mgba = Features::parse("slot-features-v1\nemulator-mgba\n");
        for platform in Platform::ALL {
            assert!(mgba.supports(platform));
        }
        assert_eq!(
            mgba.resolve_core(Platform::Gba, Core::Gpsp),
            Some(Core::Mgba)
        );
        let both = Features::default();
        assert_eq!(both.core_count(Platform::Gba), 2);
        assert_eq!(both.core_count(Platform::Gb), 1);
    }
    #[test]
    fn legacy_capabilities_keep_both_cores_but_bad_headers_do_not() {
        let old = Features::parse("slot-features-v1\nfilters\n");
        assert_eq!(old.core_count(Platform::Gba), 2);
        assert_eq!(Features::parse("damaged").core_count(Platform::Gba), 0);
    }
}
