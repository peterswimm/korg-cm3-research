# Getting the Korg files yourself

This repo contains **no Korg software, data or derived files.** That covers update packages,
binaries, recovered `.proto` schemas, Korg's update index and Korg's manuals. Everything the
tools work on comes from the owner's machine: files you save with Korg's own tools for the
instrument you own. `tools/prepare.py` then rebuilds the working tree locally, and every
output path is git-ignored.

## 1. Install Korg's tools

From Korg's support download page for your instrument, install the
**Korg System Updater**. It includes the USB Boot Utility. On macOS it installs to
`/Applications/KORG/Korg System Updater/`.

## 2. Save the update ZIP for your instrument

Pick **one** of these options.

**Korg System Updater (normal path).** Connect the instrument over USB and launch the updater.
On the instrument, set the USB Network setting (UTILITY → MIDI & USB) to **NCM**; the
updater will offer to change it for you. Choose your instrument and use the updater's
option to **save the update for offline use**. You get a file like
`wavestate_system_update_3_2_1.zip`.

**USB Boot Utility (recovery path).** In the utility, select your exact model, press **Save**,
and pick a folder. Korg's manual describes this flow (page 6). You get a file like
`wavestate_mkII_usb_boot_3_0_9.zip`. This repo has only been checked against the System
Updater's `*_system_update_*.zip` format so far.

Either way, **don't unzip or modify the file.** `prepare.py` checks it against Korg's own MD5
list, and the same ZIP is what you would hand back to Korg's tools to restore the instrument.

Select the right model. The original **wavestate** and **opsix** are CM3 boards, which is
what this repo targets. The mkII / SE / module variants are CM4. To tell them apart, see Korg's
"Identifying instrument models" help article: the original wavestate has a silver joystick
tip and a nameplate that reads just "wavestate".

## 3. Rebuild the local working tree

```bash
python3 -m venv .venv
.venv/bin/pip install protobuf grpcio-tools pyzmq zeroconf
.venv/bin/python -I tools/prepare.py ~/Downloads/wavestate_system_update_3_2_1.zip
```

This produces:

| Path | Contents |
|---|---|
| `extracted/<product>_<version>/zip/` | the ZIP contents (install.info, rootfs.tgz, MCU firmware…) |
| `extracted/<product>_<version>/rootfs/` | the unpacked rootfs overlay |
| `analysis/protos/<set>/` | `.proto` schemas recovered from the synth binary and the System Updater app |
| `build/py/<set>/` | Python modules compiled from those schemas, used by `tools/korgrpc.py` |

The set name comes from the ZIP's `.versioninfo.xml`, for example `wavestate_3_2_1`,
`opsix_3_1_2`, or `system_updater_1_1_0` for the updater app's schemas.

## 4. Use the tools

```bash
.venv/bin/python -I tools/korgrpc.py selftest
.venv/bin/python -I tools/korgrpc.py list --protos wavestate_3_2_1
.venv/bin/python -I tools/korgrpc.py discover          # instrument connected, USB Network = NCM
```

## Notes

- Keep your saved ZIP. It's your known-good restore image for Korg's USB Boot Utility.
- Don't commit anything from `downloads/`, `extracted/`, `analysis/protos/` or `build/`.
  `.gitignore` already covers them; keep it that way in forks.
