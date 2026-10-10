#!/usr/bin/env python3
"""Turn Korg update ZIPs you saved yourself into the local working tree this repo expects.

Nothing Korg-derived is committed to this repo. Each owner regenerates it locally:

  1. Save the update ZIP for your instrument with Korg's own tools (see docs/obtaining-korg-files.md).
  2. Run:  .venv/bin/python -I tools/prepare.py ~/Downloads/wavestate_system_update_3_2_1.zip [...]

For each ZIP this:
  - verifies every file against the MD5s Korg lists in install.info
  - unpacks it to extracted/<product>_<version>/zip and rootfs.tgz to .../rootfs
  - recovers .proto schemas from the main synth binary into analysis/protos/<set>/
  - compiles them to build/py/<set>/ for tools/korgrpc.py
It also does the same for the Korg System Updater app (schemas only), if it's installed.

All outputs are git-ignored.
"""
import argparse
import hashlib
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPDATER_APP = Path("/Applications/KORG/Korg System Updater/Korg System Updater.app")
UPDATER_BIN = UPDATER_APP / "Contents/MacOS/Korg System Updater"
ELF_MAGIC = b"\x7fELF"


def run(*cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True)


def set_name(product, version):
    p = re.sub(r"^Korg\s+", "", product).strip().replace(" ", "_")
    return f"{p}_{version.replace('.', '_')}"


def verify_and_unpack(zpath):
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        info_name = next((n for n in names if n.endswith("/install.info")), None)
        ver_name = next((n for n in names if n.endswith("/.versioninfo.xml")), None)
        if not info_name or not ver_name:
            sys.exit(f"{zpath}: not a Korg system update ZIP (no install.info / .versioninfo.xml)")
        prefix = info_name.rsplit("/", 1)[0] + "/"
        ver = re.search(r"<SystemUpdateVersionInfo\b[^>]*>", z.read(ver_name).decode()).group(0)
        product = re.search(r'product="([^"]+)"', ver).group(1)
        version = re.search(r'version="([^"]+)"', ver).group(1)
        arch = re.search(r'architecture="([^"]+)"', ver).group(1)
        name = set_name(product, version)

        lines = z.read(info_name).decode().splitlines()
        bad = []
        for line in lines:
            parts = line.split()
            if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{32}", parts[1]):
                got = hashlib.md5(z.read(prefix + parts[0])).hexdigest()
                if got != parts[1]:
                    bad.append(parts[0])
        if bad:
            sys.exit(f"{zpath}: MD5 mismatch for {bad}. Re-save the update with Korg's tool.")

        dest = ROOT / "extracted" / name
        (dest / "zip").mkdir(parents=True, exist_ok=True)
        z.extractall(dest / "zip")
    print(f"{zpath.name}: {product} {version} ({arch}), install.info MD5s OK -> extracted/{name}")

    rootfs = dest / "rootfs"
    rootfs.mkdir(exist_ok=True)
    with tarfile.open(dest / "zip" / prefix / "rootfs.tgz") as t:
        t.extractall(rootfs, filter="data")
    return name, rootfs


def main_binary(rootfs):
    """Largest ELF under /Korg: Wavest8, Operator6, etc."""
    best = None
    for p in (rootfs / "Korg").rglob("*"):
        if p.is_file() and not p.is_symlink():
            with p.open("rb") as f:
                if f.read(4) != ELF_MAGIC:
                    continue
            if best is None or p.stat().st_size > best.stat().st_size:
                best = p
    return best


def protos(binary, name):
    out = ROOT / "analysis" / "protos" / name
    run(sys.executable, "-I", str(ROOT / "tools" / "extract_protos.py"), str(binary), str(out))
    files = sorted(str(p.relative_to(out)) for p in out.rglob("*.proto"))
    py = ROOT / "build" / "py" / name
    py.mkdir(parents=True, exist_ok=True)
    run(sys.executable, "-m", "grpc_tools.protoc", "-I.", f"--python_out={py}", *files, cwd=out)
    print(f"  {len(files)} protos -> analysis/protos/{name}, build/py/{name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zips", nargs="*", type=Path, help="update ZIPs saved with Korg's tools")
    ap.add_argument("--no-updater", action="store_true", help="skip schemas from the Korg System Updater app")
    args = ap.parse_args()
    if not args.zips and args.no_updater:
        ap.error("nothing to do")

    for z in args.zips:
        name, rootfs = verify_and_unpack(z.expanduser())
        b = main_binary(rootfs)
        if b is None:
            print(f"  no ELF under {rootfs}/Korg; skipping schemas")
            continue
        print(f"  main binary: {b.relative_to(rootfs)}")
        protos(b, name)

    if not args.no_updater:
        if UPDATER_BIN.exists():
            plist = (UPDATER_APP / "Contents/Info.plist").read_text(errors="replace")
            m = re.search(r"CFBundleShortVersionString</key>\s*<string>([^<]+)", plist)
            protos(UPDATER_BIN, set_name("system_updater", m.group(1) if m else "unknown"))
        else:
            print(f"Korg System Updater not found at {UPDATER_APP}; skipping its schemas")


if __name__ == "__main__":
    main()
