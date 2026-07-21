# 06 — User Journeys

End-to-end narratives that thread the modules together. Each journey names the persona
(doc 01), the screens (doc 05), and the engines (docs 07–14) involved.

---

## Journey A — "03:00 congestion" (Sana, NOC Lead / L3)

**Trigger:** a business-hours congestion verdict surfaces on the NOC Dashboard.

1. Sana opens the **NOC Dashboard**; the Attention Queue is ranked by business impact.
   Top card: **● Critical Congestion — Core-01 Eth1/2 (Impact: Critical)**.
2. The card already tells her the *reason* ("p95 > 75% on 14 business days, +18% MoM").
   She clicks **Explain**.
3. The **RCA Assistant** (doc 14) auto-answers the standard questions:
   - *When did it start?* 12 days ago, first breach 2026-07-09 09:34.
   - *How long / recurring?* ~90 min/day, weekdays only — **recurring, business hours**.
   - *Previous occurrences?* Similar pattern last month (linked).
   - *Growth trend?* +18% MoM, slope rising.
   - *Related interfaces?* Uplinks Eth1/1 and the peer core show correlated rise.
   - *Maintenance correlation?* None.
   - *Likely cause?* Organic business-hour growth on a trading-class core link.
   - *Recommended next steps?* Plan capacity upgrade; review QoS; watch peer core.
4. She opens the **Interface Dashboard**, confirms the calendar heatmap shows the
   weekday-morning cluster, and reads the **AI Summary**.
5. She **annotates the Timeline** ("confirmed organic growth, not an incident"),
   **Acks** the verdict, and **Adds to the Weekly Capacity Report** for the architect.
6. All of this is **audited**; the annotation appears on the interface Timeline.

**Outcome:** understood and routed in minutes, with evidence, without touching four tools.

---

## Journey B — "Defend the budget" (Naveen, Architect)

1. Naveen lands on **Capacity Planning**, scope = all sites, class = Core.
2. He sorts the forecast table by **time-to-90%**; four links breach within 90 days.
3. For the worst (**Core-01 Eth1/2**) he opens the forecast: 30/60/90/180-day projection
   with a **confidence band**, **time-to-80% = 34d / 90% = 52d / 95% = 68d**, and a
   **recommended upgrade window of 45–60 days** at confidence 0.82 (doc 11).
4. He reviews the **Top Growing Links** to sequence upgrades by growth *and* business
   impact (a High-impact link at 40%-and-rising may outrank a Low-impact link at 88%).
5. He generates the **Weekly Capacity Report** — an AI narrative plus the forecast
   tables and charts — and exports **PDF** for the change board and **XLSX** for finance.

**Outcome:** a defensible, evidence-backed upgrade plan produced from preserved history.

---

## Journey C — "Ingest a new month" (Karan, Admin)

1. Karan opens **Uploads** and drops **three XLSX** files (one per site).
2. NetPulse **auto-detects** headers and proposes column mappings; a saved profile from
   last month maps two files automatically. He confirms the third.
3. The **Validation Console** reports: 1 blocking (one file missing the speed column for
   a device), 9 warnings (an overlap with an existing batch, two gap stretches, four
   corrupt util>100% rows, two new interfaces), and info (maintenance overlap on Site B).
4. He remaps the speed column (blocking cleared), chooses **skip overlaps** for the
   duplicate range, confirms the two **new interfaces**, and lets the four corrupt rows
   be **flagged-and-excluded** (not silently kept).
5. He **Commits.** Three immutable batches are created, rollups and analytics recompute
   incrementally, and **Upload History** shows the coverage ribbons and a "what changed".
6. Because Site B's window overlapped maintenance, those samples are auto-tagged and
   **excluded from alerts/SLA/trend** (Maintenance Awareness).

**Outcome:** clean, trustworthy data with full provenance and zero history overwritten.

---

## Journey D — "The board asks about risk" (Meera, Executive)

1. Meera opens the **Executive Dashboard**: **Infrastructure Risk 34 ▲**, six critical
   links, four forecast breaches in 90 days, with a two-sentence AI narrative.
2. She drills the **Top Critical Links** tile → a filtered impact view, then clicks
   **Generate Executive Summary**.
3. NetPulse produces a natural-language narrative ("Infrastructure is stable; the
   principal emerging risk is the LON-DC1 internet edge, forecast to reach 90% within
   ~7 weeks; recommended action is to schedule the planned 100G upgrade in Q3…").
4. She exports **PDF** and drops it into the board pack.

**Outcome:** board-ready posture in three clicks, in language leadership understands.

---

## Journey E — "Walk the data center" (Ravi, L2, via Digital Twin)

1. Ravi opens the **Digital Twin** site map; **LON-DC2** glows amber.
2. He clicks in: **Room 2 → Rack R14 → Core-02**; a **front-panel** view shows one port
   LED red.
3. He clicks the red LED → **Interface Dashboard**, reads the verdict ("Traffic Pattern
   Changed — weekend traffic on a business link"), and opens the attached **runbook**
   from the Knowledge Base.
4. He follows the runbook, adds a **Timeline comment**, and links the relevant **known
   issue** article.

**Outcome:** spatial, intuitive navigation from "something's wrong somewhere" to the
exact interface and its runbook.

---

## Journey F — "Configure a policy without code" (Karan, Admin)

1. In **Admin → Rules**, Karan builds:
   `IF Business Hours AND util > 75% FOR 30 min → Critical` for **class = Trading**.
2. He adds a weekend rule: `IF Weekend AND util > 90% → Warning`.
3. He sets a **customer-specific threshold set** for Cust-ACME (stricter High band).
4. He saves; the ruleset is **versioned**. Verdicts recompute; the change is **audited**.
5. Next upload, verdicts reflect the new policy — **no deployment required**.

**Outcome:** operational policy is data, editable by admins, fully traceable.

---

## Journey G — "Natural-language question" (future AI, any role)

1. From the **⌘K command bar**, Sana types:
   *"What happened on Core-01 yesterday between 10:00 and 12:00?"*
2. The **AI Assistant** (doc 13) parses intent + entity + time, queries the analytics
   store, and answers with a scoped narrative, the relevant chart, any anomalies, and
   links to the Interface Dashboard and RCA case for that window — **grounded in real
   data, with citations to the underlying samples/verdicts.**

**Outcome:** ask in English, get an evidence-backed answer, jump straight to the source.

---

## Journey map (who touches what)

| Journey | Persona | Entry screen | Engines exercised |
| --- | --- | --- | --- |
| A Congestion | NOC Lead | NOC Dashboard | Rule, Verdict, Anomaly, RCA, Baseline |
| B Budget | Architect | Capacity Planning | Capacity, Risk, Reports |
| C Ingest | Admin | Uploads | Ingestion, Validation, Maintenance |
| D Risk | Executive | Executive Dashboard | Risk, Capacity, AI Summary, Reports |
| E Twin | L2 | Digital Twin | Verdict, Knowledge, Timeline |
| F Policy | Admin | Admin/Rules | Rule, Verdict, Audit |
| G NL query | Any | ⌘K command bar | AI Assistant, Analytics, RCA |
