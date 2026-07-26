"""Capture-artifact detection (section 29).

Capture-side effects (offload engines, snaplen truncation, one-sided taps,
missing handshakes) must never be silently reported as network pathology —
these checks emit explicit warnings that the report surfaces next to the
affected sessions and in the capture header.
"""

from __future__ import annotations


def session_artifacts(sess) -> list[str]:
    warns: list[str] = []
    a, b = sess.dir_a, sess.dir_b
    if a.oversize_segments or b.oversize_segments:
        n = a.oversize_segments + b.oversize_segments
        warns.append(
            f"{n} segments exceed the negotiated MSS — likely TSO/GSO/GRO/LRO "
            "offload in a host-based capture; segment boundaries and per-"
            "segment timing may not reflect on-wire packets.")
    if sess.truncated_frames:
        warns.append(
            f"{sess.truncated_frames} frames truncated by snap length — TCP "
            "payloads incomplete (analysis uses IP-declared lengths).")
    if sess.partial:
        warns.append(
            "Capture begins mid-session (no handshake observed): negotiation "
            "state is Unknown and relative sequence numbers are anchored at "
            "the first observed segment.")
    for ds, other, name in ((a, b, "A->B"), (b, a, "B->A")):
        una = ds.ack_corr.snd_una
        if una is not None and ds.snd_max is not None and una > ds.snd_max:
            warns.append(
                f"ACKs in direction {'B->A' if name == 'A->B' else 'A->B'} "
                f"cover {una - ds.snd_max} bytes never seen in {name} — "
                "asymmetric capture or capture drops; missing data must not "
                "be interpreted as network loss.")
        if una is not None and ds.snd_max is None and ds.packets == 0:
            warns.append(f"Direction {name} carried no packets — one-sided "
                         "(asymmetric) capture for this session.")
    if sess.dir_a.gap_overflow or sess.dir_b.gap_overflow:
        n = sess.dir_a.gap_overflow + sess.dir_b.gap_overflow
        warns.append(
            f"{n} additional sequence gaps beyond the per-session tracking "
            "bound were not individually tracked — gap-level classification "
            "for this session is partial.")
    # unresolved receiver-side gaps that never got filled: possible capture drop
    for ds, name in ((a, "A->B"), (b, "B->A")):
        unresolved = [g for g in ds.open_gaps if not g.get("resolved")]
        if unresolved:
            byte_total = sum(g["end"] - g["start"] for g in unresolved)
            warns.append(
                f"{len(unresolved)} sequence gap(s) in {name} "
                f"({byte_total} bytes) were never filled within the capture — "
                "possible capture drop or truncated capture; classified as "
                "Unknown, not as network loss.")
    return warns
