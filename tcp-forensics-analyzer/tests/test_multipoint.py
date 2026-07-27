"""Multi-point / SPAN capture scenarios: the same packet observed at
several points in the network (different leaf, routed hop, VLAN
translation, mirrored SPAN feed) must never be classified as a
retransmission, duplicate, or extra duplicate ACK — and the observation
skew between capture points must be measured."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.pcap_builder import ACK, Flow
from tests.test_engine import T0, RTT, one_session, run


def handshake_with_ids(f, t0):
    """Handshake where every packet carries a realistic non-zero IP ID."""
    from tests.pcap_builder import SYN, opt_mss, opt_sack_perm, opt_wscale
    opts = opt_mss(1460) + opt_sack_perm() + opt_wscale(7)
    f.c2s(t0, f.cisn, 0, SYN, options=opts, ip_id=101)
    f.s2c(t0 + RTT, f.sisn, f.cisn + 1, SYN | ACK, options=opts, ip_id=901)
    f.c2s(t0 + 2 * RTT, f.cisn + 1, f.sisn + 1, ACK, ip_id=102)
    return t0 + 2 * RTT


class TestLeafToLeafObservation(unittest.TestCase):
    """A data packet captured on the ingress leaf and again on the egress
    leaf: same TCP content and IP ID, rewritten MACs, decremented TTL,
    translated VLAN, ~12 µs later.  One packet, two observations."""

    def make(self):
        f = Flow()
        d = handshake_with_ids(f, T0) + 100_000
        # ingress-leaf observation
        f.c2s(d, 1001, 50001, ACK, b"x" * 500, ip_id=103, ttl=64,
              src_mac="aa:aa:aa:aa:aa:01", dst_mac="bb:bb:bb:bb:bb:01",
              vlan=100)
        # egress-leaf observation of the SAME packet: routed hop
        f.c2s(d + 12_000, 1001, 50001, ACK, b"x" * 500, ip_id=103, ttl=63,
              src_mac="cc:cc:cc:cc:cc:02", dst_mac="dd:dd:dd:dd:dd:02",
              vlan=200)
        f.s2c(d + 80_000, 50001, 1501, ACK, ip_id=902)
        return f.frames

    def test_not_a_retransmission(self):
        s = one_session(run(self.make()))
        self.assertEqual(s["stats"]["retrans_segments"], 0)
        self.assertEqual(s["stats"]["dup_packets"], 0)
        self.assertEqual(s["stats"]["loss_events"], 0)
        self.assertEqual(s["retrans_events"], [])
        self.assertEqual(s["stats"]["network_dups"], 1)

    def test_observation_event_details(self):
        s = one_session(run(self.make()))
        ev = s["observation_events"][0]
        self.assertEqual(ev["delta_ns"], 12_000)      # leaf-to-leaf skew
        self.assertEqual(ev["confidence"], "confirmed")
        self.assertIn("TTL 64→63", ev["differs"])
        self.assertIn("MAC", ev["differs"])
        self.assertIn("VLAN 100→200", ev["differs"])
        self.assertEqual(s["stats"]["observation_skew"]["median"], 12_000)

    def test_rtt_stays_valid_despite_double_observation(self):
        """The ACK still yields a clean RTT sample: the range was never
        retransmitted, so Karn's exclusion must NOT fire."""
        s = one_session(run(self.make()))
        data_rtt = [r for r in s["rtt_samples"] if r["kind"] == "data-ack"]
        self.assertEqual(len(data_rtt), 1)
        self.assertEqual(data_rtt[0]["rtt"], 80_000)
        self.assertEqual(s["rtt_ambiguous"], [])

    def test_artifact_warning_present(self):
        s = one_session(run(self.make()))
        self.assertTrue(any("observed more than once" in w
                            for w in s["warnings"]))


class TestSamePointSpanDup(unittest.TestCase):
    def test_mirrored_feed_duplicate(self):
        """SPAN delivers the identical frame twice (same MACs/VLAN/TTL,
        same non-zero IP ID) 30 µs apart — capture artifact, not TCP."""
        f = Flow()
        d = handshake_with_ids(f, T0) + 100_000
        for ts in (d, d + 30_000):
            f.c2s(ts, 1001, 50001, ACK, b"y" * 400, ip_id=103, ttl=64)
        f.s2c(d + 90_000, 50001, 1401, ACK, ip_id=902)
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["network_dups"], 1)
        self.assertEqual(s["stats"]["retrans_segments"], 0)
        ev = s["observation_events"][0]
        self.assertIn("same-point SPAN duplication", ev["differs"])

    def test_pure_ack_span_dup_is_not_a_dup_ack(self):
        """The same ACK observed twice must not seed a duplicate-ACK train."""
        f = Flow()
        d = handshake_with_ids(f, T0) + 100_000
        f.c2s(d, 1001, 50001, ACK, b"z" * 500, ip_id=103)
        f.s2c(d + 50_000, 50001, 1501, ACK, ip_id=902)
        f.s2c(d + 58_000, 50001, 1501, ACK, ip_id=902, ttl=63,
              src_mac="ee:ee:ee:ee:ee:01")     # second observation point
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["dup_acks"], 0)
        self.assertEqual(s["dir_b"]["network_dups"], 1)


class TestGenuineEventsSurvive(unittest.TestCase):
    def test_real_retransmission_has_new_ip_id(self):
        """A genuine retransmission is a NEW IP packet (new IP ID) — it must
        still be classified as a retransmission even 100 µs after the
        original, well inside the observation window."""
        f = Flow()
        d = handshake_with_ids(f, T0) + 100_000
        f.c2s(d, 1001, 50001, ACK, b"r" * 500, ip_id=103)
        f.c2s(d + 100_000, 1001, 50001, ACK, b"r" * 500, ip_id=104)  # new ID
        f.s2c(d + 180_000, 50001, 1501, ACK, ip_id=902)
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["network_dups"], 0)
        self.assertEqual(s["stats"]["retrans_segments"], 1)

    def test_genuine_dup_acks_with_zero_ip_id_still_count(self):
        """Linux pure ACKs often carry IP ID 0.  Identical dup-ACKs with no
        L2/TTL difference must NOT be deduplicated — suppressing them would
        hide loss signalling (the ambiguous case stays untouched)."""
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"a" * 500)
        f.c2s(d + 10_000, 1501, 50001, ACK, b"b" * 500)
        f.s2c(d + 50_000, 50001, 1501, ACK)               # ip_id 0 default
        f.s2c(d + 60_000, 50001, 1501, ACK)
        f.s2c(d + 70_000, 50001, 1501, ACK)
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["dup_acks"], 2)

    def test_beyond_window_is_not_deduped(self):
        """The same content + IP ID far outside the observation window (an
        IP ID counter wrap) falls back to normal sequence-space analysis."""
        f = Flow()
        d = handshake_with_ids(f, T0) + 100_000
        f.c2s(d, 1001, 50001, ACK, b"w" * 500, ip_id=103)
        f.s2c(d + 50_000, 50001, 1501, ACK, ip_id=902)
        f.c2s(d + 400_000_000, 1001, 50001, ACK, b"w" * 500, ip_id=103)
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["network_dups"], 0)
        self.assertEqual(len(s["retrans_events"]), 1)     # judged on TCP evidence


class TestInterleavedTwoPointCaptures(unittest.TestCase):
    """Merged two-point captures with weak (zero) IP ID: genuine TCP events
    repeat at KNOWN observation points and must never be swallowed, while
    the second-point copies are still deduplicated."""

    LEAF1 = dict(ip_id=0, ttl=64, src_mac="aa:aa:aa:00:00:01", vlan=100)
    LEAF2 = dict(ip_id=0, ttl=63, src_mac="cc:cc:cc:00:00:02", vlan=200)

    def test_genuine_dup_ack_train_survives_interleaving(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"a" * 500, **self.LEAF1)
        f.c2s(d + 5_000, 1001, 50001, ACK, b"a" * 500, **self.LEAF2)
        f.c2s(d + 10_000, 1501, 50001, ACK, b"b" * 500, **self.LEAF1)
        f.c2s(d + 15_000, 1501, 50001, ACK, b"b" * 500, **self.LEAF2)
        # server's first ACK + three GENUINE dup ACKs, each seen at both leafs
        base = d + 50_000
        for i in range(4):
            f.s2c(base + i * 30_000, 50001, 1501, ACK,
                  ip_id=0, ttl=64, src_mac="bb:bb:bb:00:00:01", vlan=100)
            f.s2c(base + i * 30_000 + 7_000, 50001, 1501, ACK,
                  ip_id=0, ttl=63, src_mac="dd:dd:dd:00:00:02", vlan=200)
        s = one_session(run(f.frames))
        # the genuine train (3 dups after the first ACK) is intact ...
        self.assertEqual(s["stats"]["dup_acks"], 3)
        # ... and every second-point copy was recognized (2 data + 4 acks)
        self.assertEqual(s["stats"]["network_dups"], 6)

    def test_genuine_retransmission_survives_interleaving(self):
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"r" * 500, **self.LEAF1)
        f.c2s(d + 8_000, 1001, 50001, ACK, b"r" * 500, **self.LEAF2)
        # genuine retransmission 300 µs later, again seen at both leafs
        f.c2s(d + 300_000, 1001, 50001, ACK, b"r" * 500, **self.LEAF1)
        f.c2s(d + 308_000, 1001, 50001, ACK, b"r" * 500, **self.LEAF2)
        f.s2c(d + 400_000, 50001, 1501, ACK)
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["retrans_segments"], 1)
        self.assertEqual(s["stats"]["network_dups"], 2)

    def test_zero_window_update_is_not_deduped(self):
        """An ACK that differs ONLY in the advertised window (a zero-window
        announcement) is a different packet — the window field is part of
        the fingerprint."""
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"z" * 500, ip_id=103)
        f.s2c(d + 50_000, 50001, 1501, ACK, window=65535,
              ip_id=0, ttl=64, src_mac="bb:bb:bb:00:00:01")
        f.s2c(d + 57_000, 50001, 1501, ACK, window=65535,
              ip_id=0, ttl=63, src_mac="dd:dd:dd:00:00:02")   # 2nd point
        # 15 µs later the receiver REALLY announces a zero window
        f.s2c(d + 72_000, 50001, 1501, ACK, window=0,
              ip_id=0, ttl=64, src_mac="bb:bb:bb:00:00:01")
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["zero_window_events"], 1)
        self.assertEqual(s["dir_b"]["network_dups"], 1)


class TestIpv6StyleWeakId(unittest.TestCase):
    def test_zero_id_requires_l2_evidence(self):
        """With IP ID 0 (or IPv6), identical content alone is ambiguous —
        but a TTL decrement plus MAC rewrite IS evidence of the same packet
        at another point."""
        f = Flow()
        b = f.handshake(T0, RTT)
        d = b + 100_000
        f.c2s(d, 1001, 50001, ACK, b"q" * 300, ip_id=0, ttl=64,
              src_mac="aa:aa:aa:aa:aa:01")
        f.c2s(d + 9_000, 1001, 50001, ACK, b"q" * 300, ip_id=0, ttl=63,
              src_mac="cc:cc:cc:cc:cc:02")
        f.s2c(d + 70_000, 50001, 1301, ACK)
        s = one_session(run(f.frames))
        self.assertEqual(s["stats"]["network_dups"], 1)
        self.assertEqual(s["observation_events"][0]["confidence"], "likely")
        self.assertEqual(s["stats"]["retrans_segments"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
