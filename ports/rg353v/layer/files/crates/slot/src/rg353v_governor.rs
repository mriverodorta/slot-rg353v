//! RG353V CPU policy: after startup boost, on explicit changes and on wake.
use std::path::Path;

pub const SAMPLING_US: &str = "20000";

pub fn apply() {
    if let Err(error) = apply_at(Path::new("/sys/devices/system/cpu/cpufreq")) {
        eprintln!("slot: CPU sampling cadence: {error}");
    }
}

pub fn apply_at(root: &Path) -> std::io::Result<bool> {
    if std::fs::read_to_string(root.join("policy0/scaling_governor"))?.trim() != "ondemand" {
        return Ok(false);
    }
    let path = root.join("ondemand/sampling_rate");
    if std::fs::read_to_string(&path)?.trim() == SAMPLING_US {
        return Ok(false);
    }
    std::fs::write(path, SAMPLING_US)?;
    Ok(true)
}

/// Apply only after the first scanout, on an explicit settings change, or on wake.
/// Frequency/voltage bounds and the GPU policy remain owned by hardware setup.
pub fn select(schedutil: bool) -> bool {
    match select_after_boost_at(
        Path::new("/sys/devices/system/cpu/cpufreq"),
        Path::new("/run/slot-boot/cpu-governor"),
        schedutil,
    ) {
        Ok(None) => false,
        Ok(Some(_)) => true,
        Err(error) => {
            eprintln!("slot: CPU governor: {error}");
            // A failed explicit choice is logged once, not retried every frame.
            true
        }
    }
}

pub fn select_after_boost_at(
    root: &Path,
    pending: &Path,
    schedutil: bool,
) -> std::io::Result<Option<bool>> {
    if pending.exists() {
        return Ok(None);
    }
    select_at(root, schedutil).map(Some)
}

pub fn select_at(root: &Path, schedutil: bool) -> std::io::Result<bool> {
    let policy = root.join("policy0");
    let wanted = if schedutil { "schedutil" } else { "ondemand" };
    let available = std::fs::read_to_string(policy.join("scaling_available_governors"))?;
    if !available.split_whitespace().any(|name| name == wanted) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            "CPU governor unavailable",
        ));
    }
    let current = policy.join("scaling_governor");
    let mut changed = false;
    if std::fs::read_to_string(&current)?.trim() != wanted {
        std::fs::write(&current, format!("{wanted}\n"))?;
        changed = true;
    }
    if !schedutil {
        changed |= apply_at(root)?;
    }
    Ok(changed)
}
