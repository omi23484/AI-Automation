"""Module 1a: CSV ingest. Raw rows are immutable (frozen dataclass, never mutated).
All derived values live in separate parallel structures."""
import csv
import io
import sys
from collections import Counter
from dataclasses import dataclass, field

from .timeparse import parse_ts, get_tz, slash_census
from .units import parse_rate


class IngestError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RawRow:
    line: int            # 1-based line number in source (header = 1)
    ts_raw: str          # EXACT original string. Never modified.
    device: str
    interface: str
    cells: tuple         # all original cell strings, aligned with Dataset.header


class _Slots:
    """Compact record with dict-style read access (memory: ~5x smaller than a dict per row)."""
    __slots__ = ()

    def __getitem__(self, k):
        return getattr(self, k)

    def get(self, k, d=None):
        return getattr(self, k, d)


class TP(_Slots):
    __slots__ = ("epoch_ms", "format", "tz_assumed", "tz_source", "flags")

    def __init__(self, d):
        self.epoch_ms, self.format, self.tz_assumed = d["epoch_ms"], d["format"], d["tz_assumed"]
        self.tz_source, self.flags = d["tz_source"], tuple(d["flags"])


class PR(_Slots):
    __slots__ = ("vals", "uptime_s", "speed_bps", "zone", "dev", "ifc")

    def __init__(self, vals, uptime_s, speed_bps, zone, dev, ifc):
        self.vals, self.uptime_s, self.speed_bps, self.zone, self.dev, self.ifc = vals, uptime_s, speed_bps, zone, dev, ifc


@dataclass
class Dataset:
    source: str
    header: tuple
    rows: tuple                      # tuple[RawRow]  (immutable raw)
    ts_parsed: list                  # aligned with rows (derived)
    parsed: list                     # aligned with rows: {"vals":{}, "uptime_s":, "speed_bps":, "zone":}
    row_flags: dict                  # row index -> [flags]
    mapping: dict
    tz: str
    ts_formats: list
    meta: dict = field(default_factory=dict)


UPTIME_TO_S = {"s": 1.0, "cs": 0.01, "ms": 0.001}      # cs = SNMP TimeTicks (1/100 s)
SPEED_TO_BPS = {"bps": 1.0, "kbps": 1e3, "mbps": 1e6}  # ifHighSpeed is Mbps


def _num(s, as_int):
    s = s.strip()
    if s == "":
        return None
    try:
        return int(s) if as_int else float(s)
    except ValueError:
        return "BAD"


def validate_mapping(mapping, header):
    need = [mapping.get("device"), mapping.get("interface"), mapping.get("timestamp")]
    cols = [c["column"] for c in mapping.get("counters", [])] + [g["column"] for g in mapping.get("gauges", [])]
    if mapping.get("uptime"):
        cols.append(mapping["uptime"]["column"])
    if mapping.get("speed"):
        cols.append(mapping["speed"]["column"])
    if mapping.get("zone"):
        cols.append(mapping["zone"])
    missing = [c for c in need + cols if c not in header]
    if any(c is None for c in need):
        raise IngestError("mapping needs device, interface, timestamp columns")
    if missing:
        raise IngestError(f"columns not in file: {missing}. Available: {list(header)}")
    if not mapping.get("counters") and not mapping.get("gauges"):
        raise IngestError("mapping needs at least one counter or gauge")
    for c in mapping.get("counters", []):
        if c.get("bits") not in (32, 64):
            raise IngestError(f"counter {c.get('name')}: bits must be 32 or 64")


def load_csv(text, mapping, ts_formats=None, tz="UTC", delimiter=",", inventory=None, source="<memory>", keep_cells=False, zone_map=None):
    """keep_cells=False: full cell tuples are retained only for FLAGGED rows (memory); ts_raw/device/interface are always kept
    exactly. The source file remains the complete raw record."""
    get_tz(tz)  # fail early on bad tz
    inventory = inventory or {}
    if text.startswith("﻿"):
        text = text[1:]  # BOM is a file artifact, not data
    rdr = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = tuple(next(rdr))
    except StopIteration:
        raise IngestError("empty file")
    validate_mapping(mapping, header)
    ix = {c: i for i, c in enumerate(header)}
    i_dev, i_if, i_ts = ix[mapping["device"]], ix[mapping["interface"]], ix[mapping["timestamp"]]
    i_zone = ix[mapping["zone"]] if mapping.get("zone") else None
    ctrs = [(c["name"], ix[c["column"]], True) for c in mapping.get("counters", [])]
    gaus = [(g["name"], ix[g["column"]], False) for g in mapping.get("gauges", [])]
    rate_parse = {g["name"]: g.get("default_unit") for g in mapping.get("gauges", []) if g.get("parse") == "rate"}
    upt = mapping.get("uptime")
    i_up = ix[upt["column"]] if upt else None
    up_mult = UPTIME_TO_S[upt.get("unit", "s")] if upt else None
    spd = mapping.get("speed")
    i_sp = ix[spd["column"]] if spd else None
    sp_rate = bool(spd and spd.get("parse") == "rate")
    sp_mult = SPEED_TO_BPS[spd.get("unit", "bps")] if (spd and not sp_rate) else None

    rows, tsl, parsed, flags = [], [], [], {}
    short = 0

    for lineno, cells in enumerate(rdr, start=2):
        if not cells or all(c == "" for c in cells):
            continue
        idx = len(rows)
        fl = []
        if len(cells) != len(header):
            fl.append("column_count_mismatch")
            short += 1
            cells = list(cells) + [""] * (len(header) - len(cells))
            cells = cells[: len(header)]
        tp = TP(parse_ts(cells[i_ts], ts_formats, tz))
        fl.extend(tp.flags)
        vals = {}
        for name, ci, as_int in ctrs + gaus:
            if name in rate_parse:     # '12.34 Mbps' style cell -> bits/s
                raw_c = cells[ci]
                v = parse_rate(raw_c, rate_parse[name])
                if v is None and raw_c.strip() != "":
                    v = "BAD"
            else:
                v = _num(cells[ci], as_int)
            if v == "BAD":
                fl.append(f"bad_value:{name}")
                v = None
            vals[name] = v
        up = None
        if i_up is not None:
            u = _num(cells[i_up], False)
            if u == "BAD":
                fl.append("bad_value:uptime")
            elif u is not None:
                up = u * up_mult
        sp = None
        if i_sp is not None:
            if sp_rate:
                u = parse_rate(cells[i_sp], spd.get("default_unit"))
                if u is None and cells[i_sp].strip() != "":
                    fl.append("bad_value:speed")
                elif u is not None and u > 0:
                    sp = u
            else:
                u = _num(cells[i_sp], False)
                if u == "BAD":
                    fl.append("bad_value:speed")
                elif u is not None and u > 0:
                    sp = u * sp_mult
        dev, ifc = sys.intern(cells[i_dev].strip()), sys.intern(cells[i_if].strip())
        if not dev or not ifc:
            fl.append("missing_device_or_interface")
        zone = None
        if i_zone is not None and cells[i_zone].strip():
            zone = cells[i_zone].strip()
        elif dev in inventory and inventory[dev].get("zone"):
            zone = inventory[dev].get("zone")
        elif zone_map:
            from .config import glob_lookup
            zone = glob_lookup(dev, zone_map, "zone")
        if sp is None and (dev, ifc) in inventory.get("__speeds__", {}):
            sp = inventory["__speeds__"][(dev, ifc)]
        rows.append(RawRow(lineno, cells[i_ts], sys.intern(cells[i_dev]), sys.intern(cells[i_if]), tuple(cells) if (keep_cells or fl) else ()))
        tsl.append(tp)
        parsed.append(PR(vals, up, sp, sys.intern(zone or "unassigned"), dev, ifc))
        if fl:
            flags[idx] = fl
    meta = {"rows_total": len(rows), "column_count_mismatch": short}
    return Dataset(source, header, tuple(rows), tsl, parsed, flags, mapping, tz,
                   list(ts_formats) if ts_formats else None, meta)


def load_inventory(text, delimiter=","):
    """Inventory CSV columns: device,zone[,interface,speed_bps]. Returns dict usable by load_csv.
    Rows with an interface and speed_bps give per-interface configured speed."""
    inv = {"__speeds__": {}}
    rdr = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    for r in rdr:
        d = (r.get("device") or "").strip()
        if not d:
            continue
        if (r.get("zone") or "").strip():
            inv.setdefault(d, {})["zone"] = r["zone"].strip()
        if (r.get("interface") or "").strip() and (r.get("speed_bps") or "").strip():
            try:
                inv["__speeds__"][(d, r["interface"].strip())] = float(r["speed_bps"])
            except ValueError:
                pass
    return inv


def ts_report(ds):
    fmts = Counter(t["format"] or "UNPARSED" for t in ds.ts_parsed)
    flags = Counter(f for fl in ds.row_flags.values() for f in fl)
    return {
        "slash_census": slash_census(r.ts_raw for r in ds.rows),
        "formats": dict(fmts),
        "mixed_formats": len([f for f in fmts if f != "UNPARSED"]) > 1,
        "tz_assumed": ds.tz,
        "tz_sources": dict(Counter(t["tz_source"] for t in ds.ts_parsed if t["epoch_ms"] is not None)),
        "flag_counts": dict(flags),
        "unparseable_samples": [{"line": ds.rows[i].line, "ts_raw": ds.rows[i].ts_raw, "flags": ds.ts_parsed[i]["flags"]}
                                for i in range(len(ds.rows)) if ds.ts_parsed[i]["epoch_ms"] is None][:50],
    }
