# 11 — Capacity Planning & Forecasting Logic

Capacity planning turns preserved history into forward-looking decisions: **when** each
link runs out of headroom, and **when to upgrade**. This is the Architect's core value
and a headline differentiator.

## 1. Outputs (what every forecastable entity gets)

- **Projected utilization** at **30 / 60 / 90 / 180 days**.
- **Time-to-threshold:** estimated dates to reach **80% / 90% / 95%**.
- **Recommended upgrade window** (a date range, not a single date).
- **Confidence level** + confidence band on the projection.
- **Headroom** now and projected; and, where relevant, projected **breach count**.

## 2. Inputs (from the analytics engine, doc 08)

- **p95 (and p99) utilization trend** on the 1h/1d rollups — p95 is the planning metric
  (resilient to momentary spikes) with p99/max shown for burst context.
- **Growth features:** robust trend **slope**, MoM/WoW/QoQ growth, seasonality profile.
- **Volatility:** variability drives the confidence band width.
- **Effective speed** (doc 03 §2.2) so an upgraded link's history isn't misread.
- **Maintenance/anomaly exclusions** so planned work and one-off spikes don't skew trend.

## 3. Forecasting method (layered, explainable)

NetPulse favors **transparent, defensible** forecasting over opaque black boxes — an
architect must be able to justify a capex decision.

1. **Trend model (baseline):** robust linear/Theil–Sen regression on the p95 trend →
   slope + intercept, resistant to outliers. Gives the primary projection and
   time-to-threshold.
2. **Seasonal-aware model:** decompose level + weekly/monthly seasonality (and
   business-cycle effects) so forecasts reflect that weekday peaks, not 24×7 averages,
   are what saturate a link. Peak-hour projection is what matters, not the mean.
3. **Growth-rate model:** compound growth for links showing accelerating (non-linear)
   demand; compared against the linear model and the better fit is chosen/blended.
4. **Ensemble & selection:** fit candidates, select/blend by backtested fit (§5); expose
   which model was used. (Advanced ML models — e.g. gradient-boosted or
   Prophet/ARIMA-style — can plug in later behind the same output contract.)

Projections are computed against **peak-period p95**, so "time-to-90%" means the link's
*busy-hour* utilization crosses 90%, which is the operationally correct trigger.

## 4. Time-to-threshold & upgrade window

```
time_to_T = date when projected p95 crosses T   (80/90/95)
upgrade_window = [ time_to_90 − lead_time − buffer ,  time_to_90 − lead_time ]
```
- **Lead time** (procurement + change-window + install) is configurable per site/vendor
  (e.g., 6 weeks) so the recommended window accounts for how long an upgrade *actually*
  takes — the platform recommends acting *before* saturation, not at it.
- **Buffer** reflects confidence: wider uncertainty → earlier, wider window.
- Example output: *"Time-to-90% ≈ 52 days; with a 6-week lead time, schedule the upgrade
  in the **45–60 day** window; confidence 0.82."*

## 5. Confidence & accuracy

- **Confidence** derives from: history length, goodness-of-fit (backtest error),
  volatility, data coverage/quality, and model agreement.
- **Backtesting:** periodically hold out recent history, forecast it, measure error
  (MAPE); surface accuracy so users calibrate trust and the engine self-selects models.
- **Confidence band:** projections render with an uncertainty envelope, never a false
  single line. Low-confidence forecasts are labeled ("only 3 weeks of history — directional").

## 6. Scope aggregation (interface → device → site → customer → infra)

- **Interface** is the atomic forecast.
- **Device/Line-card:** aggregate demand vs card/backplane capacity → identify cards
  that will saturate even if individual ports look fine.
- **Site:** edge/uplink aggregate capacity vs projected demand; count of links breaching
  in each horizon.
- **Customer/Service:** contractual capacity view for account management.
- **Infrastructure:** executive roll-up — "N links breach 90% within 90 days across M
  sites" — feeding the Executive Dashboard and Capacity Forecast report.

## 7. Rule integration (proactive triggers)

The rule engine's COMPARE predicate (doc 07) plus forecasts create proactive verdicts:
- `IF traffic increased >20% vs previous month → Capacity Review` (verdict: Capacity
  Planning Required).
- `IF forecast time-to-90% within planning horizon AND positive growth → Capacity
  Planning Required`.
These land on the NOC/Capacity dashboards **before** the link is actually congested.

## 8. Reports & sequencing

- **Weekly Capacity Report** and **Capacity Forecast** (doc 15) list entities by
  time-to-threshold, with recommended windows and confidence, plus an AI narrative and
  a **recommended upgrade sequence** prioritized by business impact × urgency (a
  High-impact link at 45%-and-accelerating can outrank a Low-impact link already at 88%).
- Exportable to PDF/XLSX for change boards and finance.

## 9. Scale & performance

- Forecasts run **asynchronously** on 1d/1h rollups (not raw), scheduled and
  incremental; the UI reads the latest published forecast with a freshness stamp.
- Cheap linear/trend forecasts can refresh frequently for all entities; expensive
  seasonal/ML models run for **high-impact or fast-growing** links first (prioritized by
  business impact and slope), keeping compute bounded at 100k-interface scale (doc 19).
