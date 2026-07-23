"""Rule-based, evidence-backed session verdicts (section 27).

Every verdict carries the threshold that fired and the measured value, so
nothing in the report is an unexplained conclusion.  Thresholds are
configurable via :class:`VerdictConfig` (CLI flags / JSON config).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class VerdictConfig:
    low_retrans_pct: float = 0.5          # below → LOW RETRANSMISSION
    high_retrans_pct: float = 2.0         # above → HIGH RETRANSMISSION
    high_rtt_ns: int = 100_000_000        # median RTT above 100 ms
    rtt_outlier_ratio: float = 10.0       # p99 / median ratio → RTT OUTLIERS
    repeated_holes: int = 3               # distinct SACK holes → REPEATED HOLES
    reordering_events: int = 1
    zero_window_events: int = 1
    spurious_retrans: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(stats: dict, cfg: VerdictConfig) -> list[dict]:
    """Return a list of {verdict, severity, evidence} for one session."""
    out: list[dict] = []

    def add(verdict: str, severity: str, evidence: str):
        out.append({"verdict": verdict, "severity": severity,
                    "evidence": evidence})

    if stats.get("partial"):
        add("INCOMPLETE CAPTURE", "info",
            "Connection establishment was not observed — the capture begins "
            "mid-session; byte accounting and negotiation state are partial.")
    if stats.get("rst"):
        add("SESSION RESET", "warn",
            f"RST observed (frame {stats.get('rst_frame')}); the session was "
            "aborted rather than closed with FIN.")

    rp = stats.get("retrans_pct")
    segs = stats.get("retrans_segments", 0)
    if rp is not None and stats.get("data_segments", 0) > 0:
        if segs == 0:
            add("HEALTHY", "ok", "No retransmitted segments detected in "
                f"{stats['data_segments']} data segments.")
        elif rp < cfg.low_retrans_pct:
            add("LOW RETRANSMISSION", "ok",
                f"{segs} retransmitted segments = {rp:.2f}% of data segments "
                f"(threshold: below {cfg.low_retrans_pct}%).")
        elif rp >= cfg.high_retrans_pct:
            add("HIGH RETRANSMISSION", "bad",
                f"{segs} retransmitted segments = {rp:.2f}% of data segments "
                f"(threshold: {cfg.high_retrans_pct}%). "
                f"{stats.get('retrans_bytes', 0)} bytes retransmitted.")

    rtt = stats.get("rtt", {})
    med, p99 = rtt.get("median"), rtt.get("p99")
    if med is not None and med > cfg.high_rtt_ns:
        add("HIGH RTT", "bad",
            f"Median valid RTT {med} ns exceeds threshold {cfg.high_rtt_ns} ns "
            f"({rtt.get('count')} valid samples; ambiguous samples excluded "
            "per Karn's algorithm).")
    if med and p99 and med > 0 and p99 / med >= cfg.rtt_outlier_ratio:
        add("RTT OUTLIERS", "warn",
            f"P99 RTT {p99} ns is {p99 / med:.1f}x the median {med} ns "
            f"(threshold ratio: {cfg.rtt_outlier_ratio}).")

    sack_recovered = stats.get("sack_recovered_losses", 0)
    loss_total = stats.get("loss_events", 0)
    if sack_recovered:
        rec = stats.get("recovery", {})
        extra = ""
        if rec.get("median") is not None:
            extra = (f" Median recovery {rec['median']} ns, "
                     f"P95 {rec.get('p95')} ns.")
        add("SACK-BASED LOSS RECOVERY OBSERVED", "info",
            f"{sack_recovered} of {loss_total} loss events show SACK "
            f"involvement during recovery.{extra}")
    if stats.get("sack_holes", 0) >= cfg.repeated_holes:
        add("REPEATED SEQUENCE HOLES", "warn",
            f"{stats['sack_holes']} distinct SACK holes observed "
            f"(threshold: {cfg.repeated_holes}).")
    if stats.get("ooo_packets", 0) >= cfg.reordering_events:
        add("POSSIBLE PACKET REORDERING", "warn",
            f"{stats['ooo_packets']} segments filled sequence gaps with data "
            "never previously seen in the capture — consistent with "
            "reordering rather than loss.")
    if stats.get("spurious_retrans", 0) >= cfg.spurious_retrans:
        add("POSSIBLE SPURIOUS RETRANSMISSION", "warn",
            f"{stats['spurious_retrans']} retransmissions of data that was "
            "already ACKed/SACKed or was DSACK-reported as received.")
    if stats.get("zero_window_events", 0) >= cfg.zero_window_events:
        add("ZERO-WINDOW BOTTLENECK", "bad",
            f"{stats['zero_window_events']} zero-window episodes observed — "
            "the receiver stalled the sender (application-side bottleneck).")
    if stats.get("unrecovered_losses", 0):
        add("UNRECOVERED LOSS", "bad",
            f"{stats['unrecovered_losses']} loss events were never covered by "
            "a cumulative ACK within the capture.")
    if not out:
        add("NO FINDINGS", "ok", "No rule produced a finding for this session.")
    return out
