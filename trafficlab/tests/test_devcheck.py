"""Module 4 tests.
Part 1: hand-written SYNTHETIC fixtures in the formats seen in real captures (values invented).
Part 2: REAL lab captures, only if env TRAFFICLAB_LAB_FIXTURES points at the extracted sanitized lab package
(never committed to the repo). Skipped otherwise."""
import os
import unittest
import zipfile
import tempfile
from helpers import *
from trafficlab.devcheck import analyze_captures, from_file, load_path, cmd_key
from trafficlab.devcheck.parsers import parse_age, find_parser
from trafficlab.config import make_config

IOS_ERR = """COMMAND: show interfaces counters errors

Port           Align-Err     FCS-Err    Xmit-Err     Rcv-Err  UnderSize  OutDiscards 
Te1/0/1                0           0           0           0          0            0 
Te1/0/2                0          12           0           3          0            0 
Po1                    0           0           0           0          0            9 

Port         Single-Col  Multi-Col   Late-Col  Excess-Col  Carri-Sen      Runts 
Te1/0/1               0          0          0           0          0          0 
Te1/0/2               0          0          2           0          0          0 
"""
NX_PC = """COMMAND: show port-channel summary

Flags:  D - Down        P - Up in port-channel (members)
        I - Individual  H - Hot-standby (LACP only)
        s - Suspended   r - Module-removed
        S - Switched    R - Routed
        U - Up (port-channel)
--------------------------------------------------------------------------------
Group Port-       Type     Protocol  Member Ports
      Channel
--------------------------------------------------------------------------------
2     Po2(SD)     Eth      LACP      Eth1/3(D)    
7     Po7(SU)     Eth      LACP      Eth1/7(P)    Eth1/8(s)    
9     Po9(SU)     Eth      LACP      Eth1/9(P)    Eth1/10(P)    
"""
VPC_BAD = """COMMAND: show vpc brief

Legend:
		(*) - local vPC is down, forwarding via vPC peer-link

vPC domain id                     : 200 
Peer status                       : peer link not configured      
vPC keep-alive status             : Suspended (Destination IP not reachable)
Configuration consistency status  : failed  
Type-2 consistency status         : failed  
vPC role                          : none established              
Number of vPCs configured         : 1   

vPC status
----------------------------------------------------------------------------
Id    Port          Status Consistency Reason                Active vlans
--    ------------  ------ ----------- ------                ---------------
2     Po2           down   failed      Global compat check   -                           
                                       failed                                            
"""
VPC_OK = VPC_BAD.replace("peer link not configured", "peer adjacency formed ok").replace("Suspended (Destination IP not reachable)", "peer is alive") \
    .replace("failed  \n", "success\n").replace("none established", "primary").replace("down   failed", "up     success")
BGP = """COMMAND: show ip bgp summary

BGP router identifier 10.1.1.1, local AS number 65001
BGP table version is 19, main routing table version 19

Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.1.1.2        4        65002       5       7       19    0    0 00:01:56        1
10.1.1.3        4        65003       0       0        0    0    0 00:39:45 Idle     
10.1.1.4        4        65004       0       0        0    0    0 1d02h    Idle (Admin)
10.1.1.5        4        65005     900     901       19    0    0 3w0d          120
"""
OSPF_TBL = """COMMAND: show ip ospf neighbors

OSPF Process ID 1 VRF default
 Total number of neighbors: 3
 Neighbor ID     Pri State            Up Time  Address         Interface
 10.0.0.2          1 FULL/ -          2w3d     10.0.0.2        Eth1/1
 10.0.0.6          1 EXSTART/ -       00:00:12 10.0.0.6        Eth1/2
 10.0.0.9          1 2WAY/DROTHER     1d00h    10.0.0.9        Eth1/3
"""
OSPF_DET = """COMMAND: show ip ospf neighbor detail

 Neighbor 10.250.0.2, interface address 10.250.1.2, interface-id 72
    In the area 0 via interface FortyGigabitEthernet2/0/11
    BFD enabled, BFD session UP
    Neighbor priority is 0, State is FULL, 6 state changes
"""
HSRP = """COMMAND: show standby brief

                     P indicates configured to preempt.
                     |
Interface   Grp  Pri P State   Active          Standby         Virtual IP
Vl2500      250  110 P Init    unknown         unknown         10.250.50.254
Vl10         10  100   Active  local           10.0.10.3       10.0.10.1
"""
NX_LOG = """COMMAND: show logging last 300

2026 Nov  1 00:49:26 <name> %TACACS-3-TACACS_ERROR_MESSAGE: All servers failed to respond
2026 Nov  1 00:49:29 <name> last message repeated 24 times
2026 Nov  1 00:50:00 <name> %ETHPORT-5-IF_DOWN_NONE: Interface Ethernet1/5 is down (Link failure)
2026 Nov  1 00:50:10 <name> %ETHPORT-5-IF_UP: Interface Ethernet1/5 is up in mode trunk
2026 Nov  1 00:50:20 <name> %ETHPORT-5-IF_DOWN_NONE: Interface Ethernet1/5 is down (Link failure)
2026 Nov  1 00:51:00 <name> %SYSLOG-2-SYSTEM_MSG: something severe
"""
IOS_LOG = """COMMAND: show logging

Log Buffer (102400 bytes):
smatch discovered on Fo2/0/10 (truncated first line)
*Nov  4 00:33:14.751: %CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch discovered on Fo2/0/10 (999), with Switch Fo1/1/2 (1).
022702: Jun 19 03:02:32: %LINK-3-UPDOWN: Interface GigabitEthernet2/0/3, changed state to down
"""
SESSION = """sw1# show spanning-tree summary
Switch is in rapid-pvst mode
Name                   Blocking Listening Learning Forwarding STP Active
---------------------- -------- --------- -------- ---------- ----------
VLAN0001                     1         1        0          1          3
sw1#
sw1# show clock
*14:05:35.412 UTC Tue Nov 3 2026
sw1#
sw1# show foo bar
% Invalid input detected at '^' marker.
sw1#
"""


def caps(dev, *texts, source="x.txt"):
    out = []
    for i, t in enumerate(texts):
        out += from_file(t, dev, f"{source}{i}")
    return out


def rules(res):
    return [(f["rule"], f["severity"]) for f in res["findings"]]


class Parsing(unittest.TestCase):
    def test_age(self):
        self.assertEqual(parse_age("00:01:56"), 116)
        self.assertEqual(parse_age("1d02h"), 86400 + 7200)
        self.assertEqual(parse_age("3w0d"), 21 * 86400)
        self.assertIsNone(parse_age("never"))

    def test_cmd_key_dispatch(self):
        for c in ("show spanning-tree summary", "show port-channel summary", "show ip ospf neigh", "show ip ospf neighbors detail", "show logging last 300", "show bgp ipv4 unicast summary"):
            self.assertIsNotNone(find_parser(cmd_key(c)), c)
        self.assertIsNone(find_parser(cmd_key("show tech-support")))

    def test_session_log_split_and_rejected(self):
        cs = from_file(SESSION, "sw1", "s.log")
        self.assertEqual([c.command for c in cs], ["show spanning-tree summary", "show clock", "show foo bar"])
        self.assertTrue(cs[2].rejected)
        self.assertEqual(cs[0].first_line, 2)

    def test_command_from_filename_flagged(self):
        cs = from_file("Port Name Status\n", "d", "dir/show_interface_status.txt")
        self.assertTrue(cs[0].command_derived)
        self.assertEqual(cs[0].key, "showinterfacestatus")


class Rules(unittest.TestCase):
    def test_dc01_counters(self):
        r = analyze_captures(caps("sw", IOS_ERR))
        t = {f["title"]: f for f in r["findings"] if f["rule"] == "DC01"}
        self.assertEqual(set(t), {"Te1/0/2: non-zero error counters", "Po1: non-zero error counters"})
        self.assertEqual(t["Te1/0/2: non-zero error counters"]["severity"], "warning")
        self.assertEqual(t["Po1: non-zero error counters"]["severity"], "info")          # OutDiscards only
        vals = {e["field"]: e["value"] for e in t["Te1/0/2: non-zero error counters"]["evidence"]}
        self.assertEqual(vals, {"FCS-Err": "12", "Rcv-Err": "3", "Late-Col": "2"})

    def test_evidence_line_numbers_point_at_the_raw_line(self):
        c = caps("sw", IOS_ERR)[0]
        r = analyze_captures([c])
        src = IOS_ERR.splitlines()
        for f in r["findings"]:
            for e in f["evidence"]:
                self.assertEqual(src[e["line"] - 1].strip()[:50], e["text"].strip()[:50])

    def test_dc03_port_channel(self):
        r = analyze_captures(caps("n9k", NX_PC))
        t = [f for f in r["findings"] if f["rule"] == "DC03"]
        self.assertEqual(sorted(f["title"].split(":")[0] for f in t), ["Po2", "Po7"])      # Po9 healthy
        po2 = [f for f in t if f["title"].startswith("Po2")][0]
        self.assertIn("D=Down", po2["detail"])                                              # meaning comes from the capture's legend

    def test_dc10_vpc_unhealthy_vs_healthy(self):
        bad = analyze_captures(caps("n9k", VPC_BAD))
        self.assertIn(("DC10", "critical"), rules(bad))
        titles = " | ".join(f["title"] for f in bad["findings"])
        self.assertIn("peer link not configured", titles)
        self.assertIn("Suspended (Destination IP not reachable)", titles)
        self.assertTrue(all(f.get("verify_on_device") for f in bad["findings"] if f["rule"] == "DC10"))
        ok = analyze_captures(caps("n9k", VPC_OK))
        self.assertEqual([f for f in ok["findings"] if f["rule"] == "DC10"], [])

    def test_bgp(self):
        r = analyze_captures(caps("r1", BGP))
        by = {f["title"].split()[2]: (f["rule"], f["severity"]) for f in r["findings"]}
        self.assertEqual(by["10.1.1.3"], ("DC05", "critical"))
        self.assertEqual(by["10.1.1.4"], ("DC05", "info"))                 # Idle (Admin)
        self.assertEqual(by["10.1.1.2"], ("DC06", "info"))                 # up 116 s < 300 s
        self.assertNotIn("10.1.1.5", by)

    def test_ospf_table_and_detail(self):
        r = analyze_captures(caps("r1", OSPF_TBL, OSPF_DET))
        titles = [f["title"] for f in r["findings"]]
        self.assertEqual(sum("EXSTART" in t for t in titles), 1)
        self.assertFalse(any("2WAY" in t for t in titles))                 # 2WAY/DROTHER is normal
        self.assertTrue(any("6 state changes" in t for t in titles))

    def test_hsrp_and_x01_groups(self):
        a = caps("a", HSRP)
        b = caps("b", HSRP.replace("Init    unknown         unknown", "Active  local           10.0.0.2"))
        r = analyze_captures(a + b)
        self.assertIn(("DC11", "warning"), rules(r))                       # Init on a
        r2 = analyze_captures(a + caps("c", HSRP.replace("Init    unknown         unknown", "Active  local           10.0.0.2")) +
                              caps("d", HSRP.replace("Init    unknown         unknown", "Active  local           10.0.0.2")))
        x = {f["title"]: f["device"] for f in r2["findings"] if f["rule"] == "X01"}
        self.assertEqual(x["HSRP group 250 (10.250.50.254) Active on 2 devices"], "c,d")     # a is Init, not Active
        self.assertEqual(x["HSRP group 10 (10.0.10.1) Active on 3 devices"], "a,c,d")
        cfg = make_config({"devcheck": {"groups": {"c": "lab1", "d": "lab2"}}})
        r3 = analyze_captures(caps("c", HSRP.replace("Init    unknown         unknown", "Active  local           10.0.0.2")) +
                              caps("d", HSRP.replace("Init    unknown         unknown", "Active  local           10.0.0.2")), cfg)
        self.assertEqual([f for f in r3["findings"] if f["rule"] == "X01"], [])             # separated by group

    def test_logging_nx_and_ios(self):
        r = analyze_captures(caps("n9k", NX_LOG) + caps("c9k", IOS_LOG))
        t = {(f["device"], f["title"]) for f in r["findings"]}
        self.assertIn(("n9k", "%SYSLOG-2-SYSTEM_MSG x1"), t)
        self.assertIn(("n9k", "%TACACS-3-TACACS_ERROR_MESSAGE repeated 25x"), t)    # 1 + 24 'last message repeated' >= 20
        self.assertTrue(any(f["rule"] == "DC12" and "Ethernet1/5: 3 up/down" in f["title"] for f in r["findings"]))
        self.assertEqual([f for f in r["findings"] if f["device"] == "c9k"], [])       # 1 link event, 1 CDP line: below thresholds

    def test_log_ts_raw_exact(self):
        from trafficlab.devcheck.parsers import p_log
        rows = p_log(IOS_LOG.splitlines()[1:], 2)["rows"]
        self.assertEqual(rows[0]["ts_raw"], "*Nov  4 00:33:14.751")
        self.assertEqual(rows[0]["marker"], "*")
        self.assertEqual(rows[1]["ts_raw"], "022702: Jun 19 03:02:32")
        nx = p_log(NX_LOG.splitlines()[1:], 2)["rows"]
        self.assertEqual(nx[0]["ts_raw"], "2026 Nov  1 00:49:26")           # host not included
        self.assertEqual(nx[0]["repeat"], 24)

    def test_stp_clock_rejected_coverage(self):
        r = analyze_captures(from_file(SESSION, "sw1", "s.log"))
        self.assertIn(("DC04", "warning"), rules(r))
        self.assertIn(("DC13", "info"), rules(r))
        cov = r["devices"]["sw1"]["coverage"]
        self.assertEqual(cov["rejected"], ["show foo bar"])
        self.assertEqual(len(cov["parsed"]), 2)

    def test_waiver_is_visible_not_hidden(self):
        cfg = make_config({"devcheck": {"waivers": [{"rule": "DC05", "device": "r*", "contains": "10.1.1.3", "reason": "lab: no peer"}]}})
        r = analyze_captures(caps("r1", BGP), cfg)
        w = [f for f in r["findings"] if f.get("waived")]
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["waived"], "lab: no peer")
        self.assertNotIn("critical", r["summary"]["by_severity"])
        self.assertEqual(r["summary"]["waived"], 1)

    def test_same_finding_via_two_commands_merged(self):
        r = analyze_captures(caps("r1", BGP, BGP.replace("show ip bgp summary", "show bgp all summary")))
        idle = [f for f in r["findings"] if f["rule"] == "DC05" and "10.1.1.3" in f["title"]]
        self.assertEqual(len(idle), 1)
        self.assertEqual({e["command"] for e in idle[0]["evidence"]}, {"show ip bgp summary", "show bgp all summary"})

    def test_parser_crash_does_not_hide_other_results(self):
        from trafficlab.devcheck import parsers
        orig = parsers.PARSERS[:]
        try:
            import re
            parsers.PARSERS.insert(0, (re.compile(r"^showclock$"), "boom", "", lambda l, f: 1 / 0))
            r = analyze_captures(from_file(SESSION, "sw1", "s.log"))
            self.assertTrue(r["devices"]["sw1"]["coverage"]["parse_errors"])
            self.assertIn(("DC04", "warning"), rules(r))
        finally:
            parsers.PARSERS[:] = orig


class Loader(unittest.TestCase):
    def test_zip_latest_pass_and_zipslip(self):
        with tempfile.TemporaryDirectory() as td:
            zp = os.path.join(td, "t.zip")
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("baseline/devA/show_clock.txt", "COMMAND: show clock\n\n10:00:00.000 UTC Mon Nov 2 2026\n")
                z.writestr("probe-20261104-100000/devA/base__show_clock.txt", "COMMAND: show clock\n\n11:00:00.000 UTC Wed Nov 4 2026\n")
                z.writestr("../evil/devB/show_clock.txt", "COMMAND: show clock\n\nx\n")
            c = load_path(zp)
            self.assertEqual(len(c), 1)
            self.assertEqual(c[0].pass_name, "probe-20261104-100000")
            self.assertEqual(len(load_path(zp, "all")), 2)


LAB = os.environ.get("TRAFFICLAB_LAB_FIXTURES")


@unittest.skipUnless(LAB and os.path.isdir(LAB), "set TRAFFICLAB_LAB_FIXTURES to the extracted sanitized lab package")
class RealLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.caps = load_path(LAB)
        cls.res = analyze_captures(cls.caps)

    def test_every_evidence_line_matches_the_source_file(self):
        bad = 0
        n = 0
        for e in self.res["evidence"]:
            src = e["source"] if os.path.exists(e["source"]) else os.path.join(LAB, e["source"])
            if not os.path.exists(src):
                continue
            lines = open(src, encoding="utf-8", errors="replace").read().splitlines()
            n += 1
            if lines[e["line"] - 1].strip()[:60] != e["text"].strip()[:60]:
                bad += 1
        self.assertGreater(n, 50)
        self.assertEqual(bad, 0)

    def _find(self, rule, dev, contains):
        return [f for f in self.res["findings"] if f["rule"] == rule and f["device"] == dev and contains in f["title"]]

    def test_known_real_items(self):
        self.assertTrue(self._find("DC01", "c9500-12q-dist", "Te2/0/29"))                      # Rcv-Err=3
        v = self._find("DC10", "n93180yc-fx-nxos93", "peer link not configured")
        self.assertTrue(v and v[0]["severity"] == "critical")
        self.assertTrue(self._find("DC05", "n93180yc-fx-nxos93", "not established"))
        self.assertTrue(self._find("DC08", "c9500-12q-dist", "6 state changes"))
        self.assertTrue(self._find("DC03", "n93180yc-fx-nxos93", "Po2"))

    def test_no_parser_errors_and_rejects_counted(self):
        for dev, d in self.res["devices"].items():
            self.assertEqual(d["coverage"]["parse_errors"], [], dev)
        self.assertGreater(sum(len(d["coverage"]["rejected"]) for d in self.res["devices"].values()), 0)


if __name__ == "__main__":
    unittest.main()
