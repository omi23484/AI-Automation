import json
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from helpers import *
from trafficlab import anomaly
from trafficlab.config import make_config
from trafficlab.pipeline import analyze, annotate_feedback
from trafficlab.store import CRStore
from trafficlab.server import State, make_handler

DAY = 86400
K0 = (28 * DAY + 14 * 3600) // 300


def spike_series(key="A|I|in_bps", device="A"):
    return mk_series(daily_values(35, seed=71, mod=lambda k, t, v: v * 4.0 if K0 <= k < K0 + 6 else v), key=key, device=device)


def first_anomaly(res):
    return [f for f in res["findings"] if f["kind"] == "anomaly"][0]


class Store(unittest.TestCase):
    def test_add_list_delete_and_validation(self):
        st = CRStore()
        f = first_anomaly(analyze([spike_series()], workers=1))
        row = st.add_feedback(f, "false", "lab maintenance")
        self.assertEqual((row["verdict"], row["note"], row["series_key"]), ("false", "lab maintenance", "A|I|in_bps"))
        with self.assertRaises(ValueError):
            st.add_feedback(f, "maybe")
        st.delete_feedback(row["id"])
        self.assertEqual(st.list_feedback(), [])

    def test_multipliers_only_from_distinct_false_marks(self):
        st = CRStore()
        f = first_anomaly(analyze([spike_series()], workers=1))
        st.add_feedback(f, "real"); st.add_feedback(f, "expected")
        self.assertEqual(st.threshold_multipliers(0.15, 1.75), {})                     # real/expected never change scoring
        st.add_feedback(f, "false"); st.add_feedback(f, "false")                       # same window twice counts once
        self.assertAlmostEqual(st.threshold_multipliers(0.15, 1.75)["A|I|in_bps"], 1.15)
        g = dict(f, window=dict(f["window"], start_ms=f["window"]["start_ms"] + 10 ** 9, end_ms=f["window"]["end_ms"] + 10 ** 9))
        for i in range(10):
            st.add_feedback(dict(g, window=dict(g["window"], start_ms=g["window"]["start_ms"] + i, end_ms=g["window"]["end_ms"] + i)), "false")
        self.assertEqual(st.threshold_multipliers(0.15, 1.75)["A|I|in_bps"], 1.75)     # capped


class Effect(unittest.TestCase):
    def test_multiplier_one_is_identity_and_large_multiplier_suppresses(self):
        s = spike_series()
        cfg = make_config()
        base, _, _ = anomaly.detect(s, cfg)
        same, _, _ = anomaly.detect(s, cfg, 1.0)
        self.assertEqual([f["id"] for f in base], [f["id"] for f in same])
        self.assertTrue(base)
        none, _, _ = anomaly.detect(s, cfg, 50.0)
        self.assertEqual(none, [])

    def test_applied_multiplier_is_shown_in_the_finding(self):
        s = spike_series()
        pk = anomaly.detect(s, make_config())[0][0]["numbers"]["seasonal_peak_abs_z"]
        f = anomaly.detect(s, make_config(), mult=1.1)[0]
        self.assertTrue(f)
        self.assertEqual(f[0]["numbers"]["threshold_multiplier_from_feedback"], 1.1)
        self.assertLess(1.1 * 4.0, pk)

    def test_pipeline_uses_false_marks_on_next_analysis_only_for_that_series(self):
        a, b = spike_series("A|I|in_bps", "A"), spike_series("B|I|in_bps", "B")
        st = CRStore()
        r1 = analyze([a, b], store=st, workers=1)
        fa = [f for f in r1["findings"] if f["device"] == "A" and f["kind"] == "anomaly"][0]
        st.add_feedback(fa, "false")
        cfg = make_config({"feedback": {"step": 100.0, "cap": 100.0}})                    # exaggerated so the effect is unmistakable
        r2 = analyze([a, b], cfg, store=st, workers=1)
        self.assertEqual([f for f in r2["findings"] if f["device"] == "A" and f["kind"] == "anomaly" and not f.get("suppressed_by_feedback")], [])
        self.assertTrue([f for f in r2["findings"] if f["device"] == "B" and f["kind"] == "anomaly"])      # other series untouched
        self.assertEqual(r2["feedback_multipliers"], {"A|I|in_bps": 100.0})
        r3 = analyze([a, b], make_config({"feedback": {"enabled": False, "step": 100.0, "cap": 100.0}}), store=st, workers=1)
        self.assertTrue([f for f in r3["findings"] if f["device"] == "A" and f["kind"] == "anomaly"])       # switch off => marks ignored
        self.assertEqual(r3["feedback_multipliers"], {})

    def test_default_step_after_one_false_mark_keeps_a_strong_event(self):
        s = spike_series()
        st = CRStore()
        f = first_anomaly(analyze([s], store=st, workers=1))
        st.add_feedback(f, "false")
        r = analyze([s], store=st, workers=1)                                             # x1.15 only: a 4x spike is still far above
        self.assertTrue([x for x in r["findings"] if x["kind"] == "anomaly"])


class Annotation(unittest.TestCase):
    def F(self, **kw):
        w = {"start_ms": 1000, "end_ms": 2000}
        d = {"id": "F-1", "series_key": "S", "kind": "anomaly", "window": w}
        d.update(kw)
        return d

    def row(self, **kw):
        d = {"id": 1, "series_key": "S", "kind": "anomaly", "start_ms": 1500, "end_ms": 1800, "verdict": "false", "note": "n", "ts_utc": "t", "actor": "u"}
        d.update(kw)
        return d

    def test_overlap_kind_and_series_rules(self):
        fs = [self.F(), self.F(id="F-2", series_key="OTHER"), self.F(id="F-3", kind="pattern_shift"), self.F(id="F-4", window={"start_ms": 5000, "end_ms": 6000})]
        annotate_feedback(fs, [self.row()])
        self.assertTrue(fs[0]["suppressed_by_feedback"])
        self.assertEqual(fs[0]["feedback"]["note"], "n")
        for f in fs[1:]:
            self.assertNotIn("feedback", f)

    def test_real_is_annotated_but_not_suppressed_and_reannotation_clears(self):
        f = self.F()
        annotate_feedback([f], [self.row(verdict="real")])
        self.assertEqual(f["feedback"]["verdict"], "real")
        self.assertNotIn("suppressed_by_feedback", f)
        annotate_feedback([f], [])
        self.assertNotIn("feedback", f)


class Server(unittest.TestCase):
    def test_api_flow(self):
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
            req("/api/synth", {})
            req("/api/analyze", {"workers": 1})
            for _ in range(100):
                time.sleep(0.2)
                if req("/api/status")[1]["state"] != "running":
                    break
            fs = req("/api/findings?kind=anomaly&hide_continuation=1")[1]["findings"]
            fid, n = fs[0]["id"], len(fs)
            self.assertEqual(req("/api/feedback", {"finding_id": "F-nope", "verdict": "false"})[0], 404)
            self.assertEqual(req("/api/feedback", {"finding_id": fid, "verdict": "bogus"})[0], 400)
            code, j = req("/api/feedback", {"finding_id": fid, "verdict": "false", "note": "known"})
            self.assertEqual(code, 200)
            self.assertEqual(len(req("/api/findings?kind=anomaly&hide_continuation=1&hide_marked=1")[1]["findings"]), n - 1)
            self.assertEqual(len(req("/api/findings?kind=anomaly&hide_continuation=1")[1]["findings"]), n)          # hidden, never deleted
            req("/api/feedback/delete", {"id": j["feedback"]["id"]})
            self.assertEqual(len(req("/api/findings?kind=anomaly&hide_continuation=1&hide_marked=1")[1]["findings"]), n)
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
