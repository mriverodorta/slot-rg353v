//! On-demand explanations. No service probes, settings writes or startup assets.
use slot_ui::QuickRow;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Info {
    pub title: &'static str,
    pub body: &'static str,
}
impl Info {
    pub const SAVE_LOCATION: Self = Self { title: "Save location", body: "System keeps Saves and States on the drive running Slot. Game keeps them on the game's library drive, in separate Saves and States folders. Existing progress is not moved automatically." };
    pub fn rows(self) -> Vec<String> {
        let mut rows = vec![self.title.into()];
        let mut line = String::new();
        for word in self.body.split_whitespace() {
            let candidate = if line.is_empty() {
                word.into()
            } else {
                format!("{line} {word}")
            };
            if slot_ui::menu_detail_face(&candidate).w > 556 && !line.is_empty() {
                rows.push(std::mem::take(&mut line));
                line = word.into();
            } else {
                line = candidate;
            }
        }
        if !line.is_empty() {
            rows.push(line);
        }
        rows
    }
}
pub fn for_row(row: QuickRow) -> Option<Info> {
    use QuickRow::*;
    let body = match row {
        SchedutilGovernor => "On selects an alternative CPU power policy. Off uses our tuned ondemand 20 ms policy. Battery savings vary by game. Applies immediately and is remembered after restarting.",
        EnhancedAudio => "Uses higher-quality 48 kHz audio resampling. It can use more CPU and battery; Standard stays the default. Applies when you next open a game.",
        RunAhead => "Runs extra emulation frames to reduce input delay. It needs more CPU and may cause glitches in some games. Turn it off if play becomes less smooth.",
        Rewind => "Keeps recent gameplay in memory so you can rewind mistakes. It uses extra memory and processing. Turning this off does not remove battery saves or saved states.",
        FastForward => "Sets the speed used by the fast-forward shortcut. Actual speed depends on the game and available CPU power. Normal play speed stays unchanged.",
        FastForwardSound => "Keeps game audio audible during fast-forward. Turn it off for quiet fast-forward. This does not mute normal-speed gameplay.",
        EjectSave => "Chooses whether ejecting a cartridge keeps a resume state. Battery saves are separate and still belong to the game. Manual save states have their own controls.",
        IntegerScale => "Uses whole-number multiples of the original pixels for even pixel sizes, leaving larger borders. Overlays can lock the game layout so their artwork stays aligned.",
        GameBorder | Overlays => "Adds artwork around the game. The game layout stays aligned with the border; stretch and shrink shortcuts are blocked while overlays are enabled. Applies immediately.",
        OverlayStyle => "Slot uses decorative console borders. Perfect adds its own pixel-grid effect over the game. Extra shaders can combine with that effect; use Off to compare the overlay by itself.",
        Shader | GbaShader | GbShader | GbcShader => "Off uses the plain image. Shimmerless smooths uneven pixel scaling; Sharp LCD and LCD3x add display effects. Perfect overlays also add their own effect. Applies immediately for this console.",
        Palette => "Chooses the colours used for original Game Boy games. Game Boy Color and Advance games use their own colours. Applies immediately and stays selected when loading states.",
        GbPalettes => "On uses your chosen Game Boy palette. Off lets the emulator choose the automatic palette. Perfect overlays keep their matching palette enabled. Applies immediately.",
        ColourCorrection | GbaColourCorrection | GbColourCorrection | GbcColourCorrection => "Adjusts game colours toward the original handheld display. Off shows the uncorrected colours. Applies immediately for this console, separately from shaders and overlays.",
        FrameBlending | GbaBlending | GbBlending | GbcBlending => "Mixes consecutive game frames to soften flicker and imitate LCD persistence. Moving objects may leave trails. Off keeps frames separate. Applies immediately for this console.",
        SleepShutdown => "Sets how long Slot may stay asleep before shutting down to save battery. Power it on again to resume. This does not change the delay before the screen goes to sleep.",
        Network => "Wi-Fi connects to your wireless network. Network services are separate switches. Ordinary boots start offline; Developer Mode can restore development connections automatically.",
        UsbNetwork => "Connects Slot to a computer through the DC USB-C data port. SSH and File Sharing need their own switches. Internet access also needs connection sharing on the computer.",
        UsbStorage => "Shares the system's SLOT content drive as a USB disk. Slot pauses access while the computer owns it. Eject the disk on the computer before unplugging to protect your files.",
        Ssh => "Allows remote terminal access when Wi-Fi or USB networking is available. Uses the authentication set on the SSH page. Turn it off when you no longer need remote access.",
        Sharing => "Shares the SLOT content folder over Wi-Fi or USB networking using SMB. Open the shown address on your computer. File Sharing does not provide Internet access.",
        NetworkTime => "Sets the clock from an Internet time server. It needs an Internet connection. Ordinary boots leave this off unless Developer Mode enables it. Your timezone stays unchanged.",
        Developer => "Remembers development access across boots and enables installed development connections and services. Off returns to offline startup. Enable only while developing or troubleshooting.",
        Updates => "Checks for signed Slot RG353V updates over the Internet. Downloads only the changes needed for your installed version. Updates may restart and continue automatically after reconnecting.",
        ScreenshotShaders => "Includes the selected shader effect in new screenshots. Off captures without that effect. This changes saved screenshots, not the picture you see while playing.",
        ScreenshotFilters => "Includes the blue-light screen filter in new screenshots. This changes saved screenshots, not your gameplay display settings.",
        ScreenshotOverlay => "Includes the console border and overlay effect in new screenshots. Off saves the game image without the overlay. Existing screenshots stay unchanged.",
        FeatureStateBrowser => "Allows browsing, loading and deleting manual save states. Turning this off hides the browser; it does not delete states or change the game's battery saves.",
        FeatureManualStates => "Allows the manual save and load shortcuts. Turning this off blocks those shortcuts without deleting states. Automatic resume and battery saves are separate.",
        FeatureFavorites => "Allows marking games as favourites and browsing their shared shelf. Turning this off hides the feature without deleting your favourite selections.",
        FeatureCoreSelection => "Allows choosing between installed emulators for a game. A choice is offered only when more than one compatible core is installed. Saved states are specific to their core.",
        FeatureFastForward => "Allows the fast-forward shortcut during games. Turning this off blocks the shortcut while keeping your chosen speed for later.",
        FeatureRewind => "Allows the rewind shortcut during games. Turning this off blocks the shortcut without deleting saves or manual states.",
        FeatureInGameShader => "Allows changing shaders while playing, including the in-game menu and shortcuts. Turning this off keeps the selected look; you can still configure it from shelf Settings.",
        FeatureInGamePalette => "Allows changing Game Boy palettes while playing. Turning this off keeps your chosen palette and blocks in-game changes. Shelf Settings remain available.",
        FeatureInGameColor => "Allows changing colour correction while playing. Turning this off keeps your chosen correction and blocks in-game changes. Shelf Settings remain available.",
        _ => return None,
    };
    Some(Info {
        title: row.label(),
        body,
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn all_explanations_fit_without_truncation_or_smaller_fonts() {
        for info in QuickRow::ALL
            .into_iter()
            .filter_map(for_row)
            .chain([Info::SAVE_LOCATION])
        {
            let rows = info.rows();
            assert!(rows.len() <= 8, "{}: {} lines", info.title, rows.len());
            assert!(slot_ui::menu_face(info.title).w <= 556, "{}", info.title);
            for line in &rows[1..] {
                assert!(
                    slot_ui::menu_detail_face(line).w <= 556,
                    "{}: {line}",
                    info.title
                );
            }
            assert_eq!(rows[1..].join(" "), info.body);
        }
    }
}
