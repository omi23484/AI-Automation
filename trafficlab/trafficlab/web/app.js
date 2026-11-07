"use strict";
// trafficlab UI. No external libs. All dynamic text goes through textContent (never innerHTML).
const $ = (s, r = document) => r.querySelector(s);
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
}
async function api(path, body, raw) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({ error: "bad response" }));
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}
const fmtN = (x, d = 0) => x == null ? "" : Number(x).toLocaleString(undefined, { maximumFractionDigits: d });
const fmtBps = x => x == null ? "" : x >= 1e9 ? (x / 1e9).toFixed(2) + " Gbps" : x >= 1e6 ? (x / 1e6).toFixed(2) + " Mbps" : x >= 1e3 ? (x / 1e3).toFixed(1) + " kbps" : x.toFixed(0) + " bps";
const S = { defaults: null, validation: null, result: null, tab: "Import", sel: null, crs: [], mapping: null, headers: null, text: null };
const TABS = ["Import", "Overview", "Anomalies", "Pattern Shifts", "Devices", "CR Tracker", "Explain", "Export"];
const MAP_TEMPLATE = {
  device: "device", interface: "interface", timestamp: "timestamp", zone: null,
  counters: [{ name: "in_bps", column: "in_octets", bits: 64, mult: 8, unit: "bps" }, { name: "out_bps", column: "out_octets", bits: 64, mult: 8, unit: "bps" }],
  gauges: [], uptime: { column: "uptime_cs", unit: "cs" }, speed: { column: "speed_mbps", unit: "mbps" }
};

function theme() {
  let t = null; try { t = localStorage.getItem("tl-theme"); } catch (e) { }
  if (!t) t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = t;
}
$("#theme").onclick = () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t; try { localStorage.setItem("tl-theme", t); } catch (e) { }
  if (chart) chart.draw();
};
theme();

function nav() {
  const n = $("#tabs"); n.replaceChildren(...TABS.map(t => h("button", { class: t === S.tab ? "on" : "", onclick: () => { S.tab = t; render(); } }, t)));
}
async function render() {
  nav(); chart = null;
  const m = $("#main"); m.replaceChildren();
  try { await ({ Import: tImport, Overview: tOverview, Anomalies: () => tFindings("anomaly"), "Pattern Shifts": () => tFindings("pattern_shift"), Devices: tDevices, "CR Tracker": tCR, Explain: tExplain, Export: tExport })[S.tab](m); }
  catch (e) { m.append(h("div", { class: "banner err" }, "Error: " + e.message)); }
}
function setStatus(t) { $("#status").textContent = t; }

// ------------------------------------------------------------------ Import
async function tImport(m) {
  if (!S.defaults) S.defaults = await api("/api/defaults");
  const file = h("input", { type: "file", accept: ".csv,.txt,.tsv" });
  const delim = h("input", { value: ",", size: 2 });
  const tz = h("input", { value: "UTC", size: 22, title: "IANA name, e.g. UTC, Europe/London. Used ONLY for timestamps without an offset" });
  const fmts = h("input", { size: 60, placeholder: "e.g. %Y-%m-%d %H:%M:%S  (comma separated; blank = built-in ISO candidates; epoch_s / epoch_ms allowed)" });
  const map = h("textarea", { rows: 16 }, JSON.stringify(S.mapping || MAP_TEMPLATE, null, 2));
  const inv = h("input", { type: "file", accept: ".csv" });
  const hdr = h("div", { class: "muted" }, "Pick a file to see its header columns.");
  file.onchange = async () => {
    const f = file.files[0]; if (!f) return;
    S.text = await f.text(); S.fname = f.name;
    const first = S.text.replace(/^﻿/, "").split(/\r?\n/, 1)[0];
    hdr.textContent = "Columns: " + first + "   (" + fmtN(f.size / 1e6, 1) + " MB)";
  };
  const out = h("div");
  const presetSel = h("select", {}, h("option", { value: "" }, "preset: none (use mapping below)"), ...Object.entries(S.defaults.presets || {}).map(([k, v]) => h("option", { value: k, title: v.description }, k)));
  presetSel.onchange = () => { const p = (S.defaults.presets || {})[presetSel.value]; if (!p) return; map.value = JSON.stringify(p.mapping, null, 2); fmts.value = p.ts_formats.join(","); hdr.textContent = p.description; };
  const doImport = async () => {
    out.replaceChildren(h("div", { class: "muted" }, "importing..."));
    try {
      if (!S.text) throw new Error("choose a file first");
      const mapping = JSON.parse(map.value);
      const invText = inv.files[0] ? await inv.files[0].text() : null;
      const r = await api("/api/import", { csv_text: S.text, mapping, ts_formats: fmts.value.trim() ? fmts.value.split(",").map(s => s.trim()) : null, tz: tz.value.trim(), delimiter: delim.value || ",", inventory_text: invText, source: S.fname });
      S.validation = r.validation; S.result = null; showValidation(out);
    } catch (e) { out.replaceChildren(h("div", { class: "banner err" }, e.message)); }
  };
  const synth = async () => {
    out.replaceChildren(h("div", { class: "muted" }, "generating SYNTHETIC data..."));
    const r = await api("/api/synth", { mixed_formats: true });
    S.validation = r.validation; S.result = null; showValidation(out);
    out.prepend(h("div", { class: "banner" }, "SYNTHETIC DATA (fake). Ground truth: ", h("pre", { class: "mono" }, JSON.stringify(r.manifest.ground_truth, null, 1))));
  };
  m.append(
    h("div", { class: "banner" }, "Data stays on this machine (server bound to 127.0.0.1). Raw rows are never modified; timestamps keep ts_raw and get a separate ts_parsed. No captures are bundled: provide your own CSV."),
    h("div", { class: "card" }, h("div", { class: "row" }, presetSel), h("div", { class: "row" }, file, "delimiter", delim, "timezone for offset-less timestamps", tz), h("div", { class: "row" }, "timestamp formats", fmts), hdr,
      h("div", { class: "row" }, "optional inventory CSV (device,zone[,interface,speed_bps])", inv)),
    h("div", { class: "card" }, h("b", {}, "Column mapping (JSON)"), h("div", { class: "muted" }, "counter: cumulative (bits 32/64, mult 8 for octets->bits). gauge: value already a rate. uptime unit: s | cs (SNMP TimeTicks) | ms. speed unit: bps|kbps|mbps. zone: column name or null (inventory / 'unassigned')."), map),
    h("div", { class: "row" }, h("button", { class: "pri", onclick: doImport }, "Import + validate"), h("button", { onclick: synth }, "Load SYNTHETIC demo")),
    out);
  if (S.validation) showValidation(out);
}
function showValidation(out) {
  const v = S.validation; out.replaceChildren();
  const tr = v.timestamps;
  out.append(h("h3", {}, "Validation report (before analysis)"),
    h("div", {}, `source: ${v.source} · rows: ${fmtN(v.rows)} · series: ${v.series_count} · timestamp formats: `, h("span", { class: "mono" }, JSON.stringify(tr.formats)), ` · assumed tz: ${tr.tz_assumed}`),
    h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "severity"), h("th", {}, "message"))), h("tbody", {}, v.issues.map(i => h("tr", {}, h("td", { class: i.severity }, i.severity), h("td", {}, i.message))))));
  if (tr.unparseable_samples.length) out.append(h("details", {}, h("summary", {}, `unparseable / ambiguous timestamps (first ${tr.unparseable_samples.length})`), h("table", {}, h("tr", {}, h("th", {}, "line"), h("th", {}, "ts_raw (exact)"), h("th", {}, "flags")), tr.unparseable_samples.map(r => h("tr", {}, h("td", {}, r.line), h("td", { class: "mono" }, JSON.stringify(r.ts_raw)), h("td", {}, r.flags.join(",")))))));
  out.append(h("details", {}, h("summary", {}, "series list"), h("div", { class: "scroll" }, h("table", {}, h("tr", {}, ["series", "zone", "samples", "points", "interval s", "excluded", "speed"].map(x => h("th", {}, x))), v.series.map(s => h("tr", {}, h("td", { class: "mono" }, s.key), h("td", {}, s.zone), h("td", {}, s.samples), h("td", {}, s.points), h("td", {}, s.interval_s), h("td", {}, s.excluded), h("td", {}, fmtBps(s.speed_bps))))))));
  const cfg = h("textarea", { rows: 10, id: "cfg" }, JSON.stringify(S.defaults.config, null, 2));
  const prog = h("span", { class: "muted" });
  out.append(h("h3", {}, "Run analysis"), h("div", { class: "muted" }, "Config below = defaults chosen by the author (not standards). Edit freely; add per-zone overrides under \"zones\", e.g. {\"WAN\":{\"anomaly\":{\"z_threshold\":5}}}."), cfg,
    h("div", { class: "row" }, h("button", { class: "pri", onclick: async () => { try { await api("/api/analyze", { config: JSON.parse(cfg.value) }); poll(prog); } catch (e) { prog.textContent = "error: " + e.message; } } }, "Analyze"), prog));
}
async function poll(el) {
  for (; ;) {
    const s = await api("/api/status");
    el.textContent = `${s.state} ${s.done}/${s.total}`; setStatus(el.textContent);
    if (s.state === "done") { S.result = await api("/api/result"); S.tab = "Overview"; setStatus("analysis done"); return render(); }
    if (s.state === "error") { el.textContent = "error: " + s.error; return; }
    await new Promise(r => setTimeout(r, 400));
  }
}

// ------------------------------------------------------------------ Overview
async function tOverview(m) {
  if (!S.result) { try { S.result = await api("/api/result"); } catch (e) { m.append(h("div", { class: "banner" }, "No analysis yet. Import data and click Analyze.")); return; } }
  const r = S.result, c = r.counts;
  m.append(h("div", { class: "banner" }, h("span", { class: "tag stat" }, "statistical"), " = computed by deterministic math with numbers shown.  ", h("span", { class: "tag interp" }, "interpretation"), " = rule-based candidate, never proof. No language model is involved."),
    h("div", { class: "row" }, h("b", {}, `${c.primary} primary findings`), `(${c.findings} total incl. continuations) · ${c.clusters} cross-device clusters · ${c.series} series · ${r.elapsed_s}s on ${r.workers} workers`),
    h("table", {}, h("tr", {}, ["zone", "devices", "series", "points", "primary findings"].map(x => h("th", {}, x))), Object.entries(r.zones).map(([z, v]) => h("tr", {}, h("td", {}, z), h("td", {}, v.devices), h("td", {}, v.series), h("td", {}, fmtN(v.points)), h("td", {}, v.findings)))));
  const { findings, clusters } = await api("/api/findings?hide_continuation=1");
  m.append(h("h3", {}, "Cross-device clusters"), clusters.length ? h("table", {}, h("tr", {}, ["id", "devices", "zones", "mean r", "label (interpretation)", "CR candidates"].map(x => h("th", {}, x))),
    clusters.map(c => h("tr", { onclick: () => { S.sel = c.id; S.tab = "Explain"; render(); } }, h("td", { class: "mono" }, c.id), h("td", {}, c.devices.join(", ")), h("td", {}, c.zones.join(", ") + (c.cross_zone ? " (cross-zone)" : "")), h("td", {}, c.mean_pearson_r ?? "n/a"), h("td", {}, c.label), h("td", {}, (c.cr_candidates || []).map(x => x.cr_id).join(", "))))) : h("div", { class: "muted" }, "none"));
  m.append(h("h3", {}, "Top primary findings"), findingsTable(findings.slice(0, 15)));
}

// ------------------------------------------------------------------ Findings
function findingsTable(fs, onsel) {
  return h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, ["sev", "zone", "device / if / metric", "ts_raw window", "dir", "numbers (statistical)", "conf", "interpretation / CR"].map(x => h("th", {}, x)))),
    h("tbody", {}, fs.map(f => h("tr", { class: S.sel === f.id ? "sel" : "", onclick: () => { S.sel = f.id; onsel ? onsel(f) : (S.tab = "Anomalies", render()); } },
      h("td", { class: f.severity }, f.severity), h("td", {}, f.zone), h("td", { class: "mono" }, `${f.device} ${f.interface} ${f.metric}`), h("td", { class: "mono" }, f.window.start_raw + (f.window.end_raw !== f.window.start_raw ? " → " + f.window.end_raw : "")),
      h("td", {}, f.direction), h("td", { class: "mono" }, summarize(f)), h("td", {}, f.confidence.level), h("td", {}, f.interpretation.map(i => i.claim).join(" | ").slice(0, 160), f.cr_candidates.length ? " [CR: " + f.cr_candidates.map(c => c.cr_id).join(",") + "]" : ""))))));
}
function summarize(f) {
  const n = f.numbers;
  if (f.kind === "pattern_shift") return `${n.change_pct}%  t=${n.t_stat}  before ${fmtBps(n.raw_mean_before)} after ${fmtBps(n.raw_mean_after)}`;
  return `peak|z|=${n.seasonal_peak_abs_z ?? "-"} dev=${n.deviation_pct ?? "-"}%  ewmaS=${n.ewma_peak_S ?? "-"}`;
}
async function tFindings(kind) {
  const m = $("#main");
  if (!S.result) { try { S.result = await api("/api/result"); } catch (e) { m.append(h("div", { class: "banner" }, "No analysis yet.")); return; } }
  const hide = h("input", { type: "checkbox", checked: true }), sev = h("select", {}, ["all", "high", "medium", "low"].map(x => h("option", {}, x))), zone = h("select", {}, ["all", ...Object.keys(S.result.zones)].map(x => h("option", {}, x))), txt = h("input", { placeholder: "device/interface filter" });
  const list = h("div"), detail = h("div");
  const load = async () => {
    const { findings } = await api(`/api/findings?kind=${kind}` + (hide.checked ? "&hide_continuation=1" : ""));
    let fs = findings.filter(f => (sev.value === "all" || f.severity === sev.value) && (zone.value === "all" || f.zone === zone.value) && (f.device + " " + f.interface).toLowerCase().includes(txt.value.toLowerCase()));
    list.replaceChildren(h("div", { class: "muted" }, `${fs.length} shown`), findingsTable(fs, f => showFinding(detail, f, load)));
    const cur = fs.find(f => f.id === S.sel); if (cur) showFinding(detail, cur, load);
  };
  [hide, sev, zone].forEach(e => e.onchange = load); txt.oninput = load;
  m.append(h("div", { class: "row" }, kind === "anomaly" ? h("label", {}, hide, "hide continuations of a pattern shift (R6)") : "", "severity", sev, "zone", zone, txt),
    kind === "pattern_shift" ? h("div", { class: "muted" }, "Shift time resolution is 1 hour. Seasonal profile removed first; refuses when history < 5 days. Statistic is a heuristic score, not a calibrated p-value.") : "", list, detail);
  load();
}
async function showFinding(el, f, reload) {
  el.replaceChildren();
  const cv = h("canvas"); const info = h("div");
  const mathRows = f.math.map(x => h("div", {}, h("b", {}, x.method + ": "), h("span", { class: "mono" }, x.formula), h("pre", {}, JSON.stringify(x.params, null, 1))));
  const linkSel = h("select", {}, h("option", { value: "" }, "link to CR..."), ...(await api("/api/crs")).crs.map(c => h("option", { value: c.cr_id }, c.cr_id + " " + c.title)));
  linkSel.onchange = async () => { if (linkSel.value) { await api("/api/crs/link", { cr_id: linkSel.value, finding_id: f.id }); linkSel.value = ""; setStatus("linked"); } };
  el.append(h("div", { class: "card" }, h("b", {}, `${f.id} · ${f.kind} · ${f.device} ${f.interface} ${f.metric} · ${f.zone}`), cv,
    h("div", { class: "split" }, h("div", {}, h("div", {}, h("span", { class: "tag stat" }, "statistical"), " numbers"), h("pre", {}, JSON.stringify(f.numbers, null, 1)), h("div", {}, "window: ", h("span", { class: "mono" }, `ts_raw ${f.window.start_raw} → ${f.window.end_raw}`)),
      h("div", { class: "mono" }, `ts_parsed ${f.window.start_ts_parsed.epoch_ms} → ${f.window.end_ts_parsed.epoch_ms} ms | fmt ${f.window.start_ts_parsed.format} | tz ${f.window.start_ts_parsed.tz_assumed} (${f.window.start_ts_parsed.tz_source})`),
      h("div", {}, `confidence: ${f.confidence.level} — ${f.confidence.justification}`)),
      h("div", {}, h("div", {}, h("span", { class: "tag stat" }, "statistical"), " exact math"), mathRows)),
    h("div", {}, h("span", { class: "tag interp" }, "interpretation"), " (candidate only):", h("ul", {}, f.interpretation.map(i => h("li", {}, i.claim, " ", h("span", { class: "mono muted" }, "[" + i.evidence.join(", ") + "]"))))),
    f.cr_candidates.length ? h("div", {}, h("b", {}, "CR candidates: "), f.cr_candidates.map(c => h("div", {}, `${c.cr_id} ${c.title} — ${c.relation}${c.delta_s ? " +" + (c.delta_s / 3600).toFixed(1) + "h" : ""} (${c.window_used} window) — ${c.label}`))) : "",
    h("div", { class: "row" }, linkSel, h("button", { onclick: () => { S.sel = f.id; S.tab = "Explain"; render(); } }, "Explain"))));
  const crs = (await api("/api/crs")).crs;
  chart = new Chart(cv, f.series_key, { findings: [f], crs: crs.filter(c => c.scope.some(s => s.device === f.device)), focus: [f.window.start_ms, f.window.end_ms] });
  chart.load();
}

// ------------------------------------------------------------------ Devices
async function tDevices(m) {
  const checks = h("div"); await checksSection(checks);
  const { series } = await api("/api/series_list");
  if (!series.length) { m.append(h("div", { class: "banner" }, "No traffic analysis yet (Import tab). Device checks below work independently."), checks); return; }
  m.append(checks);
  const cv = h("canvas"); const note = h("div", { class: "muted" }, "Click a series to chart it. Overlays: anomaly windows (red), shifts (dashed), CR windows (purple), excluded intervals/gaps (grey hatch).");
  const crs = (await api("/api/crs")).crs, all = (await api("/api/findings?hide_continuation=1")).findings;
  m.append(note, cv, h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, ["zone", "series", "pts", "excl", "interval", "p50", "p95", "p99", "max", "util p95 %", "baseline tiers", "shift status"].map(x => h("th", {}, x)))),
    h("tbody", {}, series.map(s => h("tr", { onclick: ev => { document.querySelectorAll("tbody tr.sel").forEach(x => x.classList.remove("sel")); ev.currentTarget.classList.add("sel"); chart = new Chart(cv, s.key, { findings: all.filter(f => f.series_key === s.key), crs: crs.filter(c => c.scope.some(x => x.device === s.device)) }); chart.load(); } },
      h("td", {}, s.zone), h("td", { class: "mono" }, s.key), h("td", {}, fmtN(s.n_points)), h("td", {}, s.excluded), h("td", {}, s.interval_s), h("td", {}, fmtBps(s.p50)), h("td", {}, fmtBps(s.p95)), h("td", {}, fmtBps(s.p99)), h("td", {}, fmtBps(s.max)),
      h("td", {}, s.util_p95_pct == null ? "n/a (no speed)" : s.util_p95_pct.toFixed(1)), h("td", { class: "mono" }, JSON.stringify(s.baseline.tier_counts)), h("td", {}, s.shift_status.status + (s.shift_status.reason ? ": " + s.shift_status.reason : ""))))))));
}

// ------------------------------------------------------------------ Device checks (Module 4)
async function checksSection(box) {
  const dev = h("input", { size: 14, placeholder: "device name (if files not in device folders)" });
  const files = h("input", { type: "file", multiple: true, accept: ".txt,.log" });
  const folder = h("input", { type: "file", webkitdirectory: true, multiple: true });
  const zip = h("input", { type: "file", accept: ".zip" });
  const pol = h("select", {}, h("option", { value: "latest" }, "latest pass per device+command"), h("option", { value: "all" }, "all passes"));
  const opt = h("textarea", { rows: 3, placeholder: '{"groups":{"leaf1":"fabricA","leaf2":"fabricA"},"waivers":[{"rule":"DC05","device":"*","contains":"192.0.2.2","reason":"lab: no peer by design"}]}' });
  const out = h("div"), msg = h("span", { class: "muted" });
  const b64 = f => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.onerror = no; r.readAsDataURL(f); });
  const run = async () => {
    try {
      msg.textContent = "uploading..."; const body = { pass_policy: pol.value, devcheck: opt.value.trim() ? JSON.parse(opt.value) : {} };
      if (zip.files[0]) body.zip_b64 = await b64(zip.files[0]);
      else {
        const fl = [...(folder.files.length ? folder.files : files.files)]; if (!fl.length) throw new Error("choose files, a folder or a zip");
        body.device = dev.value; body.files = await Promise.all(fl.map(async f => ({ name: f.webkitRelativePath || f.name, text: await f.text() })));
      }
      await api("/api/checks/upload", body); msg.textContent = "done"; await showChecks(out);
    } catch (e) { msg.textContent = ""; out.replaceChildren(h("div", { class: "banner err" }, e.message)); }
  };
  box.append(h("h3", {}, "Device checks (rule-based, from raw show output)"),
    h("div", { class: "muted" }, "Captures need a 'COMMAND: show ...' first line, 'host# show ...' prompts, or show_*.txt names, in <device>/ folders (a <pass>/<device>/ layout is understood). Parsed: interface error counters & status, port-channel, STP, BGP, OSPF, BFD, vPC, HSRP, logging, clock. Everything else is listed as not parsed."),
    h("div", { class: "card" }, h("div", { class: "row" }, "files", files, "or folder", folder, "or .zip", zip), h("div", { class: "row" }, dev, pol),
      h("div", { class: "row" }, h("label", {}, "optional config JSON (devcheck groups / waivers / thresholds)", opt)), h("div", { class: "row" }, h("button", { class: "pri", onclick: run }, "Run checks"), msg)), out);
  try { const r0 = await api("/api/checks/result"); if (!r0.empty) await showChecks(out); } catch (e) { }
}
async function showChecks(out) {
  const r = await api("/api/checks/result"), sm = r.summary, ev = h("div"), sevSel = h("select", {}, ["all", "critical", "warning", "info"].map(x => h("option", {}, x))), txt = h("input", { placeholder: "filter device / text" });
  const list = h("div");
  const draw = () => {
    const fs = r.findings.filter(f => (sevSel.value === "all" || f.severity === sevSel.value) && (f.device + " " + f.title + " " + f.rule).toLowerCase().includes(txt.value.toLowerCase()));
    list.replaceChildren(h("div", { class: "muted" }, `${fs.length} shown`), h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, ["sev", "rule", "device", "finding", "detail", ""].map(x => h("th", {}, x)))),
      h("tbody", {}, fs.map(f => h("tr", { onclick: () => showEv(ev, f) }, h("td", { class: f.severity === "critical" ? "high" : f.severity === "warning" ? "medium" : "low" }, f.severity), h("td", {}, f.rule), h("td", {}, f.device), h("td", {}, f.title), h("td", {}, f.detail.slice(0, 140)),
        h("td", {}, (f.waived ? "waived: " + f.waived + " " : "") + (f.verify_on_device ? "verify on device" : ""))))))));
  };
  sevSel.onchange = draw; txt.oninput = draw;
  out.replaceChildren(h("div", {}, h("b", {}, `${sm.devices} devices · ${sm.captures} captures · ${sm.findings} findings`), " ", JSON.stringify(sm.by_severity), ` · waived ${sm.waived}  `,
    h("a", { href: "/api/export/devcheck-report", download: "devcheck.html" }, h("button", {}, "HTML report")), h("a", { href: "/api/export/devcheck", download: "devcheck.json" }, h("button", {}, "JSON"))),
    h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, ["device", "captures", "critical", "warning", "info", "waived", "parsed", "not parsed", "rejected by device"].map(x => h("th", {}, x)))),
      h("tbody", {}, Object.entries(r.devices).map(([d, v]) => h("tr", {}, h("td", { class: "mono" }, d), h("td", {}, v.n_captures), h("td", {}, v.counts.critical || 0), h("td", {}, v.counts.warning || 0), h("td", {}, v.counts.info || 0), h("td", {}, v.waived), h("td", {}, v.coverage.parsed.length), h("td", {}, v.coverage.not_parsed.length), h("td", {}, v.coverage.rejected.length)))))),
    h("div", { class: "row" }, "severity", sevSel, txt), list, ev,
    h("details", {}, h("summary", {}, "rules (no hidden logic)"), h("table", {}, h("tr", {}, ["id", "name", "condition", "source fields"].map(x => h("th", {}, x))), r.rules.map(x => h("tr", {}, h("td", {}, x.id), h("td", {}, x.name), h("td", {}, x.condition), h("td", {}, x.source))))));
  draw();
}
function showEv(el, f) {
  el.replaceChildren(h("div", { class: "card" }, h("b", {}, `${f.id} [${f.rule}] ${f.device}: ${f.title}`), h("div", {}, f.detail), f.waived ? h("div", { class: "banner" }, "Waived: " + f.waived) : "", f.verify_on_device ? h("div", { class: "banner" }, "Rests on values seen in captures only. Verify on device.") : "",
    h("div", { class: "scroll" }, h("table", {}, h("tr", {}, ["device", "command", "line", "field", "value", "raw text"].map(x => h("th", {}, x))), f.evidence.map(e => h("tr", {}, h("td", {}, e.device), h("td", { class: "mono" }, e.command), h("td", {}, e.line), h("td", {}, e.field), h("td", { class: "mono" }, e.value), h("td", { class: "mono" }, e.text)))))));
}

// ------------------------------------------------------------------ Chart (canvas, zoom/pan, overlays)
let chart = null;
class Chart {
  constructor(cv, key, ov) {
    this.cv = cv; this.key = key; this.ov = ov; this.d = null; this.view = null; this.full = null; this.hover = null; this.drag = null; this.timer = null;
    cv.onwheel = e => { e.preventDefault(); this.zoom(e); };
    cv.onmousedown = e => { this.drag = { x: e.offsetX, v: [...this.view] }; };
    window.onmouseup = () => { if (this.drag) { this.drag = null; this.sched(); } };
    cv.onmousemove = e => this.move(e);
    cv.onmouseleave = () => { this.hover = null; this.draw(); };
    cv.ondblclick = () => { this.view = [...this.full]; this.sched(0); };
  }
  async load(t0, t1) {
    const q = `/api/series?key=${encodeURIComponent(this.key)}&max=2400` + (t0 ? `&t0=${Math.floor(t0)}&t1=${Math.ceil(t1)}` : "");
    const d = await api(q); if (!this.full) { this.full = [...d.span]; this.view = this.ov.focus ? this.focusView(d.span) : [...d.span]; if (this.ov.focus) return this.load(this.view[0], this.view[1]); }
    this.d = d; this.draw();
  }
  focusView([a, b]) { const [f0, f1] = this.ov.focus, w = Math.max(f1 - f0, 3600000); return [Math.max(a, f0 - 12 * w), Math.min(b, f1 + 12 * w)]; }
  sched(ms = 150) { clearTimeout(this.timer); this.timer = setTimeout(() => this.load(this.view[0], this.view[1]), ms); }
  zoom(e) {
    const [a, b] = this.view, w = this.cv.clientWidth - 60, x = Math.max(0, Math.min(1, (e.offsetX - 50) / w)), t = a + (b - a) * x, k = e.deltaY < 0 ? 0.7 : 1.4;
    let na = t - (t - a) * k, nb = t + (b - t) * k; na = Math.max(this.full[0], na); nb = Math.min(this.full[1], nb); if (nb - na < 60000) return;
    this.view = [na, nb]; this.draw(); this.sched();
  }
  move(e) {
    const w = this.cv.clientWidth - 60;
    if (this.drag) { const dt = (this.drag.x - e.offsetX) / w * (this.drag.v[1] - this.drag.v[0]); let a = this.drag.v[0] + dt, b = this.drag.v[1] + dt; if (a < this.full[0]) { b += this.full[0] - a; a = this.full[0]; } if (b > this.full[1]) { a -= b - this.full[1]; b = this.full[1]; } this.view = [a, b]; this.draw(); return; }
    if (!this.d || !this.d.t.length) return;
    const t = this.view[0] + (e.offsetX - 50) / w * (this.view[1] - this.view[0]); let bi = 0, bd = 1e30;
    this.d.t.forEach((x, i) => { const dd = Math.abs(x - t); if (dd < bd) { bd = dd; bi = i; } }); this.hover = bi; this.draw();
  }
  draw() {
    const cv = this.cv, dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight; cv.width = W * dpr; cv.height = H * dpr;
    const g = cv.getContext("2d"); g.scale(dpr, dpr); const cs = getComputedStyle(document.documentElement), C = n => cs.getPropertyValue(n).trim();
    g.clearRect(0, 0, W, H); g.font = "11px system-ui"; const L = 50, R = 10, T = 10, B = 22, pw = W - L - R, ph = H - T - B;
    if (!this.d) { g.fillStyle = C("--mut"); g.fillText("loading...", L, 30); return; }
    const [a, b] = this.view, X = t => L + (t - a) / (b - a) * pw; let vmax = Math.max(1, ...this.d.v), vmin = 0; if (this.d.speed_bps && vmax < this.d.speed_bps * 0.05) { /* keep own scale */ }
    const Y = v => T + ph - (v - vmin) / (vmax - vmin) * ph * 0.95;
    // overlays
    const band = (t0, t1, col, label) => { const x0 = Math.max(L, X(t0)), x1 = Math.min(L + pw, X(t1)); if (x1 < L || x0 > L + pw) return; g.fillStyle = col; g.fillRect(x0, T, Math.max(2, x1 - x0), ph); if (label) { g.fillStyle = C("--fg"); g.fillText(label, x0 + 2, T + 10); } };
    (this.d.excluded || []).forEach(e => { band(e.start_ms, e.end_ms, "rgba(128,128,128,.28)", e.type); });
    (this.ov.crs || []).forEach(c => { const w = c.actual_start_ms != null ? [c.actual_start_ms, c.actual_end_ms ?? c.actual_start_ms] : [c.planned_start_ms, c.planned_end_ms]; if (w[0] != null) band(w[0], w[1], "rgba(123,63,228,.28)", c.cr_id); });
    (this.ov.findings || []).forEach(f => { if (f.kind === "anomaly") band(f.window.start_ms, f.window.end_ms, "rgba(217,48,37,.25)", f.severity); else { g.strokeStyle = C("--amb"); g.setLineDash([5, 4]); const x = X(f.window.start_ms); g.beginPath(); g.moveTo(x, T); g.lineTo(x, T + ph); g.stroke(); g.setLineDash([]); g.fillStyle = C("--amb"); g.fillText("shift " + (f.numbers.change_pct ?? ""), x + 3, T + 22); } });
    // axes
    g.strokeStyle = C("--bd"); g.fillStyle = C("--mut"); g.beginPath(); g.moveTo(L, T); g.lineTo(L, T + ph); g.lineTo(L + pw, T + ph); g.stroke();
    for (let i = 0; i <= 4; i++) { const v = vmin + (vmax - vmin) * i / 4 * 1; g.fillText(this.d.unit === "bps" ? fmtBps(v) : fmtN(v, 1), 2, Y(v) + 3); }
    for (let i = 0; i <= 4; i++) { const t = a + (b - a) * i / 4; g.fillText(new Date(t).toISOString().slice(0, 16).replace("T", " ") + "Z", L + pw * i / 4 - (i === 4 ? 100 : i ? 40 : 0), H - 6); }
    // line (break at excluded intervals / large dt)
    g.strokeStyle = C("--line"); g.lineWidth = 1.2; g.beginPath(); let pen = false, pt = null; const brk = (this.d.interval_ms || 0) * 1.5 * (this.d.decimated ? 1e9 : 1);
    this.d.t.forEach((t, i) => { const x = X(t), y = Y(this.d.v[i]); const cut = (this.d.excluded || []).some(e => pt != null && e.start_ms >= pt && e.end_ms <= t) || (pt != null && !this.d.decimated && t - pt > brk); if (!pen || cut) { g.moveTo(x, y); pen = true; } else g.lineTo(x, y); pt = t; }); g.stroke();
    if (this.d.speed_bps && this.d.speed_bps <= vmax * 1.2) { g.strokeStyle = C("--grn"); g.setLineDash([3, 3]); g.beginPath(); g.moveTo(L, Y(this.d.speed_bps)); g.lineTo(L + pw, Y(this.d.speed_bps)); g.stroke(); g.setLineDash([]); g.fillStyle = C("--grn"); g.fillText("configured speed", L + 4, Y(this.d.speed_bps) - 3); }
    if (this.d.decimated) { g.fillStyle = C("--amb"); g.fillText("display decimated (min/max per bucket); zoom for raw points", L + 4, H - 20 > 0 ? T + ph - 4 : 10); }
    if (this.hover != null) { const i = this.hover, x = X(this.d.t[i]), y = Y(this.d.v[i]); g.fillStyle = C("--fg"); g.beginPath(); g.arc(x, y, 3, 0, 7); g.fill();
      const lines = ["ts_raw: " + this.d.raw[i], "epoch_ms: " + this.d.t[i], "rate: " + (this.d.unit === "bps" ? fmtBps(this.d.v[i]) : fmtN(this.d.v[i], 2)), "method: " + this.d.method[i]], tw = Math.max(...lines.map(l => g.measureText(l).width)) + 10, tx = Math.min(x + 8, W - tw - 4);
      g.fillStyle = C("--bg2"); g.strokeStyle = C("--bd"); g.fillRect(tx, T + 4, tw, 54); g.strokeRect(tx, T + 4, tw, 54); g.fillStyle = C("--fg"); lines.forEach((l, k) => g.fillText(l, tx + 5, T + 18 + k * 12)); }
  }
}

// ------------------------------------------------------------------ CR tracker
const CRF = ["cr_id", "title", "description", "status", "owner", "risk", "rollback_plan", "notes", "tz", "planned_start", "planned_end", "actual_start", "actual_end"];
async function tCR(m) {
  const d = await api("/api/crs"); S.crs = d.crs; const inputs = {};
  const form = h("div", { class: "card" }, h("b", {}, "Add / edit CR"), h("div", { class: "muted" }, "Window times are stored as RAW text + parsed epoch (same rules as traffic data). Use the same format/timezone as your traffic data, e.g. 2026-01-27 05:00:00. Unparseable times are rejected, not guessed."),
    h("div", { class: "row" }, ...CRF.slice(0, 9).map(f => { const el = f === "status" ? h("select", {}, d.statuses.map(s => h("option", {}, s))) : f === "description" || f === "rollback_plan" || f === "notes" ? h("textarea", { rows: 2, placeholder: f }) : h("input", { placeholder: f, value: f === "tz" ? "UTC" : "" }); inputs[f] = el; return h("label", {}, f, el); })),
    h("div", { class: "row" }, ...CRF.slice(9).map(f => { const el = h("input", { placeholder: "YYYY-MM-DD HH:MM:SS", size: 22 }); inputs[f] = el; return h("label", {}, f, el); })),
    h("div", { class: "row" }, h("label", {}, "affected devices/interfaces (one per line: device or device,interface)", inputs.scope = h("textarea", { rows: 3 }))));
  const save = h("button", { class: "pri", onclick: async () => { try { const b = {}; for (const f of CRF) b[f] = inputs[f].value; b.scope = inputs.scope.value.split("\n").map(s => s.trim()).filter(Boolean).map(s => { const [device, iface] = s.split(",").map(x => x.trim()); return { device, interface: iface || "" }; }); await api("/api/crs", b); setStatus("saved; re-run Analyze to refresh CR matching"); render(); } catch (e) { alert(e.message); } } }, "Save CR");
  const imp = h("input", { type: "file", accept: ".json" }); imp.onchange = async () => { const t = JSON.parse(await imp.files[0].text()); const r = await api("/api/crs/import", t); setStatus("imported " + r.imported); render(); };
  const logBox = h("div");
  const edit = c => { for (const f of CRF) inputs[f].value = c[f.includes("_start") || f.includes("_end") ? f + "_raw" : f] ?? ""; inputs.scope.value = c.scope.map(s => s.device + (s.interface ? "," + s.interface : "")).join("\n"); window.scrollTo(0, 0); };
  const showLog = async c => {
    const l = (await api("/api/crs/log?cr_id=" + encodeURIComponent(c.cr_id))).log;
    logBox.replaceChildren(h("h4", {}, "Change log " + c.cr_id),
      h("table", {}, h("tr", {}, ["utc", "actor", "field", "old", "new"].map(x => h("th", {}, x))),
        l.map(r => h("tr", {}, h("td", { class: "mono" }, r.ts_utc), h("td", {}, r.actor), h("td", {}, r.field), h("td", {}, r.old ?? ""), h("td", {}, r.new ?? "")))));
  };
  const crRow = c => h("tr", {},
    h("td", { class: "mono" }, c.cr_id), h("td", {}, c.title), h("td", {}, c.status), h("td", {}, c.owner), h("td", {}, c.risk),
    h("td", { class: "mono" }, (c.planned_start_raw || "") + " → " + (c.planned_end_raw || "")),
    h("td", { class: "mono" }, (c.actual_start_raw || "") + " → " + (c.actual_end_raw || "")),
    h("td", {}, c.scope.map(s => s.device + (s.interface ? ":" + s.interface : "")).join(", ")),
    h("td", { class: "mono" }, c.linked_findings.join(", ")),
    h("td", {}, h("button", { onclick: () => edit(c) }, "edit"), h("button", { onclick: () => showLog(c) }, "log")));
  const head = h("thead", {}, h("tr", {}, ["CR", "title", "status", "owner", "risk", "planned (raw)", "actual (raw)", "scope", "linked findings", ""].map(x => h("th", {}, x))));
  m.append(form,
    h("div", { class: "row" }, save, h("a", { href: "/api/crs/export", download: "crs.json" }, h("button", {}, "Export JSON")), h("label", {}, "Import JSON", imp)),
    h("div", { class: "scroll" }, h("table", {}, head, h("tbody", {}, d.crs.map(crRow)))), logBox);
}

// ------------------------------------------------------------------ Explain
async function tExplain(m) {
  const box = h("div"), id = h("input", { size: 18, placeholder: "F-... or C-...", value: S.sel || "" });
  const go = async () => {
    try {
      const r = await api("/api/explain?id=" + encodeURIComponent(id.value.trim())), e = r.explanation;
      box.replaceChildren(h("div", { class: "banner" }, "Deterministic rule-based explanation. No AI model is loaded (SLM = optional Phase 3, not built). Every claim cites evidence ids. Verify against evidence."),
        h("div", { class: "card" }, h("b", {}, "Summary"), h("div", {}, e.summary), h("b", {}, "Ranked possible causes (candidates)"), h("ol", {}, (e.ranked_causes.length ? e.ranked_causes : [{ cause: "Unknown - insufficient evidence", evidence: [] }]).map(c => h("li", {}, c.cause, " ", h("span", { class: "mono muted" }, "[" + c.evidence.join(", ") + "]")))),
          h("b", {}, "Unknowns"), h("ul", {}, e.unknowns.map(u => h("li", {}, u))), h("b", {}, "Suggested checks"), h("ul", {}, e.suggested_checks.map(u => h("li", {}, u)))),
        h("details", {}, h("summary", {}, "evidence pack (exactly what an optional SLM would be allowed to see)"), h("pre", { class: "mono" }, JSON.stringify(r.evidence_pack, null, 1))));
    } catch (er) { box.replaceChildren(h("div", { class: "banner err" }, er.message)); }
  };
  m.append(h("div", { class: "row" }, "finding / cluster id", id, h("button", { class: "pri", onclick: go }, "Explain")), box); if (id.value) go();
}

// ------------------------------------------------------------------ Export
async function tExport(m) {
  m.append(h("div", { class: "card" }, h("div", { class: "row" },
    h("a", { href: "/api/export/findings", download: "findings.json" }, h("button", {}, "Findings JSON")),
    h("a", { href: "/api/export/report", download: "report.html" }, h("button", {}, "Standalone HTML report")),
    h("a", { href: "/api/crs/export", download: "crs.json" }, h("button", {}, "CR tracker JSON"))),
    h("div", { class: "muted" }, "Exports keep ts_raw exactly as imported next to ts_parsed. The HTML report has no external resources.")));
}
render();
