# What "intelligence" this tool has (and does not have)

Short version: **deterministic analytics plus a rule-based expert layer, plus an optional local-model explainer that is off by default.** It is not machine learning. Do not call it "AI-driven" without those qualifications.

## What it does (every number shown, every claim cites evidence)
| capability | how | where |
|---|---|---|
| Learns normal per link | causal seasonal baseline (median/MAD of the same weekday+hour over prior weeks); refuses to score without enough history | `anomaly.py` |
| Detects abnormal traffic | robust z-score + EWMA chart on it; weekly mode: z vs previous 8 weeks | `anomaly.py`, `weekly.py` |
| Detects level shifts | binary segmentation, AR(1)-adjusted; segment medians must move too | `changepoint.py` |
| Correlates devices/zones | overlapping windows + Pearson r of residuals | `correlate.py` |
| **Capacity outlook** | Theil-Sen trend + Mann-Kendall test on daily p95 / weekly utilisation; time-to-80/90/100% with a heuristic range; **no date** unless the trend is significant | `forecast.py` |
| **Topology awareness** | link graph from CDP/LLDP captures: "both ends of one link", "adjacent devices", or "no known link" | `devcheck/topology.py` |
| **Learns from analyst feedback** | verdicts real/false/expected; only "false" marks raise that series' thresholds (visible, capped, reversible); others annotate | `store.py`, `pipeline.py` |
| **Signature library** | editable symptom-combination -> candidate cause + checks, matched only on evidence the tool holds | `signatures.py` |
| **Persisted history** | derived series kept across imports: new data is scored against everything seen; chunked imports; conflicts recorded | `history.py` |
| Reads data by meaning | header aliases, units in cells, proof-based date order, counter wrap/reset reasoning | `weekly.py`, `units.py`, `timeparse.py`, `counters.py` |
| Reasons about causes | documented interpretation rules (R1-R7) + signature matches; nothing supports a cause => "Unknown - insufficient evidence" | `interpret.py` |
| Checks device health | 13 device rules + 2 cross-device rules + custom rules, each with evidence | `devcheck/` |
| **Optional local-model explainer** | phrases the evidence pack through a model server on this machine; output validated (uncited causes stripped, invented ids/numbers flagged) | `slm.py` |

## What it does NOT do
- **No trained model in the detection path.** Detection and correlation are statistics. The model, if enabled, only writes prose.
- The feedback loop adjusts thresholds by a fixed rule; it does not learn a model from labels.
- The forecast is a straight line: no seasonality, no step changes, no knowledge of upgrades. It says "no significant trend" rather than guess.
- Topology only comes from CDP/LLDP you captured; missing links mean "unknown", not "unrelated".
- The signature library ships empty (only examples in `profiles/example-neutral.json`): its value is the knowledge you put in.
- **Root cause is never certain.** Output is candidates with evidence.
- The local-model explainer has been tested only against a fake server. Its quality on a real model, and on your hardware, is unverified.

## Honest positioning
"Deterministic network analytics with an evidence-citing rule engine, capacity outlook and an optional locally-run AI explainer." Not: "AI root-cause analysis".
