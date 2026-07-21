# 08 — Analytics Engine Design

The Analytics Engine is the computation layer that sits between raw samples and the
higher-order engines (Verdict, Anomaly, Capacity, Risk, RCA). It owns **rollups,
baselines, distributions, deviations, and derived metrics**, and it is designed to run
**incrementally** so 100k interfaces and millions of samples stay responsive.

## 1. Architecture

```
        Committed samples (per batch / per stream window)
                     │
        ┌────────────▼─────────────┐
        │  1. Rollup builder        │  raw → 5m → 1h → 1d (avg/max/p95/p99/min + state time)
        └────────────┬─────────────┘
        ┌────────────▼─────────────┐
        │  2. Baseline builder      │  per-entity seasonal profiles (dow × hour)
        └────────────┬─────────────┘
        ┌────────────▼─────────────┐
        │  3. Metric/feature layer  │  slopes, MoM/WoW deltas, distribution, imbalance
        └────────────┬─────────────┘
        ┌────────────▼─────────────┐
        │  4. Fan-out to engines    │  Rule/Verdict · Anomaly · Capacity · Risk · RCA
        └───────────────────────────┘
```

Everything downstream reads **derived** artifacts, not raw scans — that's the
performance contract.

## 2. Rollups (pre-aggregation)

- On each commit, only **touched (interface, time-bucket)** pairs are recomputed
  (incremental, idempotent). Late/backfilled data re-versions just the affected buckets.
- Each bucket stores: `avg, max, min, p95, p99, sample_count, tx/rx split,
  state_time_breakdown{normal,warning,high,critical seconds}, quality_counts`.
- **`state_time_breakdown` is the key trick:** the pie/distribution analytics (time
  spent in each utilization state) and "exceeded threshold N times / for M minutes"
  come straight from rollups without rescanning raw samples.
- Query planner picks the **coarsest resolution that satisfies the range**: an
  interface day-view uses 5m; a 1-year trend uses 1d. This bounds cost regardless of
  fleet size.

## 3. Baselines (seasonal normal)

Baselines answer "what's normal for *this* entity at *this* time?" — the reference for
Historical comparison (doc: Historical Baselines), the COMPARE predicate (doc 07), and
anomaly detection (doc 10).

- **Dimensions:** day-of-week × hour-of-day is the primary seasonal grid; also
  hour-of-day, and rolling recent windows. Separate profiles for business vs
  weekend/holiday when calendars indicate distinct regimes.
- **Statistics per cell:** mean, stddev, median, p95, sample count, last-updated.
  Robust stats (median/MAD) preferred so a single spike doesn't distort "normal".
- **Windows:** trailing 4–8 weeks (configurable), **excluding maintenance windows** and
  known-anomalous periods so the baseline isn't polluted by the very events we detect.
- **Comparisons supported:** yesterday, last week, **same weekday**, previous month,
  previous quarter — each is a specific slice/aggregation of the baseline + rollups.
- **Deviation metric:** current vs baseline expressed as %Δ and as a z-score
  `(x − mean)/stddev`, so both humans ("18% above same-weekday") and engines (threshold
  on z) can consume it.

## 4. Derived metrics / feature layer

Computed per entity, cached, and refreshed incrementally:

| Metric | Definition | Consumed by |
| --- | --- | --- |
| `p95_1h`, `p95_1d` | percentile rollups | Verdict, Capacity, Reports |
| `slope_Nd` | linear/robust trend slope over N days | Trend, Capacity, Risk |
| `growth_MoM`, `growth_WoW`, `growth_QoQ` | % change vs prior period | Trend, Rule COMPARE, Risk |
| `distribution` | % of intervals in Normal/Warning/High/Critical | Pie analytics, Verdict |
| `time_in_state` | seconds/percent per state, business vs off-hours | Verdict, RCA |
| `rx_tx_ratio` / imbalance | directional balance over time | Anomaly (imbalance) |
| `change_points` | timestamps where behavior shifted (level/variance) | Anomaly, RCA, Trend |
| `peak_profile` | when peaks cluster (hour/dow) | Verdict, RCA, AI summary |
| `volatility` | variability of utilization | Risk, forecast confidence |

## 5. Utilization distribution analytics (the "smart pie")

Instead of a peak gauge, NetPulse computes, over any range, the **fraction of polling
intervals** (or seconds) spent in each state, straight from `state_time_breakdown`:

```
Normal 62% · Warning 21% · High 12% · Critical 5%
  + split by business vs off-hours
  + trend of the distribution over time (is "Critical %" growing?)
```
This distribution is far more operationally meaningful than a single max: a link that
hits 95% for 2 minutes/day is very different from one at 80% for 6 hours/day. The
Verdict Engine and AI summary both read this distribution (doc 09), and the pie carries
a generated explanation beneath it ("Congestion clusters 09:30–11:00 on weekdays; 5% of
business-hour intervals were Critical").

## 6. Incremental & idempotent computation

- **Trigger:** every commit (Excel) or window close (stream) publishes a set of
  `(entity, dirty_range)` markers.
- **Recompute only the dirty set** across rollups → baselines → metrics → engines.
- **Idempotent:** recomputation is a pure function of samples + config version, so
  replays/backfills converge to the same result and can run in parallel.
- **Versioned outputs:** derived artifacts stamp `baseline_window`, `ruleset_version`,
  `model_version` so any report/verdict is reproducible later (doc 03 §9).

## 7. Handling data-quality realities

- **Gaps:** metrics note coverage; percentiles/slopes computed over available data with
  a coverage flag; charts render gaps explicitly (dashed / hatched), never fabricated.
- **Interpolated/suspect samples** (doc 04) are excluded from baselines by default and
  visibly marked in evidence.
- **Speed changes** (10G→100G) use the effective-dated speed (doc 03 §2.2) so historical
  utilization % stays correct across upgrades.
- **Maintenance** periods are excluded from baselines, SLA, and trend/growth math.

## 8. Compute topology & scale

- Batch/stream jobs are **partitioned by entity** (site/device sharding) so work
  parallelizes horizontally.
- Rollup and baseline stores are the **hot path**; raw is touched only for RCA/precise
  timelines. This is what keeps 100k interfaces interactive (doc 19).
- Heavy jobs (baseline rebuilds, forecasts) run **asynchronously** and publish results;
  the UI reads the latest published artifact and shows freshness/confidence rather than
  blocking on compute.

## 9. Contracts to downstream engines

| Engine | Reads | Gets |
| --- | --- | --- |
| Rule/Verdict (07/09) | states, distribution, time-in-state, COMPARE deltas | judgment inputs |
| Anomaly (10) | baselines, change-points, imbalance, volatility | anomaly candidates |
| Capacity (11) | slope, p95 trend, growth, volatility | forecast inputs + confidence |
| Risk (12) | peak, avg, trend, growth, violations | factor inputs |
| RCA (14) | change-points, peak profile, related-entity correlation, raw timeline | evidence |

Clean, versioned contracts mean each engine is independently testable and the analytics
layer is the single source of derived truth.
