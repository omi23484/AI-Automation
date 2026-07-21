# 09 — Verdict Engine Logic

The Verdict Engine is NetPulse's signature. It converts states, distributions,
baselines, anomalies, and forecasts into a **single human-readable judgment** per
entity, each carrying reason, evidence, historical comparison, confidence, and a
recommended action. This is the "conclusion first" that every screen leads with.

## 1. What a verdict is

```
VERDICT
  entity_id, level, title
  reason            — why (plain English)
  evidence[]        — references to charts/metrics/samples that prove it
  comparison        — vs baseline (same weekday / prev month / quarter)
  confidence        — 0..1
  recommended_action
  valid_from, ruleset_version, model_version   — reproducibility
```

### Verdict catalog (labels)
`Healthy` · `Monitor` · `No Action Required` · `Capacity Planning Required` ·
`Critical Congestion` · `Traffic Pattern Changed` · `Recurring Business-Hour
Congestion` · `Weekend Backup Traffic` · `RX/TX Imbalance` · `Post-Maintenance Behavior
Change` · `Idle / Under-utilized` · `Data Quality Issue`.

Each label maps to a **severity tier** (Info/Watch/Warn/Critical) that drives color and
ranking, and to a **recommended-action template**.

## 2. Inputs (from the analytics + engines)

- **State & time-in-state** (doc 07/08): how long/often in each utilization state,
  business vs off-hours.
- **Distribution** (doc 08 §5): the "smart pie" fractions and their trend.
- **Baseline comparison** (doc 08 §3): deviation vs same-weekday / prev month / quarter.
- **Anomalies** (doc 10): typed abnormal-behavior signals.
- **Forecast** (doc 11): time-to-threshold, growth.
- **Context**: class, business impact, maintenance, calendars.

## 3. Verdict derivation logic (decision layer)

The engine runs a **prioritized, explainable decision procedure** — not a black box.
Conceptually a scored rule-set that yields the *most operationally important true
statement* about the entity:

```
1. DATA QUALITY GATE
   if coverage < X% or heavy suspect/interpolated  → "Data Quality Issue" (don't lie about health)

2. MAINTENANCE GATE
   if entity is/was in maintenance for the window  → annotate; exclude from adverse verdicts

3. SEVERITY EVALUATION (pick the dominant true condition)
   if sustained Critical time-in-state (business hours) AND recurring
        → "Recurring Business-Hour Congestion" (+ Capacity Planning if growing)
   elif sustained Critical now
        → "Critical Congestion"
   elif forecast time-to-90% within planning horizon AND positive growth
        → "Capacity Planning Required"
   elif anomaly: pattern-change / new-time / imbalance dominant
        → "Traffic Pattern Changed" / "Weekend Backup Traffic" / "RX/TX Imbalance"
   elif elevated but not critical, or mild deviation
        → "Monitor"
   elif consistently very low utilization
        → "Idle / Under-utilized"
   else
        → "Healthy" / "No Action Required"

4. ENRICH: attach reason, evidence, comparison, confidence, recommended action
5. RANK for queues by (business_impact × severity × confidence)  [doc 12 feeds this]
```

- **Composite verdicts** are allowed: e.g., "Recurring Business-Hour Congestion —
  Capacity Planning Required" when both a present pattern and a future risk are true.
- The engine records **which conditions/rules fired** so evidence is fully traceable
  back to metrics and samples.

## 4. Reason, evidence & comparison (the proof)

Every verdict is required to answer *why should I believe you?*:
- **Reason** — a templated, data-filled sentence: "p95 exceeded 75% on **14** business
  days in the last 30; utilization is **+18%** vs previous month."
- **Evidence** — deep links to the exact chart windows, the distribution, the breaching
  intervals, and the baseline overlay used. Clicking evidence jumps to the source.
- **Comparison** — explicit baseline reference (same weekday / prev month / quarter)
  with the numeric deviation.

## 5. Confidence scoring

Confidence (0–1) reflects how much to trust the verdict, combining:
- **Data sufficiency** — coverage, sample count, history length.
- **Signal strength** — how far from thresholds/baseline (effect size), sustain duration.
- **Consistency** — recurrence and low contradiction among inputs.
- **Quality** — proportion of clean vs suspect/interpolated samples.

Low confidence is shown, not hidden ("Confidence 0.54 — only 9 days of history"). This
prevents overconfident calls on thin data and tells the engineer how hard to lean on it.

## 6. Recommended action

Each verdict ships an action template resolved with context:
| Verdict | Recommended action (example) |
| --- | --- |
| Critical Congestion | Investigate now; check peer/uplinks; consider QoS; open RCA. |
| Capacity Planning Required | Plan upgrade within recommended window (doc 11); add to Weekly Capacity Report. |
| Recurring BH Congestion | Confirm organic growth vs incident; schedule capacity review. |
| Traffic Pattern Changed | Compare to maintenance/change events; verify expected vs anomalous. |
| Weekend Backup Traffic | Confirm backup schedule is intended; reclassify if mislabeled. |
| RX/TX Imbalance | Check asymmetric routing / unidirectional flows / mirror/SPAN misconfig. |
| Idle / Under-utilized | Candidate for consolidation/reclaim; verify still in service. |
| Data Quality Issue | Fix ingestion/gaps before trusting health (links to Validation). |

## 7. AI Summary layer (natural-language rendering)

Above the structured verdict sits a concise NOC-engineer-style narrative (doc 13):

> "This interface exceeded business-hour thresholds on **14** occasions this month.
> Utilization has increased **18%** over the previous month. At the current growth rate,
> capacity expansion should be planned within approximately **60 days**."

The AI summary is **grounded**: it is generated from the verdict's structured fields and
evidence, never free-invented. If the model is unavailable, a deterministic template
renders the same facts — the platform never depends on the LLM to state truth.

## 8. Lifecycle, stability & history

- Verdicts are **re-evaluated incrementally** after each commit/window for affected
  entities.
- **Hysteresis** (via the rule state machine, doc 07 §4) prevents verdict flapping; a
  verdict must clear its condition before flipping back.
- Verdicts are **versioned and historized** — the Timeline (doc: Timeline) shows how an
  interface's verdict evolved, and a past report reproduces the exact verdict it cited.
- Superseded verdicts remain queryable for audit and RCA ("this link was Critical for 6
  business days in July").

## 9. Rollup verdicts (device/site/customer/executive)

Higher altitudes get **aggregated verdicts** derived from their children, weighted by
business impact: a Site verdict summarizes its worst/most-impactful interface verdicts
plus site-level capacity/risk. This gives every dashboard level a leading conclusion in
the same language, consistent from Interface up to Executive.
