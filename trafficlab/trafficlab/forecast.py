"""Capacity outlook: robust linear trend of utilisation with time-to-threshold.
Method (all deterministic):
  y_t = daily p95 utilisation % of configured speed (poll mode) | weekly utilisation % (weekly mode)
  slope = Theil-Sen (median of pairwise slopes); band = Sen/Kendall rank interval at level alpha (normal approximation of S)
  trend present only if Mann-Kendall two-sided p < alpha AND slope > 0
  ETA(threshold) = (threshold - fitted_level_now) / slope
  fast/slow ETAs combine the slope band with +/-1 robust sigma (1.4826*MAD) of the daily scatter on the current level. This is a HEURISTIC range,
  not a calibrated confidence interval. The slow end is undefined if the slope band includes <= 0.
Limits: straight-line extrapolation only. Seasonality, step changes (new service, migration) and capacity upgrades are not modelled."""
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .stats import median, mad, percentile_sorted, MAD_SCALE
from .timeparse import get_tz

DAY_MS = 86_400_000


def mann_kendall(y):
    """-> (S, tau, z, p) with tie correction. p two-sided (normal approximation)."""
    n = len(y)
    S = sum((y[j] > y[i]) - (y[j] < y[i]) for i in range(n - 1) for j in range(i + 1, n))
    ties = defaultdict(int)
    for v in y:
        ties[v] += 1
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in ties.values())) / 18.0
    z = 0.0 if var <= 0 or S == 0 else (S - (1 if S > 0 else -1)) / math.sqrt(var)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return S, S / (n * (n - 1) / 2), z, p, var


def _zcrit(alpha):
    lo, hi = 0.0, 8.0          # bisection on the normal CDF: no external dependency
    for _ in range(60):
        mid = (lo + hi) / 2
        if 2 * (1 - 0.5 * (1 + math.erf(mid / math.sqrt(2)))) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def sen(t, y, alpha=0.05):
    """Theil-Sen slope with a rank-based band (Gilbert 1987 style). -> (slope, lo, hi, intercept)."""
    n = len(t)
    sl = sorted((y[j] - y[i]) / (t[j] - t[i]) for i in range(n - 1) for j in range(i + 1, n) if t[j] != t[i])
    N = len(sl)
    m = median(sl)
    _, _, _, _, var = mann_kendall(y)
    c = _zcrit(alpha) * math.sqrt(max(var, 0.0))
    lo_i = max(0, int(math.floor((N - c) / 2.0)))
    hi_i = min(N - 1, int(math.ceil((N + c) / 2.0)))
    return m, sl[lo_i], sl[hi_i], median([y[i] - m * t[i] for i in range(n)])


def _eta(level, slope, thr):
    if level >= thr:
        return 0.0
    return (thr - level) / slope if slope > 0 else None


def _daily_p95_pct(s, tz, min_cov):
    exp = 86_400_000 / s.interval_ms
    days = defaultdict(list)
    for t, r in zip(s.ts_ms, s.rate):
        d = datetime.fromtimestamp(t / 1000.0, tz)
        days[d.date()].append(r)
    out = []
    for d in sorted(days):
        v = days[d]
        if len(v) >= min_cov * exp:
            out.append((d, percentile_sorted(sorted(v), 95)))
    return out


def forecast_series(s, cfg):
    fc = cfg["forecast"]
    weekly = bool(s.interval_ms and s.interval_ms >= 6 * DAY_MS)
    if s.unit == "pct":
        scale = 1.0
    elif s.unit == "bps" and s.speed_bps:
        scale = 100.0 / s.speed_bps
    else:
        return None
    if weekly:
        pts = [(datetime.fromtimestamp(t / 1000.0, timezone.utc).date(), r) for t, r in zip(s.ts_ms, s.rate)]
        need, basis = fc["min_weeks"], "weekly value"
    else:
        if not s.interval_ms or len(s.rate) < 10:
            return None
        pts = _daily_p95_pct(s, get_tz(cfg["tz"]), fc["min_coverage"])
        need, basis = fc["min_days"], "daily p95"
    base = {"series_key": s.key, "device": s.device, "interface": s.interface, "zone": s.zone, "metric": s.metric, "basis": basis, "n_points": len(pts), "min_points": need}
    if len(pts) < need:
        return dict(base, status="insufficient_history", note=f"{len(pts)} {'weeks' if weekly else 'days'} < {need}")
    d0 = pts[0][0]
    t = [(d - d0).days for d, _ in pts]
    y = [v * scale for _, v in pts]
    S, tau, z, p, _ = mann_kendall(y)
    slope, lo, hi, icpt = sen(t, y, fc["alpha"])
    now_level = icpt + slope * t[-1]
    sigma = MAD_SCALE * mad([y[i] - (icpt + slope * t[i]) for i in range(len(t))])
    last = pts[-1][0]
    res = dict(base, tau=round(tau, 3), mk_p=round(p, 5), slope_pct_per_day=round(slope, 5), slope_band=[round(lo, 5), round(hi, 5)], level_now_pct=round(now_level, 2), level_scatter_pct=round(sigma, 2),
               last_observed=str(last), method="Theil-Sen slope, Mann-Kendall test; straight-line extrapolation only")
    if p >= fc["alpha"] or slope <= 0:
        return dict(res, status="no_significant_upward_trend", thresholds=[])
    out = []
    for thr in fc["thresholds_pct"]:
        e = _eta(now_level, slope, thr)
        fast = _eta(now_level + sigma, hi, thr)
        slow = _eta(now_level - sigma, lo, thr) if lo > 0 else None
        def date(days):
            return None if days is None else str(last + timedelta(days=math.ceil(days)))
        row = {"pct": thr, "eta_days": None if e is None else round(e, 1), "eta_date": date(e), "fast_date": date(fast), "slow_date": date(slow),
               "slow_note": None if lo > 0 else "slope band includes <= 0: the slow end is open"}
        if e is not None and e > fc["horizon_days"]:
            row["eta_date"] = f"beyond {fc['horizon_days']} days"
        out.append(row)
    return dict(res, status="upward_trend", thresholds=out)


def compute(series_list, cfg):
    if not cfg["forecast"]["enabled"]:
        return []
    out = [f for f in (forecast_series(s, cfg) for s in series_list) if f]
    def key(f):
        eta = next((r["eta_days"] for r in f.get("thresholds", []) if r["pct"] == 80), None)
        return (0 if f["status"] == "upward_trend" else 1, eta if eta is not None else 1e9)
    out.sort(key=key)
    return out
