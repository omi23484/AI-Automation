# Tiers (small / medium / large)

**Decisions (owner):** a tier is defined by the **number of devices**; **capacity only** (every feature is in every tier); **soft enforcement is accepted**;
the upgrade path is simply a replacement tier file. The numbers in `trafficlab/tiers/*.json` are still **proposals** (flagged in the UI banner until you deliver with `--final`).

| tier | max devices (proposed) |
|---|---|
| small | 25 |
| medium | 150 |
| large | 500 |

## How it works
- A tier file: `{"name": "medium", "proposal": true, "limits": {"max_devices": 150}}`. (The schema can also express rows, series, zones, captures, CR count and feature switches; the shipped tiers use none of them, per the decisions.)
- Devices are counted over imported series, device-check captures and the **whole stored history**. Over the limit: a clear error naming the tier, the limit and the count; nothing is truncated or partly written.
- A bar under the tabs shows the tier and live usage. `python3 -m trafficlab tier list|show [NAME]` prints definitions.
- Resolution: `--tier NAME|PATH` > env `TRAFFICLAB_TIER` > `tier.json` beside the app/executable > tier baked into the executable > none.
- **Upgrade**: `python3 -m trafficlab tier install new-tier.json` (or just drop the file in as `tier.json` beside the program). It validates first, keeps the old file as `tier.json.bak`. Restart to apply.

## Technical safety caps (not commercial limits)
Independent of the tier, to prevent out-of-memory crashes: **3,000,000 rows per import/analysis, 50,000 captures, 100,000 series**. They come from measured behaviour (`tools/bench.py`: ~1.1 KB RAM and ~25 microseconds per row; 2.6M rows = 3 GB, ~66 s).

### The scaling point that "devices" alone hides
Rows = devices x monitored interfaces x polls. A 150-device customer polling **all 48 ports every 5 minutes** produces about 14.4M rows per week: over the cap. What fits (estimates):
| scenario | rows |
|---|---|
| 150 devices x 8 monitored uplinks x 5-min polls x 1 day | ~0.35M |
| same, 7 days | ~2.4M (near the cap) |
| 150 devices x 48 ports x 5-min polls x 1 day | ~2.1M |
So the practical advice for medium/large customers is: **monitor links that matter (uplinks, WAN, DC interconnects), not every access port**, and import **in chunks into the history store** (overlap chunks by one poll), analysing a window (e.g. the last 35 days). Anything beyond needs downsampling upstream or a streaming engine, which is not built.

## Delivering
- Single-file executable per OS: see `docs/PACKAGING.md` (`tools/build_exe.py --tier medium --final`).
- Folder bundle (needs Python on the customer machine): `python3 tools/make_bundle.py --tier medium --name acme --profile profiles/acme.json --final`.

## Soft enforcement, honestly
The tier file sits beside a plain program on the customer's machine: it can be edited or replaced. The software shows and enforces it so accidents are caught and scope is explicit; it is not a security control (accepted by the owner). If that changes, the options are a signed licence file (needs a third-party crypto package and a private key you protect), a licence server (breaks offline use), or contract terms.
