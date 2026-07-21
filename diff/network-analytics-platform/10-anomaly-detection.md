# 10 — Anomaly Detection

Thresholds answer "is it high?"; anomaly detection answers "is it **abnormal for this
link**?" A backup link at 95% every night is not an anomaly; a business link with
sudden Sunday traffic is — even at 30%. NetPulse detects behavioral change, not just
level, and **explains** every flag.

## 1. Philosophy

- **Baseline-relative, not threshold-only.** Uses the seasonal baselines and features
  from doc 08 (day-of-week × hour profiles, robust stats, change-points).
- **Explainable by construction.** Every anomaly carries a type, the expected-vs-actual
  evidence, and a plain-English reason. No unexplained "score = 0.91".
- **Layered / ensemble.** Multiple lightweight detectors, each good at one anomaly
  class, are combined and deduplicated — more robust and more interpretable than one
  opaque model.
- **Quality- and maintenance-aware.** Interpolated/suspect samples and maintenance
  windows are excluded so we don't flag our own data gaps or planned work.

## 2. Anomaly types (the catalog) and how each is detected

| # | Anomaly type | Signal / method | Evidence shown |
| --- | --- | --- | --- |
| 1 | **Unexpected traffic spike** | value ≫ baseline(dow,hour) by k·σ (robust z / MAD); short duration | actual vs baseline band, spike window |
| 2 | **Unusual traffic time** | activity in a normally-idle cell (e.g., 03:00 business link) | heatmap cell lit outside normal envelope |
| 3 | **RX/TX imbalance** | `rx_tx_ratio` departs sustainedly from the link's own norm | directional split chart, ratio trend |
| 4 | **New traffic pattern** | change-point detection on level/variance/shape; new recurring cluster | change-point marker, before/after profiles |
| 5 | **Weekend traffic on business links** | weekend cells active on a class=Core/Trading link with weekday-only baseline | weekday vs weekend heatmap |
| 6 | **Sudden traffic reduction** | drop ≫ baseline (possible outage/rerouting/mistake) | drop window, peer correlation |
| 7 | **Long-duration congestion** | sustained High/Critical far beyond typical episode length | duration vs historical episode distribution |
| 8 | **Post-maintenance behavior change** | baseline before vs after a maintenance window differs materially | pre/post overlay aligned to window |

## 3. Detection methods (ensemble)

- **Seasonal residual + robust z-score:** compare each sample to its baseline cell mean;
  score by `(x − median)/MAD`. Robust to outliers; flags spikes/drops/unusual-time.
- **Change-point detection:** detect shifts in mean/variance of the rollup series
  (e.g., CUSUM / Bayesian online change-point style). Flags *new patterns* and dates
  them precisely (RCA reuses this as "when did it start").
- **Directional-balance monitor:** track `rx/tx` ratio vs its own distribution → imbalance.
- **Episode-length model:** learn the distribution of congestion-episode durations per
  link; a far-longer episode is anomalous even at the same level.
- **Calendar-aware presence:** learn *when* a link is normally active; presence outside
  that envelope (weekend/off-hours) is flagged relative to class expectations.
- **(Optional/advanced, future):** matrix-profile / ML models can slot in behind the same
  interface, since detectors are pluggable and outputs are standardized.

## 4. Scoring, severity & suppression

- **Anomaly score** combines effect size (how far from baseline), duration, and
  consistency into 0–1.
- **Severity** = anomaly score **weighted by business impact and class** (an anomaly on
  a Critical trading link outranks the same on a Low backup link) — this is what makes
  the NOC feed impact-ranked, not noise-ranked.
- **Suppression / noise control:**
  - Maintenance windows suppress (doc: Maintenance Awareness).
  - Known/acknowledged patterns can be **muted** with reason (e.g., "backup runs
    Sundays — expected") and the mute is audited and time-bounded.
  - **Correlated grouping:** many interfaces flagging together (a card/device event) are
    grouped into one incident rather than N alerts.
  - Hysteresis prevents an anomaly toggling on/off around the boundary.

## 5. Explanation (every anomaly says why)

Each anomaly produces a grounded sentence, e.g.:
> "Traffic on **Sun 07-19 02:00–04:00** reached **~40%** on a business-classified link
> that is normally **idle** on weekends (baseline < 3%). This is a **new pattern**,
> first seen **2 weeks ago**, recurring weekly — consistent with a newly scheduled
> backup job." (evidence: weekend heatmap + change-point + peer correlation)

Explanations are generated from the structured detection output (type, expected, actual,
first-seen, recurrence, correlation) — the AI layer renders prose, the detector owns the
facts (doc 13 grounding rule).

## 6. Feeding the rest of the platform

- **Verdict Engine (09):** dominant anomaly type can drive verdicts like "Traffic
  Pattern Changed", "Weekend Backup Traffic", "RX/TX Imbalance".
- **RCA (14):** anomaly start/duration/recurrence/correlation pre-answer RCA questions.
- **Timeline:** anomalies pin onto the entity's operational timeline and Traffic Timeline.
- **Risk (12):** anomaly frequency contributes to risk score.
- **Anomaly Feed (screen):** a ranked, filterable list across the fleet.

## 7. Data-scale considerations

- Detectors run on **rollups** (5m/1h) by default, dropping to raw only when confirming a
  flagged window — keeps 100k interfaces feasible (doc 19).
- Detection is **incremental**: only entities with new/dirty windows are re-evaluated per
  commit/stream close.
- Baselines exclude anomalous and maintenance periods so detectors don't learn the very
  events they should catch.
