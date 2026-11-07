"""Module 2b: pattern-shift (level change) detection.
Method: hourly mean series -> remove seasonal profile (median per weekday+hour if span>=21d,
else per hour if span>=5d, else REFUSE) -> binary segmentation on mean shift.
Test statistic t = |m2-m1| / (sigma_d * sqrt((1/n1+1/n2)*(1+rho)/(1-rho)^2)),
sigma_d = 1.4826*MAD(first differences)/sqrt(2); rho = lag-1 autocorr of within-segment
residuals (AR(1) long-run-variance adjustment). t is a HEURISTIC score, NOT a calibrated p-value."""
import bisect
import math
from collections import defaultdict
from datetime import datetime

from .stats import median, mad, mean, variance, MAD_SCALE
from .timeparse import get_tz
from .anomaly import fid, window
from .config import floor_abs

H_MS = 3_600_000


def _hourly(s, minpts):
    b = defaultdict(lambda: [0.0, 0])
    for t, r in zip(s.ts_ms, s.rate):
        x = b[t // H_MS]
        x[0] += r
        x[1] += 1
    hs = sorted(h for h, (sm, n) in b.items() if n >= minpts)
    return hs, [b[h][0] / b[h][1] for h in hs]


def _rho(r, lo, hi, k):
    num = den = 0.0
    for a, b in ((lo, k), (k, hi)):
        m = mean(r[a:b])
        seg = [x - m for x in r[a:b]]
        num += sum(seg[i] * seg[i - 1] for i in range(1, len(seg)))
        den += sum(x * x for x in seg)
    return 0.0 if den == 0 else max(0.0, min(0.95, num / den))


def _split(r, P, lo, hi, minseg, fabs):
    n = hi - lo
    if n < 2 * minseg:
        return None
    d = [r[i] - r[i - 1] for i in range(lo + 1, hi)]
    sd = max(MAD_SCALE * mad(d) / math.sqrt(2), fabs)
    best, bk = -1.0, None
    for k in range(lo + minseg, hi - minseg + 1):
        n1, n2 = k - lo, hi - k
        m1, m2 = (P[k] - P[lo]) / n1, (P[hi] - P[k]) / n2
        t = abs(m2 - m1) / (sd * math.sqrt(1 / n1 + 1 / n2))
        if t > best:
            best, bk = t, k
    n1, n2 = bk - lo, hi - bk
    rho = _rho(r, lo, hi, bk)
    m1, m2 = (P[bk] - P[lo]) / n1, (P[hi] - P[bk]) / n2
    se = sd * math.sqrt((1 / n1 + 1 / n2) * (1 + rho) / (1 - rho) ** 2)
    return {"k": bk, "t": abs(m2 - m1) / se, "sigma_d": sd, "rho": rho, "m1": m1, "m2": m2}


def detect_shifts(s, cfg):
    cc, bcfg = cfg["changepoint"], cfg["baseline"]
    st = {"status": "ok", "reason": None}
    if not cc["enabled"] or not s.interval_ms or len(s.rate) < 50:
        st.update(status="skipped", reason="disabled or too few points")
        return [], st
    tz = get_tz(cfg["tz"])
    exp = 3_600_000 / s.interval_ms
    hs, M = _hourly(s, max(1, int(cc["min_coverage"] * exp)))
    if len(hs) < 2 * cc["min_segment_hours"]:
        st.update(status="insufficient_history", reason=f"{len(hs)} usable hourly buckets")
        return [], st
    span_d = (hs[-1] - hs[0]) / 24.0
    keys = []
    for h in hs:
        d = datetime.fromtimestamp(h * 3600, tz)
        keys.append((d.weekday(), d.hour))
    if span_d >= cc["min_span_days_dow"]:
        g, gh = defaultdict(list), defaultdict(list)
        for k, m in zip(keys, M):
            g[k].append(m)
            gh[k[1]].append(m)
        prof = [median(g[k]) if len(g[k]) >= 3 else median(gh[k[1]]) for k in keys]
        mode = "dow_hour"
    elif span_d >= cc["min_span_days_hour"]:
        gh = defaultdict(list)
        for k, m in zip(keys, M):
            gh[k[1]].append(m)
        prof = [median(gh[k[1]]) for k in keys]
        mode = "hour_of_day"
    else:
        st.update(status="insufficient_history", reason=f"span {span_d:.1f}d < {cc['min_span_days_hour']}d; cannot remove daily cycle, refusing")
        return [], st
    r = [m - p for m, p in zip(M, prof)]
    P = [0.0]
    for x in r:
        P.append(P[-1] + x)
    fabs = floor_abs(bcfg, s.unit)
    cps = []
    stack = [(0, len(r), 0)]
    while stack:
        lo, hi, depth = stack.pop()
        sp = _split(r, P, lo, hi, cc["min_segment_hours"], fabs)
        if not sp or sp["t"] < cc["stat_threshold"]:
            continue
        eff = abs(sp["m2"] - sp["m1"])
        ref = abs(mean(M[lo:sp["k"]]))
        if eff < cc["min_effect_sigma"] * sp["sigma_d"] or (ref > 0 and eff / ref < cc["min_effect_rel"]):
            continue
        # robustness: segment MEDIANS of the residual must move too (a short burst must not look like a level shift)
        if abs(median(r[sp["k"]:hi]) - median(r[lo:sp["k"]])) < cc["min_effect_sigma"] * sp["sigma_d"]:
            continue
        cps.append(dict(sp, lo=lo, hi=hi))
        if len(cps) >= cc["max_changepoints"] * 3:
            break
        stack += [(lo, sp["k"], depth + 1), (sp["k"], hi, depth + 1)]
    cps.sort(key=lambda c: -c["t"])
    cps = sorted(cps[: cc["max_changepoints"]], key=lambda c: c["k"])
    st.update(profile=mode, span_days=round(span_d, 2), hourly_buckets=len(hs))
    findings = []
    bounds = [hs[0] * H_MS] + [hs[c["k"]] * H_MS for c in cps] + [s.ts_ms[-1] + 1]
    for n, c in enumerate(cps):
        cp_ms = hs[c["k"]] * H_MS
        a, b = bounds[n], bounds[n + 1 + 1] if n + 2 < len(bounds) else bounds[-1]
        i_a, i_cp, i_b = bisect.bisect_left(s.ts_ms, a), bisect.bisect_left(s.ts_ms, cp_ms), bisect.bisect_left(s.ts_ms, b)
        before, after = s.rate[i_a:i_cp], s.rate[i_cp:i_b]
        if len(before) < 2 or len(after) < 2 or i_cp >= len(s.ts_ms):
            continue
        mb, ma = mean(before), mean(after)
        rel = (ma - mb) / mb if mb else None
        pc = abs(rel) if rel is not None else 0
        sev = "high" if pc >= 0.5 else "medium" if pc >= 0.2 else "low"
        if c["t"] >= 2 * cc["stat_threshold"] and len(before) >= 72 and len(after) >= 72:
            lvl, why = "high", "stat >= 2x threshold; both segments >= 72 samples"
        elif c["t"] >= cc["stat_threshold"]:
            lvl, why = "medium", "stat above threshold; AR(1)-adjusted but not a calibrated p-value"
        else:
            lvl, why = "low", "n/a"
        if mode == "hour_of_day":
            lvl, why = "low", "daily profile only (weekly pattern not removed); weekday/weekend cycle can mimic a shift"
        w = window(s, i_cp, i_cp)
        findings.append({
            "id": fid("shift", s.key, cp_ms, cp_ms), "layer": "statistical", "kind": "pattern_shift",
            "metric": s.metric, "unit": s.unit, "device": s.device, "interface": s.interface, "zone": s.zone,
            "series_key": s.key, "window": w, "direction": "up" if ma > mb else "down", "severity": sev,
            "methods": ["binary_segmentation_mean_shift"],
            "math": [{"method": "binary_segmentation_mean_shift",
                      "formula": "hourly mean -> minus seasonal profile -> t=|m2-m1|/(sigma_d*sqrt((1/n1+1/n2)*(1+rho)/(1-rho)^2)); sigma_d=1.4826*MAD(diff)/sqrt2",
                      "params": {"profile": mode, "stat_threshold": cc["stat_threshold"], "min_effect_sigma": cc["min_effect_sigma"],
                                 "min_effect_rel": cc["min_effect_rel"], "min_segment_hours": cc["min_segment_hours"],
                                 "shift_resolution": "1 hour bucket (start of first 'after' hour)"}}],
            "numbers": {"t_stat": round(c["t"], 2), "sigma_d": round(c["sigma_d"], 3), "rho": round(c["rho"], 3),
                        "resid_mean_before": round(c["m1"], 3), "resid_mean_after": round(c["m2"], 3),
                        "raw_mean_before": round(mb, 3), "raw_mean_after": round(ma, 3),
                        "raw_var_before": variance(before), "raw_var_after": variance(after),
                        "n_before": len(before), "n_after": len(after), "change_pct": round(100 * rel, 1) if rel is not None else None,
                        "before_window_start_raw": s.ts_raw[i_a] if i_a < len(s.ts_raw) else None,
                        "after_window_end_raw": s.ts_raw[min(i_b, len(s.ts_raw)) - 1]},
            "confidence": {"level": lvl, "justification": why},
            "interpretation": [], "cr_candidates": [],
        })
    return findings, st
