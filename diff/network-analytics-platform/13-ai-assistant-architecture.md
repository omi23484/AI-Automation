# 13 — AI Assistant Architecture

The AI layer makes NetPulse feel like an experienced NOC engineer: it **summarizes**,
**explains**, **answers questions in natural language**, and **narrates reports** — but
it is built so it **never invents facts.** Every AI output is grounded in the platform's
own structured analytics.

## 1. Design principles

1. **Grounded, not generative-of-truth.** The engines (Rule/Verdict/Anomaly/Capacity/
   Risk) own the *facts*. The LLM only *renders* those facts as prose or maps a question
   to a query. Numbers always come from the data layer.
2. **Deterministic fallback.** Every AI narrative has a template-based fallback that
   states the same structured facts, so the product is fully functional if the model is
   unavailable, rate-limited, or disabled by policy.
3. **Explainable & cited.** AI answers link to the evidence (charts, verdicts, samples)
   they summarize; users can always click through to the source.
4. **Privacy/tenancy-aware.** The assistant only sees data the user's role permits (doc
   18); prompts are scoped to authorized entities. Model calls can run against an
   approved provider or a self-hosted model per deployment policy.
5. **Pluggable model.** The model is an implementation detail behind an internal
   interface — swappable (managed API or on-prem) without touching product surfaces.

## 2. Capabilities (v1 → future)

| Capability | Status | What it does |
| --- | --- | --- |
| **AI Summary** | v1 | Concise NOC-style narrative per interface/device/site/verdict. |
| **Anomaly explanation** | v1 | Renders each anomaly's structured detection into prose. |
| **Report narration** | v1 | Executive/capacity/trend report narratives from structured results. |
| **Natural-language query** | future | "What happened on Core-01 yesterday 10–12?" → scoped answer. |
| **AI RCA assistant** | future (assist v1) | Guides/explains RCA beyond the deterministic auto-answers (doc 14). |
| **Capacity / upgrade recommendation narrative** | future | Explains and sequences upgrades in plain English. |
| **NL report generation** | future | "Make me a monthly trend report for LON-DC1" → generated report. |

## 3. Architecture (Retrieval-Augmented, tool-calling)

```
User (⌘K / "Explain" / "Generate summary")
        │
        ▼
 Intent & scope parser  ──► {intent, entities, time-range, metric}   (+ RBAC scope check)
        │
        ▼
 Orchestrator ── calls PLATFORM TOOLS (not free text):
        ├─ get_verdict(entity, range)
        ├─ get_metrics/rollups(entity, range)
        ├─ get_anomalies(entity, range)
        ├─ get_forecast(entity)
        ├─ get_baseline_comparison(entity, baseline)
        └─ get_timeline/rca(entity, range)
        │
        ▼
 Structured context (facts + evidence refs)  ──►  LLM (render prose / narrative)
        │
        ▼
 Grounded answer  +  citations/deep-links  +  confidence
```

- The LLM is used for **language**, the tools for **truth.** This is a
  retrieval-augmented, tool-calling design: the model is handed verified structured
  facts and asked to explain, not to recall or compute.
- **Natural-language query** works by mapping the question to the same tool calls (a
  semantic layer over the analytics store), then narrating the results — so answers are
  always backed by real queries with citations.

## 4. Grounding & anti-hallucination controls

- **Facts injected, not recalled:** the model receives the exact numbers/verdicts and is
  instructed to use only those; it cannot introduce metrics not in context.
- **Citations required:** each claim links to the artifact it came from; uncited claims
  are suppressed.
- **Numeric guardrails:** any figure in the narrative is cross-checked against the
  structured context before display; mismatches fall back to the template renderer.
- **Confidence surfaced:** the assistant states uncertainty when the underlying analytics
  are low-confidence (thin history, poor coverage).
- **Scope enforcement:** the assistant can only reference entities the user may see; it
  refuses or narrows out-of-scope questions.

## 5. Example (grounded summary)

Structured context handed to the model:
```
verdict: Recurring Business-Hour Congestion (+Capacity Planning Required)
p95_business_hours: 78%; breaches_30d: 14; growth_mom: +18%;
forecast.time_to_90d: 52; upgrade_window: 45–60d; confidence: 0.86
```
Rendered narrative (grounded, every number from context):
> "This interface exceeded business-hour thresholds on **14 occasions** this month.
> Utilization has increased **18%** over the previous month. At the current growth rate,
> capacity expansion should be planned within approximately **60 days**."

## 6. Trust, safety & governance

- **Read-only by default.** The assistant explains and recommends; it does not execute
  changes. Any future action-taking is gated behind explicit RBAC + confirmation +
  audit.
- **Everything audited.** NL queries and generated narratives are logged (who asked what,
  what was returned) for the audit trail (doc 18).
- **Deployable on-prem.** For sensitive NOCs, the model interface supports a self-hosted
  model so no data leaves the environment; the grounding architecture is identical.
- **Prompt-injection resistance:** external/free-text content (comments, KB, uploaded
  descriptions) is treated as untrusted; the assistant is instructed to not follow
  instructions embedded in data, only to summarize it.

## 7. Why this ages well

Because AI sits **on top of** structured analytics via a tool interface, model upgrades
and new AI features (NL report generation, upgrade-recommendation engine) are additive —
they call the same tools. The platform's correctness never depends on the model, and the
model can get better (or be swapped/self-hosted) without destabilizing operations.
