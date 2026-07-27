"""Retransmission detection and evidence-based classification.

Detection is sequence-space based (overlap with previously transmitted byte
ranges), never packet-equality based.  Classification uses the surrounding
connection state — duplicate-ACK counts, SACK scoreboard holes, elapsed
time, and whether the range was already ACKed/SACKed:

    fast-retransmission     >= dupack_threshold duplicate ACKs or an open
                            SACK hole covering the range preceded it
    rto-retransmission      delay since the previous transmission exceeds
                            the configured RTO floor and no fast-retx signal
    possible-spurious       the range was already cumulatively ACKed (or
                            fully SACKed) before the retransmission left
    duplicate               same range re-seen within the duplicate window
                            (likely capture-level duplication)
    partial / overlapping   partial sequence overlap with earlier segments
    ambiguous               evidence insufficient to pick one
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetransConfig:
    dupack_threshold: int = 3
    rto_floor_ns: int = 200_000_000          # 200 ms conservative RTO floor
    duplicate_window_ns: int = 2_000_000     # 2 ms: capture-dup heuristic
    srtt_rto_multiplier: int = 3             # delay > 3 * sRTT also suggests RTO
    # window for recognizing the SAME IP packet observed at multiple capture
    # points (SPAN on several leafs, routed hops): identical TCP content +
    # identical non-zero IP ID within this window is one packet, not a
    # retransmission — a retransmission is a NEW IP packet with a new IP ID
    observation_window_ns: int = 20_000_000  # 20 ms


def classify(*, delay_since_last_tx_ns: int | None,
             dup_acks: int, sack_hole_over_range: bool,
             already_acked: bool, already_sacked: bool,
             full_overlap: bool, partial_overlap: bool,
             srtt_ns: int | None, cfg: RetransConfig) -> tuple[str, str]:
    """Return (classification, human-readable evidence)."""
    ev = []
    if delay_since_last_tx_ns is not None:
        ev.append(f"delay since previous transmission {delay_since_last_tx_ns} ns")
    if dup_acks:
        ev.append(f"{dup_acks} duplicate ACKs observed before retransmission")
    if sack_hole_over_range:
        ev.append("open SACK hole covered the range")
    if already_acked:
        ev.append("range was already cumulatively ACKed")
    if already_sacked:
        ev.append("range was already SACKed")

    if already_acked or already_sacked:
        if (delay_since_last_tx_ns is not None
                and delay_since_last_tx_ns <= cfg.duplicate_window_ns):
            return "duplicate", "; ".join(ev + [
                f"re-seen within {cfg.duplicate_window_ns} ns duplicate window "
                "(possible capture-level duplication)"])
        return "possible-spurious", "; ".join(ev)

    if not full_overlap and partial_overlap:
        base = "partial-retransmission"
    elif not full_overlap:
        base = "overlapping-retransmission"
    else:
        base = None

    fast_signal = dup_acks >= cfg.dupack_threshold or sack_hole_over_range
    rto_signal = False
    if delay_since_last_tx_ns is not None:
        if delay_since_last_tx_ns >= cfg.rto_floor_ns:
            rto_signal = True
        elif srtt_ns and delay_since_last_tx_ns >= cfg.srtt_rto_multiplier * srtt_ns \
                and not fast_signal:
            rto_signal = True

    if fast_signal and not rto_signal:
        kind = "fast-retransmission"
    elif rto_signal and not fast_signal:
        kind = "rto-retransmission"
        ev.append(f"delay exceeded RTO heuristic "
                  f"(floor {cfg.rto_floor_ns} ns / {cfg.srtt_rto_multiplier}x sRTT)")
    elif fast_signal and rto_signal:
        kind = "fast-retransmission"
        ev.append("both fast-retx and RTO signals present; dup-ACK/SACK "
                  "evidence takes precedence")
    else:
        kind = "retransmission"
        ev.append("no dup-ACK/SACK trigger visible and delay below RTO "
                  "heuristic — mechanism ambiguous")

    if base:
        ev.append(f"sequence overlap was {base.replace('-', ' ')}")
        if kind == "retransmission":
            kind = base
    return kind, "; ".join(ev)
