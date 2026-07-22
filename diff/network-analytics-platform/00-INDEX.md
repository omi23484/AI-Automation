# NetPulse — Network Analytics & Capacity Planning Platform
## Product Specification (Planning Only — No Code)

**Codename:** NetPulse
**Category:** Network Interface Analytics, Anomaly Detection, Capacity Planning, AI NOC Assistant
**Target markets:** Enterprise data centers, trading / low-latency infrastructure, ISPs, managed NOCs
**Positioning:** The analytical brain that sits *between* SolarWinds/ThousandEyes-style collection, Grafana/Splunk-style visualization, and an AI NOC engineer. NetPulse does not just draw graphs — it renders **verdicts**, forecasts **saturation**, and drives **RCA**.

---

## How to read this specification

This spec is deliberately modular so different disciplines (architecture, backend,
frontend, data science, product) can own their sections. Read in order for a full
picture, or jump to the document that matches your role.

| # | Document | Primary audience |
| --- | --- | --- |
| 00 | **This index** | Everyone |
| 01 | [Product Vision, Personas & Value](./01-product-vision-and-personas.md) | Product, Leadership |
| 02 | [Information Architecture & Navigation Flows](./02-information-architecture-and-navigation.md) | Product, UX, Frontend |
| 03 | [Data Model](./03-data-model.md) | Backend, Data |
| 04 | [Data Ingestion, Validation & Upload Lifecycle](./04-data-ingestion-and-validation.md) | Backend, Data |
| 05 | [Screen-by-Screen Layouts](./05-screen-layouts.md) | UX, Frontend, Product |
| 06 | [User Journeys](./06-user-journeys.md) | UX, Product |
| 07 | [Rule Engine Design](./07-rule-engine.md) | Backend, Data, Product |
| 08 | [Analytics Engine Design](./08-analytics-engine.md) | Data, Backend |
| 09 | [Verdict Engine Logic](./09-verdict-engine.md) | Data, Backend, Product |
| 10 | [Anomaly Detection](./10-anomaly-detection.md) | Data Science |
| 11 | [Capacity Planning & Forecasting Logic](./11-capacity-planning.md) | Data Science, Product |
| 12 | [Risk Scoring Model](./12-risk-scoring.md) | Data, Product |
| 13 | [AI Assistant Architecture](./13-ai-assistant-architecture.md) | AI/ML, Backend |
| 14 | [RCA Assistant](./14-rca-assistant.md) | Data Science, NOC |
| 15 | [Reports & Exports](./15-reports-and-exports.md) | Product, Backend |
| 16 | [Data Center Digital Twin](./16-digital-twin.md) | UX, Frontend, Product |
| 17 | [UI/UX Design System & Visualizations](./17-ui-ux-design-system.md) | UX, Frontend |
| 18 | [Security & RBAC Model](./18-security-and-rbac.md) | Security, Backend |
| 19 | [Scalability & Performance Strategy](./19-scalability-and-performance.md) | Architecture, SRE |
| 20 | [Integrations & Future Roadmap](./20-integrations-and-roadmap.md) | Architecture, Product |
| 21 | [Operational Modules (Classification, Business Impact, Baselines, Maintenance, Timeline, Knowledge Base)](./21-operational-modules.md) | Product, NOC, Backend |
| — | [**SOP — NetPulse Operations** (every knob & how to use it)](./SOP-netpulse-operations.md) | NOC, Architects, Admins |

---

## The single-sentence product thesis

> Point NetPulse at your interface polling data and it tells you, in plain English,
> **which links are healthy, which are lying to you, which will run out of headroom
> and when, and what to do about it** — with the evidence, confidence, and history
> to back every claim.

---

## Design principles (apply to every module)

1. **Verdict-first, not chart-first.** Every screen leads with a conclusion an
   engineer can act on; charts are the *evidence* behind the conclusion, not the
   product itself.
2. **Never destroy history.** Uploads and derived facts are append-only. The past
   is the most valuable asset for baselining, forecasting, and RCA.
3. **Source-agnostic core.** The ingestion layer normalizes everything into one
   canonical time-series + entity model. Excel today; SNMP, telemetry, NDFC, ACI,
   SolarWinds, NetFlow, Prometheus tomorrow — **without changing the dashboards.**
   Uploaded files are understood by **meaning, not by hardcoded headers**, and all
   bandwidth values (Gbps/Mbps/Kbps/bytes/counters) are **normalized to canonical bits
   per second** before anything downstream sees them (doc 04 §2.2–2.3).
4. **Explainability is a feature.** No black-box scores. Every verdict, anomaly,
   forecast, and risk number exposes its inputs, thresholds, and confidence.
5. **Business impact over raw utilization.** A 60%-utilized trading core link
   outranks a 95%-utilized backup link. Priority is a first-class dimension.
6. **Operations-center feel.** The UI is a dark, fluid, glassmorphic *digital twin*
   of the data center — not a generic BI dashboard.
7. **Scale is a day-one constraint.** 100k+ interfaces and millions of records must
   work without re-architecture. Pre-aggregation and rollups are built in, not
   bolted on.
8. **Configuration over code.** Rules, thresholds, calendars, classifications, and
   policies are all editable by administrators without a deployment.

---

## Terminology (used consistently across all documents)

| Term | Meaning |
| --- | --- |
| **Entity** | A monitored object: Site, Room, Rack, Device, Line Card, Interface, plus logical groupings (Customer, Service). |
| **Poll / Sample** | One timestamped measurement row for an interface. |
| **Upload / Batch** | One ingested file (or future stream window), timestamped and immutable. |
| **Rollup** | A pre-aggregated summary of samples over a time bucket (5m/1h/1d). |
| **Verdict** | A generated, human-readable operational judgment about an entity. |
| **Baseline** | A statistical reference profile (e.g., "normal Tuesday 10:00 traffic"). |
| **Risk Score** | A 0–100 composite indicating attention priority. |
| **Class** | An interface tag (Core, Trading, Internet, WAN, Storage, Backup, …). |
| **Business Impact / Priority** | Critical / High / Medium / Low importance of an entity. |
| **Digital Twin** | The navigable visual model Site → Room → Rack → Device → Line Card → Interface. |
