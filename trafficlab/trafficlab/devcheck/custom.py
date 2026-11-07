"""User-defined parsers and rules, DECLARATIVE ONLY (regex + comparisons). No eval/exec, no code from the profile.
Parser spec:  {"name","command_regex","row_regex"(named groups),"header_regex"?,"stop_regex"?,"int_fields"?,"kind"?}
Rule spec:    {"id":"C...","name","severity","kind"(parser kind, built-in or custom),"when":cond|[cond,...],"title","detail"?,"device"?(glob),"verify_on_device"?}
cond:         {"field","op","value"}  ops: eq ne in not_in gt ge lt le contains not_contains regex not_regex
Templates:    '{field}' placeholders only. Regexes are limited in length; lines over 2000 chars are skipped (ReDoS guard)."""
import fnmatch
import hashlib
import re

MAX_RX, MAX_LINE = 500, 2000
SEVS = ("critical", "warning", "info")
OPS = {"eq", "ne", "in", "not_in", "gt", "ge", "lt", "le", "contains", "not_contains", "regex", "not_regex"}


def _rx(s, what):
    if not isinstance(s, str) or not s or len(s) > MAX_RX:
        raise ValueError(f"{what}: regex missing or longer than {MAX_RX} chars")
    try:
        return re.compile(s)
    except re.error as e:
        raise ValueError(f"{what}: invalid regex ({e})")


def compile_parsers(specs):
    out = []
    for sp in specs or []:
        name = sp.get("name")
        if not name:
            raise ValueError("custom parser needs a name")
        row = _rx(sp.get("row_regex"), f"parser {name}.row_regex")
        if not row.groupindex:
            raise ValueError(f"parser {name}: row_regex needs at least one named group (?P<field>...)")
        out.append({"name": name, "kind": sp.get("kind") or f"custom:{name}", "command": _rx(sp.get("command_regex"), f"parser {name}.command_regex"), "row": row,
                    "header": _rx(sp["header_regex"], f"parser {name}.header_regex") if sp.get("header_regex") else None,
                    "stop": _rx(sp["stop_regex"], f"parser {name}.stop_regex") if sp.get("stop_regex") else None,
                    "ints": set(sp.get("int_fields", [])), "note": sp.get("note", "custom parser")})
    return out


def match_parser(parsers, command):
    c = " ".join(command.split())
    for p in parsers:
        if p["command"].search(c):
            return p
    return None


def run_parser(p, lines, first):
    rows, active = [], p["header"] is None
    for i, l in enumerate(lines):
        if len(l) > MAX_LINE:
            continue
        if p["header"] is not None and not active and p["header"].search(l):
            active = True
            continue
        if active and p["stop"] is not None and p["stop"].search(l):
            break                      # stop_regex ends parsing of this capture
        if not active:
            continue
        m = p["row"].match(l.rstrip())
        if m:
            d = dict(m.groupdict())
            for k in p["ints"]:
                if d.get(k) is not None:
                    try:
                        d[k] = int(d[k])
                    except ValueError:
                        d[k] = None
            d.update(line=first + i, text=l.strip())
            rows.append(d)
    return {"kind": p["kind"], "rows": rows}


def compile_rules(specs, builtin_ids):
    out = []
    seen = set()
    for sp in specs or []:
        rid = sp.get("id", "")
        if not re.fullmatch(r"C[A-Za-z0-9_-]{1,20}", rid) or rid in builtin_ids or rid in seen:
            raise ValueError(f"custom rule id {rid!r}: must match C[A-Za-z0-9_-]+ and be unique (built-in ids start with DC/X)")
        seen.add(rid)
        if sp.get("severity") not in SEVS:
            raise ValueError(f"rule {rid}: severity must be one of {SEVS}")
        conds = sp.get("when")
        conds = [conds] if isinstance(conds, dict) else conds
        if not conds or not sp.get("kind") or not sp.get("title") or not sp.get("name"):
            raise ValueError(f"rule {rid}: needs name, kind, title and when")
        cc = []
        for c in conds:
            if c.get("op") not in OPS or not c.get("field"):
                raise ValueError(f"rule {rid}: bad condition {c} (ops: {sorted(OPS)})")
            rx = _rx(c["value"], f"rule {rid} regex") if c["op"] in ("regex", "not_regex") else None
            if c["op"] in ("in", "not_in") and not isinstance(c.get("value"), list):
                raise ValueError(f"rule {rid}: '{c['op']}' needs a list value")
            cc.append(dict(c, rx=rx))
        out.append(dict(sp, conds=cc))
    return out


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _holds(c, row):
    v = row.get(c["field"])
    if v is None:
        return False
    op, ref = c["op"], c.get("value")
    if op in ("gt", "ge", "lt", "le"):
        a, b = _num(v), _num(ref)
        return a is not None and b is not None and {"gt": a > b, "ge": a >= b, "lt": a < b, "le": a <= b}[op]
    if op == "eq":
        return str(v) == str(ref)
    if op == "ne":
        return str(v) != str(ref)
    if op == "in":
        return str(v) in [str(x) for x in ref]
    if op == "not_in":
        return str(v) not in [str(x) for x in ref]
    if op == "contains":
        return str(ref) in str(v)
    if op == "not_contains":
        return str(ref) not in str(v)
    if op == "regex":
        return bool(c["rx"].search(str(v)))
    return not c["rx"].search(str(v))


def _fill(t, row):
    return re.sub(r"\{(\w+)\}", lambda m: str(row.get(m.group(1), "?")), t)


def run_rules(dev, facts, rules, limit):
    out, trunc = [], {}
    for r in rules:
        if r.get("device") and not fnmatch.fnmatch(dev, r["device"]):
            continue
        n = 0
        for cap, pname, res in facts:
            if res["kind"] != r["kind"]:
                continue
            for row in res["rows"]:
                if all(_holds(c, row) for c in r["conds"]):
                    n += 1
                    if n > limit:
                        trunc[r["id"]] = n
                        continue
                    ev = [{"device": dev, "command": cap.command, "source": cap.source, "line": row["line"], "field": c["field"], "value": str(row.get(c["field"])), "text": row["text"][:200]} for c in r["conds"]]
                    key = r["id"] + str(row["line"]) + cap.command
                    out.append({"id": "D-" + hashlib.sha1(f"{dev}|{key}".encode()).hexdigest()[:10], "layer": "rule", "rule": r["id"], "rule_name": r["name"], "custom": True,
                                "severity": r["severity"], "device": dev, "title": _fill(r["title"], row), "detail": _fill(r.get("detail", ""), row), "evidence": ev,
                                **({"verify_on_device": True} if r.get("verify_on_device") else {})})
        if n > limit:
            trunc[r["id"]] = n
    return out, trunc


def rule_docs(rules):
    return [{"id": r["id"], "name": r["name"], "severity": r["severity"], "custom": True, "source": f"parser kind '{r['kind']}'",
             "condition": " AND ".join(f"{c['field']} {c['op']} {c.get('value')!r}" for c in r["conds"])} for r in rules]
