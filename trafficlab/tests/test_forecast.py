import math
import random
import unittest
from datetime import date, timedelta
from helpers import *
from trafficlab import forecast as F
from trafficlab.config import make_config
from trafficlab.pipeline import analyze

DAY = 86400


class Stats(unittest.TestCase):
    def test_mann_kendall_hand_values(self):
        S, tau, z, p, var = F.mann_kendall([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        self.assertEqual((S, tau), (45, 1.0))
        self.assertAlmostEqual(var, 10 * 9 * 25 / 18)                      # no ties: n(n-1)(2n+5)/18
        self.assertAlmostEqual(z, 44 / math.sqrt(125), places=6)           # continuity-corrected
        self.assertLess(p, 1e-3)
        self.assertEqual(F.mann_kendall([5, 5, 5, 5, 5])[0], 0)
        self.assertEqual(F.mann_kendall([5, 5, 5, 5, 5])[3], 1.0)

    def test_zcrit(self):
        self.assertAlmostEqual(F._zcrit(0.05), 1.95996, places=4)
        self.assertAlmostEqual(F._zcrit(0.10), 1.64485, places=4)

    def test_sen_exact_line(self):
        t = list(range(30))
        m, lo, hi, ic = F.sen(t, [2 * x + 1 for x in t])
        self.assertAlmostEqual(m, 2.0)
        self.assertAlmostEqual(ic, 1.0)
        self.assertAlmostEqual(lo, 2.0)
        self.assertAlmostEqual(hi, 2.0)

    def test_sen_band_covers_true_slope_most_of_the_time(self):
        hits = 0
        for seed in range(200):
            r = random.Random(seed)
            t = list(range(40))
            y = [0.5 * x + r.gauss(0, 2.0) for x in t]
            m, lo, hi, _ = F.sen(t, y, 0.05)
            hits += lo <= 0.5 <= hi
        self.assertGreaterEqual(hits / 200, 0.90)                           # nominal 95%; approximate band, so allow some slack

    def test_sen_robust_to_outliers(self):
        t = list(range(40))
        y = [0.5 * x for x in t]
        y[10] += 500
        y[30] -= 400
        self.assertAlmostEqual(F.sen(t, y)[0], 0.5, places=1)


def daily_series(levels_pct, speed=1e9, per_day=288, start_ms=T0_MS, **kw):
    """One constant rate per day so the daily p95 is exactly that day's level."""
    vals = []
    for lv in levels_pct:
        vals += [lv / 100.0 * speed] * per_day
    s = mk_series(vals, **kw)
    s.speed_bps = speed
    return s


class Series(unittest.TestCase):
    def test_linear_growth_eta_matches_analytic(self):
        s = daily_series([20 + 0.5 * d for d in range(60)])                  # +0.5 pct-points/day, 20% -> 49.5% on the last day
        f = F.forecast_series(s, make_config())
        self.assertEqual(f["status"], "upward_trend")
        self.assertAlmostEqual(f["slope_pct_per_day"], 0.5, places=3)
        self.assertAlmostEqual(f["level_now_pct"], 49.5, places=1)
        r80 = [r for r in f["thresholds"] if r["pct"] == 80][0]
        self.assertAlmostEqual(r80["eta_days"], (80 - 49.5) / 0.5, places=0)  # 61 days
        self.assertEqual(f["basis"], "daily p95")
        last = date.fromisoformat(f["last_observed"])
        self.assertEqual(r80["eta_date"], str(last + timedelta(days=math.ceil(r80["eta_days"]))))

    def test_flat_series_has_no_trend_and_no_date(self):
        r = random.Random(3)
        f = F.forecast_series(daily_series([30 + r.gauss(0, 0.2) for _ in range(60)]), make_config())
        self.assertEqual(f["status"], "no_significant_upward_trend")
        self.assertEqual(f["thresholds"], [])

    def test_decreasing_series_has_no_eta(self):
        f = F.forecast_series(daily_series([60 - 0.3 * d for d in range(60)]), make_config())
        self.assertEqual(f["status"], "no_significant_upward_trend")

    def test_noisy_growth_band_brackets_eta(self):
        r = random.Random(11)
        s = daily_series([20 + 0.4 * d + r.gauss(0, 1.5) for d in range(90)])
        f = F.forecast_series(s, make_config())
        self.assertEqual(f["status"], "upward_trend")
        row = [x for x in f["thresholds"] if x["pct"] == 90][0]
        truth_days = (90 - (20 + 0.4 * 89)) / 0.4
        self.assertLessEqual(date.fromisoformat(row["fast_date"]), date.fromisoformat(f["last_observed"]) + timedelta(days=math.ceil(truth_days) + 1))
        self.assertGreaterEqual(date.fromisoformat(row["slow_date"]), date.fromisoformat(f["last_observed"]) + timedelta(days=math.floor(truth_days) - 1))

    def test_already_above_threshold(self):
        f = F.forecast_series(daily_series([70 + 0.5 * d for d in range(40)]), make_config())     # ends ~89.5
        r80 = [x for x in f["thresholds"] if x["pct"] == 80][0]
        self.assertEqual(r80["eta_days"], 0.0)

    def test_insufficient_history_refuses(self):
        f = F.forecast_series(daily_series([20 + d for d in range(10)]), make_config())
        self.assertEqual(f["status"], "insufficient_history")
        self.assertNotIn("thresholds", f)

    def test_days_with_poor_coverage_are_dropped_not_filled(self):
        s = daily_series([20 + 0.5 * d for d in range(40)])
        keep = [i for i, t in enumerate(s.ts_ms) if not (10 * DAY * 1000 + T0_MS <= t < 14 * DAY * 1000 + T0_MS)]   # remove 4 whole days
        for n in ("ts_ms", "ts_raw", "ts_fmt", "rate", "method"):
            setattr(s, n, [getattr(s, n)[i] for i in keep])
        f = F.forecast_series(s, make_config())
        self.assertEqual(f["n_points"], 36)

    def test_needs_speed_or_pct_unit(self):
        s = daily_series([20 + d for d in range(40)])
        s.speed_bps = None
        self.assertIsNone(F.forecast_series(s, make_config()))

    def test_weekly_pct_series(self):
        s = mk_series([20 + 0.8 * w for w in range(20)], interval_s=7 * DAY, unit="pct")
        f = F.forecast_series(s, make_config())
        self.assertEqual((f["status"], f["basis"]), ("upward_trend", "weekly value"))
        self.assertAlmostEqual(f["slope_pct_per_day"], 0.8 / 7, places=3)

    def test_disabled_and_pipeline_integration(self):
        s = daily_series([20 + 0.5 * d for d in range(60)], key="D|I|in_bps")
        r = analyze([s], workers=1)
        self.assertEqual(r["forecasts"][0]["status"], "upward_trend")
        r2 = analyze([s], make_config({"forecast": {"enabled": False}}), workers=1)
        self.assertEqual(r2["forecasts"], [])


if __name__ == "__main__":
    unittest.main()
