"""RTT sampling with Karn's algorithm.

An RTT sample is only taken when a cumulative ACK newly covers a byte range
whose transmission is unambiguous — i.e. the range was transmitted exactly
once.  If the range was retransmitted, the ACK could correspond to either
transmission, so the sample is recorded as RTT-AMBIGUOUS and excluded from
the valid statistics (but retained for forensic display).

Handshake RTTs (SYN->SYN/ACK and SYN/ACK->ACK) are sampled separately and
also contribute valid samples when the handshake is unambiguous.
"""

from __future__ import annotations

from .models import RTTSample


class RTTTracker:
    """Per-direction RTT sample store (direction = the measured data flow)."""

    def __init__(self, direction: str):
        self.direction = direction
        self.samples: list[RTTSample] = []       # valid samples
        self.ambiguous: list[dict] = []          # excluded, kept as evidence

    def add_sample(self, ts_ns: int, rtt_ns: int, kind: str,
                   frame_data: int, frame_ack: int, seq: int, end: int) -> None:
        if rtt_ns < 0:
            return  # out-of-order capture timestamps: never fabricate a sample
        self.samples.append(RTTSample(
            timestamp_ns=ts_ns, rtt_ns=rtt_ns, kind=kind,
            direction=self.direction, frame_data=frame_data,
            frame_ack=frame_ack, seq=seq, end=end))

    def add_ambiguous(self, ts_ns: int, frame_data: int, frame_ack: int,
                      seq: int, end: int, reason: str) -> None:
        self.ambiguous.append({
            "ts": ts_ns, "frame_data": frame_data, "frame_ack": frame_ack,
            "seq": seq, "end": end, "reason": reason})

    def values_ns(self) -> list[int]:
        return [s.rtt_ns for s in self.samples]
