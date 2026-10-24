//! Save location is device configuration; game progress may travel with its ROM.
use std::{
    io,
    path::{Component, Path, PathBuf},
};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum SaveLocation {
    #[default]
    System,
    Game,
}
impl SaveLocation {
    pub fn read(system: &Path) -> Self {
        match std::fs::read_to_string(system.join("Config/save-location")) {
            Ok(s) if s.trim() == "game" => Self::Game,
            _ => Self::System,
        }
    }
}

/// Use the lexical library path: canonicalizing symlinked test ROMs would escape
/// the isolated test library and risk writing to a user's real progress.
pub fn progress_root(system: &Path, rom: &Path) -> PathBuf {
    if SaveLocation::read(system) == SaveLocation::Game {
        if let Some(platform) = rom.parent() {
            if matches!(
                platform.file_name().and_then(|n| n.to_str()),
                Some("GB" | "GBC" | "GBA")
            ) {
                if let Some(games) = platform
                    .parent()
                    .filter(|p| p.file_name().is_some_and(|n| n == "Games"))
                {
                    if let Some(library) = games.parent() {
                        return library.to_owned();
                    }
                }
            }
        }
    }
    system.to_owned()
}

/// A removed card leaves an ordinary directory beneath /run. Never interpret
/// that directory as an empty library, or write progress into the RAM filesystem.
pub fn ensure_progress_storage(path: &Path, write: bool) -> io::Result<()> {
    if !path.starts_with("/run/slot-sd-library") {
        return Ok(());
    }
    let rows = std::fs::read_to_string("/proc/mounts")?;
    check_mount(path, write, &rows)
}
fn check_mount(path: &Path, write: bool, rows: &str) -> io::Result<()> {
    let invalid = || {
        io::Error::new(
            io::ErrorKind::NotConnected,
            "Game SD card is unavailable; progress was not redirected",
        )
    };
    if path.components().any(|p| matches!(p, Component::ParentDir)) {
        return Err(invalid());
    }
    let root = ["/run/slot-sd-library/TF1", "/run/slot-sd-library/TF2"]
        .into_iter()
        .find(|r| path.starts_with(r))
        .ok_or_else(invalid)?;
    let mounted = rows
        .lines()
        .filter_map(|line| {
            let cols: Vec<_> = line.split_whitespace().collect();
            (cols.len() >= 4 && cols[1] == root).then_some(cols)
        })
        .next_back()
        .ok_or_else(invalid)?;
    if mounted[2] != "exfat" || !mounted[0].starts_with("/dev/mmcblk") {
        return Err(invalid());
    }
    if write && !mounted[3].split(',').any(|s| s == "rw") {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "Game SD card is read-only",
        ));
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn removed_or_readonly_cards_never_fall_back_to_ram() {
        let p = Path::new("/run/slot-sd-library/TF1/Saves/GBA/test.sav");
        assert!(check_mount(p, false, "").is_err());
        let ro = "/dev/mmcblk1p1 /run/slot-sd-library/TF1 exfat ro,noexec 0 0";
        assert!(check_mount(p, false, ro).is_ok());
        assert!(check_mount(p, true, ro).is_err());
        assert!(check_mount(p, true, &ro.replace("ro,", "rw,")).is_ok());
        assert!(check_mount(
            Path::new("/run/slot-sd-library/TF1/../TF2/Saves/x"),
            true,
            &ro.replace("ro,", "rw,")
        )
        .is_err());
    }
}
