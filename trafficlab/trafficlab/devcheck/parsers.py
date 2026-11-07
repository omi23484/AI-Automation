"""Pluggable parsers: (regex on cmd_key) -> function(lines, first_line) -> {"kind", "rows":[...], ...}.
Only formats seen in real captures are parsed; anything else is reported as 'not parsed', never guessed.
Every row has `line` (1-based, original file) and `text` (the raw line)."""
import re

PARSERS = []   # (compiled regex on cmd_key, name, platforms-note, fn)


def register(pattern, name, note=""):
    def deco(fn):
        PARSERS.append((re.compile(pattern), name, note, fn))
        return fn
    return deco


def find_parser(key):
    for rx, name, note, fn in PARSERS:
        if rx.match(key):
            return name, note, fn
    return None


def _ln(first, i):
    return first + i


_UNITS = {"y": 365 * 86400, "w": 7 * 86400, "d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_age(s):
    """'00:01:56' / '1d02h' / '3w0d' / '1y10w' -> seconds, or None ('never', unknown)."""
    s = s.strip()
    m = re.fullmatch(r"(\d+):(\d{2}):(\d{2})", s)
    if m:
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
    toks = re.findall(r"(\d+)([ywdhms])", s)
    if toks and "".join(a + b for a, b in toks) == s:
        return sum(int(a) * _UNITS[b] for a, b in toks)
    return None


# ------------------------------------------------------------------ interface error counters
@register(r"^showinterfaces?counterserrors$", "interface_counters_errors", "IOS-XE + NX-OS (real format seen)")
def p_counters_errors(lines, first):
    rows, cols = [], None
    for i, l in enumerate(lines):
        s = l.rstrip()
        if re.match(r"^Port\s+\S", s):
            cols = s.split()[1:]
            continue
        if not s.strip():
            cols = None
            continue
        if cols and not set(s.strip()) <= set("-"):
            t = s.split()
            if len(t) == len(cols) + 1:
                vals = {c: (int(v) if v.isdigit() else None) for c, v in zip(cols, t[1:])}
                rows.append({"port": t[0], "counters": vals, "line": _ln(first, i), "text": s})
    return {"kind": "counters_errors", "rows": rows}


# ------------------------------------------------------------------ interface status
@register(r"^showinterfacestatus$", "interface_status", "IOS-XE + NX-OS (real format seen)")
def p_if_status(lines, first):
    rows, off = [], None
    for i, l in enumerate(lines):
        s = l.rstrip()
        m = re.match(r"^Port\s+Name\s+Status\s+Vlan", s)
        if m:
            off = (s.index("Name"), s.index("Status"))
            continue
        if off and s.strip() and not set(s.strip()) <= set("-") and len(s) > off[1]:
            rest = s[off[1]:].split()
            if len(rest) >= 4:
                rows.append({"port": s[:off[0]].strip(), "name": s[off[0]:off[1]].strip(), "status": rest[0], "vlan": rest[1],
                             "duplex": rest[2], "speed": rest[3], "line": _ln(first, i), "text": s})
    return {"kind": "if_status", "rows": rows}


# ------------------------------------------------------------------ port-channel
_LEG = re.compile(r"(?:^|\s{2,}|Flags:\s+)([A-Za-z])\s-\s(.+?)(?=\s{2,}[A-Za-z]\s-\s|\s*$)")


@register(r"^show(etherchannelsummary|portchannelsummary)$", "port_channel_summary", "IOS-XE show etherchannel / NX-OS show port-channel (real formats seen)")
def p_pc(lines, first):
    legend, rows, started, last = {}, [], False, None
    for i, l in enumerate(lines):
        s = l.rstrip()
        if not started:
            for k, v in _LEG.findall(s):
                legend[k] = v.strip()
            if re.match(r"^-{3,}[+-]*", s) and rows == [] and any("Group" in x for x in lines[max(0, i - 3):i]):
                started = True
            continue
        m = re.match(r"^(\d+)\s+(Po\d+)\((\w+)\)\s+(?:(Eth|Fc)\s+)?(\S+)\s*(.*)$", s)
        if m:
            mem = re.findall(r"(\S+?)\((\w+)\)", m[6])
            last = {"group": int(m[1]), "po": m[2], "po_flags": m[3], "protocol": m[5], "members": mem, "line": _ln(first, i), "text": s}
            rows.append(last)
        elif last and s.strip() and s[0] == " ":
            last["members"] += re.findall(r"(\S+?)\((\w+)\)", s)
    return {"kind": "port_channel", "rows": rows, "legend": legend}


# ------------------------------------------------------------------ spanning tree
@register(r"^showspanningtreesummary$", "stp_summary", "IOS-XE + NX-OS")
def p_stp_sum(lines, first):
    rows, mode, root = [], None, []
    for i, l in enumerate(lines):
        s = l.rstrip()
        m = re.match(r"^Switch is in (\S+) mode", s)
        if m:
            mode = (m[1], _ln(first, i), s)
        m = re.match(r"^Root bridge for:\s*(.+)$", s)
        if m:
            root.append((m[1], _ln(first, i), s))
        m = re.match(r"^(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", s)
        if m and not s[0].isdigit():
            rows.append({"name": m[1], "blocking": int(m[2]), "listening": int(m[3]), "learning": int(m[4]), "forwarding": int(m[5]),
                         "active": int(m[6]), "line": _ln(first, i), "text": s})
    return {"kind": "stp_summary", "rows": rows, "mode": mode, "root_for": root}


@register(r"^showspanningtreeinconsistentports$", "stp_inconsistent", "IOS-XE (real format seen)")
def p_stp_inc(lines, first):
    for i, l in enumerate(lines):
        m = re.search(r"Number of inconsistent ports.*?:\s*(\d+)", l)
        if m:
            return {"kind": "stp_inconsistent", "rows": [{"count": int(m[1]), "line": _ln(first, i), "text": l.rstrip()}]}
    return {"kind": "stp_inconsistent", "rows": []}


# ------------------------------------------------------------------ BGP
@register(r"^show(ip)?bgp(ipv4unicast|all|vrfall)?summary$", "bgp_summary", "IOS-XE show ip bgp summary; NX-OS show bgp ... summary (real formats seen)")
def p_bgp(lines, first):
    rows, ctx, local_as, rid = [], "", None, None
    pend = None
    for i, l in enumerate(lines):
        s = l.rstrip()
        m = re.search(r"BGP summary information for (.+)$", s)
        if m:
            ctx = m[1].strip()
        m = re.search(r"BGP router identifier (\S+?),? local AS number (\S+)", s)
        if m:
            rid, local_as = m[1], m[2]
        if pend is not None:
            s2 = pend[1] + " " + s.strip()
            pend = None
        else:
            s2 = s
        m = re.match(r"^(\S+)\s+(\d)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(.+?)\s*$", s2)
        if m and re.match(r"^[0-9a-fA-F:.]+$", m[1]):
            st = m[10]
            rows.append({"neighbor": m[1], "as": m[3], "up_down": m[9], "age_s": parse_age(m[9]), "state_pfx": st,
                         "established": st.isdigit(), "context": ctx, "local_as": local_as, "router_id": rid, "line": _ln(first, i), "text": s.strip()})
        elif re.match(r"^[0-9a-fA-F:]{6,}\s*$", s.strip()) and ":" in s:
            pend = (i, s.strip())     # IPv6 neighbor wrapped onto its own line
    return {"kind": "bgp", "rows": rows}


# ------------------------------------------------------------------ OSPF
@register(r"^showipospfneigh(bor|bors)?$", "ospf_neighbors", "IOS-XE show ip ospf neighbor; NX-OS show ip ospf neighbors (format from NX sample)")
def p_ospf(lines, first):
    rows, hdr = [], None
    for i, l in enumerate(lines):
        s = l.strip()                      # tolerate leading whitespace
        if re.match(r"^Neighbor ID\s+Pri\s+State", s):
            hdr = "Dead Time" if "Dead Time" in s else "Up Time"
            continue
        m = re.match(r"^(\S+)\s+(\d+)\s+([A-Z0-9]+)/\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", s)
        if hdr and m:
            rows.append({"neighbor_id": m[1], "state": m[3], "role": m[4], "time_field": hdr, "time": m[5], "address": m[6], "interface": m[7],
                         "line": _ln(first, i), "text": s})
    return {"kind": "ospf", "rows": rows}


@register(r"^showipospfneigh(bor|bors)?detail$", "ospf_neighbors_detail", "IOS-XE (real format seen); NX-OS detail format NOT seen")
def p_ospf_detail(lines, first):
    rows, cur = [], None
    for i, l in enumerate(lines):
        m = re.match(r"^\s*Neighbor (\S+), interface address ([^,\s]+)", l)
        if m:
            cur = {"neighbor_id": m[1], "address": m[2], "line": _ln(first, i), "text": l.strip()}
            rows.append(cur)
            continue
        if cur is None:
            continue
        m = re.search(r"In the area (\S+) via interface (\S+)", l)
        if m:
            cur["area"], cur["interface"] = m[1], m[2]
        m = re.search(r"State is (\S+?), (\d+) state changes", l)
        if m:
            cur.update(state=m[1], state_changes=int(m[2]), state_line=_ln(first, i), state_text=l.strip())
        m = re.search(r"BFD session (\S+)", l)
        if m:
            cur["bfd"] = m[1]
    return {"kind": "ospf", "rows": [r for r in rows if "state" in r]}


# ------------------------------------------------------------------ BFD
@register(r"^showbfdneighbors$", "bfd_neighbors", "IOS-XE (real format seen); NX-OS table not seen populated")
def p_bfd(lines, first):
    rows = []
    for i, l in enumerate(lines):
        m = re.match(r"^(\S+)\s+(\d+/\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", l.rstrip())
        if m and not l.startswith("NeighAddr"):
            rows.append({"neighbor": m[1], "state": m[4], "interface": m[5], "line": _ln(first, i), "text": l.strip()})
    return {"kind": "bfd", "rows": rows}


# ------------------------------------------------------------------ vPC (NX-OS)
VPC_KEYS = ["vPC domain id", "Peer status", "vPC keep-alive status", "Configuration consistency status", "Per-vlan consistency status",
            "Type-2 consistency status", "vPC role", "Number of vPCs configured", "Configuration inconsistency reason", "Type-2 inconsistency reason"]


@register(r"^showvpcbrief$", "vpc_brief", "NX-OS (real format seen)")
def p_vpc(lines, first):
    kv, legs, section = {}, [], None
    for i, l in enumerate(lines):
        s = l.rstrip()
        m = re.match(r"^(.+?)\s*:\s*(.*?)\s*$", s)
        if m and m[1] in VPC_KEYS:
            kv[m[1]] = {"value": m[2], "line": _ln(first, i), "text": s}
            continue
        if s.startswith("vPC Peer-link status"):
            section = "peerlink"
        elif s.startswith("vPC status"):
            section = "legs"
        m = re.match(r"^(\d+)\s+(\S+)\s+(up\*?|down\*?)\s+(.*?)\s*$", s)
        if m and section == "legs":
            legs.append({"id": int(m[1]), "port": m[2], "status": m[3], "rest": m[4], "line": _ln(first, i), "text": s})
        elif m and section == "peerlink":
            kv.setdefault("peerlink", {"value": f"{m[2]} {m[3]}", "line": _ln(first, i), "text": s})
    return {"kind": "vpc", "kv": kv, "rows": legs}


# ------------------------------------------------------------------ HSRP
@register(r"^showstandbybrief$", "hsrp_brief", "IOS-XE (real format seen)")
def p_hsrp(lines, first):
    rows = []
    for i, l in enumerate(lines):
        m = re.match(r"^(\S+)\s+(\d+)\s+(\d+)\s+(P\s+)?(Active|Standby|Init|Listen|Speak|Learn|Disabled)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", l.rstrip())
        if m:
            rows.append({"interface": m[1], "group": int(m[2]), "priority": int(m[3]), "state": m[5], "active": m[6], "standby": m[7], "vip": m[8],
                         "line": _ln(first, i), "text": l.strip()})
    return {"kind": "hsrp", "rows": rows}


# ------------------------------------------------------------------ logging
IOS_LOG = re.compile(r"^(?:\d+:\s*)?(?P<mark>[*.])?(?P<ts>(?:[A-Z][a-z]{2}\s+\d{1,2}(?:\s+\d{4})?\s+)?\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:\s+[A-Z]{2,5})?)\s*:\s+(?P<tag>%[A-Za-z0-9_]+-\d-[A-Za-z0-9_]+):\s?(?P<msg>.*)$")
NX_LOG = re.compile(r"^(?P<ts>\d{4}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(?P<host>\S+)\s+(?P<tag>%[A-Za-z0-9_]+-\d-[A-Za-z0-9_]+):\s?(?P<msg>.*)$")
NX_REP = re.compile(r"^(?P<ts>\d{4}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+last message repeated (?P<n>\d+) times?\s*$")
TAG = re.compile(r"^%([A-Za-z0-9_]+)-(\d)-([A-Za-z0-9_]+)$")
IFACE = re.compile(r"[Ii]nterface\s+([A-Za-z][A-Za-z\-]*\d[\d/.:]*)")


@register(r"^showlogging(last\d+)?$", "logging", "IOS-XE show logging; NX-OS show logging last N (real formats seen)")
def p_log(lines, first):
    rows = []
    for i, l in enumerate(lines):
        s = l.rstrip()
        m = NX_REP.match(s)
        if m and rows:
            rows[-1]["repeat"] += int(m["n"])
            continue
        m = NX_LOG.match(s) or IOS_LOG.match(s)
        if not m:
            continue
        t = TAG.match(m["tag"])
        if not t:
            continue
        ifm = IFACE.search(m["msg"])
        ts_raw = s[:m.end("ts")]           # exact text from line start (seq no., marker, timestamp), host/tag excluded
        rows.append({"ts_raw": ts_raw, "marker": (m.groupdict().get("mark") or ""), "facility": t[1], "severity": int(t[2]), "mnemonic": t[3],
                     "tag": m["tag"], "msg": m["msg"], "interface": ifm[1] if ifm else None, "repeat": 0, "line": _ln(first, i), "text": s})
    return {"kind": "log", "rows": rows}


# ------------------------------------------------------------------ clock
@register(r"^showclock$", "clock", "IOS-XE + NX-OS (real formats seen)")
def p_clock(lines, first):
    row = {"line": first, "text": "", "marker": "", "source": None}
    for i, l in enumerate(lines):
        s = l.rstrip()
        m = re.match(r"^([*.])?\d{2}:\d{2}:\d{2}", s)
        if m and not row["text"]:
            row.update(text=s, marker=m[1] or "", line=_ln(first, i))
        m = re.match(r"^Time source is (.+)$", s)
        if m:
            row.update(source=m[1], source_line=_ln(first, i), source_text=s)
    return {"kind": "clock", "rows": [row] if row["text"] else []}


# ------------------------------------------------------------------ CDP / LLDP neighbors (topology source; no rules)
@register(r"^showcdpneighbors?detail$", "cdp_neighbors_detail", "IOS-XE + NX-OS (real formats seen)")
def p_cdp(lines, first):
    rows, cur = [], None
    for i, l in enumerate(lines):
        m = re.match(r"^Device ID:\s*(\S.*?)\s*$", l)
        if m:
            cur = {"remote_device": m[1], "line": _ln(first, i), "text": l.strip()}
            rows.append(cur)
            continue
        m = re.match(r"^Interface:\s*([^,\s]+),\s*Port ID \(outgoing port\):\s*(\S+)", l)
        if m and cur is not None:
            cur.update(local_interface=m[1], remote_interface=m[2], if_line=_ln(first, i), if_text=l.strip())
    return {"kind": "cdp", "rows": [r for r in rows if "local_interface" in r]}


@register(r"^showlldpneighbors?detail$", "lldp_neighbors_detail", "NX-OS (real format seen); IOS-XE LLDP detail NOT seen")
def p_lldp(lines, first):
    rows, cur = [], None
    for i, l in enumerate(lines):
        if re.match(r"^Chassis id:", l):
            cur = {"line": _ln(first, i), "text": l.strip()}
            rows.append(cur)
            continue
        if cur is None:
            continue
        for key, rx in (("remote_interface", r"^Port id:\s*(\S+)"), ("local_interface", r"^Local (?:Port id|Intf):\s*(\S+)"), ("remote_device", r"^System Name:\s*(\S.*?)\s*$")):
            m = re.match(rx, l)
            if m:
                cur[key] = m[1]
                cur[key + "_line"] = _ln(first, i)
    return {"kind": "lldp", "rows": [r for r in rows if r.get("local_interface") and r.get("remote_interface") and r.get("remote_device")]}
