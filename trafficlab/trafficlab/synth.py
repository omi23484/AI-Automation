"""SYNTHETIC data generator. Everything here is FAKE: devices are prefixed SYN-, the
file name must start with SYNTHETIC_, and a ground-truth manifest is written alongside.
This is NOT Cisco output and NOT a real device export; it is a generic CSV for testing."""
import json
import math
import random
from datetime import datetime, timedelta, timezone

SYN_MAPPING = {
    "device": "device", "interface": "interface", "timestamp": "timestamp", "zone": "zone",
    "counters": [{"name": "in_bps", "column": "in_octets", "bits": 64, "mult": 8, "unit": "bps"},
                 {"name": "out_bps", "column": "out_octets", "bits": 64, "mult": 8, "unit": "bps"}],
    "uptime": {"column": "uptime_cs", "unit": "cs"},
    "speed": {"column": "speed_mbps", "unit": "mbps"},
}
SYN_MAPPING32 = dict(SYN_MAPPING, counters=[{"name": "in_bps", "column": "in_octets", "bits": 32, "mult": 8, "unit": "bps"},
                                            {"name": "out_bps", "column": "out_octets", "bits": 32, "mult": 8, "unit": "bps"}])
T0 = datetime(2026, 1, 5, 0, 0, 0)  # Monday, naive, treated as UTC


def _fmt(d):
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _daily(h, weekend):
    base = 0.55 + 0.45 * math.sin((h - 9) / 24 * 2 * math.pi)
    return base * (0.6 if weekend else 1.0)


def generate(days=35, interval_s=300, seed=42, mixed_formats=False, bits32_wan=True):
    """Returns (csv_text, manifest). Devices: WAN x2, ENT x1, DC x2."""
    rnd = random.Random(seed)
    devs = [  # name, zone, iface, speed_mbps, avg_mbps, bits
        ("SYN-WAN-R1", "WAN", "Gi0/0/0", 100, 40, 32 if bits32_wan else 64),
        ("SYN-WAN-R2", "WAN", "Gi0/0/1", 100, 30, 64),
        ("SYN-ENT-SW1", "ENT", "Gi1/0/1", 1000, 200, 64),
        ("SYN-DC-LEAF1", "DC", "Eth1/1", 10000, 3000, 64),
        ("SYN-DC-LEAF2", "DC", "Eth1/1", 10000, 2800, 64),
    ]
    n = days * 86400 // interval_s
    truth = []
    def ts(k):
        return T0 + timedelta(seconds=k * interval_s)
    def k_at(day, hh, mm=0):
        return (day * 86400 + hh * 3600 + mm * 60) // interval_s
    spike = (k_at(20, 14), k_at(20, 14, 30))
    shift_k = k_at(22, 6)
    shared = (k_at(28, 2), k_at(28, 2, 45))
    reload_k = k_at(25, 10)
    gap = (k_at(15, 8), k_at(15, 10))
    truth += [
        {"type": "spike_x4", "device": "SYN-ENT-SW1", "start": _fmt(ts(spike[0])), "end": _fmt(ts(spike[1]))},
        {"type": "level_shift_+40pct", "device": "SYN-WAN-R1", "start": _fmt(ts(shift_k))},
        {"type": "shared_surge_x3", "devices": ["SYN-DC-LEAF1", "SYN-DC-LEAF2"], "start": _fmt(ts(shared[0])), "end": _fmt(ts(shared[1]))},
        {"type": "device_reload", "device": "SYN-DC-LEAF2", "at": _fmt(ts(reload_k))},
        {"type": "polling_gap", "device": "SYN-WAN-R2", "start": _fmt(ts(gap[0])), "end": _fmt(ts(gap[1]))},
        {"type": "counter_wrap_32bit", "device": "SYN-WAN-R1", "note": "occurs naturally; avg 40 Mbps wraps 2^32 octets about every 14 min"},
    ]
    lines = ["timestamp,device,interface,zone,in_octets,out_octets,uptime_cs,speed_mbps"]
    state = {}
    for name, zone, ifc, spd, avg, bits in devs:
        state[name] = {"in": rnd.randrange(0, 2 ** bits) if bits == 32 else rnd.randrange(0, 2 ** 40),
                       "out": rnd.randrange(0, 2 ** bits) if bits == 32 else rnd.randrange(0, 2 ** 40),
                       "up": rnd.randrange(10_000_000, 50_000_000)}
    dup_done = bad_done = False
    for k in range(n):
        d = ts(k)
        wk = d.weekday() >= 5
        for name, zone, ifc, spd, avg, bits in devs:
            st = state[name]
            if name == "SYN-DC-LEAF2" and k == reload_k:
                st["in"], st["out"], st["up"] = 0, 0, 0
            fac = _daily(d.hour + d.minute / 60, wk)
            if name == "SYN-ENT-SW1" and spike[0] <= k < spike[1]:
                fac *= 4
            if name == "SYN-WAN-R1" and k >= shift_k:
                fac *= 1.4
            if name in ("SYN-DC-LEAF1", "SYN-DC-LEAF2") and shared[0] <= k < shared[1]:
                fac *= 3
            for dirn, mult in (("in", 1.0), ("out", 0.6)):
                bps = max(0.0, avg * 1e6 * mult * fac * (1 + rnd.gauss(0, 0.04)))
                st[dirn] += int(bps * interval_s / 8)
                if bits == 32:
                    st[dirn] %= 2 ** 32
            st["up"] += interval_s * 100
            if name == "SYN-WAN-R2" and gap[0] <= k < gap[1]:
                continue
            tstr = _fmt(d)
            if mixed_formats and k % 997 == 0:
                tstr = d.strftime("%Y-%m-%dT%H:%M:%S")
            row = f"{tstr},{name},{ifc},{zone},{st['in']},{st['out']},{st['up']},{spd}"
            lines.append(row)
            if not dup_done and k == 500 and name == "SYN-ENT-SW1":
                lines.append(row)
                dup_done = True
                truth.append({"type": "duplicate_row", "device": name, "ts": tstr})
            if not bad_done and k == 700 and name == "SYN-ENT-SW1":
                lines.append(f"not-a-time,{name},{ifc},{zone},1,1,1,{spd}")
                bad_done = True
                truth.append({"type": "unparseable_timestamp_row", "device": name, "ts_raw": "not-a-time"})
    manifest = {"SYNTHETIC": True, "note": "fake data for testing only", "seed": seed, "days": days,
                "interval_s": interval_s, "tz": "UTC", "ground_truth": truth,
                "mapping_64bit": SYN_MAPPING, "mapping_32bit_wan": SYN_MAPPING32}
    return "\n".join(lines) + "\n", manifest


def synthetic_crs():
    """CR covering the injected WAN-R1 shift, plus a decoy CR on an unrelated device/time."""
    return {"format": "trafficlab-crs/1", "crs": [
        {"cr_id": "SYN-CR-1001", "title": "SYNTHETIC: WAN-R1 policy change", "description": "synthetic", "status": "Implemented",
         "owner": "synthetic", "risk": "Medium", "rollback_plan": "synthetic", "notes": "", "tz": "UTC",
         "planned_start_raw": "2026-01-27 05:00:00", "planned_end_raw": "2026-01-27 06:00:00",
         "actual_start_raw": "2026-01-27 05:05:00", "actual_end_raw": "2026-01-27 05:50:00",
         "scope": [{"device": "SYN-WAN-R1", "interface": ""}], "linked_findings": []},
        {"cr_id": "SYN-CR-1002", "title": "SYNTHETIC: decoy, other device", "description": "synthetic", "status": "Closed",
         "owner": "synthetic", "risk": "Low", "rollback_plan": "", "notes": "", "tz": "UTC",
         "planned_start_raw": "2026-01-03 01:00:00", "planned_end_raw": "2026-01-03 02:00:00",
         "scope": [{"device": "SYN-ENT-SW1", "interface": ""}], "linked_findings": []}]}


def write(outdir, **kw):
    import os
    os.makedirs(outdir, exist_ok=True)
    text, man = generate(**kw)
    p = os.path.join(outdir, "SYNTHETIC_traffic.csv")
    with open(p, "w", newline="") as f:
        f.write(text)
    with open(os.path.join(outdir, "SYNTHETIC_manifest.json"), "w") as f:
        json.dump(man, f, indent=1)
    with open(os.path.join(outdir, "SYNTHETIC_crs.json"), "w") as f:
        json.dump(synthetic_crs(), f, indent=1)
    return p


def generate_collector(days=35, interval_s=300, seed=7):
    """SYNTHETIC. Emits the exact CSV LAYOUT of nexus_collect.py report1_utilization.csv
    (header + 'x.xx Mbps' cells + '%-m/%-d/%Y %H:%M:%S' timestamps). Values are fake; IPs are RFC 5737 documentation range."""
    rnd = random.Random(seed)
    devs = [("SYN-DC-LEAF1", "192.0.2.11"), ("SYN-DC-LEAF2", "192.0.2.12")]
    n = days * 86400 // interval_s
    spike = (days * 86400 * 4 // 5 // interval_s, days * 86400 * 4 // 5 // interval_s + 6)
    lines = ["Hostname,IP_Address,Interface Name,Received Bandwidth,Receive Mbps,Transmit Bandwidth,Transmit Mbps,Timestamp"]
    for k in range(n):
        d = T0 + timedelta(seconds=k * interval_s)
        ts = f"{d.month}/{d.day}/{d.year} {d:%H:%M:%S}"
        f = _daily(d.hour + d.minute / 60, d.weekday() >= 5)
        if spike[0] <= k < spike[1]:
            f *= 3
        for name, ip in devs:
            rx = max(0.0, 3000 * f * (1 + rnd.gauss(0, 0.04)))
            tx = max(0.0, 1800 * f * (1 + rnd.gauss(0, 0.04)))
            lines.append(f"{name},{ip},Ethernet1/1,10000.00 Mbps,{rx:.2f} Mbps,10000.00 Mbps,{tx:.2f} Mbps,{ts}")
    return "\n".join(lines) + "\n", {"SYNTHETIC": True, "spike_start": _fmt(T0 + timedelta(seconds=spike[0] * interval_s)),
                                      "spike_end": _fmt(T0 + timedelta(seconds=(spike[1] - 1) * interval_s)), "devices": [x[0] for x in devs]}
