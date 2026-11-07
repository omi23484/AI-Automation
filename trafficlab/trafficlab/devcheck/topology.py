"""Link graph from CDP/LLDP neighbor captures, and its use as CONTEXT for traffic findings.
It never claims a cause: it says whether two findings sit on the two ends of one link, on neighbouring devices, or on devices with no known link
(topology may simply be incomplete: CDP/LLDP must be enabled and captured on the devices involved)."""
import re
from collections import defaultdict

_PFX = [("tengigabitethernet", "te"), ("tengige", "te"), ("fortygigabitethernet", "fo"), ("hundredgige", "hu"), ("twentyfivegige", "twe"), ("gigabitethernet", "gi"),
        ("fastethernet", "fa"), ("ethernet", "eth"), ("port-channel", "po"), ("portchannel", "po"), ("loopback", "lo"), ("management", "mgmt"), ("vlan", "vl")]
_SHORT = {s for _, s in _PFX} | {"mgmt"}


def canon_if(name):
    """'GigabitEthernet1/0/1' == 'Gi1/0/1' == 'gi1/0/1'; 'Ethernet1/7' == 'Eth1/7'."""
    n = re.sub(r"\s+", "", str(name)).lower()
    for full, short in _PFX:
        if n.startswith(full) and re.match(r"[\d/.:]", n[len(full):len(full) + 1] or "x"):
            return short + n[len(full):]
    m = re.match(r"([a-z]+)([\d/.:].*)$", n)
    if m and m[1] in _SHORT:
        return n
    return n


def norm_dev(name):
    """'SW1.corp.local' / 'sw1(SAL1234ABCD)' -> 'sw1'."""
    n = str(name).strip().lower()
    n = re.sub(r"\([^)]*\)$", "", n)
    return n.split(".")[0] if not re.match(r"^\d+\.\d+\.\d+\.\d+$", n) else n


def build(facts_by_device):
    """facts_by_device: {device: [(capture, parser_name, result), ...]} -> {"links": [...]} (undirected, merged across CDP/LLDP and both directions)."""
    edges = {}
    for dev, facts in facts_by_device.items():
        for cap, pname, r in facts:
            if r["kind"] not in ("cdp", "lldp"):
                continue
            for row in r["rows"]:
                a = (norm_dev(dev), canon_if(row["local_interface"]))
                b = (norm_dev(row["remote_device"]), canon_if(row["remote_interface"]))
                key = tuple(sorted([a, b]))
                e = edges.setdefault(key, {"a_device": key[0][0], "a_if": key[0][1], "b_device": key[1][0], "b_if": key[1][1], "sources": [], "evidence": []})
                src = r["kind"].upper()
                if src not in e["sources"]:
                    e["sources"].append(src)
                e["evidence"].append({"device": dev, "command": cap.command, "source": cap.source, "line": row.get("if_line", row["line"]), "text": row.get("if_text", row["text"])[:200]})
    return {"links": list(edges.values())}


def _index(links):
    ends, devs = {}, defaultdict(set)
    for l in links:
        a, b = (l["a_device"], l["a_if"]), (l["b_device"], l["b_if"])
        ends[a], ends[b] = (b, l), (a, l)
        devs[l["a_device"]].add(l["b_device"])
        devs[l["b_device"]].add(l["a_device"])
    return ends, devs


def relation(links_idx, a, b):
    """a, b: findings. -> 'same_link' | 'adjacent' | 'unknown'"""
    ends, devs = links_idx
    ka, kb = (norm_dev(a["device"]), canon_if(a["interface"])), (norm_dev(b["device"]), canon_if(b["interface"]))
    if ka in ends and ends[ka][0] == kb:
        return "same_link"
    if norm_dev(b["device"]) in devs.get(norm_dev(a["device"]), ()):
        return "adjacent"
    return "unknown"


def annotate(result, topo):
    """Adds `topology` context to clusters and findings; appends rule R7 when both ends of one link show findings. Idempotent."""
    if not topo or not topo.get("links"):
        return
    idx = _index(topo["links"])
    ends = idx[0]
    byid = {f["id"]: f for f in result["findings"]}
    for f in result["findings"]:
        f["interpretation"] = [i for i in f["interpretation"] if i.get("rule") != "R7_both_ends_of_link"]
        f.pop("topology", None)
    for c in result["clusters"]:
        c.pop("topology", None)
        mem = [byid[m] for m in c["members"] if m in byid]
        cnt = {"same_link": 0, "adjacent": 0, "unknown": 0}
        for p in c["pairs"]:
            a, b = byid.get(p["a"]), byid.get(p["b"])
            if not a or not b:
                continue
            p["topology"] = relation(idx, a, b)
            cnt[p["topology"]] += 1
        c["topology"] = cnt
        if cnt["same_link"]:
            c["label_topology"] = "includes both ends of one link (CDP/LLDP): consistent with a single link event"
            for p in c["pairs"]:
                if p.get("topology") == "same_link":
                    for fid_ in (p["a"], p["b"]):
                        f = byid.get(fid_)
                        if f:
                            f["interpretation"] = [i for i in f["interpretation"] if i.get("rule")] + [{"rule": "R7_both_ends_of_link", "claim": "both ends of this link show a finding in the same window (per CDP/LLDP): consistent with one link-level event, not proof of cause",
                                                                                                    "evidence": [p["a"], p["b"], c["id"]]}]
                        if f and not f["interpretation"]:
                            f["interpretation"] = [{"rule": None, "claim": "Unknown - insufficient evidence", "evidence": []}]
    present = {(norm_dev(f["device"]), canon_if(f["interface"])) for f in result["findings"]}
    for f in result["findings"]:
        k = (norm_dev(f["device"]), canon_if(f["interface"]))
        if k in ends:
            (pd, pi), link = ends[k]
            w = f["window"]
            peers = [g["id"] for g in result["findings"] if (norm_dev(g["device"]), canon_if(g["interface"])) == (pd, pi) and g["kind"] == f["kind"] and g["window"]["start_ms"] <= w["end_ms"] and g["window"]["end_ms"] >= w["start_ms"]]
            f["topology"] = {"peer_device": pd, "peer_interface": pi, "sources": link["sources"], "peer_findings_same_window": peers,
                             "peer_in_dataset": any((pd, pi) == (norm_dev(x["device"]), canon_if(x["interface"])) for x in result.get("series", [])) or (pd, pi) in present}
