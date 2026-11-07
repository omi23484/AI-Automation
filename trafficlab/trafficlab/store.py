"""Module 3: CR tracker on SQLite (stdlib). Local file, export/import JSON, change log.
Windows are stored as raw string + parsed epoch (same integrity rules as traffic data)."""
import json
import sqlite3
import time

from .timeparse import parse_ts
from . import tier

STATUSES = ["Draft", "Approved", "Scheduled", "In Progress", "Implemented", "Rolled Back", "Closed", "Cancelled"]
SCALARS = ["title", "description", "status", "owner", "risk", "rollback_plan", "notes"]
WINDOWS = ["planned_start", "planned_end", "actual_start", "actual_end"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS crs(
 cr_id TEXT PRIMARY KEY, title TEXT, description TEXT, status TEXT, owner TEXT, risk TEXT,
 rollback_plan TEXT, notes TEXT, tz TEXT DEFAULT 'UTC',
 planned_start_raw TEXT, planned_start_ms INTEGER, planned_end_raw TEXT, planned_end_ms INTEGER,
 actual_start_raw TEXT, actual_start_ms INTEGER, actual_end_raw TEXT, actual_end_ms INTEGER,
 created_utc TEXT, updated_utc TEXT);
CREATE TABLE IF NOT EXISTS cr_scope(cr_id TEXT, device TEXT, interface TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS cr_findings(cr_id TEXT, finding_id TEXT, UNIQUE(cr_id, finding_id));
CREATE TABLE IF NOT EXISTS cr_log(id INTEGER PRIMARY KEY AUTOINCREMENT, cr_id TEXT, ts_utc TEXT, actor TEXT, field TEXT, old TEXT, new TEXT);
"""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class CRStore:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _log(self, cr_id, field, old, new, actor):
        self.db.execute("INSERT INTO cr_log(cr_id,ts_utc,actor,field,old,new) VALUES(?,?,?,?,?,?)",
                        (cr_id, _now(), actor, field, None if old is None else str(old), None if new is None else str(new)))

    def _parse_windows(self, d, tz, fmts):
        out = {}
        for w in WINDOWS:
            raw = d.get(w)
            if raw in (None, ""):
                out[w + "_raw"], out[w + "_ms"] = None, None
                continue
            tp = parse_ts(raw, fmts, tz)
            if tp["epoch_ms"] is None:
                raise ValueError(f"{w}: cannot parse {raw!r} ({tp['flags']}); not stored")
            out[w + "_raw"], out[w + "_ms"] = raw, tp["epoch_ms"]
        return out

    def upsert(self, d, actor="user", fmts=None):
        cr_id = (d.get("cr_id") or "").strip()
        if not cr_id:
            raise ValueError("cr_id required")
        if d.get("status") and d["status"] not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        tz = d.get("tz") or "UTC"
        win = self._parse_windows(d, tz, fmts)
        old = self.get(cr_id)
        row = {k: d.get(k, "") or "" for k in SCALARS}
        row.update(win)
        row["tz"] = tz
        if old is None:
            tier.check("cr", self.db.execute("SELECT COUNT(*) FROM crs").fetchone()[0] + 1)
            cols = ["cr_id"] + list(row) + ["created_utc", "updated_utc"]
            vals = [cr_id] + list(row.values()) + [_now(), _now()]
            self.db.execute(f"INSERT INTO crs({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
            self._log(cr_id, "created", None, row.get("title"), actor)
        else:
            for k, v in row.items():
                if old.get(k) != v and not (old.get(k) in (None, "") and v in (None, "")):
                    self._log(cr_id, k, old.get(k), v, actor)
            sets = ",".join(f"{k}=?" for k in row) + ",updated_utc=?"
            self.db.execute(f"UPDATE crs SET {sets} WHERE cr_id=?", list(row.values()) + [_now(), cr_id])
        if "scope" in d:
            before = sorted((x["device"], x["interface"]) for x in self.scope(cr_id))
            self.db.execute("DELETE FROM cr_scope WHERE cr_id=?", (cr_id,))
            for sc in d["scope"]:
                self.db.execute("INSERT INTO cr_scope VALUES(?,?,?)", (cr_id, sc["device"], sc.get("interface", "") or ""))
            after = sorted((sc["device"], sc.get("interface", "") or "") for sc in d["scope"])
            if before != after:
                self._log(cr_id, "scope", before, after, actor)
        self.db.commit()
        return self.get(cr_id)

    def scope(self, cr_id):
        return [dict(r) for r in self.db.execute("SELECT device,interface FROM cr_scope WHERE cr_id=?", (cr_id,))]

    def get(self, cr_id):
        r = self.db.execute("SELECT * FROM crs WHERE cr_id=?", (cr_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["scope"] = self.scope(cr_id)
        d["linked_findings"] = [x[0] for x in self.db.execute("SELECT finding_id FROM cr_findings WHERE cr_id=?", (cr_id,))]
        return d

    def list(self):
        return [self.get(r[0]) for r in self.db.execute("SELECT cr_id FROM crs ORDER BY cr_id")]

    def link(self, cr_id, finding_id, actor="user"):
        if self.get(cr_id) is None:
            raise ValueError("unknown cr")
        self.db.execute("INSERT OR IGNORE INTO cr_findings VALUES(?,?)", (cr_id, finding_id))
        self._log(cr_id, "link_finding", None, finding_id, actor)
        self.db.commit()

    def log(self, cr_id=None):
        q, a = "SELECT * FROM cr_log", ()
        if cr_id:
            q, a = q + " WHERE cr_id=?", (cr_id,)
        return [dict(r) for r in self.db.execute(q + " ORDER BY id", a)]

    def export_json(self):
        return {"format": "trafficlab-crs/1", "exported_utc": _now(), "crs": self.list(), "log": self.log()}

    def import_json(self, obj, actor="import"):
        if obj.get("format") != "trafficlab-crs/1":
            raise ValueError("not a trafficlab-crs/1 file")
        n = 0
        for c in obj["crs"]:
            d = dict(c)
            tz = d.get("tz") or "UTC"
            for w in WINDOWS:           # re-parse from RAW strings; ms in file is not trusted
                d[w] = c.get(w + "_raw")
            self.upsert(d, actor=actor)
            for fid_ in c.get("linked_findings", []):
                self.db.execute("INSERT OR IGNORE INTO cr_findings VALUES(?,?)", (c["cr_id"], fid_))
            n += 1
        self.db.commit()
        return n
