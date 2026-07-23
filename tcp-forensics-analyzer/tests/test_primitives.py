"""Unit tests: sequence arithmetic, interval structures, statistics."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tcpforensics.statistics import percentile, summarize
from tcpforensics.tcp_sequence import IntervalSet, SeqUnwrapper, unwrap32


class TestUnwrap(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(unwrap32(100, None), 100)
        self.assertEqual(unwrap32(100, 90), 100)

    def test_wrap_forward(self):
        ref = 0xFFFFFF00
        self.assertEqual(unwrap32(0x00000010, ref), 0x100000010)

    def test_wrap_backward(self):
        ref = 0x100000010
        self.assertEqual(unwrap32(0xFFFFFF00, ref), 0xFFFFFF00)

    def test_unwrapper_monotonic(self):
        u = SeqUnwrapper()
        vals = [u.unwrap(x) for x in
                (0xFFFFFE00, 0xFFFFFF00, 0x00000100, 0x00000200)]
        self.assertEqual(vals, [0xFFFFFE00, 0xFFFFFF00,
                                0x100000100, 0x100000200])
        # an old (retransmitted) sequence still unwraps below the reference
        self.assertEqual(u.unwrap_no_advance(0xFFFFFF80), 0xFFFFFF80)


class TestIntervalSet(unittest.TestCase):
    def test_add_merge(self):
        s = IntervalSet()
        s.add(10, 20)
        s.add(30, 40)
        s.add(20, 30)
        self.assertEqual(s.intervals(), [(10, 40)])
        self.assertEqual(s.total_bytes(), 30)

    def test_overlap_and_contains(self):
        s = IntervalSet()
        s.add(100, 200)
        s.add(300, 400)
        self.assertEqual(s.overlap(150, 350), [(150, 200), (300, 350)])
        self.assertTrue(s.contains_range(120, 180))
        self.assertFalse(s.contains_range(150, 350))

    def test_gaps(self):
        s = IntervalSet()
        s.add(1000, 1500)
        s.add(2000, 2500)
        s.add(2500, 3000)
        self.assertEqual(s.gaps_between(1000, 3000), [(1500, 2000)])

    def test_remove_below(self):
        s = IntervalSet()
        s.add(100, 200)
        s.add(300, 400)
        s.remove_below(350)
        self.assertEqual(s.intervals(), [(350, 400)])


class TestStats(unittest.TestCase):
    def test_percentile_nearest_rank(self):
        vals = list(range(1, 101))
        self.assertEqual(percentile(vals, 50), 50)
        self.assertEqual(percentile(vals, 99), 99)
        self.assertEqual(percentile(vals, 100), 100)

    def test_summarize_integer(self):
        s = summarize([100, 200, 300])
        self.assertEqual(s["count"], 3)
        self.assertEqual(s["min"], 100)
        self.assertEqual(s["median"], 200)
        self.assertEqual(s["max"], 300)
        self.assertNotIn("p999", s)  # too few samples for P99.9

    def test_p999_requires_samples(self):
        s = summarize(list(range(1000)))
        self.assertIn("p999", s)


if __name__ == "__main__":
    unittest.main()
