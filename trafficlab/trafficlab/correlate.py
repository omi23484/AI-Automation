"""Module 2c: cross-device grouping of anomaly windows + correlation numbers.
Statistical part: overlap + Pearson r of baseline residuals on a common time grid.
The classification label is INTERPRETATION (layer='interpretation')."""
import hashlib
from collections import defaultdict
from itertools import combinations

from .stats import pearson, mean


def _binned(rs, bw):
    b = defaultdict(list)
    for t, v in rs:
        b[t // bw].append(v)
    return {k: mean(v) for k, v in b.items()}


def correlate(findings, resid, intervals, cfg):
    cc = cfg["correlation"]
    an = [f for f in findings if f["kind"] == "anomaly" and not f.get("continuation_of")]
    an.sort(key=lambda f: f["window"]["start_ms"])
    slack = cc["slack_s"] * 1000
    parent = list(range(len(an)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # sweep: sorted by start; extend cluster end
    cur_end = None
    cur_root = None
    for i, f in enumerate(an):
        a, b = f["window"]["start_ms"], f["window"]["end_ms"]
        if cur_root is not None and a - slack <= cur_end:
            parent[find(i)] = find(cur_root)
            cur_end = max(cur_end, b)
        else:
            cur_root, cur_end = i, b
    groups = defaultdict(list)
    for i in range(len(an)):
        groups[find(i)].append(an[i])
    out = []
    for g in groups.values():
        devs = sorted({f["device"] for f in g})
        if len({(f["device"], f["interface"]) for f in g}) < 2:
            continue  # in/out of the same interface is one event, not a cluster
        zones = sorted({f["zone"] for f in g})
        w0 = min(f["window"]["start_ms"] for f in g)
        w1 = max(f["window"]["end_ms"] for f in g)
        bw = max(intervals.get(f["series_key"]) or 60000 for f in g)
        binned = {f["id"]: _binned(resid.get(f["id"], []), bw) for f in g}
        pairs = []
        for a, b in combinations(g, 2):
            if a["device"] == b["device"]:
                continue
            ov = min(a["window"]["end_ms"], b["window"]["end_ms"]) - max(a["window"]["start_ms"], b["window"]["start_ms"])
            un = max(a["window"]["end_ms"], b["window"]["end_ms"]) - min(a["window"]["start_ms"], b["window"]["start_ms"])
            ba, bb = binned[a["id"]], binned[b["id"]]
            common = sorted(set(ba) & set(bb))
            r = None
            if len(common) >= cc["min_overlap_points"]:
                r = pearson([ba[k] for k in common], [bb[k] for k in common])
            pairs.append({"a": a["id"], "b": b["id"], "overlap_s": max(0, ov) / 1000.0,
                          "jaccard": (max(0, ov) / un) if un > 0 else (1.0 if ov >= 0 else 0.0),
                          "common_bins": len(common), "pearson_r": None if r is None else round(r, 4),
                          "same_direction": a["direction"] == b["direction"]})
        mm = {f["id"]: f["metric"] for f in g}
        same = [p for p in pairs if mm[p["a"]] == mm[p["b"]]]
        use = same or pairs   # prefer same-metric pairs (in vs in) over cross-metric
        for p in pairs:
            p["used_for_mean"] = p in use
        rs = [p["pearson_r"] for p in use if p["pearson_r"] is not None]
        mean_r = round(mean(rs), 4) if rs else None
        if len(devs) == 1:
            label = "single-device, multiple interfaces/metrics"
        elif mean_r is not None and mean_r >= cc["shared_r_threshold"] and all(p["same_direction"] for p in use):
            label = "shared-cause candidate (not proven)"
        elif mean_r is None:
            label = "coincident in time; correlation not computable (too few common points)"
        else:
            label = "coincident in time; weak/negative correlation -> independent causes not excluded"
        cid = "C-" + hashlib.sha1("|".join(sorted(f["id"] for f in g)).encode()).hexdigest()[:10]
        out.append({
            "id": cid, "layer": "statistical+interpretation", "kind": "correlation", "members": [f["id"] for f in g],
            "devices": devs, "zones": zones, "cross_zone": len(zones) > 1,
            "window": {"start_ms": w0, "end_ms": w1}, "pairs": pairs, "mean_pearson_r": mean_r,
            "label": label, "label_layer": "interpretation",
            "math": {"grouping": f"windows overlap within slack={cc['slack_s']}s (union-find)",
                     "pearson": f"r over baseline residuals (x - baseline median) binned to {bw/1000:.0f}s, need >= {cc['min_overlap_points']} common bins",
                     "shared_rule": f"distinct devices>=2 AND mean r >= {cc['shared_r_threshold']} AND same direction in all pairs"},
            "confidence": {"level": "medium" if label.startswith("shared") else "low",
                           "justification": "temporal+shape agreement only; device clock skew not measured; no topology used"},
        })
    return out
