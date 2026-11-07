"""INTERPRETATION layer. Rule-based, no model. Each rule is documented in RULES
(name, condition, source fields). No evidence => 'Unknown - insufficient evidence'.
Every output is a CANDIDATE explanation, never a proven cause."""

RULES = [
    {"name": "R1_cr_overlap_or_follow", "condition": "CR scope includes the finding's device(/interface) AND CR window overlaps the finding window, or finding starts <= lookahead_h after CR end",
     "source": "finding.window, CR store (scope, actual/planned window)"},
    {"name": "R2_multi_device_correlated", "condition": "finding belongs to a correlation cluster with label 'shared-cause candidate'",
     "source": "correlation cluster: members, mean_pearson_r, same_direction"},
    {"name": "R3_data_artifact_in_window", "condition": "series has an excluded interval (reset/gap/ambiguous) or counter-wrap event within [start-1 interval, end+1 interval]",
     "source": "series.excluded, series.events"},
    {"name": "R4_near_zero_traffic", "condition": "direction=low AND mean value < 5% of baseline median",
     "source": "finding.numbers.mean_value, baseline_median"},
    {"name": "R6_shift_continuation", "condition": "anomaly starts within interpret.shift_followup_days after a pattern_shift on the SAME series, in the same direction (causal baseline has not yet re-learned the new level)",
     "source": "pattern_shift findings of the same series_key"},
    {"name": "R5_cross_zone", "condition": "cluster spans more than one zone",
     "source": "correlation cluster zones"},
]
UNKNOWN = "Unknown - insufficient evidence"


def mark_continuations(findings, followup_days=21):
    """Sets finding['continuation_of'] (R6). Done BEFORE correlation so continuation noise is excluded."""
    shifts = [f for f in findings if f["kind"] == "pattern_shift"]
    for f in findings:
        if f["kind"] != "anomaly":
            continue
        for sh in shifts:
            if sh["series_key"] == f["series_key"] and 0 <= f["window"]["start_ms"] - sh["window"]["start_ms"] <= followup_days * 86400000 \
                    and ((sh["direction"] == "up") == (f["direction"] == "high")):
                f["continuation_of"] = sh["id"]
                break


def interpret(finding, series, clusters_by_member):
    out = []
    if finding.get("continuation_of"):
        out.append({"rule": "R6_shift_continuation", "claim": f"follows pattern shift {finding['continuation_of']} in same direction: likely the same level change seen by a baseline that has not adapted",
                    "evidence": [finding["id"], finding["continuation_of"]]})
    for c in finding.get("cr_candidates", []):
        out.append({"rule": "R1_cr_overlap_or_follow", "claim": f"CR {c['cr_id']} {c['relation']} this window"
                    + ("" if c["relation"] == "overlaps" else f" (+{c['delta_s']/3600:.1f} h after CR end)") + f" - {c['label']}",
                    "evidence": [finding["id"], c["cr_id"]]})
    cl = clusters_by_member.get(finding["id"])
    if cl and cl["label"].startswith("shared"):
        out.append({"rule": "R2_multi_device_correlated", "claim": f"anomaly coincides on {len(cl['devices'])} devices (mean r={cl['mean_pearson_r']}) - shared cause candidate, not proven",
                    "evidence": [finding["id"], cl["id"]]})
        if cl["cross_zone"]:
            out.append({"rule": "R5_cross_zone", "claim": f"cluster spans zones {cl['zones']}", "evidence": [cl["id"]]})
    if series is not None and finding["kind"] == "anomaly":
        w = finding["window"]
        m = (series.interval_ms or 0)
        art = [x for x in series.excluded + series.events if x["start_ms"] <= w["end_ms"] + m and x["end_ms"] >= w["start_ms"] - m]
        if art:
            kinds = sorted({x["type"] for x in art})
            out.append({"rule": "R3_data_artifact_in_window", "claim": f"data-quality events near window: {kinds} - possible measurement artifact, verify raw samples",
                        "evidence": [finding["id"]] + [f"{x['type']}@{x['start_raw']}" for x in art[:3]]})
        n = finding["numbers"]
        if finding["direction"] == "low" and n.get("baseline_median") and n.get("mean_value") is not None \
                and n["mean_value"] < 0.05 * n["baseline_median"]:
            out.append({"rule": "R4_near_zero_traffic", "claim": "traffic near zero versus baseline - possible link/device outage or polling problem; check interface state and logs (verify on device)",
                        "evidence": [finding["id"]]})
    if not out:
        out.append({"rule": None, "claim": UNKNOWN, "evidence": []})
    return out
