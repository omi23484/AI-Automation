"""Signature library: an EDITABLE knowledge base of known symptom combinations -> candidate cause + suggested checks.
It only matches on evidence the tool already holds (traffic findings, device-check findings, CR candidates, cluster labels, topology) and cites every id it used.
The output is a CANDIDATE explanation attached to a traffic finding (interpretation rule 'KB:<id>'), never a diagnosis. The library ships empty:
entries are the customer's/engineer's knowledge. profiles/example-neutral.json contains generic EXAMPLES to adapt and verify.

Entry:
 {"id":"SIG-1","name":"...","scope":"device|interface","cause":"...","checks":["..."],"confidence":"low|medium","verify_on_device":true,
  "all":[ {"source":"traffic","kind":"anomaly|pattern_shift","direction":"high|low|up|down","metric":"glob","min_severity":"low|medium|high"},   <- exactly one: the anchor
          {"source":"devcheck","rule":"DC01","min_severity":"info|warning|critical","contains":"text"},                                           <- same device (scope interface: same interface)
          {"source":"cr","relation":"overlaps|follows"},   {"source":"cluster","label_startswith":"shared"},   {"source":"topology","relation":"same_link"} ]}"""
import fnmatch
import re

from .devcheck.topology import canon_if, norm_dev

SEV = {"info": 0, "low": 0, "warning": 1, "medium": 1, "critical": 2, "high": 2}
SOURCES = {"traffic", "devcheck", "cr", "cluster", "topology"}
ALLOWED = {"traffic": {"source", "kind", "direction", "metric", "min_severity"}, "devcheck": {"source", "rule", "min_severity", "contains"},
           "cr": {"source", "relation"}, "cluster": {"source", "label_startswith"}, "topology": {"source", "relation"}}
IF_TOKEN = re.compile(r"[A-Za-z][A-Za-z\-]*\d+(?:[/.:]\d+)*")


def compile_entries(entries):
    out, seen = [], set()
    for e in entries or []:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(e.get("id", ""))) or e["id"] in seen:
            raise ValueError(f"signature id {e.get('id')!r}: must match [A-Za-z0-9_-]+ and be unique")
        seen.add(e["id"])
        for k in ("name", "cause", "all"):
            if not e.get(k):
                raise ValueError(f"signature {e['id']}: '{k}' is required")
        if set(e) - {"id", "name", "scope", "cause", "checks", "confidence", "verify_on_device", "all"}:
            raise ValueError(f"signature {e['id']}: unknown key(s) {sorted(set(e) - {'id', 'name', 'scope', 'cause', 'checks', 'confidence', 'verify_on_device', 'all'})}")
        if e.get("scope", "device") not in ("device", "interface") or e.get("confidence", "low") not in ("low", "medium"):
            raise ValueError(f"signature {e['id']}: scope device|interface, confidence low|medium")
        n_anchor = 0
        for c in e["all"]:
            src = c.get("source")
            if src not in SOURCES:
                raise ValueError(f"signature {e['id']}: condition source must be one of {sorted(SOURCES)}")
            if set(c) - ALLOWED[src]:
                raise ValueError(f"signature {e['id']}: {src} condition has unknown key(s) {sorted(set(c) - ALLOWED[src])}; allowed {sorted(ALLOWED[src])}")
            if c.get("min_severity") and c["min_severity"] not in SEV:
                raise ValueError(f"signature {e['id']}: min_severity must be one of {sorted(SEV)}")
            n_anchor += src == "traffic"
        if n_anchor != 1:
            raise ValueError(f"signature {e['id']}: exactly one 'traffic' condition (the anchor finding) is required, found {n_anchor}")
        out.append(e)
    return out


def _if_set(text):
    return {canon_if(t) for t in IF_TOKEN.findall(text)}


def annotate(result, checks, cfg):
    """Idempotent: removes earlier KB interpretations, then applies the library."""
    entries = compile_entries(cfg.get("signatures"))
    for f in result["findings"]:
        f["interpretation"] = [i for i in f["interpretation"] if not str(i.get("rule") or "").startswith("KB:")]
        if not f["interpretation"]:
            f["interpretation"] = [{"rule": None, "claim": "Unknown - insufficient evidence", "evidence": []}]
    if not entries:
        return 0
    dev_findings = [d for d in (checks or {}).get("findings", []) if not d.get("waived")]
    clusters = {c["id"]: c for c in result["clusters"]}
    n = 0
    for f in result["findings"]:
        for e in entries:
            anchor = next(c for c in e["all"] if c["source"] == "traffic")
            if not _match_traffic(f, anchor):
                continue
            ev, ok = [f["id"]], True
            for c in e["all"]:
                src = c["source"]
                if src == "traffic":
                    continue
                if src == "devcheck":
                    hit = [d for d in dev_findings if norm_dev(d["device"]) == norm_dev(f["device"]) and d["rule"] == c.get("rule", d["rule"])
                           and SEV[d["severity"]] >= SEV[c.get("min_severity", "info")] and c.get("contains", "").lower() in (d["title"] + " " + d["detail"]).lower()]
                    if e.get("scope") == "interface":
                        hit = [d for d in hit if canon_if(f["interface"]) in _if_set(d["title"] + " " + d["detail"])]
                    if not hit:
                        ok = False
                        break
                    ev += [d["id"] for d in hit[:3]]
                elif src == "cr":
                    hit = [x for x in f.get("cr_candidates", []) if x["relation"] == c.get("relation", x["relation"])]
                    if not hit:
                        ok = False
                        break
                    ev += [x["cr_id"] for x in hit[:2]]
                elif src == "cluster":
                    cl = clusters.get(f.get("cluster_id"))
                    if not cl or not cl["label"].startswith(c.get("label_startswith", "")):
                        ok = False
                        break
                    ev.append(cl["id"])
                elif src == "topology":
                    t = f.get("topology")
                    r7 = any(i.get("rule") == "R7_both_ends_of_link" for i in f["interpretation"])
                    if not ((c.get("relation") == "same_link" and r7) or (c.get("relation") in (None, "peer") and t)):
                        ok = False
                        break
                    ev.append(f["id"])
            if ok:
                f["interpretation"] = [i for i in f["interpretation"] if i.get("rule")] + [{
                    "rule": f"KB:{e['id']}", "claim": f"matches known pattern '{e['name']}': {e['cause']} (candidate from the signature library; not proven)",
                    "evidence": list(dict.fromkeys(ev)), "checks": e.get("checks", []), "confidence": e.get("confidence", "low"), **({"verify_on_device": True} if e.get("verify_on_device") else {})}]
                n += 1
    return n


def _match_traffic(f, c):
    if c.get("kind") and f["kind"] != c["kind"]:
        return False
    if c.get("direction") and f.get("direction") != c["direction"]:
        return False
    if c.get("metric") and not fnmatch.fnmatch(f["metric"], c["metric"]):
        return False
    return SEV[f["severity"]] >= SEV[c.get("min_severity", "low")]
