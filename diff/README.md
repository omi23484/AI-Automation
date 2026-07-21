# `diff/` — Separate Design Workspace

This folder is intentionally **isolated** from the existing `neteng-toolkit.sh`
application at the repository root. Nothing here modifies, imports, or depends on
the current NetEng Toolkit code.

It contains a **planning-only product specification** for a new, standalone
product:

> **NetPulse** — a Production-Ready Network Analytics & Capacity Planning
> Platform.

No application code is produced here. These are architecture, product, UX, data,
and analytics design documents intended to be handed to an engineering team to
implement as a separate product.

## Contents

| Path | Purpose |
| --- | --- |
| [`netpulse.html`](./netpulse.html) | **The working application** — a single self-contained, offline HTML file (no CDN, no backend). Open it in a modern browser. |
| [`network-analytics-platform/`](./network-analytics-platform/) | The full product specification, organized as numbered documents. |

Start at
[`network-analytics-platform/00-INDEX.md`](./network-analytics-platform/00-INDEX.md)
for the design, or just open `netpulse.html` to use the app.

## Running the app (`netpulse.html`)

It is a single HTML file — matching the repo's offline-first pattern. Just open it:

```
# open diff/netpulse.html in Chrome/Edge/Firefox (or a recent Safari)
```

Then either click **✨ Demo data** to generate a realistic 14-day polling dataset, or
go to **Uploads** and drop your own `.xlsx` / `.csv` interface-polling files.

What it does, entirely in the browser:

- **Parses XLSX and CSV offline** — XLSX ZIP/DEFLATE is decoded via the browser's
  built-in `DecompressionStream`; no library, no upload to any server.
- **Understands headers by meaning, not by hardcoded names** — a semantic resolver
  (alias + fuzzy + value-shape) maps `NodeName→device`, `IfDescr→interface`,
  `Egress (Mbps)→tx`, etc., and finds the header row even when it isn't row 1.
- **Normalizes bandwidth units** — Gbps/Mbps/Kbps/bytes/counters and speeds like
  `100G`/`10G` are all converted to canonical bits-per-second before analytics.
- **Analytics engine** — verdicts, utilization distribution (time-in-state), risk
  scoring, capacity forecasting (time-to-80/90/95 + upgrade window), baseline anomaly
  detection, and an RCA assistant.
- **Ops-center UI** — dark, glassmorphic dashboards (Executive, NOC, Interface),
  a navigable **Digital Twin** (Site → Device → interface LEDs), SVG charts
  (line/area, heatmaps, calendar heatmaps, distribution donuts, sparklines), reports
  (with HTML/PDF export), maintenance windows, and an audit log.
- **Persists to IndexedDB** — history is append-only and never overwritten;
  duplicate/gap/corrupt-value detection runs at ingest.

**Requirements:** a modern browser with `DecompressionStream` and IndexedDB
(Chrome/Edge 103+, Firefox, Safari 16.4+). Data stays local to the browser profile.

> Scope note: as a single offline file this is the interactive prototype of the
> platform described in `network-analytics-platform/`. The heavier enterprise pieces
> in the spec (server-side time-series store at 100k-interface scale, an LLM-backed
> assistant, SSO/RBAC, streaming integrations) are the client–server evolution; the
> AI summaries here are the spec's deterministic, grounded fallback renderer.

## Why a `diff/` folder

The root of this repository ships the offline NetEng Toolkit. The request that
produced this specification explicitly required the new work to be **separate**
and kept in a **diff folder** so the existing toolkit is never touched or merged
with the new design. Treat this directory as a design "changeset" that can be
reviewed, iterated on, and later spun out into its own repository when
implementation begins.
