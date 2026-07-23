"""SACK option analysis: negotiation, scoreboard, holes, DSACK.

The scoreboard is maintained *per data direction*: SACK blocks arriving on
packets from B refer to sequence space of data sent by A.  Each processed
SACK-bearing ACK produces a scoreboard snapshot event so the report can step
through scoreboard evolution chronologically (section 23).
"""

from __future__ import annotations

from .models import SackBlockRecord
from .tcp_sequence import IntervalSet


class SackScoreboard:
    """Scoreboard for one data direction (sequence space of that sender)."""

    def __init__(self, direction: str):
        self.direction = direction
        self.sacked = IntervalSet()
        self.cum_ack: int | None = None
        self.records: list[SackBlockRecord] = []
        # open holes: {start64: {"start","end","first_ts","first_frame","closed"}}
        self.holes: dict[int, dict] = {}
        self.hole_history: list[dict] = []
        self.snapshots: list[dict] = []          # chronological scoreboard states
        self.dsack_count = 0
        self.sack_block_total = 0

    # ------------------------------------------------------------------ input
    def process_ack(self, frame: int, ts_ns: int, capture_id: int,
                    ack64: int, blocks64: list[tuple[int, int]]) -> SackBlockRecord | None:
        """Feed one ACK (with or without SACK blocks) into the scoreboard."""
        prev_ack = self.cum_ack
        if self.cum_ack is None or ack64 > self.cum_ack:
            self.cum_ack = ack64
        # cumulative ACK closes holes below it
        if self.cum_ack is not None:
            for h in self.holes.values():
                if not h["closed"] and h["end"] <= self.cum_ack:
                    h["closed"] = True
                    h["closed_ts"] = ts_ns
                    h["closed_frame"] = frame
            self.sacked.remove_below(self.cum_ack)

        if not blocks64:
            return None

        is_dsack, reason = self._detect_dsack(ack64, blocks64)
        rec = SackBlockRecord(frame_number=frame, timestamp_ns=ts_ns,
                              capture_id=capture_id, ack=ack64,
                              blocks=tuple(blocks64), is_dsack=is_dsack,
                              dsack_reason=reason)
        self.records.append(rec)
        self.sack_block_total += len(blocks64)
        if is_dsack:
            self.dsack_count += 1
            # DSACK first block reports already-received data; it does not
            # extend the scoreboard.  Remaining blocks behave as normal SACK.
            blocks_for_board = blocks64[1:]
        else:
            blocks_for_board = blocks64
        for left, right in blocks_for_board:
            if right > left:
                self.sacked.add(left, right)
        if self.cum_ack is not None:
            self.sacked.remove_below(self.cum_ack)
        self._update_holes(frame, ts_ns)
        self._snapshot(frame, ts_ns, is_dsack, prev_ack)
        return rec

    # ----------------------------------------------------------------- holes
    def _update_holes(self, frame: int, ts_ns: int) -> None:
        if self.cum_ack is None or not self.sacked:
            return
        hi = self.sacked.ends[-1]
        for start, end in self.sacked.gaps_between(self.cum_ack, hi):
            key = start
            if key in self.holes and not self.holes[key]["closed"]:
                h = self.holes[key]
                if end != h["end"]:
                    h["end"] = min(h["end"], end) if h["closed"] is False else end
                continue
            if key not in self.holes:
                h = {"start": start, "end": end, "first_ts": ts_ns,
                     "first_frame": frame, "closed": False,
                     "closed_ts": None, "closed_frame": None}
                self.holes[key] = h
                self.hole_history.append(h)
        # holes fully covered by SACK become "sacked over" (retransmit arrived
        # out-of-band or reordering resolved) — closed when cum_ack passes them
        for h in self.holes.values():
            if not h["closed"] and self.sacked.contains_range(h["start"], h["end"]):
                h["closed"] = True
                h["closed_ts"] = ts_ns
                h["closed_frame"] = frame

    def open_holes(self) -> list[dict]:
        return [h for h in self.holes.values() if not h["closed"]]

    # ----------------------------------------------------------------- dsack
    def _detect_dsack(self, ack64: int, blocks: list[tuple[int, int]]):
        """RFC 2883: first block below cumulative ACK, or first block covered
        by the second block, signals a duplicate."""
        l0, r0 = blocks[0]
        if r0 <= ack64:
            return True, "first SACK block entirely below cumulative ACK"
        if len(blocks) >= 2:
            l1, r1 = blocks[1]
            if l1 <= l0 and r0 <= r1:
                return True, "first SACK block contained in second block"
        return False, None

    # -------------------------------------------------------------- snapshot
    def _snapshot(self, frame: int, ts_ns: int, is_dsack: bool, prev_ack) -> None:
        self.snapshots.append({
            "frame": frame,
            "ts": ts_ns,
            "ack": self.cum_ack,
            "sacked": self.sacked.intervals(),
            "holes": [(h["start"], h["end"]) for h in self.open_holes()],
            "dsack": is_dsack,
            "ack_advanced": prev_ack is not None and self.cum_ack is not None
                            and self.cum_ack > prev_ack,
        })
