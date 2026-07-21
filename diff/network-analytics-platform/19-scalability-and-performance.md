# 19 — Scalability & Performance Strategy

NetPulse must run at **10 → 100 → 1000+ sites, 1000+ devices, 100,000+ interfaces, and
millions of polling records** without a redesign. Scale is a day-one architectural
constraint, achieved primarily through **pre-aggregation, partitioning, incremental
computation, and honest UX** — not brute force.

## 1. Scale targets & the core idea

| Dimension | Target |
| --- | --- |
| Sites | 10 → 1000+ |
| Devices | up to 1000s per site, 100k+ total |
| Interfaces | 100,000+ |
| Samples | millions/day, billions retained |

**The core idea:** the interactive path **never scans raw samples.** It reads
**pre-computed rollups and derived artifacts** (verdicts, forecasts, risk, baselines).
Raw is touched only for RCA detail and precise timelines. This bounds query cost by the
size of the *answer*, not the size of the dataset.

## 2. Storage architecture

- **Time-series store** for samples/rollups (partitioned by time + entity; columnar,
  compressed). Choose a TSDB / columnar analytical store suited to append-heavy,
  range-query workloads.
- **Relational/graph store** for the entity model, config, RBAC, audit (moderate size,
  strong consistency).
- **Object storage** for original uploads and generated reports (cheap, immutable).
- **Rollup tiers** (doc 03 §3.1): raw (90d hot) → 5m (13mo) → 1h (3y) → 1d (indefinite),
  each carrying avg/max/p95/p99 + state-time breakdown. Retention per tier is
  configurable; hot/warm/cold tiering keeps cost sane.

## 3. Ingestion at scale

- **Partitioned, parallel ingestion** by entity (site/device sharding); multiple uploads/
  streams processed concurrently.
- **Idempotent, keyed writes** (doc 04 §6) so replays/backfills don't double-count and can
  run in parallel safely.
- **Incremental rollup updates:** only touched (entity, time-bucket) pairs recompute on
  commit — cost proportional to *new* data, not total data.
- **Backpressure & batching** protect the store under bursty uploads or high-rate streams.

## 4. Analytics at scale (incremental everywhere)

- **Dirty-set recomputation** (doc 08 §6): each commit/stream-close publishes
  `(entity, dirty_range)`; only affected rollups → baselines → metrics → verdicts →
  anomalies → forecasts → risk recompute. Nothing global recomputes on every upload.
- **Tiered forecasting** (doc 11 §9): cheap trend forecasts for all entities frequently;
  expensive seasonal/ML models prioritized for high-impact/fast-growing links.
- **Async heavy jobs:** baseline rebuilds, forecasts, and large reports run on a worker
  pool and **publish** results; the UI reads the latest published artifact with a
  freshness stamp — never blocks on compute.
- **Horizontal scale:** stateless API + worker tiers scale out; the stores scale by
  partitioning. Add nodes, not redesigns.

## 5. Query & API performance

- **Serve from rollups/derived tables**, resolution chosen by range (doc 08 §2) — a
  1-year trend reads 1d buckets, a day-view reads 5m.
- **Pre-computed rankings** (Top-N, NOC queue, risk order) maintained incrementally so the
  hottest screens are near-instant reads.
- **Caching** of dashboard aggregates and twin colorings with targeted invalidation on
  the dirty set.
- **Pagination + server-side filtering/sorting** for all large lists; the API never
  returns 100k rows to the client.

## 6. Frontend performance (100k interfaces stay fluid)

- **Virtualized tables** (render only visible rows) for entity grids.
- **Level-of-detail Digital Twin** (doc 16 §5): only the focused level renders in detail;
  deeper levels lazy-load; canvas/WebGL for dense views.
- **Progressive loading:** verdict + KPIs first, heavy charts and Insight-rail panels
  stream in async with skeletons.
- **Windowed time-series rendering:** charts request only the points needed for the
  visible range/resolution; downsampled server-side (the rollups do this naturally).

## 7. Reliability & operations (SRE)

- **Stateless services** behind a load balancer; **worker queue** for async analytics/
  reports with retries and dead-lettering.
- **Idempotency + versioned artifacts** make recovery and reprocessing safe.
- **Observability:** platform self-monitoring (ingestion lag, rollup freshness, job
  queue depth, query latency) — NetPulse watches its own health.
- **Graceful degradation:** if the AI model or a heavy job is unavailable, deterministic
  fallbacks (template narratives, cached artifacts) keep the core usable.
- **Multi-tenancy:** scope-partitioned data and compute for MSP/ISP deployments.

## 8. Cost & capacity of the platform itself

- Retention tiering + compression keep storage growth sub-linear to raw volume.
- Incremental compute keeps CPU proportional to *new* data, not fleet size.
- Prioritized expensive analytics (forecasts/ML) spend compute where business value is
  highest first.

## 9. Growth path without redesign

Because dashboards read a **stable derived-artifact contract** (docs 03/08) and
ingestion is **source-agnostic** (doc 04), every scaling lever — more shards, more
workers, a bigger TSDB, a new data source, streaming instead of batch — is an operational
change **behind** that contract. The screens, engines, and data model don't change. That
is the definition of "scales without redesign."
