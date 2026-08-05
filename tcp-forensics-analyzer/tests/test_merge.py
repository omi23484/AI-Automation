"""Multi-capture merge scenarios: several pcaps combined into one timeline.

The same traffic captured on two leafs lands in TWO files; merging must
interleave frames by timestamp, recognize cross-file re-observations of
the same packet (a file boundary is an observation point), and never
swallow genuine TCP events that legitimately appear in both files."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tcpforensics.analyzer import analyze_capture
from tests.pcap_builder import ACK, SYN, Flow, opt_mss, opt_sack_perm, \
    write_pcap
from tests.test_engine import T0, RTT, one_session


def two_leaf_files(td):
    """Same session observed at leaf1 (file A) and leaf2 (file B, +9 µs,
    TTL-1, MACs rewritten).  Server ACKs appear only in file A (one-sided
    tap at leaf2 for the reverse direction keeps the test focused)."""
    opts = opt_mss(1460) + opt_sack_perm()
    fa, fb = Flow(), Flow()
    # handshake seen at both leafs
    fa.c2s(T0, 1000, 0, SYN, options=opts, ip_id=101, ttl=64,
           src_mac="aa:aa:aa:00:00:01")
    fb.c2s(T0 + 9_000, 1000, 0, SYN, options=opts, ip_id=101, ttl=63,
           src_mac="cc:cc:cc:00:00:02")
    fa.s2c(T0 + RTT, 50000, 1001, SYN | ACK, options=opts, ip_id=901)
    fa.c2s(T0 + 2 * RTT, 1001, 50001, ACK, ip_id=102, ttl=64,
           src_mac="aa:aa:aa:00:00:01")
    fb.c2s(T0 + 2 * RTT + 9_000, 1001, 50001, ACK, ip_id=102, ttl=63,
           src_mac="cc:cc:cc:00:00:02")
    d = T0 + 2 * RTT + 100_000
    seq, ipid = 1001, 103
    for i in range(3):
        fa.c2s(d + i * 30_000, seq, 50001, ACK, b"m" * 500, ip_id=ipid,
               ttl=64, src_mac="aa:aa:aa:00:00:01")
        fb.c2s(d + i * 30_000 + 9_000, seq, 50001, ACK, b"m" * 500,
               ip_id=ipid, ttl=63, src_mac="cc:cc:cc:00:00:02")
        seq += 500
        ipid += 1
    fa.s2c(d + 120_000, 50001, seq, ACK, ip_id=902)
    pa, pb = os.path.join(td, "leaf1.pcap"), os.path.join(td, "leaf2.pcap")
    write_pcap(pa, fa.frames, nano=True)
    write_pcap(pb, fb.frames, nano=True)
    return pa, pb


class TestTwoLeafMerge(unittest.TestCase):
    def test_merged_dedup_and_clean_stats(self):
        with tempfile.TemporaryDirectory() as td:
            pa, pb = two_leaf_files(td)
            model = analyze_capture([pa, pb], quiet=True)
            self.assertEqual(model["capture"]["path"], "leaf1.pcap + leaf2.pcap")
            self.assertEqual(model["capture"]["format"], "pcap")
            self.assertEqual(len(model["capture"]["files"]), 2)
            s = one_session(model)
            # SYN + est-ACK + 3 data segments re-observed at leaf2 -> 5 dups
            self.assertEqual(s["stats"]["network_dups"], 5)
            self.assertEqual(s["stats"]["retrans_segments"], 0)
            self.assertEqual(s["stats"]["dup_packets"], 0)
            self.assertEqual(s["stats"]["loss_events"], 0)
            # leaf-to-leaf skew measured on every re-observation
            self.assertEqual(s["stats"]["observation_skew"]["median"], 9_000)
            ev = s["observation_events"][0]
            self.assertIn("capture file #0→#1", ev["differs"])
            # data still fully ACKed; RTT clean
            self.assertEqual(s["dir_a"]["outstanding_bytes"], 0)
            self.assertEqual(s["rtt_ambiguous"], [])

    def test_merged_frame_numbers_are_time_ordered(self):
        with tempfile.TemporaryDirectory() as td:
            pa, pb = two_leaf_files(td)
            model = analyze_capture([pa, pb], quiet=True)
            rows = one_session(model)["packets"]
            ts_list = [r[1] for r in rows]
            self.assertEqual(ts_list, sorted(ts_list))
            frames = [r[0] for r in rows]
            self.assertEqual(frames, sorted(frames))
            # rows carry their source capture id
            srcs = {r[11] for r in rows}
            self.assertEqual(srcs, {0, 1})

    def test_genuine_dup_acks_across_files_survive(self):
        """Genuine dup-ACKs (ip_id 0) captured at BOTH leafs: first sight of
        each dup at leaf1 counts; the leaf2 copies dedup."""
        opts = opt_mss(1460) + opt_sack_perm()
        fa, fb = Flow(), Flow()
        b = fa.handshake(T0, RTT)
        d = b + 100_000
        fa.c2s(d, 1001, 50001, ACK, b"a" * 500)
        fa.c2s(d + 10_000, 1501, 50001, ACK, b"b" * 500)
        base = d + 50_000
        for i in range(4):          # first ACK + 3 genuine dups, both leafs
            fa.s2c(base + i * 30_000, 50001, 1501, ACK,
                   ip_id=0, ttl=64, src_mac="bb:bb:bb:00:00:01")
            fb.s2c(base + i * 30_000 + 7_000, 50001, 1501, ACK,
                   ip_id=0, ttl=63, src_mac="dd:dd:dd:00:00:02")
        with tempfile.TemporaryDirectory() as td:
            pa, pb = os.path.join(td, "a.pcap"), os.path.join(td, "b.pcap")
            write_pcap(pa, fa.frames, nano=True)
            write_pcap(pb, fb.frames, nano=True)
            model = analyze_capture([pa, pb], quiet=True)
            s = one_session(model)
            self.assertEqual(s["stats"]["dup_acks"], 3)
            self.assertEqual(s["dir_b"]["network_dups"], 4)

    def test_single_file_output_unchanged(self):
        """A one-element list behaves exactly like the plain-path call."""
        with tempfile.TemporaryDirectory() as td:
            pa, _ = two_leaf_files(td)
            m1 = analyze_capture(pa, quiet=True)
            m2 = analyze_capture([pa], quiet=True)
            self.assertEqual(m1, m2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
