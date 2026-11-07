"""CLI:  python3 -m trafficlab <command>
  serve                       start local UI (127.0.0.1:8765)
  synth  --out DIR            write SYNTHETIC_* files
  analyze FILE (--mapping M.json | --preset NAME) [--tz UTC] [--formats F1,F2] [--inventory inv.csv] [--cr crs.json] [--config c.json] --out DIR
  weekly PATH... [--tz Z] [--overrides o.json] --out DIR   week-over-week mode on weekly .xlsx/.csv exports
  devcheck PATH [--config c.json] --out DIR   rule-based checks on show captures (folder or .zip)
  test                        run unit tests"""
import argparse
import json
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="trafficlab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8765); s.add_argument("--db", default="trafficlab.db")
    s = sub.add_parser("synth"); s.add_argument("--out", default="synthetic"); s.add_argument("--days", type=int, default=35)
    s.add_argument("--seed", type=int, default=42); s.add_argument("--mixed-formats", action="store_true")
    s = sub.add_parser("analyze"); s.add_argument("file"); s.add_argument("--mapping"); s.add_argument("--preset", help="nexus_collect_utilization | nexus_collect_errors"); s.add_argument("--tz", default=None, help="default UTC, or the profile's import.tz")
    s.add_argument("--formats", default=None, help="comma separated strptime formats, or epoch_s / epoch_ms")
    s.add_argument("--delimiter", default=","); s.add_argument("--inventory"); s.add_argument("--cr"); s.add_argument("--config"); s.add_argument("--out", default="out")
    s.add_argument("--workers", type=int, default=None); s.add_argument("--profile", help="environment profile JSON (see docs/ADAPTING.md)")
    s = sub.add_parser("devcheck", help="Module 4: rule-based checks on raw show captures (dir or .zip)")
    s.add_argument("path"); s.add_argument("--pass-policy", default="latest", choices=["latest", "all"]); s.add_argument("--config"); s.add_argument("--out", default="out"); s.add_argument("--profile")
    s = sub.add_parser("weekly", help="week-over-week mode on aggregated weekly .xlsx/.csv exports (folder or files)")
    s.add_argument("paths", nargs="+"); s.add_argument("--tz", default=None, help="default UTC, or the profile's import.tz"); s.add_argument("--overrides", help="JSON {file name: 'YYYY-MM-DD' (Monday of covered week)}")
    s.add_argument("--config"); s.add_argument("--cr"); s.add_argument("--out", default="out"); s.add_argument("--profile")
    sub.add_parser("test")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        from .server import serve
        serve(port=a.port, db=a.db)
    elif a.cmd == "synth":
        from . import synth
        p = synth.write(a.out, days=a.days, seed=a.seed, mixed_formats=a.mixed_formats)
        print("wrote", p, "(+ SYNTHETIC_manifest.json, SYNTHETIC_crs.json). ALL DATA IS FAKE.")
    elif a.cmd == "analyze":
        from . import ingest, counters, pipeline, report
        from .store import CRStore
        from . import profile as pm
        prof = pm.load(json.load(open(a.profile))) if a.profile else None
        imp = pm.import_defaults(prof)
        text = open(a.file, newline="", encoding="utf-8-sig").read()
        presets = pm.all_presets(prof)
        if a.preset:
            pr = presets[a.preset]
            mapping = pr["mapping"]
            if not a.formats and pr.get("ts_formats"):
                a.formats = ",".join(pr["ts_formats"])
        elif a.mapping:
            mapping = json.load(open(a.mapping))
        elif imp.get("mapping"):
            mapping = imp["mapping"]
            if not a.formats and imp.get("ts_formats"):
                a.formats = ",".join(imp["ts_formats"])
        else:
            ap.error("analyze needs --mapping, --preset, or a --profile with import.mapping/import.preset")
        a.tz = a.tz or imp.get("tz") or "UTC"
        inv = ingest.load_inventory(open(a.inventory).read()) if a.inventory else None
        cfg = pm.effective_config(prof, json.load(open(a.config)) if a.config else None)
        ds = ingest.load_csv(text, mapping, a.formats.split(",") if a.formats else None, a.tz, a.delimiter, inv, a.file, zone_map=cfg.get("zone_map"))
        series, dq = counters.build_all(ds, cfg)
        val = pipeline.validation_report(ds, series, dq)
        for i in val["issues"]:
            print(f"[{i['severity']}] {i['message']}")
        st = CRStore()
        if a.cr:
            st.import_json(json.load(open(a.cr)))
        res = pipeline.analyze(series, cfg, st, a.workers)
        os.makedirs(a.out, exist_ok=True)
        json.dump({"format": "trafficlab-findings/1", "validation": val, "result": res}, open(os.path.join(a.out, "findings.json"), "w"), indent=1)
        open(os.path.join(a.out, "report.html"), "w", encoding="utf-8").write(report.build_report(res, val, {s.key: s for s in series}))
        prim = [f for f in res["findings"] if not f.get("continuation_of")]
        print(f"{len(res['findings'])} findings ({len(prim)} primary), {len(res['clusters'])} clusters, {res['elapsed_s']}s -> {a.out}/")
    elif a.cmd == "weekly":
        from . import weekly, report, profile as pm
        from .store import CRStore
        prof = pm.load(json.load(open(a.profile))) if a.profile else None
        a.tz = a.tz or pm.import_defaults(prof).get("tz") or "UTC"
        files = []
        for pth in a.paths:
            if os.path.isdir(pth):
                for root, _, names in os.walk(pth):
                    for n in sorted(names):
                        if n.lower().endswith((".xlsx", ".csv")):
                            fp = os.path.join(root, n)
                            files.append((os.path.relpath(fp, pth).replace(os.sep, "/"), open(fp, "rb").read()))
            else:
                files.append((os.path.basename(pth), open(pth, "rb").read()))
        cfg = pm.effective_config(prof, json.load(open(a.config)) if a.config else None)
        series, rep = weekly.build_series(files, cfg, a.tz, json.load(open(a.overrides)) if a.overrides else None)
        for i in rep["issues"]:
            print(f"[{i['severity']}] {i['message'][:200]}")
        st = CRStore()
        if a.cr:
            st.import_json(json.load(open(a.cr)))
        res = weekly.analyze_weekly(series, cfg, st)
        val = {"source": "weekly exports", "issues": rep["issues"], "timestamps": {"formats": {}, "tz_assumed": a.tz}}
        os.makedirs(a.out, exist_ok=True)
        json.dump({"format": "trafficlab-findings/1", "mode": "weekly", "validation": val, "weekly": rep, "result": res}, open(os.path.join(a.out, "findings.json"), "w"), indent=1)
        open(os.path.join(a.out, "report.html"), "w", encoding="utf-8").write(report.build_report(res, val, {x.key: x for x in series}))
        prim = [f for f in res["findings"] if not f.get("continuation_of")]
        print(f"{len(series)} series, {len(rep['weeks'])} weeks, {len(res['findings'])} findings ({len(prim)} primary), {len(res['clusters'])} clusters -> {a.out}/")
    elif a.cmd == "devcheck":
        from . import devcheck
        from .devcheck import report as dcr
        from . import profile as pm
        prof = pm.load(json.load(open(a.profile))) if a.profile else None
        cfg = pm.effective_config(prof, json.load(open(a.config)) if a.config else None)
        caps = devcheck.load_path(a.path, a.pass_policy)
        res = devcheck.analyze_captures(caps, cfg)
        os.makedirs(a.out, exist_ok=True)
        json.dump({"format": "trafficlab-devcheck/1", "result": res}, open(os.path.join(a.out, "devcheck.json"), "w"), indent=1)
        open(os.path.join(a.out, "devcheck.html"), "w", encoding="utf-8").write(dcr.build(res))
        sm = res["summary"]
        print(f"{sm['devices']} devices, {sm['captures']} captures, {sm['findings']} findings {sm['by_severity']} waived={sm['waived']} -> {a.out}/")
    elif a.cmd == "test":
        import unittest
        here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")
        r = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(here))
        sys.exit(0 if r.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
