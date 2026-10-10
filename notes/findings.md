# Findings

Status as of 2026-10-10. All findings come from static analysis of the public update ZIPs
and the Korg System Updater 1.1.0 macOS app. No hardware has been touched yet.

## Platform

- **SoC module:** Raspberry Pi Compute Module 3 (`architecture="cm3"` in
  `ProductVersionInfo.xml` and in each ZIP's `.versioninfo.xml`). The mkII / SE / module
  variants are `cm4`.
- **Kernel:** `4.14.112`, vermagic `SMP preempt mod_unload modversions aarch64`. This is
  **not** PREEMPT_RT, just voluntary/full preempt. It matches `linux-raspberrypi`
  `rpi-4.14.y` in wavestate_OSS.
- **Userland:** Yocto (Poky, Zeus-era package versions), aarch64 with lib32 multilib.
- **Codename:** "Spark" (`/Users/peabody/temp/korg/git/Spark/...` in updater build paths,
  "Spark Raspberry Pi CM-3 EMMC based filesystem" in `rootfs-setup`).

## eMMC layout (from `/etc/init.d/rootfs-setup`)

| Partition | Mount | Notes |
|---|---|---|
| `mmcblk0p1` | ? | presumably the FAT boot partition (bootcode/start.elf/kernel/DTB). Not in the update. |
| `mmcblk0p2` | `/` | rootfs |
| `mmcblk0p3` | `/Korg` | ext4, `e2fsck -p` on boot; user data plus `/Korg/Updater` bind-mounted to `/Updater` |

## Update packages

```
<product>_system_update_<ver>.zip
└── <product>_system_update_<ver>/
    ├── install.info          VERSION, TIME_EST, then "<file> <md5>" per payload file
    ├── .versioninfo.xml      product / version / architecture
    ├── rootfs.tgz            overlay tarball extracted over /
    ├── readme.txt            (wavestate) "don't unzip"
    └── Wavestate_*Firmware.bin   (wavestate only) MCU images
```

- **No encryption and no signature.** Integrity is only per-file MD5 in `install.info`.
- `rootfs.tgz` is an **overlay**, not a full rootfs. It contains:
  - `/Korg/Wavest8` or `/Korg/Operator6/Operator6`: the synth app (aarch64 PIE, stripped)
  - `/Korg/...` factory data (waveforms, randomization data, internal FileSystem)
  - `/lib/modules/4.14.112/`: the full module tree (1129 `.ko` in wavestate)
  - `/etc/init.d/{rootfs-setup,networking,usb-gadget/*}`, `/etc/Product.config`,
    USB product name/ID files
  - `/sbin/e2fsck`
  - `/usr/Korg/firmware/` MCU images plus an `UpdateMCUs` flag file (wavestate)
- The base rootfs (busybox, libc, avahi, init, any sshd/getty) is **not** in the update.
  It is only on the eMMC.
- The updater app sends `StartSystemUpdateRequest { string updater_path }` over the RPC
  link (below), so the instrument installs from a path the host has copied in.

## Korg GPL kernel modules not in wavestate_OSS

Present in both wavestate and opsix module trees:

| Module | license | author | DT compatible |
|---|---|---|---|
| `sound/soc/codecs/snd-soc-wavest8.ko` | GPL | Bill Jenkins `<bill@korgrd.com>` | `korg,wavest8` (I2C) |
| `sound/soc/bcm/snd-soc-wavest8-codec.ko` | GPL v2 | Bill Jenkins, Florian Meier | `korg,wavest8-codec` |
| `extra/perfcnt-enable.ko` (and `drivers/perfcnt-enable/`) | GPL | Korg R&D | — |

The README in wavestate_OSS points only at upstream `raspberrypi/linux rpi-4.14.y`, so
the source of these GPL modules, the kernel config and the DT overlay are missing. This
is a concrete basis for a GPL source request to Korg.

## Microcontroller firmware (wavestate)

`Wavestate_KeyScannerFirmware.bin` (17.8 KB), `Panel0` (53.6 KB), `Panel1` (12.2 KB).
These are plain Cortex-M images: initial SP `0x20001FFF`, reset vector in `0x0800xxxx`.
That fits an **STM32**-family part with 8 KB of RAM, with the image loaded at the flash
base. They are unencrypted, so they can be disassembled with base address `0x08000000`
(Thumb). The CM3 reaches them over `/dev/ttyAMA0`, `/dev/ttyS0`, `/dev/spidev0.*` and
sysfs GPIO (strings in `Wavest8`).

## USB personality (`/etc/init.d/usb-gadget/`)

- configfs gadget, VID `0x0944` (KORG), PID from `/etc/usb_product_id`, serial =
  CPU ID from `vcgencmd otp_dump` row 28.
- Enabled in `configure`: **MIDI** and **NCM** (USB Ethernet). Function scripts also exist
  for `audio`, `audio2`, `mass-storage`, `network-rndis` and **`serial` (ACM)**, but
  they aren't enabled by default.
- NCM host MAC = `00:<cpuid bytes>:01`. On the device, `usb0` is `inet dhcp`
  (opsix `/etc/network/interfaces`), so check how the host side gets an address
  (link-local? DHCP server on the host?).

## Host ↔ instrument protocol

- Transport: **rpcz** (protobuf RPC) over **ZeroMQ 4.1.4** over TCP across the NCM link.
- Discovery: mDNS/Bonjour service **`_korg-synth._tcp`**, published by the synth via
  avahi and browsed by the updater. With the synth connected:
  `dns-sd -B _korg-synth._tcp`, then `dns-sd -L <name> _korg-synth._tcp` to get the port.
- Schemas: package `KorgProtocolMessage`, recovered into `analysis/protos/`
  (27 files from the updater, 173 from Wavest8, 216 from Operator6). Services include
  `ProductService` (Reboot, ShowPopupMessage, Randomize, KaossPhysics…), `ObjectService`,
  FileSystem, SoundLibrary, LicenseManager and ParameterDescriptor.
- `StartAuthorizationSession` / `VerifySessionIdChallenge` (challenge plus IV, with
  `AUTH_RESULT_DECRYPTION_FAILURE*`) belong to the **LicenseManager** (sound-library
  licensing). They don't appear to gate system updates.

## USB Boot Mode (recovery / raw eMMC access)

The updater's "USB Boot Utility" works like this: hold a model-specific button combination
at power-on, the display shows "USB Boot Mode", the host sends `bootcode.bin`, and the
instrument enumerates as a **USB mass-storage drive**. This is the Raspberry Pi usbboot /
`rpiboot` mass-storage flow. It probably exposes the whole eMMC, so you could:

- take a full image backup without opening the unit,
- read `mmcblk0p1` (config.txt, cmdline.txt, kernel, DTB/overlays) and the base rootfs,
- write a modified image back, and recover from a bad flash.

Korg warns that letting the OS "fix" or reformat the drive bricks the unit. Mount it
read-only and image the raw device.

## Open questions

- [ ] Button combination for USB Boot Mode on each model (see the USB Boot Utility PDF:
      `storage.korg.com/korgms/support/USB_Boot_Utility/Korg_USB_Boot_Utility_E.pdf`).
- [ ] Is there a getty on the ACM gadget or on a UART? Is any sshd/dropbear/telnetd in the base rootfs?
- [ ] RPC TCP port and whether the rpcz endpoint needs authentication.
- [ ] Contents of `mmcblk0p1`: config.txt, DT overlay for the Wavest8 codec and panel.
- [ ] Which STM32 part, and the CM3↔MCU protocol (UART framing, update/bootloader path).
- [ ] Does the opsix share the same carrier board? (Its modules match; codec driver is also "wavest8".)

## Next steps

1. Fetch the USB Boot Utility PDF to get the button combinations.
2. With hardware: enter USB Boot Mode, then `dd` the whole eMMC to an image (read-only),
   and keep it offline as a golden backup.
3. From the image: extract config.txt / DTB, `/proc/config.gz`-equivalent (or extract
   IKCONFIG from the kernel), the base rootfs package list, and init/inittab.
4. Normal boot plus NCM: browse `_korg-synth._tcp`, nmap the instrument's usb0 address,
   and write a minimal Python rpcz client against the recovered protos (start with
   `ProductService.ShowPopupMessage`, which is harmless).
5. Send the GPL source request to Korg for the three modules above, the kernel config,
   and the build scripts.
6. Then: a Yocto Zeus + meta-raspberrypi build pinned to 4.14.112, with the Korg modules
   and overlay copied from the image, booting Korg's `Wavest8` unmodified as a baseline.
