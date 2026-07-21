# 15 — Reports & Exports

Reports turn continuous analytics into consistent, shareable, defensible artifacts.
They are **generated** (not hand-built), **grounded** (reproducible from preserved
history), and **exportable** to the formats each audience needs.

## 1. Report catalog

| Report | Audience | Contents |
| --- | --- | --- |
| **Daily Operations Report** | NOC | New/active verdicts, top incidents, anomalies, maintenance, uploads, data-quality summary. |
| **Weekly Capacity Report** | Architect | Forecasts, time-to-threshold, recommended upgrade windows + sequence, top growing links. |
| **Monthly Trend Report** | Architect/Mgmt | Growth (MoM/QoQ), pattern changes, distribution shifts, risk-of-infra trend. |
| **Executive Summary** | Leadership | Infra risk + trend, top exposures, forecast breaches, NL narrative. |
| **Top Busy Links** | NOC/Arch | Highest p95/peak, impact-weighted. |
| **Top Growing Links** | Arch | Fastest growth, with forecasts. |
| **Top Critical Links** | NOC/Exec | Highest risk × business impact. |
| **Idle Links** | Arch/FinOps | Consistently under-utilized — reclamation candidates. |
| **Capacity Forecast** | Arch/Finance | Per-scope forecast tables + confidence + capex framing. |
| **Business Impact Report** | Exec/Service Owners | Issues ranked by business impact, not utilization. |

## 2. Anatomy of a generated report

```
Cover: scope, period, generated-at, data coverage/quality note, ruleset/model versions
Executive narrative (AI, grounded — doc 13) with deterministic fallback
Key metrics (KPI band)
Sections: tables + charts (reuse the same visualization components as the dashboards)
Appendix: methodology, thresholds/rules in effect, exclusions (maintenance), confidence
```
Every report stamps the **versions and windows** used so it is **reproducible** — the
same report regenerated later renders identically (doc 03 §9).

## 3. Generation, scheduling & delivery

- **On-demand:** "Generate now" from the Reports library or from any dashboard scope
  ("report this site/customer/interface").
- **Scheduled:** daily/weekly/monthly cron per report + scope + recipients; runs
  asynchronously and publishes to Report History.
- **Delivery:** in-app library, email with attachment/deep-link, and (future) push to
  shared drives / ticketing / chat via integrations.
- **Report History:** every generated instance retained, versioned, and downloadable —
  an audit-friendly record of what was reported when.

## 4. Export formats

| Format | Use | Notes |
| --- | --- | --- |
| **PDF** | Board packs, change boards, archival | Pixel-faithful to the in-app preview; charts as vector where possible. |
| **XLSX** | Finance, further analysis | Data tables + a summary sheet; preserves units (normalized bps + human-readable Gbps/Mbps). |
| **CSV** | Pipelines, ingestion elsewhere | Raw tabular extracts of the report's datasets. |
| **HTML** | Portals, email, embedding | Self-contained, interactive-lite. |

- **Preview parity:** the on-screen report preview is byte-for-byte what the PDF/HTML
  exports (doc 05 §5.18) — no surprises.
- **Unit clarity in exports:** values carry explicit units; XLSX/CSV include both
  normalized `bps` and human units (Gbps/Mbps/Kbps) so downstream consumers aren't
  confused (ties to doc 04 §2.3).

## 5. Natural-language report generation (future, doc 13)

"Make me a monthly trend report for LON-DC1 Core links" → the assistant resolves scope +
period + report type, runs the standard report generator, and narrates it. The *data*
comes from the deterministic report engine; the assistant handles intent and prose.

## 6. Governance

- Report generation and export are **audited** (who generated/exported what, when).
- **RBAC-scoped:** a report can only include entities the requester may see; exports
  respect the same scope (doc 18).
- **Maintenance/quality honesty:** reports state exclusions (maintenance windows) and
  data-coverage caveats rather than silently omitting them — trustworthy by construction.
