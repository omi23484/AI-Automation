# 05 — Screen-by-Screen Layouts

Every screen follows the shared page anatomy from doc 02 §6 (Verdict banner → Context
strip → Evidence canvas → Insight rail). Layouts below are wireframes in text; visual
system and components are specified in doc 17.

Legend: `▮` KPI/stat tile · `▬` chart · `▤` table · `◧` heatmap · `●` verdict/AI card.

---

## 5.1 Executive Dashboard

**Purpose:** whole-infrastructure posture and exposure, board-ready. Read-first.

```
● INFRASTRUCTURE POSTURE — "Stable, with 3 emerging capacity risks"      Risk 34/100 ▲
  AI narrative (2–3 sentences, generated) · confidence · "Generate Executive Summary ⤓"
────────────────────────────────────────────────────────────────────────────────────
▮ Infra Risk 34 ▲   ▮ Critical Links 6   ▮ Growing >20%/mo 14   ▮ Forecast breaches 90d: 4
────────────────────────────────────────────────────────────────────────────────────
▬ Infrastructure utilization trend (30/90/180d, p95)   ◧ Site risk heatmap (site × week)
────────────────────────────────────────────────────────────────────────────────────
▤ Top Critical Links (by business impact)   ▤ Top Growing Links (by growth rate)
▤ Capacity Forecast summary (site → time-to-90%)        ● Executive AI Summary
```
- Tiles drill into filtered NOC/Capacity views. Everything is exportable (doc 15).
- No gauges. Risk is a single number with a trend arrow and a factor tooltip (doc 12).

---

## 5.2 NOC Dashboard

**Purpose:** live triage across everything, ranked by **business impact × risk**, not
by raw utilization. This is the NOC Lead's home.

```
● NOC STATUS — "4 items need attention · 2 Critical · maintenance active on LON-DC2"
────────────────────────────────────────────────────────────────────────────────────
[ Filters: site · class · customer · impact · state ]   [ Group by: impact | site | class ]
────────────────────────────────────────────────────────────────────────────────────
ATTENTION QUEUE (impact-ranked verdict cards)                 │  INSIGHT RAIL
  ● Critical Congestion — Core-01 Eth1/2   impact:Critical    │  ▬ live anomaly feed
     18% MoM ↑ · exceeded BH threshold 14× · [Explain][Ack]   │  ◧ health heatmap
  ● Capacity Review — LON-DC1 Internet-A    impact:High       │     (device × hour)
     time-to-90%: 52d · [Plan][Explain]                       │  ▮ open RCA cases
  ● Traffic Pattern Changed — Cust-ACME WAN impact:High       │  ▮ maintenance now
  … (paginated / virtualized)                                 │  ▮ uploads today
────────────────────────────────────────────────────────────────────────────────────
▤ All interfaces (virtualized grid): name · class · impact · util p95 · verdict · risk
```
- The queue is the product: each card is a **verdict** with reason, evidence teaser,
  and one-click **Explain** (→ RCA) / **Ack** / **Plan**.
- Green rows are collapsed by default; the floor sees signal, not 4,000 healthy links.

---

## 5.3 Site Dashboard

**Purpose:** one site — its rooms, top devices/links, and site-level risk & capacity.

```
● SITE: LON-DC1 — "Healthy. Internet edge trending to 90% in ~7 weeks."   Site Risk 41
────────────────────────────────────────────────────────────────────────────────────
▮ Devices 42  ▮ Interfaces 1,180  ▮ Critical 3  ▮ Avg p95 46%  ▮ Growing links 9
────────────────────────────────────────────────────────────────────────────────────
◧ Room/device health heatmap (device × hour)     ▬ Site aggregate traffic (in/out, p95)
────────────────────────────────────────────────────────────────────────────────────
▤ Top devices by risk   ▤ Top links by growth   ● Site AI summary + forecast snapshot
[ Open in Digital Twin → ]   [ Site capacity report ⤓ ]
```

---

## 5.4 Device Dashboard

**Purpose:** one device — line cards, its interfaces, device health & correlation.

```
● DEVICE: Core-01 (Nexus 9508) — "1 line card hot; Eth1/2 congested in business hours"
────────────────────────────────────────────────────────────────────────────────────
▮ Interfaces 96  ▮ Up 94  ▮ Critical 1  ▮ Device Risk 58  ▮ Backplane/agg p95 61%
────────────────────────────────────────────────────────────────────────────────────
FRONT-PANEL VIEW (line cards with per-port LED = verdict color)   │  ● Device AI summary
  [Slot1 ▮▮▮▮▮▮▮▮]  [Slot2 ▮▮▮▮▮▮▮▮]  …                            │  ▬ related-interface
────────────────────────────────────────────────────────────────  │     correlation
▤ Interfaces (grid): name · class · impact · p95 · verdict · risk  │  ▮ maintenance
▬ Device aggregate traffic     ◧ interface × hour utilization heatmap
```
- Clicking a port LED → Interface Dashboard. This is the bridge to the Digital Twin.

---

## 5.5 Interface Dashboard (the deep-dive — most important screen)

**Purpose:** the atomic unit. Verdict, evidence, distribution, forecast, anomalies,
RCA, timeline, and knowledge — everything about one interface in one place.

```
● Core-01 · Eth1/2   [Trading][Core]  Impact: CRITICAL   Risk 72 ▲
  VERDICT: "Recurring Business-Hour Congestion — Capacity Planning Required"
  Confidence 0.86 · Reason: p95 exceeded 75% on 14 business days in 30d, +18% MoM
  Recommended action: plan upgrade within ~60 days · [Explain (RCA)] [Add to report]
────────────────────────────────────────────────────────────────────────────────────
[ Time range · Compare to: yesterday|last week|same weekday|prev month|prev quarter ]
────────────────────────────────────────────────────────────────────────────────────
▬ Utilization line/area (TX/RX, peak overlay, threshold bands, maintenance shaded)
◧ Calendar heatmap (day × hour utilization)        🥧 Utilization state distribution
                                                       Normal 62% · Warn 21% · High 12% · Crit 5%
                                                       ● AI: "Most congestion clusters
                                                         09:30–11:00 on weekdays…"
────────────────────────────────────────────────────────────────────────────────────
▬ Capacity forecast (30/60/90/180) with confidence band · time-to-80/90/95
────────────────────────────────────────────────────────────────────────────────────
INSIGHT RAIL:  ● AI summary   ⚠ anomalies (list)   ↔ RX/TX balance   related interfaces
               🕒 Timeline (violations, maintenance, comments, RCA)   📎 Knowledge (SOPs)
```
- The **pie/distribution** is analytical (time-in-state), not a peak gauge, with an AI
  explanation beneath (doc 08 §distribution, doc 09).
- "Compare to" swaps the baseline overlay (doc: Historical Baselines).

---

## 5.6 Historical Analysis

**Purpose:** any entity vs. its own past; deviation detection.

```
● "Core-01 Eth1/2 is running 18% above the same-weekday baseline this week."
[ Entity picker · Baseline: yesterday | last week | same weekday | prev month | quarter ]
────────────────────────────────────────────────────────────────────────────────────
▬ Overlay: current vs baseline (shaded deviation)   ▤ deviation table (metric · Δ · sig)
◧ Deviation heatmap (period × hour)                 ● AI: what changed and when
```

---

## 5.7 Capacity Planning

**Purpose:** forecast-centric planning at any scope.

```
● "Across LON-DC1 Core class: 4 links breach 90% within 90 days."
[ Scope: site/device/class/customer ]  [ Horizon: 30/60/90/180 ]
────────────────────────────────────────────────────────────────────────────────────
▤ Forecast table: entity · current p95 · slope · time-to-80 · 90 · 95 · upgrade window · conf
▬ Selected entity forecast with confidence band       ▬ aggregate capacity trend
● AI capacity narrative + recommended upgrade sequencing   [ Weekly Capacity Report ⤓ ]
```

---

## 5.8 Trend Analysis

**Purpose:** growth and pattern change across scopes.

```
[ Scope · window: WoW / MoM / QoQ ]
▤ Top Growing / Top Declining links (Δ%, slope)   ▬ trend lines with change-point markers
◧ Growth heatmap (entity × month)   ● AI: "New weekend traffic pattern on 3 backup links"
```

---

## 5.9 Traffic Timeline

**Purpose:** a scrubable time ribbon combining traffic with operational events.

```
[ scrubber ────────●──────────── ]  zoom: 1h / 1d / 1w / 1m
▬ Traffic (TX/RX) with overlaid event pins:
   ▼ violation  ▼ maintenance  ▼ upgrade  ▼ comment  ▼ RCA  ▼ anomaly
Hover a pin → detail popover · click → jump to source (RCA case, upload, comment)
```

---

## 5.10 Upload History  &  5.11 Validation Console

```
UPLOAD HISTORY
▤ batches: time · uploader · source · file · coverage ribbon · rows · entities · status
  row → [Validation report] [Download original] [What changed] [Supersede (reason)]

VALIDATION CONSOLE (pre-commit, from doc 04)
● "12 warnings · 1 blocking · covers 2026-07-01→07-14"
[ Blocking ]  schema/map fixes (must resolve)
[ Warnings ] duplicates · gaps · corrupt values · new entities (choose resolution each)
[ Info ]     interpolation · cadence jitter · maintenance overlap
coverage ribbon ▬▬▬░░▬▬  · [ Commit ] enabled only when blocking cleared
```

---

## 5.12 Maintenance History

```
▤ windows: scope · start/end · recurrence · reason · created_by · status(active/planned/past)
[ + New window ]  → scope picker (site/device/interface/class) · schedule · suppression opts
Impact preview: "suppresses alerts/SLA/trend for 96 interfaces during the window"
```

---

## 5.13 Audit Logs

```
[ filters: actor · action-type · entity · date ]
▤ append-only: when · who · role · action · target · before→after · source-ip · batch/report ref
[ Export evidence ⤓ ]   (read-only for all; immutable)
```

---

## 5.14 Business Reports

```
▤ report library: Daily Ops · Weekly Capacity · Monthly Trend · Exec Summary ·
   Top Busy/Growing/Critical/Idle · Capacity Forecast · Business Impact
row → [ Generate now ] [ Schedule ] [ History ] [ Export: PDF | XLSX | CSV | HTML ]
Preview pane renders the report with AI narrative + charts before export.
```

---

## 5.15 Knowledge Base

```
[ search · filter by type: SOP/Runbook/Known Issue/TAC/RCA/Design/Maintenance ]
▤ articles with entity attachments   article view: content · attachments · linked entities
From any Interface/Device: "📎 Attach knowledge" links an article to that entity.
```

---

## 5.16 Digital Twin

Full spatial navigation — specified in doc 16.

---

## 5.17 Admin

Tabbed: **Rules** (builder, doc 07) · **Thresholds** · **Calendars/Holidays** ·
**Classifications & Policies** · **Maintenance** · **Users & Roles** (doc 18) ·
**Data Sources/Adapters** (future) · **Retention**. Every change is audited and
versioned; nothing here requires a code deploy.

---

## 5.18 Responsive & operational modes

- **Wall/NOC mode:** Executive and NOC dashboards have a fullscreen, auto-refresh,
  low-interaction layout for video walls (large type, high contrast, rotation of key
  tiles).
- **Focus mode:** any Interface Dashboard collapses to verdict + one chart + action for
  fast phone/tablet triage.
- **Print/report parity:** report previews render identically to their PDF export.
