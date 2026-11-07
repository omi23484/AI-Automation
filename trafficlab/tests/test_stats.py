import unittest
from helpers import *
from trafficlab import stats


class T(unittest.TestCase):
    def test_median(self):
        self.assertEqual(stats.median([3, 1, 2]), 2)
        self.assertEqual(stats.median([4, 1, 2, 3]), 2.5)

    def test_mad_hand_calc(self):
        # data 1,2,3,4,100 -> median 3 -> abs dev 2,1,0,1,97 -> median 1
        self.assertEqual(stats.mad([1, 2, 3, 4, 100]), 1)

    def test_percentile_linear(self):
        xs = list(range(1, 11))  # 1..10
        self.assertAlmostEqual(stats.percentile(xs, 50), 5.5)
        self.assertAlmostEqual(stats.percentile(xs, 95), 9.55)   # pos=8.55
        self.assertAlmostEqual(stats.percentile(xs, 99), 9.91)
        self.assertEqual(stats.percentile(xs, 0), 1)
        self.assertEqual(stats.percentile(xs, 100), 10)

    def test_percentile_matches_numpy_if_present(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        import random
        r = random.Random(3)
        xs = [r.random() for _ in range(101)]
        for p in (1, 50, 95, 99, 99.9):
            self.assertAlmostEqual(stats.percentile(xs, p), float(np.percentile(xs, p)), places=10)

    def test_variance_pearson(self):
        self.assertAlmostEqual(stats.variance([1, 2, 3, 4]), 5 / 3)
        self.assertAlmostEqual(stats.pearson([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)
        self.assertAlmostEqual(stats.pearson([1, 2, 3, 4], [8, 6, 4, 2]), -1.0)
        self.assertIsNone(stats.pearson([1, 1, 1], [1, 2, 3]))


if __name__ == "__main__":
    unittest.main()
