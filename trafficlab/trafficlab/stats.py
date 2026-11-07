"""Pure-python robust statistics. No dependencies."""
import math

MAD_SCALE = 1.4826  # 1 / inverse-normal-CDF(0.75) = 1.482602...


def mean(xs):
    return sum(xs) / len(xs)


def median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        raise ValueError("median of empty")
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def mad(xs, med=None):
    """Raw median absolute deviation (NOT scaled by 1.4826)."""
    if med is None:
        med = median(xs)
    return median([abs(x - med) for x in xs])


def percentile(xs, p):
    """Linear interpolation between closest ranks (numpy 'linear', type 7). p in [0,100]."""
    s = sorted(xs)
    return percentile_sorted(s, p)


def percentile_sorted(s, p):
    n = len(s)
    if n == 0:
        raise ValueError("percentile of empty")
    if n == 1:
        return float(s[0])
    pos = (n - 1) * p / 100.0
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def variance(xs):
    """Sample variance (ddof=1). None if n<2."""
    n = len(xs)
    if n < 2:
        return None
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def pearson(a, b):
    n = len(a)
    if n < 3 or n != len(b):
        return None
    ma, mb = mean(a), mean(b)
    sa = sum((x - ma) ** 2 for x in a)
    sb = sum((y - mb) ** 2 for y in b)
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(sa * sb)
