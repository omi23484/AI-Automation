"""Tiers: limits and feature switches (soft enforcement), bundle builder, manifest verification."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from helpers import *
from trafficlab import tier, ingest, counters, weekly, profile, synth, report
from trafficlab.config import make_config
from trafficlab.devcheck import analyze_captures, from_file
from trafficlab.store import CRStore
from trafficlab.server import State, make_handler
from test_devcheck import BGP
from test_weekly import build_files
from test_profile_custom import PARSER, RULE

ROOT = os.path.join(os.path.dirname(__file__), "..")
MAP = {"device": "d", "interface": "i", "timestamp": "t", "counters": [{"name": "x", "column": "o", "bits": 64, "mult": 8, "unit": "bps"}]}


def T(limits=None, features=None, name="t"):
    return tier.Tier({"name": name, "limits": limits or {}, "features": features or {}})


class Base(unittest.TestCase):
    def tearDown(self):
        tier.activate(None)


class Definition(Base):
    def test_validation(self):
        for bad in ({"limitz": {}}, {"limits": {"max_cats": 1}}, {"limits": {"max_rows": -1}}, {"limits": {"max_rows": "9"}}, {"features": {"magic": True}}, []):
            with self.assertRaises(ValueError, msg=str(bad)):
                tier.Tier(bad)

    def test_proposed_tiers_ship_and_are_ordered(self):
        t = {n: tier.load(os.path.join(ROOT, "tiers", f"{n}.json")) for n in ("small", "medium", "large")}
        self.assertTrue(all(x.proposal for x in t.values()))                        # flagged as proposals until the owner dictates
        for k in ("max_devices", "max_series", "max_rows", "max_captures"):
            self.assertLess(t["small"].limits[k], t["medium"].limits[k])
            self.assertLess(t["medium"].limits[k], t["large"].limits[k])

    def test_no_tier_means_no_limits(self):
        tier.activate(None)
        tier.check("rows", 10 ** 12)
        tier.require("devcheck")

    def test_resolve_env_and_missing(self):
        os.environ["TRAFFICLAB_TIER"] = "small"
        try:
            self.assertEqual(tier.resolve().name, "small")
            os.environ["TRAFFICLAB_TIER"] = "nope"
            with self.assertRaises(ValueError):
                tier.resolve()
        finally:
            del os.environ["TRAFFICLAB_TIER"]


class Limits(Base):
    def csv(self, n):
        return "t,d,i,o\n" + "".join(f"2026-01-05 00:{k % 60:02d}:00,d{k % 3},e1,{k}\n" for k in range(n))

    def test_rows_limit_refuses_and_says_so(self):
        tier.activate(T({"max_rows": 50}))
        ingest.load_csv(self.csv(50), MAP, ["%Y-%m-%d %H:%M:%S"])                   # exactly at the limit is fine
        with self.assertRaises(tier.TierError) as e:
            ingest.load_csv(self.csv(51), MAP, ["%Y-%m-%d %H:%M:%S"])
        self.assertIn("more than 50", str(e.exception))
        self.assertIn("tier 't'", str(e.exception))

    def test_devices_and_series_limits(self):
        ds = ingest.load_csv(self.csv(30), MAP, ["%Y-%m-%d %H:%M:%S"])              # 3 devices x 1 iface x 1 metric
        tier.activate(T({"max_devices": 2}))
        with self.assertRaises(tier.TierError) as e:
            counters.build_all(ds)
        self.assertIn("devices", str(e.exception))
        tier.activate(T({"max_series": 2}))
        with self.assertRaises(tier.TierError):
            counters.build_all(ds)
        tier.activate(T({"max_devices": 3, "max_series": 3, "max_zones": 1}))
        counters.build_all(ds)

    def test_weekly_limits(self):
        tier.activate(T({"max_series": 3}))
        with self.assertRaises(tier.TierError):
            weekly.build_series(build_files(8), make_config())

    def test_devcheck_limits(self):
        caps = from_file(BGP, "r1", "a.txt") + from_file(BGP, "r2", "b.txt")
        tier.activate(T({"max_devices": 1}))
        with self.assertRaises(tier.TierError):
            analyze_captures(caps)
        tier.activate(T({"max_captures": 1}))
        with self.assertRaises(tier.TierError):
            analyze_captures(caps)

    def test_cr_limit(self):
        tier.activate(T({"max_cr": 2}))
        st = CRStore()
        for i in range(2):
            st.upsert({"cr_id": f"C{i}"})
        st.upsert({"cr_id": "C0", "title": "edit existing is fine"})
        with self.assertRaises(tier.TierError):
            st.upsert({"cr_id": "C9"})
        self.assertEqual(len(st.list()), 2)                                          # nothing partially written


class Features(Base):
    def test_each_switch(self):
        text = "t,d,i,o\n2026-01-05 00:00:00,d,e,1\n"
        tier.activate(T(features={"poll_mode": False}))
        with self.assertRaises(tier.TierError):
            ingest.load_csv(text, MAP, ["%Y-%m-%d %H:%M:%S"])
        tier.activate(T(features={"weekly_mode": False}))
        with self.assertRaises(tier.TierError):
            weekly.build_series(build_files(2), make_config())
        tier.activate(T(features={"devcheck": False}))
        with self.assertRaises(tier.TierError):
            analyze_captures(from_file(BGP, "r1", "a.txt"))
        tier.activate(T(features={"custom_rules": False}))
        analyze_captures(from_file(BGP, "r1", "a.txt"))                              # built-in rules still work
        with self.assertRaises(tier.TierError):
            analyze_captures(from_file(BGP, "r1", "a.txt"), make_config({"devcheck": {"custom_parsers": [PARSER], "custom_rules": [RULE]}}))
        tier.activate(T(features={"profiles": False}))
        with self.assertRaises(tier.TierError):
            profile.load({})
        tier.activate(T(features={"report_export": False}))
        with self.assertRaises(tier.TierError):
            report.build_report({"findings": [], "clusters": [], "series": [], "config": {}}, {"source": "x", "issues": [], "timestamps": {"formats": {}, "tz_assumed": "UTC"}})


class ServerTier(Base):
    def test_tier_endpoint_and_export_gate(self):
        tier.activate(T({"max_rows": 100}, {"report_export": False}, name="demo"))
        st = State(":memory:")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            def get(p):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}{p}") as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read())
            code, j = get("/api/tier")
            self.assertEqual((code, j["active"]["name"], j["active"]["limits"]["max_rows"]), (200, "demo", 100))
            code, j = get("/api/export/findings")
            self.assertEqual(code, 400)
            self.assertIn("not included in tier 'demo'", j["error"])
        finally:
            httpd.shutdown()


class Bundle(Base):
    def run_py(self, cwd, *args):
        return subprocess.run([sys.executable, "-W", "ignore", "-m", "trafficlab", *args], cwd=cwd, capture_output=True, text=True)

    def test_bundle_build_verify_and_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            prof = os.path.join(td, "p.json")
            json.dump({"name": "cust", "config": {"zone_map": [{"match": "*", "zone": "Z"}]}}, open(prof, "w"))
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_bundle.py"), "--tier", "small", "--name", "acme", "--profile", prof, "--out", td, "--final"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            zp = os.path.join(td, "trafficlab-acme-small.zip")
            zipfile.ZipFile(zp).extractall(td)
            b = os.path.join(td, "trafficlab-acme-small")
            names = set(os.listdir(b))
            self.assertTrue({"trafficlab", "docs", "profiles", "tier.json", "MANIFEST.sha256", "README-FIRST.txt"} <= names)
            self.assertFalse({"tests", "tools", "captures"} & names)                 # no dev artifacts shipped
            self.assertFalse(os.path.exists(os.path.join(b, "docs", "DEVELOPMENT-NOTES.md")))
            self.assertFalse(json.load(open(os.path.join(b, "tier.json")))["proposal"])   # --final clears the proposal flag
            v = self.run_py(b, "verify")
            self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
            show = self.run_py(b, "tier", "show")                                      # picks up tier.json next to the package, no flags
            self.assertEqual(json.loads(show.stdout)["name"], "small")
            open(os.path.join(b, "trafficlab", "stats.py"), "a").write("\n# edited\n")
            v = self.run_py(b, "verify")
            self.assertEqual(v.returncode, 1)
            self.assertIn("MODIFIED trafficlab/stats.py", v.stdout)

    def test_bundle_enforces_its_tier_from_the_cli(self):
        with tempfile.TemporaryDirectory() as td:
            t = os.path.join(td, "tiny.json")
            json.dump({"name": "tiny", "limits": {"max_rows": 10}}, open(t, "w"))
            text, _ = synth.generate_collector(days=2)
            open(os.path.join(td, "d.csv"), "w").write(text)
            r = subprocess.run([sys.executable, "-W", "ignore", "-m", "trafficlab", "--tier", t, "analyze", os.path.join(td, "d.csv"), "--preset", "nexus_collect_utilization", "--out", td], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("tier 'tiny' allows at most 10 rows", r.stderr)


if __name__ == "__main__":
    unittest.main()
