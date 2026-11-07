# Packaging as a single executable

A customer needs **no Python**: one file, double-click (or run it) and the UI opens at `http://127.0.0.1:8765/`. With no arguments it starts the server and opens the browser.

## Build (on the OS you are targeting: PyInstaller cannot cross-compile)
```
pip install pyinstaller tzdata            # build machine only
python tools/build_exe.py --tier medium --final --out dist
python tools/smoke_exe.py dist/trafficlab-0.1.0-medium-linux-x86_64 --expect-tier medium
```
Output: `trafficlab-<version>-<tier|notier>-<os>-<arch>[.exe]` + `.sha256`. `--tier` bakes that tier in; `--final` clears its "proposal" flag.
Linux and Windows builds each need a machine of that OS. `.github/workflows/trafficlab-build.yml` builds both (manual or `trafficlab-v*` tag only).

## Status: what is verified
| | status |
|---|---|
| Linux x86_64 build (13.9 MB, built with PyInstaller 6.22.3 / Python 3.13) | **built and smoke-tested** (CLI, bundled UI assets, API, synthetic import, process-pool analysis with a non-UTC time zone, device checks, tier endpoint, report export), run with a stripped environment and no Python on PATH |
| Tier upgrade by dropping `tier.json` beside the executable (`tier install`) | **verified** on the Linux binary |
| Windows `.exe` | **NOT built or run by the author** (no Windows machine here). The code paths that differ on Windows are handled (tzdata bundled, `multiprocessing.freeze_support()`, `;` data separator) but unproven. Run the workflow and check the first result |
| macOS | not attempted |

## Things that differ per customer machine
- **Linux glibc**: a binary needs a glibc at least as new as the one it was built on. The one built here used glibc 2.39. For wider reach build on an older base (the workflow uses ubuntu-22.04; older still = an old container).
- **Windows time zones**: Windows has no system IANA database. `tzdata` is bundled so named zones (e.g. `Asia/Kolkata`) work; this is why `tzdata` is a build requirement.
- **Windows SmartScreen / antivirus** commonly flag unsigned PyInstaller executables. Code signing needs a certificate you own. Plan for it before shipping to Windows customers.
- **Files**: next to the executable: `tier.json` (overrides the baked tier), `trafficlab.db` (CR tracker; falls back to `~/.trafficlab/` if the folder is read-only), `MANIFEST` is not used for single files (use the `.sha256`).
- **Startup**: a one-file executable unpacks itself to a temp folder on each start; expect a few seconds of delay.

## Bundled components (build-time inputs; read from installed metadata, verify before commercial redistribution)
| component | version built with | licence field |
|---|---|---|
| PyInstaller | 6.22.3 | GPLv2-or-later with a special exception allowing it to build and distribute non-free (including commercial) programs |
| pyinstaller-hooks-contrib | 2026.9 | Apache Software License / GPLv2 (classifiers) |
| tzdata | 2026.6 | Apache-2.0 |
| altgraph | 0.17.5 | MIT |
| Python runtime | 3.13 | PSF licence |
trafficlab itself has no third-party runtime dependencies. It has no licence file yet: the owner must choose one.
