import unittest
from helpers import *
from trafficlab.timeparse import parse_ts, EPOCH_S, EPOCH_MS


class T(unittest.TestCase):
    def test_utc_naive(self):
        r = parse_ts("2026-01-05 00:00:00", ["%Y-%m-%d %H:%M:%S"], "UTC")
        self.assertEqual(r["epoch_ms"], T0_MS)
        self.assertEqual(r["tz_source"], "assumed")
        self.assertEqual(r["format"], "%Y-%m-%d %H:%M:%S")

    def test_explicit_offset_wins(self):
        r = parse_ts("2026-01-05T05:30:00+05:30", None, "America/New_York")
        self.assertEqual(r["epoch_ms"], T0_MS)
        self.assertEqual(r["tz_source"], "explicit_offset")

    def test_Z_suffix(self):
        self.assertEqual(parse_ts("2026-01-05T00:00:00Z", None)["epoch_ms"], T0_MS)

    def test_assumed_tz_conversion(self):
        r = parse_ts("2026-01-04 19:00:00", ["%Y-%m-%d %H:%M:%S"], "America/New_York")  # EST = UTC-5
        self.assertEqual(r["epoch_ms"], T0_MS)

    def test_dst_ambiguous_not_guessed(self):
        r = parse_ts("2026-11-01 01:30:00", ["%Y-%m-%d %H:%M:%S"], "America/New_York")
        self.assertIsNone(r["epoch_ms"])
        self.assertIn("dst_ambiguous", r["flags"])

    def test_dst_nonexistent_not_guessed(self):
        r = parse_ts("2026-03-08 02:30:00", ["%Y-%m-%d %H:%M:%S"], "America/New_York")
        self.assertIsNone(r["epoch_ms"])
        self.assertIn("dst_nonexistent", r["flags"])

    def test_unparseable_flagged(self):
        r = parse_ts("garbage", None)
        self.assertIsNone(r["epoch_ms"])
        self.assertIn("unparseable", r["flags"])

    def test_slash_dates_never_guessed(self):
        self.assertIsNone(parse_ts("01/02/2026 10:00:00", None)["epoch_ms"])

    def test_epoch_only_if_declared(self):
        self.assertIsNone(parse_ts("1767571200", None)["epoch_ms"])
        self.assertEqual(parse_ts("1767571200", [EPOCH_S])["epoch_ms"], T0_MS)
        self.assertEqual(parse_ts("1767571200000", [EPOCH_MS])["epoch_ms"], T0_MS)

    def test_subsecond_floor(self):
        r = parse_ts("2026-01-05 00:00:00.9999", ["%Y-%m-%d %H:%M:%S.%f"])
        self.assertEqual(r["epoch_ms"], T0_MS + 999)

    def test_input_not_mutated(self):
        raw = "  2026-01-05 00:00:00  "
        parse_ts(raw, ["%Y-%m-%d %H:%M:%S"])
        self.assertEqual(raw, "  2026-01-05 00:00:00  ")


if __name__ == "__main__":
    unittest.main()
