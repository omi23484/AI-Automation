"""Timestamp normalization and honest-precision reporting.

Every timestamp inside the analyzer is an *integer number of nanoseconds*
since the Unix epoch.  The capture reader reports the native resolution of
the capture file (per pcap magic / per pcapng interface ``if_tsresol``) and
that native resolution is surfaced verbatim in the report — nanosecond
*display* never implies nanosecond *accuracy*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NS_PER_SEC = 1_000_000_000
NS_PER_US = 1_000
NS_PER_MS = 1_000_000


@dataclass
class TimestampResolution:
    """Native resolution of a capture (or one pcapng interface)."""

    ticks_per_second: int  # e.g. 1_000_000 for µs pcap, 1_000_000_000 for ns

    @property
    def ns_per_tick(self) -> int:
        """Effective precision in nanoseconds (rounded up for odd resolutions)."""
        return max(1, (NS_PER_SEC + self.ticks_per_second - 1) // self.ticks_per_second)

    @property
    def label(self) -> str:
        if self.ticks_per_second >= NS_PER_SEC:
            return "1 ns"
        if self.ticks_per_second == 1_000_000:
            return "1 µs"
        if self.ticks_per_second == 1_000:
            return "1 ms"
        return f"1/{self.ticks_per_second} s"

    def to_ns(self, ticks: int) -> int:
        """Convert native ticks to integer nanoseconds without float error."""
        tps = self.ticks_per_second
        if tps == NS_PER_SEC:
            return ticks
        # integer arithmetic: seconds part exact, sub-second part scaled exactly
        return (ticks * NS_PER_SEC) // tps


@dataclass
class CaptureTimeInfo:
    """Capture-level timing metadata for the report header."""

    file_format: str = "unknown"          # "pcap" | "pcapng"
    resolutions: list = field(default_factory=list)  # TimestampResolution per interface
    first_ts_ns: int | None = None
    last_ts_ns: int | None = None
    packet_count: int = 0
    tcp_packet_count: int = 0

    def note_packet(self, ts_ns: int) -> None:
        if self.first_ts_ns is None or ts_ns < self.first_ts_ns:
            self.first_ts_ns = ts_ns
        if self.last_ts_ns is None or ts_ns > self.last_ts_ns:
            self.last_ts_ns = ts_ns

    @property
    def duration_ns(self) -> int:
        if self.first_ts_ns is None or self.last_ts_ns is None:
            return 0
        return self.last_ts_ns - self.first_ts_ns

    @property
    def finest_resolution(self) -> TimestampResolution | None:
        if not self.resolutions:
            return None
        return max(self.resolutions, key=lambda r: r.ticks_per_second)

    @property
    def coarsest_resolution(self) -> TimestampResolution | None:
        if not self.resolutions:
            return None
        return min(self.resolutions, key=lambda r: r.ticks_per_second)

    def effective_precision_ns(self) -> int:
        res = self.coarsest_resolution
        return res.ns_per_tick if res else NS_PER_SEC


def format_ns_utc(ts_ns: int | None) -> str:
    """Render an epoch-ns timestamp as UTC ``HH:MM:SS.nnnnnnnnn`` with date."""
    if ts_ns is None:
        return "-"
    import datetime

    sec, frac = divmod(ts_ns, NS_PER_SEC)
    dt = datetime.datetime.fromtimestamp(sec, datetime.timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f".{frac:09d}"


def format_duration_ns(dur_ns: int | None) -> str:
    if dur_ns is None:
        return "-"
    sec, frac = divmod(abs(dur_ns), NS_PER_SEC)
    sign = "-" if dur_ns < 0 else ""
    return f"{sign}{sec}.{frac:09d} s"
