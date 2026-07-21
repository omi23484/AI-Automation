# 17 — UI/UX Design System & Visualizations

The UI must feel like a **modern data-center operations center**: premium, dark, fluid,
and calm under pressure — not a generic BI dashboard. This document defines the visual
language, the component system, and the visualization catalog with rules for when each
is used.

## 1. Design language

- **Dark-first, operations-center aesthetic.** Deep neutral background (near-black
  blue-graphite), luminous data, restrained chrome. Light theme available but dark is
  the primary, wall-friendly experience.
- **Subtle glassmorphism.** Panels are frosted, slightly translucent surfaces with soft
  depth — used to layer the Insight rail and overlays over the evidence canvas, never so
  heavy that it hurts legibility or contrast.
- **Fluid motion.** Meaningful transitions (drill-down zoom in the twin, panel reveals,
  value counters) that orient the user and imply spatial continuity. Motion is
  purposeful and fast (150–300ms); respects `prefers-reduced-motion`.
- **Calm signal, loud only when it matters.** Healthy state is quiet; severity earns
  color and subtle motion (a pulsing red LED) so the eye goes to what's wrong.
- **Digital-twin feel throughout.** Navigation implies moving *through* a building
  (docs 02/16), reinforced by breadcrumbs, depth, and consistent spatial metaphors.

## 2. Color system (semantic, accessible, theme-aware)

- **Severity/state palette** (used everywhere consistently — verdicts, LEDs, heatmaps):
  Normal, Warning, High, Critical, plus Down and No-Data/Maintenance. Distinct hue **and**
  brightness so states are distinguishable in both themes and for color-vision
  deficiency; never rely on hue alone (add icon/label/shape).
- **Categorical palette** for classes/series — a curated, non-clashing set with stable
  assignment (a class keeps its color across the app).
- **Sequential/diverging palettes** for heatmaps (utilization, risk, deviation) with
  perceptually-uniform ramps; diverging for "vs baseline" (below/above normal).
- **WCAG AA** contrast for text and essential UI in both themes; charts carry redundant
  encodings (labels, patterns) so meaning survives grayscale.
- (Implementation note: follow the `dataviz` design-system method — a validated color
  formula, mark specs, and interaction rules — when the charts are actually built.)

## 3. Typography & layout

- **Type:** a clean technical sans for UI, a tabular/monospaced variant for metrics and
  tables (aligned digits matter in a NOC). Clear hierarchy: verdict > metric > label.
- **Grid & spacing:** consistent 8px spacing system; the shared page anatomy (doc 02 §6)
  is a reusable layout template so every screen feels the same.
- **Density modes:** comfortable (default) and compact (power users / large tables /
  wall). Tables are virtualized and support column choice, sort, and saved views.

## 4. Component library (design-system primitives)

| Component | Role |
| --- | --- |
| **Verdict banner / card** | The leading conclusion: level color, title, reason, confidence, action. |
| **KPI stat tile** | One number + trend arrow + factor tooltip (no gauges). |
| **Risk badge** | 0–100 with color + expandable factor breakdown (doc 12). |
| **Impact badge / class chips** | Business impact + class tags on every entity. |
| **Insight rail** | Right-side stack: AI summary, anomalies, forecast, related, timeline. |
| **Time-range + "compare to" control** | Range picker + baseline selector (doc: baselines). |
| **Chart frame** | Consistent title, legend, threshold bands, maintenance shading, export. |
| **Entity table (virtualized)** | Impact/risk-ranked grid scaling to 100k rows. |
| **Twin canvas** | LOD spatial renderer (doc 16). |
| **Command bar (⌘K)** | Search + actions + NL query (doc 02 §5, doc 13). |
| **Toast / status strip** | Non-intrusive system + NOC status. |

All components are themeable, responsive, and accessible (keyboard-navigable,
ARIA-labeled). Focus states and hit targets are generous for on-call use.

## 5. Visualization catalog (every chart earns its place)

**Principle: no gauges; every visualization must give operational value.**

| Visualization | Primary use | Why here (not a gauge) |
| --- | --- | --- |
| **Line chart** | Utilization/traffic over time (TX/RX, peak overlay) | The core evidence; shows shape, not just a number. |
| **Area chart** | Aggregate/stacked traffic (site/device totals, in vs out) | Volume + composition over time. |
| **Heatmap (day × hour)** | Utilization/health rhythm of a link/device | Reveals *when* congestion clusters — invaluable for RCA. |
| **Calendar heatmap** | Long-range daily intensity (months) | Seasonality, weekend patterns, trend at a glance. |
| **Pie / distribution** | % of intervals in Normal/Warning/High/Critical (doc 08 §5) | Time-in-state, not a peak — with AI explanation beneath. |
| **Histogram** | Utilization value distribution | Shows how often a link runs hot vs the tail. |
| **Sparklines** | Inline trend in tables / twin hovers / related lists | Dense context without leaving the row. |
| **Top-N ranking** | Busiest/growing/critical/idle links | The operational shortlist, impact-weighted. |
| **Capacity trend chart** | Forecast with confidence band + threshold crossings | Turns history into a decision (time-to-90%). |
| **Change-point / event overlay** | Markers on the time axis (violations, maintenance, RCA) | Ties metrics to operational events (Traffic Timeline). |

Each chart frame supports: threshold bands, maintenance shading, baseline overlay,
zoom/scrub, hover detail, and one-click export — consistently.

## 6. Interaction & information-scent rules

- **Verdict first, chart second, detail on demand.** Progressive disclosure: conclusion
  → evidence → raw. Users never hit a wall of graphs with no guidance.
- **Everything drillable and cross-linked.** Click a top-N row, a heatmap cell, a twin
  LED, or an evidence link and land on the right deeper view with scope preserved
  (doc 02 §5).
- **Consistent controls.** Time range, compare-to, scope filters live in the same place
  on every screen.
- **Explainability affordances.** Any score/verdict/anomaly exposes its "why" on hover or
  click; nothing is a mystery.
- **Empty/loading/low-confidence states** are designed, honest, and helpful ("only 9 days
  of history — forecast is directional"), never blank or falsely confident.

## 7. Operational UX considerations

- **Wall mode & focus mode** (doc 05 §5.18): fullscreen auto-rotating overview for video
  walls; stripped single-verdict view for phone/tablet triage.
- **Performance UX:** virtualization, skeleton loaders, async panels with freshness
  stamps — the UI stays responsive at fleet scale (doc 19) and is honest about staleness.
- **Accessibility:** full keyboard nav, screen-reader labels on data, reduced-motion and
  high-contrast options, colorblind-safe encodings — a NOC runs 24/7 for everyone.
- **Consistency = speed.** Because every screen shares anatomy, components, colors, and
  interactions, an engineer's muscle memory transfers everywhere, which matters most at
  03:00 during an incident.
