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


def _apply_captures(a, res, cfg, outdir):
    """--captures PATH: run device checks on raw show captures, use their topology and findings as context (signature library, CDP/LLDP links)."""
    if not getattr(a, "captures", None):
        return
    from . import devcheck, context
    from .devcheck import report as dcr
    checks = devcheck.analyze_captures(devcheck.load_path(a.captures), cfg)
    context.apply(res, checks, cfg)
    json.dump({"format": "trafficlab-devcheck/1", "result": checks}, open(os.path.join(outdir, "devcheck.json"), "w"), indent=1)
    open(os.path.join(outdir, "devcheck.html"), "w", encoding="utf-8").write(dcr.build(checks))
    kb = sum(1 for f in res["findings"] for i in f["interpretation"] if str(i.get("rule")).startswith("KB:"))
    print(f"device checks: {checks['summary']['findings']} findings, {len(checks['topology']['links'])} links; signature matches: {kb}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="trafficlab")
    ap.add_argument("--tier", help="tier name or JSON path (else env TRAFFICLAB_TIER, else tier.json next to the package, else no limits)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8765); s.add_argument("--db", default=None, help="CR database (default: beside the app, else ~/.trafficlab)")
    s.add_argument("--open", action="store_true", help="open the UI in the default browser")
    s = sub.add_parser("synth"); s.add_argument("--out", default="synthetic"); s.add_argument("--days", type=int, default=35)
    s.add_argument("--seed", type=int, default=42); s.add_argument("--mixed-formats", action="store_true")
    s = sub.add_parser("analyze"); s.add_argument("file"); s.add_argument("--mapping"); s.add_argument("--preset", help="nexus_collect_utilization | nexus_collect_errors"); s.add_argument("--tz", default=None, help="default UTC, or the profile's import.tz")
    s.add_argument("--formats", default=None, help="comma separated strptime formats, or epoch_s / epoch_ms")
    s.add_argument("--delimiter", default=","); s.add_argument("--inventory"); s.add_argument("--cr"); s.add_argument("--config"); s.add_argument("--out", default="out")
    s.add_argument("--workers", type=int, default=None); s.add_argument("--profile", help="environment profile JSON (see docs/ADAPTING.md)"); s.add_argument("--captures", help="folder/zip of raw show captures: adds topology + device-check context")
    s = sub.add_parser("devcheck", help="Module 4: rule-based checks on raw show captures (dir or .zip)")
    s.add_argument("path"); s.add_argument("--pass-policy", default="latest", choices=["latest", "all"]); s.add_argument("--config"); s.add_argument("--out", default="out"); s.add_argument("--profile")
    s = sub.add_parser("weekly", help="week-over-week mode on aggregated weekly .xlsx/.csv exports (folder or files)")
    s.add_argument("paths", nargs="+"); s.add_argument("--tz", default=None, help="default UTC, or the profile's import.tz"); s.add_argument("--overrides", help="JSON {file name: 'YYYY-MM-DD' (Monday of covered week)}")
    s.add_argument("--config"); s.add_argument("--cr"); s.add_argument("--out", default="out"); s.add_argument("--profile")
    s = sub.add_parser("history", help="persisted history: add | summary | analyze | retention (chunked imports, scored against everything stored)")
    s.add_argument("action", choices=["add", "summary", "analyze", "retention"]); s.add_argument("file", nargs="?", help="CSV for 'add'")
    s.add_argument("--db", required=True, help="SQLite file holding the history"); s.add_argument("--mapping"); s.add_argument("--preset"); s.add_argument("--profile")
    s.add_argument("--tz", default=None); s.add_argument("--formats"); s.add_argument("--delimiter", default=","); s.add_argument("--inventory"); s.add_argument("--config"); s.add_argument("--cr")
    s.add_argument("--window-days", type=float, default=None); s.add_argument("--captures"); s.add_argument("--days", type=float, default=None, help="retention days"); s.add_argument("--out", default="out"); s.add_argument("--workers", type=int, default=None)
    s = sub.add_parser("tier", help="tier definitions: list | show [NAME] | install FILE (upgrade = replace tier.json)"); s.add_argument("action", choices=["list", "show", "install"]); s.add_argument("name", nargs="?")
    sub.add_parser("verify", help="check this install against MANIFEST.sha256 (accident/tamper-evidence only)")
    sub.add_parser("test")
    a = ap.parse_args(argv if argv is not None else (sys.argv[1:] or ["serve", "--open"]))   # double-click / no arguments => start the UI
    from . import tier as tier_mod
    if a.cmd not in ("tier", "verify", "test"):
        tier_mod.activate(tier_mod.resolve(a.tier))
    if a.cmd == "serve":
        from .server import serve
        serve(port=a.port, db=a.db, tier_spec=a.tier, open_browser=a.open)
    elif a.cmd == "tier":
        if a.action == "install":
            if not a.name:
                sys.exit("usage: tier install FILE")
            t, dst = tier_mod.install(a.name)
            print(f"installed tier '{t.name}' -> {dst} (previous kept as tier.json.bak); restart to apply")
        elif a.action == "list":
            for n in ("small", "medium", "large"):
                t = tier_mod.load(n)
                print(f"{t.name:8} {'PROPOSAL ' if t.proposal else ''}limits={t.limits}")
            cur = tier_mod.resolve(a.tier)
            print("active:", (cur.name + " from " + cur.source) if cur else "none (no limits)")
        else:
            t = tier_mod.load(a.name) if a.name else tier_mod.resolve(a.tier)
            print(json.dumps(t.describe() if t else {"active": None}, indent=1))
    elif a.cmd == "verify":
        import hashlib
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        mf = os.path.join(here, "MANIFEST.sha256")
        if not os.path.isfile(mf):
            sys.exit("no MANIFEST.sha256 here (only delivered bundles have one)")
        want = dict(reversed(l.rstrip("\n").split("  ", 1)) for l in open(mf) if l.strip())
        bad, seen = [], set()
        for rel, h in want.items():
            fp = os.path.join(here, rel)
            seen.add(rel)
            if not os.path.isfile(fp):
                bad.append(f"MISSING  {rel}")
            elif hashlib.sha256(open(fp, "rb").read()).hexdigest() != h:
                bad.append(f"MODIFIED {rel}")
        for root, d, names in os.walk(here):
            d[:] = [x for x in d if x not in ("__pycache__",)]
            for n in names:
                rel = os.path.relpath(os.path.join(root, n), here).replace(os.sep, "/")
                if rel not in seen and rel != "MANIFEST.sha256" and not n.endswith((".db", ".pyc")):
                    bad.append(f"EXTRA    {rel}")
        print("\n".join(bad) if bad else f"OK: {len(want)} files match the manifest")
        sys.exit(1 if bad else 0)
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
        _apply_captures(a, res, cfg, a.out)
        json.dump({"format": "trafficlab-findings/1", "validation": val, "result": res}, open(os.path.join(a.out, "findings.json"), "w"), indent=1)
        open(os.path.join(a.out, "report.html"), "w", encoding="utf-8").write(report.build_report(res, val, {s.key: s for s in series}))
        prim = [f for f in res["findings"] if not f.get("continuation_of")]
        print(f"{len(res['findings'])} findings ({len(prim)} primary), {len(res['clusters'])} clusters, {res['elapsed_s']}s -> {a.out}/")
    elif a.cmd == "history":
        from . import ingest, counters, pipeline, report, profile as pm
        from .history import HistoryStore
        from .store import CRStore
        import hashlib
        prof = pm.load(json.load(open(a.profile))) if a.profile else None
        imp = pm.import_defaults(prof)
        cfg = pm.effective_config(prof, json.load(open(a.config)) if a.config else None)
        h = HistoryStore(a.db)
        if a.action == "summary":
            sm = h.summary()
            print(json.dumps({k: v for k, v in sm.items() if k != "batches"}, indent=1)); print("batches:", len(sm["batches"]))
        elif a.action == "retention":
            if a.days is None:
                ap.error("retention needs --days")
            print(h.apply_retention(a.days))
        elif a.action == "add":
            if not a.file:
                ap.error("add needs a CSV file")
            raw = open(a.file, "rb").read()
            text = raw.decode("utf-8-sig")
            presets = pm.all_presets(prof)
            mapping = presets[a.preset]["mapping"] if a.preset else json.load(open(a.mapping)) if a.mapping else imp.get("mapping")
            if mapping is None:
                ap.error("add needs --mapping, --preset or a profile with import.mapping")
            fm = a.formats or ",".join((presets[a.preset].get("ts_formats") if a.preset else imp.get("ts_formats")) or []) or None
            ds = ingest.load_csv(text, mapping, fm.split(",") if fm else None, a.tz or imp.get("tz") or "UTC", a.delimiter, ingest.load_inventory(open(a.inventory).read()) if a.inventory else None, a.file, zone_map=cfg.get("zone_map"))
            series, dq = counters.build_all(ds, cfg)
            for i in pipeline.validation_report(ds, series, dq)["issues"]:
                if i["severity"] != "info":
                    print(f"[{i['severity']}] {i['message']}")
            print(h.add_series(series, os.path.basename(a.file), hashlib.sha256(raw).hexdigest()))
        else:
            series = h.load_series(a.window_days)
            if not series:
                sys.exit("history is empty")
            st = CRStore()
            if a.cr:
                st.import_json(json.load(open(a.cr)))
            res = pipeline.analyze(series, cfg, st, a.workers)
            os.makedirs(a.out, exist_ok=True)
            _apply_captures(a, res, cfg, a.out)
            val = {"source": f"history {a.db}", "issues": [], "timestamps": {"formats": {}, "tz_assumed": cfg["tz"]}}
            os.makedirs(a.out, exist_ok=True)
            json.dump({"format": "trafficlab-findings/1", "mode": "history", "validation": val, "result": res}, open(os.path.join(a.out, "findings.json"), "w"), indent=1)
            open(os.path.join(a.out, "report.html"), "w", encoding="utf-8").write(report.build_report(res, val, {x.key: x for x in series}))
            prim = [f for f in res["findings"] if not f.get("continuation_of")]
            print(f"{len(series)} series, {len(res['findings'])} findings ({len(prim)} primary), {len(res['clusters'])} clusters -> {a.out}/")
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
        os.makedirs(a.out, exist_ok=True)
        _apply_captures(a, res, cfg, a.out)
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
    import multiprocessing
    multiprocessing.freeze_support()          # required for the process pool inside a frozen (PyInstaller) executable
    main()
