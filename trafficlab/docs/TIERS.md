# Tiers (small / medium / large)

The owner dictates the tiers. `tiers/small.json`, `medium.json`, `large.json` are **proposals** (`"proposal": true`, shown in the UI banner) built from measured performance. Edit the numbers, then deliver with `--final`.

## What a tier contains
```json
{ "name": "medium", "proposal": true,
  "limits":   { "max_devices": 150, "max_series": 5000, "max_rows": 1000000, "max_captures": 12000, "max_cr": 2000, "max_zones": 10 },
  "features": { "poll_mode": true, "weekly_mode": true, "devcheck": true, "custom_rules": true, "profiles": true, "report_export": true } }
```
`null` = unlimited. A missing feature = on. Unknown keys are rejected.

| limit | counted on | where checked |
|---|---|---|
| `max_rows` | CSV rows in one import | while reading (stops early, never truncates silently) |
| `max_devices` | distinct devices in the imported series / device-check captures | after parsing |
| `max_series` | device x interface x metric series | after parsing |
| `max_zones` | distinct zones (incl. `unassigned`) | after parsing |
| `max_captures` | per-command captures in one device-check run | before analysis |
| `max_cr` | change requests in the tracker | on create |

Features: `poll_mode` (poll-based CSV engine), `weekly_mode`, `devcheck`, `custom_rules` (custom parsers/rules), `profiles`, `report_export` (HTML/JSON exports).
Over a limit or a missing feature => a clear error naming the tier, the limit and the count. The UI shows the tier and live usage in a bar under the tabs.

## Proposed numbers (basis)
Measured on this project's benchmark (`tools/bench.py`, 4 cores, 16 GB sandbox, synthetic rows): about **1.1 KB RAM and 25 microseconds per row**. Measured: 864k rows = 1.0 GB, ~20 s; 2.6M rows = 3 GB, ~66 s.
| tier | rows | devices | series | est. RAM / time at the row limit |
|---|---|---|---|---|
| small | 200k | 25 | 500 | ~0.25 GB, ~5 s (extrapolated) |
| medium | 1M | 150 | 5,000 | ~1.1 GB, ~25 s (interpolated between measurements) |
| large | 3M | 500 | 20,000 | ~3.3 GB, ~75 s (slightly beyond the largest measured run) |
These are capacity numbers, not business terms. Price, support and SLA are yours. Beyond ~3M rows per import needs a streaming ingest, which is not built.

## Choosing and delivering
- Resolution order: `--tier NAME|PATH` > env `TRAFFICLAB_TIER` > `tier.json` next to the package > none (no limits; the UI says so).
- `python3 -m trafficlab tier list|show [NAME]` shows definitions.
- Build a customer bundle: `python3 tools/make_bundle.py --tier medium --name acme --profile profiles/acme.json --out dist --final`
  -> `dist/trafficlab-acme-medium.zip`: package, docs, `tier.json`, the profile, `README-FIRST.txt`, `MANIFEST.sha256`. No tests, tools, captures or databases. It refuses to ship an invalid profile.
- In the delivered folder: `python3 -m trafficlab verify` compares every file with the manifest.

## Honest limits of enforcement
This is **soft** enforcement. The tool is plain Python source on the customer's machine: anyone can edit `tier.json` or the code. The manifest check makes accidental or casual changes visible; it does not stop a determined user.
Stronger options, each with a cost: (a) a signed licence file verified with an asymmetric signature (needs a third-party crypto package, since Python's standard library has none, and a private key you must protect);
(b) a licence server (breaks the offline requirement); (c) contractual terms. Decide what the contract needs before choosing.

## Questions only the owner can answer
1. Which dimension defines the tier: devices, rows per import, or both? Are limits per import or cumulative?
2. Should smaller tiers lose features (e.g. `custom_rules`, `weekly_mode`, `report_export`) or only capacity?
3. Is soft enforcement acceptable, or is tamper resistance a requirement?
4. Upgrade path: how does a customer move small -> medium (new bundle, or a replacement `tier.json`)?
