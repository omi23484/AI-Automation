"""Batch-validate the analyzer against a directory of real captures.

    python tools/validate_samples.py /path/to/captures [--reports outdir]

Runs the full pipeline on every .pcap/.pcapng/.cap file, prints a summary
row per capture (packets, TCP, sessions, retransmissions, loss, warnings)
and fails loudly on any exception.  Intended for real-world corpora such
as the Wireshark wiki sample captures — synthetic unit tests validate
exact numbers; this validates that arbitrary field captures parse and
produce internally consistent results.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tcpforensics.analyzer import analyze_capture
from tcpforensics.report_generator import generate_report


def check_consistency(model: dict) -> list[str]:
    """Cross-checks that must hold for ANY capture."""
    problems = []
    t = model["totals"]
    if t["tcp_packets"] > model["capture"]["packets"]:
        problems.append("tcp_packets exceeds total packets")
    for s in model["sessions"]:
        st = s["stats"]
        if st["recovered_losses"] > st["loss_events"]:
            problems.append(f"session {s['id']}: recovered > loss events")
        if st["retrans_pct"] < 0 or st["retrans_pct"] > 100:
            problems.append(f"session {s['id']}: retrans% out of range")
        for r in s["rtt_samples"]:
            if r["rtt"] < 0:
                problems.append(f"session {s['id']}: negative RTT sample")
        for e in s["loss_events"]:
            for k in ("detection_ns", "reaction_ns", "post_retrans_ns",
                      "total_ns"):
                if e[k] is not None and e[k] < 0:
                    problems.append(
                        f"session {s['id']} {e['loss_id']}: negative {k}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--reports", help="also write an HTML report per capture")
    args = ap.parse_args()

    files = sorted(p for p in Path(args.directory).iterdir()
                   if p.suffix.lower() in (".pcap", ".pcapng", ".cap"))
    if not files:
        print("no capture files found", file=sys.stderr)
        return 2
    failures = 0
    hdr = (f"{'capture':<42}{'pkts':>7}{'tcp':>7}{'sess':>6}{'retx':>6}"
           f"{'loss':>6}{'ooo':>5}{'dups':>5}{'rtt-n':>7}  warnings")
    print(hdr)
    print("-" * len(hdr))
    for path in files:
        try:
            model = analyze_capture(str(path), quiet=True)
            problems = check_consistency(model)
            t, c = model["totals"], model["capture"]
            warn_count = (len(c["warnings"])
                          + sum(len(s["warnings"]) for s in model["sessions"]))
            rtt_n = model["rtt_summary"].get("count", 0)
            flag = " !! " + "; ".join(problems) if problems else ""
            print(f"{path.name:<42}{c['packets']:>7}{c['tcp_packets']:>7}"
                  f"{t['sessions']:>6}{t['retrans_segments']:>6}"
                  f"{t['loss_events']:>6}{t['ooo_packets']:>5}"
                  f"{t['network_dups']:>5}{rtt_n:>7}  {warn_count}{flag}")
            if problems:
                failures += 1
            if args.reports:
                os.makedirs(args.reports, exist_ok=True)
                generate_report(model, os.path.join(
                    args.reports, path.stem + ".html"))
        except Exception:
            failures += 1
            print(f"{path.name:<42} FAILED")
            traceback.print_exc()
    print("-" * len(hdr))
    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
