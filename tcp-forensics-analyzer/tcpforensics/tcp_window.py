"""TCP receive-window tracking per direction.

Tracks the advertised window of each endpoint (scaled once the handshake
window-scale factors are known), and emits events for zero-window, probes,
window updates that end a zero-window episode, and possible window-full
conditions (bytes in flight reaching the peer's advertised window).
"""

from __future__ import annotations

from .models import WindowEvent


class WindowTracker:
    """Window state for one advertiser (the endpoint sending the window)."""

    def __init__(self, direction: str):
        self.direction = direction          # direction of packets carrying the window
        self.scale: int | None = None       # advertiser's negotiated send scale
        self.scale_known = False
        self.last_window: int | None = None
        self.zero_window_open_ts: int | None = None
        self.events: list[WindowEvent] = []
        self.zero_window_count = 0
        self.update_count = 0
        self.min_window: int | None = None
        self.max_window: int | None = None

    def effective_window(self, raw: int, in_syn: bool) -> int:
        if in_syn or not self.scale_known or self.scale is None:
            return raw
        return raw << self.scale

    def process(self, frame: int, ts_ns: int, raw_window: int, in_syn: bool) -> None:
        win = self.effective_window(raw_window, in_syn)
        self.min_window = win if self.min_window is None else min(self.min_window, win)
        self.max_window = win if self.max_window is None else max(self.max_window, win)
        prev = self.last_window
        self.last_window = win
        if win == 0 and not in_syn:
            if self.zero_window_open_ts is None:
                self.zero_window_open_ts = ts_ns
                self.zero_window_count += 1
                self.events.append(WindowEvent(
                    kind="zero-window", direction=self.direction,
                    frame_number=frame, timestamp_ns=ts_ns, window_bytes=0,
                    detail="advertised receive window dropped to 0"))
            return
        if self.zero_window_open_ts is not None and win > 0:
            stall = ts_ns - self.zero_window_open_ts
            self.events.append(WindowEvent(
                kind="window-recovery", direction=self.direction,
                frame_number=frame, timestamp_ns=ts_ns, window_bytes=win,
                detail=f"zero-window episode ended after {stall} ns"))
            self.zero_window_open_ts = None
        if prev is not None and win > prev:
            self.update_count += 1

    def note_probe(self, frame: int, ts_ns: int) -> None:
        self.events.append(WindowEvent(
            kind="zero-window-probe", direction=self.direction,
            frame_number=frame, timestamp_ns=ts_ns, window_bytes=0,
            detail="probe into a zero receive window"))

    def note_window_full(self, frame: int, ts_ns: int, in_flight: int, win: int) -> None:
        self.events.append(WindowEvent(
            kind="window-full", direction=self.direction,
            frame_number=frame, timestamp_ns=ts_ns, window_bytes=win,
            detail=f"bytes in flight {in_flight} reached advertised window {win}"))
