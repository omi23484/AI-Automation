# trafficlab - offline traffic analysis

Offline, local-only tool for bandwidth pattern-shift detection, anomaly detection, CR tracking and
cross-device correlation across **Enterprise / WAN / DC** zones. Python 3.10+ standard library only
(developed and tested on 3.13). No network, no CDN, no telemetry, no AI in detection.

**Status:** traffic engine, CR tracker, device checks on raw `show` captures, weekly-export mode, capacity outlook, persisted history, analyst feedback,
CDP/LLDP topology context, an editable signature library, tiers, a single-file executable build (Linux verified; Windows via CI, not run by the author), and an
**optional** local-model explainer (off by default; tested only against a fake server). See `docs/INTELLIGENCE.md` for what is and is not "intelligent".

## Not tied to one customer: profiles
Everything environment-specific is a setting, not code: zones (`zone_map` globs, inventory CSV, data column), device groups for cross-device rules, thresholds (global and per
zone), per-rule enable/disable and severity, waivers, weekly-export header aliases and week-assignment basis, column mappings and presets, and **declarative custom parsers
and rules** (regex + comparisons, no code). One JSON **profile** bundles them (`--profile FILE`, or the Import tab). Unknown keys, bad regexes and bad rule ids are rejected.
Start from `profiles/example-neutral.json`; full guide: **[docs/ADAPTING.md](docs/ADAPTING.md)**.

## Delivering to a customer: tiers
Small / medium / large tiers are defined by **device count** (capacity only), as JSON files in `trafficlab/tiers/`; the numbers shipped are **proposals** for the owner to dictate. A tier banner shows limits and live usage;
over-limit input is refused with a clear message, never truncated. Single-file executable: **[docs/PACKAGING.md](docs/PACKAGING.md)**. Folder bundle: `tools/make_bundle.py`. Enforcement is soft (accepted). See **[docs/TIERS.md](docs/TIERS.md)**.
What the tool's "intelligence" is, and is not: **[docs/INTELLIGENCE.md](docs/INTELLIGENCE.md)**.

## Run (offline)

```bash
cd trafficlab
python3 -m trafficlab serve            # UI at http://127.0.0.1:8765/  (binds loopback only)
python3 -m trafficlab test             # 247 unit/integration tests
python3 -m trafficlab synth --out synthetic --mixed-formats     # FAKE data + ground-truth manifest
python3 -m trafficlab analyze FILE.csv --mapping map.json --tz UTC \
    --formats "%Y-%m-%d %H:%M:%S" [--inventory inv.csv] [--cr crs.json] [--config cfg.json] --out out
```
The UI has a **Load SYNTHETIC demo** button (fake data, ground truth printed) so you can try everything first.
It needs a browser only to view; `file://` is not used, so no `file://` worker/IndexedDB limits apply
(CRs live in SQLite `trafficlab.db`, not IndexedDB - decision: survives browser cache clears, easy backup).

## Input contract
Generic CSV, one row per (device, interface, poll). You map columns in a JSON mapping:
```json
{"device":"hostname","interface":"ifName","timestamp":"time","zone":null,
 "counters":[{"name":"in_bps","column":"ifHCInOctets","bits":64,"mult":8,"unit":"bps"}],
 "gauges":[], "uptime":{"column":"sysUpTime","unit":"cs"}, "speed":{"column":"ifHighSpeed","unit":"mbps"}}
```
Zone comes from a `zone` column, else an inventory CSV (`device,zone[,interface,speed_bps]`), else `unassigned`.
Column names above are examples; **map yours**. Units I am sure of: SNMP `sysUpTime` is TimeTicks (1/100 s) -> `cs`;
`ifHighSpeed` is Mbps. Everything else is whatever your export contains.

## Device checks (Module 4): `python3 -m trafficlab devcheck PATH --out DIR` (or Devices tab)
Input: a folder or `.zip` of raw `show` output, laid out `<pass>/<device>/<file>.txt` or `<device>/<file>.txt`. A file is one command (`COMMAND: show ...`
first line, else the command comes from a `show_*.txt` file name = less certain, flagged) or a session log with `host# show ...` prompts. Per device and
command the newest pass folder wins (`--pass-policy all` keeps every pass).
Parsers exist only for formats seen in real IOS-XE / NX-OS captures: interface error counters + status, etherchannel/port-channel, STP summary +
inconsistent ports, BGP summary, OSPF neighbors (table + detail), BFD, vPC brief, HSRP brief, logging, clock. Everything else is listed per device as
"not parsed"; commands the device rejected are listed as "rejected". 13 device rules (DC01-DC13) + 2 cross-device rules (X01-X02), each documented in
`devcheck/rules.py::RULES` and printed in the report. **Every finding carries evidence rows: device, command, line number in the original file, field, value, raw text.**
- Counters are cumulative snapshots: one capture cannot show whether an error counter is still rising.
- vPC/clock rules compare against healthy strings seen in captures (`peer adjacency formed ok`, `peer is alive`, `success`); other values are flagged "verify on device".
- Cross-device rules compare only inside a device group (`config.devcheck.groups`, default one group `all`). Unrelated lab boxes need separate groups.
- **Waivers are visible, never silent**: `config.devcheck.waivers` marks a finding `waived` with your reason; it stays in the output and is excluded from counts.
- Log timestamps stay raw. NX-OS lines carry a year; IOS-XE buffer lines often do not (no `ts_parsed` is invented). A leading `*` on IOS-XE times is reported (meaning: verify on device).
- Validated against the sanitized hardware-lab package: 14 devices / 2,279 captures -> 139 findings; a test checks that every evidence line number matches the source file.
  That package is NOT in this repo (set `TRAFFICLAB_LAB_FIXTURES=<extracted dir>` to run those tests). Committed tests use hand-written fixtures in the same formats.
- Lab devices are in a deliberately odd state (pushed config, no real neighbors): "BGP Idle" etc. are correct readings of the output, not necessarily faults. Use waivers.

## Weekly mode: `python3 -m trafficlab weekly FOLDER --tz Asia/Kolkata --out DIR` (or Import tab)
For aggregated weekly exports (`.xlsx` / `.csv`; one row per link per week: peak/average/utilisation). Stdlib xlsx reader; header columns matched by meaning
(`Node Name`, `Interface Name`, `Peak Receive`, `Average Transmit`, ...); every cell keeps its unit token (`1.06 Gbps`, `13.78 %`), header units apply only to unit-less cells.
- **The week is an assumption** unless an ISO-week folder name (`2026-W23/`) or an explicit override is given: the file-name stamp is taken as the generation time and the
  covered period as the 7 days before it ("Last 7 Days"). Each file's basis is listed. Missing weeks = marked gaps; conflicting duplicates are excluded.
- Detection: week-level robust z vs the previous 8 observed weeks (needs >= 6) and level shifts by binary segmentation (needs >= 8 weeks, shift must move the segment **medians** too,
  so one outlier week is not reported as a shift). Same finding schema, charts, CR overlay, correlation and report as the poll-based mode.
- Cannot see anything inside a week (spikes, outages shorter than a week), has no yearly seasonality, and a gradual ramp can show as several small steps.
- Utilisation-% columns that duplicate an analysed average-bps series are not analysed twice. Supplied % is cross-checked against average/speed.
- Checked on the `weekly-dashboard` repo's "field-shape" workbooks (26 weeks, 150 series). Those are generated by that repo, not real traffic.

## Example presets (optional; add your own in a profile)
`python3 -m trafficlab analyze FILE --preset nexus_collect_utilization --tz <your tz>` (also `nexus_collect_errors`; UI has a preset dropdown).
Layout comes from a collector script's CSV writer (see `presets.py`): cells like `12.34 Mbps`,
timestamps `%-m/%-d/%Y %H:%M:%S` (month-first, non-padded, collector's local clock). **Layout only - not validated against a real device.**
- Rate cells with unit tokens are parsed to bits/s (`units.py`): `bps/Kbps/Mbps/Gbps/Tbps`; lower-case `b` = bit, upper-case `B` = byte (x8). No unit token => mapping's `default_unit`, else the cell is flagged. Never inferred from magnitude.
- Slash dates (`01/08/2026`): **census proof** over the whole file (first part >12 proves day-first, second >12 proves month-first). Contradicting your declared format = error; undecidable = warning; mixed = error. Undeclared slash dates are not parsed, and the report says why.
- Collector rates are the device's own load-interval average (a smoothed sample, not a counter delta). Peaks inside the interval are lost and samples closer than the averaging window overlap.
- Error/discard presets declare 32-bit counters because the real width is unknown: a decrease with no uptime is excluded, never guessed.

## Data integrity (enforced + tested)
- `ts_raw` stored exactly; `ts_parsed` is separate: `{epoch_ms, format, tz_assumed, tz_source, flags}`. Raw rows are frozen dataclasses.
- Unparseable, DST-ambiguous, DST-nonexistent timestamps are **flagged and excluded, never guessed or silently dropped**.
- Slash dates (dd/mm vs mm/dd) are never auto-tried; epoch only if declared.
- Gaps are marked `excluded` intervals; nothing is interpolated. Duplicates (identical) and conflicts (same ts, different values) reported.
- Rates record their method per point: `delta`, `wrap32_uptime_confirmed`, `wrap32_plausible`, `wrap32_unverified`, `gauge_as_given`.
  Decrease handling: uptime drop => reset (no rate); 32-bit + no reload => wrap, checked against line speed when known;
  64-bit decrease => reset assumed (no rate); ambiguous => excluded.
- Memory trade-off: full raw cell tuples are kept only for flagged rows (`keep_cells=False`); `ts_raw/device/interface` always exact. Source file remains the full raw record.

## Engine (deterministic; `trafficlab/{anomaly,changepoint,correlate}.py`)
| Piece | Method | Default (author's choice, not a standard) |
|---|---|---|
| Baseline | causal median/MAD of same weekday+hour, prior 4 weeks; fallback weekday/weekend+hour over 28 d | need >=3 prior weeks / >=4 prior same-daytype days, else **insufficient history** (no score). Hour-only tier exists but is OFF (pools weekday+weekend => false alarms) |
| Anomaly 1 | robust z = (x-median)/max(1.4826*MAD, 5%*median, abs floor) | \|z\|>=4 for >=3 consecutive points |
| Anomaly 2 | EWMA control chart on that z (lambda 0.2, clipped), small sustained shifts | limit 4*sqrt(l/(2-l)); approx., autocorrelation ignored |
| Pattern shift | hourly mean - seasonal profile, binary segmentation, AR(1)-adjusted t | t>=6 and effect >=1 sigma and >=5%; refuses if span < 5 d; shift time resolution **1 h** |
| Correlation | union-find on overlapping windows (+/-300 s) + Pearson r of baseline residuals on common grid | "shared-cause candidate" if >=2 devices, mean r>=0.5, same direction |
Findings carry id, metric, device/interface/zone, window (raw + parsed), severity, exact formula + params, numbers, confidence + justification.
`layer` marks **statistical** vs **interpretation**. Interpretation = 6 documented rules (`interpret.RULES`); no evidence => `Unknown - insufficient evidence`.
Per-zone overrides: `config.zones = {"WAN": {"anomaly": {"z_threshold": 5}}, "DC": {"tz": "Europe/London"}}`.

## CR tracker
SQLite; fields per spec + scope (device[/interface]) + change log (field, old, new, actor, utc). Windows entered as raw text, parsed with the
same rules. Export/import JSON (`trafficlab-crs/1`; import re-parses from raw strings). Candidates = scope match AND (window overlaps OR finding starts
<= 24 h after CR end); shifts matched with +/-1 h uncertainty. Always labelled "candidate correlation, not proven cause". CR windows are drawn on charts.

## Measured performance (this repo's sandbox: 4 cores, 16 GB; synthetic rows, `tools/bench.py`)
| rows | ingest | series build | analyze (4 procs) | peak RSS main proc |
|---|---|---|---|---|
| 173k | 2.2 s | 1.2 s | 0.5 s | 0.36 GB |
| 864k | 11 s | 7.5 s | 2.0 s | 1.0 GB |
| 2.59M | 34 s | 27 s | 5.1 s | 3.0 GB |
~1.1 KB RAM/row (measured), so **~5M rows = ~6 GB (extrapolated, not measured)**. Your scale was not given: 100 devices x 48 ifaces x 5 min x 30 d = 41M rows
would NOT fit. For that, split by zone/time window or downsample upstream. A streaming ingest is not built.
Heavy compute runs in a process pool (the Python equivalent of web workers); the UI stays responsive (job polling).

## Dependencies
Runtime: Python standard library only (`http.server`, `sqlite3`, `csv`, `zoneinfo`, `concurrent.futures`). `zoneinfo` needs system tzdata for non-UTC zones.
UI: hand-written JS/canvas, nothing vendored. Dev/test: stdlib `unittest` (numpy used in ONE optional test if installed). No third-party license obligations.

## Security notes
Loopback bind only (refuses others); Host-header check (DNS-rebinding); POST requires `application/json` + same-origin (CSRF); CSP `default-src 'self'`;
no file-path or shell endpoints; UI never uses innerHTML for data. No auth: anyone on the same machine can reach the port.

## Not built / known limitations
- Phase 2 parsers cover only the commands listed above. Interface counters are never turned into rates (captures carry no collection time). NX-OS OSPF/BFD tables were not seen populated.
- No SLM (Phase 3). The Explain tab is deterministic and shows the evidence pack an SLM would be allowed to see.
- No topology: "shared cause" ignores whether devices are actually adjacent. Clock skew between devices not measured.
- Speed = last non-empty speed seen for the series (link upgrades mid-series not handled). `sysUpTime` 497-day TimeTicks wrap treated as reload (excluded, safe side).
- Hour-bucket DST fall-back merges the repeated local hour. Public holidays not modelled. 32-bit counters at high speed can wrap >1x per interval (warned, unrecoverable).
- A sustained level shift makes the causal baseline flag the new level for weeks; those are tagged `continuation_of` (R6) and hidden by default, not deleted.
- Thresholds are heuristics, not calibrated false-alarm rates. Open CR (actual start, no end) is matched as a point.
- Synthetic-data results prove the code finds what it was told to inject; they say nothing about accuracy on your traffic.
