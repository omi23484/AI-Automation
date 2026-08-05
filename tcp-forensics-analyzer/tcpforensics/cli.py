"""Command-line interface.

    python -m tcpforensics capture.pcap -o report.html

Thresholds behind the automated verdicts and retransmission classification
are configurable so no conclusion rests on an arbitrary hidden number; the
values in effect are embedded into the report next to the verdicts.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .analyzer import analyze_capture
from .capture_reader import CaptureError
from .report_generator import generate_report
from .tcp_retransmission import RetransConfig
from .verdicts import VerdictConfig


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tcpforensics",
        description="TCP session, sequence, SACK & nanosecond latency "
                    "forensics analyzer (PCAP/PCAPNG -> single-file HTML)")
    p.add_argument("capture", nargs="+",
                   help="input .pcap / .pcapng file(s); several files are "
                        "merged into one timeline by timestamp, with a file "
                        "boundary treated as an observation point")
    p.add_argument("-o", "--output", default="tcp_forensics_report.html",
                   help="output HTML report path (default: %(default)s)")
    p.add_argument("--json", help="also write the raw analysis model as JSON")
    p.add_argument("--capture-id", type=int, default=0,
                   help="capture id stored on sessions/events "
                        "(multi-capture correlation, default 0)")
    p.add_argument("--capture-point", default="",
                   help="capture point label (e.g. 'tor-switch-1 span')")
    p.add_argument("--max-packet-rows", type=int, default=20_000,
                   help="max per-session packet rows embedded in the HTML")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="suppress progress output")
    p.add_argument("--version", action="version",
                   version=f"tcpforensics {__version__}")
    g = p.add_argument_group("classification thresholds")
    g.add_argument("--dupack-threshold", type=int, default=3,
                   help="duplicate ACKs implying fast retransmit (default 3)")
    g.add_argument("--rto-floor-ms", type=float, default=200.0,
                   help="RTO-style retransmission delay floor in ms (default 200)")
    g.add_argument("--dup-window-us", type=float, default=2000.0,
                   help="duplicate-packet window in µs (default 2000)")
    v = p.add_argument_group("verdict thresholds")
    v.add_argument("--low-retrans-pct", type=float, default=0.5)
    v.add_argument("--high-retrans-pct", type=float, default=2.0)
    v.add_argument("--high-rtt-ms", type=float, default=100.0)
    v.add_argument("--rtt-outlier-ratio", type=float, default=10.0)
    v.add_argument("--repeated-holes", type=int, default=3)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    retrans_cfg = RetransConfig(
        dupack_threshold=args.dupack_threshold,
        rto_floor_ns=int(args.rto_floor_ms * 1_000_000),
        duplicate_window_ns=int(args.dup_window_us * 1_000))
    verdict_cfg = VerdictConfig(
        low_retrans_pct=args.low_retrans_pct,
        high_retrans_pct=args.high_retrans_pct,
        high_rtt_ns=int(args.high_rtt_ms * 1_000_000),
        rtt_outlier_ratio=args.rtt_outlier_ratio,
        repeated_holes=args.repeated_holes)
    try:
        model = analyze_capture(
            args.capture[0] if len(args.capture) == 1 else args.capture,
            capture_id=args.capture_id,
            capture_point=args.capture_point, retrans_cfg=retrans_cfg,
            verdict_cfg=verdict_cfg, max_packet_rows=args.max_packet_rows,
            quiet=args.quiet)
    except FileNotFoundError as exc:
        print(f"error: capture not found: {exc.filename or args.capture}",
              file=sys.stderr)
        return 2
    except IsADirectoryError:
        print("error: got a directory, not a capture file", file=sys.stderr)
        return 2
    except CaptureError as exc:
        print(f"error: cannot parse capture: {exc}", file=sys.stderr)
        return 2
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(model, fh, indent=1)
        if not args.quiet:
            print(f"analysis model written to {args.json}", file=sys.stderr)
    print("Generating report ...", file=sys.stderr) if not args.quiet else None
    generate_report(model, args.output)
    if not args.quiet:
        c = model["capture"]
        print(f"report written to {args.output} "
              f"({c['tcp_packets']:,} TCP packets, "
              f"{model['totals']['sessions']:,} sessions)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
