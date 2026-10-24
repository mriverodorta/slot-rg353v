//! RG353V removable-media events. No daemon, shell polling or render-thread I/O.
use std::collections::BTreeSet;
use std::io;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

const CONTROLLERS: [&str; 2] = ["fe2b0000.mmc", "fe2c0000.mmc"];
type Topology = BTreeSet<(PathBuf, u64, String)>;

#[derive(Default)]
pub(super) struct Change {
    pub changed: bool,
    pub inserted: bool,
}

pub(super) struct Monitor {
    events: Option<OwnedFd>,
    topology: Topology,
}

impl Monitor {
    pub(super) fn new() -> Self {
        // Bind first, so a card changed during the initial snapshot is not lost.
        let events = socket().ok();
        Self {
            events,
            topology: topology(Path::new("/sys/class/block")),
        }
    }

    pub(super) fn changed(&mut self) -> Change {
        let event = self.events.as_ref().map_or_else(Change::default, drain);
        // Cheap sysfs-only fallback covers queue loss, disabled netlink and wake.
        // No filesystem probing, content reads, processes or mount commands here.
        let next = topology(Path::new("/sys/class/block"));
        let changed = event.changed || self.topology != next;
        let inserted = event.inserted || next.iter().any(|entry| !self.topology.contains(entry));
        self.topology = next;
        Change { changed, inserted }
    }
}

fn controller(path: &Path) -> bool {
    path.components()
        .any(|part| CONTROLLERS.iter().any(|name| part.as_os_str() == *name))
}

fn topology(base: &Path) -> Topology {
    let mut result = Topology::new();
    let Ok(entries) = base.read_dir() else {
        return result;
    };
    for entry in entries.flatten() {
        let Ok(path) = entry.path().canonicalize() else {
            continue;
        };
        if !controller(&path) {
            continue;
        }
        let disk = if path.join("partition").exists() {
            path.parent().unwrap_or(&path)
        } else {
            &path
        };
        if std::fs::read_to_string(disk.join("device/type")).is_ok_and(|kind| kind.trim() == "SD") {
            if let Ok(meta) = path.metadata() {
                // diskseq changes even when the same card/block number returns.
                let sequence = std::fs::read_to_string(disk.join("diskseq")).unwrap_or_default();
                result.insert((path, meta.ino(), sequence));
            }
        }
    }
    result
}

fn socket() -> io::Result<OwnedFd> {
    let fd = unsafe {
        libc::socket(
            libc::AF_NETLINK,
            libc::SOCK_DGRAM | libc::SOCK_NONBLOCK | libc::SOCK_CLOEXEC,
            libc::NETLINK_KOBJECT_UEVENT,
        )
    };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    let fd = unsafe { OwnedFd::from_raw_fd(fd) };
    let mut address: libc::sockaddr_nl = unsafe { std::mem::zeroed() };
    address.nl_family = libc::AF_NETLINK as _;
    address.nl_groups = 1;
    let ok = unsafe {
        libc::bind(
            fd.as_raw_fd(),
            (&address as *const libc::sockaddr_nl).cast(),
            std::mem::size_of_val(&address) as _,
        )
    };
    if ok < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(fd)
    }
}

fn relevant(message: &[u8]) -> bool {
    let mut action = false;
    let mut block = false;
    let mut card = false;
    for field in message.split(|byte| *byte == 0) {
        action |= matches!(field, b"ACTION=add" | b"ACTION=remove" | b"ACTION=change");
        block |= field == b"SUBSYSTEM=block";
        if let Some(path) = field.strip_prefix(b"DEVPATH=") {
            card |= std::str::from_utf8(path).is_ok_and(|path| controller(Path::new(path)));
        }
    }
    action && block && card
}

fn drain(fd: &OwnedFd) -> Change {
    let mut change = Change::default();
    // Bound work if an unrelated device floods events; pending packets remain.
    for _ in 0..256 {
        let mut bytes = [0u8; 8192];
        let mut sender: libc::sockaddr_nl = unsafe { std::mem::zeroed() };
        let mut len = std::mem::size_of_val(&sender) as libc::socklen_t;
        let count = unsafe {
            libc::recvfrom(
                fd.as_raw_fd(),
                bytes.as_mut_ptr().cast(),
                bytes.len(),
                libc::MSG_DONTWAIT | libc::MSG_TRUNC,
                (&mut sender as *mut libc::sockaddr_nl).cast(),
                &mut len,
            )
        };
        if count < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted {
                continue;
            }
            // Lost events require a full reconciliation, not a silent miss.
            change.changed |= error.raw_os_error() == Some(libc::ENOBUFS);
            break;
        }
        // Accept the kernel multicast group only, never userspace messages.
        if len as usize == std::mem::size_of_val(&sender)
            && sender.nl_family as i32 == libc::AF_NETLINK
            && sender.nl_pid == 0
            && sender.nl_groups == 1
        {
            if count as usize > bytes.len() {
                change.changed = true;
            } else if relevant(&bytes[..count as usize]) {
                change.changed = true;
                change.inserted |= bytes[..count as usize]
                    .split(|byte| *byte == 0)
                    .any(|field| field == b"ACTION=add");
            }
        }
    }
    change
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    #[test]
    fn only_sd_controller_block_events_trigger_discovery() {
        for action in ["add", "remove", "change"] {
            for controller in CONTROLLERS {
                for tail in ["mmcblk4", "mmcblk4/mmcblk4p1"] {
                    let event = format!("{action}@/devices\0ACTION={action}\0SUBSYSTEM=block\0DEVPATH=/devices/platform/{controller}/mmc_host/mmc1/mmc1:1234/block/{tail}\0");
                    assert!(relevant(event.as_bytes()));
                    assert!(!relevant(
                        event.replace("SUBSYSTEM=block", "SUBSYSTEM=net").as_bytes()
                    ));
                    assert!(!relevant(
                        event.replace(controller, "fe310000.mmc").as_bytes()
                    ));
                    assert!(!relevant(event.replace("ACTION=", "IGNORED=").as_bytes()));
                }
            }
        }
        assert!(!relevant(b"ACTION=add\0SUBSYSTEM=block\0"));
        assert!(!relevant(
            b"ACTION=bind\0SUBSYSTEM=block\0DEVPATH=/fe2b0000.mmc/x\0"
        ));
    }

    #[test]
    fn topology_detects_removal_reinsertion_and_late_partitions_without_card_io() {
        let root = tempfile::tempdir().unwrap();
        let blocks = root.path().join("blocks");
        std::fs::create_dir(&blocks).unwrap();
        let disk = root.path().join("fe2b0000.mmc/block/mmcblk4");
        std::fs::create_dir_all(disk.join("device")).unwrap();
        std::fs::write(disk.join("device/type"), "SD\n").unwrap();
        std::fs::write(disk.join("diskseq"), "1\n").unwrap();
        symlink(&disk, blocks.join("mmcblk4")).unwrap();
        let initial = topology(&blocks);
        assert_eq!(initial.len(), 1);
        assert_eq!(initial, topology(&blocks));
        std::fs::write(disk.join("diskseq"), "2\n").unwrap();
        assert_ne!(initial, topology(&blocks));
        let part = disk.join("mmcblk4p1");
        std::fs::create_dir(&part).unwrap();
        std::fs::write(part.join("partition"), "1\n").unwrap();
        symlink(&part, blocks.join("mmcblk4p1")).unwrap();
        assert_eq!(topology(&blocks).len(), 2);
        std::fs::remove_file(blocks.join("mmcblk4")).unwrap();
        std::fs::remove_file(blocks.join("mmcblk4p1")).unwrap();
        assert!(topology(&blocks).is_empty());
        symlink(&disk, blocks.join("mmcblk4")).unwrap();
        assert_eq!(topology(&blocks).len(), 1);
        std::fs::write(disk.join("device/type"), "MMC\n").unwrap();
        assert!(topology(&blocks).is_empty());
    }

    #[test]
    fn real_kernel_socket_is_nonblocking_and_no_event_means_no_refresh() {
        let fd = socket().unwrap();
        assert!(!drain(&fd).changed);
        let mut monitor = Monitor::new();
        assert!(!monitor.changed().changed);
    }
}
