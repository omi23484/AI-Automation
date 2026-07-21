# 21 — Operational Modules

This document specifies the supporting modules that make the analytics operationally
complete: **Interface Classification, Business Impact, Historical Baselines, Maintenance
Awareness, Operational Timeline, and Knowledge Base.** (Audit Trail is specified in doc
18 §4.) These are the connective tissue between raw analytics and day-to-day NOC work.

---

## 1. Interface Classification

**Purpose:** tag every interface with its operational role so policy, priority, and
analytics can be role-aware.

- **Classes:** Core · Trading · Internet · WAN · Storage · Backup · Voice · Replication ·
  Management · Customer. Multi-tag allowed (an interface can be Core *and* Trading).
- **Assignment:** manual (Admin/Architect), rule-based (by description/name pattern,
  device role, or VLAN/subnet hints), and import (from source metadata). Proposed
  classifications are confirmable; changes are historized (doc 03 §2.2) so past analytics
  respect the class in effect at the time.
- **Drives policy:** each class maps to default **threshold sets**, **business impact**,
  anomaly expectations, and rule scope (doc 07). Example: Trading gets a stricter High
  band and business-hour sensitivity; Backup expects high off-hours utilization and
  weekend activity (so it isn't falsely flagged), but weekend traffic on a *business*
  link is an anomaly (doc 10 §2.5).
- **Managed in:** Admin → Classifications & Policies (no code).

---

## 2. Business Impact / Priority

**Purpose:** ensure the platform prioritizes by **consequence**, not raw utilization.

- **Levels:** Critical · High · Medium · Low, on every interface (and inheritable to
  device/site/customer).
- **Assignment:** derived from class defaults, overridable per entity, and settable via
  customer/service mapping (a customer's SLA can force Critical).
- **Effect across the platform:**
  - **Ranking:** NOC queue, Top-N, and all tables sort by `business_impact × risk ×
    confidence` (docs 05/12) — a 60% Critical trading link outranks a 95% Low backup link.
  - **Verdict emphasis & severity** (doc 09) and **risk multiplier** (doc 12).
  - **Anomaly severity weighting** (doc 10 §4).
  - **Reports:** the **Business Impact Report** ranks issues by impact, not utilization
    (doc 15).
- This is a **first-class dimension**, present on every entity badge (doc 17).

---

## 3. Historical Baselines

**Purpose:** compare current behavior against the entity's own past to spot deviation.

- **Comparison references:** Yesterday · Last week · **Same weekday** · Previous month ·
  Previous quarter — each a specific slice of the baseline/rollup store (doc 08 §3).
- **Deviation output:** %Δ and z-score vs the reference, surfaced as "18% above the
  same-weekday baseline", with a shaded overlay on the chart and a deviation heatmap
  (doc 05 §5.6).
- **Uses:** the Historical Analysis screen, the rule COMPARE predicate (doc 07),
  anomaly detection (doc 10), verdict comparison evidence (doc 09), and AI summaries.
- **Integrity:** baselines exclude maintenance and known-anomalous periods so "normal"
  isn't polluted; they respect effective-dated speed so upgrades don't distort history.

---

## 4. Maintenance Awareness

**Purpose:** planned work must not create false alarms or corrupt analytics.

- **Maintenance windows** (doc 03 config) scope to site/device/interface/class, with
  one-off or recurring schedules and a reason; created by Admin/L3 in Maintenance History
  (doc 05 §5.12) with an **impact preview** ("suppresses N interfaces").
- **What maintenance excludes:** **Alerts** (no adverse verdicts/notifications), **SLA**
  (uptime/availability math), **Reports** (excluded or clearly annotated), and **Trend
  calculations** (growth/forecast baselines skip the window). Samples in the window are
  **tagged at ingest** (doc 04 §3.5), not retroactively guessed.
- **Awareness elsewhere:**
  - The **Verdict Engine** applies a maintenance gate (doc 09 §3).
  - **Anomaly detection** suppresses within windows (doc 10 §4) but *can* flag
    **post-maintenance behavior change** (a shift that persists after the window).
  - **RCA** checks maintenance correlation automatically (doc 14 §1).
  - Charts **shade** maintenance windows (doc 17 §5) so humans see them.
- **Complete history:** every window (planned/active/past) is retained and auditable.

---

## 5. Operational Timeline

**Purpose:** every interface (and device/site) maintains a single chronological record
of everything that mattered — the operational memory of the link.

- **Event types on the timeline:** traffic increases / change-points · threshold
  violations · anomalies · maintenance · capacity upgrades · engineer comments ·
  RCA cases · reports · historical annotations · classification/impact changes.
- **Two views:**
  - **Entity Timeline** (Insight rail / dedicated tab): a vertical event log with
    filters and deep-links.
  - **Traffic Timeline** (doc 05 §5.9): the same events pinned onto the traffic chart's
    time axis, scrubable and zoomable, so metrics and events are read together.
- **Interactions:** click an event → jump to its source (RCA case, upload batch,
  comment, report); add a comment/annotation at a point in time (audited).
- **Value:** answers "has this happened before / what changed and when" instantly, and
  feeds RCA recurrence detection (doc 14).

---

## 6. Knowledge Base

**Purpose:** attach institutional knowledge directly to the entities it concerns, so the
right runbook is one click from the alert.

- **Article types:** SOPs · Runbooks · Known Issues · Vendor TAC cases · RCA documents ·
  Design documents · Maintenance records.
- **Attachment model:** any article can be linked to one or many **interfaces/devices/
  sites/classes/customers**; from any Interface/Device dashboard, "📎 Attach knowledge"
  links or creates an article for that entity (doc 05 §5.15).
- **Surfacing:** relevant articles appear in the Interface Dashboard Insight rail and in
  RCA (attach known issues/runbooks to a case). Search across the KB by type/entity/text.
- **Lifecycle:** versioned, authored/edited with audit, and RCA outputs can be promoted
  into permanent KB articles (doc 14 §6) — a virtuous loop where each incident makes the
  next one faster.

---

## 7. How these modules interlock

```
Classification ─┐
                ├─► sets defaults for → Thresholds/Rules (07) → Verdicts (09)
Business Impact ─┘                                   │
                                                     ├─► Ranking everywhere (05/12)
Baselines (08) ──► Deviation → Anomaly (10) ─────────┤
                                                     ▼
Maintenance ──► gates Alerts/SLA/Trend/Anomaly ──► honest analytics
                                                     ▼
Timeline ◄── records violations/anomalies/RCA/comments/reports ──► feeds RCA recurrence
                                                     ▼
Knowledge Base ◄── attached to entities, promoted from RCA ──► faster next incident
```

Together these turn NetPulse from an analytics engine into a **working NOC system**:
role-aware, impact-prioritized, deviation-sensitive, maintenance-honest, historically
complete, and knowledge-rich.
