"""Module 2a: seasonal robust baseline, robust z-score, EWMA residual detection.
Deterministic, no DOM, no randomness. Findings are STATISTICAL (layer='statistical')."""
import bisect
import hashlib
from collections import defaultdict, deque
from datetime import datetime

from .stats import median, mad, MAD_SCALE
from .timeparse import get_tz, _to_ms
from .config import floor_abs


def fid(kind, key, start, end):
    return "F-" + hashlib.sha1(f"{kind}|{key}|{start}|{end}".encode()).hexdigest()[:10]


def seasonal_scores(s, bcfg, tz):
    """Causal baseline. For each hour-instance, baseline = median/MAD of pooled prior
    samples of the same (weekday,hour) over `lookback_weeks`; fallback = same hour-of-day
    over `fallback_days`; else insufficient history. Returns per-point lists."""
    n = len(s.rate)
    med = [None] * n
    scl = [None] * n
    z = [None] * n
    tier = [None] * n
    nin = [0] * n
    fabs = floor_abs(bcfg, s.unit)
    meta = []
    for t in s.ts_ms:
        d = datetime.fromtimestamp(t / 1000.0, tz)
        meta.append((d.toordinal(), d.hour, d.weekday()))
    h_dow = defaultdict(deque)
    h_dt = defaultdict(deque)
    h_hr = defaultdict(deque)
    lb = 7 * bcfg["lookback_weeks"]
    dtd = bcfg["daytype_days"]
    i = 0
    while i < n:
        o, hr, dw = meta[i]
        j = i
        while j < n and meta[j][0] == o and meta[j][1] == hr:
            j += 1
        pri = [e for e in h_dow[(dw, hr)] if 0 < o - e[0] <= lb]
        pool, tname = None, None
        if len(pri) >= bcfg["min_weeks"]:
            pool = [v for e in pri for v in e[1]]
            tname = "dow_hour"
            cnt = len(pri)
        else:
            dkey = (dw >= 5, hr)
            pr3 = [e for e in h_dt[dkey] if 0 < o - e[0] <= dtd]
            if len(pr3) >= bcfg["min_daytype"]:
                pool = [v for e in pr3 for v in e[1]]
                tname = "daytype_hour"
                cnt = len(pr3)
            elif bcfg["allow_hour_only_tier"]:
                pr2 = [e for e in h_hr[hr] if 0 < o - e[0] <= bcfg["fallback_days"]]
                if len(pr2) >= bcfg["min_days"]:
                    pool = [v for e in pr2 for v in e[1]]
                    tname = "hour_of_day"
                    cnt = len(pr2)
        if pool:
            m = median(pool)
            sc = max(MAD_SCALE * mad(pool, m), bcfg["scale_floor_rel"] * abs(m), fabs)
            for k in range(i, j):
                med[k], scl[k], z[k], tier[k], nin[k] = m, sc, (s.rate[k] - m) / sc, tname, cnt
        vals = s.rate[i:j]
        h_dow[(dw, hr)].append((o, vals))
        h_dt[(dw >= 5, hr)].append((o, vals))
        h_hr[hr].append((o, vals))
        dq = h_dow[(dw, hr)]
        while dq and o - dq[0][0] > lb:
            dq.popleft()
        dq = h_dt[(dw >= 5, hr)]
        while dq and o - dq[0][0] > dtd:
            dq.popleft()
        dq = h_hr[hr]
        while dq and o - dq[0][0] > bcfg["fallback_days"]:
            dq.popleft()
        i = j
    return med, scl, z, tier, nin


def ewma_on_z(z, ts_ms, gap_ms, acfg):
    """EWMA control chart on the seasonal robust z. S_t = lam*clip(z_t) + (1-lam)*S_{t-1}; S reset to 0
    after gaps / unscored points. Limit = L*sqrt(lam/(2-lam)) assumes ~unit-variance, independent z
    (an approximation: real z is autocorrelated, so treat as a heuristic). Catches SMALL SUSTAINED shifts."""
    lam, clip = acfg["ewma_lambda"], acfg["ewma_z_clip"]
    S = [None] * len(z)
    prev, prev_t = 0.0, None
    for i, v in enumerate(z):
        if v is None:
            prev, prev_t = 0.0, None
            continue
        if prev_t is not None and ts_ms[i] - prev_t > gap_ms:
            prev = 0.0
        prev = lam * max(-clip, min(clip, v)) + (1 - lam) * prev
        prev_t = ts_ms[i]
        S[i] = prev
    return S, acfg["ewma_L"] * (lam / (2 - lam)) ** 0.5


def _runs(idx, s, gap_ms, vals):
    """Consecutive flagged points; split on gaps AND on sign change of the score."""
    out, cur = [], []
    for i in idx:
        if cur and (i != cur[-1] + 1 or s.ts_ms[i] - s.ts_ms[cur[-1]] > gap_ms or (vals[i] > 0) != (vals[cur[-1]] > 0)):
            out.append(cur)
            cur = []
        cur.append(i)
    if cur:
        out.append(cur)
    return out


def _flag(vals, thr, direction):
    out = []
    for i, v in enumerate(vals):
        if v is None:
            continue
        if (direction in ("both", "high") and v >= thr) or (direction in ("both", "low") and v <= -thr):
            out.append(i)
    return out


def _sev(pz, acfg):
    return "high" if pz >= acfg["severity_high"] else "medium" if pz >= acfg["severity_medium"] else "low"


def detect(s, cfg):
    """Returns (findings, summary, resid) for one series. resid = {finding_id: [[ms, resid],..]}"""
    tz = get_tz(cfg["tz"])
    bcfg, acfg = cfg["baseline"], cfg["anomaly"]
    summary = {"tier_counts": {}, "scored_points": 0, "insufficient_points": 0, "ewma_limit": None}
    if len(s.rate) < 10 or not s.interval_ms:
        summary["status"] = "too_few_points"
        return [], summary, {}
    gap_ms = cfg["counters"]["gap_factor"] * s.interval_ms
    med, scl, z, tier, nin = seasonal_scores(s, bcfg, tz)
    for t in tier:
        k = t or "insufficient_history"
        summary["tier_counts"][k] = summary["tier_counts"].get(k, 0) + 1
    summary["scored_points"] = sum(1 for x in z if x is not None)
    summary["insufficient_points"] = len(z) - summary["scored_points"]
    cands = []
    for run in _runs(_flag(z, acfg["z_threshold"], acfg["direction"]), s, gap_ms, z):
        if len(run) < acfg["min_points"]:
            continue
        pk = max(run, key=lambda k: abs(z[k]))
        cands.append({"method": "seasonal_robust_z", "run": run, "peak": pk, "pz": abs(z[pk]),
                      "direction": "high" if z[pk] > 0 else "low",
                      "tiers": sorted({tier[k] for k in run}), "min_inst": min(nin[k] for k in run),
                      "base_med": median([med[k] for k in run]), "mean_val": sum(s.rate[k] for k in run) / len(run),
                      "mean_z": sum(z[k] for k in run) / len(run)})
    S, elimit = ewma_on_z(z, s.ts_ms, gap_ms, acfg)
    summary["ewma_limit"] = elimit
    for run in _runs(_flag(S, elimit, acfg["direction"]), s, gap_ms, S):
        if len(run) < acfg["ewma_min_points"]:
            continue
        pk = max(run, key=lambda k: abs(S[k]))
        cands.append({"method": "ewma_chart", "run": run, "peak": pk, "pz": abs(S[pk]) / (elimit / acfg["ewma_L"]),
                      "direction": "high" if S[pk] > 0 else "low", "tiers": sorted({tier[k] for k in run}), "min_inst": min(nin[k] for k in run),
                      "base_med": median([med[k] for k in run]), "mean_val": sum(s.rate[k] for k in run) / len(run),
                      "mean_z": sum(z[k] for k in run) / len(run), "peak_S": S[pk]})
    # merge overlapping windows
    # Window rule: where a seasonal-z run exists, ITS window is the finding window (the EWMA chart lags
    # and decays after an event, so it only corroborates). EWMA-only runs keep their own window.
    cands.sort(key=lambda c: (s.ts_ms[c["run"][0]], c["method"] != "seasonal_robust_z"))
    merged = []
    for c in cands:
        a, b = s.ts_ms[c["run"][0]], s.ts_ms[c["run"][-1]]
        hit = next((m for m in merged if a <= m["end"] and b >= m["start"]), None)
        if hit is None:
            merged.append({"start": a, "end": b, "cs": [c], "seasonal": c["method"] == "seasonal_robust_z"})
        elif hit["seasonal"] and c["method"] == "seasonal_robust_z":
            hit["start"], hit["end"] = min(hit["start"], a), max(hit["end"], b)
            hit["cs"].append(c)
        elif hit["seasonal"]:
            hit["cs"].append(c)           # corroborating EWMA, window unchanged
        else:                              # hit is EWMA-only so far
            hit["start"], hit["end"] = min(hit["start"], a), max(hit["end"], b)
            hit["cs"].append(c)
    findings, resid = [], {}
    pos = {t: i for i, t in enumerate(s.ts_ms)}
    for m in merged:
        cs = m["cs"]
        i0, i1 = pos[m["start"]], pos[m["end"]]
        first = next((c for c in cs if c["method"] == "seasonal_robust_z"), cs[0])
        pz = max(c["pz"] for c in cs)
        methods = sorted({c["method"] for c in cs})
        math, nums = [], {}
        for c in cs:
            if c["method"] == "seasonal_robust_z":
                math.append({"method": c["method"],
                             "formula": "z=(x-median_b)/max(1.4826*MAD_b, rel*|median_b|, abs_floor); flag |z|>=thr for >=min_points consecutive points",
                             "params": {"z_threshold": acfg["z_threshold"], "min_points": acfg["min_points"], "direction": acfg["direction"],
                                        "scale_floor_rel": bcfg["scale_floor_rel"], "scale_floor_abs": floor_abs(bcfg, s.unit), "baseline_tiers": c["tiers"]}})
                nums.update(seasonal_peak_abs_z=round(c["pz"], 3), seasonal_mean_z=round(c["mean_z"], 3),
                            baseline_median=round(c["base_med"], 3), mean_value=round(c["mean_val"], 3),
                            deviation_pct=(round(100 * (c["mean_val"] - c["base_med"]) / c["base_med"], 1) if c["base_med"] else None),
                            seasonal_points=len(c["run"]))
            else:
                math.append({"method": c["method"],
                             "formula": "S_t=lam*clip(z_t)+(1-lam)*S_{t-1}, S reset after gaps; flag |S_t|>=L*sqrt(lam/(2-lam)) for >=min_points",
                             "params": {"lambda": acfg["ewma_lambda"], "L": acfg["ewma_L"], "limit": round(elimit, 4),
                                        "z_clip": acfg["ewma_z_clip"], "min_points": acfg["ewma_min_points"]}})
                nums.update(ewma_peak_S=round(c["peak_S"], 3), ewma_points=len(c["run"]))
        fidv = fid("anomaly", s.key, m["start"], m["end"])
        # confidence
        both = len(methods) == 2
        dowh = any("dow_hour" in c["tiers"] for c in cs)
        if both and dowh and first["min_inst"] >= 4:
            lvl, why = "high", "both detectors agree; weekday+hour baseline with >=4 prior weeks"
        elif dowh and "seasonal_robust_z" in methods:
            lvl, why = "medium", "weekday+hour baseline" + ("; EWMA also agrees" if both else "; EWMA did not flag")
        elif "seasonal_robust_z" in methods and "daytype_hour" in {t for c in cs for t in c["tiers"]}:
            lvl, why = "low", "weekday/weekend+hour baseline (fewer than 3 same-weekday weeks)"
        elif "seasonal_robust_z" in methods:
            lvl, why = "low", "hour-of-day-only baseline (weekly pattern not modeled)"
        else:
            lvl, why = "low", "EWMA chart only (small sustained deviation); single-point z never reached threshold"
        w0, w1 = i0, i1
        mg = int((m["end"] - m["start"]) * cfg["correlation"]["margin_factor"]) + (s.interval_ms or 0)
        ka, kb = bisect.bisect_left(s.ts_ms, m["start"] - mg), bisect.bisect_right(s.ts_ms, m["end"] + mg)
        rs = [[s.ts_ms[k], s.rate[k] - med[k]] for k in range(ka, kb) if med[k] is not None]
        resid[fidv] = rs
        findings.append({
            "id": fidv, "layer": "statistical", "kind": "anomaly", "metric": s.metric, "unit": s.unit,
            "device": s.device, "interface": s.interface, "zone": s.zone, "series_key": s.key,
            "window": window(s, w0, w1), "direction": first["direction"], "severity": _sev(pz, acfg),
            "methods": methods, "math": math, "numbers": nums,
            "confidence": {"level": lvl, "justification": why},
            "interpretation": [], "cr_candidates": [],
        })
    return findings, summary, resid


def window(s, i0, i1):
    f0, f1 = s.ts_fmt[i0].rsplit("|", 1), s.ts_fmt[i1].rsplit("|", 1)
    return {"start_ms": s.ts_ms[i0], "end_ms": s.ts_ms[i1], "start_raw": s.ts_raw[i0], "end_raw": s.ts_raw[i1],
            "start_ts_parsed": {"epoch_ms": s.ts_ms[i0], "format": f0[0], "tz_assumed": s.tz_assumed, "tz_source": f0[1]},
            "end_ts_parsed": {"epoch_ms": s.ts_ms[i1], "format": f1[0], "tz_assumed": s.tz_assumed, "tz_source": f1[1]}}
