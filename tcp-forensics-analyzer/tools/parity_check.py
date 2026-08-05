"""Cross-engine parity check: Python analyzer vs in-browser engine.

    python tools/parity_check.py capture1.pcap [capture2.pcapng ...]

For each capture, runs the Python pipeline AND the standalone HTML's
JavaScript engine (headless Chromium), then deep-compares the two model
objects.  Differences are reported with their JSON paths.  Exact match is
required for integers/strings/structure; floats compare with tolerance
(the two languages round display fractions differently); verdict/artifact
prose is compared by verdict identity (names + severities) rather than
letter-for-letter formatting.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tcpforensics.analyzer import analyze_capture
from tools.build_standalone import build

FLOAT_TOL = 1e-6
MAX_DIFFS = 25


def normalize(model: dict) -> dict:
    m = json.loads(json.dumps(model))          # deep copy, tuples -> lists
    m["capture"]["path"] = Path(m["capture"]["path"]).name
    m["capture"]["capture_point"] = Path(m["capture"]["capture_point"]).name
    m["tool"]["version"] = m["tool"]["version"].replace("-web", "")
    for s in m.get("sessions", []):
        for v in s.get("verdicts", []):
            v.pop("evidence", None)            # prose: rounding may differ
    return m


def diff(a, b, path="$", out=None):
    if out is None:
        out = []
    if len(out) >= MAX_DIFFS:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: missing in python")
            elif k not in b:
                out.append(f"{path}.{k}: missing in js")
            else:
                diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diff(x, y, f"{path}[{i}]", out)
    elif isinstance(a, bool) or isinstance(b, bool):
        if bool(a) != bool(b):
            out.append(f"{path}: {a!r} != {b!r}")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, int) and isinstance(b, int):
            if a != b:
                out.append(f"{path}: {a} != {b}")
        elif not math.isclose(a, b, rel_tol=FLOAT_TOL, abs_tol=FLOAT_TOL):
            out.append(f"{path}: {a} !~ {b}")
    elif a != b:
        out.append(f"{path}: {a!r} != {b!r}")
    return out


async def js_model(page_html: str, capture: Path) -> dict:
    from playwright.async_api import async_playwright
    with tempfile.TemporaryDirectory() as td:
        html_path = Path(td) / "standalone.html"
        html_path.write_text(page_html, encoding="utf-8")
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path="/opt/pw-browsers/chromium")
            page = await browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(html_path.as_uri())
            await page.set_input_files("#fileInput", str(capture))
            await page.wait_for_function("typeof M !== 'undefined' && M !== null", timeout=600000)
            raw = await page.evaluate("JSON.stringify(M)")
            await browser.close()
            if errors:
                raise RuntimeError("JS errors: " + "; ".join(errors))
            return json.loads(raw)


def main() -> int:
    captures = [Path(x) for x in sys.argv[1:]]
    if not captures:
        print("usage: parity_check.py capture [capture ...]", file=sys.stderr)
        return 2
    html = build()
    failures = 0
    for cap in captures:
        py = normalize(analyze_capture(str(cap), quiet=True))
        js = normalize(asyncio.run(js_model(html, cap)))
        diffs = diff(py, js)
        status = "MATCH" if not diffs else f"{len(diffs)}+ DIFFS"
        print(f"{cap.name:<42} sessions={py['totals']['sessions']:<4} "
              f"tcp={py['capture']['tcp_packets']:<7} {status}")
        for d in diffs:
            print("   ", d)
        if diffs:
            failures += 1
    print("PARITY FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
