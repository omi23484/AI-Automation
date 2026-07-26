"""Robustness scenarios: liveness segments, dup-ACK strictness, handshake
Karn exclusions, simultaneous open, window-scale fallback, corrupt/empty
captures, and CLI error handling."""

import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tcpforensics.analyzer import analyze_capture
from tcpforensics.report_generator import generate_report
from tests.pcap_builder import (ACK, SYN, Flow, opt_mss, opt_sack,
                                opt_sack_perm, opt_wscale, write_pcap,
                                write_pcapng)
from tests.test_engine import T0, RTT, one_session, run


class TestKeepAlive(unittest.TestCase):
    """A 1-byte segment at snd_una-1 on an idle connection is TCP keep-alive
    signalling, not a retransmission, duplicate, or loss."""

    def make(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"x" * 500)             # 1001–1500
        f.s2c(d + 50_000, 50001, 1501, ACK)                # all ACKed
        # keep-alive: seq = snd_una - 1, 1 garbage byte, 45 s later
        f.c2s(d + 45_000_000_000, 1500, 50001, ACK, b"\x00")
        f.s2c(d + 45_000_050_000, 50001, 1501, ACK)        # keep-alive ACK
        return f.frames

    def test_not_a_retransmission(self):
        s = one_session(run(self.make()))
        self.assertEqual(s["stats"]["retrans_segments"], 0)
        self.assertEqual(s["stats"]["dup_packets"], 0)
        self.assertEqual(s["stats"]["loss_events"], 0)
        self.assertEqual(s["retrans_events"], [])
        self.assertEqual(s["dir_a"]["keepalives"], 1)
        seg = next(g for g in s["segments"] if g["state"] == "Keep-alive")
        self.assertEqual(seg["len"], 1)
        # keep-alives are never latency samples
        self.assertIsNone(seg["rtt"])
        self.assertIsNone(seg["ack_lat"])

    def test_no_spurious_verdicts(self):
        s = one_session(run(self.make()))
        verdicts = [v["verdict"] for v in s["verdicts"]]
        self.assertNotIn("POSSIBLE SPURIOUS RETRANSMISSION", verdicts)
        self.assertIn("HEALTHY", verdicts)


class TestDupAckWindowRule(unittest.TestCase):
    """Same ACK number with a NEW advertised window is a window update
    (RFC 5681), not a duplicate ACK."""

    def test_window_updates_are_not_dup_acks(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"x" * 500)
        f.s2c(d + 50_000, 50001, 1501, ACK, window=1000)
        f.s2c(d + 60_000, 50001, 1501, ACK, window=2000)    # window update
        f.s2c(d + 70_000, 50001, 1501, ACK, window=4000)    # window update
        f.s2c(d + 80_000, 50001, 1501, ACK, window=8000)    # window update
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["dup_acks"], 0)
        self.assertEqual(s["dup_ack_trains"], [])

    def test_same_window_still_counts(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"x" * 500)
        f.s2c(d + 50_000, 50001, 1501, ACK, window=1000)
        f.s2c(d + 60_000, 50001, 1501, ACK, window=1000)
        f.s2c(d + 70_000, 50001, 1501, ACK, window=1000)
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["dup_acks"], 2)


class TestHandshakeKarn(unittest.TestCase):
    def test_syn_retransmission_excludes_handshake_rtt(self):
        f = Flow()
        f.c2s(T0, 1000, 0, SYN, options=opt_mss(1460) + opt_sack_perm())
        f.c2s(T0 + 1_000_000_000, 1000, 0, SYN,
              options=opt_mss(1460) + opt_sack_perm())        # SYN retx
        f.s2c(T0 + 1_000_100_000, 50000, 1001, SYN | ACK,
              options=opt_mss(1460) + opt_sack_perm())
        f.c2s(T0 + 1_000_200_000, 1001, 50001, ACK)
        s = one_session(run(f.frames))
        kinds = [r["kind"] for r in s["rtt_samples"]]
        self.assertNotIn("syn-synack", kinds)     # ambiguous, excluded
        self.assertIn("synack-ack", kinds)        # SYN/ACK sent once: valid
        self.assertTrue(any("SYN was retransmitted" in a["reason"]
                            for a in s["rtt_ambiguous"]))


class TestLateDsackKeepsRecoveredLoss(unittest.TestCase):
    def test_dsack_after_recovery_does_not_rewrite_loss(self):
        """RTO loss recovers; a spurious copy afterwards draws a DSACK.  The
        DSACK marks the spurious copy, but the earlier, already-recovered
        loss event keeps its 'loss' classification."""
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"r" * 600)               # lost
        f.c2s(d + 320_000_000, 1001, 50001, ACK, b"r" * 600)  # RTO retx
        f.s2c(d + 320_090_000, 50001, 1601, ACK)              # recovery
        f.c2s(d + 321_000_000, 1001, 50001, ACK, b"r" * 600)  # spurious copy
        f.s2c(d + 321_080_000, 50001, 1601, ACK,
              options=opt_sack([(1001, 1601)]))               # DSACK
        s = one_session(run(f.frames))
        loss = [e for e in s["loss_events"] if e["classification"] == "loss"]
        self.assertEqual(len(loss), 1)
        self.assertTrue(loss[0]["recovered"])
        spurious = [r for r in s["retrans_events"]
                    if r["class"] == "possible-spurious"]
        self.assertEqual(len(spurious), 1)


class TestSimultaneousOpen(unittest.TestCase):
    def test_first_syn_stays_client(self):
        f = Flow()
        f.c2s(T0, 1000, 0, SYN, options=opt_mss(1460))
        f.s2c(T0 + 20_000, 50000, 0, SYN, options=opt_mss(1460))  # crossing SYN
        s = one_session(run(f.frames))
        self.assertEqual(s["client"], "10.0.0.1:40000")


class TestWindowScaleFallback(unittest.TestCase):
    def test_scaling_active_without_third_ack(self):
        """Handshake ACK not captured: scaling still activates from the two
        SYNs once a non-SYN packet arrives."""
        f = Flow()
        f.c2s(T0, 1000, 0, SYN,
              options=opt_mss(1460) + opt_sack_perm() + opt_wscale(7))
        f.s2c(T0 + RTT, 50000, 1001, SYN | ACK,
              options=opt_mss(1460) + opt_sack_perm() + opt_wscale(7))
        # third ACK missing; client sends data with raw window 100
        f.c2s(T0 + 300_000, 1001, 50001, ACK, b"x" * 100, window=100)
        s = one_session(run(f.frames))
        # raw window 100 scaled by 2^7 -> 12800 (unscaled it would be 100)
        self.assertEqual(s["dir_a"]["window_min"], 100 << 7)


class TestDegenerateCaptures(unittest.TestCase):
    def test_no_tcp_packets(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "e.pcap")
            # one UDP frame only
            udp = (b"\x02" * 6 + b"\x04" * 6 + b"\x08\x00"
                   + struct.pack(">BBHHHBBH4s4s", 0x45, 0, 28, 0, 0, 64, 17, 0,
                                 bytes([10, 0, 0, 1]), bytes([10, 0, 0, 2]))
                   + struct.pack(">HHHH", 53, 53, 8, 0))
            write_pcap(path, [(T0, udp)], nano=True)
            model = analyze_capture(path, quiet=True)
            self.assertEqual(model["totals"]["sessions"], 0)
            self.assertEqual(model["capture"]["packets"], 1)
            self.assertEqual(model["capture"]["tcp_packets"], 0)
            out = os.path.join(td, "r.html")
            generate_report(model, out)          # renders without sessions
            self.assertTrue(os.path.getsize(out) > 1000)

    def test_corrupt_pcapng_tail_keeps_prefix(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        f.c2s(b + 100_000, 1001, 50001, ACK, b"x" * 100)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "c.pcapng")
            write_pcapng(path, f.frames, tsresol_pow10=9)
            with open(path, "ab") as fh:         # garbage block header
                fh.write(struct.pack("<II", 0x00000006, 7) + b"\xff" * 3)
            model = analyze_capture(path, quiet=True)
            self.assertEqual(model["capture"]["tcp_packets"], 4)
            self.assertTrue(any("corrupt" in w or "mid-block" in w
                                for w in model["capture"]["warnings"]))

    def test_truncated_pcap_final_record_warns(self):
        f = Flow()
        f.handshake(T0, RTT)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "t.pcap")
            write_pcap(path, f.frames, nano=True)
            size = os.path.getsize(path)
            with open(path, "r+b") as fh:
                fh.truncate(size - 10)           # cut into the last record
            model = analyze_capture(path, quiet=True)
            self.assertEqual(model["capture"]["tcp_packets"], 2)
            self.assertTrue(any("mid-record" in w
                                for w in model["capture"]["warnings"]))


class TestRowCap(unittest.TestCase):
    def test_packet_rows_bounded(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        seq = 1001
        for i in range(40):
            f.c2s(d + i * 20_000, seq, 50001, ACK, b"x" * 100)
            seq += 100
        model = run(f.frames, max_packet_rows=10)
        s = one_session(model)
        self.assertEqual(len(s["packets"]), 10)
        self.assertEqual(s["packets_truncated"], 43 - 10)
        # analysis itself is NOT truncated — the full ledger is intact
        self.assertEqual(len([g for g in s["segments"] if g["len"] == 100]), 40)


class TestCliErrors(unittest.TestCase):
    def _run(self, *argv):
        return subprocess.run([sys.executable, "-m", "tcpforensics", *argv],
                              cwd=str(ROOT), capture_output=True, text=True)

    def test_not_a_capture_file(self):
        with tempfile.TemporaryDirectory() as td:
            bad = os.path.join(td, "bad.pcap")
            with open(bad, "wb") as fh:
                fh.write(b"this is not a capture file at all")
            proc = self._run(bad, "-o", os.path.join(td, "r.html"), "-q")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("cannot parse", proc.stderr)

    def test_missing_file(self):
        proc = self._run("/nonexistent/x.pcap", "-q")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
