# 07 — Rule Engine Design

The Rule Engine lets administrators encode operational policy **as data, not code.**
It converts raw metrics + context into *states* and *events* that the Verdict Engine
(doc 09) turns into judgments. Its design goals: configurable without deployment,
composable, testable, versioned, and auditable.

## 1. What a rule is

A rule is a declarative structure:

```
RULE
  name, description, enabled, priority, version
  SCOPE     — which entities it applies to (selector)
  WHEN      — temporal/context predicate (calendar, maintenance)
  IF        — metric condition(s) with operators + duration ("FOR")
  COMPARE   — optional baseline comparison (vs previous period)
  THEN      — outcome: set state / raise event / assign verdict level / tag
  FOR       — sustain window (debounce; must hold this long)
  ELSE      — optional alternate outcome
```

### Example rules (from the requirements, made concrete)
```
R1  IF Business Hours AND util_pct > 75 FOR 30m           THEN state = Critical
R2  IF Weekend AND util_pct > 90                          THEN state = Warning
R3  IF traffic_MoM_change > 20%                           THEN event = CapacityReview
R4  IF class = Trading AND util_pct > 60 FOR 15m          THEN state = High     (stricter for trading)
R5  IF oper_status = down DURING NOT maintenance FOR 5m   THEN event = LinkDown
R6  IF rx/tx imbalance ratio > 5 sustained               THEN event = ImbalanceAnomaly (hand to doc 10)
```

## 2. Rule anatomy in detail

### 2.1 Scope selector (which entities)
A boolean selector over entity attributes, evaluated against the entity model:
```
scope: class in [Core, Trading]  AND  site = LON-DC1  AND  business_impact >= High
       [OR customer = ACME]  [OR interface_id in {…}]
```
Specificity: **Interface > Customer > Site > Class > Global.** A more specific rule's
threshold set overrides a broader one for the same metric (see §5 precedence).

### 2.2 WHEN — temporal/context predicate
References **Calendars** and **Maintenance** (doc 03 config model):
- `Business Hours` / `Business Days` — per-site or per-customer calendar.
- `Weekend` / `Holiday` — holiday calendar aware.
- `Maintenance Window` — usually used to **suppress** (e.g., `WHEN NOT maintenance`).
- Custom windows (e.g., "market open 09:30–16:00 America/New_York" for trading).

### 2.3 IF — metric condition
- Metrics: `util_pct`, `util_tx_pct`, `util_rx_pct`, `tx_bps`, `rx_bps`, `errors`,
  `discards`, `rx_tx_ratio`, `oper_status`, plus derived (`p95_1h`, `slope_7d`).
- Operators: `> >= < <= == != between`, `rate-of-change`, `crosses`.
- Aggregation: raw sample, or a rollup statistic (`p95 over 1h`), configurable.

### 2.4 COMPARE — baseline predicate
References the Baseline store (doc 08): `util_pct > baseline(same_weekday_hour) * 1.2`,
or `traffic_MoM_change > 20%`. This is what powers "Traffic Increased >20% vs previous
month → Capacity Review".

### 2.5 FOR — sustain / debounce
A condition must hold for `FOR` duration before firing, and (optionally) clear for a
`recovery` duration before resetting. This eliminates single-sample flapping and is
essential for "> 75% **for 30 minutes**". Implemented as a per-entity state machine
(§4).

### 2.6 THEN — outcome
- `set_state`: Normal / Warning / High / Critical (feeds the pie distribution + verdict).
- `raise_event`: typed operational event (LinkDown, CapacityReview, ImbalanceAnomaly…)
  that lands on the Timeline and can seed an RCA case.
- `assign_tag` / `set_priority`: enrich the entity.
- `route`: hand off to Anomaly (doc 10) or Capacity (doc 11) engines for deeper analysis.

## 3. Threshold sets (reusable bands)

Rather than hard-coding numbers in each rule, thresholds live in named,
assignable **threshold sets**:

```
ThresholdSet "Trading-Core"   Normal <50 · Warning 50–70 · High 70–85 · Critical >85
ThresholdSet "Backup-Default" Normal <70 · Warning 70–85 · High 85–95 · Critical >95
```
Sets are assigned by class/site/customer/interface. Rules reference the *resolved* set
for the entity, so changing a band updates every dependent rule at once. This is the
mechanism behind class/site/customer/interface-specific policies.

## 4. Evaluation model (how rules run)

```
For each entity, on each new sample or rollup close:
  1. Resolve applicable rules (scope) + resolved threshold set + calendar/maintenance.
  2. Evaluate WHEN (context) — skip suppressed contexts (maintenance).
  3. Evaluate IF/COMPARE → candidate condition true/false.
  4. Feed candidate into the entity's per-rule STATE MACHINE (handles FOR / recovery).
  5. On state transition → emit state change + event(s), write Timeline entry.
  6. Hand resulting states/events to the Verdict Engine (doc 09).
```

- **State machine per (entity, rule):** `clear → pending(FOR timer) → active →
  recovering → clear`. Guarantees debounce, one event per episode, and clean
  start/stop timestamps that RCA reuses ("when did it start / how long").
- **Batch vs stream:** in the Excel era this runs over each committed batch's window
  incrementally; in the streaming era the identical machine runs continuously. Same code,
  same results — the ingestion abstraction (doc 04) makes this transparent.

## 5. Conflict resolution & precedence

When multiple rules match one entity:
1. **Specificity wins** (Interface > Customer > Site > Class > Global) for threshold
   resolution.
2. **Severity wins** for state (the highest asserted state stands), unless a rule is
   marked `override`.
3. **Explicit priority** field breaks remaining ties.
4. **Maintenance suppression** always wins (a suppressed context yields no alert/state).
The Verdict Engine records *which* rules fired so the verdict's evidence is traceable.

## 6. Authoring experience (no-code builder)

Admin → Rules provides:
- A **guided builder** (Scope → When → If → For → Then) with live entity-count preview
  ("this rule matches 96 interfaces").
- A **plain-English preview** ("When it's business hours and utilization stays above 75%
  for 30 minutes on Trading/Core links, mark Critical").
- **Dry-run / backtest:** evaluate a draft rule against the last N days of history and
  show what it *would* have fired — before enabling it. Prevents alert storms.
- **Versioning:** every save creates a new `ruleset_version`; verdicts stamp the version
  used so history is reproducible and changes are diffable.
- **Audit:** who changed what rule/threshold/calendar, and when (doc 18).

## 7. Calendars, holidays & maintenance as rule inputs

- **Calendars** define business days/hours per site/customer (multi-timezone).
- **Holiday calendars** feed `Holiday`/`Weekend` predicates.
- **Maintenance windows** are consumed as suppression context and also tag samples
  (doc 04 §3.5) so trend/SLA math excludes them.
All three are admin-editable data objects — never code.

## 8. Why this scales and stays safe

- Rules compile to a compact evaluable form and run against **rollups** where possible,
  so 100k interfaces are feasible (doc 19).
- Dry-run + versioning + audit make policy changes **safe and reversible**.
- The clean separation — Rules produce *states/events*, Verdict Engine produces
  *judgments*, Anomaly/Capacity engines produce *deeper analysis* — keeps each layer
  simple and independently testable.
