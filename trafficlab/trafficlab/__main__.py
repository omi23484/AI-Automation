"""CLI:  python3 -m trafficlab <command>
  serve                       start local UI (127.0.0.1:8765)
  synth  --out DIR            write SYNTHETIC_* files
  analyze FILE (--mapping M.json | --preset NAME) [--tz UTC] [--formats F1,F2] [--inventory inv.csv] [--cr crs.json] [--config c.json] --out DIR
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
    s = sub.add_parser("analyze"); s.add_argument("file"); s.add_argument("--mapping"); s.add_argument("--preset", help="nexus_collect_utilization | nexus_collect_errors"); s.add_argument("--tz", default="UTC")
    s.add_argument("--formats", default=None, help="comma separated strptime formats, or epoch_s / epoch_ms")
    s.add_argument("--delimiter", default=","); s.add_argument("--inventory"); s.add_argument("--cr"); s.add_argument("--config"); s.add_argument("--out", default="out")
    s.add_argument("--workers", type=int, default=None)
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
        from .config import make_config
        from .store import CRStore
        text = open(a.file, newline="", encoding="utf-8-sig").read()
        from .presets import PRESETS
        if a.preset:
            pr = PRESETS[a.preset]
            mapping = pr["mapping"]
            if not a.formats:
                a.formats = ",".join(pr["ts_formats"])
        elif a.mapping:
            mapping = json.load(open(a.mapping))
        else:
            ap.error("analyze needs --mapping or --preset")
        inv = ingest.load_inventory(open(a.inventory).read()) if a.inventory else None
        cfg = make_config(json.load(open(a.config)) if a.config else None)
        ds = ingest.load_csv(text, mapping, a.formats.split(",") if a.formats else None, a.tz, a.delimiter, inv, a.file)
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
    elif a.cmd == "test":
        import unittest
        here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")
        r = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(here))
        sys.exit(0 if r.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
