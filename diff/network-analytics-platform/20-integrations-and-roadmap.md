# 20 — Integrations & Future Roadmap

This document shows how NetPulse evolves from an Excel-upload tool into a real-time,
multi-source, AI-driven platform — **without redesigning the dashboards or engines** —
and lays out the phased roadmap and enterprise best practices.

## 1. The integration promise (why nothing downstream changes)

Every data source terminates in the **same canonical contract**: normalized `Sample`
(rates + utilization) → `ValidationReport` → immutable `UploadBatch` → incremental
analytics (docs 03/04/08). The Verdict, Anomaly, Capacity, Risk, RCA, dashboards, and
Digital Twin only ever read the **derived-artifact contract**. Therefore a new source is
a **new adapter at the edge**, not a change to the product.

```
[ XLSX ] [ SNMP ] [ Telemetry ] [ NDFC ] [ ACI ] [ SolarWinds ] [ NetFlow ] [ Prometheus ]
     └──────┴───────────┴─────────┴──────┴──────┴──────────┴──────────┴──────┘
                         ▼  (adapter contract, doc 04 §1)
                 canonical Sample + Batch + Validation
                         ▼
                 SAME analytics, verdicts, dashboards, twin
```

## 2. Integration targets & what each adapter handles

| Source | Mode | Adapter responsibilities (kept at the edge) |
| --- | --- | --- |
| **SNMP** | Poll | ifTable/ifXTable, 64-bit counters, wrap/reset, rate conversion, community/v3 secrets. |
| **Streaming Telemetry (gNMI/gRPC)** | Push | Subscriptions, native rates, sub-minute cadence, resumable cursors. |
| **Cisco NX-API** | Poll/API | REST/JSON pulls, per-device auth, interface stats mapping. |
| **Cisco NDFC** | API | Fabric/inventory → site/device/interface mapping; fabric-wide pulls. |
| **Cisco ACI** | API | Tenant/EPG/fabric model → entity mapping; APIC stats. |
| **SolarWinds** | API/DB | SWIS/Orion node+interface → entity mapping and metric import. |
| **NetFlow / IPFIX** | Collector | Flow aggregation → interface rates now; per-conversation analytics later. |
| **Prometheus** | Query | PromQL range queries over `ifHC*Octets`-style series → normalized rates. |

Secrets for all of these live in the vault (doc 18 §5); each source is scoped and
audited. **Mixed sources coexist:** an interface can be seeded from Excel history and
continued via streaming telemetry — provenance (`source_type`) is preserved per sample.

## 3. Phased roadmap

### Phase 1 — Foundation (v1)
- XLSX ingestion with intelligent header understanding + unit normalization (doc 04).
- Entity model, rollups, baselines (doc 03/08).
- Rule engine, Verdict engine, utilization distribution analytics (docs 07/08/09).
- Core dashboards (Executive/NOC/Site/Device/Interface), Historical, Trends, Traffic
  Timeline (doc 05).
- Capacity forecasting (trend + seasonal), Risk scoring (docs 11/12).
- Anomaly detection (baseline + change-point ensemble) (doc 10).
- RCA auto-answers (deterministic) (doc 14).
- Reports + exports (doc 15), Upload/Maintenance/Audit, Knowledge Base, Timeline (doc 21).
- AI Summary + anomaly/report narration (grounded, with fallback) (doc 13).
- Digital Twin (logical layout, LED health) (doc 16).
- RBAC, audit, encryption (doc 18); scale foundations (doc 19).

### Phase 2 — Live data & deeper AI
- **SNMP + Prometheus** adapters (first real-time-ish sources).
- **Streaming telemetry** adapter (true real-time; near-live twin & alerting).
- **Natural-language query** ("what happened on Core-01 yesterday 10–12?", doc 13).
- **AI RCA assistant** (conversational over grounded evidence).
- **Automatic anomaly explanations** at scale; upgrade-recommendation narratives.
- Alerting/notifications integrations (email/chat/webhook) and ticketing hooks.

### Phase 3 — Fabric-native & platform
- **NDFC / ACI / NX-API / SolarWinds / NetFlow** adapters (vendor/fabric-native + flow).
- **Capacity recommendation engine** and **upgrade recommendation engine** (sequencing,
  capex framing).
- **Natural-language report generation** (doc 15 §5).
- **Multi-tenancy / MSP** hardening (scoped tenants at fleet scale).
- **Environmental overlays** (power/thermal), traffic-flow animation, path highlighting
  in the twin.

### Phase 4 — Autonomous NOC (guarded)
- Proactive, prioritized recommendations and playbook suggestions.
- Optional, **strictly-gated** action-taking (config change proposals routed to change
  management) — recommend-then-approve, never silent automation; full audit + separation
  of duties (doc 18 §7).
- Continuous learning loop from confirmed RCAs → improved verdicts/hypotheses.

## 4. Future AI feature set (planned, from the brief)

- **Natural-language querying** over all analytics (grounded, cited).
- **AI RCA assistant** (guides investigation beyond auto-answers).
- **Capacity recommendation engine** (what/where/when to upgrade).
- **Upgrade recommendation engine** (sequenced, business-impact-weighted).
- **Automatic anomaly explanations** (already grounded; scaled + conversational).
- **Natural-language report generation** (describe → generated report).

All of these are **additive** — they call the same platform tools (doc 13 §3) and read
the same derived artifacts, so they do not destabilize operations or require redesign.

## 5. Enterprise best practices (baked in)

- **Source-agnostic core** — protect the investment across the collection-method
  transition.
- **Never destroy history** — append-only, immutable batches, reproducible artifacts.
- **Explainability everywhere** — verdicts, scores, anomalies, forecasts expose their
  inputs and confidence; audit + versioning make any past state reproducible.
- **Configuration over code** — rules, thresholds, calendars, classes, policies editable
  by admins with dry-run + versioning + audit.
- **Business impact first** — prioritize by consequence, not raw utilization.
- **Least privilege + full audit + on-prem AI option** — deployable in regulated,
  mission-critical NOCs.
- **Scale as a constraint, not a project** — pre-aggregation, incremental compute,
  virtualized UI from day one.
- **Deterministic truth, AI for language** — the platform is correct without the model;
  the model makes it faster to understand.

## 6. Success metrics (how we'll know it works)

- **MTTU (mean time to understanding)** for incidents ↓ (RCA auto-answers).
- **Capacity surprises** (unplanned saturation events) ↓ (forecasts + proactive verdicts).
- **Alert noise** ↓ while **true behavioral catches** ↑ (baseline anomalies + impact
  ranking + maintenance awareness).
- **Report turnaround** (exec/capacity) from days → minutes (generated reports).
- **Adoption:** engineers start their shift on the NOC Dashboard / Digital Twin, not in
  a spreadsheet.
