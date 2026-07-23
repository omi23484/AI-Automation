"""Compact data model shared by the analysis engine and the report.

Objects use __slots__ dataclasses so multi-million-packet captures stay
memory-friendly.  Session, packet and event objects carry ``capture_id`` /
``capture_point`` so multi-PCAP correlation can be layered on later without
schema changes (section 32 of the design brief).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# TCP flag bits
FIN, SYN, RST, PSH, ACK, URG, ECE, CWR = 1, 2, 4, 8, 16, 32, 64, 128

FLAG_NAMES = [(CWR, "CWR"), (ECE, "ECE"), (URG, "URG"), (ACK, "ACK"),
              (PSH, "PSH"), (RST, "RST"), (SYN, "SYN"), (FIN, "FIN")]


def flags_to_str(flags: int) -> str:
    out = [name for bit, name in FLAG_NAMES if flags & bit]
    return "/".join(out) if out else "-"


# ---------------------------------------------------------------- raw packet
@dataclass(slots=True)
class TCPPacket:
    """One decoded TCP packet as produced by the capture reader."""

    frame_number: int
    timestamp_ns: int
    capture_id: int
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    seq_raw: int
    ack_raw: int
    flags: int
    window_raw: int
    payload_len: int
    ip_total_len: int
    truncated: bool = False
    # TCP options (None when absent)
    mss: int | None = None
    window_scale: int | None = None
    sack_permitted: bool = False
    sack_blocks: tuple = ()          # ((left32, right32), ...)
    ts_val: int | None = None
    ts_ecr: int | None = None

    @property
    def flow_key(self) -> tuple:
        return (self.src_ip, self.src_port, self.dst_ip, self.dst_port)


# ------------------------------------------------------------- ledger entry
# Segment states (sequence ledger, section 4)
ST_ORIGINAL = "Original"
ST_ACKED = "ACKed"
ST_SACKED = "SACKed"
ST_RETRANSMITTED = "Retransmitted"
ST_DUPLICATE = "Duplicate"
ST_OUT_OF_ORDER = "Out-of-order"
ST_RECOVERED = "Recovered"
ST_AMBIGUOUS = "Ambiguous"
ST_MISSING = "Missing"


@dataclass(slots=True)
class SegmentRecord:
    """One transmitted TCP segment in a direction's sequence ledger.

    Sequence values are 64-bit unwrapped; ``rel_*`` are relative to the
    direction's ISN (or first-seen sequence for mid-capture sessions).
    """

    seg_id: int
    frame_number: int
    timestamp_ns: int
    seq: int                 # unwrapped 64-bit start
    end: int                 # unwrapped 64-bit end (seq + payload + SYN/FIN)
    payload_len: int
    flags: int
    ack_raw: int
    window_raw: int
    state: str = ST_ORIGINAL
    is_retransmission: bool = False
    retrans_kind: str | None = None     # fast / rto / spurious / partial / ...
    retrans_of_frame: int | None = None
    retrans_delay_ns: int | None = None
    acked_ts_ns: int | None = None
    acked_by_frame: int | None = None
    ack_latency_ns: int | None = None   # DATA -> covering cumulative ACK
    rtt_ns: int | None = None           # valid (Karn-clean) RTT sample
    rtt_ambiguous: bool = False
    sacked_ts_ns: int | None = None
    sacked_by_frame: int | None = None


# ------------------------------------------------------------------- events
@dataclass(slots=True)
class SackBlockRecord:
    """One SACK option instance (per ACK packet carrying SACK blocks)."""

    frame_number: int
    timestamp_ns: int
    capture_id: int
    ack: int                     # unwrapped cumulative ACK
    blocks: tuple                # ((left64, right64), ...)
    is_dsack: bool = False
    dsack_reason: str | None = None


@dataclass(slots=True)
class RetransmissionEvent:
    frame_number: int
    timestamp_ns: int
    capture_id: int
    direction: str               # "A->B" | "B->A"
    seq: int
    end: int
    bytes: int
    classification: str
    original_frame: int | None
    original_ts_ns: int | None
    delay_ns: int | None
    dup_acks_before: int
    sack_active: bool
    evidence: str


@dataclass(slots=True)
class LossEvent:
    """First-class loss/recovery lifecycle object (section 12)."""

    loss_id: int
    capture_id: int
    direction: str
    seq: int
    end: int
    bytes: int
    original_tx_ns: int | None = None
    original_frame: int | None = None
    first_evidence_ns: int | None = None
    first_evidence_frame: int | None = None
    evidence_kind: str = "sack-hole"       # sack-hole | dup-ack | retransmission | seq-gap
    retrans_ns: int | None = None
    retrans_frame: int | None = None
    retrans_lost: bool = False
    recovery_ns: int | None = None
    recovery_frame: int | None = None
    recovered: bool = False
    partial: bool = False
    sack_involved: bool = False
    dup_ack_count: int = 0
    sack_report_count: int = 0
    additional_holes: int = 0
    likely_mechanism: str = "unknown"      # fast-retransmit | rto | unknown
    classification: str = "loss"           # loss | reordering | duplicate | artifact | ambiguous
    classification_evidence: str = ""

    @property
    def detection_ns(self) -> int | None:
        if self.original_tx_ns is not None and self.first_evidence_ns is not None:
            return self.first_evidence_ns - self.original_tx_ns
        return None

    @property
    def reaction_ns(self) -> int | None:
        if self.first_evidence_ns is not None and self.retrans_ns is not None:
            return self.retrans_ns - self.first_evidence_ns
        return None

    @property
    def post_retrans_recovery_ns(self) -> int | None:
        if self.retrans_ns is not None and self.recovery_ns is not None:
            return self.recovery_ns - self.retrans_ns
        return None

    @property
    def total_recovery_ns(self) -> int | None:
        if self.original_tx_ns is not None and self.recovery_ns is not None:
            return self.recovery_ns - self.original_tx_ns
        return None


@dataclass(slots=True)
class DupAckTrain:
    direction: str               # direction of the ACK sender
    ack: int
    first_frame: int
    first_ts_ns: int
    count: int = 1
    last_ts_ns: int = 0
    gaps_ns: list = field(default_factory=list)
    sack_blocks: int = 0
    missing_seq: int | None = None
    missing_end: int | None = None
    retrans_frame: int | None = None
    time_to_retrans_ns: int | None = None
    time_to_recovery_ns: int | None = None


@dataclass(slots=True)
class WindowEvent:
    kind: str                    # zero-window | window-update | zero-window-probe | window-recovery | window-full
    direction: str               # direction of the advertiser (for probes: the prober)
    frame_number: int
    timestamp_ns: int
    window_bytes: int
    detail: str = ""


@dataclass(slots=True)
class RTTSample:
    timestamp_ns: int
    rtt_ns: int
    kind: str                    # data-ack | syn-synack | synack-ack | ts-opt
    direction: str               # direction of the measured data flow
    frame_data: int
    frame_ack: int
    seq: int
    end: int
