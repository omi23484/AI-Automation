"""Loss / recovery lifecycle management (first-class Loss Events).

A Loss Event is opened when the capture first shows evidence that a byte
range went missing — a SACK hole, a duplicate-ACK train, a receiver-side
sequence gap, or an unexplained retransmission — and is driven through:

    original TX -> first evidence -> retransmission -> recovery ACK

with all four deltas kept in integer nanoseconds.  Gap evidence is NOT
automatically loss: gaps filled by a never-before-seen segment are
classified as reordering, and duplicate/DSACK evidence downgrades events to
duplicate/spurious, with the reasoning recorded on the event.
"""

from __future__ import annotations

from .models import LossEvent


class LossManager:
    """Loss events for one data direction of one session."""

    def __init__(self, direction: str, capture_id: int):
        self.direction = direction
        self.capture_id = capture_id
        self.events: list[LossEvent] = []
        self._open_by_start: dict[int, LossEvent] = {}
        self._next_id = 0

    # ------------------------------------------------------------------ open
    def open_event(self, seq: int, end: int, evidence_kind: str,
                   evidence_ts: int, evidence_frame: int,
                   original_tx_ns: int | None, original_frame: int | None,
                   sack_involved: bool = False,
                   classification: str = "loss",
                   classification_evidence: str = "") -> LossEvent:
        existing = self._find_overlap(seq, end)
        if existing is not None:
            # extend evidence on the existing episode instead of duplicating
            if existing.first_evidence_ns is None or evidence_ts < existing.first_evidence_ns:
                existing.first_evidence_ns = evidence_ts
                existing.first_evidence_frame = evidence_frame
                existing.evidence_kind = evidence_kind
            existing.sack_involved = existing.sack_involved or sack_involved
            return existing
        ev = LossEvent(
            loss_id=self._next_id, capture_id=self.capture_id,
            direction=self.direction, seq=seq, end=end, bytes=end - seq,
            original_tx_ns=original_tx_ns, original_frame=original_frame,
            first_evidence_ns=evidence_ts, first_evidence_frame=evidence_frame,
            evidence_kind=evidence_kind, sack_involved=sack_involved,
            classification=classification,
            classification_evidence=classification_evidence)
        self._next_id += 1
        self.events.append(ev)
        self._open_by_start[seq] = ev
        return ev

    def _find_overlap(self, seq: int, end: int) -> LossEvent | None:
        for ev in self._open_by_start.values():
            if ev.seq < end and seq < ev.end and not ev.recovered:
                return ev
        return None

    # -------------------------------------------------------------- lifecycle
    def note_retransmission(self, seq: int, end: int, frame: int,
                            ts_ns: int, mechanism: str) -> LossEvent | None:
        ev = self._find_overlap(seq, end)
        if ev is None:
            return None
        if ev.retrans_ns is None:
            ev.retrans_ns = ts_ns
            ev.retrans_frame = frame
            ev.likely_mechanism = mechanism
        else:
            # the range needed retransmitting again: earlier retransmission
            # itself was likely lost
            ev.retrans_lost = True
        return ev

    def note_dup_acks(self, seq: int, end: int, count: int) -> None:
        ev = self._find_overlap(seq, end)
        if ev is not None:
            ev.dup_ack_count = max(ev.dup_ack_count, count)

    def note_sack_report(self, seq: int, end: int) -> None:
        ev = self._find_overlap(seq, end)
        if ev is not None:
            ev.sack_report_count += 1
            ev.sack_involved = True

    def note_additional_hole(self, during_ts: int) -> None:
        for ev in self._open_by_start.values():
            if not ev.recovered and ev.first_evidence_ns is not None \
                    and ev.first_evidence_ns < during_ts:
                ev.additional_holes += 1

    def note_cum_ack(self, ack64: int, frame: int, ts_ns: int) -> list[LossEvent]:
        """Cumulative ACK advanced: close any events now fully covered."""
        recovered = []
        for start in list(self._open_by_start):
            ev = self._open_by_start[start]
            if ev.end <= ack64:
                ev.recovered = True
                ev.recovery_ns = ts_ns
                ev.recovery_frame = frame
                ev.partial = False
                del self._open_by_start[start]
                recovered.append(ev)
            elif ev.seq < ack64 < ev.end:
                ev.partial = True
        return recovered

    def reclassify(self, seq: int, end: int, classification: str,
                   evidence: str) -> None:
        for ev in self.events:
            if ev.seq < end and seq < ev.end:
                ev.classification = classification
                ev.classification_evidence = evidence

    # ------------------------------------------------------------------ stats
    def recovered_events(self) -> list[LossEvent]:
        return [e for e in self.events if e.recovered and e.classification == "loss"]

    def unrecovered_events(self) -> list[LossEvent]:
        return [e for e in self.events if not e.recovered and e.classification == "loss"]
