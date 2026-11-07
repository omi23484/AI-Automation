"""Persisted history (SQLite): derived rate series kept across imports so new data is scored against everything seen before,
and big inputs can be imported in chunks. Raw ts strings are stored exactly as given (`ts_raw`), together with the format that parsed them.
Rules: re-importing identical points is a no-op; a point whose value differs from the stored one is recorded in `conflicts` and NEVER overwrites;
gaps between imports are marked as gaps (never filled); one rate interval at an import boundary is lost unless the imports overlap by >= 1 poll."""
import hashlib
import json
import sqlite3
import time
from collections import defaultdict

from .counters import Series
from . import tier

SCHEMA = """
CREATE TABLE IF NOT EXISTS h_batches(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, sha256 TEXT, imported_utc TEXT, series INTEGER, points_added INTEGER, duplicates INTEGER, conflicts INTEGER, t_min INTEGER, t_max INTEGER);
CREATE TABLE IF NOT EXISTS h_series(series_key TEXT PRIMARY KEY, device TEXT, interface TEXT, zone TEXT, metric TEXT, unit TEXT, kind TEXT, speed_bps REAL, interval_ms INTEGER, tz TEXT);
CREATE TABLE IF NOT EXISTS h_points(series_key TEXT, ts_ms INTEGER, ts_raw TEXT, ts_fmt TEXT, rate REAL, method TEXT, batch_id INTEGER, PRIMARY KEY(series_key, ts_ms)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS h_excluded(series_key TEXT, start_ms INTEGER, end_ms INTEGER, type TEXT, detail TEXT, start_raw TEXT, end_raw TEXT, batch_id INTEGER, UNIQUE(series_key, start_ms, end_ms, type));
CREATE TABLE IF NOT EXISTS h_conflicts(series_key TEXT, ts_ms INTEGER, stored REAL, incoming REAL, batch_id INTEGER);
"""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class HistoryStore:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def devices(self):
        return {r[0] for r in self.db.execute("SELECT DISTINCT device FROM h_series")}

    def add_series(self, series_list, source="import", digest=None):
        incoming = {s.device for s in series_list}
        tier.check("devices", len(self.devices() | incoming))        # the tier counts devices across the whole history
        cur = self.db.execute("INSERT INTO h_batches(source, sha256, imported_utc, series, points_added, duplicates, conflicts) VALUES(?,?,?,?,0,0,0)", (source, digest, _now(), len(series_list)))
        bid = cur.lastrowid
        added = dup = conf = 0
        tmin, tmax = None, None
        for s in series_list:
            self.db.execute("INSERT OR REPLACE INTO h_series VALUES(?,?,?,?,?,?,?,?,?,?)", (s.key, s.device, s.interface, s.zone, s.metric, s.unit, s.kind, s.speed_bps, s.interval_ms, s.tz_assumed))
            have = {r[0]: r[1] for r in self.db.execute("SELECT ts_ms, rate FROM h_points WHERE series_key=? AND ts_ms BETWEEN ? AND ?", (s.key, s.ts_ms[0], s.ts_ms[-1]))} if s.ts_ms else {}
            rows = []
            for t, raw, fmt, v, m in zip(s.ts_ms, s.ts_raw, s.ts_fmt, s.rate, s.method):
                if t in have:
                    if abs(have[t] - v) <= 1e-9 * max(1.0, abs(v)):
                        dup += 1
                    else:
                        conf += 1
                        self.db.execute("INSERT INTO h_conflicts VALUES(?,?,?,?,?)", (s.key, t, have[t], v, bid))
                    continue
                rows.append((s.key, t, raw, fmt, v, m, bid))
            self.db.executemany("INSERT INTO h_points VALUES(?,?,?,?,?,?,?)", rows)
            added += len(rows)
            for e in s.excluded:
                self.db.execute("INSERT OR IGNORE INTO h_excluded VALUES(?,?,?,?,?,?,?,?)", (s.key, e["start_ms"], e["end_ms"], e["type"], e.get("detail", ""), e.get("start_raw", ""), e.get("end_raw", ""), bid))
            if s.ts_ms:
                tmin = s.ts_ms[0] if tmin is None else min(tmin, s.ts_ms[0])
                tmax = s.ts_ms[-1] if tmax is None else max(tmax, s.ts_ms[-1])
        self.db.execute("UPDATE h_batches SET points_added=?, duplicates=?, conflicts=?, t_min=?, t_max=? WHERE id=?", (added, dup, conf, tmin, tmax, bid))
        self.db.commit()
        return {"batch_id": bid, "series": len(series_list), "points_added": added, "duplicates_skipped": dup, "conflicts_recorded": conf}

    def summary(self):
        r = self.db.execute("SELECT COUNT(*), COUNT(DISTINCT device) FROM h_series").fetchone()
        p = self.db.execute("SELECT COUNT(*), MIN(ts_ms), MAX(ts_ms) FROM h_points").fetchone()
        return {"series": r[0], "devices": r[1], "points": p[0], "t_min": p[1], "t_max": p[2], "conflicts": self.db.execute("SELECT COUNT(*) FROM h_conflicts").fetchone()[0],
                "batches": [dict(zip(("id", "source", "imported_utc", "series", "points_added", "duplicates", "conflicts", "t_min", "t_max"), x)) for x in
                            self.db.execute("SELECT id, source, imported_utc, series, points_added, duplicates, conflicts, t_min, t_max FROM h_batches ORDER BY id")]}

    def conflicts(self, limit=100):
        return [dict(zip(("series_key", "ts_ms", "stored", "incoming", "batch_id"), x)) for x in self.db.execute("SELECT * FROM h_conflicts LIMIT ?", (limit,))]

    def load_series(self, window_days=None, keys=None):
        tmax = self.db.execute("SELECT MAX(ts_ms) FROM h_points").fetchone()[0]
        if tmax is None:
            return []
        t0 = tmax - int(window_days * 86_400_000) if window_days else -1
        total = self.db.execute("SELECT COUNT(*) FROM h_points WHERE ts_ms >= ?", (t0,)).fetchone()[0]
        tier.check("rows", total)                                      # technical guard: use window_days or downsample if this fires
        out = []
        metas = self.db.execute("SELECT * FROM h_series").fetchall()
        for key, dev, ifc, zone, metric, unit, kind, speed, iv, tz in metas:
            if keys is not None and key not in keys:
                continue
            s = Series(key=key, device=dev, interface=ifc, zone=zone, metric=metric, unit=unit, kind=kind, speed_bps=speed, interval_ms=iv, tz_assumed=tz)
            for t, raw, fmt, v, m in self.db.execute("SELECT ts_ms, ts_raw, ts_fmt, rate, method FROM h_points WHERE series_key=? AND ts_ms>=? ORDER BY ts_ms", (key, t0)):
                s.ts_ms.append(t); s.ts_raw.append(raw); s.ts_fmt.append(fmt); s.rate.append(v); s.method.append(m)
            if not s.ts_ms:
                continue
            s.n_samples = len(s.ts_ms) + 1
            for st, en, ty, de, sr, er in self.db.execute("SELECT start_ms, end_ms, type, detail, start_raw, end_raw FROM h_excluded WHERE series_key=? AND end_ms>=?", (key, t0)):
                s.excluded.append({"start_ms": st, "end_ms": en, "type": ty, "detail": de, "start_raw": sr, "end_raw": er})
            known = {(e["start_ms"], e["end_ms"]) for e in s.excluded}
            gap = 1.5 * (iv or 0)
            for i in range(1, len(s.ts_ms)):                           # gaps between imports: marked, never filled
                if iv and s.ts_ms[i] - s.ts_ms[i - 1] > gap and (s.ts_ms[i - 1], s.ts_ms[i]) not in known and not any(e["start_ms"] <= s.ts_ms[i - 1] and e["end_ms"] >= s.ts_ms[i] for e in s.excluded):
                    s.excluded.append({"start_ms": s.ts_ms[i - 1], "end_ms": s.ts_ms[i], "start_raw": s.ts_raw[i - 1], "end_raw": s.ts_raw[i], "type": "gap",
                                       "detail": "no stored samples between these two points (missing data or imports that do not overlap)"})
            s.excluded.sort(key=lambda e: e["start_ms"])
            out.append(s)
        tier.check("devices", len({x.device for x in out}))
        return out

    def apply_retention(self, days):
        tmax = self.db.execute("SELECT MAX(ts_ms) FROM h_points").fetchone()[0]
        if tmax is None:
            return {"deleted_points": 0}
        cut = tmax - int(days * 86_400_000)
        n = self.db.execute("DELETE FROM h_points WHERE ts_ms < ?", (cut,)).rowcount
        self.db.execute("DELETE FROM h_excluded WHERE end_ms < ?", (cut,))
        self.db.execute("DELETE FROM h_series WHERE series_key NOT IN (SELECT DISTINCT series_key FROM h_points)")
        self.db.commit()
        return {"deleted_points": n, "kept_from_ms": cut}

    def clear(self):
        for t in ("h_batches", "h_series", "h_points", "h_excluded", "h_conflicts"):
            self.db.execute(f"DELETE FROM {t}")
        self.db.commit()
