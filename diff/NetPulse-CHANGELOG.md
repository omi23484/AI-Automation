# NetPulse — Feature & Change Summary (through v52)

**What it is:** a single, fully-offline, self-contained HTML network analytics &
capacity-planning dashboard. No server, no internet, no libraries — open the `.html`
in a browser. Data lives in the browser (IndexedDB); XLSX/CSV parsed in-browser;
reports generated in-browser. Enforced offline by a Content-Security-Policy.

---

## Core capabilities

**Data ingestion**
- Drag-and-drop **XLSX / CSV**, many files at once; same-layout files mapped once and streamed.
- Headers understood by **meaning** (not fixed names); fully editable column mapping.
- Units auto-normalized (bps/Kbps/Mbps/Gbps/bytes); explicit units respected.
- Memory-bounded streaming for **6-month / 1M+ row** datasets; string interning.
- History is append-only; duplicate interface+timestamp rows skipped (no overwrite).

**Analytics (per link)**
- Utilization = busier direction, **max(Transmit%, Receive%)**, per sample vs its own capacity.
- p95 (sustained busy level), average, peak (p99/p99.9/max selectable).
- Verdict engine (Healthy → Monitor → Capacity Planning → Upgrade Recommended).
- Robust **capacity forecast** (Theil–Sen on daily p95, 7-day deseasonalize, confidence
  range, days-to-80/90/95%, upgrade window, growth %/month), market-hours or all-hours basis.
- **Anomaly detection** (day×hour baseline z-score) with "why flagged" explanations.
- Risk scoring with business-impact multiplier.
- Rhythm heatmap (day × hour, values shown), state distribution, business vs off-hours split.

**Views**
- Executive summary, NOC (per-link), Digital Twin (site→device→port), Link Manager,
  Trends, Anomalies, Historical, Capacity Planning, Upgrade Watch, Uploads, Maintenance,
  Admin, Audit log.
- Per-interface **time & business-hours filter** (From/To datetime + hours mode).
- Charts: business-hours shading, threshold bands, policy line, anomaly markers, zoom/pan.

**Configuration (Admin)**
- Global + per-class + per-link thresholds; separate off-hours limits.
- Business/market-hours window (minute-accurate).
- Link-upgrade policy (threshold %, days, look-back window, market-hours-only, mode).
- Forecast settings (metric, direction, provision factor N×peak, peak basis, CI, window).
- **Time zone**: your zone + whether file times are local ("as written") or UTC.
- **Capacity-review flag** level (default 100%).
- Institution name + Prepared/Reviewed/Approved signatories + retention days (white-label).

**Reports & exports**
- **Upgrade Policy Hits .xlsx** — per link or all links; Summary + **Hits by Day** +
  **Hits by Date-Time**; Market vs Non-market split; Last hit vs Data-through columns.
- **Regulatory Capacity Report** (xlsx + on-screen) — p95/peak/headroom vs configurable
  threshold, augmentation trigger, projected breach date, methodology, generic compliance mapping.
- **Threshold Breach PDF** (per link, submission-grade) — last 6 months Warning & Critical
  counts, market/non-market split, per-day table, full timestamped detail log, sign-off block.
- **Download processed data** (CSV/XLSX) — every raw row 1:1 with derived values, for audit.
- Per-link HTML / PDF report; Executive/Capacity/Trend/Busy/Critical/Idle/Impact reports.
- Device-name variant merge (auto FQDN-vs-short-hostname, and manual merge of any two).

---

## Version-by-version changelog

**This session (data-correctness + reporting hardening):**

- **v65** — **Two fixes.** (1) *Capacity forecast drew a decline for links above ~120%.* The
  forecast engine capped the fitted **level** at 150% but every **projection** (`proj`, and the
  range band `projLo`/`projHi`) at 120%, so a link already above 120% had its band start at 150%
  and "fall" to 120% over 30 days, then run flat — beside text saying "growing ~21%/month". One
  ceiling now applies to both. The chart also sized its y-axis from the 180-day projection alone,
  so history was drawn outside the plot; it now sizes from everything plotted, and every chart
  clips its series to the plot area. The 120% cap had also been flattening far-horizon
  projections on ordinary links projected above 120%; those now show their real value (up to
  150%). The C# analytics port was changed identically and its parity fixtures regenerated.
  (2) *Windows blocked the PDFs extracted from the .zip* ("potentially harmful"). PDF layout is now
  **Separate PDF files** (default, up to 25, one download per link), **One .zip**, or **One
  combined PDF**; the zip option explains the Unblock step. Cause is Windows' Mark-of-the-Web on a
  downloaded zip, which Explorer cannot persist onto a network share.
- **v64** — **Multi-link Threshold Hit Reports** (Reports page, top panel). Pick any number of
  links (filter, All / ⚠ Upgrade / None) and get, from one set of options:
  a **period** (7 d … 12 months, all data, or custom range), **hours** (all / market / non-market),
  **what counts as a hit** (Warning+, High+, Critical, or the Upgrade-policy threshold), and what to
  include — a **utilisation graph for the period** (default on), **hits by date**, **hits by
  date-time**, or none of the tables. Output is **real PDF files** — one per link (a .zip when
  several) or one combined document with a cover page, contents and bookmarks — plus an **Excel
  workbook with native charts**: Summary, a stacked top-links chart, hits by date, hits by
  date-time (split across sheets at 200,000 rows) and one chart sheet per link (peak, average,
  threshold lines, hit markers). PDFs are written directly rather than printed, because a print
  dialog can only ever produce one file. Every figure comes from one shared `hitCalc()`, extracted
  from the existing Threshold Report, whose output is **byte-identical** before and after
  (45 hours × band × link combinations compared). Links with no data in the period are marked
  "no data", never shown as zero hits. The Excel writer gained styles, frozen headers, filters,
  native charts and deflate compression (existing exports unchanged). Limits, all stated in the
  documents: PDFs use the built-in Helvetica face so non-Latin-1 characters in device names print
  as "?" (Excel keeps them); a PDF lists the first 10,000 hits per link (Excel lists all); the
  period is anchored on the newest sample among the selected links.
  New `scripts/regression.mjs` is the one runnable check for everything since v60.
- **v63** — **Storage safety + design/accessibility pass.**
  *Storage:* a refused write (browser quota) used to be a silent unhandled rejection —
  the screen showed the upload as committed and it was gone on reload. Writes now roll
  back and say what to free; config saves warn instead of failing quietly; the browser
  is asked to keep the data rather than evict it; a new **Admin → Storage** panel shows
  used/quota, per-workspace sizes and a warning band (~18 MB per million samples).
  Strings are re-interned after loading from IndexedDB (structured-clone had been
  giving every row its own copy of the device/interface names).
  *Design:* colour emoji replaced with an inline single-stroke SVG icon set (still
  fully offline); sibling metric tiles unified onto one panel with hairline dividers;
  chart Y-axis rounded to readable steps (0/30/60/90/120, not 0/28/57/85/114); KPI
  footnotes carry a state dot instead of a delta arrow that implied movement.
  *Bugs found in the pass:* every **risk bar in the app rendered empty** (the fill was
  an inline `<span>` in a non-flex track, so its width/height were ignored); light-mode
  secondary text sat at 3.3–3.6:1 against a 4.5:1 requirement; the infrastructure-risk
  footnote used a different band from its own state colour.
- **v62** — **Workspaces** — keep two estates analysed separately (e.g. *RO Internet* vs
  *Corp Core*). Each workspace is its own browser database: separate uploads, links,
  thresholds, market hours, upgrade policy, maintenance windows, custom fields,
  organisation name, audit log and reports. Nothing crosses between them; switching from
  the header picker is instant with no re-upload, and the choice survives a reload.
  Downloads from a non-default workspace are prefixed with its name so files never
  collide. Managed in Admin → *Workspaces* (create, rename, delete; the default one
  cannot be deleted). "Reset all data" now applies to the current workspace only.
- **v61** — **Merge links on hostname + interface**, not just hostname. A hardware/model
  swap renames the host *and* re-numbers the port (`core-1 Gi0/1` → `core-1a Te0/0/0/1`),
  so the link id changes on both halves and a device merge alone leaves two half-length
  links with a split history and forecast. New picker in Admin → *Device & link identity*
  merges one whole link identity into another; sample counts and date spans are shown in
  the picker, overlapping histories are warned about, and per-link overrides, RCA notes,
  comments and the watchlist follow the merge. A sample whose timestamp already exists on
  the kept link is skipped as a duplicate (same rule as ingest) and the count is reported.
  The capacity change across the swap is handled by the existing per-sample capacity logic.
- **v60** — **Fixed: the chart stopping before the data does.** Maintenance exclusion was
  stamped onto each sample at *upload* time and never re-evaluated, so a window covering a
  date range permanently hid those samples from the chart, `Data through`, p95/peak and every
  report — while the processed-data export still listed them. Maintenance is now evaluated
  **live** against the current windows (add or delete a window and the data updates
  immediately, in both directions). Every exclusion is now **stated, not silent**: a notice
  above the link chart names the count, the reason, the affected dates and the fix; the
  processed-data export gains an **"Excluded from analytics"** column; the Threshold Breach
  PDF declares exclusions in its Reporting parameters.
- **v52** — New per-link **Threshold Breach PDF** (6-month Warning/Critical counts +
  full timestamped detail, market/non-market option, professional sign-off layout).
  **White-labelled** the whole app (removed all BSE/SEBI/NSE/RBI/CERT-In names; org name
  is now a blank Admin field).
- **v51** — Processed-data export shows timestamps **to the second** (exact reconciliation).
- **v50** — **Fixed unit bug**: a header like `Transmit bps` was reading the trailing "t"
  of "Transmit" as a *tera* prefix (×10¹²); traffic & utilization now correct. Bare "bps"
  treated as metric name, magnitude decides scale.
- **v49** — Clarified raw rows are kept **1:1, never resampled**; "Cadence" relabelled
  "Median interval (rows kept as-is)"; verified seconds preserved.
- **v48** — Admin **time-zone** setting: your zone + input times local-vs-UTC.
- **v47** — Timestamps parsed **as-is, no timezone shift** (fixed Excel-serial vs string
  inconsistency); verified identical across IST/Tokyo/New York.
- **v45–v46** — Over-100% samples **never dropped**; kept, counted, and **flagged for
  capacity review** in the Upgrade tab (link likely upgraded / stale capacity). New
  **Download processed data** audit export. Hardcoded 120% ceiling → Admin-configurable flag.
- **v44** — Charts adapt to **per-sample capacity changes** (mid-history upgrades); a
  "capacity changed" banner; tooltip shows true throughput.
- **v42–v43** — Policy Hits report lists **both market and non-market** crossings, tagged;
  chart gains an amber **policy line**; off-hours reconciliation note.
- **v41** — "Last hit" + "Data through" columns so a quiet recent stretch isn't mistaken
  for missing data.
- **v40** — Policy Hits export split into **Hits by Day** + **Hits by Date-Time** sheets.
- **v39** — Per-month **policy-hits strip** on each link's Upgrade-watch panel (spot data gaps).

**Earlier iterations:**

- **v38** — Offline-safe visual refresh (design tokens + polish).
- **v37** — Fixed chart/graph overflow spilling outside panels on all pages.
- **v36** — Enforced the **offline invariant** (CSP) and recorded the rule.
- **v35** — Three compliance alignments (default threshold, 180-day window, headroom flag).
- **v34** — Forecast precision pack (confidence range, deseasonalize, peak basis, market hours).
- **v33** — Interface-page upgrade watch, anomaly reasons, heatmap values.
- **v31–v32** — Merge device-name variants (FQDN vs short hostname); manual merge of any two.
- **v30** — Expose device-name-variant fragments in report scope.
- **v28–v29** — Surface links-with-hits; explain zero-hit exports; rank report pickers.
- **v27** — Upgrade-report consistency; full-history views by default.
- **v26** — Logic-audit fixes across analytics (timezone, look-back window, business-hour
  minutes, weekend anomaly baseline, CSV alignment, speed parsing).
- **v25** — Forecast metric/direction, provision-to-N×peak, editable class bands, CSV export.
- **v9–v23** — Grouped multi-file upload (map once) + upgrade policy; large-dataset scaling;
  streaming ingest; editable RCA + per-link HTML/PDF export + plain-English summary;
  fleet anomaly chart; per-interface business-hours analysis & filters; rhythm heatmap;
  Upgrade Watch dashboard; Upgrade Policy Hits xlsx; inline glossary tooltips; Regulatory
  Capacity Report; Historical-view crash fix.

---

## Key issues fixed (root causes)

1. **Traffic & utilization wrong** — header unit regex grabbed a word's trailing letter as
   a size prefix (`Transmit bps` → tera ×10¹²). Fixed; bare "bps" no longer forces bits/s.
2. **Timestamps shifted** — Excel serial dates parsed as UTC while strings were local.
   Now all formats kept as wall-clock as-is; optional UTC→local via Admin.
3. **"Missing" recent hits** — device-name variants splitting a link, and market-hours-only
   policy hiding off-hours peaks. Fixed with variant merge, market/non-market split, and
   per-month strips.
4. **Samples "sampled at 9 min"** — misread label; data is kept 1:1, "9 min" was just the
   descriptive median cadence. Relabelled.
5. **Over-100% data dropped** — now kept and flagged for capacity review instead.
6. **Capacity changes** — per-sample capacity honored everywhere; surfaced to the user.
7. **Stale exports** — confirmed a mismatched sheet came from an older build; verified the
   current build reproduces the raw file exactly (value + timestamp).

---

*NetPulse is a management aid. Regulatory thresholds/formats must be validated by your
compliance function against your applicable circulars. Fully offline; no data leaves the browser.*
