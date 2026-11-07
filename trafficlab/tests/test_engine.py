import unittest
from helpers import *
from trafficlab.config import make_config
from trafficlab import anomaly, changepoint, correlate
from trafficlab.pipeline import analyze

DAY = 86400


def spike(k0, k1, f):
    return lambda k, t, v: v * f if k0 <= k < k1 else v


class Anomaly(unittest.TestCase):
    def test_clean_series_no_findings(self):
        s = mk_series(daily_values(35, seed=11))
        fs, summ, _ = anomaly.detect(s, make_config())
        self.assertEqual(fs, [], [f["window"] for f in fs])

    def test_spike_found_at_known_window(self):
        k0 = (28 * DAY + 14 * 3600) // 300     # day 28 (Monday) 14:00
        k1 = k0 + 6
        s = mk_series(daily_values(35, seed=12, mod=spike(k0, k1, 4.0)))
        fs, _, _ = anomaly.detect(s, make_config())
        self.assertEqual(len(fs), 1)
        f = fs[0]
        self.assertEqual(f["direction"], "high")
        # rates are stamped at interval end: index k <-> t=(k+1)*300 after T0
        self.assertEqual(f["window"]["start_ms"], T0_MS + (k0 + 1) * 300000)
        self.assertEqual(f["window"]["end_ms"], T0_MS + (k1) * 300000)
        self.assertEqual(f["window"]["start_raw"], f"RAW{f['window']['start_ms']}")
        self.assertEqual(f["confidence"]["level"], "high")
        self.assertGreater(f["numbers"]["deviation_pct"], 200)

    def test_drop_to_zero_direction_low(self):
        k0 = (28 * DAY + 14 * 3600) // 300
        s = mk_series(daily_values(35, seed=13, mod=spike(k0, k0 + 8, 0.0)))
        fs, _, _ = anomaly.detect(s, make_config())
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["direction"], "low")

    def test_insufficient_history_refuses(self):
        s = mk_series(daily_values(3, seed=14, mod=spike(300, 320, 5.0)))
        fs, summ, _ = anomaly.detect(s, make_config())
        self.assertEqual(fs, [])
        self.assertEqual(summ["scored_points"], 0)
        self.assertEqual(summ["tier_counts"], {"insufficient_history": len(s.rate)})

    def test_weekend_not_false_positive(self):
        # weekend traffic is 60% of weekday; must not flag Saturdays/Sundays
        s = mk_series(daily_values(35, seed=15, noise=0.02))
        fs, summ, _ = anomaly.detect(s, make_config())
        self.assertEqual(fs, [])

    def test_single_point_blip_ignored_by_min_points(self):
        k = (28 * DAY + 14 * 3600) // 300
        s = mk_series(daily_values(35, seed=16, mod=spike(k, k + 1, 6.0)))
        fs, _, _ = anomaly.detect(s, make_config())
        self.assertTrue(all("seasonal_robust_z" not in f["methods"] for f in fs))

    def test_flat_series_floor_prevents_div0(self):
        s = mk_series([5e6] * (35 * 288))
        fs, summ, _ = anomaly.detect(s, make_config())
        self.assertEqual(fs, [])

    def test_gap_breaks_runs_and_ewma(self):
        vals = daily_values(35, seed=17)
        s = mk_series(vals)
        # remove 2h in the middle (a gap) - no points invented
        cut = [i for i, t in enumerate(s.ts_ms) if not (T0_MS + 20 * DAY * 1000 <= t < T0_MS + (20 * DAY + 7200) * 1000)]
        for name in ("ts_ms", "ts_raw", "ts_fmt", "rate", "method"):
            setattr(s, name, [getattr(s, name)[i] for i in cut])
        fs, _, _ = anomaly.detect(s, make_config())
        self.assertEqual(fs, [])

    def test_zone_override_threshold(self):
        k0 = (28 * DAY + 14 * 3600) // 300
        s = mk_series(daily_values(35, seed=18, mod=spike(k0, k0 + 6, 1.5)), zone="WAN")
        base = anomaly.detect(s, make_config())[0]
        strict = anomaly.detect(s, make_config({"anomaly": {"z_threshold": 50, "ewma_L": 500}}))[0]
        self.assertGreaterEqual(len(base), 1)
        self.assertEqual(strict, [])


class Shift(unittest.TestCase):
    def test_step_found_within_one_hour(self):
        k0 = (22 * DAY + 6 * 3600) // 300
        s = mk_series(daily_values(35, seed=21, mod=lambda k, t, v: v * 1.4 if k >= k0 else v))
        fs, st = changepoint.detect_shifts(s, make_config())
        self.assertEqual(st["status"], "ok")
        self.assertEqual(len(fs), 1)
        f = fs[0]
        true_ms = T0_MS + 22 * DAY * 1000 + 6 * 3600 * 1000
        self.assertLessEqual(abs(f["window"]["start_ms"] - true_ms), 3600 * 1000 + 300000)
        self.assertEqual(f["direction"], "up")
        self.assertAlmostEqual(f["numbers"]["change_pct"], 40, delta=8)
        self.assertEqual(f["window"]["start_raw"], f"RAW{f['window']['start_ms']}")
        self.assertIn("raw_var_before", f["numbers"])

    def test_clean_series_no_shift(self):
        s = mk_series(daily_values(35, seed=22))
        fs, st = changepoint.detect_shifts(s, make_config())
        self.assertEqual(fs, [])

    def test_refuses_when_span_too_short(self):
        s = mk_series(daily_values(3, seed=23))
        fs, st = changepoint.detect_shifts(s, make_config())
        self.assertEqual(fs, [])
        self.assertEqual(st["status"], "insufficient_history")

    def test_downward_step(self):
        k0 = (20 * DAY) // 300
        s = mk_series(daily_values(35, seed=24, mod=lambda k, t, v: v * 0.5 if k >= k0 else v))
        fs, _ = changepoint.detect_shifts(s, make_config())
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["direction"], "down")


class Correlation(unittest.TestCase):
    def _two(self, same_time=True, seed=31):
        k0 = (28 * DAY + 2 * 3600) // 300
        a = mk_series(daily_values(35, seed=seed, mod=spike(k0, k0 + 9, 3.0)), key="A|I|in_bps", device="A")
        k1 = k0 if same_time else k0 + 3 * 288
        b = mk_series(daily_values(35, seed=seed + 1, mod=spike(k1, k1 + 9, 3.0)), key="B|I|in_bps", device="B")
        return [a, b]

    def test_shared_cause_candidate(self):
        r = analyze(self._two(True), workers=1)
        self.assertEqual(len(r["clusters"]), 1)
        c = r["clusters"][0]
        self.assertEqual(c["devices"], ["A", "B"])
        self.assertGreater(c["mean_pearson_r"], 0.5)
        self.assertTrue(c["label"].startswith("shared-cause candidate"))
        self.assertTrue(all(f["cluster_id"] == c["id"] for f in r["findings"]))

    def test_non_overlapping_not_clustered(self):
        r = analyze(self._two(False), workers=1)
        self.assertEqual(r["clusters"], [])
        self.assertEqual(len(r["findings"]), 2)

    def test_anticorrelated_not_shared(self):
        k0 = (28 * DAY + 2 * 3600) // 300
        a = mk_series(daily_values(35, seed=41, mod=spike(k0, k0 + 9, 3.0)), key="A|I|in_bps", device="A")
        b = mk_series(daily_values(35, seed=42, mod=spike(k0, k0 + 9, 0.0)), key="B|I|in_bps", device="B")
        r = analyze([a, b], workers=1)
        self.assertEqual(len(r["clusters"]), 1)
        self.assertFalse(r["clusters"][0]["label"].startswith("shared"))

    def test_unknown_when_no_evidence(self):
        k0 = (28 * DAY + 14 * 3600) // 300
        s = mk_series(daily_values(35, seed=51, mod=spike(k0, k0 + 6, 4.0)))
        r = analyze([s], workers=1)
        self.assertEqual(r["findings"][0]["interpretation"][0]["claim"], "Unknown - insufficient evidence")


if __name__ == "__main__":
    unittest.main()
