"""Tier (entitlement) limits: capacity limits + feature switches, loaded from a JSON file.
SOFT enforcement only: this is plain Python source on the customer's machine, so a determined user can edit or remove it.
It exists to stop accidents and to make the delivered scope explicit and visible, NOT to prevent tampering.
Resolution order: explicit argument/--tier  >  env TRAFFICLAB_TIER  >  tier.json next to the package  >  none (unlimited, shown as such)."""
import json
import os

from . import paths

LIMITS = {"max_devices", "max_series", "max_rows", "max_captures", "max_cr", "max_zones"}
FEATURES = {"poll_mode", "weekly_mode", "devcheck", "custom_rules", "profiles", "report_export"}
ACTIVE = None
# Technical guards from MEASURED performance (tools/bench.py: 2.6M rows = 3 GB RAM, ~66 s). Independent of the commercial tier:
# they stop an out-of-memory crash. Larger inputs must be split (chunked import into the history store) or downsampled upstream.
SAFETY = {"rows": 3_000_000, "captures": 50_000, "series": 100_000}


class TierError(ValueError):
    pass


class Tier:
    def __init__(self, obj, source="<memory>"):
        if not isinstance(obj, dict):
            raise ValueError("tier must be a JSON object")
        extra = set(obj) - {"name", "description", "limits", "features", "estimates", "proposal"}
        if extra:
            raise ValueError(f"unknown tier key(s) {sorted(extra)}")
        self.raw = obj
        self.name = obj.get("name") or "unnamed"
        self.description = obj.get("description", "")
        self.proposal = bool(obj.get("proposal", False))
        self.limits = dict(obj.get("limits", {}))
        self.features = {k: True for k in FEATURES}
        self.features.update(obj.get("features", {}))
        self.estimates = obj.get("estimates", {})
        self.source = source
        bad = set(self.limits) - LIMITS
        if bad:
            raise ValueError(f"unknown limit(s) {sorted(bad)}; valid {sorted(LIMITS)}")
        bad = set(self.features) - FEATURES
        if bad:
            raise ValueError(f"unknown feature(s) {sorted(bad)}; valid {sorted(FEATURES)}")
        for k, v in self.limits.items():
            if v is not None and (not isinstance(v, int) or v < 0):
                raise ValueError(f"limit {k} must be a non-negative integer or null (unlimited)")

    def check(self, what, n, at_least=False):
        lim = self.limits.get(f"max_{what}")
        if lim is not None and n > lim:
            have = f"more than {lim:,}" if at_least else f"{n:,}"
            raise TierError(f"tier '{self.name}' allows at most {lim:,} {what.replace('_', ' ')}; this input has {have}. Reduce the scope, or use a larger tier.")
        _safety(what, n, at_least)

    def require(self, feature, label=None):
        if not self.features.get(feature, True):
            raise TierError(f"feature '{label or feature}' is not included in tier '{self.name}'")

    def describe(self):
        return {"name": self.name, "description": self.description, "proposal": self.proposal, "limits": self.limits, "features": self.features, "estimates": self.estimates, "source": self.source}


def _safety(what, n, at_least=False):
    cap = SAFETY.get(what)
    if cap is not None and n > cap:
        have = f"more than {cap:,}" if at_least else f"{n:,}"
        raise TierError(f"technical safety cap: {what} limited to {cap:,} per run in this build (measured memory limit); this input has {have}. Split the input or downsample upstream.")


def load(spec):
    """spec: path to a tier JSON, or a name: <app dir>/tiers, built-in package tiers, ./tiers."""
    cands = [spec, os.path.join(paths.app_dir(), "tiers", f"{spec}.json"), os.path.join(os.getcwd(), "tiers", f"{spec}.json")]
    for c in cands:
        if os.path.isfile(c):
            return Tier(json.load(open(c, encoding="utf-8")), c)
    if paths.has_resource("tiers", f"{spec}.json"):
        return Tier(json.loads(paths.read_resource("tiers", f"{spec}.json")), f"built-in:{spec}")
    raise ValueError(f"tier '{spec}' not found (looked for a file {spec!r}, tiers/{spec}.json, built-in tiers)")


def resolve(explicit=None):
    """--tier / env > tier.json beside the app > tier baked into this build (tier.default.json) > none."""
    spec = explicit or os.environ.get("TRAFFICLAB_TIER")
    if spec:
        return load(spec)
    p = os.path.join(paths.app_dir(), "tier.json")
    if os.path.isfile(p):
        return load(p)
    if paths.has_resource("tier.default.json"):
        return Tier(json.loads(paths.read_resource("tier.default.json")), "baked into this build")
    return None


def install(path):
    """Validate a tier file and install it as <app dir>/tier.json (the simple upgrade path). Keeps the old one as tier.json.bak."""
    t = Tier(json.load(open(path, encoding="utf-8")), path)
    dst = os.path.join(paths.app_dir(), "tier.json")
    if os.path.isfile(dst):
        import shutil
        shutil.copy(dst, dst + ".bak")
    json.dump(json.load(open(path, encoding="utf-8")), open(dst, "w"), indent=2)
    return t, dst


def activate(t):
    global ACTIVE
    ACTIVE = t
    return t


def check(what, n, at_least=False):
    if ACTIVE:
        ACTIVE.check(what, n, at_least)
    else:
        _safety(what, n, at_least)            # the technical guards apply even with no tier


def limit(what):
    """Smallest of the tier limit and the technical guard (None = unlimited)."""
    vals = [v for v in ((ACTIVE.limits.get(f"max_{what}") if ACTIVE else None), SAFETY.get(what)) if v is not None]
    return min(vals) if vals else None


def require(feature, label=None):
    if ACTIVE:
        ACTIVE.require(feature, label)
