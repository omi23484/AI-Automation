# 02 — Information Architecture & Navigation Flows

## 1. Top-level information architecture

NetPulse organizes around **three axes** that the user can pivot between at any time:

1. **Topology axis** — Site → Room → Rack → Device → Line Card → Interface (the Digital Twin).
2. **Analytical axis** — Verdicts, Anomalies, Capacity, Trends, Risk, RCA.
3. **Operational axis** — Uploads, Maintenance, Audit, Reports, Knowledge Base, Admin.

The primary navigation is a **persistent left rail** grouped into these axes, plus a
**global command bar** (search + natural-language query) at the top and a **context
breadcrumb** that always reflects where you are in the topology.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ◎ NetPulse   [ ⌘K  Search / Ask NetPulse… ]        ⚙  🔔  👤 (role)      │  ← Global bar
├───────────────┬──────────────────────────────────────────────────────────┤
│  OVERVIEW     │  Breadcrumb: Site: LON-DC1 › Rack: R14 › Device: Core-01   │
│   Executive   │                                                            │
│   NOC         │                                                            │
│   Digital Twin│                 ── main content canvas ──                  │
│               │                                                            │
│  ANALYZE      │                                                            │
│   Site        │                                                            │
│   Device      │                                                            │
│   Interface   │                                                            │
│   Historical  │                                                            │
│   Capacity    │                                                            │
│   Trends      │                                                            │
│   Traffic TL  │                                                            │
│   Anomalies   │                                                            │
│   RCA         │                                                            │
│               │                                                            │
│  OPERATE      │                                                            │
│   Uploads     │                                                            │
│   Maintenance │                                                            │
│   Reports     │                                                            │
│   Knowledge   │                                                            │
│   Audit       │                                                            │
│   Admin       │                                                            │
└───────────────┴──────────────────────────────────────────────────────────┘
```

The left rail is **role-filtered** (doc 18): a Viewer never sees Admin; an L2 sees
Operate items relevant to their duties, etc.

## 2. Dashboard hierarchy (drill path)

NetPulse is a **hierarchy of dashboards**, each a lens at a different altitude. The
core interaction is *drill-down* (zoom in) and *roll-up* (zoom out), and every level
carries verdicts, risk, and capacity signals appropriate to its altitude.

```
Executive Dashboard        ← whole-infrastructure posture, board-level
        │  (drill by site / customer / class)
        ▼
NOC Dashboard              ← live triage across everything, impact-ranked
        │  (drill into an alerting site)
        ▼
Site Dashboard             ← one site: rooms, top devices/links, site risk
        │  (drill into a device)
        ▼
Device Dashboard           ← one device: line cards, interfaces, device health
        │  (drill into an interface)
        ▼
Interface Dashboard        ← the atomic unit: verdict, charts, forecast, RCA, timeline
```

Parallel to this drill path sit the **cross-cutting analytical dashboards** that slice
across the hierarchy rather than down it:

- **Historical Analysis** — any entity vs. its own past (yesterday / last week / same
  weekday / previous month / quarter).
- **Capacity Planning** — forecast-centric view, filterable to any scope.
- **Trend Analysis** — growth and pattern change across scopes.
- **Traffic Timeline** — a scrubable time ribbon of traffic + events for an entity.
- **Anomaly Feed** — everything flagged as abnormal, ranked.
- **RCA Workspace** — investigation surface anchored to an incident or interface.

And the **operational dashboards**:

- Upload History, Maintenance History, Audit Logs, Business Reports, Knowledge Base,
  Admin (Rules, Classifications, Calendars, Users/RBAC).

## 3. Role-based landing (default entry)

| Role | Lands on | Rationale |
| --- | --- | --- |
| Executive | Executive Dashboard | Posture and exposure first. |
| Architect | Capacity Planning | Forward-looking planning is the day job. |
| NOC Lead (L3) | NOC Dashboard | Impact-ranked triage. |
| NOC Eng (L2) | NOC Dashboard → assigned queue | What's mine to work. |
| Admin | Admin / Upload History | Data + configuration health. |
| Read-Only / Viewer | Executive Dashboard (read-only) | Safe, high-level overview. |

Every user can navigate anywhere their role permits; landing is just the default.

## 4. Primary navigation flows (flow diagrams)

### 4.1 Triage flow (NOC Lead)
```
NOC Dashboard
  → sort/rank by Business Impact + Risk
  → open top verdict card ("Critical Congestion — Core-01 Eth1/2")
  → Interface Dashboard (verdict, evidence, forecast)
  → "Explain" → RCA Assistant auto-answers (start, duration, recurrence, related, cause)
  → attach comment / annotate Timeline / open runbook from Knowledge Base
  → mark acknowledged / escalate / open maintenance
```

### 4.2 Capacity flow (Architect)
```
Capacity Planning
  → scope = Site LON-DC1, class = Core
  → Top Growing Links (ranked by growth rate)
  → open link → forecast (30/60/90/180) + time-to-80/90/95 + confidence
  → "Recommended upgrade window: 45–60 days"
  → add to Weekly Capacity Report → export PDF for CAB
```

### 4.3 Ingestion flow (Admin)
```
Uploads → Upload new XLSX (one or many)
  → Validation console: schema check, duplicate detection, gap/interval check,
    corrupt-value check, timestamp coverage
  → resolve warnings (map columns, confirm site/device, mark maintenance overlap)
  → Commit → new immutable batch created, analytics recomputed incrementally
  → Upload History shows batch, coverage, and what changed
```

### 4.4 Executive flow
```
Executive Dashboard
  → Infrastructure Risk Score + trend
  → Top Critical / Top Growing / Business Impact tiles
  → drill a tile → filtered NOC/Capacity view
  → "Generate Executive Summary" → natural-language narrative + PDF export
```

### 4.5 Digital Twin flow (spatial navigation)
```
Digital Twin (Site map)
  → click Site → Room floor plan
  → click Rack → rack elevation with devices
  → click Device → front panel with line cards
  → click Interface LED → Interface Dashboard
  (LED color = health verdict at every level; hover = mini-verdict + sparkline)
```

## 5. Cross-navigation and deep-linking

- **Every entity is addressable** by a stable URL (e.g. `/interface/{id}`,
  `/site/{id}/capacity`). This makes verdicts, reports, and RCA sharable and lets
  alerts/emails deep-link straight to the relevant view.
- **Context follows you.** Switching from Interface → Trends keeps the interface in
  scope; switching from Site → Capacity keeps the site in scope. A scope chip in the
  breadcrumb shows and lets you clear/change the active entity.
- **Global command bar (⌘K)** does three things: (1) fuzzy entity search
  ("Core-01", "LON-DC1 Eth1/2"), (2) action search ("upload file", "new rule"),
  and (3) natural-language query ("what happened on Core-01 yesterday 10–12?") which
  routes to the AI assistant (doc 13).

## 6. Consistent page anatomy

To keep 100k interfaces navigable, **every** analytical page follows the same anatomy
so users build one mental model:

```
┌ Header ────────────────────────────────────────────────────────────────┐
│  Entity name + class chips + Business Impact badge + Risk score          │
│  Verdict banner (the conclusion, plain English) + confidence + action    │
├ Context strip ──────────────────────────────────────────────────────────┤
│  Time-range selector · scope filters · "compare to" baseline selector    │
├ Evidence canvas ─────────────────────────────────────────────────────────┤
│  Charts / heatmaps / distribution — the proof behind the verdict          │
├ Insight rail (right) ────────────────────────────────────────────────────┤
│  AI summary · anomalies · forecast snapshot · related entities · timeline │
└──────────────────────────────────────────────────────────────────────────┘
```

Verdict on top, evidence in the middle, AI and context on the right — at every
altitude from Executive to Interface. See doc 05 for the per-screen detail.
