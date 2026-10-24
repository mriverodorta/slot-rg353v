//! Verify only the core being opened and load the exact, immutable bytes checked.
use std::ffi::CString;
use std::fs::File;
use std::io;
use std::os::fd::{AsRawFd, FromRawFd};
use std::path::Path;
use std::process::{Command, Stdio};

const HASHES: &str = "SLOT_CORE_HASHES";
const SEALS: i32 = libc::F_SEAL_WRITE | libc::F_SEAL_GROW | libc::F_SEAL_SHRINK | libc::F_SEAL_SEAL;

fn expected_hash<'a>(entries: &'a str, name: &str) -> io::Result<&'a str> {
    let mut mgba = None;
    let mut gpsp = None;
    for line in entries.lines() {
        let (key, hash) = line.split_once('=').ok_or_else(invalid)?;
        if hash.len() != 64
            || !hash
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        {
            return Err(invalid());
        }
        let entry = match key {
            "mgba_libretro.so" => &mut mgba,
            "gpsp_libretro.so" => &mut gpsp,
            _ => return Err(invalid()),
        };
        if entry.replace(hash).is_some() {
            return Err(invalid());
        }
    }
    if mgba.is_none() && gpsp.is_none() {
        return Err(invalid());
    }
    match name {
        "mgba_libretro.so" => mgba.ok_or_else(invalid),
        "gpsp_libretro.so" => gpsp.ok_or_else(invalid),
        _ => Err(invalid()),
    }
}

fn invalid() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidData,
        "invalid sealed-core verification contract",
    )
}

fn snapshot_with(path: &Path, entries: &str, helper: &Path) -> io::Result<File> {
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .ok_or_else(invalid)?;
    let expected = expected_hash(entries, name)?;
    let absolute = std::path::absolute(path)?;
    let label = CString::new("slot-core").unwrap();
    // Only the helper's stdout receives a duplicate; the loading fd stays CLOEXEC.
    let fd =
        unsafe { libc::memfd_create(label.as_ptr(), libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    let file = unsafe { File::from_raw_fd(fd) };
    let status = Command::new(helper)
        .arg("--core")
        .arg(expected)
        .arg(absolute)
        .stdin(Stdio::null())
        .stdout(Stdio::from(file.try_clone()?))
        .status()?;
    if !status.success()
        || unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GET_SEALS) } != SEALS
        || file.metadata()?.len() == 0
    {
        return Err(invalid());
    }
    Ok(file)
}

pub fn snapshot(path: &Path) -> io::Result<Option<File>> {
    match std::env::var(HASHES) {
        Ok(entries) => snapshot_with(path, &entries, Path::new("/usr/bin/slot-verify")).map(Some),
        Err(std::env::VarError::NotPresent) => {
            // Standalone development bundles keep their existing loader behavior.
            // An installed opt-in bundle must never silently bypass its gate.
            if path
                .parent()
                .is_some_and(|p| p.join("core-verification-v1").exists())
            {
                Err(invalid())
            } else {
                Ok(None)
            }
        }
        Err(_) => Err(invalid()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn requires_selected_known_cores_with_exact_lowercase_hashes() {
        let a = "a".repeat(64);
        let b = "b".repeat(64);
        let valid = format!("gpsp_libretro.so={a}\nmgba_libretro.so={b}");
        assert_eq!(expected_hash(&valid, "mgba_libretro.so").unwrap(), b);
        assert_eq!(expected_hash(&valid, "gpsp_libretro.so").unwrap(), a);
        assert_eq!(
            expected_hash(&format!("mgba_libretro.so={b}"), "mgba_libretro.so").unwrap(),
            b
        );
        assert!(expected_hash(&format!("mgba_libretro.so={b}"), "gpsp_libretro.so").is_err());
        for bad in [
            "".to_owned(),
            format!("{valid}\nmgba_libretro.so={b}"),
            format!("{valid}\nextra={a}"),
            valid.replace('a', "A"),
            valid.replace(&a, "00"),
        ] {
            assert!(expected_hash(&bad, "mgba_libretro.so").is_err(), "{bad}");
        }
        assert!(expected_hash(&valid, "other.so").is_err());
    }

    #[test]
    fn rejects_missing_or_unsuccessful_helper_without_returning_a_loadable_file() {
        let valid = format!(
            "mgba_libretro.so={}\ngpsp_libretro.so={}",
            "a".repeat(64),
            "b".repeat(64)
        );
        assert!(snapshot_with(
            Path::new("/tmp/mgba_libretro.so"),
            &valid,
            Path::new("/missing-helper")
        )
        .is_err());
        assert!(snapshot_with(
            Path::new("/tmp/mgba_libretro.so"),
            &valid,
            Path::new("/bin/false")
        )
        .is_err());
        // Even a helper claiming success must supply sealed nonempty bytes.
        assert!(snapshot_with(
            Path::new("/tmp/mgba_libretro.so"),
            &valid,
            Path::new("/bin/true")
        )
        .is_err());
    }
}
