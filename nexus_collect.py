#!/usr/bin/env python3
"""
nexus_collect.py — Cisco Nexus read-only telemetry collector
============================================================

Collects, from one or more Cisco Nexus (NX-OS) switches, the three datasets the
"Nexus Buffer / Traffic / Discard / Multicast Forensic Console" HTML tool consumes,
then bundles them into a single ZIP you can drop straight into the tool's Import page.

  1. Utilization / link time-series   -> report1_utilization.csv
  2. Errors / discards (cumulative)    -> report2_errors_discards.csv
  3. Multicast mapping                 -> report3_multicast.csv

SAFETY
------
* READ-ONLY. The script issues ONLY `show` commands. It never enters config mode,
  never writes to the device, and refuses any command that is not a `show`.
* Credentials are asked ONCE and reused for every device. The password is read with
  getpass (not echoed) and is never written to disk or into the ZIP.

Show commands used (per device):
    show hostname
    show interface
    show cdp neighbors detail        (best-effort, to enrich peer/description/MAC)
    show ip igmp snooping groups     (multicast group -> interface mapping)

Multicast: link-local / "local" groups (224.0.0.0/24 by default) are ignored.

Requires: netmiko  ->  pip install netmiko
Usage examples:
    python3 nexus_collect.py                         # fully interactive
    python3 nexus_collect.py --devices devices.txt
    python3 nexus_collect.py --devices 10.6.2.60,10.6.2.61 --samples 6 --interval 60
    python3 nexus_collect.py --serve 8080            # also serve the ZIP for browser download
"""

import argparse
import csv
import datetime as dt
import getpass
import io
import ipaddress
import os
import re
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
except Exception:  # pragma: no cover
    sys.stderr.write(
        "\nThis script needs the 'netmiko' library.\n"
        "Install it with:  pip install netmiko\n\n"
    )
    sys.exit(2)

DEFAULT_IGNORE_MCAST = ["224.0.0.0/24"]   # link-local control block ("local" multicast)

# A hard allow-list guard: every command sent to a device MUST start with 'show'.
def _guard_show(cmd: str) -> str:
    if not cmd.strip().lower().startswith("show"):
        raise ValueError("Refused non-show command: %r" % cmd)
    return cmd


# ---------------------------------------------------------------------------
# Parsing helpers  (pure functions -> easy to unit test)
# ---------------------------------------------------------------------------
def parse_show_interface(text):
    """
    Parse NX-OS 'show interface' output into a list of per-interface dicts:
      { iface, description, bw_mbps, rx_mbps, tx_mbps,
        rx_discards, rx_errors, tx_discards, tx_errors }
    Rates are the device's own load-interval average (point-in-time sample).
    Discard/error counters are cumulative (the HTML tool computes deltas).
    """
    results = []
    # Split into per-interface blocks. A block header looks like:
    #   Ethernet1/1 is up      /  Ethernet1/7 is down
    blocks = re.split(r"(?m)^(?=\S+\s+is\s+(?:up|down))", text)
    for blk in blocks:
        m = re.match(r"^(\S+)\s+is\s+(up|down)", blk)
        if not m:
            continue
        name = m.group(1)
        # only physical Ethernet ports (buffer-block model is per physical port)
        if not re.match(r"(?i)^Ethernet\d+/\d+", name):
            continue

        def find(pat, default=None, grp=1):
            mm = re.search(pat, blk)
            return mm.group(grp) if mm else default

        desc = find(r"(?im)^\s*Description:\s*(.+?)\s*$")
        bw_kbit = find(r"BW\s+(\d+)\s+Kbit")
        in_rate = find(r"input rate\s+(\d+)\s+bits/sec")
        out_rate = find(r"output rate\s+(\d+)\s+bits/sec")
        in_err = find(r"(\d+)\s+input error")
        in_disc = find(r"(\d+)\s+input discard")
        out_err = find(r"(\d+)\s+output error")
        out_disc = find(r"(\d+)\s+output discard")

        bw_mbps = (int(bw_kbit) / 1000.0) if bw_kbit else None
        results.append({
            "iface": name,
            "description": desc,
            "bw_mbps": bw_mbps,
            "rx_mbps": (int(in_rate) / 1_000_000.0) if in_rate is not None else None,
            "tx_mbps": (int(out_rate) / 1_000_000.0) if out_rate is not None else None,
            "rx_discards": int(in_disc) if in_disc is not None else None,
            "rx_errors": int(in_err) if in_err is not None else None,
            "tx_discards": int(out_disc) if out_disc is not None else None,
            "tx_errors": int(out_err) if out_err is not None else None,
        })
    return results


def parse_cdp_detail(text):
    """
    Parse 'show cdp neighbors detail' into {local_iface: {peer, peer_ip, peer_iface}}.
    Best-effort; used only to enrich the discard report's "Full Name" column.
    """
    neigh = {}
    for blk in re.split(r"-{4,}", text):
        dev = re.search(r"(?im)^Device ID:\s*(\S+)", blk)
        # local interface + remote port on the same line
        li = re.search(r"(?im)Interface:\s*([A-Za-z0-9/\.]+)\s*,\s*Port ID \(outgoing port\):\s*([A-Za-z0-9/\.]+)", blk)
        ip = re.search(r"(?im)IPv4 Address:\s*(\d+\.\d+\.\d+\.\d+)", blk) or \
             re.search(r"(?im)IP address:\s*(\d+\.\d+\.\d+\.\d+)", blk)
        if dev and li:
            local = _canon_iface(li.group(1))
            neigh[local] = {
                "peer": dev.group(1).split("(")[0],
                "peer_ip": ip.group(1) if ip else None,
                "peer_iface": li.group(2),
            }
    return neigh


def parse_igmp_snooping_groups(text):
    """
    Parse 'show ip igmp snooping groups' into a list of (vlan, group, iface) tuples.
    Tolerant of column variations: a data line has a leading VLAN id, an IPv4 group,
    and one or more Eth interfaces which we extract individually.
    """
    rows = []
    for line in text.splitlines():
        gm = re.search(r"\b(\d+\.\d+\.\d+\.\d+)\b", line)
        vm = re.match(r"\s*(\d+)\b", line)
        if not gm or not vm:
            continue
        group = gm.group(1)
        vlan = vm.group(1)
        ports = re.findall(r"(?i)\b(?:Eth|Ethernet)\d+/\d+(?:/\d+)?\b", line)
        for p in ports:
            rows.append((vlan, group, _canon_iface(p)))
    return rows


def _canon_iface(name):
    """Eth1/1 -> Ethernet1/1 (matches the HTML tool's normalization)."""
    m = re.match(r"(?i)(?:eth(?:ernet)?)\s*(\d+/\d+(?:/\d+)?)", name)
    return "Ethernet" + m.group(1) if m else name


def _short_host(name):
    """Strip a DNS domain so the hostname matches SolarWinds' short names.
    'PJT-EDX-ORD-LF9.BSELTD' -> 'PJT-EDX-ORD-LF9'. IPs are left intact."""
    if not name:
        return name
    name = name.strip()
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", name):   # IPv4 -> keep
        return name
    first = name.split(".")[0]
    return first if re.search(r"[A-Za-z]", first) else name


def is_ignored_mcast(group, ignore_nets):
    try:
        addr = ipaddress.ip_address(group)
    except ValueError:
        return False
    return any(addr in net for net in ignore_nets)


def build_full_name(host, iface, description, cdp):
    """Compose the discard report 'Full Name' the way the source reports do."""
    base = "%s - %s" % (host, iface)
    n = cdp.get(iface)
    if n and n.get("peer"):
        extra = " · Connected to %s" % n["peer"]
        if n.get("peer_ip"):
            extra += " | IP:%s" % n["peer_ip"]
        if n.get("peer_iface"):
            extra += " | Interface:%s" % n["peer_iface"]
        return base + extra
    if description:
        d = description.strip()
        if "***" in d or "|" in d:      # already formatted like the source reports
            return "%s | %s" % (base, d)
        return "%s | *** %s ***" % (base, d)
    return base


# ---------------------------------------------------------------------------
# Per-device collection
# ---------------------------------------------------------------------------
def collect_device(ip, username, password, secret, timeout, samples, interval, verbose):
    """Connect (SSH), run show commands, return parsed data. Read-only."""
    device = {
        "device_type": "cisco_nxos",
        "host": ip,
        "username": username,
        "password": password,
        "secret": secret or "",
        "fast_cli": False,
        "conn_timeout": timeout,
        "read_timeout_override": max(30, timeout),
    }
    out = {"ip": ip, "hostname": ip, "iface_samples": [], "cdp": {}, "mcast": [], "error": None}
    try:
        conn = ConnectHandler(**device)
    except NetmikoAuthenticationException:
        out["error"] = "authentication failed"
        return out
    except NetmikoTimeoutException:
        out["error"] = "connection timed out / unreachable"
        return out
    except Exception as e:
        out["error"] = "connect error: %s" % e
        return out

    try:
        try:
            hn = conn.send_command(_guard_show("show hostname")).strip().splitlines()
            if hn:
                out["hostname"] = _short_host(hn[-1].strip())
        except Exception:
            out["hostname"] = _short_host(conn.base_prompt or ip)

        # multicast + neighbors: once per device
        try:
            out["cdp"] = parse_cdp_detail(conn.send_command(_guard_show("show cdp neighbors detail")))
        except Exception:
            out["cdp"] = {}
        try:
            out["mcast"] = parse_igmp_snooping_groups(conn.send_command(_guard_show("show ip igmp snooping groups")))
        except Exception:
            out["mcast"] = []

        # interface stats: N samples spaced by `interval` seconds -> time series
        for s in range(samples):
            ts = dt.datetime.now()
            raw = conn.send_command(_guard_show("show interface"))
            out["iface_samples"].append((ts, parse_show_interface(raw)))
            if verbose:
                print("  [%s] sample %d/%d: %d interfaces" %
                      (out["hostname"], s + 1, samples, len(out["iface_samples"][-1][1])))
            if s < samples - 1:
                time.sleep(interval)
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# CSV / ZIP assembly
# ---------------------------------------------------------------------------
def ts_str(t):
    return t.strftime("%-m/%-d/%Y %H:%M:%S") if os.name != "nt" else t.strftime("%#m/%#d/%Y %H:%M:%S")


def build_reports(collected, ignore_nets):
    util = io.StringIO(); disc = io.StringIO(); mc = io.StringIO()
    uw = csv.writer(util); dw = csv.writer(disc); mw = csv.writer(mc)
    uw.writerow(["Hostname", "IP_Address", "Interface Name", "Received Bandwidth",
                 "Receive Mbps", "Transmit Bandwidth", "Transmit Mbps", "Timestamp"])
    dw.writerow(["Caption", "IP_Address", "Interface Name", "Full Name", "Received Discards",
                 "Received Errors", "Transmit Discards", "Transmit Errors", "Timestamp"])
    mw.writerow(["Switch", "Interface", "Multicast Group", "VLAN", "Description", "Feed", "Role"])

    for d in collected:
        if d.get("error"):
            continue
        host, ip, cdp = d["hostname"], d["ip"], d["cdp"]
        for ts, ifaces in d["iface_samples"]:
            when = ts_str(ts)
            for r in ifaces:
                bw = ("%.2f Mbps" % r["bw_mbps"]) if r["bw_mbps"] is not None else ""
                uw.writerow([host, ip, r["iface"], bw,
                             ("%.2f Mbps" % r["rx_mbps"]) if r["rx_mbps"] is not None else "",
                             bw,
                             ("%.2f Mbps" % r["tx_mbps"]) if r["tx_mbps"] is not None else "",
                             when])
                dw.writerow([host, ip, r["iface"], build_full_name(host, r["iface"], r["description"], cdp),
                             _blank(r["rx_discards"]), _blank(r["rx_errors"]),
                             _blank(r["tx_discards"]), _blank(r["tx_errors"]), when])
        seen = set()
        for vlan, group, iface in d["mcast"]:
            if is_ignored_mcast(group, ignore_nets):
                continue
            key = (iface, group, vlan)
            if key in seen:
                continue
            seen.add(key)
            desc = ""
            n = cdp.get(iface)
            if n and n.get("peer"):
                desc = n["peer"]
            mw.writerow([host, iface, group, vlan, desc, "", ""])
    return util.getvalue(), disc.getvalue(), mc.getvalue()


def _blank(v):
    return "" if v is None else v


def write_zip(util_csv, disc_csv, mc_csv, errors, outdir):
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(outdir, "nexus_reports_%s.zip" % stamp)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report1_utilization.csv", util_csv)
        z.writestr("report2_errors_discards.csv", disc_csv)
        z.writestr("report3_multicast.csv", mc_csv)
        if errors:
            z.writestr("collection_errors.txt", errors)
        z.writestr("README.txt",
                   "Generated by nexus_collect.py (read-only show commands).\n"
                   "Import report1/report2/report3 into the Nexus Forensic Console.\n"
                   "Local multicast groups were filtered out.\n")
    return path


# ---------------------------------------------------------------------------
# Input gathering
# ---------------------------------------------------------------------------
def gather_targets(args):
    if args.devices:
        raw = args.devices
        if os.path.isfile(raw):
            with open(raw) as f:
                items = f.read()
        else:
            items = raw
    else:
        print("Enter device IPs/hostnames (comma, space or newline separated).")
        print("Finish with an empty line:")
        lines = []
        while True:
            try:
                ln = input()
            except EOFError:
                break
            if ln.strip() == "":
                break
            lines.append(ln)
        items = "\n".join(lines)
    targets = [t.strip() for t in re.split(r"[\s,;]+", items) if t.strip()]
    # de-duplicate preserving order
    seen, uniq = set(), []
    for t in targets:
        if t not in seen:
            seen.add(t); uniq.append(t)
    return uniq


def serve_file(path, port):
    import http.server, socketserver, urllib.parse
    directory = os.path.dirname(os.path.abspath(path))
    fname = os.path.basename(path)
    os.chdir(directory)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
        url = "http://<this-host>:%d/%s" % (port, urllib.parse.quote(fname))
        print("\nServing ZIP for download at: %s" % url)
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Read-only Cisco Nexus collector for the Forensic Console.")
    ap.add_argument("--devices", help="Comma/space list of IPs, or a path to a file (one per line). "
                                       "If omitted, you'll be prompted.")
    ap.add_argument("--username", help="SSH username (prompted once if omitted).")
    ap.add_argument("--samples", type=int, default=1, help="Interface poll samples per device (default 1).")
    ap.add_argument("--interval", type=int, default=60, help="Seconds between samples (default 60).")
    ap.add_argument("--workers", type=int, default=8, help="Concurrent device connections (default 8).")
    ap.add_argument("--timeout", type=int, default=30, help="Per-device connect/read timeout seconds (default 30).")
    ap.add_argument("--secret", action="store_true", help="Prompt for an enable secret as well.")
    ap.add_argument("--ignore-mcast", default=",".join(DEFAULT_IGNORE_MCAST),
                    help="Comma-separated multicast networks to ignore (default 224.0.0.0/24).")
    ap.add_argument("--outdir", default=".", help="Directory to write the ZIP (default current dir).")
    ap.add_argument("--serve", type=int, metavar="PORT",
                    help="After collecting, serve the ZIP over HTTP on PORT for browser download.")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    targets = gather_targets(args)
    if not targets:
        print("No devices provided. Exiting.")
        return 1
    ignore_nets = [ipaddress.ip_network(c.strip()) for c in args.ignore_mcast.split(",") if c.strip()]

    username = args.username or input("Username: ").strip()
    password = getpass.getpass("Password: ")
    secret = getpass.getpass("Enable secret: ") if args.secret else ""

    print("\nCollecting from %d device(s), %d sample(s) each (read-only show commands)...\n"
          % (len(targets), args.samples))

    collected = []
    with ThreadPoolExecutor(max_workers=min(args.workers, len(targets))) as ex:
        futs = {ex.submit(collect_device, ip, username, password, secret,
                          args.timeout, args.samples, args.interval, args.verbose): ip
                for ip in targets}
        for fut in as_completed(futs):
            ip = futs[fut]
            try:
                d = fut.result()
            except Exception as e:
                d = {"ip": ip, "hostname": ip, "iface_samples": [], "cdp": {}, "mcast": [],
                     "error": "unexpected: %s" % e}
            collected.append(d)
            status = "FAILED: %s" % d["error"] if d.get("error") else \
                     "ok (%d iface rows, %d mcast rows)" % (
                         sum(len(s[1]) for s in d["iface_samples"]), len(d["mcast"]))
            print("  %-18s %s -> %s" % (ip, d["hostname"], status))

    ok = [d for d in collected if not d.get("error")]
    fails = [d for d in collected if d.get("error")]
    if not ok:
        print("\nNo devices collected successfully. Nothing to bundle.")
        return 1

    util_csv, disc_csv, mc_csv = build_reports(collected, ignore_nets)
    err_txt = "\n".join("%s (%s): %s" % (d["ip"], d["hostname"], d["error"]) for d in fails)
    zip_path = write_zip(util_csv, disc_csv, mc_csv, err_txt, args.outdir)
    zip_path = os.path.abspath(zip_path)

    print("\n=========================================================")
    print(" Collected: %d ok, %d failed" % (len(ok), len(fails)))
    print(" ZIP written: %s" % zip_path)
    print(" Import report1/2/3 CSVs into the Nexus Forensic Console.")
    print("=========================================================")

    if args.serve:
        serve_file(zip_path, args.serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
