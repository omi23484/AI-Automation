"""Generate a large synthetic bulk-transfer capture for scale testing.

    python tools/make_bulk_capture.py out.pcap --gib 1.0

Streams a nanosecond pcap directly to disk (constant memory): N parallel
bulk sessions, 1460-byte data segments with realistic incrementing IP IDs,
a cumulative ACK every 8 segments, and a sprinkling of genuine
retransmissions (new IP ID) so loss analysis has work to do.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.pcap_builder import ACK, PSH, SYN, opt_mss, opt_sack_perm, \
    opt_wscale, tcp_frame

T0 = 1_700_000_000 * 1_000_000_000
MSS = 1460


def rec(ts_ns: int, frame: bytes) -> bytes:
    sec, ns = divmod(ts_ns, 1_000_000_000)
    return struct.pack(">IIII", sec, ns, len(frame), len(frame)) + frame


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("--gib", type=float, default=1.0)
    ap.add_argument("--sessions", type=int, default=4)
    args = ap.parse_args()
    target = int(args.gib * (1 << 30))

    out = open(args.output, "wb")
    out.write(struct.pack(">IHHiIII", 0xA1B23C4D, 2, 4, 0, 0, 262144, 1))
    written = 24

    payload = b"D" * MSS
    opts = opt_mss(MSS) + opt_sack_perm() + opt_wscale(7)
    sessions = []
    ts = T0
    for i in range(args.sessions):
        cip, cport = f"10.1.{i}.2", 40000 + i
        s = {"cip": cip, "cport": cport, "sip": "10.2.0.9", "sport": 9000,
             "seq": 1001, "ipid": 1, "sipid": 1, "sent": 0}
        out.write(rec(ts, tcp_frame(cip, s["sip"], cport, 9000, 1000, 0, SYN,
                                    options=opts, ip_id=s["ipid"])))
        out.write(rec(ts + 50_000, tcp_frame(s["sip"], cip, 9000, cport,
                                             50000, 1001, SYN | ACK,
                                             options=opts, ip_id=s["sipid"])))
        out.write(rec(ts + 100_000, tcp_frame(cip, s["sip"], cport, 9000,
                                              1001, 50001, ACK, ip_id=2)))
        s["ipid"], s["sipid"] = 3, 2
        sessions.append(s)
        ts += 120_000
    written = out.tell()

    batch = bytearray()
    frames = 0
    while written + len(batch) < target:
        for s in sessions:
            for _ in range(8):
                ts += 2_000
                s["ipid"] += 1
                batch += rec(ts, tcp_frame(
                    s["cip"], s["sip"], s["cport"], s["sport"],
                    s["seq"], 50001, ACK | PSH, payload, ip_id=s["ipid"]))
                s["seq"] += MSS
                s["sent"] += 1
                frames += 1
            # occasional genuine retransmission: previous segment, NEW IP ID
            if s["sent"] % 40_000 == 0:
                ts += 250_000_000
                s["ipid"] += 1
                batch += rec(ts, tcp_frame(
                    s["cip"], s["sip"], s["cport"], s["sport"],
                    s["seq"] - MSS, 50001, ACK | PSH, payload,
                    ip_id=s["ipid"]))
                frames += 1
            ts += 1_000
            s["sipid"] += 1
            batch += rec(ts, tcp_frame(
                s["sip"], s["cip"], s["sport"], s["cport"],
                50001, s["seq"], ACK, ip_id=s["sipid"]))
            frames += 1
        if len(batch) > 4 << 20:
            out.write(batch)
            written += len(batch)
            batch.clear()
    out.write(batch)
    written += len(batch)
    out.close()
    print(f"wrote {args.output}: {written:,} bytes, ~{frames:,} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
