import unittest
import dataclasses
from helpers import *
from trafficlab import ingest, counters
from trafficlab.config import make_config

M64 = {"device": "dev", "interface": "if", "timestamp": "ts",
       "counters": [{"name": "in_bps", "column": "oct", "bits": 64, "mult": 8, "unit": "bps"}],
       "uptime": {"column": "up", "unit": "s"}, "speed": {"column": "spd", "unit": "mbps"}}
M32 = dict(M64, counters=[{"name": "in_bps", "column": "oct", "bits": 32, "mult": 8, "unit": "bps"}])
FMT = ["%Y-%m-%d %H:%M:%S"]


def build(rows, mapping=M64, header="ts,dev,if,oct,up,spd", cfg=None):
    text = header + "\n" + "\n".join(rows) + "\n"
    ds = ingest.load_csv(text, mapping, ts_formats=FMT)
    sl, dq = counters.build_all(ds, cfg)
    return ds, sl, dq


def row(minute, oct_, up, spd=1000, dev="d1"):
    return f"2026-01-05 00:{minute:02d}:00,{dev},e1,{oct_},{up},{spd}"


class T(unittest.TestCase):
    def test_simple_delta_rate(self):
        # 60 s, +7500000 octets => 7.5e6*8/60 = 1e6 bps
        _, sl, _ = build([row(0, 0, 1000), row(1, 7_500_000, 1060)])
        self.assertAlmostEqual(sl[0].rate[0], 1_000_000.0)
        self.assertEqual(sl[0].method, ["delta"])

    def test_wrap32_with_uptime(self):
        v0 = 2 ** 32 - 1000
        # delta true = 1000 + 500 = 1500 octets in 60 s -> 200 bps
        _, sl, _ = build([row(0, v0, 1000), row(1, 500, 1060)], M32)
        self.assertEqual(sl[0].method, ["wrap32_uptime_confirmed"])
        self.assertAlmostEqual(sl[0].rate[0], 1500 * 8 / 60)

    def test_wrap32_no_uptime_plausible_via_speed(self):
        m = dict(M32); m.pop("uptime")
        v0 = 2 ** 32 - 1000
        _, sl, _ = build([f"2026-01-05 00:00:00,d1,e1,{v0},,1000", "2026-01-05 00:01:00,d1,e1,500,,1000"], m)
        self.assertEqual(sl[0].method, ["wrap32_plausible"])

    def test_decrease_no_uptime_implausible_is_excluded_not_guessed(self):
        m = dict(M32); m.pop("uptime")
        # 1 Mbps link (speed 1 mbps): 60 s max ~ 8250 octets; decrease from 1e9 to 10 -> wrapped delta huge
        _, sl, _ = build(["2026-01-05 00:00:00,d1,e1,1000000000,,1", "2026-01-05 00:01:00,d1,e1,10,,1"], m)
        self.assertEqual(sl[0].rate, [])
        self.assertEqual(sl[0].excluded[0]["type"], "reset_or_wrap_ambiguous")

    def test_decrease_no_uptime_no_speed_ambiguous(self):
        m = dict(M32); m.pop("uptime"); m.pop("speed")
        _, sl, _ = build(["2026-01-05 00:00:00,d1,e1,5000,", "2026-01-05 00:01:00,d1,e1,10,"], m, header="ts,dev,if,oct,x")
        self.assertEqual(sl[0].rate, [])
        self.assertEqual(sl[0].excluded[0]["type"], "reset_or_wrap_ambiguous")

    def test_unverified_wrap_only_if_allowed(self):
        m = dict(M32); m.pop("uptime"); m.pop("speed")
        cfg = make_config({"counters": {"allow_unverified_wrap": True}})
        _, sl, _ = build(["2026-01-05 00:00:00,d1,e1,4294967000,", "2026-01-05 00:01:00,d1,e1,100,"], m, header="ts,dev,if,oct,x", cfg=cfg)
        self.assertEqual(sl[0].method, ["wrap32_unverified"])

    def test_reload_by_uptime_drop_no_rate(self):
        _, sl, _ = build([row(0, 9_000_000, 100000), row(1, 1000, 30)])
        self.assertEqual(sl[0].rate, [])
        self.assertEqual(sl[0].excluded[0]["type"], "reset")

    def test_reload_detected_even_if_counter_increases(self):
        # counter went UP but uptime says device came up inside the interval
        _, sl, _ = build([row(0, 100, 100000), row(1, 5000, 20)])
        self.assertEqual(sl[0].rate, [])
        self.assertEqual(sl[0].excluded[0]["type"], "reset")

    def test_64bit_decrease_no_rate(self):
        _, sl, _ = build([row(0, 9_000_000, 1000), row(1, 10, 1060)])
        self.assertEqual(sl[0].excluded[0]["type"], "counter_decrease_64bit")

    def test_gap_marked_never_filled(self):
        rows = [row(m, m * 7500, 1000 + 60 * m) for m in (0, 1, 2, 3, 10, 11, 12)]
        _, sl, _ = build(rows)
        s = sl[0]
        self.assertEqual(len(s.rate), 5)          # 6 intervals minus 1 gap
        self.assertEqual([e["type"] for e in s.excluded], ["gap"])
        self.assertEqual(s.excluded[0]["start_raw"], "2026-01-05 00:03:00")
        self.assertEqual(s.excluded[0]["end_raw"], "2026-01-05 00:10:00")

    def test_ts_raw_preserved_exact(self):
        ds, sl, _ = build([row(0, 0, 1000), row(1, 7500, 1060)])
        self.assertEqual(sl[0].ts_raw, ["2026-01-05 00:01:00"])
        self.assertEqual(ds.rows[0].ts_raw, "2026-01-05 00:00:00")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ds.rows[0].ts_raw = "x"

    def test_unparseable_ts_flagged_not_dropped_from_raw(self):
        ds, sl, dq = build([row(0, 0, 1000), "bad time,d1,e1,5,1,1000", row(1, 7500, 1060)])
        self.assertEqual(len(ds.rows), 3)                       # raw kept
        self.assertEqual(ds.rows[1].ts_raw, "bad time")
        self.assertIn("unparseable", ds.row_flags[1])
        self.assertEqual(dq["rows_excluded_no_ts"], 1)

    def test_duplicates_and_conflicts(self):
        _, sl, dq = build([row(0, 0, 1000), row(1, 7500, 1060), row(1, 7500, 1060), row(2, 100, 1120), row(2, 999, 1120)])
        self.assertEqual(len(dq["duplicates"]), 1)
        self.assertEqual(len(dq["conflicts"]), 1)
        self.assertEqual(len(sl[0].rate), 1)   # minute 2 dropped (conflict) -> only 0->1 interval

    def test_out_of_order_detected(self):
        _, sl, dq = build([row(1, 7500, 1060), row(0, 0, 1000), row(2, 15000, 1120)])
        self.assertEqual(dq["out_of_order"], 1)
        self.assertEqual(len(sl[0].rate), 2)

    def test_bad_numeric_flagged(self):
        ds, sl, _ = build([row(0, 0, 1000), "2026-01-05 00:01:00,d1,e1,1.2E+10,1060,1000", row(2, 15000, 1120)])
        self.assertIn("bad_value:in_bps", ds.row_flags[1])

    def test_unreliable_32bit_note(self):
        m = M32
        rows = [row(0, 0, 1000, spd=10000), row(5, 100, 1300, spd=10000)]
        # 10 Gbps, 300 s interval: 10e9*300/8 = 3.75e11 >= 2^32 => note
        rows = ["2026-01-05 00:00:00,d1,e1,0,1000,10000", "2026-01-05 00:05:00,d1,e1,100,1300,10000"]
        _, sl, _ = build(rows, m)
        self.assertTrue(any("wrap more than once" in n for n in sl[0].notes))

    def test_missing_mapping_column_is_error(self):
        with self.assertRaises(ingest.IngestError):
            ingest.load_csv("a,b\n1,2\n", M64)


if __name__ == "__main__":
    unittest.main()
