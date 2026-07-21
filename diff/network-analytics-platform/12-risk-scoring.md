# 12 — Risk Scoring Model

Risk scoring produces a single, comparable **0–100** number per entity so users can
rank attention across a fleet of 100k interfaces. It is **transparent** — every score
decomposes into its contributing factors — and **business-aware** — importance, not just
utilization, drives it.

## 1. Scored entities

`Interface · Device · Site · Customer · Overall Infrastructure` — computed bottom-up
and rolled up, weighted by business impact.

## 2. Factors (inputs)

| Factor | Signal | Why it matters |
| --- | --- | --- |
| **Peak utilization** | recent p99/max busy-hour | proximity to saturation |
| **Average / sustained utilization** | p95 time-in-High/Critical | chronic pressure, not one spike |
| **Trend** | slope of p95 | is it getting worse? |
| **Growth** | MoM/QoQ growth rate | speed toward the wall |
| **Violations** | rule breaches (business-hour Critical count, duration) | operational pain already occurring |
| **Anomalies** | frequency/severity of behavioral anomalies (doc 10) | instability / surprise |
| **Historical behavior** | volatility, recurrence, past incidents | reliability track record |
| **Business criticality** | Business Impact + Class | consequence if it fails |
| **Forecast urgency** | time-to-90% within horizon | imminent capacity risk |
| **Data quality** | coverage/suspect ratio | discounts confidence in the score |

## 3. Scoring model (transparent, weighted)

```
raw_risk = Σ (weight_f × normalized_factor_f)         # each factor scaled to 0–1
risk_0_100 = 100 × clamp(raw_risk)
final_risk = risk_0_100 × business_impact_multiplier  # then re-clamped to 0–100
```

- **Normalization:** each factor is mapped to 0–1 with sensible curves (e.g.,
  utilization uses a non-linear curve so 60→70% moves risk less than 85→95%).
- **Weights** are **configurable per class/policy** (Admin) — trading links can weight
  peak + business-hour violations higher; backup links weight sustained saturation
  lower. No code change.
- **Business impact multiplier:** Critical > High > Medium > Low re-orders the fleet so
  a moderately-utilized Critical link can outrank a hot Low-impact link.
- **Confidence-adjusted:** thin/low-quality data widens uncertainty and is shown
  alongside the score (a high score on 5 days of data is labeled as such).

## 4. Explainability (factor breakdown)

Every score exposes its decomposition — a small bar/segmented breakdown and text:
> "Risk **72/100** — driven by Business Impact (Critical), business-hour violations
> (14 in 30d), and growth (+18% MoM). Peak 88%, trend rising. Confidence 0.86."

Hovering any risk number anywhere in the product reveals this breakdown; nothing is a
mystery number. This is essential for trust and for defensible reporting.

## 5. Aggregation (roll-up logic)

- **Device risk** = impact-weighted aggregate of its interfaces' risk, plus
  device-level signals (a saturating line card raises the device even if ports differ).
- **Site risk** = impact-weighted aggregate of device risks + site edge/uplink capacity.
- **Customer risk** = aggregate over that customer's interfaces (contractual lens).
- **Infrastructure risk** = weighted aggregate across sites — the single Executive
  Dashboard number, with its own trend arrow and factor breakdown.

Aggregation uses **impact-weighted, worst-case-sensitive** blending (not a naïve mean),
so one Critical exposure isn't averaged away by many healthy links — but many small
issues still accumulate.

## 6. Uses across the platform

- **Ranking:** NOC queue, Top Critical Links, and every entity table sort by
  `business_impact × risk × confidence`.
- **Heatmaps:** site/device risk heatmaps (doc 05) are colored by risk.
- **Verdicts:** risk feeds verdict ranking (doc 09 §3) and severity emphasis.
- **Reports:** Business Impact Report and Executive Summary lead with risk and its drivers.
- **Trend of risk:** risk is historized, so "infrastructure risk is up 6 points this
  month" is answerable and chartable.

## 7. Stability & scale

- Recomputed **incrementally** per commit/window for affected entities; rolled-up scores
  recompute up the tree only where children changed.
- **Smoothed** over a short window to avoid score flapping from single samples, while
  still reacting to genuine step changes (a new violation or anomaly moves it promptly).
- Runs on derived metrics (doc 08), not raw scans — feasible at 100k-interface scale.
