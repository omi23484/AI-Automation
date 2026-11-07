"""Local-only HTTP server (127.0.0.1) + JSON API for the offline UI. stdlib only.
Security: binds loopback; rejects requests whose Host header is not loopback (DNS rebinding);
no CORS headers; no file-path endpoints."""
import json
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import base64
from . import synth, ingest, counters, pipeline, report
from . import devcheck
from .devcheck import report as dc_report
from .config import make_config, DEFAULTS
from .store import CRStore, STATUSES
from .interpret import RULES
from .presets import PRESETS

WEB = os.path.join(os.path.dirname(__file__), "web")
MAX_BODY = 1024 * 1024 * 1024


class State:
    def __init__(self, db_path):
        self.lock = threading.Lock()
        self.store = CRStore(db_path)
        self.ds = None
        self.series = []
        self.smap = {}
        self.dq = None
        self.validation = None
        self.result = None
        self.job = {"state": "idle", "done": 0, "total": 0, "error": None}
        self.checks = None


def evidence_pack(st, fid_):
    f = next((x for x in st.result["findings"] if x["id"] == fid_), None) if st.result else None
    c = next((x for x in st.result["clusters"] if x["id"] == fid_), None) if st.result else None
    if f is None and c is None:
        return None
    if c:
        mem = [x for x in st.result["findings"] if x["id"] in c["members"]]
        return {"kind": "cluster", "cluster": c, "members": [{"id": m["id"], "device": m["device"], "interface": m["interface"], "metric": m["metric"],
                "window_raw": [m["window"]["start_raw"], m["window"]["end_raw"]], "numbers": m["numbers"]} for m in mem]}
    s = st.smap.get(f["series_key"])
    near = []
    if s:
        m = s.interval_ms or 0
        near = [x for x in s.excluded + s.events if x["start_ms"] <= f["window"]["end_ms"] + m and x["end_ms"] >= f["window"]["start_ms"] - m][:10]
    cl = next((x for x in st.result["clusters"] if f["id"] in x["members"]), None)
    return {"kind": "finding", "finding": {k: f[k] for k in ("id", "kind", "layer", "metric", "device", "interface", "zone", "severity", "direction", "window", "numbers", "math", "confidence")},
            "interpretation": f["interpretation"], "cr_candidates": f["cr_candidates"], "data_quality_near_window": near,
            "cluster": ({k: cl[k] for k in ("id", "devices", "zones", "mean_pearson_r", "label")} if cl else None)}


def explain(pack):
    """Deterministic explanation (NO language model). Format mirrors the SLM output contract."""
    if pack["kind"] == "cluster":
        c = pack["cluster"]
        return {"summary": f"{len(c['devices'])} devices show overlapping anomaly windows: {', '.join(c['devices'])} (zones {', '.join(c['zones'])}). mean r = {c['mean_pearson_r']}.",
                "ranked_causes": [{"cause": c["label"], "evidence": [c["id"]] + c["members"]}], "unknowns": ["Topology/shared dependency not provided", "Device clock skew not measured"],
                "suggested_checks": ["Check whether these devices share an upstream path, service or scheduled job in the window (verify on device)"]}
    f = pack["finding"]
    causes = [{"cause": i["claim"], "evidence": i["evidence"]} for i in pack["interpretation"] if i["rule"]]
    unknown = ["Root cause is not determined by this tool"] if causes else ["Unknown - insufficient evidence"]
    checks = ["Compare raw samples in the window (ts_raw) against interface error/drop counters and logs (verify command on platform)"]
    if pack["cr_candidates"]:
        checks.append("Review the candidate CR(s): scope, actual window, rollback plan")
    if pack["data_quality_near_window"]:
        checks.append("Confirm counter reset / gap events are not a polling artifact")
    return {"summary": f"{f['severity']} {f['kind']} on {f['device']} {f['interface']} {f['metric']} from {f['window']['start_raw']} to {f['window']['end_raw']} (raw timestamps).",
            "ranked_causes": causes, "evidence_cited": [f["id"]], "unknowns": unknown, "suggested_checks": checks}


def make_handler(st):
    class H(BaseHTTPRequestHandler):
        server_version = "trafficlab"

        def log_message(self, *a):
            pass

        def _host_ok(self):
            h = (self.headers.get("Host") or "").split(":")[0].strip("[]")
            return h in ("127.0.0.1", "localhost", "::1")

        def _send(self, code, body, ctype="application/json", headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or "json" in ctype else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("body too large")
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    return self._send(200, open(os.path.join(WEB, "index.html"), "rb").read(), "text/html")
                if u.path in ("/app.js", "/style.css"):
                    return self._send(200, open(os.path.join(WEB, u.path[1:]), "rb").read(), "text/javascript" if u.path.endswith("js") else "text/css")
                return self._send(*self.api_get(u.path, q))
            except Exception as e:
                traceback.print_exc()
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def _origin_ok(self):
            o = self.headers.get("Origin")
            if o is None:
                return True   # same-origin fetch from our own page or non-browser client
            host = self.headers.get("Host", "")
            return o in (f"http://{host}",)

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            # CSRF guard: a cross-origin page cannot send application/json without a preflight (which we never answer)
            if not (self.headers.get("Content-Type") or "").lower().startswith("application/json") or not self._origin_ok():
                return self._send(403, {"error": "POST requires Content-Type: application/json and same-origin"})
            try:
                return self._send(*self.api_post(urlparse(self.path).path, self._body()))
            except (ingest.IngestError, ValueError, KeyError) as e:
                self._send(400, {"error": f"{type(e).__name__}: {e}"})
            except Exception as e:
                traceback.print_exc()
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        # ---------------- GET ----------------
        def api_get(self, p, q):
            if p == "/api/defaults":
                return 200, {"config": DEFAULTS, "statuses": STATUSES, "rules": RULES, "presets": PRESETS, "synth_mapping32": synth.SYN_MAPPING32, "synth_mapping64": synth.SYN_MAPPING}
            if p == "/api/status":
                return 200, dict(st.job, has_data=st.ds is not None, has_result=st.result is not None)
            if p == "/api/validation":
                return (200, st.validation) if st.validation else (404, {"error": "no data imported"})
            if p == "/api/result":
                if not st.result:
                    return 404, {"error": "no result"}
                r = st.result
                zones = {}
                for s in r["series"]:
                    z = zones.setdefault(s["zone"], {"series": 0, "devices": set(), "points": 0, "findings": 0})
                    z["series"] += 1; z["devices"].add(s["device"]); z["points"] += s["n_points"]
                for f in r["findings"]:
                    if not f.get("continuation_of"):
                        zones.setdefault(f["zone"], {"series": 0, "devices": set(), "points": 0, "findings": 0})["findings"] += 1
                for z in zones.values():
                    z["devices"] = len(z["devices"])
                return 200, {"config": r["config"], "elapsed_s": r["elapsed_s"], "workers": r["workers"], "zones": zones,
                             "counts": {"findings": len(r["findings"]), "primary": sum(1 for f in r["findings"] if not f.get("continuation_of")),
                                        "clusters": len(r["clusters"]), "series": len(r["series"])}}
            if p == "/api/findings":
                if not st.result:
                    return 404, {"error": "no result"}
                kind = q.get("kind")
                fs = [f for f in st.result["findings"] if (not kind or f["kind"] == kind)]
                if q.get("hide_continuation") == "1":
                    fs = [f for f in fs if not f.get("continuation_of")]
                return 200, {"findings": fs, "clusters": st.result["clusters"] if not kind else []}
            if p == "/api/series_list":
                return 200, {"series": st.result["series"] if st.result else []}
            if p == "/api/series":
                s = st.smap.get(q.get("key"))
                if not s:
                    return 404, {"error": "unknown series"}
                t0 = int(q["t0"]) if q.get("t0") else s.ts_ms[0] if s.ts_ms else 0
                t1 = int(q["t1"]) if q.get("t1") else s.ts_ms[-1] if s.ts_ms else 0
                mx = int(q.get("max", 3000))
                idx = [i for i, t in enumerate(s.ts_ms) if t0 <= t <= t1]
                dec = False
                if len(idx) > mx:
                    dec = True
                    nb = mx // 2
                    size = len(idx) / nb
                    keep = []
                    for b in range(nb):
                        seg = idx[int(b * size): int((b + 1) * size)]
                        if seg:
                            lo, hi = min(seg, key=lambda i: s.rate[i]), max(seg, key=lambda i: s.rate[i])
                            keep += sorted({lo, hi})
                    idx = keep
                return 200, {"key": s.key, "unit": s.unit, "t": [s.ts_ms[i] for i in idx], "v": [s.rate[i] for i in idx], "raw": [s.ts_raw[i] for i in idx],
                             "method": [s.method[i] for i in idx], "decimated": dec, "excluded": [e for e in s.excluded if e["end_ms"] >= t0 and e["start_ms"] <= t1],
                             "speed_bps": s.speed_bps, "interval_ms": s.interval_ms, "span": [s.ts_ms[0], s.ts_ms[-1]] if s.ts_ms else None}
            if p == "/api/crs":
                return 200, {"crs": st.store.list(), "statuses": STATUSES}
            if p == "/api/crs/log":
                return 200, {"log": st.store.log(q.get("cr_id"))}
            if p == "/api/crs/export":
                return 200, st.store.export_json(), "application/json"
            if p == "/api/explain":
                pack = evidence_pack(st, q.get("id", ""))
                if pack is None:
                    return 404, {"error": "unknown id"}
                return 200, {"evidence_pack": pack, "explanation": explain(pack), "slm": "disabled (Phase 3 not built)"}
            if p == "/api/checks/result":
                return (200, st.checks) if st.checks else (200, {"empty": True})
            if p == "/api/export/devcheck":
                return (200, json.dumps({"format": "trafficlab-devcheck/1", "result": st.checks}, indent=1), "application/json") if st.checks else (404, {"error": "none"})
            if p == "/api/export/devcheck-report":
                return (200, dc_report.build(st.checks), "text/html") if st.checks else (404, {"error": "none"})
            if p == "/api/export/findings":
                if not st.result:
                    return 404, {"error": "no result"}
                body = json.dumps({"format": "trafficlab-findings/1", "validation": st.validation, "result": st.result, "devcheck": st.checks}, indent=1)
                return 200, body, "application/json"
            if p == "/api/export/report":
                if not st.result:
                    return 404, {"error": "no result"}
                return 200, report.build_report(st.result, st.validation, st.smap), "text/html"
            return 404, {"error": "not found"}

        # ---------------- POST ----------------
        def api_post(self, p, b):
            if p == "/api/synth":
                text, man = synth.generate(mixed_formats=bool(b.get("mixed_formats", True)))
                mapping = synth.SYN_MAPPING32 if b.get("bits32_wan", True) else synth.SYN_MAPPING
                self._load(text, mapping, ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"], "UTC", ",", None, "SYNTHETIC (generated in memory)")
                st.store.import_json(synth.synthetic_crs())
                return 200, {"validation": st.validation, "manifest": man}
            if p == "/api/import":
                inv = ingest.load_inventory(b["inventory_text"]) if b.get("inventory_text") else None
                self._load(b["csv_text"], b["mapping"], b.get("ts_formats") or None, b.get("tz") or "UTC", b.get("delimiter") or ",", inv, b.get("source") or "upload")
                return 200, {"validation": st.validation}
            if p == "/api/analyze":
                with st.lock:
                    if st.job["state"] == "running":
                        return 409, {"error": "analysis already running"}
                    if st.ds is None:
                        return 400, {"error": "import data first"}
                    st.job = {"state": "running", "done": 0, "total": len(st.series), "error": None}
                cfg = make_config(b.get("config"))
                threading.Thread(target=self._run, args=(cfg, b.get("workers")), daemon=True).start()
                return 202, {"started": True}
            if p == "/api/checks/upload":
                pol = b.get("pass_policy") or "latest"
                if b.get("zip_b64"):
                    caps = devcheck.load_zip_bytes(base64.b64decode(b["zip_b64"]), pol)
                else:
                    dflt = (b.get("device") or "").strip()
                    items = [((f["name"] if "/" in f["name"] or not dflt else f"{dflt}/{f['name']}"), f["text"]) for f in b.get("files", [])]
                    caps = devcheck.load_items(items, pol)
                if not caps:
                    return 400, {"error": "no usable captures: files need a 'COMMAND: show ...' first line, 'host# show ...' prompts, or show_*.txt names, inside <device>/ folders"}
                cfg = make_config({"devcheck": {k: v for k, v in (b.get("devcheck") or {}).items()}})
                st.checks = devcheck.analyze_captures(caps, cfg)
                return 200, {"summary": st.checks["summary"]}
            if p == "/api/crs":
                return 200, {"cr": st.store.upsert(b)}
            if p == "/api/crs/link":
                st.store.link(b["cr_id"], b["finding_id"])
                return 200, {"cr": st.store.get(b["cr_id"])}
            if p == "/api/crs/import":
                return 200, {"imported": st.store.import_json(b)}
            return 404, {"error": "not found"}

        def _load(self, text, mapping, fmts, tz, delim, inv, source):
            ds = ingest.load_csv(text, mapping, fmts, tz, delim, inv, source)
            cfg = make_config()
            series, dq = counters.build_all(ds, cfg)
            with st.lock:
                st.ds, st.series, st.dq = ds, series, dq
                st.smap = {s.key: s for s in series}
                st.validation = pipeline.validation_report(ds, series, dq)
                st.result = None
                st.job = {"state": "idle", "done": 0, "total": 0, "error": None}

        def _run(self, cfg, workers):
            try:
                # rebuild series with this config's counter settings (gap_factor etc.)
                series, dq = counters.build_all(st.ds, cfg)
                st.series, st.smap, st.dq = series, {s.key: s for s in series}, dq
                st.validation = pipeline.validation_report(st.ds, series, dq)
                st.job["total"] = len(series)
                def prog(d, t):
                    st.job["done"], st.job["total"] = d, t
                st.result = pipeline.analyze(series, cfg, st.store, workers, prog)
                st.job["state"] = "done"
            except Exception as e:
                traceback.print_exc()
                st.job.update(state="error", error=f"{type(e).__name__}: {e}")
    return H


def serve(host="127.0.0.1", port=8765, db="trafficlab.db"):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("refusing to bind non-loopback address (tool is local-only)")
    st = State(db)
    httpd = ThreadingHTTPServer((host, port), make_handler(st))
    print(f"trafficlab on http://{host}:{port}/  (CR db: {os.path.abspath(db)})  Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
