"""Standalone HTML report: no external resources, raw timestamps preserved, everything escaped."""
import html
import json
import time
from . import tier

E = html.escape
CSS = """body{font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;margin:24px;color:#1b1f23;background:#fff}
h1,h2{margin:.6em 0 .3em}table{border-collapse:collapse;width:100%;margin:.5em 0}td,th{border:1px solid #c8ccd0;padding:4px 6px;text-align:left;vertical-align:top;font-size:12.5px}
th{background:#eef0f2}.banner{background:#fff4ce;border:1px solid #d9b100;padding:8px;margin:8px 0}.mono{font-family:ui-monospace,Consolas,monospace}
.high{color:#b00020;font-weight:600}.medium{color:#a15c00;font-weight:600}.low{color:#555}.stat{background:#e8f0fe;padding:1px 5px;border-radius:3px}.interp{background:#fde8f3;padding:1px 5px;border-radius:3px}
@media(prefers-color-scheme:dark){body{background:#14171a;color:#e6e8ea}th{background:#23282d}td,th{border-color:#3a4047}.banner{background:#3b3200}.stat{background:#1d3557}.interp{background:#4a1d3a}}"""


def _spark(series, w0, w1, width=420, height=70):
    pad = (w1 - w0) or 3600000
    a, b = w0 - 6 * pad, w1 + 6 * pad
    pts = [(t, v) for t, v in zip(series.ts_ms, series.rate) if a <= t <= b]
    if len(pts) < 2:
        return ""
    if len(pts) > 600:
        step = len(pts) // 600 + 1
        pts = pts[::step]   # DISPLAY decimation only (derived); stated in caption
    vmax = max(v for _, v in pts) or 1
    sx = lambda t: (t - a) / (b - a) * width
    sy = lambda v: height - 4 - v / vmax * (height - 8)
    d = " ".join(f"{sx(t):.1f},{sy(v):.1f}" for t, v in pts)
    return (f'<svg width="{width}" height="{height}" role="img" aria-label="rate around finding">'
            f'<rect x="{sx(max(w0,a)):.1f}" y="0" width="{max(2,sx(min(w1,b))-sx(max(w0,a))):.1f}" height="{height}" fill="#d9300033"/>'
            f'<polyline fill="none" stroke="#1a73e8" stroke-width="1" points="{d}"/></svg>'
            f'<div class="low">display-decimated if &gt;600 pts; red band = finding window</div>')


def build_report(result, validation, series_map=None, dataset_info=""):
    tier.require("report_export", "report/JSON export")
    h = [f"<!doctype html><html lang=en><meta charset=utf-8><title>trafficlab report</title><style>{CSS}</style><body>"]
    h.append("<h1>Traffic analysis report</h1>")
    h.append(f"<p>Generated {E(time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime()))} (UTC) &middot; source: <span class=mono>{E(str(validation['source']))}</span> {E(dataset_info)}</p>")
    h.append("<div class=banner>Statistical findings (<span class=stat>statistical</span>) are computed deterministically. "
             "Interpretations (<span class=interp>interpretation</span>) are rule-based CANDIDATES, not proven causes. No language model was used.</div>")
    h.append("<h2>Validation</h2><table><tr><th>severity<th>message</tr>")
    for i in validation["issues"]:
        h.append(f"<tr><td>{E(i['severity'])}<td>{E(i['message'])}</tr>")
    h.append("</table>")
    tr = validation["timestamps"]
    h.append(f"<p>Timestamp formats: <span class=mono>{E(json.dumps(tr['formats']))}</span>; assumed tz: {E(tr['tz_assumed'])}</p>")
    h.append("<h2>Findings</h2>")
    fs = result["findings"]
    main = [f for f in fs if not f.get("continuation_of")]
    cont = len(fs) - len(main)
    h.append(f"<p>{len(main)} primary findings; {cont} anomalies flagged as continuation of a pattern shift (listed in JSON export).</p>")
    for f in main:
        w = f["window"]
        h.append(f"<h3><span class={E(f['severity'])}>{E(f['severity'].upper())}</span> {E(f['kind'])} &middot; {E(f['device'])} {E(f['interface'])} {E(f['metric'])} &middot; zone {E(f['zone'])} <span class=mono>{E(f['id'])}</span></h3>")
        h.append("<table>")
        h.append(f"<tr><th>window ts_raw<td class=mono>{E(w['start_raw'])} &rarr; {E(w['end_raw'])}")
        sp, ep = w["start_ts_parsed"], w["end_ts_parsed"]
        h.append(f"<tr><th>window ts_parsed<td class=mono>{sp['epoch_ms']} &rarr; {ep['epoch_ms']} ms; format {E(str(sp['format']))}; tz {E(sp['tz_assumed'])} ({E(str(sp['tz_source']))})")
        h.append(f"<tr><th><span class=stat>statistical</span> math<td class=mono>{E(json.dumps(f['math']))}")
        h.append(f"<tr><th><span class=stat>statistical</span> numbers<td class=mono>{E(json.dumps(f['numbers']))}")
        h.append(f"<tr><th>confidence<td>{E(f['confidence']['level'])} &mdash; {E(f['confidence']['justification'])}")
        h.append("<tr><th><span class=interp>interpretation</span><td>" + "<br>".join(E(i["claim"]) + f" <span class=mono>[{E(', '.join(i['evidence']))}]</span>" for i in f["interpretation"]))
        if f["cr_candidates"]:
            h.append("<tr><th>CR candidates<td>" + "<br>".join(f"{E(c['cr_id'])} {E(c['relation'])} ({E(c['label'])})" for c in f["cr_candidates"]))
        if series_map and f["series_key"] in series_map:
            h.append(f"<tr><th>chart<td>{_spark(series_map[f['series_key']], w['start_ms'], w['end_ms'])}")
        h.append("</table>")
    h.append("<h2>Cross-device clusters</h2><table><tr><th>id<th>devices<th>zones<th>mean r<th>label (interpretation)<th>pairs</tr>")
    for c in result["clusters"]:
        pr = "; ".join(f"{p['a']}~{p['b']} r={p['pearson_r']} bins={p['common_bins']} jaccard={p['jaccard']:.2f}" for p in c["pairs"])
        h.append(f"<tr><td class=mono>{E(c['id'])}<td>{E(', '.join(c['devices']))}<td>{E(', '.join(c['zones']))}<td>{c['mean_pearson_r']}<td>{E(c['label'])}<td class=mono>{E(pr)}")
    h.append("</table><h2>Series summary (percentiles of derived rates)</h2><table><tr><th>series<th>zone<th>points<th>excluded<th>p50<th>p95<th>p99<th>util p95 %</tr>")
    for s in result["series"]:
        f = lambda x: "" if x is None else f"{x:,.0f}"
        up = s.get("util_p95_pct")
        h.append(f"<tr><td class=mono>{E(s['key'])}<td>{E(s['zone'])}<td>{s['n_points']}<td>{s['excluded']}<td>{f(s.get('p50'))}<td>{f(s.get('p95'))}<td>{f(s.get('p99'))}<td>{'' if up is None else f'{up:.1f}'}")
    h.append("</table>")
    fcs = [f for f in result.get("forecasts", []) if f["status"] == "upward_trend"]
    if fcs:
        h.append("<h2>Capacity outlook</h2><p>Theil-Sen trend with Mann-Kendall test; straight-line extrapolation, not seasonal; range is heuristic (slope band and 1 robust sigma of scatter).</p>"
                 "<table><tr><th>series<th>basis<th>level now %<th>slope %/day (band)<th>80%: date (fast..slow)<th>90%<th>100%</tr>")
        for f in fcs[:50]:
            cells = "".join(f"<td>{E(str(t['eta_date']))} ({E(str(t['fast_date']))}..{E(str(t['slow_date']))})" for t in f["thresholds"])
            h.append(f"<tr><td class=mono>{E(f['series_key'])}<td>{E(f['basis'])}<td>{f['level_now_pct']}<td>{f['slope_pct_per_day']} ({f['slope_band'][0]}..{f['slope_band'][1]}){cells}")
        h.append("</table>")
    h.append("<h2>Configuration used</h2><pre class=mono>" + E(json.dumps(result["config"], indent=1)) + "</pre></body></html>")
    return "".join(h)
