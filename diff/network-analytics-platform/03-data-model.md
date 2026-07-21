# 03 — Data Model

The data model has one job above all others: **decouple the dashboards and analytics
from the data source.** Excel today, streaming telemetry tomorrow — everything lands
in the same canonical entity + time-series model, so nothing downstream changes.

## 1. Modeling principles

1. **Entities vs. facts.** Slowly-changing *entities* (sites, devices, interfaces)
   live in a relational/graph model. High-volume *facts* (polls) live in a
   time-series store. They are joined by stable IDs.
2. **Append-only facts.** Poll samples and derived analytics are never mutated in
   place. Corrections arrive as new versioned records.
3. **Everything is versioned and sourced.** Every record carries `source_type`,
   `upload_batch_id`, and ingest timestamps so any number can be traced to its origin.
4. **Rollups are first-class.** Raw samples plus pre-aggregated 5m/1h/1d rollups
   coexist; queries pick the coarsest resolution that answers the question.
5. **Logical overlays.** Customers, services, and classes are overlays on the physical
   topology, not baked into it — one interface can belong to a customer *and* a class
   *and* a service.

## 2. Core entity model (physical topology)

```
Organization
  └─ Site (LON-DC1)            geo, region, timezone, business tier
       └─ Room / Hall          floor, cooling zone
            └─ Rack             row, position, U-height
                 └─ Device      hostname, vendor, model, role, mgmt IP, serial
                      └─ LineCard / Module   slot, model
                           └─ Interface      the atomic monitored unit
```

### 2.1 Interface (the atomic entity — the heart of the model)

| Field | Type | Notes |
| --- | --- | --- |
| `interface_id` | UUID | Stable internal ID (never the SNMP ifIndex, which can renumber). |
| `device_id` | FK | Parent device. |
| `line_card_id` | FK (nullable) | Parent module if modeled. |
| `name` | string | e.g. `Ethernet1/2`, `HundredGigE0/0/0/3`. |
| `alias` / `description` | string | ifAlias / configured description. |
| `if_index` | int (nullable) | Source ifIndex, kept for correlation, not identity. |
| `speed_bps` | bigint | Administrative/negotiated speed; historized (see 2.2). |
| `admin_status` / `oper_status` | enum | up/down/testing. |
| `class` | enum[] | Core, Trading, Internet, WAN, Storage, Backup, Voice, Replication, Management, Customer (multi-tag allowed). |
| `business_impact` | enum | Critical / High / Medium / Low. |
| `customer_id` | FK (nullable) | Logical owner. |
| `service_id` | FK (nullable) | Logical service. |
| `tags` | string[] | Free-form. |
| `first_seen` / `last_seen` | ts | Lifecycle. |
| `state` | enum | active / decommissioned / provisional. |

### 2.2 Historized attributes
Speed, description, class, and business impact **change over time** and analytics must
respect the value *as of* the sample. These are stored as effective-dated rows:
`(interface_id, attribute, value, valid_from, valid_to)`. A link upgraded from 10G→100G
must not corrupt historical utilization %.

## 3. Time-series fact model (poll samples)

The canonical sample — every source is normalized into this shape.

| Field | Type | Notes |
| --- | --- | --- |
| `interface_id` | FK | Join to entity. |
| `ts` | timestamptz | Poll timestamp (source of truth for ordering). |
| `tx_bps` | double | Egress bits/sec (rate, normalized — see note). |
| `rx_bps` | double | Ingress bits/sec. |
| `peak_tx_bps` | double (nullable) | Peak within interval, if provided. |
| `peak_rx_bps` | double (nullable) | Peak within interval. |
| `speed_bps` | bigint | Speed effective at `ts` (denormalized for fast %). |
| `util_tx_pct` | double | `tx_bps / speed_bps` (derived, stored). |
| `util_rx_pct` | double | `rx_bps / speed_bps`. |
| `util_pct` | double | `max(util_tx, util_rx)` — the headline utilization. |
| `errors` / `discards` | double (nullable) | If present in source. |
| `source_type` | enum | xlsx / snmp / telemetry / ndfc / aci / solarwinds / netflow / prometheus. |
| `upload_batch_id` | FK | Provenance → immutable batch. |
| `quality_flags` | bitmask | interpolated / suspect / gap-adjacent / corrected. |

**Normalization note.** Sources deliver different primitives: SNMP delivers
monotonically increasing byte *counters* (must be rate-converted with delta/time and
counter-wrap handling); telemetry and many Excel exports deliver *rates* directly;
some deliver only utilization %. The ingestion adapter's contract is to always emit
`tx_bps`/`rx_bps` **rates** and `util_pct`, filling what it can and flagging what it
can't. Downstream code only ever sees rates and percentages.

### 3.1 Storage tiers for facts
| Tier | Resolution | Retention (default, configurable) | Use |
| --- | --- | --- | --- |
| Raw | native (e.g. 1–5 min) | 90 days hot | RCA, precise timelines, anomaly detail. |
| Rollup 5m | 5 min | 13 months | Interface/device charts, baselines. |
| Rollup 1h | 1 hour | 3 years | Trends, capacity, calendar heatmaps. |
| Rollup 1d | 1 day | indefinite | Long-range forecasting, executive trends. |

Each rollup bucket stores `avg`, `max`, `p95`, `p99`, `min`, `sample_count`, and
`state_time_breakdown` (seconds spent Normal/Warning/High/Critical — powers the pie
distribution without rescanning raw). This is the mechanism that makes 100k interfaces
and millions of records tractable (doc 19).

## 4. Ingestion & provenance model

| Object | Key fields | Purpose |
| --- | --- | --- |
| `upload_batch` | id, uploader, uploaded_at, source_type, original_filename, checksum, row_count, time_range_covered, status, validation_report_id | One immutable ingest event. Original file retained in object storage. |
| `validation_report` | batch_id, schema_result, duplicate_result, gap_findings[], corrupt_findings[], interval_findings[], summary | Full record of what validation found (doc 04). |
| `column_mapping_profile` | id, name, source_signature, field_map | Reusable mapping of messy spreadsheet headers → canonical fields. |
| `ingest_cursor` (future) | source_id, last_ts, last_counter | For streaming/polling sources, resumable state. |

## 5. Analytics & derived model

These tables hold what the engines produce. All are recomputable from facts + config,
and all are versioned so a report can be reproduced exactly.

| Object | Key fields | Produced by |
| --- | --- | --- |
| `baseline` | entity_id, dimension (dow/hour), stats (mean, stddev, p50/p95), window, computed_at | Analytics engine (doc 08). |
| `verdict` | entity_id, level, title, reason, evidence_ref[], confidence, recommended_action, valid_from, ruleset_version | Verdict engine (doc 09). |
| `anomaly` | entity_id, type, ts_start, ts_end, severity, score, explanation, evidence_ref[] | Anomaly detection (doc 10). |
| `forecast` | entity_id, horizon, model, projected_series, time_to_80/90/95, upgrade_window, confidence_interval | Capacity engine (doc 11). |
| `risk_score` | entity_id, score, factor_breakdown{}, computed_at | Risk engine (doc 12). |
| `rca_case` | id, trigger_ref, answers{}, related_entities[], likely_cause, status | RCA assistant (doc 14). |

## 6. Configuration & governance model

| Object | Purpose |
| --- | --- |
| `rule` | Configurable condition→verdict logic (doc 07). Versioned. |
| `threshold_set` | Named Normal/Warning/High/Critical bands, assignable by class/site/customer/interface. |
| `calendar` | Business days, business hours, holidays, per site/customer. |
| `maintenance_window` | Planned window; scopes suppression of alerts/SLA/trend (doc + maintenance awareness). |
| `classification_policy` | Maps class → default thresholds/impact/policy. |
| `user`, `role`, `permission`, `assignment` | RBAC (doc 18). |
| `audit_event` | Append-only record of every change/action (doc 18 §Audit). |
| `kb_article` | SOPs, runbooks, known issues, TAC cases, RCA docs, attached to entities (doc: Knowledge Base). |
| `timeline_event` | Operational timeline entries per entity (doc: Timeline). |
| `comment` / `annotation` | Human notes attached to entities/timepoints. |
| `report_definition` / `report_run` | Report templates and generated instances. |

## 7. Logical overlays

```
Customer ──< owns >── Interface   (a customer's links across many devices/sites)
Service  ──< uses  >── Interface   (a business service spanning links)
Class    ──< tags  >── Interface   (Core/Trading/… — drives policy)
```

Overlays let the same physical fact roll up three different ways — by site (physical),
by customer (contractual), and by class (operational) — which is exactly what the
Executive, NOC, and Capacity views each need.

## 8. Entity-relationship summary (text ERD)

```
Site 1─* Room 1─* Rack 1─* Device 1─* LineCard 1─* Interface
Interface *─1 Customer        Interface *─1 Service       Interface *─* Class
Interface 1─* Sample(ts)      Sample *─1 UploadBatch      UploadBatch 1─1 ValidationReport
Interface 1─* Verdict         Interface 1─* Anomaly       Interface 1─* Forecast
Entity(any) 1─* RiskScore     Entity(any) 1─* TimelineEvent   Entity(any) 1─* KBArticle
Rule *─* ThresholdSet         Calendar 1─* MaintenanceWindow
User *─* Role *─* Permission  AuditEvent (append-only, references any entity)
```

## 9. Data lifecycle & integrity rules

- **Immutability:** samples and batches are write-once. A re-upload of the same period
  creates a *new* batch; conflict resolution is explicit (doc 04), never silent overwrite.
- **Idempotency:** ingestion is keyed by `(interface_id, ts, source_type)` so replays
  don't double-count; duplicates are detected, not merged blindly.
- **Reproducibility:** every derived artifact stores the `ruleset_version` /
  `model_version` / `baseline_window` used, so an old report renders identically later.
- **Right-to-forget / decommission:** entities can be decommissioned (hidden from live
  views, retained for history) or purged (with audit) per retention policy.
