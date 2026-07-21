# 01 — Product Vision, Personas & Value

## 1. Vision

NetPulse turns raw interface polling data into **operational judgment**. Most
tools in this space stop at collection and visualization; they hand a NOC engineer
a wall of graphs and leave the interpretation to a human at 03:00. NetPulse closes
that last mile: it interprets the data the way a seasoned NOC lead would, states a
verdict, shows the evidence, forecasts what happens next, and recommends an action.

It is deployable in a mission-critical NOC on day one against nothing more than an
uploaded spreadsheet, and it grows — without re-architecture — into a real-time,
multi-source, AI-driven single pane of glass for interface analytics.

## 2. The problem it solves

| Pain today | NetPulse response |
| --- | --- |
| Dashboards show *what* happened, never *what it means* or *what to do*. | Verdict Engine + AI Summary render plain-English conclusions and recommended actions. |
| Capacity planning is a quarterly spreadsheet exercise, done too late. | Continuous forecasting: "time to 80/90/95%", recommended upgrade window, confidence. |
| RCA is tribal knowledge reconstructed by hand from many tools. | RCA Assistant auto-answers the standard RCA questions with correlated evidence. |
| Thresholds create alert noise; real behavioral changes get missed. | Rule engine + baseline + anomaly detection separate "busy" from "abnormal". |
| Business context is lost — a backup link and a trading link look the same. | Classification + Business Impact reprioritize everything by what matters. |
| Historical data is overwritten or siloed, so trend/baseline work is weak. | Append-only history; every upload preserved; rollups for fast long-range trends. |
| Tools are locked to one collection method. | Source-agnostic ingestion; Excel now, SNMP/telemetry/APIs later, same UI. |

## 3. Competitive positioning

```
        Collection / Reachability        Visualization            Interpretation / Action
        ---------------------------      ------------------       -------------------------
        SolarWinds, ThousandEyes         Grafana, Splunk          (mostly manual today)
                    \                          |                          /
                     \                         |                         /
                      \________________  NetPulse  ________________/
                                    "the analytical brain"
```

NetPulse is **not** primarily a poller and **not** primarily a chart library. It is
the analytical and decision layer. It can *consume* from the pollers on the left
and *render richer visuals* than the tools in the middle, but its defensible value
is on the right: verdicts, forecasts, RCA, and AI assistance.

## 4. Personas

Each persona maps to a role in the RBAC model (see doc 18) and to a default landing
experience (see doc 02).

### 4.1 Naveen — Network Architect
- **Goals:** long-term capacity strategy, upgrade budgeting, standards enforcement.
- **Lives in:** Capacity Planning, Trend Analysis, Business Reports, Risk Scoring.
- **Success:** "I can defend next year's hardware budget with forecasts and
  confidence intervals, per site and per customer."
- **Key features:** 30/60/90/180-day forecasts, time-to-threshold, upgrade windows,
  infrastructure risk rollups, exportable executive reports.

### 4.2 Sana — NOC Lead (L3)
- **Goals:** keep the floor calm, triage what matters, own RCA quality.
- **Lives in:** NOC Dashboard, RCA Assistant, Anomaly feed, Verdict queue.
- **Success:** "The top of my screen is always the few things that actually need a
  human, ranked by business impact — not 4,000 green rows."
- **Key features:** business-impact-ranked verdict queue, anomaly explanations, RCA
  auto-answers, maintenance-aware suppression.

### 4.3 Ravi — NOC Engineer (L2)
- **Goals:** respond to what he's handed, follow runbooks, annotate.
- **Lives in:** Interface Dashboard, Timeline, Knowledge Base, Traffic Timeline.
- **Success:** "I open an interface and immediately see the verdict, the history,
  the runbook, and the last three times this happened."
- **Key features:** interface deep-dive, attached SOPs/runbooks, timeline
  annotations, historical comparison.

### 4.4 Meera — Executive / Service Owner
- **Goals:** risk posture, SLA health, where money should go — at a glance.
- **Lives in:** Executive Dashboard, Business Impact Report, Capacity Forecast.
- **Success:** "One screen tells me infrastructure risk, the top exposures, and
  what's trending toward trouble, in language I can take to the board."
- **Key features:** infrastructure risk score, top critical/growing links, forecast
  summary, natural-language executive narrative.

### 4.5 Karan — Platform / Data Administrator
- **Goals:** keep ingestion healthy, configure rules/calendars/classes, manage users.
- **Lives in:** Upload History, Rule Engine config, Maintenance, Audit Logs, RBAC.
- **Success:** "I can add a new customer policy or maintenance window without a code
  change, and every change is audited."
- **Key features:** rule builder, calendar/maintenance config, classification
  management, upload validation console, audit trail, RBAC admin.

### 4.6 Priya — Read-Only Stakeholder / Auditor
- **Goals:** view state and history, verify controls, export evidence.
- **Lives in:** read-only views of any dashboard, Audit Logs, Reports.
- **Success:** "I can see and export everything relevant and change nothing."

## 5. Value narrative by outcome

- **Fewer, better alerts.** Business-impact ranking + maintenance awareness + baseline
  anomaly detection cut noise while surfacing genuine behavioral change.
- **Capacity decided early, not late.** Continuous forecasts convert "we ran out of
  ports last month" into "plan the upgrade in the 45–60 day window."
- **Faster RCA.** The standard RCA questionnaire is pre-answered with correlated
  evidence, shrinking mean-time-to-understanding.
- **Defensible reporting.** Executive and capacity reports are generated, consistent,
  and exportable, with the analytics reproducible from preserved history.
- **Future-proofing.** Source-agnostic ingestion protects the investment as the org
  moves from spreadsheets to streaming telemetry.

## 6. Non-goals (explicit scope boundaries)

- NetPulse is **not** a device configuration or change-execution tool. It analyzes
  and recommends; it does not push config. (Actioning may arrive via integrations
  later, gated behind strict RBAC — see roadmap.)
- NetPulse is **not** a packet-capture / deep flow forensics tool in v1. NetFlow/IPFIX
  is a *future data source* for richer analytics, not a replacement for the core
  interface-utilization model.
- NetPulse does **not** guarantee real-time sub-second alerting in the Excel-upload
  era; real-time is a property that arrives with streaming integrations, and the
  architecture is built so that transition needs no dashboard redesign.
