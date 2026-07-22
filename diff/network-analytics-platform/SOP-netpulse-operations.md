# NetPulse — Standard Operating Procedure (SOP)
## Every knob, what it does, and how to use it

**Applies to:** `diff/netpulse.html` (the single-file offline app). Version badge shown next to the "NetPulse" logo (top-left).
**Audience:** NOC engineers, network architects, and platform admins operating NetPulse.
**Golden rules:** history is append-only (never overwritten); every change is written to the Audit Log; all analytics recompute automatically when you change a knob.

---

## 0. Quick start

1. Open `netpulse.html` in Chrome/Edge/Firefox (Safari 16.4+). Confirm the **version badge**.
2. Click **✨ Demo data** to explore, or go to **Uploads** and drop your `.xlsx`/`.csv` files.
3. Review the **Validation Console** (mapping + checks), then **Commit**.
4. Work from the **NOC** dashboard (impact-ranked) or the **Digital Twin**; drill into any link for full analytics.
5. Tune behavior in **Admin** and **Link Manager** (below).

Data is stored locally in your browser profile (IndexedDB). Nothing leaves your machine.

---

## 1. Uploads & the Validation Console

**Where:** left rail → **Uploads**.

| Knob / control | What it does | How to use |
| --- | --- | --- |
| **Choose files / drag-drop** | Ingest one or many `.xlsx`/`.csv` files. | Select as many as you like. Same-layout files are mapped **once** and streamed in one at a time; different layouts are prompted in turn. |
| **Column mapping dropdowns** | Map each canonical field (Device, Interface, Timestamp, Average/Peak Transmit/Receive as rate or %, Transmit/Received/Reference Bandwidth, Site, IP, Link name). | Auto-proposed by meaning. **Change any dropdown** if a guess is wrong, or pick "— not in this file —". A field marked `manual` was set by you. `*` = required. |
| **Parse Inspector** | Shows the highest parsed values (Transmit/Received/Capacity/Util) before commit. | Sanity-check that the backend read your numbers correctly. Impossible rows are flagged here. |
| **Validation findings** | Blocking (must fix), Warning (duplicates, gaps, impossible values), Info (unit normalization, new interfaces, maintenance overlap). | Resolve blocking items (usually a missing required mapping). Warnings are advisory. |
| **Commit** | Writes the batch(es) to storage and recomputes analytics. | Enabled once blocking items are cleared. For same-layout multi-file, commits all automatically. |
| **Cancel** | Discards the staged upload(s). | — |

**Upload history** (below the dropzone): every batch with coverage, rows, interfaces, cadence.
- **✕ Remove**: delete a batch and its samples — use to undo an upload committed with a wrong mapping.
- Shows total **samples in memory**; warns past ~800k (very large datasets ≈ ~1 GB RAM — upload in ~10-file chunks for smoothness).

**Tips**
- Bandwidth units (Gbps/Mbps/Kbps/bytes, counters, `10G`/`100G` speeds) are auto-normalized to bits per second.
- Day-first timestamps (`22-06-2026 00:30`) are understood.
- Physically impossible rows (rate above link capacity / util > 120%) are excluded as counter-wrap artifacts; if a whole link is affected, its bandwidth column is mismapped — fix the mapping or set a **Speed override** (Link Manager).

---

## 2. Admin — global policy knobs

**Where:** left rail → **Admin**. All changes are audited and recompute verdicts immediately.

### 2.1 Global thresholds (utilization bands)
| Knob | Meaning |
| --- | --- |
| **Warning ≥ (%)** | Below this = Normal. |
| **High ≥ (%)** | Elevated. |
| **Critical ≥ (%)** | Congested. |

These bands drive the state distribution ("smart pie"), heatmap colors, verdicts, and chart threshold lines. **Save thresholds** to apply.

### 2.2 Business hours & planning
| Knob | Meaning / use |
| --- | --- |
| **Business start / end hour** | Defines "business hours" used by verdicts, the upgrade policy, and RCA. |
| **Planning horizon (days)** | How far ahead a forecast breach counts as "capacity planning required". |
| **Upgrade lead time (days)** | Procurement/change lead time; the recommended upgrade **window** is `time-to-90% − lead time`. Set it to how long an upgrade really takes you. |

### Upgrade Watch dashboard  *(Analyze → Upgrade Watch)*
Track how often specific links cross the upgrade threshold over a chosen window.
- **Window**: 30 / 60 / 90 / 120 / 180 days (remembered across sessions). The window ends at the most recent data point.
- **Add links**: pick a device+interface from the dropdown and **Add**, or **Add all** to watch everything; **✕** to stop watching one, **Clear** for all. Your watchlist is saved.
- **Per-link columns**: hits in the window (with a bar), days-hit vs the required trigger days, peak utilization, last hit time, and whether the trigger is **MET**. Rows are sorted by hit count. Click a row to open the interface. "Export all watched to Excel" produces the Policy Hits .xlsx (§8) for the watched set.
- Uses the threshold/days/business-hours setting from **Admin → Link upgrade policy** (below).

### 2.3 Link upgrade policy  *(the "recommend upgrade" rule)*
| Knob | Meaning |
| --- | --- |
| **Utilization threshold (%)** | The busy level that counts toward an upgrade (e.g., 80%). |
| **Sustained for (days)** | How many distinct days must cross the threshold before an upgrade is recommended (e.g., 5). |
| **Count business-hours only** | If on, only business-hours samples count (recommended for business links). |
| **Action** | *Recommend* (verdict + report) or *Auto-flag for upgrade*. |

When satisfied, the link gets the **"Link Upgrade Recommended"** verdict. A live "Current rule" line summarizes the setting. **Save upgrade policy** to apply. Per-link overrides are possible via Link Manager thresholds.

### 2.4 Class-specific policies (reference table)
Shows the effective Warn/High/Critical bands and default business impact per class (Core, Trading, Internet, WAN, Storage, Backup, Voice, Management, Customer). Trading/Core are stricter; Backup is looser by design.

### 2.5 Data management
- **⤓ Export all data (JSON)** — full local backup.
- **Reset all data** — wipes uploads, batches, config, audit (confirmation required).

---

## 3. Link Manager — per-link knobs

**Where:** left rail → **Link Manager**. One row per link; **every column is editable and overrides the automatic guess.** Changes persist, are audited, and recompute analytics instantly. A ↺ button resets a link to automatic.

| Knob | What it does | When to use |
| --- | --- | --- |
| **Class / role tag** | Core, Trading, Internet, WAN, Storage, Backup, Voice, Replication, Management, Customer. | The name-based guess is wrong, or you want a specific policy applied. |
| **Business impact** | Critical / High / Medium / Low. | Sets ranking priority and the risk multiplier. A trading link should be Critical even at low utilization. |
| **Warn / High / Crit %** | Per-link utilization bands. | This link needs stricter/looser thresholds than its class default. |
| **Speed** | Override the interface capacity (e.g., `200M`, `10G`). | The file's bandwidth column is wrong, or missing; utilization recomputes from stored rates. |
| **Site** | Override the site grouping. | Site wasn't in the file or is mislabeled. |
| **Tags** | Free-form comma-separated labels (e.g., `customer-acme, dr-link`). | Group/filter links your way; tags show as chips and are searchable. |

**Filter box**: search by device / interface / class / site / tag.

> The same per-link knobs (class, impact, thresholds, speed, site, tags) are also available in the **Link settings** panel on each interface page.

---

## 4. Interface (per-link) page — analysis tools

**Where:** click any link (NOC card, table row, Digital Twin LED, or search).

| Control | What it does |
| --- | --- |
| **Verdict banner** | The plain-English conclusion + recommended action + confidence. Leads every page. |
| **🔍 Explain (RCA)** | Generates the RCA questionnaire and **editable Likely cause / Recommended next steps** (see §5). |
| **▦ Add to report** | Adds this link to a generated report. |
| **⤓ Export HTML** | Downloads a self-contained printable report of this link. |
| **🖨 Export PDF** | Opens the print dialog → choose "Save as PDF". |
| **Traffic & Utilization chart** | Transmit/Received (+Peak) with threshold bands and maintenance shading. **Hover** for exact values (% and bandwidth); **scroll** to zoom; **drag** to pan; **double-click** to reset; `+ / − / ⟲` buttons. |
| **Utilization rhythm (day × hour heatmap)** | Shows *when* the link is busy. |
| **State distribution (donut)** | % of time in Normal/Warning/High/Critical, with an AI explanation. |
| **Capacity forecast** | 30/60/90/180-day projection, days-to-80/90/95%, recommended upgrade window, confidence. |
| **◆ AI summary — Technical \| Simple toggle** | *Technical* = engineer detail (p95, MoM, model). *Simple* = jargon-free management language. Choice is remembered (see §6). |
| **Link settings** | Per-link class/impact/thresholds/speed/site/tags (see §3). |
| **Risk factors** | 0–100 score with its contributing factors. |
| **Timeline & comments** | Operational history; add a comment/annotation (audited). |

---

## 5. RCA — editable cause & steps

**Where:** interface page → **🔍 Explain (RCA)**.

1. NetPulse auto-answers: when it started, recurring?, business hours?, growth trend, related interfaces, maintenance correlation.
2. **Likely cause** and **Recommended next steps** are pre-filled from analysis but are **editable textareas** — correct them with your engineering judgment.
3. **Save RCA** — persists per link (audited), and the edited text flows into the **exported report** and any generated report. **Reset to auto** restores the automatic text.

Use this to capture the real root cause after investigation, so the next person (and the exported report) sees the truth, not just the automatic guess.

---

## 6. AI summary modes (management vs engineer)

- **Technical** (default): full detail for engineers — p95, month-over-month growth, forecast model, confidence.
- **Simple**: plain English for management / non-technical readers — e.g., *"…the LON core link is running very busy. At its busiest it uses about 95% of the line's capacity. It is already close to full — this needs attention now."* No jargon.

Toggle on any interface page (top-right of the AI summary card). Your choice is remembered across sessions and is used in the exported report's "In plain terms" section.

---

## 7. Maintenance windows

**Where:** left rail → **Maintenance**.

| Knob | Use |
| --- | --- |
| **Scope** | All interfaces, a device, or a single interface. |
| **Start / End** | The window. |
| **Reason** | Free text (shown on the timeline). |

Samples inside a maintenance window are **tagged and excluded** from alerts, SLA, trends, and adverse verdicts — so planned work never creates false alarms. Charts shade the window. Delete a window with ✕.

---

## 8. Reports & Audit

- **Reports**: generate Executive Summary, Weekly Capacity, Monthly Trend, Top Busy/Growing/Critical/Idle Links, Business Impact. Preview, then **Export HTML** or **🖨 PDF**. Per-link reports export from the interface page (§4).
- **Upgrade Policy Hits — Excel (.xlsx)**: a customer-facing spreadsheet listing every timestamp a link crossed the upgrade policy threshold and the exact utilization at that moment. Choose **Scope** = *All links* or a single link, click **Generate .xlsx**. Also available per link via the **📊 Policy hits .xlsx** button on the interface page. The file has two sheets: **Summary** (one row per link — capacity, policy settings, days-hit, total hits, whether the upgrade trigger was met, p95, verdict) and **Policy Hits** (one row per breach — Device, Interface, Site, Timestamp, Utilization %, Transmit/Received Mbps, Capacity, Business-hours flag, threshold). Utilization/bandwidth are stored as real numbers so the customer can sort and chart. The threshold/days/business-hours-only come from **Admin → Link upgrade policy**. (Very large all-links exports cap the hit list at 50,000 rows — narrow the scope for full detail.)
- **Audit Log**: append-only record of every action (uploads, mapping/threshold/policy changes, per-link edits, RCA edits, exports, resets). Read-only. Use it as compliance evidence.

---

## 9. Theme & display

- **◐ button** (top bar): toggle **light/dark**. Remembered across sessions.
- **⛶ button**: fullscreen (NOC wall mode).
- **⌘K / search box**: jump to any link by name, or ask "worst link", "capacity", "anomalies".

---

## 10. Common workflows

**A. Onboard a new monthly export**
Uploads → drop file(s) → confirm mapping (once per layout) → check Parse Inspector → Commit → review NOC dashboard.

**B. Decide an upgrade**
Admin → set Upgrade policy (e.g., 80% / 5 business days). Links meeting it show **Link Upgrade Recommended**. Open the link → review forecast & RCA → edit RCA cause/steps → **Export PDF** for the change board.

**C. Fix a mis-detected link**
Link Manager → set correct Class, Impact, Speed (if bandwidth column was wrong), and Tags → analytics recompute. Or per link via Link settings.

**D. Brief management**
Open the link → AI summary → **Simple** → **Export PDF**. Or Reports → Executive Summary → PDF.

**E. Plan maintenance without false alarms**
Maintenance → add window (scope + time + reason) before the work. Affected samples are excluded automatically.

---

## 11. Data-scale guidance

- Comfortable up to a few hundred thousand rows; ~1M+ works on a desktop with adequate RAM (~1 GB in the browser).
- For 6-month / multi-file datasets, upload in **~10-file batches** — history accumulates seamlessly (per-batch storage).
- For routine, always-on, multi-million-row analytics, the server-side architecture in this spec folder is the intended long-term path.

---

*Every knob in this SOP is editable without code changes and takes effect immediately. When in doubt, remember: nothing is overwritten, everything is audited, and any override can be reset to automatic.*
