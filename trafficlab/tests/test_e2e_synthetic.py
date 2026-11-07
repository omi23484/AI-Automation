"""End-to-end on SYNTHETIC data with known ground truth (see synth.py manifest)."""
import unittest
from helpers import *
from trafficlab import synth, ingest, counters, pipeline
from trafficlab.store import CRStore

FMTS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]


class E2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text, cls.man = synth.generate(mixed_formats=True)
        cls.ds = ingest.load_csv(text, synth.SYN_MAPPING32, ts_formats=FMTS)
        cls.series, cls.dq = counters.build_all(cls.ds)
        st = CRStore()
        st.import_json(synth.synthetic_crs())
        cls.res = pipeline.analyze(cls.series, store=st, workers=1)
        cls.F = [f for f in cls.res["findings"] if not f.get("continuation_of")]

    def test_data_quality_detected(self):
        self.assertEqual(len(self.dq["duplicates"]), 1)
        self.assertEqual(self.dq["rows_excluded_no_ts"], 1)
        rep = ingest.ts_report(self.ds)
        self.assertTrue(rep["mixed_formats"])
        self.assertEqual(rep["unparseable_samples"][0]["ts_raw"], "not-a-time")

    def test_mixed_format_raw_untouched(self):
        raws = {r.ts_raw for r in self.ds.rows}
        self.assertTrue(any("T" in r for r in raws))
        self.assertTrue(any(" " in r and "T" not in r for r in raws))

    def test_reload_and_gap_marked(self):
        l2 = [s for s in self.series if s.device == "SYN-DC-LEAF2" and s.metric == "in_bps"][0]
        self.assertEqual([e["type"] for e in l2.excluded], ["reset"])
        self.assertEqual(l2.excluded[0]["end_raw"], "2026-01-30 10:00:00")
        r2 = [s for s in self.series if s.device == "SYN-WAN-R2" and s.metric == "in_bps"][0]
        self.assertEqual([e["type"] for e in r2.excluded], ["gap"])
        self.assertEqual(r2.excluded[0]["end_raw"], "2026-01-20 10:00:00")

    def test_wrap32_used_and_rates_sane(self):
        w = [s for s in self.series if s.device == "SYN-WAN-R1" and s.metric == "in_bps"][0]
        self.assertGreater(w.method.count("wrap32_uptime_confirmed"), 100)
        self.assertLess(max(w.rate), 100e6 * 1.1)    # never above line speed -> wraps handled right
        self.assertGreater(min(w.rate), 0)

    def test_spike_found(self):
        sp = [f for f in self.F if f["device"] == "SYN-ENT-SW1"]
        self.assertEqual(len(sp), 2)  # in + out
        for f in sp:
            self.assertEqual(f["window"]["start_raw"], "2026-01-25 14:00:00")
            self.assertEqual(f["window"]["end_raw"], "2026-01-25 14:25:00")

    def test_shift_found_and_cr_candidate(self):
        sh = [f for f in self.F if f["kind"] == "pattern_shift"]
        self.assertEqual({f["device"] for f in sh}, {"SYN-WAN-R1"})
        for f in sh:
            self.assertEqual(f["window"]["start_raw"], "2026-01-27 06:00:00")
            self.assertEqual([c["cr_id"] for c in f["cr_candidates"]], ["SYN-CR-1001"])
            self.assertEqual(f["cr_candidates"][0]["relation"], "overlaps")

    def test_decoy_cr_never_matched(self):
        for f in self.res["findings"]:
            self.assertNotIn("SYN-CR-1002", [c["cr_id"] for c in f["cr_candidates"]])

    def test_shared_dc_surge_clustered_across_both_leaves(self):
        cl = [c for c in self.res["clusters"] if set(c["devices"]) == {"SYN-DC-LEAF1", "SYN-DC-LEAF2"}]
        self.assertEqual(len(cl), 1)
        self.assertGreater(cl[0]["mean_pearson_r"], 0.9)
        self.assertEqual(cl[0]["zones"], ["DC"])

    def test_no_findings_on_untouched_devices(self):
        devs = {f["device"] for f in self.F}
        self.assertNotIn("SYN-WAN-R2", devs)

    def test_every_finding_has_required_fields(self):
        for f in self.res["findings"]:
            for k in ("id", "metric", "device", "interface", "window", "severity", "math", "numbers", "confidence", "layer"):
                self.assertIn(k, f)
            self.assertIn("level", f["confidence"])
            self.assertTrue(f["confidence"]["justification"])
            self.assertIn("epoch_ms", f["window"]["start_ts_parsed"])
            self.assertTrue(f["window"]["start_raw"])

    def test_deterministic(self):
        st = CRStore(); st.import_json(synth.synthetic_crs())
        r2 = pipeline.analyze(self.series, store=st, workers=1)
        self.assertEqual([f["id"] for f in r2["findings"]], [f["id"] for f in self.res["findings"]])


if __name__ == "__main__":
    unittest.main()
