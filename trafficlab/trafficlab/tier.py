"""Tier (entitlement) limits: capacity limits + feature switches, loaded from a JSON file.
SOFT enforcement only: this is plain Python source on the customer's machine, so a determined user can edit or remove it.
It exists to stop accidents and to make the delivered scope explicit and visible, NOT to prevent tampering.
Resolution order: explicit argument/--tier  >  env TRAFFICLAB_TIER  >  tier.json next to the package  >  none (unlimited, shown as such)."""
import json
import os

LIMITS = {"max_devices", "max_series", "max_rows", "max_captures", "max_cr", "max_zones"}
FEATURES = {"poll_mode", "weekly_mode", "devcheck", "custom_rules", "profiles", "report_export"}
ACTIVE = None


class TierError(ValueError):
    pass


class Tier:
    def __init__(self, obj, source="<memory>"):
        if not isinstance(obj, dict):
            raise ValueError("tier must be a JSON object")
        extra = set(obj) - {"name", "description", "limits", "features", "estimates", "proposal"}
        if extra:
            raise ValueError(f"unknown tier key(s) {sorted(extra)}")
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

    def require(self, feature, label=None):
        if not self.features.get(feature, True):
            raise TierError(f"feature '{label or feature}' is not included in tier '{self.name}'")

    def describe(self):
        return {"name": self.name, "description": self.description, "proposal": self.proposal, "limits": self.limits, "features": self.features, "estimates": self.estimates, "source": self.source}


def load(spec):
    """spec: path to a tier JSON, or a name resolved against ./tiers and <app dir>/tiers."""
    cands = [spec]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands += [os.path.join(d, f"{spec}.json") for d in (os.path.join(here, "tiers"), os.path.join(os.getcwd(), "tiers"))]
    for c in cands:
        if os.path.isfile(c):
            return Tier(json.load(open(c, encoding="utf-8")), c)
    raise ValueError(f"tier '{spec}' not found (looked for {cands[0]} and tiers/{spec}.json)")


def resolve(explicit=None):
    spec = explicit or os.environ.get("TRAFFICLAB_TIER")
    if spec:
        return load(spec)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(here, "tier.json")
    return load(p) if os.path.isfile(p) else None


def activate(t):
    global ACTIVE
    ACTIVE = t
    return t


def check(what, n, at_least=False):
    if ACTIVE:
        ACTIVE.check(what, n, at_least)


def limit(what):
    return ACTIVE.limits.get(f"max_{what}") if ACTIVE else None


def require(feature, label=None):
    if ACTIVE:
        ACTIVE.require(feature, label)
