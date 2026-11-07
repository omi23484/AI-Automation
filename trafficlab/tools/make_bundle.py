"""Build a customer delivery bundle: code + chosen tier + chosen profile + docs, with a SHA-256 manifest.
Usage: python3 tools/make_bundle.py --tier medium --name acme [--profile profiles/acme.json] [--out dist]
Excludes tests, tools, captures, databases. `python3 -m trafficlab verify` inside the bundle checks the manifest
(accident / casual-tamper evidence only; see tier.py)."""
import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from trafficlab import tier as tier_mod, profile as profile_mod, __version__


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", required=True)
    ap.add_argument("--name", required=True, help="delivery label used in the file name (no spaces)")
    ap.add_argument("--profile")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--final", action="store_true", help="mark the tier as final (clears the 'proposal' flag in the delivered tier.json)")
    a = ap.parse_args(argv)
    t = tier_mod.load(a.tier)
    tobj = dict(t.raw)
    if a.final:
        tobj["proposal"] = False
    elif tobj.get("proposal"):
        print("WARNING: tier is still a PROPOSAL; the delivered banner will say so (use --final once the owner has dictated the numbers).")
    prof = None
    if a.profile:
        prof = json.load(open(a.profile))
        profile_mod.load(prof)                         # refuse to ship an invalid profile
    stage = os.path.join(a.out, f"trafficlab-{a.name}-{t.name}")
    if os.path.exists(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc", "*.db")
    shutil.copytree(os.path.join(ROOT, "trafficlab"), os.path.join(stage, "trafficlab"), ignore=ign)
    shutil.copytree(os.path.join(ROOT, "docs"), os.path.join(stage, "docs"), ignore=shutil.ignore_patterns("DEVELOPMENT-NOTES.md"))
    os.makedirs(os.path.join(stage, "profiles"))
    shutil.copy(os.path.join(ROOT, "profiles", "example-neutral.json"), os.path.join(stage, "profiles"))
    if prof is not None:
        shutil.copy(a.profile, os.path.join(stage, "profiles", "active-profile.json"))
    json.dump(tobj, open(os.path.join(stage, "tier.json"), "w"), indent=2)
    open(os.path.join(stage, "README-FIRST.txt"), "w").write(
        f"trafficlab {__version__} - delivery '{a.name}', tier '{t.name}'\n\nRequires Python 3.10+ (standard library only). Offline; binds to 127.0.0.1 only.\n\n"
        "  python3 -m trafficlab serve                 # UI at http://127.0.0.1:8765/\n"
        "  python3 -m trafficlab tier show             # your tier's limits and features\n"
        "  python3 -m trafficlab verify                # check files against MANIFEST.sha256\n"
        + ("  (a customised profile is in profiles/active-profile.json: load it on the Import tab, or pass --profile to the CLI commands)\n" if prof is not None else "") +
        "\nLimits (tier.json):\n" + json.dumps(tobj.get("limits", {}), indent=2) + "\n\nFeatures not included: " +
        (", ".join(k for k, v in tobj.get("features", {}).items() if not v) or "none") +
        "\n\nNo authentication: run one instance per user. Treat the CR database (trafficlab.db) and exports as customer data.\n"
        "Tier limits are enforced in software and are visible, but this is not tamper-proof.\n")
    files = []
    for root, _, names in os.walk(stage):
        for n in sorted(names):
            fp = os.path.join(root, n)
            files.append(os.path.relpath(fp, stage).replace(os.sep, "/"))
    with open(os.path.join(stage, "MANIFEST.sha256"), "w") as m:
        for rel in sorted(files):
            m.write(f"{hashlib.sha256(open(os.path.join(stage, rel), 'rb').read()).hexdigest()}  {rel}\n")
    zp = stage + ".zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, names in os.walk(stage):
            for n in sorted(names):
                fp = os.path.join(root, n)
                z.write(fp, os.path.join(os.path.basename(stage), os.path.relpath(fp, stage)))
    print(f"{zp}  sha256={hashlib.sha256(open(zp, 'rb').read()).hexdigest()}  files={len(files) + 1}")
    return zp


if __name__ == "__main__":
    main()
