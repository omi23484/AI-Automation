"""End-to-end validation scenarios (section 35 of the design brief).

Each test builds a synthetic capture with exact nanosecond timestamps,
runs the full analysis pipeline, and asserts the expected sequence-space
state and the expected integer-nanosecond timing results.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tcpforensics.analyzer import analyze_capture
from tests.pcap_builder import (ACK, FIN, PSH, RST, SYN, Flow, opt_mss,
                                opt_sack, opt_sack_perm, opt_wscale,
                                write_pcap, write_pcapng)

T0 = 1_700_000_000 * 1_000_000_000        # epoch base, ns
RTT = 100_000                             # handshake RTT: 100 µs


def run(frames, nano=True, fmt="pcap", **kw):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.pcapng" if fmt == "pcapng" else "t.pcap")
        if fmt == "pcapng":
            write_pcapng(path, frames, tsresol_pow10=9)
        else:
            write_pcap(path, frames, nano=nano)
        return analyze_capture(path, quiet=True, **kw)


def one_session(model):
    assert len(model["sessions"]) == 1, model["sessions"]
    return model["sessions"][0]


class TestNormalTCP(unittest.TestCase):
    def make(self):
        f = Flow()
        b = f.handshake(T0, RTT)                     # done at T0+200µs
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK | PSH, b"x" * 500)          # 1001–1500
        f.s2c(d + 80_000, 50001, 1501, ACK)                    # ACK all
        f.c2s(d + 200_000, 1501, 50001, FIN | ACK)
        f.s2c(d + 250_000, 50001, 1502, FIN | ACK)
        f.c2s(d + 300_000, 1502, 50002, ACK)
        return f.frames

    def test_session_reconstruction(self):
        s = one_session(run(self.make()))
        self.assertEqual(s["client"], "10.0.0.1:40000")
        self.assertEqual(s["server"], "10.0.0.2:80")
        self.assertFalse(s["partial"])
        self.assertEqual(s["state"], "closed")
        self.assertTrue(s["handshake"]["complete"])

    def test_establishment_latency_ns(self):
        s = one_session(run(self.make()))
        hs = s["handshake"]
        self.assertEqual(hs["syn_synack_ns"], RTT)
        self.assertEqual(hs["synack_ack_ns"], RTT)
        self.assertEqual(hs["total_ns"], 2 * RTT)

    def test_negotiated_options(self):
        s = one_session(run(self.make()))
        self.assertTrue(s["sack_client"])
        self.assertTrue(s["sack_server"])
        self.assertTrue(s["sack_active"])
        self.assertEqual(s["dir_a"]["mss"], 1460)
        self.assertEqual(s["dir_a"]["window_scale"], 7)

    def test_data_ack_latency_and_rtt(self):
        s = one_session(run(self.make()))
        seg = next(g for g in s["segments"] if g["len"] == 500)
        self.assertEqual(seg["state"], "ACKed")
        self.assertEqual(seg["ack_lat"], 80_000)
        self.assertEqual(seg["rtt"], 80_000)
        kinds = {r["kind"] for r in s["rtt_samples"]}
        self.assertEqual(kinds, {"syn-synack", "synack-ack", "data-ack"})

    def test_healthy_verdict(self):
        s = one_session(run(self.make()))
        self.assertIn("HEALTHY", [v["verdict"] for v in s["verdicts"]])
        self.assertEqual(s["stats"]["loss_events"], 0)
        self.assertEqual(s["stats"]["retrans_segments"], 0)


class TestCumulativeAck(unittest.TestCase):
    def test_one_ack_covers_three_segments(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        for i in range(3):
            f.c2s(d + i * 10_000, 1001 + i * 500, 50001, ACK, b"x" * 500)
        f.s2c(d + 100_000, 50001, 1001 + 1500, ACK)   # cumulative ACK
        s = one_session(run(f.frames))
        segs = [g for g in s["segments"] if g["len"] == 500]
        self.assertEqual([g["state"] for g in segs], ["ACKed"] * 3)
        # DATA->ACK latency measured per byte-range against the ONE ack
        self.assertEqual([g["ack_lat"] for g in segs],
                         [100_000, 90_000, 80_000])
        # RTT sampled only from the segment that triggered the ACK
        data_rtt = [r for r in s["rtt_samples"] if r["kind"] == "data-ack"]
        self.assertEqual(len(data_rtt), 1)
        self.assertEqual(data_rtt[0]["rtt"], 80_000)
        self.assertEqual(s["stats"]["dup_acks"], 0)


class TestFastRetransmitSack(unittest.TestCase):
    """Single loss, dup-ACK train, SACK hole, fast retransmit, recovery."""

    def make(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d + 0,      1001, 50001, ACK, b"a" * 500)    # 1001–1500
        f.c2s(d + 10_000, 1501, 50001, ACK, b"b" * 500)    # 1501–2000 (lost)
        f.c2s(d + 20_000, 2001, 50001, ACK, b"c" * 500)    # 2001–2500
        f.c2s(d + 30_000, 2501, 50001, ACK, b"d" * 500)    # 2501–3000
        f.s2c(d + 50_000, 50001, 1501, ACK)                          # ACK seg1
        f.s2c(d + 60_000, 50001, 1501, ACK, options=opt_sack([(2001, 2501)]))
        f.s2c(d + 70_000, 50001, 1501, ACK, options=opt_sack([(2001, 3001)]))
        f.s2c(d + 80_000, 50001, 1501, ACK, options=opt_sack([(2001, 3001)]))
        f.c2s(d + 95_000, 1501, 50001, ACK, b"b" * 500)    # fast retransmit
        f.s2c(d + 140_000, 50001, 3001, ACK)               # full recovery
        return f.frames

    def test_sack_hole_and_scoreboard(self):
        s = one_session(run(self.make()))
        self.assertEqual(s["stats"]["sack_events"], 3)
        self.assertEqual(s["stats"]["sack_holes"], 1)
        snaps = s["sack_snapshots"]["A->B"]
        self.assertEqual(len(snaps), 3)
        # first SACK event: ACKed to 501(rel), SACKed 1001–1501, hole 501–1001
        self.assertEqual(snaps[0]["ack"], 501)
        self.assertEqual(snaps[0]["sacked"], [[1001, 1501]])
        self.assertEqual(snaps[0]["holes"], [[501, 1001]])

    def test_dup_ack_train(self):
        s = one_session(run(self.make()))
        self.assertEqual(s["stats"]["dup_acks"], 3)
        t = s["dup_ack_trains"][0]
        self.assertEqual(t["count"], 3)
        self.assertEqual(t["gaps_ns"], [10_000, 10_000])
        self.assertEqual(t["missing_seq"], 501)
        self.assertIsNotNone(t["retrans_frame"])
        self.assertEqual(t["time_to_retrans"], 35_000)

    def test_fast_retransmission_classification(self):
        s = one_session(run(self.make()))
        rt = s["retrans_events"]
        self.assertEqual(len(rt), 1)
        self.assertEqual(rt[0]["class"], "fast-retransmission")
        self.assertEqual(rt[0]["dup_acks"], 3)
        self.assertTrue(rt[0]["sack"])
        self.assertEqual(rt[0]["delay"], 85_000)   # vs original at d+10µs

    def test_loss_event_lifecycle_ns(self):
        s = one_session(run(self.make()))
        loss = [e for e in s["loss_events"] if e["classification"] == "loss"]
        self.assertEqual(len(loss), 1)
        e = loss[0]
        self.assertEqual((e["seq"], e["end"], e["bytes"]), (501, 1001, 500))
        self.assertEqual(e["evidence_kind"], "sack-hole")
        self.assertEqual(e["detection_ns"], 50_000)   # TX+10µs -> SACK+60µs
        self.assertEqual(e["reaction_ns"], 35_000)    # evidence -> retx
        self.assertEqual(e["post_retrans_ns"], 45_000)
        self.assertEqual(e["total_ns"], 130_000)
        self.assertTrue(e["recovered"])
        self.assertTrue(e["sack"])
        self.assertEqual(e["mechanism"], "fast-retransmit")
        self.assertEqual(e["dup_acks"], 3)

    def test_recovery_rtt_still_valid_for_clean_range(self):
        s = one_session(run(self.make()))
        # the recovery ACK ends at 3001 -> segment 2501–3000 (never
        # retransmitted) yields a valid sample: 140µs - 30µs = 110µs
        data_rtt = [r["rtt"] for r in s["rtt_samples"] if r["kind"] == "data-ack"]
        self.assertIn(110_000, data_rtt)

    def test_sack_verdict(self):
        s = one_session(run(self.make()))
        self.assertIn("SACK-BASED LOSS RECOVERY OBSERVED",
                      [v["verdict"] for v in s["verdicts"]])


class TestRtoAndKarn(unittest.TestCase):
    def make(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"x" * 500)
        f.c2s(d + 250_000_000, 1001, 50001, ACK, b"x" * 500)   # RTO retx
        f.s2c(d + 250_100_000, 50001, 1501, ACK)
        return f.frames

    def test_rto_classification(self):
        s = one_session(run(self.make()))
        rt = s["retrans_events"][0]
        self.assertEqual(rt["class"], "rto-retransmission")
        self.assertEqual(rt["delay"], 250_000_000)
        loss = [e for e in s["loss_events"] if e["classification"] == "loss"]
        self.assertEqual(loss[0]["mechanism"], "rto")

    def test_karn_ambiguous_rtt_excluded(self):
        s = one_session(run(self.make()))
        data_rtt = [r for r in s["rtt_samples"] if r["kind"] == "data-ack"]
        self.assertEqual(data_rtt, [])                 # excluded
        self.assertEqual(len(s["rtt_ambiguous"]), 1)   # retained as evidence
        seg = next(g for g in s["segments"] if g["len"] == 500 and not g["retx"])
        self.assertTrue(seg["rtt_ambiguous"])
        self.assertIsNone(seg["rtt"])


class TestDuplicateAndDsack(unittest.TestCase):
    def make(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"x" * 500)
        f.s2c(d + 50_000, 50001, 1501, ACK)
        f.c2s(d + 150_000, 1001, 50001, ACK, b"x" * 500)   # duplicate arrival
        f.s2c(d + 200_000, 50001, 1501, ACK,
              options=opt_sack([(1001, 1501)]))            # DSACK (< cum ACK)
        return f.frames

    def test_duplicate_classification(self):
        s = one_session(run(self.make()))
        self.assertEqual(s["stats"]["dup_packets"], 1)
        self.assertEqual(s["stats"]["retrans_segments"], 0)
        self.assertEqual(s["retrans_events"][0]["class"], "duplicate")

    def test_dsack_detected(self):
        s = one_session(run(self.make()))
        self.assertEqual(s["stats"]["dsack_events"], 1)
        rec = next(r for r in s["sack_records"] if r["dsack"])
        self.assertIn("below cumulative ACK", rec["dsack_reason"])
        # loss event bookkeeping records the range as duplicate, not loss
        self.assertEqual(s["stats"]["loss_events"], 0)


class TestSpuriousRetransmission(unittest.TestCase):
    def test_late_retx_of_acked_data(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"x" * 500)
        f.s2c(d + 50_000, 50001, 1501, ACK)
        f.c2s(d + 300_000_000, 1001, 50001, ACK, b"x" * 500)
        s = one_session(run(f.frames))
        self.assertEqual(s["retrans_events"][0]["class"], "possible-spurious")
        self.assertIn("POSSIBLE SPURIOUS RETRANSMISSION",
                      [v["verdict"] for v in s["verdicts"]])


class TestReordering(unittest.TestCase):
    def test_gap_filled_by_new_data_is_not_loss(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"a" * 500)             # 1001–1500
        f.c2s(d + 10_000, 2001, 50001, ACK, b"c" * 500)    # gap 1501–2000
        f.c2s(d + 15_000, 1501, 50001, ACK, b"b" * 500)    # late arrival
        f.s2c(d + 60_000, 50001, 2501, ACK)
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["ooo_packets"], 1)
        self.assertEqual(s["stats"]["retrans_segments"], 0)
        self.assertEqual(s["stats"]["loss_events"], 0)     # NOT loss
        ev = next(e for e in s["loss_events"]
                  if e["classification"] == "reordering")
        self.assertIn("never seen before", ev["classification_evidence"])
        seg = next(g for g in s["segments"] if g["seq"] == 501)
        self.assertEqual(seg["state"], "Out-of-order")
        self.assertIn("POSSIBLE PACKET REORDERING",
                      [v["verdict"] for v in s["verdicts"]])


class TestSequenceWraparound(unittest.TestCase):
    def test_transfer_across_wrap(self):
        isn = 0xFFFFFFFF - 700
        f = Flow(client_isn=isn)
        b = f.handshake(T0, RTT)
        d = b + 100_000
        seqs = [(isn + 1 + i * 500) & 0xFFFFFFFF for i in range(3)]
        for i, sq in enumerate(seqs):
            f.c2s(d + i * 10_000, sq, 50001, ACK, bytes([65 + i]) * 500)
        final_ack = (isn + 1 + 1500) & 0xFFFFFFFF
        f.s2c(d + 50_000, 50001, final_ack, ACK)
        s = one_session(run(f.frames))
        segs = [g for g in s["segments"] if g["len"] == 500]
        self.assertEqual(len(segs), 3)
        self.assertEqual([g["state"] for g in segs], ["ACKed"] * 3)
        # relative sequence space is contiguous across the 2^32 wrap
        self.assertEqual([(g["seq"], g["end"]) for g in segs],
                         [(1, 501), (501, 1001), (1001, 1501)])
        self.assertEqual(s["stats"]["retrans_segments"], 0)
        self.assertEqual(s["stats"]["loss_events"], 0)
        self.assertEqual(s["dir_a"]["unique_bytes"], 1501)  # SYN + 1500 B


class TestZeroWindow(unittest.TestCase):
    def test_zero_window_probe_recovery(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"x" * 500)
        f.s2c(d + 50_000, 50001, 1501, ACK, window=0)          # zero window
        f.c2s(d + 250_000, 1501, 50001, ACK, b"p")             # probe
        f.s2c(d + 500_000, 50001, 1502, ACK, window=512)       # recovery
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["zero_window_events"], 1)
        kinds = [w["kind"] for w in s["window_events"]]
        self.assertIn("zero-window", kinds)
        self.assertIn("zero-window-probe", kinds)
        self.assertIn("window-recovery", kinds)
        rec = next(w for w in s["window_events"]
                   if w["kind"] == "window-recovery")
        self.assertIn("450000 ns", rec["detail"])
        self.assertIn("ZERO-WINDOW BOTTLENECK",
                      [v["verdict"] for v in s["verdicts"]])


class TestRstSession(unittest.TestCase):
    def test_reset(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        f.s2c(b + 100_000, 50001, 1001, RST | ACK)
        s = one_session(run(f.frames))
        self.assertEqual(s["state"], "reset")
        self.assertIn("SESSION RESET", [v["verdict"] for v in s["verdicts"]])


class TestMidSessionCapture(unittest.TestCase):
    def test_partial_session(self):
        f = Flow()
        d = T0
        f.c2s(d, 90000, 70000, ACK, b"x" * 500)
        f.s2c(d + 40_000, 70000, 90500, ACK)
        s = one_session(run(f.frames))
        self.assertTrue(s["partial"])
        self.assertEqual(s["state"], "partial")
        self.assertIsNone(s["sack_client"])     # unknown, not assumed
        self.assertIsNone(s["sack_server"])
        seg = s["segments"][0]
        self.assertEqual((seg["seq"], seg["end"]), (0, 500))  # anchored
        self.assertEqual(seg["rtt"], 40_000)
        self.assertIn("INCOMPLETE CAPTURE",
                      [v["verdict"] for v in s["verdicts"]])
        self.assertTrue(any("mid-session" in w for w in s["warnings"]))


class TestTupleReuse(unittest.TestCase):
    def test_two_connections_same_tuple(self):
        f = Flow(client_isn=1000, server_isn=50000)
        b = f.handshake(T0, RTT)
        f.c2s(b + 10_000, 1001, 50001, FIN | ACK)
        f.s2c(b + 20_000, 50001, 1002, FIN | ACK)
        f.c2s(b + 30_000, 1002, 50002, ACK)
        # same 5-tuple, new ISN, one second later
        f2 = Flow(client_isn=777000, server_isn=888000)
        b2 = f2.handshake(T0 + 1_000_000_000, RTT)
        f2.c2s(b2 + 10_000, 777001, 888001, ACK, b"y" * 100)
        model = run(f.frames + f2.frames)
        self.assertEqual(len(model["sessions"]), 2)
        self.assertFalse(model["sessions"][1]["partial"])

    def test_syn_retransmission_is_same_session(self):
        f = Flow()
        f.c2s(T0, 1000, 0, SYN, options=opt_mss(1460) + opt_sack_perm())
        f.c2s(T0 + 1_000_000_000, 1000, 0, SYN,
              options=opt_mss(1460) + opt_sack_perm())   # SYN retx, same ISN
        f.s2c(T0 + 1_000_100_000, 50000, 1001, SYN | ACK,
              options=opt_mss(1460) + opt_sack_perm())
        f.c2s(T0 + 1_000_200_000, 1001, 50001, ACK)
        model = run(f.frames)
        self.assertEqual(len(model["sessions"]), 1)


class TestTimestampPrecision(unittest.TestCase):
    def flow(self, delta_ns):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"x" * 500)
        f.s2c(d + delta_ns, 50001, 1501, ACK)
        return f.frames

    def test_nanosecond_pcap_exact(self):
        model = run(self.flow(80_123), nano=True)
        cap = model["capture"]
        self.assertEqual(cap["format"], "pcap")
        self.assertEqual(cap["effective_precision_ns"], 1)
        self.assertTrue(cap["nanosecond_native"])
        seg = next(g for g in one_session(model)["segments"] if g["len"] == 500)
        self.assertEqual(seg["rtt"], 80_123)      # exact odd-ns value survives

    def test_microsecond_pcap_reports_1000ns_precision(self):
        model = run(self.flow(80_000), nano=False)
        cap = model["capture"]
        self.assertEqual(cap["effective_precision_ns"], 1000)
        self.assertFalse(cap["nanosecond_native"])
        self.assertEqual(cap["resolution_label"], "1 µs")
        seg = next(g for g in one_session(model)["segments"] if g["len"] == 500)
        self.assertEqual(seg["rtt"], 80_000)

    def test_pcapng_nanosecond_tsresol(self):
        model = run(self.flow(12_345), fmt="pcapng")
        cap = model["capture"]
        self.assertEqual(cap["format"], "pcapng")
        self.assertEqual(cap["effective_precision_ns"], 1)
        seg = next(g for g in one_session(model)["segments"] if g["len"] == 500)
        self.assertEqual(seg["rtt"], 12_345)


class TestMultipleSackBlocks(unittest.TestCase):
    def test_three_blocks_two_holes(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        # send 1001..4000; only some ranges arrive
        for i, sq in enumerate(range(1001, 4001, 500)):
            f.c2s(d + i * 10_000, sq, 50001, ACK, b"z" * 500)
        f.s2c(d + 100_000, 50001, 1501, ACK,
              options=opt_sack([(2001, 2501), (3001, 3501), (3501, 4001)]))
        s = one_session(run(f.frames))
        rec = s["sack_records"][0]
        self.assertEqual(len(rec["blocks"]), 3)
        snap = s["sack_snapshots"]["A->B"][0]
        # holes: 1501–2000 and 2501–3000 (relative: 501–1001, 1501–2001)
        self.assertEqual(snap["holes"], [[501, 1001], [1501, 2001]])
        self.assertEqual(s["stats"]["sack_holes"], 2)
        self.assertEqual(len([e for e in s["loss_events"]
                              if e["classification"] == "loss"]), 2)


class TestCaptureArtifacts(unittest.TestCase):
    def test_oversize_segment_warns_tso(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        f.c2s(b + 100_000, 1001, 50001, ACK, b"x" * 4000)   # 4000 > MSS 1460
        s = one_session(run(f.frames))
        self.assertTrue(any("TSO/GSO" in w for w in s["warnings"]))

    def test_asymmetric_ack_warns(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        # server ACKs 5000 bytes that never appear in the capture
        f.s2c(b + 100_000, 50001, 6001, ACK)
        s = one_session(run(f.frames))
        self.assertTrue(any("asymmetric capture" in w.lower() or
                            "never seen" in w for w in s["warnings"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
