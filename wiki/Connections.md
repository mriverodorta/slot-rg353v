# Connections and file transfers

Installing a module makes the capability available; switching it on is separate. Ordinary boots start with optional network access and services off. Developer Mode is the explicit exception for persistent development access. An unfinished OTA session may also restore its previously enabled transport after reboot to finish the authorized updates; it does not enable remote services. SSH, SMB and automatic time can work over a usable Wi-Fi or USB network; enabling a transport does not install missing services.

![Connections menu](images/features/connections.png)

| What you want | Modules to select during setup |
| --- | --- |
| Terminal over Wi-Fi | Wi-Fi + SSH |
| File-manager share over Wi-Fi | Wi-Fi + File Sharing |
| Terminal over USB | USB Networking + SSH |
| File-manager share over USB | USB Networking + File Sharing |
| SLOT as an external USB drive | USB Storage |
| Internet through a computer | USB Networking, plus sharing/routing configured on that computer |

Network names, IPs and status values in the guide images are examples. Use the address shown on **your handheld**, not `192.0.2.2` from the illustrations.

## Wi-Fi

![Wi-Fi connection status](images/features/wifi.png)

Open Connections → Wi-Fi, turn it on and choose Other Networks. Select the access point and enter its password. X shows/hides typed characters; Start submits. Saved connection credentials are local to that installation. Enterprise/802.1X setup is not provided by this picker.

![Available wireless networks](images/features/wifi-networks.png)

1. Use Left/Right on the Wi-Fi row to turn the radio On.
2. Select Other Networks and press A. Wait for the scan; X refreshes it.
3. Select your network and press A to open its password keyboard.
4. Move with the D-pad, add characters with A and delete with Y. L/R changes keyboard sections; X shows/hides the password. Press Start to connect.
5. Return to the status screen and check for both the connected name and IP address. B leaves the page.

![Wi-Fi password keyboard](images/features/wifi-password.png)

Turning Wi-Fi Off also stops SSH, File Sharing and automatic network time unless a working enabled USB transport keeps them available. SSH remembers your On/Off choice for the current boot: when Wi-Fi or USB networking returns, previously enabled SSH starts again. While both transports are Off, SSH can show On with “Service stopped”; switch SSH Off to cancel its return. File Sharing and automatic network time must be enabled again separately. Ordinary boots still start offline; Developer Mode restores its selected services at boot.

The shelf Wi-Fi symbol appears **left of the clock only while Wi-Fi is connected**. It updates in the background and need not appear on the first shelf frame. It does not indicate USB networking. A connected Wi-Fi icon also does not prove internet access.

## USB networking

![USB mode choices](images/features/usb.png)

![USB network connection](images/features/usb-network.png)

Connect the handheld's **DC USB-C port** to the computer with a data-capable cable. Turn on Connections → USB → USB Networking. Accept the accessory prompt if macOS presents one. A cable may charge successfully without carrying USB data.

The USB transport supports computer access independently of Wi-Fi. Install and enable SSH for a terminal and SMB for file-manager access. Use the displayed network address; do not assume it is the same as the Wi-Fi address. macOS/Linux and supported Windows USB modes are handled by the transport; Windows setup may depend on the host's USB network driver.

Internet access through USB additionally requires internet sharing/routing on the computer. macOS Internet Sharing or Windows Internet Connection Sharing must be configured with the appropriate upstream and USB adapter. Merely plugging in USB does not provide internet. Windows ICS commonly uses 192.168.137.0/24; the handheld's actual status page is authoritative. Host firewall policy can affect SSH/SMB access.

**macOS:** allow the USB accessory when prompted, then check the USB Ethernet adapter in Network settings. If you want internet, share the Mac's active internet connection to that adapter. Leave Internet via USB Off for a local terminal/file-transfer connection that does not need routing.

**Windows:** check that the USB network adapter appears in Network Connections. Use the supported normal mode first; Legacy USB Mode is a compatibility option if the host requires it. For internet, share the upstream connection to the USB adapter through Windows Internet Connection Sharing, then enable Internet via USB on the handheld. Physical host/driver combinations still require qualification; the presence of a menu switch is not proof that every Windows driver works.

**Linux:** use the USB network interface exposed by the host and an address compatible with the handheld's displayed peer/subnet. Internet sharing needs forwarding/NAT on that interface. Neither SSH nor SMB needs internet access for a local USB connection.

Wi-Fi can stay Off during USB SSH/SMB. Enable each installed service separately the first time. SSH remembers its enabled choice within the current boot and resumes when a transport returns; USB networking never enables SSH if you have not selected it. USB Storage takes exclusive ownership of the USB gadget/content handoff, so finish it before switching to USB Networking.

## SSH

![SSH settings](images/features/ssh.png)

Enable Connections → SSH and use the authentication information shown there. For public installations, import your own public key or use the configured password path; the developer's key is absent. Verify the device host-key fingerprint rather than disabling SSH host checks.

```sh
ssh root@DEVICE_IP
```

SSH provides system access. Disable it when not needed. USB SSH does not require a functioning Wi-Fi adapter.

To import a public key, copy your `.pub` file into `Config/SSH` on SLOT, choose **Import Public Key**, check the displayed fingerprint and confirm. Import the public half only; your private key stays on the computer. **Set Password** is the separate password path. Public release images do not contain the owner's development key or saved Wi-Fi credentials.

![Set an SSH password](images/features/ssh-set-password.png)

For SFTP, connect with the same user, address and authentication, then open `/storage/slotcontent`. Eject any game before replacing saves or states. Verify a changed host identity after a fresh install instead of bypassing the host-key warning.

## SMB file sharing

![File sharing enabled](images/features/file-sharing.png)

Enable File Sharing and use its displayed address. On macOS/Linux use `smb://DEVICE_IP/Slot`; on Windows use `\\DEVICE_IP\Slot` in File Explorer. The default share's access mode is shown in Settings. Direct-IP access avoids a dependency on network discovery services. The image does not need nmbd or Avahi browsing for this path.

On macOS, the file manager's Connect to Server command accepts the `smb://` address. On Windows, enter the double-backslash path in the file-manager address bar. On Linux, use an SMB-capable file manager or client. The share presents the content folders; copy games into `Games/GB`, `Games/GBC` or `Games/GBA`. If the displayed access mode is Guest, select Guest when the client asks.

The current implementation uses the Linux ksmbd server with its small userspace helpers. The UI name remains **File Sharing**; users do not need Samba's discovery daemons. Keep it Off when no transfer is needed.

## USB Storage

![Start a USB storage transfer](images/features/usb-storage.png)

USB Storage is different from USB networking: it exports the SLOT exFAT partition as a drive, not a network adapter. This works from supported SD and eMMC installations. Slot releases local filesystem ownership before the computer writes it, then restores local access when USB mode ends.

Eject the game before enabling storage. Copy files, **safely eject the drive on the computer**, then disconnect/exit USB Storage and wait for the shelf to return. Never write the exported partition from the handheld and computer simultaneously. The system/boot partitions are not exported as writable game storage.

1. Hold F to eject the game.
2. Open Connections → USB → USB Storage and select Connect to Computer.
3. Connect the **DC USB-C** port using a data cable. Accept a computer accessory prompt if shown.
4. Wait for SLOT to mount. Copy files using the [content folder layout](Adding-Games.md).
5. Safely eject SLOT using the computer, wait for writes to finish, then finish the mode/disconnect as directed. Wait for the shelf before opening a game.

| Waiting for approval/data | Content shared with computer |
| --- | --- |
| ![USB Storage waiting](images/features/usb-storage-waiting.png) | ![USB Storage connected](images/features/usb-storage-connected.png) |

If charging works but neither USB mode connects, check the cable and port first. The top OTG port is not the port used by this computer-device workflow. If macOS says the accessory needs approval, charging alone does not complete that approval.
