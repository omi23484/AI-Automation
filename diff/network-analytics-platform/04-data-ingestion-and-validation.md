# 04 — Data Ingestion, Validation & Upload Lifecycle

Ingestion is where NetPulse earns trust. If the platform silently accepts a bad file,
every verdict downstream is poisoned. The design goal: **be strict, be transparent,
and never destroy history.**

## 1. The source-agnostic ingestion architecture

```
   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │  XLSX     │   │  SNMP     │   │ Telemetry │   │ NetFlow  │  … (pluggable adapters)
   └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘
        └──────┬────────┴──────┬───────┴───────┬─────┘
               ▼               ▼               ▼
        ┌───────────────────────────────────────────┐
        │   Source Adapter Contract (normalizer)      │  → emits canonical Samples
        │   • parse  • map  • rate-convert  • flag    │     (tx_bps, rx_bps, util, …)
        └───────────────────────┬───────────────────┘
                                ▼
        ┌───────────────────────────────────────────┐
        │   Validation Pipeline (staging)             │  → ValidationReport
        └───────────────────────┬───────────────────┘
                                ▼
        ┌───────────────────────────────────────────┐
        │   Commit → immutable UploadBatch + facts    │  → triggers incremental analytics
        └─────────────────────────────────────────────┘
```

Every adapter implements the same contract, so **v1 ships only the XLSX adapter** and
future sources plug in behind the identical validation → commit → analytics path. The
dashboards never know or care which adapter produced the data.

### Adapter contract (what every source must provide)
- `discover()` → entities present (devices/interfaces) with identity hints.
- `parse(window)` → raw rows.
- `normalize(rows)` → canonical `Sample[]` (rates + utilization, quality flags).
- `describe()` → source metadata (type, native resolution, capabilities).

## 2. XLSX upload lifecycle (v1 primary flow)

```
Select file(s) → Upload → Detect & Map → Validate → Review → Commit → Post-process
```

### 2.1 Select & upload
- One or **multiple** `.xlsx` files per submission; each becomes its own batch.
- Large files stream to object storage; the **original is retained verbatim** forever
  (regulatory + reproducibility + re-parse if mapping improves later).
- Every upload is **timestamped** and attributed to the uploader (audit).

### 2.2 Detect & map (intelligent, schema-agnostic — **nothing is hardcoded**)
Column headers are **never assumed by position or exact name.** Different tools,
vendors, and analysts export wildly different spreadsheets — `TX`, `Tx (bps)`,
`Out-Octets`, `Egress Mbps`, `if_out`, `TxRate`, `Interface Out` may all mean the same
thing. NetPulse **understands the file, not a fixed template.**

**Header-understanding engine (semantic column resolver):**
- **Locate the header row** even when it isn't row 1 (title banners, blank rows, merged
  cells, multi-row headers are handled) by scoring candidate rows for header-likeness.
- **Resolve each column to a canonical field by *meaning*, using layered signals — not a
  hardcoded name list:**
  1. **Alias/lexical match** — a large, admin-**editable** synonym dictionary
     (`out`, `tx`, `egress`, `transmit`, `outbound`, `snd` → `tx_bps`; `in`, `rx`,
     `ingress`, `receive`, `inbound`, `rcv` → `rx_bps`; `speed`, `bw`, `bandwidth`,
     `capacity`, `if-speed`, `port speed` → `speed_bps`; `util`, `utilization`, `%`,
     `usage` → `util_pct`; `time`, `poll`, `timestamp`, `date`, `datetime`, `polled at`
     → `ts`). Case-, space-, punctuation-, and separator-insensitive; fuzzy (edit
     distance + token overlap) so `Utilisation` vs `Utilization` and abbreviations match.
  2. **Data-type & value-shape inference** — a column of parseable datetimes is the
     timestamp; a column of `%` values in 0–100 is utilization; large monotonically
     increasing integers are counters (bytes); values bounded by the speed column are
     rates. This catches columns whose *names* are unhelpful (`Column3`, vendor codes).
  3. **Unit tokens in the header** — `(Mbps)`, `Gb/s`, `kbit`, `%`, `bytes` both
     identify the field *and* set its unit (feeds §2.3).
  4. **Cross-column consistency** — the field assignment that makes utilization ≈
     rate/speed win; contradictory guesses are down-ranked.
- **Confidence per column**: each proposed mapping carries a confidence. High-confidence
  columns auto-map; low-confidence ones are surfaced for a **one-click confirm** in the
  mapping UI (with the top alternatives suggested). The user is never forced to map
  what the engine is already sure of, and never blocked when it's unsure.
- **Learned mapping profiles**: the confirmed mapping is saved as a reusable
  `column_mapping_profile` keyed by the file's structural signature (header fingerprint),
  so the *next* file from the same export tool maps automatically and silently.
- **Admin-extensible**: administrators can add aliases/units to the dictionaries in
  Admin (no code change), so a new export format is taught once and remembered.
- **Identity resolution**: device/interface columns are matched to existing entities
  (fuzzy on hostname/ifName/ifAlias); unknown ones are proposed as new entities for
  confirmation (prevents duplicate/sprawl entities).

### 2.3 Bandwidth & unit normalization engine (**Gbps / Mbps / Kbps / bytes all understood**)
Rates and speeds arrive in many units and NetPulse **normalizes everything to canonical
bits-per-second** before anything downstream sees it. No engine, chart, or verdict ever
deals with mixed units.

- **Unit detection**, in priority order:
  1. **Explicit unit in the header** — `Gbps`, `Gb/s`, `Gbit/s`, `Mbps`, `Mbit`, `Kbps`,
     `kb/s`, `bps`, `bit/s`, `Bps`/`B/s`/`bytes/s`, `GB`, `MB`, `KB`. Both **bit** and
     **byte** families are recognized (byte units are ×8 to bits).
  2. **Explicit unit in the cell** — values like `1.5 Gbps`, `800 Mbps`, `250000 kbps`
     are parsed (number + unit token) per-cell, so mixed-unit columns still normalize.
  3. **Inference from magnitude vs. interface speed** — when no unit is given, the value
     is reconciled against the (already-normalized) interface speed and the plausible
     utilization range to infer the scale (e.g., a "value" of `950` against a `1 Gbps`
     link is Mbps, not bps). Ambiguous cases are flagged, not guessed silently.
- **SI vs IEC**: network line rates are decimal SI (1 Gbps = 1,000 Mbps = 10⁹ bps);
  byte-based storage-style values default to the appropriate base with the assumption
  shown to the user and overridable.
- **Counters vs rates**: byte/packet **counters** (monotonic, e.g. `ifHCOutOctets`) are
  detected and converted to bit-rates via delta/interval with counter-wrap/reset
  handling; **rate** columns are used directly. Either way the output is `*_bps`.
- **Speed normalization**: interface speed strings — `1G`, `10G`, `100G`, `40GE`,
  `1000`, `10Gbps`, `1 Gigabit` — all resolve to `speed_bps` (effective-dated, doc 03
  §2.2), which is what utilization % is computed against.
- **Utilization**: recomputed as `rate_bps / speed_bps` from normalized values rather
  than trusting a possibly-stale supplied `%`; any discrepancy between supplied and
  computed util is surfaced as a data-quality finding (doc 04 §3.4).
- **Transparency**: the detected unit per column and any inference/assumption is shown
  in the mapping review and recorded on the batch, so normalization is auditable and
  reproducible.

### Example: the SAME data in three files, all handled without configuration
```
File A header:  Device | Port      | Time            | Tx (Gbps) | Rx (Gbps) | Speed
File B header:  host   | interface | poll_timestamp  | out_bps   | in_bps    | if_speed_mbps
File C header:  (row 4) NodeName | IfName | DateTime | Egress    | Ingress   | Bandwidth
                cells like "1.5 Gbps", "800 Mbps"
→ All three resolve to canonical: device, interface, ts, tx_bps, rx_bps, speed_bps, util_pct
```

### Expected canonical fields (typical XLSX — *illustrative, not required order/names*)
`Device, Interface, Poll Timestamp, TX, RX, Peak TX, Peak RX, Interface Speed,
Utilization %` → mapped **by meaning** to the canonical sample (doc 03 §3). Any subset,
order, naming, or unit is acceptable as long as the required fields are resolvable.

## 3. Validation pipeline (the trust layer)

Validation runs in **staging** before any commit. It produces a `ValidationReport`
with severity-graded findings. Nothing is committed until the user resolves/acknowledges
blocking issues.

### 3.1 Structural & schema validation
- Required fields present and typed; unmappable/extra columns surfaced.
- Timestamp parseable and timezone-resolved (per-site timezone from entity model; ask
  if ambiguous — a naïve local timestamp with no zone is a classic corruption source).
- Speed present or derivable; interfaces with unknown speed flagged (util % impossible).

### 3.2 Duplicate-upload detection
Three layers, escalating:
1. **File-identical:** checksum of the original matches a prior batch → hard warning
   "this exact file was uploaded on <date> by <user>."
2. **Content-overlap:** same `(interface, ts)` keys already present from another batch →
   surfaced as an overlap map with a resolution choice: *skip overlaps*, *keep both as
   separate sources*, or *supersede* (with reason, audited). **Never silent overwrite.**
3. **Near-duplicate:** same coverage window and row count but different checksum →
   flagged for human review (could be a re-export with corrections).

### 3.3 Polling-interval & gap analysis
- Infer the expected polling interval per interface (mode of inter-sample deltas).
- **Missing intervals:** buckets with no sample where one was expected → listed with
  count and span; classified as *gap-in-source* vs *device-down* if oper_status known.
- **Timestamp gaps:** contiguous stretches with no data → shown on a coverage ribbon so
  the user sees exactly what periods this batch does/doesn't cover.
- **Irregular cadence:** jitter beyond tolerance flagged (affects rate math and baselines).
- Gaps are **recorded, not fabricated.** Interpolation (if enabled) is explicit,
  bounded (only across short gaps), and every interpolated sample is `quality_flag =
  interpolated` so analytics can include/exclude it and charts can render it dashed.

### 3.4 Corrupt-value detection
- **Physically impossible:** util > 100% (beyond a small tolerance), negative rates,
  rate > speed, NaN/blank in required fields.
- **Counter anomalies (for counter sources):** negative deltas → counter wrap vs reset
  disambiguation; implausible spikes from missed wraps.
- **Statistical outliers:** values many σ outside the interface's own history flagged
  *suspect* (not auto-deleted — could be a real event; the human decides).
- **Speed/util mismatch:** supplied util % inconsistent with rate/speed → recompute and
  flag the discrepancy.

### 3.5 Maintenance overlap check
If the batch's time range intersects a defined maintenance window, it's surfaced so the
affected samples are tagged maintenance (excluded from alerts/SLA/trend per doc on
Maintenance Awareness) — caught at ingest, not after a false alarm fires.

## 4. Review & commit

The **Validation Console** (screen in doc 05) presents findings grouped by severity:

| Severity | Meaning | Commit behavior |
| --- | --- | --- |
| **Blocking** | Schema broken, no timestamps, no mappable interfaces. | Must fix/remap to proceed. |
| **Warning** | Duplicates, gaps, corrupt values, new entities. | Must acknowledge a resolution choice per item (skip/keep/supersede/create). |
| **Info** | Interpolation applied, cadence jitter, maintenance overlap. | Auto-recorded; visible. |

On **Commit**:
1. Immutable `UploadBatch` created; original file linked; provenance stamped on every
   sample.
2. Samples written to raw tier; rollups updated incrementally for touched
   interface/time buckets only.
3. Analytics re-run **incrementally** (only affected entities/windows): baselines,
   verdicts, anomalies, forecasts, risk (doc 08 §incremental).
4. Audit event recorded (who, when, what, validation summary).
5. Upload History updated with a human-readable "what changed" delta.

## 5. Upload History (append-only ledger)

Every batch is listed with: uploader, time, source, filename, checksum, coverage
window, row count, entities touched, validation summary, and resolution decisions.
From here a user can: view the validation report, download the original file,
see the coverage ribbon, and understand exactly how this batch altered analytics.
Batches can be **superseded** (with reason) but **never deleted silently**; a
supersede is itself an audited, reversible event.

## 6. Idempotency, ordering & late data

- Ingestion is **idempotent** on `(interface_id, ts, source_type)` — safe re-uploads.
- **Out-of-order / late data** (a backfilled older period) is accepted; affected
  rollups and any derived artifacts covering that window are recomputed and re-versioned.
- **Backfill vs. real-time** use the same path; only the trigger differs, which is what
  lets the platform move from batch Excel to streaming with no dashboard change.

## 7. Future-source readiness (no redesign required)

| Source | Adapter specifics handled at the edge (not downstream) |
| --- | --- |
| **SNMP** | Counter polling, 64-bit counters, wrap/reset detection, ifTable mapping, rate conversion. |
| **Cisco NX-API / NDFC / ACI** | REST/GRPC pulls, fabric/tenant → site/device mapping, per-fabric identity. |
| **SolarWinds** | SWIS/API export or DB read, node/interface → entity mapping. |
| **NetFlow/IPFIX** | Flow aggregation into interface-level rates + future per-conversation analytics. |
| **Streaming Telemetry (gNMI/gRPC)** | Push subscription, native rates, sub-minute cadence → same Sample. |
| **Prometheus** | PromQL range queries for `ifHCInOctets`-style series → normalized rates. |

Because all of these terminate in the identical `Sample` + `ValidationReport` +
`UploadBatch` contract, the **Verdict, Capacity, Anomaly, RCA, and dashboard layers
require zero changes** to gain a new source — the central promise of the architecture.
