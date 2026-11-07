# What "intelligence" this tool has (and does not have)

Short version: it is **deterministic analytics plus a rule-based expert layer**. It is not machine learning and it is not an LLM. Do not describe it to customers as "AI" without that qualification.

## What it does (all explainable, every number shown)
| capability | how | where |
|---|---|---|
| Learns what is normal per link | causal seasonal baseline: median/MAD of the same weekday+hour over prior weeks (fallback weekday/weekend+hour); refuses to score without enough history | `anomaly.py` |
| Detects abnormal traffic | robust z-score + EWMA control chart on that z (small sustained shifts); weekly mode: z vs the previous 8 weeks | `anomaly.py`, `weekly.py` |
| Detects pattern (level) shifts | binary segmentation with AR(1)-adjusted statistic; the segment medians must move too, so one outlier is not a shift | `changepoint.py` |
| Correlates across devices and zones | overlapping anomaly windows + Pearson r of baseline residuals; labels "shared-cause candidate" only with numbers shown | `correlate.py` |
| Matches changes to events | CR windows vs finding windows by device scope; "candidate correlation, not proven cause" | `crmatch.py` |
| Reads data by meaning | header matching by aliases, units inside cells, proof-based day/month order for slash dates, counter wrap vs reset reasoning (uptime, line-speed plausibility) | `weekly.py`, `units.py`, `timeparse.py`, `counters.py` |
| Reasons about causes | 6 documented interpretation rules; no supporting evidence => "Unknown - insufficient evidence" | `interpret.py` |
| Checks device health | 13 device rules + 2 cross-device rules over parsed `show` output, each finding with evidence; user-defined parsers and rules | `devcheck/` |

## What it does NOT do
- **No learned models.** Nothing is trained; thresholds are fixed defaults you can tune, not values the tool adapts.
- **No learning from feedback.** Marking a finding as a false positive does not change future results. Waivers are manual and visible.
- **No LLM / language model.** Explanations are templates over evidence. (The optional SLM explainer, Phase 3, is not built, and would only phrase evidence the engine already produced.)
- **No forecasting or capacity planning** (no time-to-threshold, no growth projection).
- **No topology awareness.** It does not know which devices are connected, so "shared cause" is time-and-shape agreement only.
- **No root-cause certainty.** Output is candidates with evidence, never a diagnosis.
- **No intra-week visibility** in weekly mode, and no yearly seasonality.

## Honest positioning
"Deterministic network analytics with an evidence-citing rule engine" is accurate. "AI-driven root cause analysis" is not. If an SLM is added later, the accurate claim is "AI-written explanations of deterministic findings".

## Candidate next steps (each is a decision, not a promise)
1. **Feedback loop**: mark findings real/false; suppress or adapt per-series thresholds (needs a stored feedback table and a rule for how it changes scoring).
2. **Capacity forecast**: robust trend (Theil-Sen) with time-to-threshold and uncertainty; a natural fit for larger tiers.
3. **Topology-aware correlation**: build a link graph from CDP/LLDP captures and correlate neighbours first.
4. **Signature library**: editable symptom-combination -> known-cause entries (a knowledge base the customer can extend).
5. **Persisted baselines** across imports so a new file is scored against history without re-importing it.
6. **SLM explainer (Phase 3)**: optional; needs hardware inventory and a local model file.
