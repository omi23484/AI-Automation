"""Week-over-week mode for AGGREGATED weekly exports (one row per link per week: peak/average/utilisation).
These carry no poll series, so intra-week events are invisible by construction. Detection is limited to
week-level anomalies (robust z vs trailing weeks) and level shifts (binary segmentation). No yearly seasonality is modelled.

Honesty notes
- Week assignment is an ASSUMPTION unless the user overrides it: file-name stamp = report generation time, covered period =
  the 7 days BEFORE it ("Last 7 Days"). Every file's assignment is listed in the validation report.
- Cells keep their unit token ('1.06 Gbps', '13.78 %'); header units are used only when the cell has none. Nothing is rescaled
  from magnitude. Fractions-vs-percent is NOT guessed (reported only).
- Missing weeks are gaps (marked, never filled). Conflicting duplicates are excluded."""
import csv
import io
import os
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

from .config import make_config, cfg_for_zone, floor_abs
from .counters import Series
from .stats import median, mad, mean, variance, MAD_SCALE
from .units import parse_rate, unit_multiplier
from .timeparse import get_tz, _to_ms
from .anomaly import fid
from . import changepoint as cpm
from .pipeline import _summ, finish
from . import tier

WEEK_MS = 7 * 86_400_000
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


# ------------------------------------------------------------------ xlsx reader (stdlib)
def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(data, max_rows=200_000, max_bytes=300_000_000):
    """-> [(sheet_name, rows)], rows = list of list[str|None] aligned by column. Values are the RAW cell text."""
    z = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in z.infolist()) > max_bytes:
        raise ValueError("xlsx too large when uncompressed")
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            ss.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = []
    for sh in wb.find("m:sheets", _NS):
        rid = sh.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        tgt = rels.get(rid, "")
        path = tgt.lstrip("/") if tgt.startswith("/") else "xl/" + tgt
        if path not in z.namelist():
            continue
        rows = []
        for r in ET.fromstring(z.read(path)).iter("{%s}row" % _NS["m"]):
            cells = {}
            for c in r.findall("m:c", _NS):
                t, v = c.get("t"), c.find("m:v", _NS)
                if t == "s" and v is not None:
                    val = ss[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % _NS["m"]))
                elif v is not None:
                    val = v.text
                else:
                    val = None
                cells[_col(c.get("r"))] = val
            if cells:
                row = [None] * (max(cells) + 1)
                for k, v in cells.items():
                    row[k] = v
                rows.append(row)
            else:
                rows.append([])
            if len(rows) > max_rows:
                raise ValueError("too many rows")
        out.append((sh.get("name"), rows))
    return out


def read_csv_rows(text):
    return [("csv", [list(r) for r in csv.reader(io.StringIO(text.lstrip("﻿")))])]


# ------------------------------------------------------------------ header resolver (by meaning, editable)
def _norm(h):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\([^)]*\)", "", h.lower()))


ALIASES = {
    "device": ["nodename", "node", "hostname", "host", "device", "devicename", "caption", "routername", "switchname"],
    "interface": ["interfacename", "interface", "port", "ifname", "ifdescr", "portname"],
    "link": ["linkname", "link", "circuit", "circuitid"],
    "site": ["site", "location"],
    "peak_in_bps": ["peakreceive", "peakin", "inpeak", "rxpeak", "peakrx", "maxreceive", "peakingress"],
    "peak_out_bps": ["peaktransmit", "peakout", "outpeak", "txpeak", "peaktx", "maxtransmit", "peakegress"],
    "avg_in_bps": ["averagereceive", "avgreceive", "avgin", "inavg", "averagein", "rxavg", "avgrx"],
    "avg_out_bps": ["averagetransmit", "avgtransmit", "avgout", "outavg", "averageout", "txavg", "avgtx"],
    "speed_in": ["receivedbandwidth", "rxbandwidth", "bandwidthin", "inbandwidth"],
    "speed_out": ["transmitbandwidth", "txbandwidth", "bandwidthout", "outbandwidth"],
    "speed": ["speed", "bandwidth", "linkspeed", "ifspeed", "capacity"],
    "util_in_pct": ["receivedpercentutilization", "rxutil", "inpercent", "inutilization", "receiveutilization"],
    "util_out_pct": ["transmitpercentutilization", "txutil", "outpercent", "oututilization", "transmitutilization"],
    "util_avg_pct": ["avgutil", "averageutilization", "totalaveragepercentutilization", "avgutilization"],
    "util_p95_pct": ["95thpercentile", "p95", "percentile95"],
    "util_peak_pct": ["peakutil", "peakutilization", "peakpercent"],
}
ALIAS_REV = {a: k for k, v in ALIASES.items() for a in v}
BPS_METRICS = ["avg_in_bps", "avg_out_bps", "peak_in_bps", "peak_out_bps"]
PCT_METRICS = ["util_in_pct", "util_out_pct", "util_avg_pct", "util_p95_pct", "util_peak_pct"]


def alias_table(extra=None):
    """Built-in aliases + user additions (config weekly.aliases). Unknown canonical names are an error."""
    rev = dict(ALIAS_REV)
    for canon, names in (extra or {}).items():
        if canon not in ALIASES:
            raise ValueError(f"weekly.aliases: unknown field '{canon}'. Valid: {sorted(ALIASES)}")
        for n in names:
            rev[_norm(n)] = canon
    return rev


def resolve_header(row, override=None, rev=None):
    """-> {canonical: (col_index, header_text, default_unit)} or None if the row doesn't look like a header."""
    override = override or {}
    rev = rev or ALIAS_REV
    found = {}
    for i, h in enumerate(row):
        if not h:
            continue
        key = override.get(h) or rev.get(_norm(h))
        if not key or key in found:
            continue
        unit = None
        m = re.search(r"\(([^)]*)\)", h)
        if m and unit_multiplier(m.group(1).strip()):
            unit = m.group(1).strip()
        elif m and m.group(1).strip().lower() in ("mbps", "gbps", "kbps", "bps", "tbps"):
            unit = m.group(1).strip()
        elif re.search(r"\b([kKmMgGtT]?[bB]ps)\s*$", h):
            unit = re.search(r"\b([kKmMgGtT]?[bB]ps)\s*$", h).group(1)
        found[key] = (i, h, unit)
    ok = ("device" in found or "link" in found) and ("interface" in found or "link" in found) and any(k in found for k in BPS_METRICS + PCT_METRICS)
    return found if ok else None


# ------------------------------------------------------------------ week assignment
STAMP = re.compile(r"(\d{4})[_-](\d{2})[_-](\d{2})[_-](\d{2})[_-](\d{2})[_-](\d{2})")
ISOWEEK = re.compile(r"(\d{4})-?W(\d{2})")


BASES = ("stamp_period_ends", "stamp_period_starts", "stamp_week_contains")


def week_of(name, tz_name, overrides=None, basis="stamp_period_ends"):
    """-> dict(start_ms, end_ms, ts_raw, basis, assumption) or None. Priority: explicit override > ISO-week in name > file-name stamp (per `basis`)."""
    if basis not in BASES:
        raise ValueError(f"weekly.week_basis must be one of {BASES}")
    tz = get_tz(tz_name)
    base = os.path.basename(name)
    if overrides and (base in overrides or name in overrides):
        d = datetime.strptime(overrides.get(base) or overrides[name], "%Y-%m-%d")
        st = d.replace(tzinfo=tz)
        return dict(start_ms=_to_ms(st), end_ms=_to_ms(st) + WEEK_MS, ts_raw=overrides.get(base) or overrides[name], basis="explicit override", assumption=False)
    m = ISOWEEK.search(name)
    if m:
        d = datetime.fromisocalendar(int(m[1]), int(m[2]), 1).replace(tzinfo=tz)
        return dict(start_ms=_to_ms(d), end_ms=_to_ms(d) + WEEK_MS, ts_raw=m.group(0), basis="ISO week in folder/file name", assumption=False)
    m = STAMP.search(base)
    if m:
        g = datetime(*[int(x) for x in m.groups()], tzinfo=tz)
        t = _to_ms(g)
        if basis == "stamp_period_ends":
            st, en, why = t - WEEK_MS, t, "file-name stamp = end of the 7-day period (report generated after the week it covers)"
        elif basis == "stamp_period_starts":
            st, en, why = t, t + WEEK_MS, "file-name stamp = start of the 7-day period"
        else:
            mon = (g - timedelta(days=g.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            st = _to_ms(mon)
            st, en, why = st, st + WEEK_MS, "ISO week (Mon-Sun) containing the file-name stamp"
        return dict(start_ms=st, end_ms=en, ts_raw=m.group(0), basis=why, assumption=True)
    return None


# ------------------------------------------------------------------ build
def _num_cell(c):
    return None if c is None or str(c).strip() == "" else str(c).strip()


def _pct(c):
    s = c.replace("%", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def build_series(files, cfg=None, tz="UTC", overrides=None, mapping_override=None, inventory=None):
    """files: [(name, bytes|str)] .xlsx or .csv. -> (series_list, report). Raw cell text is never modified."""
    tier.require("weekly_mode", "weekly aggregate mode")
    cfg = cfg or make_config()
    wcfg = cfg["weekly"]
    rev = alias_table(wcfg.get("aliases"))
    from .config import glob_lookup
    rep = {"files": [], "issues": [], "weeks": [], "duplicates": [], "conflicts": [], "cells": {"unit_from_header": 0, "bad": 0, "blank": 0}}
    pts = defaultdict(list)       # (device, iface, metric) -> [(start, end, ts_raw, value, file)]
    meta = {}
    supplied = defaultdict(dict)  # for util recompute: (dev, if, week_end) -> {...}
    frac_cols = defaultdict(lambda: [0, 0])

    def issue(sev, msg):
        rep["issues"].append({"severity": sev, "message": msg})

    for name, blob in files:
        wk = week_of(name, tz, overrides, wcfg["week_basis"])
        f = {"file": name, "recognized": False}
        rep["files"].append(f)
        try:
            sheets = read_xlsx(blob) if name.lower().endswith(".xlsx") else read_csv_rows(blob if isinstance(blob, str) else blob.decode("utf-8-sig", "replace"))
        except Exception as e:
            f["error"] = f"{type(e).__name__}: {e}"
            issue("error", f"{name}: cannot read ({f['error']})")
            continue
        hdr = rows = None
        for sh, rws in sheets:
            for ri, r in enumerate(rws[:25]):
                hdr = resolve_header([("" if c is None else str(c)) for c in r], mapping_override, rev)
                if hdr:
                    rows, f["sheet"], f["header_row"] = rws[ri + 1:], sh, ri + 1
                    break
            if hdr:
                break
        if not hdr:
            issue("warn", f"{name}: no recognizable link-utilisation header (needs device+interface or link, and a peak/average/utilisation column); skipped")
            continue
        f["recognized"], f["columns"] = True, {k: v[1] for k, v in hdr.items()}
        if wk is None:
            issue("error", f"{name}: cannot assign a week (no ISO-week folder, no YYYY_MM_DD_hh_mm_ss stamp, no override); skipped")
            continue
        f["week"] = {k: wk[k] for k in ("ts_raw", "basis", "assumption")}
        f["week"]["period_start_ms"], f["week"]["period_end_ms"] = wk["start_ms"], wk["end_ms"]
        n_rows = 0
        for r in rows:
            def g(k):
                if k not in hdr or hdr[k][0] >= len(r):
                    return None
                return _num_cell(r[hdr[k][0]])
            dev, ifc, link = g("device"), g("interface"), g("link")
            if not (dev or link):
                continue
            dev, ifc = dev or link, ifc or link or "?"
            n_rows += 1
            key = (dev, ifc)
            zone = (inventory or {}).get(dev, {}).get("zone") or glob_lookup(dev, cfg.get("zone_map"), "zone", "unassigned")
            meta.setdefault(key, {"site": g("site"), "zone": zone})
            sp = None
            for sk in ("speed_in", "speed_out", "speed"):
                if g(sk):
                    sp = parse_rate(g(sk), hdr[sk][2])          # unit token in the cell, else header unit, else unparsed (never assumed)
                    if sp:
                        break
            if sp:
                meta[key]["speed_bps"] = sp
            for mk in BPS_METRICS + PCT_METRICS:
                c = g(mk)
                if mk not in hdr:
                    continue
                if c is None:
                    rep["cells"]["blank"] += 1
                    continue
                if mk in BPS_METRICS:
                    v = parse_rate(c, hdr[mk][2])
                    if v is not None and not re.search(r"[A-Za-z]", c) and hdr[mk][2]:
                        rep["cells"]["unit_from_header"] += 1
                else:
                    v = _pct(c)
                    frac_cols[(name, mk)][0] += 1
                    if v is not None and abs(v) <= 1.0:
                        frac_cols[(name, mk)][1] += 1
                if v is None:
                    rep["cells"]["bad"] += 1
                    continue
                if v < 0:
                    issue("warn", f"{name}: negative value in {mk} for {dev} {ifc}: {c!r} (kept as given, flagged)")
                pts[(dev, ifc, mk)].append((wk["start_ms"], wk["end_ms"], wk["ts_raw"], v, name))
                supplied[(dev, ifc, wk["end_ms"])][mk] = v
        f["rows"] = n_rows
    for (nm, mk), (n, small) in frac_cols.items():
        if n >= 5 and small == n:
            issue("warn", f"{nm}: every {mk} value is <= 1.0 ({n} cells): may be fractions instead of percent. NOT rescaled; check the export")
    # util recompute cross-check
    mism = tot = 0
    for (dev, ifc, we), d in supplied.items():
        sp = meta.get((dev, ifc), {}).get("speed_bps")
        for pm, bm in (("util_in_pct", "avg_in_bps"), ("util_out_pct", "avg_out_bps")):
            if sp and pm in d and bm in d:
                tot += 1
                if abs(100.0 * d[bm] / sp - d[pm]) > wcfg["util_mismatch_pts"]:
                    mism += 1
    if tot:
        issue("warn" if mism else "info", f"utilisation cross-check: {mism}/{tot} link-weeks differ by > {wcfg['util_mismatch_pts']} percentage points between the supplied % and average/speed")
    out, dropped = [], 0
    for (dev, ifc, mk), lst in pts.items():
        twin = {"util_in_pct": "avg_in_bps", "util_out_pct": "avg_out_bps"}.get(mk)
        if twin and (dev, ifc, twin) in pts:
            dropped += 1          # derived % twin of an analysed bps series: skipped to avoid duplicate findings for one event
            continue
        by = defaultdict(list)
        for st, en, raw, v, nm in lst:
            by[en].append((st, raw, v, nm))
        s = Series(key=f"{dev}|{ifc}|{mk}", device=dev, interface=ifc, zone=meta[(dev, ifc)]["zone"], metric=mk, unit="bps" if mk in BPS_METRICS else "pct",
                   kind="gauge", speed_bps=meta[(dev, ifc)].get("speed_bps"), tz_assumed=tz)
        s.interval_ms = WEEK_MS
        for en in sorted(by):
            g = by[en]
            vals = {x[2] for x in g}
            if len(g) > 1 and len(vals) == 1:
                rep["duplicates"].append({"series": s.key, "week_end_ms": en, "files": [x[3] for x in g]})
            elif len(g) > 1:
                rep["conflicts"].append({"series": s.key, "week_end_ms": en, "files": [x[3] for x in g], "values": sorted(vals)})
                s.excluded.append({"start_ms": en - WEEK_MS, "end_ms": en, "start_raw": g[0][1], "end_raw": g[0][1], "type": "conflict", "detail": "same week, different values in several files; excluded"})
                continue
            s.ts_ms.append(en)
            s.ts_raw.append(g[0][1])
            s.ts_fmt.append("weekly|file")
            s.rate.append(g[0][2])
            s.method.append("weekly_aggregate")
        s.n_samples = len(s.ts_ms)
        for i in range(1, len(s.ts_ms)):
            if s.ts_ms[i] - s.ts_ms[i - 1] > 1.5 * WEEK_MS:
                s.excluded.append({"start_ms": s.ts_ms[i - 1], "end_ms": s.ts_ms[i], "start_raw": s.ts_raw[i - 1], "end_raw": s.ts_raw[i], "type": "gap",
                                   "detail": f"{round((s.ts_ms[i] - s.ts_ms[i - 1]) / WEEK_MS) - 1} week(s) missing; not filled"})
        out.append(s)
    if dropped:
        issue("info", f"{dropped} utilisation-% series not analysed separately: they duplicate the average-bps series of the same link/direction")
    if rep["duplicates"]:
        issue("warn", f"{len(rep['duplicates'])} identical duplicate link-weeks across files (kept once)")
    if rep["conflicts"]:
        issue("error", f"{len(rep['conflicts'])} link-weeks with CONFLICTING values in several files: excluded, not merged")
    gaps = sum(1 for s in out for e in s.excluded if e["type"] == "gap")
    if gaps:
        issue("warn", f"{gaps} missing-week gaps across series (marked, never filled)")
    if rep["cells"]["unit_from_header"]:
        issue("info", f"{rep['cells']['unit_from_header']} cells had no unit token; unit taken from the column header")
    if rep["cells"]["bad"]:
        issue("warn", f"{rep['cells']['bad']} cells unparseable (flagged, treated as missing)")
    asm = [f for f in rep["files"] if f.get("week", {}).get("assumption")]
    if asm:
        issue("warn", f"{len(asm)} file(s): week ASSUMED from the file-name stamp ({asm[0]['week']['basis']}), e.g. {asm[0]['file']!r} -> stamp {asm[0]['week']['ts_raw']}. "
                      "Change weekly.week_basis or pass per-file overrides if wrong")
    tier.check("devices", len({x.device for x in out}))
    tier.check("series", len(out))
    tier.check("zones", len({x.zone for x in out}))
    weeks = sorted({s_end for s in out for s_end in s.ts_ms})
    rep["weeks"] = weeks
    issue("info", f"{len(out)} weekly series from {sum(1 for f in rep['files'] if f['recognized'])} recognised files, {len(weeks)} distinct weeks")
    return out, rep


# ------------------------------------------------------------------ detection
def _wwin(s, i0, i1):
    f0, f1 = s.ts_fmt[i0].rsplit("|", 1), s.ts_fmt[i1].rsplit("|", 1)
    return {"start_ms": s.ts_ms[i0] - WEEK_MS, "end_ms": s.ts_ms[i1], "start_raw": s.ts_raw[i0], "end_raw": s.ts_raw[i1], "granularity": "weekly",
            "start_ts_parsed": {"epoch_ms": s.ts_ms[i0] - WEEK_MS, "format": "weekly period start (end - 7d)", "tz_assumed": s.tz_assumed, "tz_source": "derived"},
            "end_ts_parsed": {"epoch_ms": s.ts_ms[i1], "format": "weekly period end", "tz_assumed": s.tz_assumed, "tz_source": "derived"}}


def _sev(z):
    return "high" if z >= 10 else "medium" if z >= 6 else "low"


def detect_weekly(s, cfg):
    w = cfg["weekly"]
    n = len(s.rate)
    info = {"status": "ok", "scored": 0}
    fabs = floor_abs(cfg["baseline"], s.unit)
    z, med, scl = [None] * n, [None] * n, [None] * n
    for i in range(n):
        hist = s.rate[max(0, i - w["window_weeks"]):i]
        if len(hist) < w["min_weeks"]:
            continue
        m = median(hist)
        sc = max(MAD_SCALE * mad(hist, m), cfg["baseline"]["scale_floor_rel"] * abs(m), fabs)
        med[i], scl[i], z[i] = m, sc, (s.rate[i] - m) / sc
    info["scored"] = sum(1 for x in z if x is not None)
    findings, resid = [], {}
    run = []
    runs = []
    for i in range(n):
        hit = z[i] is not None and abs(z[i]) >= w["z_threshold"]
        if hit and run and (s.ts_ms[i] - s.ts_ms[run[-1]] <= 1.5 * WEEK_MS) and ((z[i] > 0) == (z[run[-1]] > 0)):
            run.append(i)
        else:
            if run:
                runs.append(run)
            run = [i] if hit else []
    if run:
        runs.append(run)
    for r in runs:
        if len(r) < w["min_points"]:
            continue
        pk = max(r, key=lambda k: abs(z[k]))
        fi = fid("anomaly", s.key, s.ts_ms[r[0]], s.ts_ms[r[-1]])
        bm = median([med[k] for k in r])
        mv = mean([s.rate[k] for k in r])
        lvl, why = ("medium", "week-level robust z vs >= 8 prior weeks") if info["scored"] and min(w["window_weeks"], r[0]) >= w["window_weeks"] else ("low", "fewer than a full trailing window of prior weeks")
        findings.append({"id": fi, "layer": "statistical", "kind": "anomaly", "metric": s.metric, "unit": s.unit, "device": s.device, "interface": s.interface, "zone": s.zone,
                         "series_key": s.key, "window": _wwin(s, r[0], r[-1]), "direction": "high" if z[pk] > 0 else "low", "severity": _sev(abs(z[pk])), "methods": ["weekly_robust_z"],
                         "math": [{"method": "weekly_robust_z", "formula": "z=(x-median_w)/max(1.4826*MAD_w, rel*|median_w|, abs_floor) over the previous window_weeks observed weeks; flag |z|>=thr",
                                   "params": {"window_weeks": w["window_weeks"], "min_weeks": w["min_weeks"], "z_threshold": w["z_threshold"], "min_points": w["min_points"],
                                              "granularity": "weekly: intra-week events are invisible"}}],
                         "numbers": {"peak_abs_z": round(abs(z[pk]), 3), "baseline_median": round(bm, 3), "mean_value": round(mv, 3),
                                     "deviation_pct": round(100 * (mv - bm) / bm, 1) if bm else None, "weeks": len(r)},
                         "confidence": {"level": lvl, "justification": why + "; weekly aggregate, no seasonality model"}, "interpretation": [], "cr_candidates": []})
        mg = w["corr_margin_weeks"] * WEEK_MS
        resid[fi] = [[s.ts_ms[k], s.rate[k] - med[k]] for k in range(n) if med[k] is not None and s.ts_ms[r[0]] - mg <= s.ts_ms[k] <= s.ts_ms[r[-1]] + mg]
    # level shifts
    shst = {"status": "ok", "reason": None}
    ms = w["min_segment_weeks"]
    if n < 2 * ms:
        shst.update(status="insufficient_history", reason=f"{n} weeks < {2 * ms}")
        return findings, info, resid, shst
    r_ = list(s.rate)
    P = [0.0]
    for x in r_:
        P.append(P[-1] + x)
    cps, stack = [], [(0, n)]
    while stack:
        lo, hi = stack.pop()
        sp = cpm._split(r_, P, lo, hi, ms, fabs)
        if not sp or sp["t"] < w["stat_threshold"]:
            continue
        eff, ref = abs(sp["m2"] - sp["m1"]), abs(mean(r_[lo:sp["k"]]))
        if eff < w["min_effect_sigma"] * sp["sigma_d"] or (ref > 0 and eff / ref < w["min_effect_rel"]):
            continue
        # robustness: the MEDIAN must move too, so one outlier week cannot masquerade as a level shift
        eff_med, ref_med = abs(median(r_[sp["k"]:hi]) - median(r_[lo:sp["k"]])), abs(median(r_[lo:sp["k"]]))
        if eff_med < w["min_effect_sigma"] * sp["sigma_d"] or (ref_med > 0 and eff_med / ref_med < w["min_effect_rel"]):
            continue
        cps.append(dict(sp, lo=lo, hi=hi))
        stack += [(lo, sp["k"]), (sp["k"], hi)]
    cps = sorted(sorted(cps, key=lambda c: -c["t"])[:w["max_changepoints"]], key=lambda c: c["k"])
    bounds = [0] + [c["k"] for c in cps] + [n]
    for j, c in enumerate(cps):
        k = c["k"]
        before, after = r_[bounds[j]:k], r_[k:bounds[j + 2]]
        if len(before) < 2 or len(after) < 2:
            continue
        mb, ma = mean(before), mean(after)
        rel = (ma - mb) / mb if mb else None
        pc = abs(rel) if rel is not None else 0
        findings.append({"id": fid("shift", s.key, s.ts_ms[k], s.ts_ms[k]), "layer": "statistical", "kind": "pattern_shift", "metric": s.metric, "unit": s.unit,
                         "device": s.device, "interface": s.interface, "zone": s.zone, "series_key": s.key, "window": _wwin(s, k, k), "direction": "up" if ma > mb else "down",
                         "severity": "high" if pc >= 0.5 else "medium" if pc >= 0.2 else "low", "methods": ["binary_segmentation_mean_shift"],
                         "math": [{"method": "binary_segmentation_mean_shift", "formula": "t=|m2-m1|/(sigma_d*sqrt((1/n1+1/n2)*(1+rho)/(1-rho)^2)); sigma_d=1.4826*MAD(diff)/sqrt2 on WEEKLY values (no seasonal removal)",
                                   "params": {"stat_threshold": w["stat_threshold"], "min_effect_sigma": w["min_effect_sigma"], "min_effect_rel": w["min_effect_rel"], "min_segment_weeks": ms,
                                              "shift_resolution": "1 week (first week of the new level)"}}],
                         "numbers": {"t_stat": round(c["t"], 2), "sigma_d": round(c["sigma_d"], 3), "rho": round(c["rho"], 3), "raw_mean_before": round(mb, 3), "raw_mean_after": round(ma, 3),
                                     "raw_var_before": variance(before), "raw_var_after": variance(after), "n_before": len(before), "n_after": len(after),
                                     "change_pct": round(100 * rel, 1) if rel is not None else None},
                         "confidence": {"level": "medium" if c["t"] >= 2 * w["stat_threshold"] and len(before) >= 6 and len(after) >= 6 else "low",
                                        "justification": "weekly values, no seasonality removed; heuristic t, not a calibrated p-value"},
                         "interpretation": [], "cr_candidates": []})
    return findings, info, resid, shst


def analyze_weekly(series_list, cfg=None, store=None):
    import time
    cfg = cfg or make_config()
    t0 = time.time()
    findings, sums, resid = [], [], {}
    for s in series_list:
        eff = cfg_for_zone(cfg, s.zone)
        fs, info, rs, shst = detect_weekly(s, eff)
        findings += fs
        resid.update(rs)
        d = _summ(s)
        d["interval_s"] = 7 * 86400
        d.update(baseline={"tier_counts": {"trailing_weeks": info["scored"], "insufficient_history": len(s.rate) - info["scored"]}}, shift_status=shst, tz_used=eff["tz"], secs=0.0)
        sums.append(d)
    ccfg2 = dict(cfg)
    ccfg2["correlation"] = dict(cfg["correlation"], slack_s=7 * 86400 // 2, min_overlap_points=5)
    crs = store.list() if store else []
    res = finish(findings, sums, resid, series_list, ccfg2, crs, t0, 1, shift_uncertainty_ms=WEEK_MS, followup_days=7 * cfg["weekly"]["followup_weeks"])
    res["mode"] = "weekly"
    from .pipeline import annotate_feedback
    annotate_feedback(res["findings"], store.list_feedback() if store else [])
    return res
