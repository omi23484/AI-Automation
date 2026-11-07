"""Module 4 input: split raw device output into per-command captures. Raw text is never altered;
every parsed fact carries the 1-based line number in the ORIGINAL file."""
import io
import os
import re
import zipfile
from dataclasses import dataclass

CMD_HDR = re.compile(r"^COMMAND:\s*(.+?)\s*$")
PROMPT = re.compile(r"^(?P<host>[A-Za-z0-9_.\-]+)(?:\([^)]*\))?[#>]\s*(?P<cmd>(?:sh|show)\s.*?)\s*$")
REJECT = re.compile(r"(% Invalid input|% Incomplete command|Incorrect command|% Ambiguous command|Invalid command|invalid input)", re.I)
PASS_TS = re.compile(r"(\d{8})-(\d{6})")


def cmd_key(cmd):
    """Dispatch key: lower-case alphanumerics only ('show spanning-tree summary' == 'showspanningtreesummary')."""
    return re.sub(r"[^a-z0-9]", "", cmd.lower())


@dataclass(frozen=True)
class Capture:
    device: str
    command: str            # as written in the file (or derived from file name)
    key: str
    lines: tuple            # content lines (no header)
    first_line: int         # 1-based line number in source of lines[0]
    source: str             # file path / name (display only)
    pass_name: str = ""
    command_derived: bool = False   # True when the command came from the file NAME (less certain)
    rejected: bool = False          # device said the command is invalid


def _mk(device, command, lines, first_line, source, pass_name="", derived=False):
    body = list(lines)
    rej = any(REJECT.search(l) for l in body[:6])
    return Capture(device, command, cmd_key(command), tuple(body), first_line, source, pass_name, derived, rej)


def from_file(text, device, source, pass_name=""):
    """One file = one command (broker format 'COMMAND: show x' first line, else command from file name),
    OR a session log with 'host# show ...' prompts holding several commands."""
    lines = text.splitlines()
    if lines and CMD_HDR.match(lines[0]):
        return [_mk(device, CMD_HDR.match(lines[0]).group(1), lines[1:], 2, source, pass_name)]
    prompts = [(i, PROMPT.match(l)) for i, l in enumerate(lines)]
    prompts = [(i, m) for i, m in prompts if m]
    if prompts:
        out = []
        for n, (i, m) in enumerate(prompts):
            end = prompts[n + 1][0] if n + 1 < len(prompts) else len(lines)
            body = lines[i + 1:end]
            while body and re.match(r"^[A-Za-z0-9_.\-]+(?:\([^)]*\))?[#>]\s*$", body[-1]):
                body = body[:-1]
            out.append(_mk(m.group("host"), m.group("cmd"), body, i + 2, source, pass_name))
        return out
    stem = os.path.splitext(os.path.basename(source))[0].split("__")[-1]
    if stem.startswith("show_"):
        return [_mk(device, stem.replace("_", " "), lines, 1, source, pass_name, derived=True)]
    return []


def _pass_rank(name):
    m = PASS_TS.search(name or "")
    return (m.group(1) + m.group(2)) if m else "0"       # un-timestamped (e.g. 'baseline') = oldest


def load_path(path, pass_policy="latest", max_bytes=500_000_000):
    """Directory or .zip laid out as <pass>/<device>/<file>.txt (also <device>/<file>.txt).
    pass_policy: 'latest' keeps, per (device, command), the capture from the newest pass folder; 'all' keeps every one."""
    items = []
    if zipfile.is_zipfile(path):
        items = _zip_items(zipfile.ZipFile(path), max_bytes)
    else:
        for root, _, names in os.walk(path):
            for n in names:
                if n.lower().endswith((".txt", ".log")):
                    p = os.path.join(root, n)
                    items.append((os.path.relpath(p, path).replace(os.sep, "/"), open(p, encoding="utf-8", errors="replace").read()))
    return load_items(items, pass_policy)


def load_zip_bytes(data, pass_policy="latest", max_bytes=500_000_000):
    return load_items(_zip_items(zipfile.ZipFile(io.BytesIO(data)), max_bytes), pass_policy)


def _zip_items(z, max_bytes):
    if sum(i.file_size for i in z.infolist()) > max_bytes:
        raise ValueError("archive too large")
    out = []
    for i in z.infolist():
        parts = i.filename.split("/")
        if i.is_dir() or ".." in parts or i.filename.startswith("/") or not i.filename.lower().endswith((".txt", ".log")):
            continue      # zip-slip / non-text entries are skipped
        out.append((i.filename, z.read(i).decode("utf-8", "replace")))
    return out


def load_items(items, pass_policy="latest"):
    """items: [(relative path 'pass/device/file.txt', text)]. Device = parent folder; pass = grandparent."""
    caps = []
    for rel, text in items:
        parts = [x for x in rel.replace("\\", "/").split("/") if x not in ("", ".")]
        if ".." in parts:
            continue
        pass_name, dev, src = _split_parts(parts)
        caps += from_file(text, dev, rel, pass_name)
    if pass_policy == "all":
        return caps
    best = {}
    for c in caps:
        k = (c.device, c.key)
        if k not in best or _pass_rank(c.pass_name) > _pass_rank(best[k].pass_name):
            best[k] = c
    return list(best.values())


def _split_parts(parts):
    if len(parts) >= 3:
        return parts[-3], parts[-2], parts[-1]
    if len(parts) == 2:
        return "", parts[0], parts[1]
    return "", os.path.splitext(parts[0])[0], parts[0]
