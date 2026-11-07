"""Timestamp parsing. ts_raw is NEVER modified; this returns a separate ts_parsed dict.

ts_parsed = {epoch_ms, format, tz_assumed, tz_source, flags}
 - epoch_ms is None when the string cannot be parsed OR local time is ambiguous /
   nonexistent (DST). We do not guess.
 - sub-millisecond precision is truncated (floor) when converting to epoch_ms.
"""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Candidate formats used ONLY if the user declares none. The validation report always
# shows which format matched how many rows - confirm it. Slash dates (dd/mm vs mm/dd)
# are deliberately absent: ambiguous, must be declared explicitly.
CANDIDATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
]
# pseudo formats (must be declared, never auto-tried)
EPOCH_S, EPOCH_MS = "epoch_s", "epoch_ms"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_RE_INT = re.compile(r"^\d+$")
_RE_DEC = re.compile(r"^\d+(\.\d+)?$")


def get_tz(name):
    if name.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown timezone {name!r} (needs system tzdata): {e}")


def _to_ms(aware_dt):
    d = aware_dt - _EPOCH
    return d.days * 86_400_000 + d.seconds * 1000 + d.microseconds // 1000


def parse_ts(raw, formats=None, tz_name="UTC"):
    formats = formats or CANDIDATE_FORMATS
    tz = get_tz(tz_name)
    s = raw.strip()
    res = {"epoch_ms": None, "format": None, "tz_assumed": tz_name, "tz_source": None, "flags": []}
    if not s:
        res["flags"].append("empty")
        return res
    for fmt in formats:
        if fmt == EPOCH_MS:
            if _RE_INT.match(s):
                res.update(epoch_ms=int(s), format=fmt, tz_source="epoch_utc")
                return res
            continue
        if fmt == EPOCH_S:
            if _RE_DEC.match(s):
                try:
                    res.update(epoch_ms=int(Decimal(s) * 1000), format=fmt, tz_source="epoch_utc")
                except InvalidOperation:
                    continue
                return res
            continue
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        res["format"] = fmt
        if dt.tzinfo is not None:
            res["epoch_ms"] = _to_ms(dt)
            res["tz_source"] = "explicit_offset"
            return res
        res["tz_source"] = "assumed"
        if tz is timezone.utc:
            res["epoch_ms"] = _to_ms(dt.replace(tzinfo=timezone.utc))
            return res
        d0 = dt.replace(tzinfo=tz, fold=0)
        d1 = dt.replace(tzinfo=tz, fold=1)
        if d0.utcoffset() != d1.utcoffset():
            back = d0.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
            res["flags"].append("dst_nonexistent" if back != dt else "dst_ambiguous")
            return res  # epoch_ms stays None: no guessing
        res["epoch_ms"] = _to_ms(d0)
        return res
    res["flags"].append("unparseable")
    return res
