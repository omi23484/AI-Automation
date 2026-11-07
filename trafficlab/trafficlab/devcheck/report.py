"""Standalone HTML report for Module 4 (no external resources; everything escaped)."""
import html
import json
import time
from .. import tier

E = html.escape


def build(res, title="Device checks"):
    tier.require("report_export", "report/JSON export")
    s = res["summary"]
    h = ["<!doctype html><html lang=en><meta charset=utf-8><title>%s</title><style>%s</style><body>" % (E(title), _CSS),
         f"<h1>{E(title)}</h1><p>Generated {E(time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime()))} &middot; {s['devices']} devices &middot; {s['captures']} captures &middot; "
         f"{s['findings']} findings ({E(json.dumps(s['by_severity']))}, waived {s['waived']})</p>",
         "<div class=b>Rule-based checks on parsed fields. Every finding lists evidence (device, command, line, field, value, raw text). "
         "Counters are cumulative snapshots. Items marked <b>verify on device</b> rest on values seen in captures only. No model was used.</div>",
         "<h2>Per device</h2><table><tr><th>device<th>captures<th>critical<th>warning<th>info<th>waived<th>parsed commands<th>not parsed<th>rejected by device</tr>"]
    for d, v in res["devices"].items():
        c, cv = v["counts"], v["coverage"]
        h.append(f"<tr><td>{E(d)}<td>{v['n_captures']}<td>{c.get('critical', 0)}<td>{c.get('warning', 0)}<td>{c.get('info', 0)}<td>{v['waived']}<td>{len(cv['parsed'])}<td>{len(cv['not_parsed'])}<td>{len(cv['rejected'])}")
    h.append("</table><h2>Cross-device</h2>")
    cr = res["cross_device"]
    h.append("<p>none</p>" if not cr else "<ul>" + "".join(f"<li class={E(f['severity'])}>[{E(f['rule'])}] {E(f['title'])} &mdash; {E(f['device'])}</li>" for f in cr) + "</ul>")
    h.append("<h2>Findings</h2>")
    for f in res["findings"]:
        w = f" <i>(waived: {E(f['waived'])})</i>" if f.get("waived") else ""
        vf = " <b>[verify on device]</b>" if f.get("verify_on_device") else ""
        h.append(f"<h3 class={E(f['severity'])}>{E(f['severity'].upper())} [{E(f['rule'])}] {E(f['device'])}: {E(f['title'])}{w}{vf}</h3><p>{E(f['detail'])}</p>"
                 "<table><tr><th>device<th>command<th>line<th>field<th>value<th>raw text</tr>" +
                 "".join(f"<tr><td>{E(e['device'])}<td>{E(e['command'])}<td>{e['line']}<td>{E(e['field'])}<td>{E(e['value'])}<td class=m>{E(e['text'])}" for e in f["evidence"]) + "</table>")
    h.append("<h2>Rules (no hidden logic)</h2><table><tr><th>id<th>name<th>condition<th>source fields</tr>")
    for r in res["rules"]:
        h.append(f"<tr><td>{E(r['id'])}<td>{E(r['name'])}<td>{E(r['condition'])}<td>{E(r['source'])}")
    h.append("</table><h2>Thresholds used</h2><pre>" + E(json.dumps(res["config"], indent=1)) + "</pre></body></html>")
    return "".join(h)


_CSS = """body{font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;margin:24px;color:#1b1f23;background:#fff}table{border-collapse:collapse;width:100%;margin:.4em 0}td,th{border:1px solid #c8ccd0;padding:3px 6px;text-align:left;font-size:12.5px;vertical-align:top}
th{background:#eef0f2}.m{font-family:ui-monospace,Consolas,monospace}.critical{color:#b00020}.warning{color:#a15c00}.info{color:#555}.b{background:#fff4ce;border:1px solid #d9b100;padding:8px;margin:8px 0}
@media(prefers-color-scheme:dark){body{background:#14171a;color:#e6e8ea}th{background:#23282d}td,th{border-color:#3a4047}.b{background:#3b3200}}"""
