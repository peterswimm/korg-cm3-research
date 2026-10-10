# korg-cm3-research

Research notes and tooling for building custom firmware for the Raspberry Pi CM3-based
Korg synths: **wavestate** (original) and **opsix** (original). The mkII / SE / module
variants are CM4 and are out of scope for now.

Related: Korg's GPL source dump, github.com/korginc/wavestate_OSS.

**This repo contains no Korg software, data or derived files.** Owners save the update ZIP for
their own instrument with Korg's tools, then run `tools/prepare.py` to rebuild everything
locally. See [docs/obtaining-korg-files.md](docs/obtaining-korg-files.md).

## Layout

| Path | Contents | Tracked |
|---|---|---|
| `docs/obtaining-korg-files.md` | How to save Korg's update ZIPs and rebuild the local tree | yes |
| `notes/findings.md` | What we know so far, open questions, next steps | yes |
| `tools/prepare.py` | Verifies saved update ZIPs, unpacks them, recovers and compiles schemas | yes |
| `tools/extract_protos.py` | Recovers `.proto` files from FileDescriptorProtos embedded in binaries | yes |
| `tools/korgrpc.py` | rpcz client for the instrument's USB-network API (discover / list / call) | yes |
| `downloads/`, `extracted/` | Your saved Korg ZIPs and their unpacked contents | **no** |
| `analysis/protos/`, `build/` | Schemas recovered from your copies, and their compiled modules | **no** |

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install protobuf grpcio-tools pyzmq zeroconf
.venv/bin/python -I tools/prepare.py path/to/<instrument>_system_update_<ver>.zip
.venv/bin/python -I tools/korgrpc.py selftest
```
