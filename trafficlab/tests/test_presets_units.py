import unittest
from helpers import *
from trafficlab import ingest, counters, pipeline, synth
from trafficlab.units import parse_rate, unit_multiplier
from trafficlab.timeparse import slash_census
from trafficlab.presets import PRESETS


class Units(unittest.TestCase):
    def test_parse(self):
        self.assertAlmostEqual(parse_rate("123.45 Mbps"), 123.45e6)
        self.assertAlmostEqual(parse_rate("1.5 Gbps"), 1.5e9)
        self.assertAlmostEqual(parse_rate("250000 kbps"), 250e6)
        self.assertAlmostEqual(parse_rate("800Mbps"), 800e6)
        self.assertAlmostEqual(parse_rate("1,234.5 Mbps"), 1234.5e6)
        self.assertAlmostEqual(parse_rate("12 MB/s"), 96e6)       # byte (capital B) x8
        self.assertAlmostEqual(parse_rate("12 Mb/s"), 12e6)       # bit (lower b)
        self.assertAlmostEqual(parse_rate("0 bps"), 0.0)

    def test_no_unit_needs_default_never_inferred(self):
        self.assertIsNone(parse_rate("950"))
        self.assertAlmostEqual(parse_rate("950", "Mbps"), 950e6)

    def test_garbage_is_none(self):
        for x in ("N/A", "", "12 widgets", "Mbps", "1.2.3 Mbps"):
            self.assertIsNone(parse_rate(x), x)


class Census(unittest.TestCase):
    def test_month_first_proof(self):
        c = slash_census(["1/5/2026 00:00:00", "1/13/2026 00:00:00"])
        self.assertEqual(c["verdict"], "month_first")

    def test_day_first_proof(self):
        self.assertEqual(slash_census(["01/08/2026 03:55 AM", "25/08/2026 03:55 AM"])["verdict"], "day_first")

    def test_ambiguous_never_guessed(self):
        self.assertEqual(slash_census(["01/08/2026", "02/09/2026"])["verdict"], "ambiguous")

    def test_conflict(self):
        self.assertEqual(slash_census(["25/08/2026", "08/25/2026"])["verdict"], "conflict")


class Collector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text, cls.man = synth.generate_collector()
        cls.text = text
        p = PRESETS["nexus_collect_utilization"]
        cls.ds = ingest.load_csv(text, p["mapping"], p["ts_formats"])
        cls.series, cls.dq = counters.build_all(cls.ds)
        cls.val = pipeline.validation_report(cls.ds, cls.series, cls.dq)

    def test_header_matches_collector_layout(self):
        self.assertEqual(self.text.splitlines()[0], "Hostname,IP_Address,Interface Name,Received Bandwidth,Receive Mbps,Transmit Bandwidth,Transmit Mbps,Timestamp")

    def test_cells_parsed_to_bps_and_speed(self):
        s = [x for x in self.series if x.metric == "in_bps" and x.device == "SYN-DC-LEAF1"][0]
        self.assertEqual(s.speed_bps, 10e9)
        self.assertEqual(set(s.method), {"gauge_as_given"})
        self.assertGreater(max(s.rate), 1e9)

    def test_raw_timestamp_untouched_nonpadded(self):
        self.assertEqual(self.ds.rows[0].ts_raw, "1/5/2026 00:00:00")
        self.assertEqual(self.ds.ts_parsed[0]["epoch_ms"], T0_MS)

    def test_census_proves_month_first_and_consistent(self):
        msgs = [i["message"] for i in self.val["issues"]]
        self.assertTrue(any("prove month-first" in m and "consistent" in m for m in msgs), msgs)
        self.assertEqual(self.val["timestamps"]["slash_census"]["verdict"], "month_first")

    def test_wrong_declared_order_is_an_error(self):
        p = PRESETS["nexus_collect_utilization"]
        ds = ingest.load_csv(self.text, p["mapping"], ["%d/%m/%Y %H:%M:%S"])
        sl, dq = counters.build_all(ds)
        v = pipeline.validation_report(ds, sl, dq)
        self.assertTrue(any(i["severity"] == "error" for i in v["issues"]))

    def test_undeclared_slash_dates_not_parsed_and_explained(self):
        p = PRESETS["nexus_collect_utilization"]
        ds = ingest.load_csv(self.text, p["mapping"], None)       # built-in ISO candidates only
        self.assertIsNone(ds.ts_parsed[0]["epoch_ms"])
        sl, dq = counters.build_all(ds)
        v = pipeline.validation_report(ds, sl, dq)
        self.assertTrue(any("not parsed" in i["message"] and i["severity"] == "error" for i in v["issues"]))

    def test_spike_found_end_to_end(self):
        r = pipeline.analyze(self.series, workers=1)
        prim = [f for f in r["findings"] if not f.get("continuation_of") and f["kind"] == "anomaly"]
        self.assertEqual(len(prim), 4)   # 2 devices x (in,out)
        from datetime import datetime
        a = datetime.strptime(self.man["spike_start"], "%Y-%m-%d %H:%M:%S")
        b = datetime.strptime(self.man["spike_end"], "%Y-%m-%d %H:%M:%S")
        raw = lambda d: f"{d.month}/{d.day}/{d.year} {d:%H:%M:%S}"      # collector layout, non-padded
        for f in prim:
            self.assertEqual(f["window"]["start_raw"], raw(a))
            self.assertEqual(f["window"]["end_raw"], raw(b))
        self.assertEqual(len({f["device"] for f in prim}), 2)
        self.assertEqual(len(r["clusters"]), 1)
        self.assertTrue(r["clusters"][0]["label"].startswith("shared-cause"))


class ErrorsPreset(unittest.TestCase):
    def test_cumulative_counter_decrease_is_excluded_not_guessed(self):
        p = PRESETS["nexus_collect_errors"]
        text = ("Caption,IP_Address,Interface Name,Full Name,Received Discards,Received Errors,Transmit Discards,Transmit Errors,Timestamp\n"
                "H1,192.0.2.1,Ethernet1/1,x,10,0,0,0,1/5/2026 00:00:00\n"
                "H1,192.0.2.1,Ethernet1/1,x,40,0,0,0,1/5/2026 00:05:00\n"
                "H1,192.0.2.1,Ethernet1/1,x,5,0,0,0,1/5/2026 00:10:00\n")
        ds = ingest.load_csv(text, p["mapping"], p["ts_formats"])
        sl, _ = counters.build_all(ds)
        s = [x for x in sl if x.metric == "rx_discards"][0]
        self.assertEqual(len(s.rate), 1)
        self.assertAlmostEqual(s.rate[0], 30 / 300.0)           # count/s, mult=1
        self.assertEqual(s.excluded[0]["type"], "reset_or_wrap_ambiguous")


if __name__ == "__main__":
    unittest.main()
