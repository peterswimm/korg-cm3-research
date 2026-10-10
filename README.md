# korg-cm3-research

Research notes and tooling for building custom firmware for the Raspberry Pi CM3-based
Korg synths: **wavestate** (original) and **opsix** (original). The mkII / SE / module
variants are CM4 and are out of scope for now.

Related: Korg's GPL source dump, `../wavestate_OSS` (github.com/korginc/wavestate_OSS).

## Layout

| Path | Contents | Tracked |
|---|---|---|
| `notes/findings.md` | What we know so far, open questions, next steps | yes |
| `notes/ProductVersionInfo.xml` | Korg's update index (product → version, arch, ZIP URL) | yes |
| `tools/extract_protos.py` | Recovers `.proto` files from FileDescriptorProtos embedded in binaries | yes |
| `analysis/protos/<source>/` | Recovered protobuf schemas (updater, Wavest8, Operator6) | yes |
| `downloads/` | Official Korg update ZIPs, as downloaded | **no** |
| `extracted/` | Unpacked ZIPs and rootfs overlays | **no** |

Korg's binaries and update packages are proprietary and are git-ignored. Fetch them
yourself (see below). The recovered schemas in `analysis/protos/` are derived from Korg
binaries. Review them before publishing this repo anywhere public.

## Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install protobuf
mkdir -p downloads/wavestate_3_2_1 downloads/opsix_3_1_2
curl -L -o downloads/wavestate_3_2_1/wavestate_system_update_3_2_1.zip \
  https://storage.korg.com/korgms/KorgSystemUpdater/wavestate_system_update_3_2_1.zip
curl -L -o downloads/opsix_3_1_2/opsix_system_update_3_1_2.zip \
  https://storage.korg.com/korgms/KorgSystemUpdater/opsix_system_update_3_1_2.zip
# unzip each into extracted/<name>/zip, then: tar -xzf .../rootfs.tgz -C extracted/<name>/rootfs
.venv/bin/python -I tools/extract_protos.py extracted/wavestate_3_2_1/rootfs/Korg/Wavest8 analysis/protos/wavestate_3_2_1
```

SHA-256 of the analysed ZIPs:

```
1ccdc7d8972b258e3956a342cecfd92dbae6d9b08baa073ecb9ec937f209d3bd  wavestate_system_update_3_2_1.zip
f7f08c9e7ee0595905cc9d9f2585c41dc8c6667ace4ef9bd398393ab5b92da52  opsix_system_update_3_1_2.zip
```
