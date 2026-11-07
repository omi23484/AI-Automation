"""Default configuration. Every number here is a DEFAULT CHOSEN BY THE AUTHOR,
not an industry standard. All are overridable (UI / CLI --config / per zone)."""
import copy

DEFAULTS = {
    # tz used for seasonal bucketing (hour-of-day / day-of-week). IANA name.
    "tz": "UTC",
    "counters": {
        "gap_factor": 1.5,            # dt > gap_factor * median_interval => gap (no rate)
        "speed_headroom": 0.10,       # allowed overshoot over line speed in plausibility test
        "allow_unverified_wrap": False,  # 32-bit decrease, no uptime, no speed => ambiguous unless True
    },
    "baseline": {
        "lookback_weeks": 4,          # same (weekday,hour) instances looked back
        "min_weeks": 3,               # min prior instances for dow_hour tier
        "daytype_days": 28,           # weekday/weekend + hour tier lookback
        "min_daytype": 4,             # min prior same-daytype instances for daytype_hour tier
        "allow_hour_only_tier": False,  # pools weekdays+weekends: false alarms; OFF by default
        "fallback_days": 14,          # hour-of-day-only tier lookback (only if allowed)
        "min_days": 5,                # min prior days for hour_of_day tier (only if allowed)
        "scale_floor_rel": 0.05,      # scale >= 5% of baseline median
        "scale_floor_abs": {"bps": 1000.0, "pct": 0.5, "default": 1.0},
    },
    "anomaly": {
        "z_threshold": 4.0,
        "direction": "both",          # both | high | low
        "min_points": 3,
        "ewma_lambda": 0.2,           # EWMA chart smoothing on seasonal z
        "ewma_L": 4.0,                # control limit = L * sqrt(lambda/(2-lambda)) (z units)
        "ewma_z_clip": 6.0,           # winsorise z before smoothing (limits spike carry-over)
        "ewma_min_points": 3,
        "severity_medium": 6.0,       # peak |z| >= -> medium
        "severity_high": 10.0,        # peak |z| >= -> high
    },
    "changepoint": {
        "enabled": True,
        "stat_threshold": 6.0,
        "min_effect_sigma": 1.0,
        "min_effect_rel": 0.05,
        "min_segment_hours": 24,
        "max_changepoints": 5,
        "min_span_days_hour": 5,
        "min_span_days_dow": 21,
        "min_coverage": 0.5,
    },
    "correlation": {
        "slack_s": 300,
        "min_overlap_points": 6,
        "shared_r_threshold": 0.5,
        "margin_factor": 1.0,         # resid window = finding window +/- margin_factor*duration
    },
    "weekly": {                       # week-over-week mode (aggregated weekly exports). Author's defaults.
        "window_weeks": 8,            # trailing baseline window (observed weeks)
        "min_weeks": 6,               # below this many prior weeks => insufficient history, no score
        "z_threshold": 4.0,           # robust z of this week vs trailing window
        "min_points": 1,              # consecutive weeks needed (a week is already a coarse unit)
        "min_segment_weeks": 4,       # pattern shift: each side >= this many weeks (needs >= 8 weeks total)
        "max_changepoints": 3,
        "stat_threshold": 6.0, "min_effect_sigma": 1.0, "min_effect_rel": 0.05,
        "followup_weeks": 6,          # anomaly this soon after a same-direction shift = continuation (R6)
        "corr_margin_weeks": 6,
        "util_mismatch_pts": 1.0,     # |supplied % - recomputed %| above this => data-quality note
        "aliases": {},                # extra header names per canonical field: {"avg_in_bps":["Mean RX"], "device":["CI Name"]}
        "week_basis": "stamp_period_ends",  # stamp_period_ends | stamp_period_starts | stamp_week_contains  (ISO-week folder names and explicit overrides always win)
    },
    "forecast": {                     # capacity outlook (linear robust trend; NOT seasonal, NOT growth-step aware)
        "enabled": True,
        "min_days": 21,               # poll mode: distinct local days with enough coverage
        "min_weeks": 12,              # weekly mode
        "min_coverage": 0.5,          # fraction of expected polls in a day for that day to count
        "alpha": 0.05,                # Mann-Kendall significance and Sen slope band level
        "thresholds_pct": [80, 90, 100],
        "horizon_days": 1825,         # farther than this => reported as beyond horizon
    },
    "feedback": {                     # effect of analyst verdicts on scoring (visible and reversible)
        "enabled": True,
        "step": 0.15,                 # each distinct 'false positive' mark on a series raises its thresholds by this fraction ...
        "cap": 1.75,                  # ... up to this multiplier. 'real' and 'expected' marks never change thresholds.
    },
    "cr": {"lookahead_h": 24},
    "devcheck": {                     # Module 4 thresholds: author's defaults, not standards
        "bgp_recent_s": 300,          # established session younger than this => info
        "ospf_changes_min": 5,        # cumulative adjacency state changes >= => info
        "log_sev_max": 2,             # syslog severity <= this => critical (0 emerg,1 alert,2 crit)
        "flap_min_events": 3,         # up/down log events on one interface in the capture => warning
        "log_repeat_min": 20,         # same message tag seen >= times in the capture => noisy-message finding
        "groups": {},                 # device -> group label. Cross-device rules (X01/X02) compare ONLY within a group; default group "all"
        "group_map": [],              # glob rules: [{"match":"leaf-*","group":"fabricA"}] (exact "groups" entries win)
        "waivers": [],                # [{"rule":"DC05","device":"n93*","contains":"192.0.2.2","reason":"lab: no peer by design"}]
        "rules": {},                  # per-rule control: {"DC13":{"enabled":false},"DC12":{"severity":"info"}}. Disabled rules are LISTED in the output
        "custom_parsers": [],         # declarative regex parsers, see docs/ADAPTING.md
        "custom_rules": [],           # declarative field checks, see docs/ADAPTING.md
        "max_custom_findings": 50,    # per custom rule per device; truncation is reported
    },
    "zone_map": [],                   # device-name globs -> zone: [{"match":"*-wan-*","zone":"WAN"}]. Order: data column > inventory > zone_map > 'unassigned' 
    "interpret": {"shift_followup_days": 21},  # anomaly after same-direction shift => continuation (R6)
    # per-zone overrides, same nested shape, e.g. {"WAN": {"anomaly": {"z_threshold": 5}}}
    "zones": {},
}


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


# nodes whose children are free-form (user-chosen keys) and are therefore not key-checked
_FREE = {"baseline.scale_floor_abs", "devcheck.groups", "devcheck.rules", "weekly.aliases"}


def check_keys(over, base=None, path=""):
    """Strict validation: an unknown key is an ERROR (a typo must not silently do nothing)."""
    base = DEFAULTS if base is None else base
    for k, v in over.items():
        here = f"{path}.{k}" if path else k
        if path == "zones":                      # zones.<ZONE>: same shape as the top level (minus 'zones')
            check_keys(v, {kk: vv for kk, vv in DEFAULTS.items() if kk != "zones"}, "")
            continue
        if k not in base:
            raise ValueError(f"unknown config key '{here}'. Valid at this level: {sorted(base)}")
        if isinstance(v, dict) and here not in _FREE and here != "zones" and isinstance(base[k], dict):
            check_keys(v, base[k], here)
        elif isinstance(v, dict) and here == "zones":
            for z, zv in v.items():
                check_keys(zv, {kk: vv for kk, vv in DEFAULTS.items() if kk != "zones"}, "")


def make_config(user=None, strict=True):
    cfg = copy.deepcopy(DEFAULTS)
    if user:
        if strict:
            check_keys(user)
        _merge(cfg, user)
    return cfg


def glob_lookup(name, entries, key, default=None):
    """First matching {'match': glob, key: value} entry. Case-insensitive."""
    import fnmatch
    for e in entries or []:
        if fnmatch.fnmatch(name.lower(), str(e.get("match", "")).lower()):
            return e.get(key, default)
    return default


def cfg_for_zone(cfg, zone):
    """Effective config for a zone (zone overrides merged over base, 'zones' dropped)."""
    eff = copy.deepcopy({k: v for k, v in cfg.items() if k != "zones"})
    ov = cfg.get("zones", {}).get(zone)
    if ov:
        _merge(eff, ov)
    return eff


def floor_abs(cfg_baseline, unit):
    fa = cfg_baseline["scale_floor_abs"]
    return float(fa.get(unit, fa.get("default", 1.0)))
