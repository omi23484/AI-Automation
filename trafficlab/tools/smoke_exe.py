"""Smoke-test a built executable (or `python -m trafficlab`) end to end. Usage: python3 tools/smoke_exe.py PATH_TO_EXE [--expect-tier NAME]
Exercises: bundled web assets, API, synthetic data, process-pool analysis, non-UTC time zone (tzdata), device checks, tier banner, CLI."""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

exe = [sys.argv[1]] if len(sys.argv) > 1 and not sys.argv[1].endswith(".py") else [sys.executable, "-m", "trafficlab"]
want_tier = sys.argv[sys.argv.index("--expect-tier") + 1] if "--expect-tier" in sys.argv else None
PORT = 8790
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(os.environ, PYTHONPATH=ROOT)          # only matters for the `python -m trafficlab` mode
ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


def call(path, body=None):
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw[:1] in b"{[" else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


with tempfile.TemporaryDirectory() as td:
    r = subprocess.run(exe + ["tier", "list"], capture_output=True, text=True, cwd=td, env=ENV)
    check("CLI runs (tier list)", r.returncode == 0 and "medium" in r.stdout, r.stdout + r.stderr)
    r = subprocess.run(exe + ["--tier", "small", "tier", "show"], capture_output=True, text=True, cwd=td, env=ENV)
    check("built-in tiers resolve by name", '"max_devices": 25' in r.stdout, r.stdout + r.stderr)
    p = subprocess.Popen(exe + ["serve", "--port", str(PORT), "--db", os.path.join(td, "t.db")], cwd=td, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        code = None
        for _ in range(100):
            try:
                code, _ = call("/api/status")
                break
            except Exception:
                time.sleep(0.3)
        check("server starts", code == 200)
        code, html = call("/")
        check("bundled web assets served", code == 200 and b"trafficlab" in html)
        code, js = call("/app.js")
        check("bundled app.js served", code == 200 and len(js) > 20000)
        code, t = call("/api/tier")
        check("tier endpoint", code == 200 and (t["active"] or {}).get("name") == want_tier if want_tier else code == 200, str(t)[:100])
        code, j = call("/api/synth", {"mixed_formats": True})
        check("synthetic import", code == 200 and j["validation"]["rows"] > 50000, str(j)[:120])
        code, _ = call("/api/analyze", {"config": {"tz": "Asia/Kolkata"}, "workers": 2})
        check("analysis accepted (non-UTC tz => tzdata present)", code == 202)
        for _ in range(200):
            s = call("/api/status")[1]
            if s["state"] != "running":
                break
            time.sleep(0.3)
        check("analysis finished (process pool works frozen)", s["state"] == "done", str(s))
        code, f = call("/api/findings?hide_continuation=1")
        check("findings produced", code == 200 and len(f["findings"]) >= 6, str(len(f.get("findings", []))))
        code, fc = call("/api/forecasts")
        check("capacity outlook endpoint", code == 200 and "forecasts" in fc, str(fc)[:100])
        code, hs = call("/api/history/add", {})
        check("history add", code == 200 and hs["points_added"] > 1000, str(hs)[:120])
        code, hs = call("/api/history/add", {})
        check("history idempotent", code == 200 and hs["points_added"] == 0, str(hs)[:120])
        fid = f["findings"][0]["id"]
        code, fb = call("/api/feedback", {"finding_id": fid, "verdict": "real", "note": "smoke"})
        check("feedback", code == 200, str(fb)[:100])
        code, e = call("/api/slm/explain", {"finding_id": fid})
        check("local-model explainer is off by default", code == 400 and "disabled" in e["error"], str(e)[:100])
        cap = "COMMAND: show ip bgp summary\n\nBGP router identifier 10.1.1.1, local AS number 65001\n\nNeighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n10.1.1.3        4        65003       0       0        0    0    0 00:39:45 Idle     \n"
        code, j = call("/api/checks/upload", {"files": [{"name": "r1/show_ip_bgp_summary.txt", "text": cap}]})
        check("device checks", code == 200 and j["summary"]["by_severity"].get("critical") == 1, str(j))
        code, j = call("/api/export/report")
        check("report export", code == 200 and b"<!doctype html>" in j[:40].lower() if isinstance(j, bytes) else code == 200)
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()
print("\nALL PASS" if ok else "\nFAILURES")
sys.exit(0 if ok else 1)
