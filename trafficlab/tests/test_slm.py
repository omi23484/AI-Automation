"""Optional local-model explainer, tested against a FAKE OpenAI-compatible server on loopback. NOT tested against a real model."""
import json
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from helpers import *
from trafficlab import slm
from trafficlab.config import make_config
from trafficlab.devcheck import analyze_captures, from_file
from trafficlab.pipeline import analyze
from trafficlab.server import State, make_handler
from test_devcheck import IOS_ERR, BGP

DAY = 86400
K0 = (28 * DAY + 2 * 3600) // 300


class Fake:
    """Scripted model server. mode: 'ok' (reply with self.content), 'http500', 'badjson', 'wrongshape'."""
    def __init__(self):
        self.content, self.mode, self.requests = "", "ok", []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append(json.loads(body))
                if outer.mode == "http500":
                    self.send_response(500); self.end_headers(); self.wfile.write(b"boom"); return
                data = {"ok": json.dumps({"choices": [{"message": {"role": "assistant", "content": outer.content}}]}), "badjson": "not json", "wrongshape": json.dumps({"result": "x"})}[outer.mode]
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(data.encode())
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1/chat/completions"

    def stop(self):
        self.httpd.shutdown()


def spike(dev, seed):
    s = mk_series(daily_values(35, seed=seed, mod=lambda k, t, v: v * 3.0 if K0 <= k < K0 + 9 else v), key=f"{dev}|Te1/0/2|in_bps", device=dev)
    s.interface = "Te1/0/2"
    return s


def good(fid, extra=""):
    return f"""Summary
Traffic on A rose sharply in the window. [{fid}]

Ranked possible causes
1. A shared event on two devices is a candidate cause. [{fid}]
2. {slm.UNKNOWN}

Evidence cited
{fid}

Unknowns
Root cause is not determined. {extra}

Suggested checks
Review the device checks for A.
"""


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = analyze([spike("A", 1), spike("B", 2)], workers=1)
        cls.checks = analyze_captures(from_file(IOS_ERR, "A", "a.txt") + from_file(BGP, "A", "b.txt"))
        cls.fid = [f for f in cls.res["findings"] if f["device"] == "A"][0]["id"]

    def setUp(self):
        self.fake = Fake()
        self.cfg = make_config({"slm": {"enabled": True, "endpoint": self.fake.url, "model": "local-model"}})

    def tearDown(self):
        self.fake.stop()

    def ask(self, content, **kw):
        self.fake.content = content
        return slm.explain(self.res, self.checks, kw.get("fid", self.fid), kw.get("cfg", self.cfg))


class Behaviour(Base):
    def test_valid_answer_is_accepted_and_bannered(self):
        out = self.ask(good(self.fid))
        self.assertEqual(out["banner"], "AI-generated explanation. Verify against evidence.")
        self.assertEqual((out["accepted_causes"], out["stripped_causes"], out["invalid_ids"], out["missing_sections"]), (1, [], [], []))
        self.assertIn(self.fid, out["allowed_ids"])

    def test_request_is_openai_style_and_pack_has_no_raw_samples(self):
        self.ask(good(self.fid))
        body = self.fake.requests[0]
        self.assertEqual(body["model"], "local-model")
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertIn("Use ONLY the pack", body["messages"][0]["content"])
        pack = json.loads(body["messages"][1]["content"].split("\n", 1)[1])

        def walk(x):
            if isinstance(x, list):
                self.assertFalse(len(x) > 30 and all(isinstance(v, (int, float)) for v in x), "a long numeric array (raw samples?) reached the model")
                [walk(v) for v in x]
            elif isinstance(x, dict):
                [walk(v) for v in x.values()]
        walk(pack)
        self.assertEqual(pack["finding"]["id"], self.fid)
        self.assertTrue(pack["device_checks"])
        self.assertNotIn("rate", json.dumps(pack).lower().replace("rate-limit", ""))

    def test_model_omitted_when_not_configured(self):
        cfg = make_config({"slm": {"enabled": True, "endpoint": self.fake.url}})
        self.ask(good(self.fid), cfg=cfg)
        self.assertNotIn("model", self.fake.requests[0])

    def test_cause_without_citation_is_stripped(self):
        out = self.ask(good(self.fid).replace("[" + self.fid + "]\n2.", "[" + self.fid + "]\n2. Cosmic rays caused this.\n3.", 1).replace("candidate cause. [" + self.fid + "]", "candidate cause. [" + self.fid + "]"))
        self.assertEqual([s["line"] for s in out["stripped_causes"]], ["2. Cosmic rays caused this."])
        self.assertNotIn("Cosmic", out["sections"]["Ranked possible causes"])
        self.assertIn(slm.UNKNOWN, out["sections"]["Ranked possible causes"])                  # explicit unknown is allowed without a citation

    def test_invented_id_flagged_and_its_cause_stripped(self):
        out = self.ask(good(self.fid).replace("1. A shared event on two devices is a candidate cause. [" + self.fid + "]", "1. Something happened. [F-0000000000]"))
        self.assertEqual(out["invalid_ids"], ["F-0000000000"])
        self.assertEqual(out["accepted_causes"], 0)
        self.assertEqual(len(out["stripped_causes"]), 1)
        self.assertEqual(out["sections"]["Ranked possible causes"].strip(), "2. " + slm.UNKNOWN)

    def test_all_causes_stripped_falls_back_to_unknown(self):
        out = self.ask(good(self.fid).replace("1. A shared event on two devices is a candidate cause. [" + self.fid + "]\n2. " + slm.UNKNOWN, "1. Guess without evidence."))
        self.assertEqual(out["sections"]["Ranked possible causes"], slm.UNKNOWN)

    def test_rule_and_cr_style_ids_from_the_pack_are_valid_citations(self):
        pack_rules = [i["rule"] for f in self.res["findings"] if f["id"] == self.fid for i in f["interpretation"] if i.get("rule")]
        self.assertTrue(pack_rules)
        out = self.ask(good(self.fid).replace("[" + self.fid + "]\n2.", f"[{pack_rules[0]}]\n2.", 1))
        self.assertEqual(out["stripped_causes"], [])

    def test_numbers_not_in_the_pack_are_flagged(self):
        out = self.ask(good(self.fid, extra="Peak was 98765 Mbps."))
        self.assertIn("98765", out["unverified_numbers"])
        pack_number = str(next(v for v in [f for f in self.res["findings"] if f["id"] == self.fid][0]["numbers"].values() if isinstance(v, (int, float)) and len(str(v)) >= 3))
        out2 = self.ask(good(self.fid, extra=f"The value was {pack_number}."))
        self.assertNotIn(pack_number, out2["unverified_numbers"])

    def test_missing_sections_reported(self):
        out = self.ask(f"Summary\nshort [{self.fid}]\n\nRanked possible causes\n1. x [{self.fid}]\n")
        self.assertEqual(out["missing_sections"], ["Evidence cited", "Unknowns", "Suggested checks"])

    def test_markdown_decorated_headings_are_understood(self):
        txt = good(self.fid).replace("Summary\n", "## Summary\n").replace("Ranked possible causes\n", "**Ranked possible causes**\n").replace("Unknowns\n", "Unknowns:\n")
        self.assertEqual(self.ask(txt)["missing_sections"], [])

    def test_pack_trimmed_to_fit_and_flagged_or_refused(self):
        big = slm.build_pack(self.res, self.checks, self.fid, 10 ** 6)
        self.assertFalse(big[2])
        size = len(json.dumps(big[0], default=str))
        trimmed = slm.build_pack(self.res, self.checks, self.fid, size - 50)
        self.assertTrue(trimmed[2])
        with self.assertRaises(slm.SLMError) as e:
            slm.build_pack(self.res, self.checks, self.fid, 200)
        self.assertIn("above slm.max_pack_chars", str(e.exception))


class Safety(Base):
    def test_disabled_by_default_and_tool_unaffected(self):
        with self.assertRaises(slm.SLMError) as e:
            slm.explain(self.res, self.checks, self.fid, make_config())
        self.assertIn("disabled", str(e.exception))
        self.assertEqual(self.fake.requests, [])

    def test_non_loopback_refused_unless_allowed(self):
        cfg = make_config({"slm": {"enabled": True, "endpoint": "http://example.com/v1/chat/completions"}})
        with self.assertRaises(slm.SLMError) as e:
            slm.explain(self.res, self.checks, self.fid, cfg)
        self.assertIn("not this machine", str(e.exception))
        for bad in ("ftp://127.0.0.1/x", "not a url"):
            with self.assertRaises(slm.SLMError):
                slm.check_endpoint(make_config({"slm": {"enabled": True, "endpoint": bad}}))
        slm.check_endpoint(make_config({"slm": {"enabled": True, "endpoint": "http://example.com/x", "allow_non_loopback": True}}))

    def test_server_failures_become_clear_errors(self):
        self.fake.mode = "http500"
        with self.assertRaises(slm.SLMError) as e:
            slm.explain(self.res, self.checks, self.fid, self.cfg)
        self.assertIn("HTTP 500", str(e.exception))
        for mode in ("badjson", "wrongshape"):
            self.fake.mode = mode
            with self.assertRaises(slm.SLMError) as e:
                slm.explain(self.res, self.checks, self.fid, self.cfg)
            self.assertIn("OpenAI-style", str(e.exception))
        dead = make_config({"slm": {"enabled": True, "endpoint": "http://127.0.0.1:1/v1/chat/completions", "timeout_s": 2}})
        with self.assertRaises(slm.SLMError) as e:
            slm.explain(self.res, self.checks, self.fid, dead)
        self.assertIn("cannot reach the model server", str(e.exception))

    def test_unknown_finding(self):
        with self.assertRaises(slm.SLMError):
            slm.explain(self.res, self.checks, "F-nope", self.cfg)


class Endpoint(Base):
    def test_server_endpoint(self):
        st = State(":memory:")
        st.result, st.checks = self.res, self.checks
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]

        def post(path, body):
            r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(r) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            code, j = post("/api/slm/explain", {"finding_id": self.fid})
            self.assertEqual(code, 400)
            self.assertIn("disabled", j["error"])
            post("/api/profile", {"profile": {"name": "p", "config": {"slm": {"enabled": True, "endpoint": self.fake.url}}}})
            self.fake.content = good(self.fid)
            code, j = post("/api/slm/explain", {"finding_id": self.fid})
            self.assertEqual((code, j["banner"]), (200, slm.BANNER))
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
