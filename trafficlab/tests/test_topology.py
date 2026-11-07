import os
import unittest
from helpers import *
from trafficlab.devcheck import analyze_captures, from_file, load_path
from trafficlab.devcheck import topology as T
from trafficlab.pipeline import analyze

DAY = 86400
K0 = (28 * DAY + 2 * 3600) // 300


def cdp_ios(remote, local_if, remote_if):
    return f"""COMMAND: show cdp neighbors detail

-------------------------
Device ID: {remote}
Entry address(es): 
  IP address: 10.0.0.9
Platform: cisco C9500-12Q,  Capabilities: Router Switch IGMP 
Interface: {local_if},  Port ID (outgoing port): {remote_if}
Holdtime : 122 sec
"""


CDP_NX = """COMMAND: show cdp neighbors detail

----------------------------------------
Device ID:sw-b(SAL1234ABCD)
Interface address(es): 1
    IPv4 Address: 10.88.152.39
Platform: cisco WS-C2960X-48FPD-L, Capabilities: Switch IGMP Filtering 
Interface: mgmt0, Port ID (outgoing port): GigabitEthernet1/0/22
Holdtime: 176 sec
"""
LLDP_NX = """COMMAND: show lldp neighbors detail

Capability codes:
  (R) Router, (B) Bridge
Device ID            Local Intf      Hold-time  Capability  Port ID  

Chassis id: ecc0.1846.f24e
Port id: Ethernet1/7
Local Port id: Eth1/3
Port Description: Ethernet1/7
System Name: sw-c.corp.local
Time remaining: 111 seconds

Total entries displayed: 1
"""


class Names(unittest.TestCase):
    def test_canon_if(self):
        for a, b in (("GigabitEthernet1/0/1", "Gi1/0/1"), ("gi1/0/1", "GI1/0/1"), ("Ethernet1/7", "Eth1/7"), ("FortyGigabitEthernet2/0/11", "Fo2/0/11"),
                     ("TenGigabitEthernet1/1/1", "Te1/1/1"), ("Port-channel10", "Po10"), ("Vlan 2500", "Vl2500"), ("Hu1/0/1", "HundredGigE1/0/1")):
            self.assertEqual(T.canon_if(a), T.canon_if(b), (a, b))
        self.assertNotEqual(T.canon_if("Gi1/0/1"), T.canon_if("Gi1/0/2"))
        self.assertNotEqual(T.canon_if("Gi1/0/1"), T.canon_if("Te1/0/1"))

    def test_norm_dev(self):
        self.assertEqual(T.norm_dev("SW1.corp.local"), "sw1")
        self.assertEqual(T.norm_dev("sw-b(SAL1234ABCD)"), "sw-b")
        self.assertEqual(T.norm_dev("10.0.0.1"), "10.0.0.1")


class Build(unittest.TestCase):
    def links(self, *caps):
        return analyze_captures(list(caps))["topology"]["links"]

    def test_parse_formats_and_merge_both_directions(self):
        a = from_file(cdp_ios("B.corp.local", "Fo1/0/12", "FortyGigabitEthernet2/0/12"), "A", "a.txt")
        b = from_file(cdp_ios("a", "Fo2/0/12", "FortyGigabitEthernet1/0/12"), "B", "b.txt")
        links = analyze_captures(a + b)["topology"]["links"]
        self.assertEqual(len(links), 1)                                        # same link seen from both ends
        l = links[0]
        self.assertEqual({(l["a_device"], l["a_if"]), (l["b_device"], l["b_if"])}, {("a", "fo1/0/12"), ("b", "fo2/0/12")})
        self.assertEqual(len(l["evidence"]), 2)

    def test_nxos_cdp_and_lldp(self):
        links = analyze_captures(from_file(CDP_NX, "sw-a", "x") + from_file(LLDP_NX, "sw-a", "y"))["topology"]["links"]
        ends = {frozenset([(l["a_device"], l["a_if"]), (l["b_device"], l["b_if"])]) for l in links}
        self.assertIn(frozenset([("sw-a", "mgmt0"), ("sw-b", "gi1/0/22")]), ends)
        self.assertIn(frozenset([("sw-a", "eth1/3"), ("sw-c", "eth1/7")]), ends)
        self.assertEqual({tuple(l["sources"]) for l in links}, {("CDP",), ("LLDP",)})

    def test_evidence_line_is_the_interface_line(self):
        c = from_file(cdp_ios("B", "Fo1/0/12", "Fo2/0/12"), "A", "a.txt")
        ev = analyze_captures(c)["topology"]["links"][0]["evidence"][0]
        self.assertEqual(cdp_ios("B", "Fo1/0/12", "Fo2/0/12").splitlines()[ev["line"] - 1].strip(), ev["text"])


def mk(dev, ifc, factor, seed):
    s = mk_series(daily_values(35, seed=seed, mod=lambda k, t, v: v * factor if K0 <= k < K0 + 9 else v), key=f"{dev}|{ifc}|in_bps", device=dev)
    s.interface = ifc
    return s


class Annotate(unittest.TestCase):
    def topo(self, *pairs):
        caps = []
        for dev, rem, li, ri in pairs:
            caps += from_file(cdp_ios(rem, li, ri), dev, f"{dev}.txt")
        return analyze_captures(caps)["topology"]

    def test_both_ends_of_one_link(self):
        res = analyze([mk("A", "Gi1/0/1", 3.0, 1), mk("B", "GigabitEthernet2/0/2", 3.0, 2)], workers=1)
        T.annotate(res, self.topo(("A", "b.corp", "Gi1/0/1", "Gi2/0/2")))                         # names in different styles on purpose
        c = res["clusters"][0]
        self.assertEqual(c["topology"], {"same_link": 1, "adjacent": 0, "unknown": 0})
        self.assertIn("both ends of one link", c["label_topology"])
        r7 = [i for f in res["findings"] for i in f["interpretation"] if i["rule"] == "R7_both_ends_of_link"]
        self.assertEqual(len(r7), 2)                                                               # one note per finding (two findings)
        self.assertIn("not proof of cause", r7[0]["claim"])
        f = [x for x in res["findings"] if x["device"] == "A"][0]
        self.assertEqual(f["topology"]["peer_device"], "b")
        self.assertEqual(len(f["topology"]["peer_findings_same_window"]), 1)

    def test_adjacent_devices_different_interfaces(self):
        res = analyze([mk("A", "Gi1/0/1", 3.0, 1), mk("B", "Gi9/9/9", 3.0, 2)], workers=1)
        T.annotate(res, self.topo(("A", "b", "Gi1/0/5", "Gi2/0/2")))
        self.assertEqual(res["clusters"][0]["topology"], {"same_link": 0, "adjacent": 1, "unknown": 0})
        self.assertNotIn("label_topology", res["clusters"][0])
        self.assertFalse([i for f in res["findings"] for i in f["interpretation"] if i["rule"] == "R7_both_ends_of_link"])

    def test_unknown_when_no_link_and_says_incomplete_is_possible(self):
        res = analyze([mk("A", "Gi1/0/1", 3.0, 1), mk("C", "Gi1/0/1", 3.0, 2)], workers=1)
        T.annotate(res, self.topo(("A", "b", "Gi1/0/1", "Gi2/0/2")))
        self.assertEqual(res["clusters"][0]["topology"], {"same_link": 0, "adjacent": 0, "unknown": 1})

    def test_peer_without_finding_is_reported_as_such(self):
        res = analyze([mk("A", "Gi1/0/1", 3.0, 1), mk("B", "Gi2/0/2", 1.0, 2)], workers=1)
        T.annotate(res, self.topo(("A", "b", "Gi1/0/1", "Gi2/0/2")))
        f = [x for x in res["findings"] if x["device"] == "A"][0]
        self.assertEqual(f["topology"]["peer_findings_same_window"], [])
        self.assertTrue(f["topology"]["peer_in_dataset"])
        self.assertEqual(f["interpretation"][0]["claim"], "Unknown - insufficient evidence")        # topology alone does not invent a cause

    def test_idempotent_and_no_topology_is_a_noop(self):
        res = analyze([mk("A", "Gi1/0/1", 3.0, 1), mk("B", "Gi2/0/2", 3.0, 2)], workers=1)
        T.annotate(res, None)
        self.assertNotIn("topology", res["clusters"][0])
        t = self.topo(("A", "b", "Gi1/0/1", "Gi2/0/2"))
        T.annotate(res, t); T.annotate(res, t)
        self.assertEqual(len([i for f in res["findings"] for i in f["interpretation"] if i["rule"] == "R7_both_ends_of_link"]), 2)


LAB = os.environ.get("TRAFFICLAB_LAB_FIXTURES")


@unittest.skipUnless(LAB and os.path.isdir(LAB), "set TRAFFICLAB_LAB_FIXTURES")
class RealLab(unittest.TestCase):
    def test_real_cdp_lldp_parse(self):
        res = analyze_captures(load_path(LAB))
        links = res["topology"]["links"]
        self.assertGreater(len(links), 5)
        for l in links:
            self.assertTrue(l["a_if"] and l["b_if"] and l["a_device"] and l["b_device"])
        self.assertTrue(any("CDP" in l["sources"] for l in links))
        self.assertTrue(any("LLDP" in l["sources"] for l in links))


if __name__ == "__main__":
    unittest.main()
