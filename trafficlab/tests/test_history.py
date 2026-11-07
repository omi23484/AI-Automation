import unittest
from helpers import *
from trafficlab import synth, ingest, counters, pipeline, tier
from trafficlab.history import HistoryStore
from trafficlab.counters import Series

FMTS = ["%Y-%m-%d %H:%M:%S"]


def chunks(text, n_chunks, overlap_polls=1):
    """Split the synthetic CSV by time into n chunks, each overlapping the previous one by whole polls (so no interval is lost)."""
    head, *rows = text.strip().splitlines()
    stamps = sorted({r.split(",", 1)[0] for r in rows if r[0].isdigit()})
    cut = len(stamps) // n_chunks
    out = []
    for i in range(n_chunks):
        lo = stamps[max(0, i * cut - overlap_polls)]
        hi = stamps[min(len(stamps) - 1, (i + 1) * cut - 1)] if i < n_chunks - 1 else stamps[-1]
        out.append(head + "\n" + "\n".join(r for r in rows if r[0].isdigit() and lo <= r.split(",", 1)[0] <= hi) + "\n")
    return out


class Store(unittest.TestCase):
    def setUp(self):
        self.h = HistoryStore()

    def tearDown(self):
        tier.activate(None)

    def test_roundtrip_preserves_raw_strings_and_methods(self):
        s = mk_series([1, 2, 3, 4, 5])
        s.excluded.append({"start_ms": 1, "end_ms": 2, "type": "reset", "detail": "d", "start_raw": "a", "end_raw": "b"})
        rep = self.h.add_series([s], "t")
        self.assertEqual(rep["points_added"], 5)
        back = self.h.load_series()[0]
        self.assertEqual(back.ts_raw, s.ts_raw)
        self.assertEqual(back.ts_fmt, s.ts_fmt)
        self.assertEqual(back.rate, s.rate)
        self.assertEqual(back.method, s.method)
        self.assertEqual(back.excluded[0]["type"], "reset")

    def test_reimport_is_idempotent(self):
        s = mk_series([1, 2, 3])
        self.h.add_series([s])
        rep = self.h.add_series([s])
        self.assertEqual((rep["points_added"], rep["duplicates_skipped"], rep["conflicts_recorded"]), (0, 3, 0))
        self.assertEqual(self.h.summary()["points"], 3)

    def test_conflict_recorded_never_overwritten(self):
        a, b = mk_series([1, 2, 3]), mk_series([1, 99, 3])
        self.h.add_series([a])
        rep = self.h.add_series([b])
        self.assertEqual(rep["conflicts_recorded"], 1)
        self.assertEqual(self.h.load_series()[0].rate, [1.0, 2.0, 3.0])
        c = self.h.conflicts()[0]
        self.assertEqual((c["stored"], c["incoming"]), (2.0, 99.0))

    def test_gap_between_non_overlapping_imports_is_marked_not_filled(self):
        a = mk_series([1, 2, 3], start_ms=T0_MS)
        b = mk_series([4, 5, 6], start_ms=T0_MS + 100 * 300000)
        self.h.add_series([a]); self.h.add_series([b])
        s = self.h.load_series()[0]
        self.assertEqual(len(s.rate), 6)                                   # nothing invented
        self.assertEqual([e["type"] for e in s.excluded], ["gap"])

    def test_window_and_retention(self):
        s = mk_series(list(range(1000)))
        self.h.add_series([s])
        w = self.h.load_series(window_days=1)[0]                           # 288 polls/day
        self.assertEqual(len(w.rate), 289)
        r = self.h.apply_retention(1)
        self.assertEqual(r["deleted_points"], 1000 - 289)
        self.assertEqual(self.h.summary()["points"], 289)

    def test_tier_counts_devices_across_whole_history(self):
        tier.activate(tier.Tier({"name": "t", "limits": {"max_devices": 2}}))
        self.h.add_series([mk_series([1, 2, 3], key="A|I|m", device="A")])
        self.h.add_series([mk_series([1, 2, 3], key="B|I|m", device="B")])
        with self.assertRaises(tier.TierError):
            self.h.add_series([mk_series([1, 2, 3], key="C|I|m", device="C")])
        self.assertEqual(self.h.summary()["devices"], 2)                   # refused import wrote no series
        self.h.add_series([mk_series([4, 5], key="A|I|m", device="A", start_ms=T0_MS + 10 ** 7)])   # same device again is fine

    def test_safety_guard_on_load(self):
        self.h.add_series([mk_series(list(range(50)))])
        old = dict(tier.SAFETY)
        tier.SAFETY["rows"] = 10
        try:
            with self.assertRaises(tier.TierError):
                self.h.load_series()
            self.assertLessEqual(len(self.h.load_series(window_days=0.01)[0].rate), 10)         # a window under the cap loads fine
        finally:
            tier.SAFETY.update(old)


class Chunked(unittest.TestCase):
    def test_chunked_import_gives_same_findings_as_single_import(self):
        text, man = synth.generate(mixed_formats=False)
        ds = ingest.load_csv(text, synth.SYN_MAPPING32, FMTS)
        whole, _ = counters.build_all(ds)
        base = pipeline.analyze(whole, workers=1)
        h = HistoryStore()
        for part in chunks(text, 5):
            sl, _ = counters.build_all(ingest.load_csv(part, synth.SYN_MAPPING32, FMTS))
            h.add_series(sl, "chunk")
        s = h.summary()
        self.assertEqual(s["conflicts"], 0)
        self.assertEqual(s["series"], len(whole))
        merged = h.load_series()
        self.assertEqual(sum(len(x.rate) for x in merged), sum(len(x.rate) for x in whole))      # no interval lost thanks to the 1-poll overlap
        res = pipeline.analyze(merged, workers=1)
        prim = lambda r: sorted((f["device"], f["metric"], f["kind"], f["window"]["start_raw"], f["window"]["end_raw"]) for f in r["findings"] if not f.get("continuation_of"))
        self.assertEqual(prim(res), prim(base))
        self.assertEqual(len(res["clusters"]), len(base["clusters"]))

    def test_second_import_is_scored_against_stored_history(self):
        """Import 28 days, then only 7 more days containing a spike: the spike is found because earlier history is kept."""
        k0 = (33 * 86400 + 14 * 3600) // 300
        vals = daily_values(35, seed=8, mod=lambda k, t, v: v * 4.0 if k0 <= k < k0 + 6 else v)
        full = mk_series(vals)
        first = mk_series(vals[: 28 * 288 + 1])
        second = mk_series(vals[28 * 288:], start_ms=T0_MS + 28 * 288 * 300000)           # overlaps by one poll
        alone = pipeline.analyze([second], workers=1)
        self.assertEqual([f for f in alone["findings"] if f["kind"] == "anomaly"], [])    # 7 days alone: insufficient history, refuses
        h = HistoryStore()
        h.add_series([first]); h.add_series([second])
        res = pipeline.analyze(h.load_series(), workers=1)
        spike = [f for f in res["findings"] if f["kind"] == "anomaly" and not f.get("continuation_of")]
        self.assertTrue(spike)
        self.assertEqual(spike[0]["direction"], "high")


if __name__ == "__main__":
    unittest.main()


import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from trafficlab.server import State, make_handler


class ServerHistory(unittest.TestCase):
    def test_import_add_analyze_flow(self):
        st = State(":memory:")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]

        def req(path, body=None):
            r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"} if body is not None else {})
            try:
                with urllib.request.urlopen(r) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            self.assertEqual(req("/api/history/add", {})[0], 400)                       # nothing imported yet
            self.assertEqual(req("/api/synth", {"mixed_formats": False})[0], 200)
            code, rep = req("/api/history/add", {})
            self.assertEqual((code, rep["conflicts_recorded"]), (200, 0))
            code, rep2 = req("/api/history/add", {})
            self.assertEqual(rep2["points_added"], 0)                                   # idempotent
            self.assertEqual(req("/api/history/clear", {})[0], 400)                     # needs explicit confirm
            code, _ = req("/api/history/analyze", {"window_days": 40, "workers": 1})
            self.assertEqual(code, 202)
            for _ in range(100):
                time.sleep(0.2)
                s = req("/api/status")[1]
                if s["state"] != "running":
                    break
            self.assertEqual(s["state"], "done", s)
            self.assertEqual(len(req("/api/findings?hide_continuation=1")[1]["findings"]), 8)
            self.assertEqual(req("/api/history")[1]["series"], 10)
            self.assertEqual(req("/api/history/clear", {"confirm": True})[0], 200)
            self.assertEqual(req("/api/history")[1]["series"], 0)
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
