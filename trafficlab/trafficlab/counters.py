"""Module 1b: counters -> rates, with wrap/reset/gap handling. Every rate records HOW it
was computed (method). Nothing is filled: unusable intervals go to `excluded`."""
from dataclasses import dataclass, field
from collections import defaultdict

from .stats import median
from .config import make_config
from . import tier


@dataclass
class Series:
    key: str
    device: str
    interface: str
    zone: str
    metric: str
    unit: str
    kind: str                       # 'counter' | 'gauge'
    ts_ms: list = field(default_factory=list)
    ts_raw: list = field(default_factory=list)     # ts_raw of the sample that ends each interval
    ts_fmt: list = field(default_factory=list)     # "format|tz_source" per point
    rate: list = field(default_factory=list)
    method: list = field(default_factory=list)
    excluded: list = field(default_factory=list)   # intervals with NO rate (gap/reset/ambiguous)
    events: list = field(default_factory=list)     # informational (wrap used, over-speed)
    interval_ms: int = None
    speed_bps: float = None
    n_samples: int = 0
    notes: list = field(default_factory=list)
    tz_assumed: str = "UTC"


def _row_sig(p, metrics):
    return tuple(p["vals"].get(m) for m in metrics) + (p["uptime_s"],)


def build_all(ds, cfg=None):
    """Returns (series_list, dq) where dq is the data-quality section of the validation report."""
    cfg = cfg or make_config()
    cc = cfg["counters"]
    metrics = [c["name"] for c in ds.mapping.get("counters", [])] + [g["name"] for g in ds.mapping.get("gauges", [])]
    spec = {c["name"]: dict(c, kind="counter") for c in ds.mapping.get("counters", [])}
    spec.update({g["name"]: dict(g, kind="gauge") for g in ds.mapping.get("gauges", [])})

    dq = {"duplicates": [], "conflicts": [], "out_of_order": 0, "rows_excluded_no_ts": 0, "series": 0}
    by_if = defaultdict(list)  # (dev, ifc) -> [row idx] in file order
    for i, p in enumerate(ds.parsed):
        if "missing_device_or_interface" in ds.row_flags.get(i, ()):
            continue
        if ds.ts_parsed[i]["epoch_ms"] is None:
            dq["rows_excluded_no_ts"] += 1
            continue
        by_if[(p["dev"], p["ifc"])].append(i)

    out = []
    for (dev, ifc), idxs in by_if.items():
        # out-of-order (file order)
        last = None
        for i in idxs:
            t = ds.ts_parsed[i]["epoch_ms"]
            if last is not None and t < last:
                dq["out_of_order"] += 1
            last = t
        # duplicate / conflict by epoch
        groups = defaultdict(list)
        for i in idxs:
            groups[ds.ts_parsed[i]["epoch_ms"]].append(i)
        keep = []
        for t in sorted(groups):
            g = groups[t]
            if len(g) == 1:
                keep.append(g[0])
                continue
            sigs = {_row_sig(ds.parsed[i], metrics) for i in g}
            lines = [ds.rows[i].line for i in g]
            if len(sigs) == 1:
                dq["duplicates"].append({"device": dev, "interface": ifc, "ts_raw": ds.rows[g[0]].ts_raw, "lines": lines})
                keep.append(g[0])
            else:
                dq["conflicts"].append({"device": dev, "interface": ifc, "ts_raw": ds.rows[g[0]].ts_raw, "lines": lines})
        for m in metrics:
            s = _build_series(ds, keep, dev, ifc, m, spec[m], cc)
            if s is not None:
                out.append(s)
    dq["series"] = len(out)
    tier.check("devices", len({x.device for x in out}))
    tier.check("series", len(out))
    tier.check("zones", len({x.zone for x in out}))
    return out, dq


def _build_series(ds, keep, dev, ifc, metric, sp, cc):
    samples = []
    speed = None
    for i in keep:
        p = ds.parsed[i]
        v = p["vals"].get(metric)
        if p["speed_bps"]:
            speed = p["speed_bps"]
        if v is None:
            continue
        t = ds.ts_parsed[i]
        samples.append((t["epoch_ms"], ds.rows[i].ts_raw, f'{t["format"]}|{t["tz_source"]}', v, p["uptime_s"]))
    if not samples:
        return None
    zone = ds.parsed[keep[0]].zone
    s = Series(key=f"{dev}|{ifc}|{metric}", device=dev, interface=ifc, zone=zone, metric=metric,
               unit=sp.get("unit", "bps"), kind=sp["kind"], speed_bps=speed, n_samples=len(samples),
               tz_assumed=ds.tz)
    if len(samples) < 2:
        s.notes.append("fewer than 2 samples: no rates")
        return s
    dts = [samples[i][0] - samples[i - 1][0] for i in range(1, len(samples))]
    s.interval_ms = int(median(dts))
    gap_ms = cc["gap_factor"] * s.interval_ms
    mult = float(sp.get("mult", 1))
    if sp["kind"] == "counter":
        bits = sp["bits"]
        mod = 2 ** bits
        if bits == 32 and speed and sp.get("unit") == "bps" and mult == 8:
            if speed * (s.interval_ms / 1000.0) / 8.0 >= mod:
                s.notes.append("32-bit octet counter can wrap more than once per interval at line rate "
                               "(speed*interval/8 >= 2^32): rates unreliable; use 64-bit counters")
    for i in range(1, len(samples)):
        t0, r0, _, v0, u0 = samples[i - 1]
        t1, r1, f1, v1, u1 = samples[i]
        dt_ms = t1 - t0
        base = {"start_ms": t0, "end_ms": t1, "start_raw": r0, "end_raw": r1}
        if dt_ms > gap_ms:
            s.excluded.append(dict(base, type="gap", detail=f"dt={dt_ms/1000:.0f}s > {cc['gap_factor']}*interval({s.interval_ms/1000:.0f}s)"))
            continue
        dt = dt_ms / 1000.0
        if sp["kind"] == "gauge":
            _add(s, t1, r1, f1, v1 * mult, "gauge_as_given")
            continue
        # ---- counter ----
        reload = None
        if u0 is not None and u1 is not None:
            tol = max(5.0, 0.1 * dt)
            if u1 < u0:
                reload = f"uptime dropped {u0:.0f}s -> {u1:.0f}s"
            elif u1 < dt - tol:
                reload = f"uptime {u1:.0f}s < interval {dt:.0f}s (reload inside interval)"
        if reload:
            s.excluded.append(dict(base, type="reset", detail=reload))
            continue
        max_delta = None
        if speed and sp.get("unit") == "bps" and mult == 8:
            max_delta = speed * (1 + cc["speed_headroom"]) * dt / 8.0
        if v1 >= v0:
            delta = v1 - v0
            _add(s, t1, r1, f1, delta * mult / dt, "delta")
            if max_delta is not None and delta > max_delta:
                s.events.append(dict(base, type="rate_exceeds_speed", detail=f"delta={delta} > max_plausible={max_delta:.0f}"))
            continue
        # v1 < v0 : wrap or reset
        have_up = u0 is not None and u1 is not None
        if sp["bits"] == 32:
            delta = v1 + mod - v0
            if have_up:
                if max_delta is not None and delta > max_delta:
                    s.excluded.append(dict(base, type="reset_unexplained", detail=f"decrease; uptime ok; wrapped delta {delta} > plausible {max_delta:.0f}"))
                else:
                    _add(s, t1, r1, f1, delta * mult / dt, "wrap32_uptime_confirmed")
                    s.events.append(dict(base, type="wrap32", detail="uptime shows no reload; plausibility " + ("ok" if max_delta else "unverified (speed unknown)")))
            elif max_delta is not None:
                if delta <= max_delta:
                    _add(s, t1, r1, f1, delta * mult / dt, "wrap32_plausible")
                    s.events.append(dict(base, type="wrap32", detail="no uptime; wrapped delta within line-speed bound; a counter clear is not excluded"))
                else:
                    s.excluded.append(dict(base, type="reset_or_wrap_ambiguous", detail=f"no uptime; wrapped delta {delta} > plausible {max_delta:.0f} -> treated as reset"))
            elif cc["allow_unverified_wrap"]:
                _add(s, t1, r1, f1, delta * mult / dt, "wrap32_unverified")
                s.events.append(dict(base, type="wrap32", detail="UNVERIFIED (no uptime, no speed; allow_unverified_wrap=True)"))
            else:
                s.excluded.append(dict(base, type="reset_or_wrap_ambiguous", detail="32-bit decrease; no uptime and no speed to decide wrap vs reset"))
        else:
            s.excluded.append(dict(base, type="counter_decrease_64bit", detail="64-bit counter decreased; wrap not credible; reset/clear assumed, no rate"))
    return s


def _add(s, t, raw, fmt, rate, method):
    s.ts_ms.append(t)
    s.ts_raw.append(raw)
    s.ts_fmt.append(fmt)
    s.rate.append(rate)
    s.method.append(method)
