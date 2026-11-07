"""Module 4 rules. Each rule is documented in RULES (name, condition, source fields). No hidden logic:
a finding exists only if its rule fired on parsed fields, and carries evidence (device, command, line, field, value, raw text).
Severity: critical | warning | info.  `verify` = items whose semantics should be confirmed on the device."""
import hashlib
from collections import defaultdict

RULES = [
    {"id": "DC01", "name": "interface error counters non-zero", "severity": "warning/info", "source": "show interface(s) counters errors: Align-Err, FCS-Err, Xmit-Err, Rcv-Err, UnderSize, OutDiscards, collisions, Runts",
     "condition": "any counter > 0. FCS/Align/Rcv/Xmit-Err and Late/Excess-Col/Carri-Sen => warning; others => info. Counters are cumulative since boot/clear: ONE snapshot cannot show whether they still increase."},
    {"id": "DC02", "name": "interface err-disabled", "severity": "critical", "source": "show interface status: Status", "condition": "Status == 'err-disabled'"},
    {"id": "DC03", "name": "port-channel / member not up", "severity": "warning", "source": "show etherchannel summary / show port-channel summary: flags (meaning taken from the legend printed in the same capture)",
     "condition": "port-channel flags contain 'D', or any member flag != 'P'"},
    {"id": "DC04", "name": "spanning-tree transitional or inconsistent ports", "severity": "warning/critical", "source": "show spanning-tree summary (Listening, Learning); show spanning-tree inconsistentports (count)",
     "condition": "Listening>0 or Learning>0 => warning (ports not yet forwarding; may follow a topology change); inconsistent ports > 0 => critical"},
    {"id": "DC05", "name": "BGP neighbor not established", "severity": "critical/info", "source": "show [ip] bgp [ipv4 unicast] summary: State/PfxRcd", "condition": "State/PfxRcd is not a number (Idle, Active, Connect, OpenSent...). 'Idle (Admin)' => info"},
    {"id": "DC06", "name": "BGP session established recently", "severity": "info", "source": "BGP summary: Up/Down", "condition": "established and Up/Down age < devcheck.bgp_recent_s"},
    {"id": "DC07", "name": "OSPF neighbor not FULL", "severity": "warning", "source": "show ip ospf neighbor(s): State", "condition": "state != FULL, except 2WAY with DROTHER role (normal between non-DR/BDR routers)"},
    {"id": "DC08", "name": "OSPF adjacency not FULL / churn", "severity": "warning/info", "source": "show ip ospf neighbor detail: State, state changes", "condition": "state != FULL => warning; state changes >= devcheck.ospf_changes_min => info (cumulative counter)"},
    {"id": "DC09", "name": "BFD session not Up", "severity": "warning", "source": "show bfd neighbors: State", "condition": "State != Up"},
    {"id": "DC10", "name": "vPC health", "severity": "critical/warning", "source": "show vpc brief: Peer status, keep-alive, consistency, role, per-vPC status",
     "condition": "healthy values taken from OBSERVED captures only: peer 'peer adjacency formed ok', keep-alive 'peer is alive', consistency 'success'. Anything else is flagged (verify on device). vPC leg 'down'/'down*' => warning", "verify": True},
    {"id": "DC11", "name": "HSRP group not Active/Standby", "severity": "warning", "source": "show standby brief: State", "condition": "State in Init/Listen/Speak/Learn/Disabled"},
    {"id": "DC12", "name": "syslog: severe, flapping or noisy messages", "severity": "critical/warning/info", "source": "show logging [last N]: tag %FAC-SEV-MNEMONIC",
     "condition": "severity <= devcheck.log_sev_max => critical; >= flap_min_events UP/DOWN events on one interface => warning; same tag >= log_repeat_min times => warning (sev<=4) / info"},
    {"id": "DC13", "name": "device clock not confirmed synchronized", "severity": "info", "source": "show clock: leading '*' (IOS-XE), 'Time source is' (NX-OS)", "condition": "leading '*' present, or time source is not NTP", "verify": True},
    {"id": "X01", "name": "same HSRP group Active on more than one device", "severity": "critical", "source": "show standby brief across devices (group + virtual IP)", "condition": "two or more devices report State=Active for the same (group, virtual IP)", "cross": True},
    {"id": "X02", "name": "same syslog tag on several devices", "severity": "info", "source": "show logging across devices", "condition": "tag with severity <= 4 seen on >= 2 devices (shared-symptom candidate, not a cause)", "cross": True},
]
RULE_BY_ID = {r["id"]: r for r in RULES}
FLAP_RE = ("UPDOWN", "IF_DOWN", "IF_UP")
CRC_LIKE = {"FCS-Err", "Align-Err", "Rcv-Err", "Xmit-Err", "Late-Col", "Excess-Col", "Carri-Sen"}


def _ev(cap, row, field, value):
    return {"device": cap.device, "command": cap.command, "source": cap.source, "line": row["line"], "field": field, "value": str(value), "text": row["text"][:200]}


def _f(rule, dev, sev, title, detail, evidence, key, verify=False):
    fid = "D-" + hashlib.sha1(f"{rule}|{dev}|{key}".encode()).hexdigest()[:10]
    out = {"id": fid, "layer": "rule", "rule": rule, "rule_name": RULE_BY_ID[rule]["name"], "severity": sev, "device": dev, "title": title, "detail": detail, "evidence": evidence}
    if verify or RULE_BY_ID[rule].get("verify"):
        out["verify_on_device"] = True
    return out


def run_device(dev, facts, cfg):
    """facts: list of (Capture, parser_name, result). Returns findings for one device."""
    d, out = cfg["devcheck"], []
    for cap, pname, r in facts:
        kind = r["kind"]
        rows = r["rows"]
        if kind == "counters_errors":
            per_port = defaultdict(list)           # a port appears once per table (errors / collisions): merge into ONE finding
            for row in rows:
                per_port[row["port"]].append(row)
            for port, prs in per_port.items():
                nz = [(k, v, pr) for pr in prs for k, v in pr["counters"].items() if v]
                if not nz:
                    continue
                sev = "warning" if any(k in CRC_LIKE for k, _, _ in nz) else "info"
                out.append(_f("DC01", dev, sev, f"{port}: non-zero error counters", "; ".join(f"{k}={v}" for k, v, _ in nz) + " (cumulative; one snapshot)",
                              [_ev(cap, pr, k, v) for k, v, pr in nz], port))
        elif kind == "if_status":
            for row in rows:
                if row["status"] == "err-disabled":
                    out.append(_f("DC02", dev, "critical", f"{row['port']}: err-disabled", "interface status is err-disabled", [_ev(cap, row, "Status", row["status"])], row["port"]))
        elif kind == "port_channel":
            leg = r["legend"]
            for row in rows:
                bad = [(m, f) for m, f in row["members"] if f != "P"]
                if "D" in row["po_flags"] or bad:
                    txt = "; ".join(f"{c}={leg.get(c, '?')}" for c in sorted(set(row["po_flags"] + "".join(f for _, f in bad))))
                    ev = [_ev(cap, row, "port-channel flags", f"{row['po']}({row['po_flags']})")] + [_ev(cap, row, f"member {m}", f) for m, f in bad]
                    out.append(_f("DC03", dev, "warning", f"{row['po']}: down or members not bundled", f"flags per legend in capture: {txt}", ev, row["po"]))
        elif kind == "stp_summary":
            for row in rows:
                if row["listening"] or row["learning"]:
                    out.append(_f("DC04", dev, "warning", f"{row['name']}: ports not yet forwarding",
                                  f"listening={row['listening']} learning={row['learning']}", [_ev(cap, row, "Listening", row["listening"]), _ev(cap, row, "Learning", row["learning"])], row["name"]))
        elif kind == "stp_inconsistent":
            for row in rows:
                if row["count"] > 0:
                    out.append(_f("DC04", dev, "critical", "STP inconsistent ports present", f"count={row['count']}", [_ev(cap, row, "inconsistent ports", row["count"])], "inconsistent"))
        elif kind == "bgp":
            for row in rows:
                lab = f"{row['neighbor']} (AS {row['as']}{', ' + row['context'] if row['context'] else ''})"
                if not row["established"]:
                    sev = "info" if row["state_pfx"].startswith("Idle (Admin)") else "critical"
                    out.append(_f("DC05", dev, sev, f"BGP neighbor {lab} not established", f"State/PfxRcd={row['state_pfx']}", [_ev(cap, row, "State/PfxRcd", row["state_pfx"])], row["neighbor"] + row["context"]))
                elif row["age_s"] is not None and row["age_s"] < d["bgp_recent_s"]:
                    out.append(_f("DC06", dev, "info", f"BGP neighbor {lab} up only {row['up_down']}", f"Up/Down={row['up_down']} < {d['bgp_recent_s']}s", [_ev(cap, row, "Up/Down", row["up_down"])], row["neighbor"] + row["context"]))
        elif kind == "ospf":
            for row in rows:
                st = row["state"]
                if "time_field" in row:
                    if st != "FULL" and not (st == "2WAY" and row["role"] == "DROTHER"):
                        out.append(_f("DC07", dev, "warning", f"OSPF neighbor {row['neighbor_id']} on {row['interface']} is {st}", f"role={row['role']}", [_ev(cap, row, "State", f"{st}/{row['role']}")], row["neighbor_id"] + row["interface"]))
                else:
                    ev = [_ev(cap, {"line": row["state_line"], "text": row["state_text"]}, "State", st)]
                    if st != "FULL":
                        out.append(_f("DC08", dev, "warning", f"OSPF neighbor {row['neighbor_id']} on {row.get('interface', '?')} is {st}", f"state changes={row['state_changes']}", ev, row["neighbor_id"] + "state"))
                    if row["state_changes"] >= d["ospf_changes_min"]:
                        out.append(_f("DC08", dev, "info", f"OSPF neighbor {row['neighbor_id']}: {row['state_changes']} state changes", "cumulative counter since adjacency creation; may be normal bring-up", ev, row["neighbor_id"] + "churn"))
        elif kind == "bfd":
            for row in rows:
                if row["state"] != "Up":
                    out.append(_f("DC09", dev, "warning", f"BFD neighbor {row['neighbor']} on {row['interface']} is {row['state']}", "", [_ev(cap, row, "State", row["state"])], row["neighbor"]))
        elif kind == "vpc":
            kv = r["kv"]
            def chk(key, healthy, sev):
                v = kv.get(key)
                if v and v["value"] not in healthy:
                    out.append(_f("DC10", dev, sev, f"vPC: {key} = '{v['value']}'", f"healthy value(s) seen in captures: {sorted(healthy)}", [_ev(cap, v, key, v["value"])], key))
            chk("Peer status", {"peer adjacency formed ok"}, "critical")
            chk("vPC keep-alive status", {"peer is alive"}, "critical")
            chk("Configuration consistency status", {"success"}, "warning")
            chk("Per-vlan consistency status", {"success"}, "warning")
            chk("Type-2 consistency status", {"success"}, "warning")
            chk("vPC role", {"primary", "secondary", "primary, operational secondary", "secondary, operational primary"}, "warning")
            for row in rows:
                if row["status"].startswith("down"):
                    out.append(_f("DC10", dev, "warning", f"vPC {row['id']} ({row['port']}) is {row['status']}", row["rest"], [_ev(cap, row, "Status", row["status"])], f"leg{row['id']}"))
        elif kind == "hsrp":
            for row in rows:
                if row["state"] not in ("Active", "Standby"):
                    out.append(_f("DC11", dev, "warning", f"HSRP {row['interface']} group {row['group']} is {row['state']}", f"vip={row['vip']} active={row['active']} standby={row['standby']}", [_ev(cap, row, "State", row["state"])], f"{row['interface']}{row['group']}"))
        elif kind == "log":
            by_tag, flaps = defaultdict(list), defaultdict(list)
            for row in rows:
                by_tag[row["tag"]].append(row)
                if row["interface"] and any(x in row["mnemonic"] for x in FLAP_RE):
                    flaps[row["interface"]].append(row)
            for tag, rs in by_tag.items():
                n = sum(1 + x["repeat"] for x in rs)
                sev_n = rs[0]["severity"]
                evs = [_ev(cap, rs[0], "first ts_raw", rs[0]["ts_raw"]), _ev(cap, rs[-1], "last ts_raw", rs[-1]["ts_raw"])]
                if sev_n <= d["log_sev_max"]:
                    out.append(_f("DC12", dev, "critical", f"{tag} x{n}", f"severity {sev_n} <= {d['log_sev_max']}: {rs[0]['msg'][:140]}", evs, tag + "sev"))
                elif n >= d["log_repeat_min"]:
                    out.append(_f("DC12", dev, "warning" if sev_n <= 4 else "info", f"{tag} repeated {n}x", rs[0]["msg"][:140], evs, tag + "rep"))
            for ifc, rs in flaps.items():
                n = sum(1 + x["repeat"] for x in rs)
                if n >= d["flap_min_events"]:
                    out.append(_f("DC12", dev, "warning", f"{ifc}: {n} up/down log events", "; ".join(x["tag"] for x in rs[:3]), [_ev(cap, x, "ts_raw", x["ts_raw"]) for x in rs[:4]], ifc + "flap"))
        elif kind == "clock":
            for row in rows:
                if row["marker"] == "*":
                    out.append(_f("DC13", dev, "info", "clock marked with leading '*'", "IOS-XE prefixes show clock with '*' when time is not authoritative (verify on device)", [_ev(cap, row, "show clock", row["text"])], "star"))
                if row.get("source") and row["source"] != "NTP":
                    out.append(_f("DC13", dev, "info", f"time source is {row['source']}", "", [_ev(cap, {"line": row["source_line"], "text": row["source_text"]}, "Time source", row["source"])], "src"))
    return out


def run_cross(per_dev_facts, findings_by_dev, cfg):
    """Cross-device rules compare devices only inside the same group (cfg devcheck.groups; default one group 'all')."""
    out = []
    grp = cfg["devcheck"].get("groups", {})
    for gname in sorted({grp.get(d, "all") for d in per_dev_facts}):
        out += _cross_group(gname, {d: f for d, f in per_dev_facts.items() if grp.get(d, "all") == gname})
    return out


def _cross_group(gname, per_dev_facts):
    out = []
    groups = defaultdict(list)
    tags = defaultdict(dict)
    for dev, facts in per_dev_facts.items():
        for cap, pname, r in facts:
            if r["kind"] == "hsrp":
                for row in r["rows"]:
                    if row["state"] == "Active":
                        groups[(row["group"], row["vip"])].append((dev, cap, row))
            if r["kind"] == "log":
                for row in r["rows"]:
                    if row["severity"] <= 4:
                        tags[row["tag"]].setdefault(dev, (cap, row))
    for (g, vip), lst in groups.items():
        devs = sorted({x[0] for x in lst})
        if len(devs) >= 2:
            out.append(_f("X01", ",".join(devs), "critical", f"HSRP group {g} ({vip}) Active on {len(devs)} devices", f"compared within device group '{gname}'. Possible split-brain, OR devices from different networks/times: set devcheck.groups to separate them", [_ev(c, r, "State", "Active") for _, c, r in lst], f"{gname}{g}{vip}"))
    for tag, per in tags.items():
        if len(per) >= 2:
            out.append(_f("X02", ",".join(sorted(per)), "info", f"{tag} seen on {len(per)} devices", f"group '{gname}'; shared-symptom candidate; not evidence of a common cause", [_ev(c, r, "first seen", r["ts_raw"]) for c, r in per.values()], gname + tag))
    return out
