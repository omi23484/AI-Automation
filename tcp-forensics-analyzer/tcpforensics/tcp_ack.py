"""DATA -> ACK correlation with cumulative-ACK semantics.

Every transmitted byte range is tracked until a *cumulative* ACK covers it —
one ACK may acknowledge many segments, and a segment is never naively paired
with "the next ACK packet".  For each newly covered segment we record:

* DATA->ACK latency  (ack ts - ts of the LAST transmission of the range)
* a valid RTT sample (Karn: only if the range was transmitted exactly once);
  otherwise the sample is marked RTT-AMBIGUOUS and excluded from statistics.
"""

from __future__ import annotations

import heapq

from .models import SegmentRecord, ST_ACKED, ST_ORIGINAL, ST_RECOVERED
from .tcp_rtt import RTTTracker
from .tcp_sequence import IntervalSet


class AckCorrelator:
    """Correlates ACKs from the peer against one direction's data ledger."""

    def __init__(self, direction: str, rtt: RTTTracker):
        self.direction = direction
        self.rtt = rtt
        self._unacked: list[tuple[int, int]] = []   # heap of (end64, seg_id)
        self.retransmitted_ranges = IntervalSet()   # Karn exclusion zones
        self.snd_una: int | None = None             # highest cumulative ACK seen
        self.srtt_ns: int | None = None             # smoothed RTT (RTO heuristics)

    def register_segment(self, seg: SegmentRecord) -> None:
        heapq.heappush(self._unacked, (seg.end, seg.seg_id))

    def note_retransmission(self, start: int, end: int) -> None:
        self.retransmitted_ranges.add(start, end)

    def outstanding_count(self) -> int:
        return len(self._unacked)

    def process_ack(self, ack64: int, ack_frame: int, ack_ts_ns: int,
                    segments: list[SegmentRecord]) -> list[SegmentRecord]:
        """Sweep the ledger with a cumulative ACK; return newly ACKed segments."""
        if self.snd_una is not None and ack64 <= self.snd_una:
            return []
        self.snd_una = ack64
        newly = []
        while self._unacked and self._unacked[0][0] <= ack64:
            _end, seg_id = heapq.heappop(self._unacked)
            seg = segments[seg_id]
            if seg.acked_ts_ns is not None:
                continue
            seg.acked_ts_ns = ack_ts_ns
            seg.acked_by_frame = ack_frame
            seg.ack_latency_ns = ack_ts_ns - seg.timestamp_ns
            # forensically interesting states (Out-of-order, Duplicate) stay
            # sticky in the ledger; plain data transitions to ACKed
            if seg.is_retransmission:
                seg.state = ST_RECOVERED
            elif seg.state in (ST_ORIGINAL, "SACKed"):
                seg.state = ST_ACKED
            newly.append(seg)

        if not newly:
            return newly

        # RTT sampling: prefer the segment whose end matches the ACK exactly
        # (the segment that triggered this ACK); fall back to the highest end.
        # Zero-payload segments (SYN/FIN) are excluded — handshake RTT is
        # sampled separately as syn-synack / synack-ack.
        newly.sort(key=lambda s: s.end)
        data_newly = [s for s in newly if s.payload_len > 0]
        if not data_newly:
            return newly
        sample_seg = None
        for seg in data_newly:
            if seg.end == ack64:
                sample_seg = seg
        if sample_seg is None:
            sample_seg = data_newly[-1]
        for seg in newly:
            ambiguous = (seg.is_retransmission
                         or bool(self.retransmitted_ranges.overlap(seg.seq, seg.end)))
            if ambiguous and seg.payload_len > 0:
                seg.rtt_ambiguous = True   # range transmitted more than once
            if seg is not sample_seg:
                continue
            if ambiguous:
                seg.rtt_ambiguous = True
                self.rtt.add_ambiguous(
                    ack_ts_ns, seg.frame_number, ack_frame, seg.seq, seg.end,
                    "range retransmitted; ACK could match either transmission "
                    "(Karn's algorithm exclusion)")
            else:
                rtt_ns = ack_ts_ns - seg.timestamp_ns
                if rtt_ns >= 0:
                    seg.rtt_ns = rtt_ns
                    self.rtt.add_sample(ack_ts_ns, rtt_ns, "data-ack",
                                        seg.frame_number, ack_frame,
                                        seg.seq, seg.end)
                    self.srtt_ns = (rtt_ns if self.srtt_ns is None
                                    else (7 * self.srtt_ns + rtt_ns) // 8)
        return newly
