import json
import os
import unittest
from helpers import *
from trafficlab import signatures, context, profile
from trafficlab.config import make_config
from trafficlab.devcheck import analyze_captures, from_file
from trafficlab.devcheck import topology as T
from trafficlab.pipeline import analyze
from trafficlab.store import CRStore
from test_devcheck import IOS_ERR, BGP
from test_topology import cdp_ios

DAY = 86400
K0 = (28 * DAY + 14 * 3600) // 300


def drop(dev, ifc, factor=0.0, seed=1):
    s = mk_series(daily_values(35, seed=seed, mod=lambda k, t, v: v * factor if K0 <= k < K0 + 8 else v), key=f"{dev}|{ifc}|in_bps", device=dev)
    s.interface = ifc
    return s


PHY = {"id": "SIG-PHY", "name": "drop + errors", "scope": "interface", "cause": "physical layer", "checks": ["look at optics"], "confidence": "low", "verify_on_device": True,
       "all": [{"source": "traffic", "kind": "anomaly", "direction": "low"}, {"source": "devcheck", "rule": "DC01", "min_severity": "warning"}]}


def kb(res):
    return [i for f in res["findings"] for i in f["interpretation"] if str(i.get("rule")).startswith("KB:")]


class Validation(unittest.TestCase):
    def test_errors(self):
        bad = [dict(PHY, id="bad id"), dict(PHY, all=[{"source": "devcheck", "rule": "DC01"}]),                              # no anchor
               dict(PHY, all=[{"source": "traffic"}, {"source": "traffic"}]), dict(PHY, all=[{"source": "traffic"}, {"source": "magic"}]),
               dict(PHY, all=[{"source": "traffic", "kind": "anomaly", "bogus": 1}]), dict(PHY, scope="galaxy"), dict(PHY, confidence="certain"),
               dict(PHY, extra=1), {k: v for k, v in PHY.items() if k != "cause"}, dict(PHY, all=[{"source": "traffic", "min_severity": "huge"}])]
        for b in bad:
            with self.assertRaises(ValueError, msg=str(b)[:80]):
                signatures.compile_entries([b])
        with self.assertRaises(ValueError):
            signatures.compile_entries([PHY, PHY])                                                                           # duplicate id

    def test_example_profile_signatures_are_valid(self):
        here = os.path.join(os.path.dirname(__file__), "..", "profiles", "example-neutral.json")
        cfg = profile.effective_config(profile.load(json.load(open(here))))
        self.assertEqual([e["id"] for e in signatures.compile_entries(cfg["signatures"])], ["SIG-EX-PHY", "SIG-EX-ROUTING", "SIG-EX-CHANGE"])


class Matching(unittest.TestCase):
    def setUp(self):
        self.checks = analyze_captures(from_file(IOS_ERR, "A", "a.txt"))                 # Te1/0/2: FCS-Err=12, Rcv-Err=3, Late-Col=2 -> DC01 warning
        self.cfg = make_config({"signatures": [PHY]})

    def run_(self, series, checks=None, cfg=None):
        res = analyze(series, workers=1)
        context.apply(res, checks if checks is not None else self.checks, cfg or self.cfg)
        return res

    def test_match_on_same_device_and_interface_cites_evidence(self):
        res = self.run_([drop("A", "Te1/0/2")])
        m = kb(res)
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["rule"], "KB:SIG-PHY")
        self.assertIn("candidate", m[0]["claim"])
        self.assertIn("not proven", m[0]["claim"])
        f = res["findings"][0]
        self.assertIn(f["id"], m[0]["evidence"])
        dev_ids = {d["id"] for d in self.checks["findings"] if d["rule"] == "DC01" and "Te1/0/2" in d["title"]}
        self.assertTrue(dev_ids & set(m[0]["evidence"]))                                    # cites the device-check finding it used
        self.assertEqual(m[0]["checks"], ["look at optics"])
        self.assertTrue(m[0]["verify_on_device"])
        self.assertNotIn(None, [i["rule"] for i in f["interpretation"]])                    # 'Unknown' placeholder replaced

    def test_interface_names_match_across_styles(self):
        self.assertEqual(len(kb(self.run_([drop("A", "TenGigabitEthernet1/0/2")]))), 1)

    def test_other_interface_without_errors_does_not_match(self):
        self.assertEqual(kb(self.run_([drop("A", "Te1/0/1")])), [])                         # Te1/0/1 has no error counters

    def test_other_device_does_not_match(self):
        self.assertEqual(kb(self.run_([drop("B", "Te1/0/2")])), [])

    def test_direction_condition(self):
        self.assertEqual(kb(self.run_([drop("A", "Te1/0/2", factor=3.0)])), [])             # spike (high) is not a 'low' anomaly

    def test_device_scope_ignores_interface(self):
        cfg = make_config({"signatures": [dict(PHY, scope="device")]})
        self.assertEqual(len(kb(self.run_([drop("A", "Gi9/9/9")], cfg=cfg))), 1)

    def test_min_severity_on_devcheck(self):
        cfg = make_config({"signatures": [dict(PHY, all=[{"source": "traffic", "kind": "anomaly"}, {"source": "devcheck", "rule": "DC01", "min_severity": "critical"}])]})
        self.assertEqual(kb(self.run_([drop("A", "Te1/0/2")], cfg=cfg)), [])

    def test_waived_devcheck_findings_are_ignored(self):
        waived = analyze_captures(from_file(IOS_ERR, "A", "a.txt"), make_config({"devcheck": {"waivers": [{"rule": "DC01", "device": "A", "contains": "Te1/0/2", "reason": "known"}]}}))
        self.assertEqual(kb(self.run_([drop("A", "Te1/0/2")], checks=waived)), [])

    def test_no_checks_no_match_and_idempotent(self):
        self.assertEqual(kb(self.run_([drop("A", "Te1/0/2")], checks={})), [])
        res = self.run_([drop("A", "Te1/0/2")])
        context.apply(res, self.checks, self.cfg); context.apply(res, self.checks, self.cfg)
        self.assertEqual(len(kb(res)), 1)
        context.apply(res, self.checks, make_config())                                      # library removed => KB entries removed again
        self.assertEqual(kb(res), [])

    def test_cr_and_cluster_conditions(self):
        a = drop("A", "Gi1/0/1", 3.0, 1)
        b = drop("B", "Gi1/0/1", 3.0, 2)
        st = CRStore()
        st.upsert({"cr_id": "CR-9", "status": "Implemented", "planned_start": "2026-02-02 00:00:00", "planned_end": "2026-02-02 01:00:00", "scope": [{"device": "A"}]})
        res = analyze([a, b], store=st, workers=1)
        entry = {"id": "SIG-CR", "name": "cr+cluster", "cause": "change", "all": [{"source": "traffic", "kind": "anomaly", "direction": "high"}, {"source": "cr", "relation": "follows"},
                                                                                      {"source": "cluster", "label_startswith": "shared"}]}
        context.apply(res, {}, make_config({"signatures": [entry]}))
        m = [(f["device"], i) for f in res["findings"] for i in f["interpretation"] if str(i.get("rule")).startswith("KB:")]
        self.assertEqual([d for d, _ in m], ["A"])                                           # only A has the CR candidate; B has the cluster but no CR
        self.assertTrue(any(e.startswith("CR-9") for e in m[0][1]["evidence"]))
        self.assertTrue(any(e.startswith("C-") for e in m[0][1]["evidence"]))

    def test_topology_condition_same_link(self):
        a, b = drop("A", "Gi1/0/1", 3.0, 1), drop("B", "Gi2/0/2", 3.0, 2)
        checks = analyze_captures(from_file(cdp_ios("b", "Gi1/0/1", "Gi2/0/2"), "A", "a.txt"))
        entry = {"id": "SIG-LINK", "name": "both ends", "cause": "link event", "all": [{"source": "traffic", "kind": "anomaly"}, {"source": "topology", "relation": "same_link"}]}
        res = analyze([a, b], workers=1)
        context.apply(res, checks, make_config({"signatures": [entry]}))
        self.assertEqual(len(kb(res)), 2)


if __name__ == "__main__":
    unittest.main()
