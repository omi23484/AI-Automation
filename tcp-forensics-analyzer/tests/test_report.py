"""Report generation & CLI round-trip tests."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tcpforensics.analyzer import analyze_capture
from tcpforensics.report_generator import generate_report
from tests.pcap_builder import ACK, Flow, write_pcap

T0 = 1_700_000_000 * 1_000_000_000


def make_capture(path):
    f = Flow()
    b = f.handshake(T0, 100_000)
    d = b + 100_000
    f.c2s(d, 1001, 50001, ACK, b"x" * 500)
    f.s2c(d + 80_000, 50001, 1501, ACK)
    write_pcap(path, f.frames, nano=True)


class TestJsSafeTimestamps(unittest.TestCase):
    """Embedded timestamps must stay exact in a JS double (< 2^53)."""

    def test_rebased_and_exact(self):
        with tempfile.TemporaryDirectory() as td:
            cap = os.path.join(td, "c.pcap")
            make_capture(cap)
            model = analyze_capture(cap, quiet=True)
            self.assertEqual(model["capture"]["first_ts"], 0)
            limit = 2 ** 53
            def walk(o):
                if isinstance(o, dict):
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
                elif isinstance(o, int):
                    self.assertLess(abs(o), limit)
            walk(model)
            s = model["sessions"][0]
            self.assertEqual(s["start_ts"], 0)
            self.assertEqual(s["handshake"]["synack_ts"], 100_000)  # exact ns


class TestReport(unittest.TestCase):
    def test_selfcontained_html(self):
        with tempfile.TemporaryDirectory() as td:
            cap = os.path.join(td, "c.pcap")
            out = os.path.join(td, "r.html")
            make_capture(cap)
            model = analyze_capture(cap, quiet=True)
            generate_report(model, out)
            html = open(out, encoding="utf-8").read()
            # single self-contained file: no external references
            self.assertNotRegex(html, r'src="https?://')
            self.assertNotRegex(html, r'href="https?://')
            self.assertNotIn("@import", html)
            # embedded model parses back and matches
            m = re.search(r'<script id="data" type="application/json">(.*?)'
                          r'</script>', html, re.S)
            self.assertIsNotNone(m)
            data = json.loads(m.group(1).replace("<\\/", "</"))
            self.assertEqual(data["totals"]["sessions"], 1)
            self.assertIn("Nanosecond Latency Forensics", html)

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            cap = os.path.join(td, "c.pcap")
            out = os.path.join(td, "r.html")
            js = os.path.join(td, "m.json")
            make_capture(cap)
            proc = subprocess.run(
                [sys.executable, "-m", "tcpforensics", cap, "-o", out,
                 "--json", js, "-q"],
                cwd=str(ROOT), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(os.path.exists(out))
            model = json.load(open(js))
            self.assertEqual(model["capture"]["tcp_packets"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
