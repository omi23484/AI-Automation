"""Environment profile: ONE JSON file holding everything that differs between customers/environments.
Strictly validated at load (unknown keys, bad regexes, bad rule ids are errors, not silent no-ops).

{
 "name": "...", "description": "...",
 "config":  { ...any keys of config.DEFAULTS (zone_map, devcheck.groups, devcheck.rules, weekly.aliases, thresholds, per-zone overrides)... },
 "import":  { "tz": "UTC", "ts_formats": ["%Y-%m-%d %H:%M:%S"], "delimiter": ",", "mapping": {...} | "preset": "name" },
 "presets": { "my-export": { "description": "...", "ts_formats": [...], "mapping": {...} } }
}"""
import copy

from .config import DEFAULTS, check_keys, make_config, _merge
from . import tier
from .devcheck import custom as C
from .devcheck.rules import RULE_BY_ID

TOP = {"name", "description", "config", "import", "presets"}
IMPORT = {"tz", "ts_formats", "delimiter", "mapping", "preset"}


def load(obj):
    tier.require("profiles", "environment profiles")
    if not isinstance(obj, dict):
        raise ValueError("profile must be a JSON object")
    extra = set(obj) - TOP
    if extra:
        raise ValueError(f"unknown profile key(s) {sorted(extra)}; valid: {sorted(TOP)}")
    prof = copy.deepcopy(obj)
    prof.setdefault("name", "unnamed")
    cfg = prof.setdefault("config", {})
    check_keys(cfg)
    dc = make_config(cfg)["devcheck"]          # merged view: also proves types merge cleanly
    C.compile_parsers(dc.get("custom_parsers"))
    C.compile_rules(dc.get("custom_rules"), set(RULE_BY_ID))
    imp = prof.setdefault("import", {})
    if set(imp) - IMPORT:
        raise ValueError(f"unknown import key(s) {sorted(set(imp) - IMPORT)}; valid: {sorted(IMPORT)}")
    for n, p in prof.setdefault("presets", {}).items():
        if not isinstance(p, dict) or "mapping" not in p:
            raise ValueError(f"preset '{n}' needs a mapping")
        if set(p) - {"description", "ts_formats", "mapping"}:
            raise ValueError(f"preset '{n}': allowed keys description, ts_formats, mapping")
    if imp.get("preset") and imp["preset"] not in all_presets(prof):
        raise ValueError(f"import.preset '{imp['preset']}' not found; known: {sorted(all_presets(prof))}")
    return prof


def effective_config(prof, request_cfg=None):
    """profile config, then per-request overrides on top (both strictly validated)."""
    base = copy.deepcopy(prof["config"]) if prof else {}
    if request_cfg:
        check_keys(request_cfg)
        _merge(base, request_cfg)
    return make_config(base)


def all_presets(prof=None):
    from .presets import PRESETS
    out = dict(PRESETS)
    out.update((prof or {}).get("presets", {}))
    return out


def import_defaults(prof):
    """-> dict(tz, ts_formats, delimiter, mapping) resolved from the profile (preset expanded), only keys that are set."""
    imp = dict((prof or {}).get("import", {}))
    pre = imp.pop("preset", None)
    out = {}
    if pre:
        p = all_presets(prof)[pre]
        out["mapping"], out["ts_formats"] = p["mapping"], p.get("ts_formats")
    out.update({k: v for k, v in imp.items() if v is not None})
    return out
