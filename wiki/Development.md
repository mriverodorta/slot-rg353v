# Private development images

Public and private builds are explicit separate profiles:

| Location | Contents | In Git? |
| --- | --- | --- |
| `resources/` | Caches, prepared sources, experiments, historical images, private library and test evidence | No |
| `localdev/provisioning/` | Personal Wi-Fi provisioning, SSH client public key and development server identity | No |
| `localdev/images/<version>/` | Private development image and its build record | No |
| `release/<version>/` | Public candidate image, checksum and build record | No; attach selected artifacts to a release later |
| `wiki/`, scripts, layer and license notices | Public project source and documentation | Yes |

The private client key remains on the computer, normally in its SSH configuration directory. It is never inserted into an image. `authorized_keys` contains only the client's **public** Ed25519 key. The separate `ssh_host_ed25519_key` is the device server identity and belongs only to private image provisioning. Keep strict host-key verification and the corresponding known-host record.

## Configure once

The provisioning schema is documented by `ports/rg353v/image/slot-setup-debug.py`. Keep this structure in `localdev/provisioning/slot-setup-debug.json`:

```json
{
  "schema": 1,
  "wifi": [{"name": "Home.nmconnection", "data": "BASE64_OF_YOUR_NETWORKMANAGER_PROFILE"}],
  "authorized_keys": ["ssh-ed25519 YOUR_PUBLIC_KEY your-comment"]
}
```

This is a schema illustration, not a usable credential profile. Protect the real file and server key with owner-only permissions. No real credential is included in this guide or the repository.

## Build

```sh
bash scripts/build-localdev.sh --version dev-1 --plan
bash scripts/build-localdev.sh --version dev-1
```

The same qualified-input fast path described in [Building](Building.md) is supported. Private composition supplies the profile and server identity and enables setup-time developer access. During setup keep the relevant Wi-Fi/SSH/USB Networking/Developer modules and prepared developer-access choices selected. Omitting the transport or SSH module cannot be repaired merely by having a key inside the seed profile.

Build output contains `PRIVATE` in its filename. After a successful build the command updates `localdev/current` and archives its previous image under `resources/private-image-history/`, preserving the older delivery path as a link. Only the current compressed image remains physically under `localdev/images/`. Never upload a private image, its build logs or a raw personal card dump.

## Library and testing

For local hardware tests, keep a single content backup outside Git. The backup helper uses `.private-rg353v/content/`, physically under `resources/.private-rg353v/content/`. Use `python3 scripts/rg353v-personal-library.py pull` while the game is ejected before and after device tests. History preserves changed saves. Do not overwrite newer imported local saves with stale device copies; the pending-restore manifest protects them.

Default provisioning is SD-only. eMMC writes require explicit authorization and the exact device identity. Keep silent test audio, isolated save/state output, F-held recovery and persistent-RAM/watchdog evidence available. Do not use the real library as disposable test data.
