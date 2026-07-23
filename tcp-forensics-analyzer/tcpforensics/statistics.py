"""Integer-friendly latency statistics (percentiles, histogram, CDF)."""

from __future__ import annotations

import math


def percentile(sorted_vals: list[int], p: float) -> int | None:
    """Nearest-rank percentile on a pre-sorted list of integers."""
    if not sorted_vals:
        return None
    if p <= 0:
        return sorted_vals[0]
    if p >= 100:
        return sorted_vals[-1]
    rank = math.ceil(p / 100.0 * len(sorted_vals))
    return sorted_vals[max(0, rank - 1)]


def summarize(values: list[int], min_p999_samples: int = 100) -> dict:
    """Full latency summary in integer nanoseconds.

    P99.9 is only reported when the sample count makes it meaningful
    (>= *min_p999_samples*), per the accuracy requirements.
    """
    if not values:
        return {"count": 0}
    vals = sorted(values)
    n = len(vals)
    total = sum(vals)
    mean = total // n
    var = sum((v - mean) ** 2 for v in vals) // n if n > 1 else 0
    out = {
        "count": n,
        "min": vals[0],
        "max": vals[-1],
        "mean": mean,
        "median": percentile(vals, 50),
        "p50": percentile(vals, 50),
        "p90": percentile(vals, 90),
        "p95": percentile(vals, 95),
        "p99": percentile(vals, 99),
        "stddev": int(math.isqrt(var)),
    }
    if n >= min_p999_samples:
        out["p999"] = percentile(vals, 99.9)
    return out


def histogram(values: list[int], buckets: int = 40) -> dict:
    """Linear histogram + CDF points for the report charts."""
    if not values:
        return {"buckets": [], "counts": [], "cdf": []}
    vals = sorted(values)
    lo, hi = vals[0], vals[-1]
    if hi == lo:
        return {"buckets": [lo], "counts": [len(vals)],
                "cdf": [[lo, 100.0]]}
    width = max(1, (hi - lo) // buckets)
    counts = [0] * (buckets + 1)
    for v in vals:
        counts[min(buckets, (v - lo) // width)] = counts[min(buckets, (v - lo) // width)] + 1
    edges = [lo + i * width for i in range(len(counts))]
    n = len(vals)
    cdf = []
    step = max(1, n // 200)
    for i in range(0, n, step):
        cdf.append([vals[i], round((i + 1) * 100.0 / n, 3)])
    cdf.append([vals[-1], 100.0])
    return {"buckets": edges, "counts": counts, "cdf": cdf}
