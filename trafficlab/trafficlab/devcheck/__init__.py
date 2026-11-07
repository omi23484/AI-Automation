"""Module 4: multi-device Cisco issue analysis from raw show-command captures (rule based, deterministic)."""
import fnmatch
from collections import Counter, defaultdict

from ..config import make_config
from .capture import Capture, load_path, load_items, load_zip_bytes, from_file, cmd_key
from .parsers import find_parser
from . import rules as R

SEV = {"critical": 3, "warning": 2, "info": 1}


def analyze_captures(caps, cfg=None):
    cfg = cfg or make_config()
    facts = defaultdict(list)
    cov = defaultdict(lambda: {"parsed": [], "rejected": [], "not_parsed": [], "parse_errors": []})
    for c in caps:
        dev = c.device
        if c.rejected:
            cov[dev]["rejected"].append(c.command)
            continue
        fp = find_parser(c.key)
        if not fp:
            cov[dev]["not_parsed"].append(c.command)
            continue
        name, note, fn = fp
        try:
            res = fn(list(c.lines), c.first_line)
        except Exception as e:      # a parser bug must not hide the other results
            cov[dev]["parse_errors"].append(f"{c.command}: {type(e).__name__}: {e}")
            continue
        facts[dev].append((c, name, res))
        cov[dev]["parsed"].append({"command": c.command, "parser": name, "rows": len(res["rows"]), "source": c.source, "command_from_filename": c.command_derived})
    findings, by_dev = [], {}
    for dev, fx in facts.items():
        merged = {}
        for f in R.run_device(dev, fx, cfg):       # same finding seen via two commands -> one finding, evidence from both
            if f["id"] in merged:
                known = {(e["command"], e["line"], e["field"]) for e in merged[f["id"]]["evidence"]}
                merged[f["id"]]["evidence"] += [e for e in f["evidence"] if (e["command"], e["line"], e["field"]) not in known]
            else:
                merged[f["id"]] = f
        fs = list(merged.values())
        by_dev[dev] = fs
        findings += fs
    cross = R.run_cross(facts, by_dev, cfg)
    allf = findings + cross
    for f in allf:                                  # waivers are VISIBLE: kept in output, flagged, excluded from counts
        for w in cfg["devcheck"].get("waivers", []):
            if w.get("rule") == f["rule"] and fnmatch.fnmatch(f["device"], w.get("device", "*")) and w.get("contains", "") in (f["title"] + f["detail"]):
                f["waived"] = w.get("reason") or "waived"
    allf.sort(key=lambda f: (-SEV[f["severity"]], f["device"], f["rule"]))
    devices = {}
    for dev in sorted({c.device for c in caps}):
        fs = [f for f in allf if dev in f["device"].split(",") and not f.get("waived")]
        devices[dev] = {"counts": dict(Counter(f["severity"] for f in fs)), "waived": sum(1 for f in allf if dev in f["device"].split(",") and f.get("waived")), "coverage": {k: (v if k == "parsed" else sorted(set(v))) for k, v in cov[dev].items()},
                        "n_captures": sum(1 for c in caps if c.device == dev)}
    evidence = [dict(e, finding=f["id"], rule=f["rule"], severity=f["severity"]) for f in allf for e in f["evidence"]]
    return {"findings": allf, "cross_device": cross, "devices": devices, "evidence": evidence, "rules": R.RULES,
            "summary": {"devices": len(devices), "captures": len(caps), "findings": len(allf), "by_severity": dict(Counter(f["severity"] for f in allf if not f.get("waived"))),
                        "waived": sum(1 for f in allf if f.get("waived")), "by_rule": dict(Counter(f["rule"] for f in allf))},
            "config": cfg["devcheck"]}
