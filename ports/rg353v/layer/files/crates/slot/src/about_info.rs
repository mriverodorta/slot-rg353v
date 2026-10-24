//! Read small, local version records only when About is opened.
use std::path::Path;

pub struct Info {
    pub firmware: String,
    pub kernel: String,
    pub frontend: String,
}

fn identifier(value: &str) -> String {
    let value = value.trim();
    if value.is_empty()
        || value.len() > 96
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._+-".contains(&b))
    {
        return "Unavailable".into();
    }
    value.into()
}

fn firmware(cmdline: &str) -> String {
    cmdline
        .split_whitespace()
        .find_map(|v| v.strip_prefix("SLOT_OS_ID="))
        .map(identifier)
        .unwrap_or_else(|| "Factory".into())
}

fn frontend(path: &Path) -> String {
    if path.file_name().and_then(|s| s.to_str()) != Some("System") {
        return "Factory".into();
    }
    path.parent()
        .and_then(Path::file_name)
        .and_then(|s| s.to_str())
        .map(identifier)
        .unwrap_or_else(|| "Factory".into())
}

impl Info {
    pub fn read() -> Self {
        Self {
            firmware: firmware(&std::fs::read_to_string("/proc/cmdline").unwrap_or_default()),
            kernel: identifier(
                &std::fs::read_to_string("/proc/sys/kernel/osrelease").unwrap_or_default(),
            ),
            frontend: std::env::var_os("SLOT_CORE_DIR")
                .map(|p| frontend(Path::new(&p)))
                .unwrap_or_else(|| "Factory".into()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn versions_follow_active_os_and_component_not_compile_time_upstream() {
        assert_eq!(
            firmware("quiet SLOT_OS_ID=os-20261019-game-start3 other=1"),
            "os-20261019-game-start3"
        );
        assert_eq!(
            frontend(Path::new(
                "/storage/slot-manager/revisions/slot-20261019-about1/System"
            )),
            "slot-20261019-about1"
        );
        assert_eq!(identifier("7.0.2\n"), "7.0.2");
    }
    #[test]
    fn missing_or_invalid_identifiers_have_safe_fallbacks() {
        assert_eq!(firmware("quiet"), "Factory");
        assert_eq!(firmware("SLOT_OS_ID=../../private"), "Unavailable");
        assert_eq!(frontend(Path::new("/unexpected")), "Factory");
        assert_eq!(identifier(""), "Unavailable");
        assert_eq!(identifier(&"a".repeat(97)), "Unavailable");
    }
}
