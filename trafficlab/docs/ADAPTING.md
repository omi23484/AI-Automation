# Adapting trafficlab to an environment

trafficlab carries no customer-specific logic. Anything that differs per environment lives in a **profile**: one JSON file.
Anyone who can run Python 3.10+ on a machine that holds the data can use it. See "Sharing and access" below for what that does and does not mean.

## 1. Onboarding checklist (new environment)
1. Copy `profiles/example-neutral.json`, rename it, delete what you don't need (every key is optional).
2. **Zones**: `config.zone_map` (device-name globs -> zone). Precedence: data column > inventory CSV > `zone_map` > `unassigned`.
3. **Input shape**: either pick/define a **preset** (`presets` in the profile) or write a column **mapping** in `import.mapping` (see README "Input contract").
   Set `import.tz` and `import.ts_formats`. Slash dates are never guessed: the validation report shows a census that proves day-first or month-first, or says it cannot.
4. **Timestamps**: leave `ts_raw` alone (it is never modified). Declare the timezone only for strings without an offset.
5. **Thresholds**: start with defaults; tune globally in `config.*` and per zone in `config.zones.<ZONE>.*`. All defaults are the author's choices, not standards.
6. **Device checks**: `config.devcheck.group_map` (which devices belong to one network, so cross-device rules don't compare unrelated boxes), `rules` (disable or re-grade a rule),
   `waivers` (expected conditions; waived findings stay visible), `custom_parsers` / `custom_rules`.
7. **Weekly exports**: `config.weekly.aliases` (extra header names), `config.weekly.week_basis` (how the file-name stamp maps to a week); overrides per file are also possible.
8. Run, read the **validation report first**, then the findings. Re-run after each profile change; profiles are validated on load.

## 2. What a profile can contain
```json
{ "name": "", "description": "",
  "config":  { "tz": "UTC", "zone_map": [], "zones": {}, "counters": {}, "baseline": {}, "anomaly": {}, "changepoint": {}, "correlation": {},
               "weekly": {"aliases": {}, "week_basis": "stamp_period_ends"},
               "devcheck": {"groups": {}, "group_map": [], "rules": {}, "waivers": [], "custom_parsers": [], "custom_rules": []} },
  "import":  { "tz": "", "ts_formats": [], "delimiter": ",", "mapping": {}, "preset": "" },
  "presets": { "my-export": {"description": "", "ts_formats": [], "mapping": {}} } }
```
`config` accepts any key of `trafficlab/config.py::DEFAULTS` (comments there say what each does). A key that doesn't exist is an **error**, so typos can't silently do nothing.

## 3. Custom parsers and rules (declarative; no code)
Use these when a command or check you need is not built in. They are regexes and comparisons only: no `eval`, no scripts.

**Parser** (turns a command's output into rows):
```json
{ "name": "fans", "command_regex": "^show environment fan", "header_regex": "^Fan\\s+Model\\s+Hw", "stop_regex": "^Other table",
  "row_regex": "^(?P<fan>\\S+)\\s+(?P<model>\\S+)\\s+\\S+\\s+\\S+\\s+(?P<status>\\S+)\\s*$", "int_fields": [] }
```
- `command_regex` is matched (case-sensitive `re.search`) against the command text with whitespace collapsed. Custom parsers are tried before built-in ones.
- `row_regex` must have named groups; each match becomes a row `{fan, model, status, line, text}`. `line` is the line number in the original file (this is what evidence cites).
- Rows start after `header_regex` (if given) and end at `stop_regex`. Regex length limit 500; lines over 2000 characters are skipped (ReDoS guard).

**Rule** (flags rows):
```json
{ "id": "CFAN1", "name": "fan not Ok", "severity": "warning", "kind": "custom:fans",
  "when": {"field": "status", "op": "ne", "value": "Ok"}, "title": "fan {fan} is {status}", "detail": "model {model}", "device": "dc-*", "verify_on_device": false }
```
- `kind` is `custom:<parser name>` or a built-in kind (`log`, `bgp`, `ospf`, `bfd`, `hsrp`, `vpc`, `port_channel`, `counters_errors`, `if_status`, `stp_summary`, `clock`).
  Built-in row fields are documented by the parsers in `devcheck/parsers.py` (each row dict).
- `when` is one condition or a list (AND). Ops: `eq ne in not_in gt ge lt le contains not_contains regex not_regex`. Numeric ops need numeric fields (use `int_fields`).
- Titles/details accept only `{field}` placeholders. Ids must match `C[A-Za-z0-9_-]+` (built-ins use `DC`/`X`). At most `max_custom_findings` per rule per device; truncation is reported in the summary.
- Custom rules appear in the report's rule list and can be disabled or re-graded like built-ins. Evidence rows are generated automatically.

## 4. Weekly exports
- Header matching is by meaning; add names with `weekly.aliases` (valid targets: see `weekly.py::ALIASES`).
- `week_basis`: `stamp_period_ends` (stamp = end of the 7 days covered), `stamp_period_starts`, `stamp_week_contains` (ISO week containing the stamp).
  An ISO-week folder name (`2026-W23/`) or a per-file override beats the basis. The assignment is always listed in the validation report.

## 5. Intelligence features you configure
- **Signatures** (`config.signatures`): symptom-combination -> candidate cause. One `traffic` condition is the anchor; add `devcheck` / `cr` / `cluster` / `topology` conditions. Ships empty; see the three examples in `profiles/example-neutral.json` and `trafficlab/signatures.py` for the exact schema. Treat entries as hypotheses and mark `verify_on_device`.
- **Feedback** (`config.feedback`): `step` and `cap` control how much each distinct "false positive" mark raises that series' thresholds; `enabled: false` ignores marks.
- **Forecast** (`config.forecast`): history needed (`min_days` / `min_weeks`), thresholds (`thresholds_pct`), significance (`alpha`), horizon.
- **Topology**: run device checks on captures that include `show cdp neighbors detail` / `show lldp neighbors detail`; CLI `--captures PATH` or the Devices tab.
- **History**: CLI `history add|analyze|summary|retention --db FILE`, or the Import tab. Overlap consecutive chunks by at least one poll.
- **Local model** (`config.slm`): `enabled`, `endpoint` (an OpenAI-compatible chat-completions server on this machine), `model`, `max_pack_chars`. Off by default. The tool never starts or installs a model.

## 6. What still needs code
Output formats with no regex-able row structure (multi-line records, tree output), new counter arithmetic, periods other than 7 days in weekly mode, new statistical methods, and anything that needs topology.

## 7. Sharing and access
- The tool runs locally and binds to `127.0.0.1` only; there is **no authentication or roles**. Whoever can reach the machine's loopback can use it. Run one instance per user.
- Uploaded data is held in memory; the CR tracker writes a local SQLite file (`--db`). Treat that file and any exports as customer data.
- To share the tool, share the folder (code + a profile), not captures or databases. Keep raw captures out of version control (`captures/` is git-ignored).
- No licence file is included yet: the owner must choose one before redistribution.
