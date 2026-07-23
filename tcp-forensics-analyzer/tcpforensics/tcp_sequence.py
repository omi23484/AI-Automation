"""Wraparound-aware TCP sequence arithmetic and interval structures.

TCP sequence numbers are 32-bit and wrap.  Raw numbers are never compared
numerically; every sequence value entering the engine is *unwrapped* into a
monotonically extendable 64-bit space anchored near a per-direction
reference (RFC 1982-style serial arithmetic).  All downstream analysis
(ledger, ACK correlation, SACK scoreboard, holes) operates on 64-bit
unwrapped values, so a wrap in the middle of a transfer is transparent.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right, insort

SEQ_MOD = 1 << 32
SEQ_HALF = 1 << 31


def seq_lt(a: int, b: int) -> bool:
    """32-bit serial 'a < b'."""
    return ((b - a) & (SEQ_MOD - 1)) - 1 < SEQ_HALF - 1


def seq_add(a: int, n: int) -> int:
    return (a + n) & (SEQ_MOD - 1)


def unwrap32(value: int, reference: int | None) -> int:
    """Lift a raw 32-bit value into 64-bit space, choosing the candidate
    congruent to *value* (mod 2^32) that lies closest to *reference*."""
    if reference is None:
        return value
    candidate = (reference & ~(SEQ_MOD - 1)) | (value & (SEQ_MOD - 1))
    if candidate + SEQ_HALF < reference:
        candidate += SEQ_MOD
    elif candidate > reference + SEQ_HALF:
        candidate -= SEQ_MOD
    return candidate


class SeqUnwrapper:
    """Per-direction unwrapping context.

    The reference tracks the highest unwrapped value observed so far, so
    slightly-old segments (retransmissions) unwrap below it and new data
    unwraps above it, across any number of 32-bit wraps.
    """

    def __init__(self) -> None:
        self.reference: int | None = None

    def unwrap(self, raw32: int) -> int:
        val = unwrap32(raw32, self.reference)
        if self.reference is None or val > self.reference:
            self.reference = val
        return val

    def unwrap_no_advance(self, raw32: int) -> int:
        """Unwrap against the current reference without moving it (used for
        SACK edges / ACK values referencing the peer's send space)."""
        return unwrap32(raw32, self.reference)


class IntervalSet:
    """Sorted, coalesced set of half-open [start, end) integer intervals.

    Compact (two parallel lists + bisect) so millions of byte-ranges stay
    cheap; used for transmitted-byte tracking and SACK scoreboards.
    """

    __slots__ = ("starts", "ends")

    def __init__(self) -> None:
        self.starts: list[int] = []
        self.ends: list[int] = []

    def __len__(self) -> int:
        return len(self.starts)

    def __bool__(self) -> bool:
        return bool(self.starts)

    def intervals(self) -> list[tuple[int, int]]:
        return list(zip(self.starts, self.ends))

    def total_bytes(self) -> int:
        return sum(e - s for s, e in zip(self.starts, self.ends))

    def add(self, start: int, end: int) -> None:
        if end <= start:
            return
        i = bisect_left(self.ends, start)          # first interval that may touch
        j = bisect_right(self.starts, end)         # last interval that may touch
        if i < j:
            start = min(start, self.starts[i])
            end = max(end, self.ends[j - 1])
            del self.starts[i:j]
            del self.ends[i:j]
        self.starts.insert(i, start)
        self.ends.insert(i, end)

    def remove_below(self, boundary: int) -> None:
        """Drop everything strictly below *boundary* (cumulative-ACK sweep)."""
        i = bisect_right(self.ends, boundary)
        if i:
            del self.starts[:i]
            del self.ends[:i]
        if self.starts and self.starts[0] < boundary:
            self.starts[0] = boundary

    def overlap(self, start: int, end: int) -> list[tuple[int, int]]:
        """Portions of [start, end) already present in the set."""
        out = []
        i = bisect_right(self.ends, start)
        while i < len(self.starts) and self.starts[i] < end:
            out.append((max(start, self.starts[i]), min(end, self.ends[i])))
            i += 1
        return out

    def contains_range(self, start: int, end: int) -> bool:
        i = bisect_right(self.ends, start)
        return i < len(self.starts) and self.starts[i] <= start and self.ends[i] >= end

    def gaps_between(self, lo: int, hi: int) -> list[tuple[int, int]]:
        """Sub-ranges of [lo, hi) NOT covered by the set (the holes)."""
        holes = []
        cur = lo
        i = bisect_right(self.ends, lo)
        while cur < hi and i < len(self.starts) and self.starts[i] < hi:
            if self.starts[i] > cur:
                holes.append((cur, self.starts[i]))
            cur = max(cur, self.ends[i])
            i += 1
        if cur < hi:
            holes.append((cur, hi))
        return holes


class SegmentIndex:
    """Locate previously transmitted data segments overlapping a byte range.

    Keeps (start, seg_id) sorted; a retransmission lookup scans only the
    neighbourhood of the queried range.
    """

    __slots__ = ("_keys", "_max_len")

    def __init__(self) -> None:
        self._keys: list[tuple[int, int, int]] = []   # (start, end, seg_id)
        self._max_len = 0

    def add(self, start: int, end: int, seg_id: int) -> None:
        insort(self._keys, (start, end, seg_id))
        self._max_len = max(self._max_len, end - start)

    def overlapping(self, start: int, end: int) -> list[tuple[int, int, int]]:
        out = []
        lo = bisect_left(self._keys, (start - self._max_len, 0, 0))
        for s, e, sid in self._keys[lo:]:
            if s >= end:
                break
            if e > start:
                out.append((s, e, sid))
        return out
