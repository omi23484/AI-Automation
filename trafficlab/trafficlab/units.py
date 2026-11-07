"""Rate cells with unit tokens ('12.34 Mbps', '1.5 Gbps', '250000 kbps', '12 MB/s').
SI decimal (k=1e3, M=1e6, G=1e9, T=1e12). Case of the LAST letter decides bit vs byte:
lower-case b = bit ('Mbps', 'Mb/s'), upper-case B = byte ('MBps', 'MB/s') -> bytes x8.
No unit token => caller's default_unit, else None (never inferred from magnitude)."""
import re

_CELL = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z/]+)?\s*$")
_THOUSANDS = re.compile(r"^\s*([+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?)(\s*[A-Za-z/]+)?\s*$")
_TOK = re.compile(r"^([kKmMgGtT]?)(b|B)(?:ps|/s|it/s|its/sec|ytes/s|ytes/sec)$")
_PFX = {"": 1.0, "k": 1e3, "m": 1e6, "g": 1e9, "t": 1e12}
_BITS_NAMES = {"bps": 1.0, "bit/s": 1.0}


def unit_multiplier(token):
    """token -> multiplier to bits/s, or None if unknown."""
    if token is None:
        return None
    m = _TOK.match(token)
    if not m:
        return None
    pfx, b = m.group(1).lower(), m.group(2)
    return _PFX[pfx] * (8.0 if b == "B" else 1.0)


def parse_rate(cell, default_unit=None):
    """Return bits/s (float) or None if the cell is empty/unparseable/unknown unit."""
    s = cell.strip()
    if s == "":
        return None
    t = _THOUSANDS.match(s)
    if t:
        s = t.group(1).replace(",", "") + (t.group(2) or "")
    m = _CELL.match(s)
    if not m:
        return None
    num, tok = float(m.group(1)), m.group(2)
    if tok is None:
        mult = unit_multiplier(default_unit) if default_unit else None
        if mult is None and default_unit:      # allow short names like 'mbps' / 'Mbps' / 'gbps'
            mult = unit_multiplier(default_unit)
    else:
        mult = unit_multiplier(tok)
    if mult is None:
        return None
    return num * mult
