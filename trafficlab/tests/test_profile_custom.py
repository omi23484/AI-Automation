"""Customisation layer: strict config, profiles, zone/group maps, rule control, declarative custom parsers/rules, weekly aliases/basis."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from helpers import *
from trafficlab import ingest, counters, profile, weekly, synth
from trafficlab.config import make_config, glob_lookup
from trafficlab.devcheck import analyze_captures, from_file
from trafficlab.server import State, make_handler
from test_devcheck import BGP, IOS_ERR, NX_LOG, HSRP
from test_weekly import build_files, make_xlsx, week_rows
from trafficlab.__main__ import main


class Strict(unittest.TestCase):
    def test_typos_are_errors(self):
        for bad in ({"anomly": {}}, {"anomaly": {"z_treshold": 3}}, {"devcheck": {"waiver": []}}, {"zones": {"WAN": {"anomaly": {"nope": 1}}}}):
            with self.assertRaises(ValueError, msg=str(bad)):
                make_config(bad)

    def test_free_form_nodes_allowed(self):
        make_config({"baseline": {"scale_floor_abs": {"pct": 2}}, "devcheck": {"groups": {"x": "g"}, "rules": {"DC01": {"enabled": False}}}, "weekly": {"aliases": {"device": ["CI"]}}})

    def test_glob_lookup_case_insensitive_first_match(self):
        m = [{"match": "edge-*", "zone": "WAN"}, {"match": "*", "zone": "X"}]
        self.assertEqual(glob_lookup("EDGE-1", m, "zone"), "WAN")
        self.assertEqual(glob_lookup("core", m, "zone"), "X")
        self.assertIsNone(glob_lookup("core", [], "zone"))


class Zones(unittest.TestCase):
    MAP = {"device": "d", "interface": "i", "timestamp": "t", "zone": "z",
           "counters": [{"name": "in_bps", "column": "o", "bits": 64, "mult": 8, "unit": "bps"}]}

    def test_precedence_column_inventory_zone_map_default(self):
        text = "t,d,i,o,z\n2026-01-05 00:00:00,wan-r1,e1,1,\n2026-01-05 00:00:00,dc-s1,e1,1,\n2026-01-05 00:00:00,odd,e1,1,\n2026-01-05 00:00:00,inv1,e1,1,COLZONE\n"
        inv = ingest.load_inventory("device,zone\ninv1,INVZONE\n")
        ds = ingest.load_csv(text, self.MAP, ["%Y-%m-%d %H:%M:%S"], inventory=inv, zone_map=[{"match": "wan-*", "zone": "WAN"}, {"match": "dc-*", "zone": "DC"}])
        z = {p.dev: p.zone for p in ds.parsed}
        self.assertEqual(z, {"wan-r1": "WAN", "dc-s1": "DC", "odd": "unassigned", "inv1": "COLZONE"})


def caps(dev, *texts):
    out = []
    for i, t in enumerate(texts):
        out += from_file(t, dev, f"{dev}{i}.txt")
    return out


class RuleControl(unittest.TestCase):
    def test_disable_is_visible_and_severity_override_keeps_original(self):
        cfg = make_config({"devcheck": {"rules": {"DC05": {"enabled": False}, "DC06": {"severity": "warning"}}}})
        r = analyze_captures(caps("r1", BGP), cfg)
        self.assertFalse([f for f in r["findings"] if f["rule"] == "DC05"])
        self.assertEqual(r["summary"]["disabled_rules"], {"DC05": 2})              # Idle + Idle (Admin) suppressed, but COUNTED
        dc6 = [f for f in r["findings"] if f["rule"] == "DC06"][0]
        self.assertEqual((dc6["severity"], dc6["severity_default"]), ("warning", "info"))

    def test_unknown_rule_id_is_an_error(self):
        with self.assertRaises(ValueError):
            analyze_captures(caps("r1", BGP), make_config({"devcheck": {"rules": {"DC99": {"enabled": False}}}}))
        with self.assertRaises(ValueError):
            analyze_captures(caps("r1", BGP), make_config({"devcheck": {"rules": {"DC05": {"sever": "info"}}}}))

    def test_group_map_glob(self):
        act = HSRP.replace("Init    unknown         unknown", "Active  local           10.0.0.2")
        both = caps("lab-a-1", act) + caps("lab-b-1", act)
        self.assertTrue([f for f in analyze_captures(both)["findings"] if f["rule"] == "X01"])
        cfg = make_config({"devcheck": {"group_map": [{"match": "lab-a-*", "group": "A"}, {"match": "lab-b-*", "group": "B"}]}})
        self.assertEqual([f for f in analyze_captures(both, cfg)["findings"] if f["rule"] == "X01"], [])


FAN = """COMMAND: show environment fan

Fan             Model              Hw    Direction      Status
Fan1(sys_fan1)  NXA-FAN-65CFM-PE   --    back-to-front  Ok
Fan2(sys_fan2)  NXA-FAN-65CFM-PE   --    back-to-front  Failed
Fan3(sys_fan3)  NXA-FAN-65CFM-PE   --    back-to-front  Ok

Other table:
x y z
"""
PARSER = {"name": "fans", "command_regex": "^show environment fan", "header_regex": r"^Fan\s+Model\s+Hw", "stop_regex": r"^Other table",
          "row_regex": r"^(?P<fan>\S+)\s+(?P<model>\S+)\s+\S+\s+\S+\s+(?P<status>\S+)\s*$"}
RULE = {"id": "CFAN1", "name": "fan not Ok", "severity": "warning", "kind": "custom:fans", "when": {"field": "status", "op": "ne", "value": "Ok"}, "title": "fan {fan} is {status}", "detail": "model {model}"}


class Custom(unittest.TestCase):
    def run_(self, parsers=(PARSER,), rules=(RULE,), text=FAN, **extra):
        cfg = make_config({"devcheck": dict({"custom_parsers": list(parsers), "custom_rules": list(rules)}, **extra)})
        return analyze_captures(caps("sw", text), cfg)

    def test_custom_parser_and_rule_with_evidence_line(self):
        r = self.run_()
        f = [x for x in r["findings"] if x["rule"] == "CFAN1"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["title"], "fan Fan2(sys_fan2) is Failed")
        self.assertEqual(f[0]["detail"], "model NXA-FAN-65CFM-PE")
        ev = f[0]["evidence"][0]
        self.assertEqual(FAN.splitlines()[ev["line"] - 1].strip(), ev["text"])       # line number = original file line
        self.assertTrue(f[0]["custom"])
        self.assertIn("CFAN1", [x["id"] for x in r["rules"] if x.get("custom")])    # documented next to the built-ins
        self.assertEqual(r["devices"]["sw"]["coverage"]["parsed"][0]["parser"], "fans")

    def test_stop_regex_ends_parsing(self):
        rows = self.run_(rules=[dict(RULE, id="CALL", when={"field": "fan", "op": "regex", "value": "."})])
        self.assertEqual(len([x for x in rows["findings"] if x["rule"] == "CALL"]), 3)     # 'x y z' line not parsed

    def test_custom_rule_on_builtin_kind_log(self):
        rule = {"id": "CLOG", "name": "tacacs", "severity": "critical", "kind": "log", "when": [{"field": "facility", "op": "eq", "value": "TACACS"}, {"field": "severity", "op": "le", "value": 3}], "title": "{tag}"}
        r = analyze_captures(caps("n9k", NX_LOG), make_config({"devcheck": {"custom_rules": [rule]}}))
        self.assertTrue([x for x in r["findings"] if x["rule"] == "CLOG"])

    def test_findings_cap_is_reported(self):
        r = self.run_(rules=[dict(RULE, when={"field": "fan", "op": "regex", "value": "."})], max_custom_findings=1)
        self.assertEqual(len([x for x in r["findings"] if x["rule"] == "CFAN1"]), 1)
        self.assertEqual(r["summary"]["custom_truncated"], {"CFAN1@sw": 3})

    def test_rule_can_be_disabled_like_builtins(self):
        r = self.run_(rules=[RULE], rules_=None) if False else analyze_captures(caps("sw", FAN), make_config({"devcheck": {"custom_parsers": [PARSER], "custom_rules": [RULE], "rules": {"CFAN1": {"enabled": False}}}}))
        self.assertEqual(r["summary"]["disabled_rules"], {"CFAN1": 1})

    def test_validation_errors(self):
        bad_rules = [dict(RULE, id="DC01"), dict(RULE, severity="fatal"), dict(RULE, when={"field": "a", "op": "exec", "value": "x"}),
                     dict(RULE, when={"field": "a", "op": "regex", "value": "("}), dict(RULE, when={"field": "a", "op": "in", "value": "notalist"}), dict(RULE, id="bad id")]
        for br in bad_rules:
            with self.assertRaises(ValueError, msg=str(br)):
                self.run_(rules=[br])
        for bp in (dict(PARSER, row_regex="no groups"), dict(PARSER, command_regex="("), dict(PARSER, row_regex="x" * 600), {"command_regex": "x", "row_regex": "(?P<a>.)"}):
            with self.assertRaises(ValueError, msg=str(bp)[:60]):
                self.run_(parsers=[bp])
        with self.assertRaises(ValueError):                                              # duplicate custom ids
            self.run_(rules=[RULE, RULE])

    def test_templates_are_placeholders_only(self):
        r = self.run_(rules=[dict(RULE, title="{fan.__class__} {0} {status}")])
        t = [x["title"] for x in r["findings"] if x["rule"] == "CFAN1"][0]
        self.assertIn("{fan.__class__}", t)                                              # not evaluated; left as text
        self.assertIn("Failed", t)


class WeeklyCustom(unittest.TestCase):
    def test_header_alias_extension(self):
        csv_t = "CI Name,Port,Mean RX (Mbps),Mean TX (Mbps)\nr1,Gi1,100,50\n"
        files = [(f"2026-W{w:02d}/x.csv", csv_t) for w in range(10, 12)]
        s0, rep0 = weekly.build_series(files, make_config())
        self.assertEqual(s0, [])                                                         # built-ins do not know these headers
        cfg = make_config({"weekly": {"aliases": {"device": ["CI Name"], "avg_in_bps": ["Mean RX"], "avg_out_bps": ["Mean TX"]}}})
        s1, _ = weekly.build_series(files, cfg)
        self.assertEqual({x.metric for x in s1}, {"avg_in_bps", "avg_out_bps"})
        with self.assertRaises(ValueError):
            weekly.build_series(files, make_config({"weekly": {"aliases": {"nonsense": ["x"]}}}))

    def test_week_basis_options(self):
        n = "2026_02_04_13_00_00_Util.xlsx"          # a Wednesday
        e = weekly.week_of(n, "UTC", None, "stamp_period_ends")
        s = weekly.week_of(n, "UTC", None, "stamp_period_starts")
        c = weekly.week_of(n, "UTC", None, "stamp_week_contains")
        self.assertEqual(e["end_ms"] - e["start_ms"], weekly.WEEK_MS)
        self.assertEqual(s["start_ms"], e["end_ms"])
        from datetime import datetime, timezone
        self.assertEqual(datetime.fromtimestamp(c["start_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d %a"), "2026-02-02 Mon")
        with self.assertRaises(ValueError):
            weekly.week_of(n, "UTC", None, "bogus")

    def test_zone_map_in_weekly(self):
        files = build_files(8)
        s, _ = weekly.build_series(files, make_config({"zone_map": [{"match": "rtr-a", "zone": "WAN"}]}))
        z = {x.device: x.zone for x in s}
        self.assertEqual(z["rtr-a"], "WAN")
        self.assertEqual(z["rtr-b"], "unassigned")


class Profile(unittest.TestCase):
    def test_example_profile_file_is_valid(self):
        here = os.path.join(os.path.dirname(__file__), "..", "profiles", "example-neutral.json")
        p = profile.load(json.load(open(here)))
        cfg = profile.effective_config(p)
        self.assertEqual(cfg["devcheck"]["rules"]["DC13"], {"enabled": False})
        self.assertEqual(len(cfg["devcheck"]["custom_rules"]), 2)

    def test_load_rejects_bad_profiles(self):
        for bad in ({"nme": "x"}, {"config": {"anomly": {}}}, {"import": {"tzz": "UTC"}}, {"presets": {"p": {"description": "no mapping"}}}, {"import": {"preset": "missing"}}, []):
            with self.assertRaises(ValueError, msg=str(bad)):
                profile.load(bad)

    def test_request_config_overrides_profile_and_is_validated(self):
        p = profile.load({"config": {"anomaly": {"z_threshold": 6.0}, "tz": "Europe/London"}})
        self.assertEqual(profile.effective_config(p)["anomaly"]["z_threshold"], 6.0)
        c = profile.effective_config(p, {"anomaly": {"z_threshold": 3.0}})
        self.assertEqual((c["anomaly"]["z_threshold"], c["tz"]), (3.0, "Europe/London"))
        with self.assertRaises(ValueError):
            profile.effective_config(p, {"anomaly": {"oops": 1}})

    def test_preset_expansion_and_user_presets(self):
        p = profile.load({"presets": {"mine": {"description": "d", "ts_formats": ["%Y"], "mapping": {"device": "a"}}}, "import": {"preset": "mine", "tz": "Asia/Kolkata"}})
        d = profile.import_defaults(p)
        self.assertEqual(d["mapping"], {"device": "a"})
        self.assertEqual(d["tz"], "Asia/Kolkata")
        self.assertIn("nexus_collect_utilization", profile.all_presets(p))               # built-ins stay available

    def test_cli_analyze_with_profile(self):
        text, _ = synth.generate_collector(days=14)
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "d.csv"), "w").write(text)
            json.dump({"name": "t", "config": {"zone_map": [{"match": "syn-dc-*", "zone": "DC"}]}, "import": {"preset": "nexus_collect_utilization"}}, open(os.path.join(td, "p.json"), "w"))
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["analyze", os.path.join(td, "d.csv"), "--profile", os.path.join(td, "p.json"), "--out", os.path.join(td, "o")])
            res = json.load(open(os.path.join(td, "o", "findings.json")))["result"]
            self.assertEqual({s["zone"] for s in res["series"]}, {"DC"})


class ServerProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = State(":memory:")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.st))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def req(self, path, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"} if body is not None else {})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_profile_endpoint(self):
        self.assertEqual(self.req("/api/profile", {"profile": {"config": {"anomly": {}}}})[0], 400)
        code, j = self.req("/api/profile", {"profile": {"name": "p1", "config": {"zone_map": [{"match": "*", "zone": "Z"}]}, "import": {"tz": "Asia/Kolkata"}}})
        self.assertEqual(code, 200)
        d = self.req("/api/defaults")[1]
        self.assertEqual(d["profile"]["name"], "p1")
        self.assertEqual(d["profile_import"]["tz"], "Asia/Kolkata")
        code, j = self.req("/api/synth", {})
        self.assertEqual(code, 200)
        self.assertEqual({s["zone"] for s in j["validation"]["series"]}, {"WAN", "ENT", "DC"})   # synthetic data has its own zone column: column beats zone_map
        self.assertEqual(self.req("/api/profile", {"clear": True})[1]["profile"], None)


if __name__ == "__main__":
    unittest.main()
