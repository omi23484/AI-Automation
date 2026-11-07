import json
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from helpers import *
from trafficlab import synth, ingest, counters, pipeline
from trafficlab.server import State, make_handler
from trafficlab.config import make_config


class Zones(unittest.TestCase):
    def test_inventory_assigns_zone_and_speed(self):
        inv = ingest.load_inventory("device,zone,interface,speed_bps\nR1,WAN,,\nR1,,Gi0,100000000\n")
        m = {"device": "d", "interface": "i", "timestamp": "t", "counters": [{"name": "in_bps", "column": "o", "bits": 64, "mult": 8, "unit": "bps"}]}
        ds = ingest.load_csv("t,d,i,o\n2026-01-05 00:00:00,R1,Gi0,1\n2026-01-05 00:05:00,R1,Gi0,2\n", m, ["%Y-%m-%d %H:%M:%S"], inventory=inv)
        sl, _ = counters.build_all(ds)
        self.assertEqual(sl[0].zone, "WAN")
        self.assertEqual(sl[0].speed_bps, 100000000.0)

    def test_zone_override_only_affects_that_zone(self):
        k0 = (28 * 86400 + 14 * 3600) // 300
        mod = lambda k, t, v: v * 1.5 if k0 <= k < k0 + 6 else v
        a = mk_series(daily_values(35, seed=61, mod=mod), key="W|I|in_bps", device="W", zone="WAN")
        b = mk_series(daily_values(35, seed=61, mod=mod), key="D|I|in_bps", device="D", zone="DC")
        cfg = make_config({"zones": {"WAN": {"anomaly": {"z_threshold": 1000, "ewma_L": 1000}}}})
        r = pipeline.analyze([a, b], cfg, workers=1)
        self.assertEqual({f["zone"] for f in r["findings"]}, {"DC"})


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = State(":memory:")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.st))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def req(self, path, body=None, headers=None, method=None):
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if body is None else json.dumps(body).encode(), headers=h, method=method)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_flow(self):
        code, j = self.req("/api/synth", {"mixed_formats": True})
        self.assertEqual(code, 200)
        self.assertGreater(j["validation"]["rows"], 50000)
        self.assertEqual(self.req("/api/analyze", {"config": {}, "workers": 1})[0], 202)
        for _ in range(100):
            time.sleep(0.2)
            s = self.req("/api/status")[1]
            if s["state"] != "running":
                break
        self.assertEqual(s["state"], "done", s)
        code, fj = self.req("/api/findings?hide_continuation=1")
        self.assertEqual(len(fj["findings"]), 8)
        code, ex = self.req("/api/explain?id=" + fj["findings"][0]["id"])
        self.assertEqual(code, 200)
        self.assertIn("evidence_pack", ex)
        code, ser = self.req("/api/series?key=SYN-ENT-SW1%7CGi1%2F0%2F1%7Cin_bps&max=500")
        self.assertTrue(ser["decimated"])
        self.assertLessEqual(len(ser["t"]), 500)
        self.assertEqual(len(ser["raw"]), len(ser["t"]))

    def test_bad_host_rejected(self):
        code, j = self.req("/api/status", headers={"Host": "evil.example"})
        self.assertEqual(code, 403)

    def test_csrf_text_plain_rejected(self):
        code, j = self.req("/api/crs", {"cr_id": "X"}, headers={"Content-Type": "text/plain"})
        self.assertEqual(code, 403)

    def test_cross_origin_rejected(self):
        code, j = self.req("/api/crs", {"cr_id": "X"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(code, 403)

    def test_cr_roundtrip_via_api(self):
        code, j = self.req("/api/crs", {"cr_id": "T1", "title": "x", "status": "Draft", "planned_start": "2026-01-10 00:00:00", "planned_end": "2026-01-10 01:00:00", "scope": [{"device": "A"}]})
        self.assertEqual(code, 200)
        code, j = self.req("/api/crs", {"cr_id": "T2", "planned_start": "nonsense"})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
