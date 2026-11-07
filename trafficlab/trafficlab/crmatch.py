"""CR <-> finding candidate matching. Temporal + device scope only.
Always labelled: candidate correlation, NOT proven cause."""

LABEL = "candidate correlation, not proven cause"


def cr_window(cr):
    """Actual window if both ends present, else planned. Returns (start,end,which) or None."""
    if cr.get("actual_start_ms") is not None:
        end = cr.get("actual_end_ms")
        if end is None:
            end = cr["actual_start_ms"]  # open-ended actual: treat as point start
        return cr["actual_start_ms"], end, "actual"
    if cr.get("planned_start_ms") is not None and cr.get("planned_end_ms") is not None:
        return cr["planned_start_ms"], cr["planned_end_ms"], "planned"
    return None


def scope_hit(cr, device, interface):
    if not cr["scope"]:
        return False
    for sc in cr["scope"]:
        if sc["device"] == device and (not sc["interface"] or sc["interface"] == interface):
            return True
    return False


def match(finding_window, devices_ifs, crs, lookahead_h=24):
    """devices_ifs: list of (device, interface|None). Returns list of candidate dicts."""
    a, b = finding_window["start_ms"], finding_window["end_ms"]
    la = lookahead_h * 3600 * 1000
    out = []
    for cr in crs:
        cw = cr_window(cr)
        if not cw:
            continue
        s, e, which = cw
        if not any(scope_hit(cr, d, i or "") for d, i in devices_ifs):
            continue
        if a <= e and b >= s:
            rel, delta = "overlaps", 0
        elif a > e and a - e <= la:
            rel, delta = "follows", a - e
        else:
            continue
        out.append({"cr_id": cr["cr_id"], "title": cr["title"], "status": cr["status"], "window_used": which,
                    "relation": rel, "delta_s": delta / 1000.0, "label": LABEL,
                    "cr_window_raw": [cr.get(f"{which}_start_raw"), cr.get(f"{which}_end_raw")]})
    return out
