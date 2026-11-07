"""Orchestrates analysis. Engine modules have no DOM / no I/O. Parallel per series."""
import os
import time
from concurrent.futures import ProcessPoolExecutor

from .config import make_config, cfg_for_zone
from .stats import percentile_sorted
from .anomaly import detect
from .changepoint import detect_shifts
from .correlate import correlate
from .crmatch import match
from .interpret import interpret, mark_continuations


def _summ(s):
    r = sorted(s.rate)
    d = {"key": s.key, "device": s.device, "interface": s.interface, "zone": s.zone, "metric": s.metric, "unit": s.unit,
         "n_samples": s.n_samples, "n_points": len(r), "interval_s": (s.interval_ms / 1000.0 if s.interval_ms else None),
         "speed_bps": s.speed_bps, "excluded": len(s.excluded), "events": len(s.events), "notes": s.notes,
         "first_ts_raw": s.ts_raw[0] if s.ts_raw else None, "last_ts_raw": s.ts_raw[-1] if s.ts_raw else None,
         "methods": {m: s.method.count(m) for m in set(s.method)}}
    if r:
        d.update(mean=sum(r) / len(r), p50=percentile_sorted(r, 50), p95=percentile_sorted(r, 95),
                 p99=percentile_sorted(r, 99), max=r[-1], min=r[0])
        if s.speed_bps and s.unit == "bps":
            d["util_p95_pct"] = 100.0 * d["p95"] / s.speed_bps
            d["util_max_pct"] = 100.0 * r[-1] / s.speed_bps
    return d


def _work(args):
    s, cfg = args
    eff = cfg_for_zone(cfg, s.zone)
    t = time.time()
    an, summ, resid = detect(s, eff)
    sh, shst = detect_shifts(s, eff)
    out = _summ(s)
    out.update(baseline=summ, shift_status=shst, tz_used=eff["tz"], secs=round(time.time() - t, 3))
    return an + sh, out, resid


def analyze(series_list, cfg=None, store=None, workers=None, progress=None):
    cfg = cfg or make_config()
    crs = store.list() if store else []
    t0 = time.time()
    results = []
    workers = workers if workers is not None else min(4, os.cpu_count() or 1)
    jobs = [(s, cfg) for s in series_list]
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, r in enumerate(ex.map(_work, jobs, chunksize=max(1, len(jobs) // (workers * 4)))):
                results.append(r)
                if progress:
                    progress(i + 1, len(jobs))
    else:
        for i, j in enumerate(jobs):
            results.append(_work(j))
            if progress:
                progress(i + 1, len(jobs))
    findings, sums, resid = [], [], {}
    for f, s, r in results:
        findings += f
        sums.append(s)
        resid.update(r)
    smap = {s.key: s for s in series_list}
    intervals = {s.key: s.interval_ms for s in series_list}
    mark_continuations(findings, cfg["interpret"]["shift_followup_days"])
    clusters = correlate(findings, resid, intervals, cfg)
    by_member = {m: c for c in clusters for m in c["members"]}
    cl_by_id = {c["id"]: c for c in clusters}
    la = cfg["cr"]["lookahead_h"]
    for f in findings:
        fw = f["window"]
        if f["kind"] == "pattern_shift":   # shift time resolution is 1 h bucket -> match with +/-1h uncertainty
            fw = {"start_ms": fw["start_ms"] - 3_600_000, "end_ms": fw["end_ms"] + 3_600_000}
        f["cr_candidates"] = match(fw, [(f["device"], f["interface"])], crs, la)
        f["interpretation"] = interpret(f, smap.get(f["series_key"]), by_member)
        f["interpretation_layer"] = "interpretation (rule-based, candidate only)"
        cl = by_member.get(f["id"])
        f["cluster_id"] = cl["id"] if cl else None
    for c in clusters:
        mem = [f for f in findings if f["id"] in c["members"]]
        devs = [(f["device"], f["interface"]) for f in mem]
        c["cr_candidates"] = match(c["window"], devs, crs, la)
    sev = {"high": 3, "medium": 2, "low": 1}
    findings.sort(key=lambda f: (-sev[f["severity"]], f["window"]["start_ms"]))
    return {"config": cfg, "findings": findings, "clusters": clusters, "series": sums,
            "elapsed_s": round(time.time() - t0, 3), "workers": workers}


def validation_report(ds, series, dq):
    """Validation shown BEFORE analysis. Facts only; severity = how much it affects analysis."""
    from .ingest import ts_report
    tr = ts_report(ds)
    issues = []
    def add(sev, msg):
        issues.append({"severity": sev, "message": msg})
    flags = tr["flag_counts"]
    n_unp = flags.get("unparseable", 0) + flags.get("empty", 0)
    if n_unp:
        add("error", f"{n_unp} rows have unparseable timestamps: kept in raw, EXCLUDED from analysis (see list)")
    for k, lab in (("dst_ambiguous", "ambiguous (DST fall-back)"), ("dst_nonexistent", "nonexistent (DST spring-forward)")):
        if flags.get(k):
            add("error", f"{flags[k]} rows have {lab} local times under tz {ds.tz}: not guessed, EXCLUDED. Export with UTC/offset or fix tz")
    bad = {k: v for k, v in flags.items() if k.startswith("bad_value") or k in ("column_count_mismatch", "missing_device_or_interface")}
    for k, v in bad.items():
        add("warn", f"{v} rows flagged '{k}'")
    if tr["mixed_formats"]:
        add("warn", f"mixed timestamp formats: {tr['formats']}")
    n_assumed = tr["tz_sources"].get("assumed", 0)
    if n_assumed:
        add("warn", f"timezone ASSUMED = {ds.tz} for {n_assumed} rows with no offset in the string (confirm this)")
    if dq["duplicates"]:
        add("warn", f"{len(dq['duplicates'])} duplicate rows (identical): first kept in derived data")
    if dq["conflicts"]:
        add("error", f"{len(dq['conflicts'])} timestamps with CONFLICTING values: all such rows dropped from derived data")
    if dq["out_of_order"]:
        add("warn", f"{dq['out_of_order']} rows out of time order (sorted in derived copy)")
    ex, ev = {}, {}
    for s in series:
        for e in s.excluded:
            ex[e["type"]] = ex.get(e["type"], 0) + 1
        for e in s.events:
            ev[e["type"]] = ev.get(e["type"], 0) + 1
        for n in s.notes:
            add("warn", f"{s.key}: {n}")
    for k, v in ex.items():
        add("warn", f"{v} intervals excluded as '{k}' (marked as gaps, never filled)")
    for k, v in ev.items():
        add("info", f"{v} '{k}' events (rates kept; see per-interval method)")
    add("info", f"{len(series)} series from {len(ds.rows)} raw rows; raw rows are immutable, all transforms are derived copies")
    return {"source": ds.source, "rows": len(ds.rows), "series_count": len(series), "timestamps": tr, "data_quality": dq,
            "excluded_by_type": ex, "events_by_type": ev, "issues": issues,
            "series": [{"key": s.key, "zone": s.zone, "samples": s.n_samples, "points": len(s.rate), "interval_s": (s.interval_ms or 0) / 1000.0,
                        "excluded": len(s.excluded), "speed_bps": s.speed_bps} for s in series]}
