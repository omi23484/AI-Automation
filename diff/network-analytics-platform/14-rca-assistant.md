# 14 — RCA Assistant

When an issue occurs, an engineer always asks the same questions. The RCA Assistant
**pre-answers them automatically** from correlated evidence, turning a 30-minute manual
reconstruction across tools into a one-click, evidence-backed briefing.

## 1. The standard RCA questionnaire (auto-answered)

| Question | How NetPulse answers it |
| --- | --- |
| **When did it start?** | First threshold breach / change-point timestamp (rule state machine + change-point detection, docs 07/10). |
| **How long did it last?** | Episode start→end from the rule state machine (with recovery), or ongoing. |
| **Business hours?** | Overlay the episode against the entity's calendar (doc 07). |
| **Recurring?** | Match this episode's signature against historical episodes (same dow/hour cluster, similar shape). |
| **Previous occurrences?** | List prior matching episodes with links to their timelines. |
| **Growth trend?** | Slope + MoM/QoQ growth from the analytics engine (doc 08/11). |
| **Related interfaces?** | Correlated entities: peers/uplinks/same-card/same-path whose series moved together in the window. |
| **Maintenance correlation?** | Intersect the window with maintenance history; flag overlap. |
| **Likely cause?** | Ranked hypotheses from the evidence pattern (see §3). |
| **Recommended next steps?** | Action template from the dominant verdict/anomaly type (doc 09/10). |

## 2. Trigger & workflow

```
Trigger: a Critical verdict, a high-severity anomaly, or an engineer clicking "Explain"
   │
   ▼
RCA case created (rca_case, doc 03) anchored to entity + time window
   │
   ├─ gather evidence: metrics, distribution, baseline deviation, anomalies, forecast,
   │                    maintenance overlap, related-entity correlation, prior episodes
   ├─ auto-answer the questionnaire (deterministic)
   ├─ rank likely causes (hypothesis engine)
   └─ AI narration (doc 13) renders a readable RCA summary (grounded)
   │
   ▼
Engineer reviews → confirms/edits cause → adds notes → attaches KB → closes case
   (every step audited; case lands on the entity Timeline and can seed a report)
```

## 3. Likely-cause hypothesis engine (explainable)

Rather than a black-box "root cause", NetPulse ranks **candidate explanations** by how
well the evidence matches known patterns:

| Pattern in evidence | Suggested cause (hypothesis) |
| --- | --- |
| Gradual rise, recurring business-hour, +growth | **Organic demand growth** → capacity planning. |
| Step change dated to a maintenance window | **Change-induced** (post-maintenance behavior shift). |
| Sudden drop + correlated peer rise | **Rerouting / failover / path change** elsewhere. |
| New off-hours/weekend cluster on business link | **New scheduled job** (backup/replication/misclassification). |
| Sustained RX/TX imbalance onset | **Asymmetric routing / unidirectional flow / SPAN misconfig.** |
| Spike isolated to one link, no peers | **Localized event / microburst / single-flow elephant.** |
| Broad simultaneous rise across a device/card | **Device/line-card or upstream aggregation event.** |

Each hypothesis shows the **evidence for and against** and a confidence, so the engineer
adjudicates rather than trusting a guess. The human can confirm, override, or add a cause;
their decision is captured and feeds future matching.

## 4. Correlation (related interfaces / blast radius)

- **Temporal correlation:** find entities whose rollup series moved together in the RCA
  window (correlation over the same interval), scoped to topological neighbors first
  (same device/card/path/peer) to keep it meaningful and cheap.
- **Topological correlation:** uplinks, peer core, port-channel members, and same-path
  links are prioritized as candidates.
- Output: a ranked "related interfaces" list with mini-sparklines and the correlation
  strength — the blast radius at a glance.

## 5. RCA Workspace (screen)

A focused investigation surface (doc 05 §RCA):
- **Header:** entity, window, dominant verdict/anomaly, auto-answered questionnaire.
- **Evidence canvas:** synchronized charts (subject + related interfaces), distribution,
  baseline overlay, change-point + maintenance markers on one shared time axis.
- **Hypotheses panel:** ranked causes with evidence and confidence.
- **Actions:** confirm/edit cause, add notes, attach KB articles/runbooks, link prior
  episodes, generate an RCA document, close case.

## 6. Outputs & integration

- **RCA document** — exportable (PDF/HTML, doc 15), attachable to the entity's Knowledge
  Base, and pinned on the Timeline.
- **Timeline entry** — the RCA becomes a permanent operational-history event.
- **Feedback loop** — confirmed causes improve future hypothesis matching and can seed
  new rules ("this pattern → this verdict/action").
- **AI RCA (future, doc 13):** conversational follow-ups ("show me the last three times
  this happened", "compare to the peer core") over the same grounded evidence.

## 7. Why it's trustworthy

RCA answers are **deterministic and evidence-linked** first; AI only narrates them. Every
claim ("started 07-09 09:34", "recurred 4×", "correlates with Eth1/1") deep-links to the
data that proves it. The assistant accelerates the human's judgment — it does not replace
the human's accountability.
