"""Build ONE single-file executable for the OS you run this on (PyInstaller cannot cross-compile:
build on Linux for Linux, on Windows for Windows).
Needs (build machine only): pip install pyinstaller tzdata
Usage: python3 tools/build_exe.py [--tier NAME|PATH] [--final] [--out dist] [--python PY]
The customer needs NO Python. tzdata is bundled (Windows has no system time-zone database)."""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from trafficlab import __version__, tier as tier_mod


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", help="bake a tier into the executable (a tier.json beside the exe still overrides it)")
    ap.add_argument("--final", action="store_true", help="clear the 'proposal' flag of the baked tier")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)
    osname = {"linux": "linux", "win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
    arch = platform.machine().lower() or "x64"
    label = "notier"
    sep = os.pathsep                                   # PyInstaller --add-data uses ':' on POSIX and ';' on Windows
    work = tempfile.mkdtemp(prefix="tl_build_")
    data = [f"{os.path.join(ROOT, 'trafficlab', 'web')}{sep}trafficlab/web", f"{os.path.join(ROOT, 'trafficlab', 'tiers')}{sep}trafficlab/tiers"]
    if a.tier:
        t = tier_mod.load(a.tier)
        raw = dict(t.raw)
        if a.final:
            raw["proposal"] = False
        elif raw.get("proposal"):
            print("WARNING: baked tier is still a PROPOSAL; its banner says so (use --final once the owner has dictated the numbers).")
        p = os.path.join(work, "tier.default.json")
        json.dump(raw, open(p, "w"), indent=2)
        data.append(f"{p}{sep}trafficlab")
        label = t.name
    name = f"trafficlab-{__version__}-{label}-{osname}-{arch}"
    cmd = [a.python, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", name, "--distpath", a.out, "--workpath", os.path.join(work, "build"),
           "--specpath", work, "--paths", ROOT, "--collect-data", "tzdata", "--hidden-import", "tzdata"]
    for d in data:
        cmd += ["--add-data", d]
    cmd.append(os.path.join(ROOT, "tools", "entry.py"))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("PyInstaller failed:\n" + r.stdout[-2000:] + r.stderr[-3000:])
    exe = os.path.join(a.out, name + (".exe" if sys.platform == "win32" else ""))
    h = hashlib.sha256(open(exe, "rb").read()).hexdigest()
    open(exe + ".sha256", "w").write(f"{h}  {os.path.basename(exe)}\n")
    shutil.rmtree(work, ignore_errors=True)
    print(f"{exe}  {os.path.getsize(exe) / 1e6:.1f} MB  sha256={h}")
    return exe


if __name__ == "__main__":
    main()
