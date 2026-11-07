import math
import random
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from trafficlab.counters import Series

T0_MS = 1767571200000  # 2026-01-05T00:00:00Z (Monday)


def mk_series(values, interval_s=300, start_ms=T0_MS, key="D|I|in_bps", device="D", zone="DC", unit="bps"):
    s = Series(key=key, device=device, interface="I", zone=zone, metric="in_bps", unit=unit, kind="counter")
    s.interval_ms = interval_s * 1000
    s.n_samples = len(values) + 1
    for i, v in enumerate(values):
        t = start_ms + (i + 1) * s.interval_ms
        s.ts_ms.append(t)
        s.ts_raw.append(f"RAW{t}")
        s.ts_fmt.append("fmt|assumed")
        s.rate.append(float(v))
        s.method.append("delta")
    return s


def daily_values(days, interval_s=300, base=100e6, amp=0.4, noise=0.03, weekend=0.6, seed=1, mod=None):
    """mod(k, t_s, v) -> v lets a test inject known events."""
    rnd = random.Random(seed)
    n = days * 86400 // interval_s
    out = []
    for k in range(n):
        t = (k + 1) * interval_s
        h = (t % 86400) / 3600
        dow = (t // 86400) % 7  # T0 is Monday
        v = base * (1 + amp * math.sin((h - 9) / 24 * 2 * math.pi)) * (weekend if dow >= 5 else 1.0)
        v *= 1 + rnd.gauss(0, noise)
        if mod:
            v = mod(k, t, v)
        out.append(v)
    return out
