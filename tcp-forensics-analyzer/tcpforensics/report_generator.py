"""Self-contained interactive HTML report.

The report consumes the analysis model produced by :mod:`analyzer` — it
performs *no* TCP interpretation of its own.  All CSS/JS is embedded, no
external resources are referenced, and the file opens from disk (file://)
with no server.  CSV exports are generated client-side via Blob URLs.

Visual notes: the chart series palette (dup-ACK magenta, RTT blue, loss
orange, DATA->ACK aqua, zero-window violet, retransmission red) was
validated for CVD separation, lightness band and surface contrast against
the dark chart surface; all motion honours ``prefers-reduced-motion``.
"""

from __future__ import annotations

import json


def generate_report(model: dict, out_path: str) -> None:
    payload = json.dumps(model, separators=(",", ":"), allow_nan=False)
    payload = payload.replace("</", "<\\/")
    html = _TEMPLATE.replace("%%DATA%%", payload)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TCP Forensics Report</title>
<style>
:root{
  --bg:#0a0e1a;--surface:#10141f;
  --panel:rgba(22,28,42,.66);--panel2:rgba(30,37,54,.62);--solid:#161c2a;
  --border:rgba(120,140,190,.16);--border2:rgba(120,140,190,.28);
  --fg:#d4dae6;--bright:#eef2f8;--dim:#8b95a8;
  --accent:#3987e5;--accent2:#9085e9;
  --ok:#2fb35c;--warn:#d29922;--bad:#e66767;
  --c-rtt:#3987e5;--c-ack:#199e70;--c-retx:#e66767;
  --c-loss:#d95926;--c-dup:#d55181;--c-zw:#9085e9;
  --mono:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;
  --ui:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  --glow:0 0 24px rgba(57,135,229,.25);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
/* Type system: UI sans carries structure (headings, labels, controls);
   mono is reserved for data — numbers, timestamps, addresses, tables.
   System stacks are a deliberate constraint: the report must stay a
   zero-request single file, so no webfonts. */
body{margin:0;background:var(--bg);color:var(--fg);
  font:13.5px/1.55 var(--ui);font-variant-numeric:tabular-nums;
  overflow-x:hidden}
table,.kv,.mono,td,.tile .v,.legend,.chip{font-family:var(--mono);font-size:12px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
/* ---- ambient background: aurora orbs + engineering grid ---- */
body::before{content:'';position:fixed;inset:0;z-index:-3;background:
  radial-gradient(60% 50% at 12% -5%, rgba(57,135,229,.17), transparent 62%),
  radial-gradient(50% 42% at 88% 8%, rgba(144,133,233,.14), transparent 60%),
  radial-gradient(45% 45% at 50% 105%, rgba(25,158,112,.08), transparent 60%)}
body::after{content:'';position:fixed;inset:0;z-index:-2;pointer-events:none;
  background:
   linear-gradient(rgba(140,160,210,.035) 1px, transparent 1px),
   linear-gradient(90deg, rgba(140,160,210,.035) 1px, transparent 1px);
  background-size:44px 44px;
  mask-image:radial-gradient(75% 60% at 50% 30%, #000 30%, transparent 100%)}
.orb{position:fixed;border-radius:50%;filter:blur(90px);z-index:-1;
  pointer-events:none;opacity:.5;will-change:transform}
.orb.a{width:520px;height:520px;left:-160px;top:-140px;
  background:radial-gradient(circle,rgba(57,135,229,.32),transparent 70%);
  animation:orbA 26s ease-in-out infinite alternate}
.orb.b{width:460px;height:460px;right:-140px;top:120px;
  background:radial-gradient(circle,rgba(144,133,233,.26),transparent 70%);
  animation:orbB 32s ease-in-out infinite alternate}
@keyframes orbA{from{transform:translate(0,0) scale(1)}to{transform:translate(140px,90px) scale(1.15)}}
@keyframes orbB{from{transform:translate(0,0) scale(1.1)}to{transform:translate(-120px,160px) scale(.95)}}

h1,h2,h3{font-weight:650;margin:.4em 0;font-family:var(--ui);letter-spacing:.01em}
h1{font-size:21px;background:linear-gradient(92deg,#eaf1fb 10%,#7fb3f5 45%,#b3a8f5 75%,#eaf1fb 95%);
  background-size:220% 100%;-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;animation:sheen 9s linear infinite}
@keyframes sheen{from{background-position:0% 0}to{background-position:220% 0}}
h2{font-size:16px;color:var(--bright)}
h2::before{content:'';display:inline-block;width:9px;height:9px;margin-right:9px;
  border-radius:3px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  box-shadow:var(--glow)}
h3{font-size:12.5px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
a{color:var(--accent);cursor:pointer;text-decoration:none;transition:color .15s}
a:hover{color:#7fb3f5}
.wrap{max-width:1520px;margin:0 auto;padding:64px 16px 16px}

/* ---- sticky section nav ---- */
.nav{position:fixed;top:0;left:0;right:0;z-index:50;display:flex;align-items:center;
  gap:4px;padding:8px 20px;background:rgba(10,14,26,.78);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border);font-family:var(--ui);
  animation:navIn .5s cubic-bezier(.22,1,.36,1)}
@keyframes navIn{from{transform:translateY(-100%)}to{transform:none}}
.nav .brand{font-weight:700;font-size:13px;letter-spacing:.02em;color:var(--bright);
  margin-right:14px;white-space:nowrap}
.nav .brand::before{content:'';display:inline-block;width:10px;height:10px;
  border-radius:3px;margin-right:8px;vertical-align:-1px;
  background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:var(--glow)}
.nav a{color:var(--dim);font-size:12.5px;padding:5px 11px;border-radius:7px;
  transition:color .15s,background .15s}
.nav a:hover{color:var(--bright);background:rgba(57,135,229,.10)}
.nav .spacer{flex:1}
.seg{display:inline-flex;background:rgba(30,37,54,.85);border:1px solid var(--border);
  border-radius:8px;padding:2px;gap:2px}
.seg button{border:none;background:transparent;box-shadow:none;padding:3px 12px;
  border-radius:6px;color:var(--dim);font-family:var(--mono)}
.seg button:hover{color:var(--bright);box-shadow:none}
.seg button.on{background:linear-gradient(135deg,var(--accent),var(--accent2));
  color:#fff;box-shadow:0 1px 8px rgba(57,135,229,.4)}

/* ---- glass panels with staggered entrance ---- */
.panel{background:var(--panel);border:1px solid var(--border);border-radius:14px;
  padding:16px 18px;margin-bottom:16px;position:relative;
  backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  box-shadow:0 8px 32px rgba(0,0,0,.35);
  animation:riseIn .6s cubic-bezier(.22,1,.36,1) both;
  animation-delay:calc(var(--i,0)*90ms)}
.panel::before{content:'';position:absolute;inset:0;border-radius:14px;padding:1px;
  background:linear-gradient(135deg,rgba(57,135,229,.35),transparent 30%,transparent 70%,rgba(144,133,233,.25));
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
@keyframes riseIn{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}

/* ---- stat tiles ---- */
.tiles{display:flex;flex-wrap:wrap;gap:10px}
.tile{background:var(--panel2);border:1px solid var(--border);border-radius:11px;
  padding:11px 15px;min-width:132px;position:relative;overflow:hidden;
  transition:transform .22s cubic-bezier(.22,1,.36,1),box-shadow .22s,border-color .22s;
  animation:riseIn .55s cubic-bezier(.22,1,.36,1) both;
  animation-delay:calc(120ms + var(--i,0)*45ms)}
.tile:hover{transform:translateY(-4px) scale(1.02);border-color:var(--border2);
  box-shadow:0 12px 28px rgba(0,0,0,.45),var(--glow)}
.tile::after{content:'';position:absolute;left:0;top:0;right:0;height:2px;
  background:linear-gradient(90deg,var(--accent),var(--accent2));opacity:.5}
.tile.ok::after{background:var(--ok)}
.tile.warn::after{background:var(--warn)}
.tile.bad::after{background:var(--bad)}
.tile .v{font-size:18px;font-weight:700;color:var(--bright);letter-spacing:.01em}
.tile .l{font-size:10.5px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-top:2px}
.tile.bad .v{color:var(--bad)}.tile.warn .v{color:var(--warn)}.tile.ok .v{color:var(--ok)}
.tile.bad .l::after{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;
  background:var(--bad);margin-left:6px;vertical-align:1px;animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.35;transform:scale(.8)}50%{opacity:1;transform:scale(1.15)}}

/* ---- tables ---- */
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border-bottom:1px solid rgba(120,140,190,.10);padding:5px 9px;text-align:left;white-space:nowrap}
th{color:var(--dim);cursor:pointer;user-select:none;position:sticky;top:0;z-index:2;
  background:rgba(16,20,31,.92);backdrop-filter:blur(6px);
  text-transform:uppercase;font-size:10.5px;letter-spacing:.05em;
  transition:color .15s}
th:hover{color:var(--accent)}
tr{transition:background .15s}
tbody tr,table tr{animation:rowIn .4s ease both;animation-delay:calc(var(--i,0)*22ms)}
@keyframes rowIn{from{opacity:0;transform:translateX(-8px)}to{opacity:1;transform:none}}
tr.clickable{cursor:pointer}
tr.clickable:hover{background:linear-gradient(90deg,rgba(57,135,229,.14),rgba(57,135,229,.04));
  box-shadow:inset 3px 0 0 var(--accent)}
.num{text-align:right}
.scroll{overflow:auto;max-height:480px;border:1px solid var(--border);border-radius:9px;
  background:rgba(10,14,26,.35)}
.scroll::-webkit-scrollbar{width:9px;height:9px}
.scroll::-webkit-scrollbar-thumb{background:rgba(120,140,190,.25);border-radius:5px}
.scroll::-webkit-scrollbar-thumb:hover{background:rgba(120,140,190,.45)}
.scroll::-webkit-scrollbar-track{background:transparent}

.badge{display:inline-block;border-radius:20px;padding:1px 9px;font-size:10.5px;margin:1px 2px;
  border:1px solid;letter-spacing:.02em;font-family:var(--ui)}
.hdot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;
  vertical-align:1px}
.hdot.ok{background:var(--ok);box-shadow:0 0 6px rgba(47,179,92,.5)}
.hdot.warn{background:var(--warn);box-shadow:0 0 6px rgba(210,153,34,.5)}
.hdot.bad{background:var(--bad);box-shadow:0 0 6px rgba(230,103,103,.55)}
.pill{display:inline-block;padding:1px 9px;border-radius:20px;font-size:10.5px;
  font-family:var(--ui);letter-spacing:.03em;border:1px solid var(--border2);color:var(--dim)}
.pill.closed{color:var(--ok);border-color:rgba(47,179,92,.4)}
.pill.established{color:var(--accent);border-color:rgba(57,135,229,.4)}
.pill.reset{color:var(--bad);border-color:rgba(230,103,103,.45)}
.pill.half-closed{color:var(--warn);border-color:rgba(210,153,34,.4)}
.pill.partial{color:var(--warn);border-color:rgba(210,153,34,.4)}
.empty{padding:34px 10px;text-align:center;color:var(--dim);font-family:var(--ui);
  font-size:13px}
.empty::before{content:'∅';display:block;font-size:22px;opacity:.4;margin-bottom:6px}
.b-ok{color:var(--ok);border-color:var(--ok);background:rgba(47,179,92,.09)}
.b-warn{color:var(--warn);border-color:var(--warn);background:rgba(210,153,34,.09)}
.b-bad{color:var(--bad);border-color:var(--bad);background:rgba(230,103,103,.09)}
.b-info{color:var(--accent);border-color:var(--accent);background:rgba(57,135,229,.09)}

/* ---- controls ---- */
.controls{display:flex;flex-wrap:wrap;gap:9px;margin-bottom:12px;align-items:center}
.controls input,.controls select,button{background:rgba(30,37,54,.8);color:var(--fg);
  border:1px solid var(--border);border-radius:7px;padding:5px 10px;font:12px var(--mono);
  transition:border-color .18s,box-shadow .18s,transform .12s}
.controls input:focus,.controls select:focus{outline:none;border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(57,135,229,.18)}
.controls label{color:var(--dim);font-size:11px}
button{cursor:pointer}
button:hover{border-color:var(--accent);box-shadow:0 0 12px rgba(57,135,229,.25)}
button:active{transform:scale(.96)}
button.primary{border-color:transparent;color:#fff;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  box-shadow:0 2px 12px rgba(57,135,229,.35)}
input[type=range]{accent-color:var(--accent)}

/* ---- tabs ---- */
.tabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--border);
  margin-bottom:12px;padding-bottom:0}
.tabs div{padding:7px 15px;cursor:pointer;color:var(--dim);border-radius:8px 8px 0 0;
  position:relative;transition:color .18s,background .18s;font-family:var(--ui);font-size:12.5px}
.tabs div:hover{color:var(--bright);background:rgba(57,135,229,.07)}
.tabs div.active{color:var(--bright);background:var(--panel2)}
.tabs div.active::after{content:'';position:absolute;left:8px;right:8px;bottom:0;height:2px;
  border-radius:2px;background:linear-gradient(90deg,var(--accent),var(--accent2));
  animation:tabGlow .35s ease}
@keyframes tabGlow{from{transform:scaleX(.3);opacity:0}to{transform:none;opacity:1}}
.tabIn{animation:tabBody .3s cubic-bezier(.22,1,.36,1)}
@keyframes tabBody{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

.kv{display:grid;grid-template-columns:max-content 1fr;gap:3px 18px;font-size:12px}
.kv .k{color:var(--dim)}
canvas{background:var(--surface);border:1px solid var(--border);border-radius:9px;max-width:100%}
.state-Original{color:var(--fg)}.state-ACKed{color:var(--ok)}.state-SACKed{color:var(--c-zw)}
.state-Retransmitted{color:var(--c-retx)}.state-Duplicate{color:var(--c-loss)}
.state-Out-of-order{color:var(--warn)}.state-Recovered{color:var(--ok)}
.state-Ambiguous,.state-Missing{color:var(--warn)}
.state-Keep-alive,.state-Window-probe,.state-Capture-dup{color:var(--dim)}
.panel{scroll-margin-top:56px}
.tooltip{position:fixed;background:rgba(10,14,26,.92);border:1px solid var(--border2);
  border-radius:8px;padding:7px 10px;font-size:11px;pointer-events:none;z-index:99;
  white-space:pre;display:none;backdrop-filter:blur(8px);
  box-shadow:0 8px 24px rgba(0,0,0,.5);animation:ttIn .15s ease}
@keyframes ttIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.warnbox{border-left:3px solid var(--warn);padding:7px 12px;margin:7px 0;
  background:rgba(210,153,34,.06);font-size:12px;border-radius:0 8px 8px 0}
.verdict{border-left:3px solid var(--border2);padding:8px 12px;margin:7px 0;
  background:var(--panel2);border-radius:0 9px 9px 0;
  animation:rowIn .45s ease both;animation-delay:calc(var(--i,0)*70ms);
  transition:transform .18s,box-shadow .18s}
.verdict:hover{transform:translateX(4px);box-shadow:0 4px 16px rgba(0,0,0,.3)}
.verdict.ok{border-color:var(--ok)}.verdict.warn{border-color:var(--warn)}
.verdict.bad{border-color:var(--bad)}.verdict.info{border-color:var(--accent)}
.verdict{display:grid;grid-template-columns:24px 1fr;gap:2px 10px;font-family:var(--ui)}
.verdict .glyph{grid-row:span 2;width:22px;height:22px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;font-size:12px;
  font-weight:700;margin-top:1px}
.verdict.ok .glyph{color:var(--ok);background:rgba(47,179,92,.13)}
.verdict.warn .glyph{color:var(--warn);background:rgba(210,153,34,.13)}
.verdict.bad .glyph{color:var(--bad);background:rgba(230,103,103,.13)}
.verdict.info .glyph{color:var(--accent);background:rgba(57,135,229,.13)}
.verdict .ev{color:var(--dim);font-size:12.5px;white-space:normal}
.mut{color:var(--dim)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:1000px){.grid2{grid-template-columns:1fr}}
#detail{display:none}
#detail.pop{animation:detailIn .45s cubic-bezier(.22,1,.36,1)}
@keyframes detailIn{from{opacity:0;transform:translateY(26px) scale(.985)}to{opacity:1;transform:none}}
.legend{margin:6px 0}
.legend span{margin-right:15px;font-size:11px;color:var(--dim)}
.dot{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px;vertical-align:middle}
.chip{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;
  background:rgba(57,135,229,.12);border:1px solid rgba(57,135,229,.3);color:#8fbcf2}

@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation:none !important;transition:none !important}
  html{scroll-behavior:auto}
}
</style>
</head>
<body>
<div class="orb a"></div><div class="orb b"></div>
<div class="tooltip" id="tt"></div>
<nav class="nav" aria-label="report sections">
  <span class="brand">TCP Forensics</span>
  <a href="#hdr">Capture</a>
  <a href="#latPanel">Latency</a>
  <a href="#sessPanel">Sessions</a>
  <a href="#lossPanel">Loss</a>
  <a href="#detail" id="navSess" style="display:none"></a>
  <span class="spacer"></span>
  <span class="seg" role="group" aria-label="sequence display" id="seqSeg" title="relative or raw 32-bit SEQ/ACK numbers"></span>
  <span class="seg" role="group" aria-label="display unit" id="unitSeg"></span>
</nav>
<div class="wrap">
  <div class="panel" style="--i:0" id="hdr"></div>
  <div class="panel" style="--i:1"><div class="tiles" id="tiles"></div></div>
  <div class="panel" style="--i:2" id="latPanel">
    <h2>Capture Latency &amp; Recovery Distribution</h2>
    <div class="grid2">
      <div><h3>Valid RTT (Karn-filtered)</h3><div id="gRttStats"></div>
        <canvas id="gRttHist" width="640" height="180"></canvas>
        <canvas id="gRttCdf" width="640" height="150"></canvas></div>
      <div><h3>Loss recovery (original TX &rarr; recovery ACK)</h3><div id="gRecStats"></div>
        <canvas id="gRecHist" width="640" height="180"></canvas>
        <canvas id="gRecCdf" width="640" height="150"></canvas></div>
    </div>
  </div>
  <div class="panel" style="--i:3" id="sessPanel">
    <h2>Session Explorer</h2>
    <div class="controls" id="sessFilters"></div>
    <div class="scroll" style="max-height:420px"><table id="sessTable"></table></div>
  </div>
  <div class="panel" style="--i:4" id="lossPanel">
    <h2>Loss &amp; Recovery Dashboard</h2>
    <div class="controls">
      <button onclick="exportLossCsv()">Export loss CSV</button>
      <button onclick="exportRetransCsv()">Export retransmissions CSV</button>
      <button onclick="exportRttCsv()">Export RTT samples CSV</button>
      <button onclick="exportSackCsv()">Export SACK events CSV</button>
      <button onclick="exportSessionsCsv()">Export sessions CSV</button>
    </div>
    <div class="scroll" style="max-height:380px"><table id="lossTable"></table></div>
  </div>
  <div class="panel" id="detail"></div>
</div>
<script id="data" type="application/json">%%DATA%%</script>
<script>
"use strict";
const M = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
if(!CanvasRenderingContext2D.prototype.roundRect){ // older-browser fallback
  CanvasRenderingContext2D.prototype.roundRect=function(x,y,w,h){this.rect(x,y,w,h);};
}
const MOTION = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const EASE = t => t < .5 ? 2*t*t : 1 - Math.pow(-2*t + 2, 2) / 2;
// series palette — validated for CVD separation & contrast on the dark surface
const C = {rtt:'#3987e5', ack:'#199e70', retx:'#e66767',
           loss:'#d95926', dup:'#d55181', zw:'#9085e9',
           acked:'#199e70', sacked:'#9085e9', hole:'#e66767', out:'#2a3040'};
let UNIT = 'ns';           // ns | us | ms
let SEQMODE = 'rel';       // rel | raw — display only; engine stays 64-bit
let curSess = null, curTab = 'overview';
let TILES_ANIMATED = false;

/* ------------------------------------------------------ animation utils */
function animCanvas(canvas, dur, draw){
  if(canvas._tok) cancelAnimationFrame(canvas._tok);
  if(!MOTION){ draw(1); return; }
  const t0 = performance.now();
  const step = now => {
    const p = Math.min(1, (now - t0) / dur);
    draw(EASE(p));
    if(p < 1) canvas._tok = requestAnimationFrame(step);
  };
  canvas._tok = requestAnimationFrame(step);
}
function countUp(el, target, fmt, dur){
  if(!MOTION || TILES_ANIMATED || typeof target !== 'number' || !isFinite(target)){
    el.textContent = fmt(target); return;
  }
  const t0 = performance.now();
  const step = now => {
    const p = Math.min(1, (now - t0) / dur);
    const v = Math.round(target * EASE(p));
    el.textContent = fmt(Number.isInteger(target) ? v : target * EASE(p));
    if(p < 1) requestAnimationFrame(step);
    else el.textContent = fmt(target);
  };
  requestAnimationFrame(step);
}

/* ---------------------------------------------------------- formatting */
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function fmtInt(n){return n==null?'-':Number(n).toLocaleString('en-US');}
function fmtNs(ns){ // duration in the selected unit; underlying value stays integer ns
  if(ns==null)return '-';
  if(UNIT==='ns')return fmtInt(Math.round(ns))+' ns';
  if(UNIT==='us')return (ns/1000).toLocaleString('en-US',{maximumFractionDigits:3})+' µs';
  return (ns/1e6).toLocaleString('en-US',{maximumFractionDigits:6})+' ms';
}
function fmtTs(ns){ // capture-start-relative, full ns precision
  if(ns==null)return '-';
  const rel = ns - (M.capture.first_ts||0);
  const s = Math.floor(rel/1e9), f = String(rel-s*1e9).padStart(9,'0');
  return 't+'+s+'.'+f+'s';
}
function fmtBytes(b){
  if(b==null)return '-';
  if(b>=1e9)return (b/1e9).toFixed(2)+' GB';
  if(b>=1e6)return (b/1e6).toFixed(2)+' MB';
  if(b>=1e3)return (b/1e3).toFixed(1)+' kB';
  return Math.round(b)+' B';
}
function pct(x){return x==null?'-':x.toFixed(2)+'%';}
function seqBase(s,dir){return (dir==='A->B'?s.dir_a:s.dir_b).seq_base_raw||0;}
function fmtSeq(s,dir,v){ // relative <-> raw 32-bit sequence display
  if(v==null)return '-';
  if(SEQMODE==='rel')return fmtInt(v);
  return fmtInt((seqBase(s,dir)+v)%4294967296);
}
function oppDir(d){return d==='A->B'?'B->A':'A->B';}
function tri(v){return v==null?'unknown':(v?'yes':'no');}

/* ------------------------------------------------------------- header */
function renderHeader(){
  const c = M.capture;
  const precNote = c.nanosecond_native
    ? 'Capture timestamp resolution: '+c.resolution_label+' &mdash; effective precision: nanosecond'
    : 'Capture timestamp resolution: '+c.resolution_label+' &mdash; display unit: ns &mdash; effective precision: '
      +fmtInt(c.effective_precision_ns)+' ns (nanosecond digits below this are not meaningful)';
  $('#hdr').innerHTML =
   '<h1>TCP Session, Sequence, SACK &amp; Nanosecond Latency Forensics</h1>'+
   '<div class="kv">'+
   '<div class="k">Capture file</div><div>'+esc(c.path)+' <span class="chip">'+esc(c.format)+'</span></div>'+
   (c.files&&c.files.length>1?'<div class="k">Merged files</div><div>'+
     c.files.map((f,i)=>'<span class="chip" title="'+esc(f.format)+'">#'+i+' '+esc(f.name)+' ('+fmtInt(f.tcp_packets)+' TCP)</span>').join(' ')+'</div>':'')+
   '<div class="k">Capture point</div><div>'+esc(c.capture_point)+' <span class="mut">capture_id='+c.capture_id+'</span></div>'+
   '<div class="k">Timestamp precision</div><div>'+precNote+'</div>'+
   '<div class="k">First packet</div><div>'+esc(c.first_ts_str)+' UTC</div>'+
   '<div class="k">Last packet</div><div>'+esc(c.last_ts_str)+' UTC</div>'+
   '<div class="k">Duration</div><div>'+esc(c.duration_str)+'</div>'+
   '<div class="k">Packets</div><div>'+fmtInt(c.packets)+' total, '+fmtInt(c.tcp_packets)+' TCP'+
     (c.truncated_frames?' <span class="b-warn badge">'+fmtInt(c.truncated_frames)+' truncated by snaplen</span>':'')+'</div>'+
   '</div>'+
   (c.warnings&&c.warnings.length?c.warnings.map(w=>'<div class="warnbox">⚠ '+esc(w)+'</div>').join(''):'')+
   '<div class="mut" style="margin-top:8px;font-family:var(--ui)">'+esc(M.tool.name)+' v'+esc(M.tool.version)+
   ' &mdash; display unit is presentation only; internal values remain integer nanoseconds</div>';
}
function renderNav(){
  $('#seqSeg').innerHTML=['rel','raw'].map(m=>
    '<button class="'+(SEQMODE===m?'on':'')+'" onclick="setSeqMode(\''+m+'\')" '+
    'aria-pressed="'+(SEQMODE===m)+'">SEQ '+m+'</button>').join('');
  $('#unitSeg').innerHTML=['ns','us','ms'].map(u=>
    '<button class="'+(UNIT===u?'on':'')+'" onclick="setUnit(\''+u+'\')" '+
    'aria-pressed="'+(UNIT===u)+'">'+(u==='us'?'µs':u)+'</button>').join('');
  const nl=$('#navSess');
  if(curSess){nl.style.display='';nl.textContent=curSess.label;}
  else nl.style.display='none';
}
function setUnit(u){UNIT=u;renderAll();}
function setSeqMode(m){SEQMODE=m;renderAll();}

/* -------------------------------------------------------------- tiles */
function renderTiles(){
  const t=M.totals,r=M.rtt_summary,rec=M.recovery_summary;
  const defs=[
    ['Sessions',t.sessions,fmtInt,''],
    ['TCP packets',t.tcp_packets,fmtInt,''],
    ['TCP payload',t.payload_bytes,fmtBytes,''],
    ['Retransmissions',t.retrans_segments,fmtInt,t.retrans_segments?'warn':'ok'],
    ['Retrans %',t.retrans_pct,pct,t.retrans_pct>2?'bad':t.retrans_pct>0.5?'warn':'ok'],
    ['SACK events',t.sack_events,fmtInt,''],
    ['DSACK',t.dsack_events,fmtInt,''],
    ['Loss events',t.loss_events,fmtInt,t.loss_events?'warn':'ok'],
    ['Dup ACKs',t.dup_acks,fmtInt,''],
    ['Out-of-order',t.ooo_packets,fmtInt,''],
    ['Zero-window',t.zero_window_events,fmtInt,t.zero_window_events?'bad':'ok'],
    ['Multi-point dups',t.network_dups,fmtInt,''],
    ['Median RTT',r.median,fmtNs,''],
    ['P95 RTT',r.p95,fmtNs,''],
    ['P99 RTT',r.p99,fmtNs,''],
    ['Max RTT',r.max,fmtNs,''],
    ['Median recovery',rec.median,fmtNs,''],
    ['P95 recovery',rec.p95,fmtNs,''],
    ['Max recovery',rec.max,fmtNs,'']];
  $('#tiles').innerHTML = defs.map((d,i)=>
    '<div class="tile '+d[3]+'" style="--i:'+i+'"><div class="v" id="tv'+i+'"></div>'+
    '<div class="l">'+d[0]+'</div></div>').join('');
  defs.forEach((d,i)=>countUp($('#tv'+i), d[1], d[2], 700+i*40));
  TILES_ANIMATED = true;
}

/* ------------------------------------------------------------- charts */
function drawHist(canvas,h,color){
  if(!canvas)return;   // tab switched away before a deferred draw ran
  const ctx=canvas.getContext('2d');
  if(!h||!h.counts||!h.counts.length){
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.fillStyle='#8b95a8';ctx.fillText('no samples',10,20);return;
  }
  const W=canvas.width,H=canvas.height,pad=34,max=Math.max(...h.counts);
  const bw=(W-pad-8)/h.counts.length, n=h.counts.length;
  const total=h.counts.reduce((a,b)=>a+b,0);
  canvas._hist={h,pad,bw,total};          // geometry for the hover layer
  if(!canvas._histHover){canvas._histHover=true;
    canvas.addEventListener('mousemove',histHover);
    canvas.addEventListener('mouseleave',()=>{$('#tt').style.display='none';});}
  animCanvas(canvas, 650, p=>{
    ctx.clearRect(0,0,W,H);
    ctx.strokeStyle='rgba(120,140,190,.14)';ctx.lineWidth=1;
    [0.5,1].forEach(f=>{const y=H-18-(H-30)*f;
      ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(W-8,y);ctx.stroke();});
    h.counts.forEach((c,i)=>{
      const pi=Math.max(0,Math.min(1,(p - (i/n)*0.35)/0.65));
      const bh=max?(H-30)*c/max*pi:0;
      const g=ctx.createLinearGradient(0,H-18-bh,0,H-18);
      g.addColorStop(0,color);g.addColorStop(1,color+'55');
      ctx.fillStyle=g;
      const x=pad+i*bw, w=Math.max(1,bw-2);
      ctx.beginPath();
      ctx.roundRect(x,H-18-bh,w,Math.max(0,bh),[3,3,0,0]);
      ctx.fill();
    });
    ctx.fillStyle='#8b95a8';ctx.font='10px monospace';
    ctx.fillText(fmtNs(h.buckets[0]),pad,H-5);
    const last=fmtNs(h.buckets[h.buckets.length-1]);
    ctx.fillText(last,W-8-ctx.measureText(last).width,H-5);
    ctx.save();ctx.translate(10,H/2);ctx.rotate(-Math.PI/2);ctx.fillText('count',0,0);ctx.restore();
    ctx.fillText('max '+max,pad,12);
  });
}
function drawCdf(canvas,h,color){
  if(!canvas)return;
  const ctx=canvas.getContext('2d');
  if(!h||!h.cdf||!h.cdf.length){
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.fillStyle='#8b95a8';ctx.fillText('no samples',10,20);return;
  }
  const W=canvas.width,H=canvas.height,pad=34;
  const xs=h.cdf.map(q=>q[0]);const lo=xs[0],hi=xs[xs.length-1]||1;
  const X=v=>pad+(hi>lo?(v-lo)/(hi-lo):0)*(W-pad-8);
  const Y=q=>H-16-(q/100)*(H-28);
  canvas._cdf={cdf:h.cdf,lo,hi,pad};      // for the hover readout
  if(!canvas._cdfHover){canvas._cdfHover=true;
    canvas.addEventListener('mousemove',cdfHover);
    canvas.addEventListener('mouseleave',()=>{$('#tt').style.display='none';});}
  animCanvas(canvas, 750, p=>{
    ctx.clearRect(0,0,W,H);
    ctx.strokeStyle='rgba(120,140,190,.18)';ctx.lineWidth=1;
    [50,90,95,99].forEach(q=>{ctx.beginPath();ctx.moveTo(pad,Y(q));ctx.lineTo(W-8,Y(q));ctx.stroke();});
    const upto=Math.max(2,Math.ceil(h.cdf.length*p));
    ctx.strokeStyle=color;ctx.lineWidth=2;ctx.lineJoin='round';
    ctx.shadowColor=color;ctx.shadowBlur=6;
    ctx.beginPath();
    h.cdf.slice(0,upto).forEach((q,i)=>{i?ctx.lineTo(X(q[0]),Y(q[1])):ctx.moveTo(X(q[0]),Y(q[1]));});
    ctx.stroke();ctx.shadowBlur=0;
    ctx.fillStyle='#8b95a8';ctx.font='10px monospace';
    [50,90,99].forEach(q=>ctx.fillText('P'+q,2,Y(q)+3));
    ctx.fillText('CDF',pad,10);ctx.fillText(fmtNs(lo),pad,H-4);
    const last=fmtNs(hi);ctx.fillText(last,W-8-ctx.measureText(last).width,H-4);
  });
}
function histHover(ev){
  const cv=ev.currentTarget,g=cv._hist,tt=$('#tt');
  if(!g){tt.style.display='none';return;}
  const r=cv.getBoundingClientRect();
  const x=(ev.clientX-r.left)*cv.width/r.width;
  const i=Math.floor((x-g.pad)/g.bw);
  if(i<0||i>=g.h.counts.length||!g.h.counts[i]){tt.style.display='none';return;}
  const lo=g.h.buckets[i], hi=g.h.buckets[i+1]??g.h.buckets[i];
  const c=g.h.counts[i], pctv=g.total?(100*c/g.total).toFixed(1):'0';
  tt.style.display='block';tt.style.left=(ev.clientX+12)+'px';tt.style.top=(ev.clientY+12)+'px';
  tt.textContent=fmtNs(lo)+' – '+fmtNs(hi)+'\n'+fmtInt(c)+' samples ('+pctv+'%)';
}
function cdfHover(ev){
  const cv=ev.currentTarget,g=cv._cdf,tt=$('#tt');
  if(!g){tt.style.display='none';return;}
  const r=cv.getBoundingClientRect();
  const x=(ev.clientX-r.left)*cv.width/r.width;
  const v=g.lo+Math.max(0,Math.min(1,(x-g.pad)/(cv.width-g.pad-8)))*(g.hi-g.lo);
  let best=g.cdf[0];
  for(const q of g.cdf){if(q[0]<=v)best=q;else break;}
  tt.style.display='block';tt.style.left=(ev.clientX+12)+'px';tt.style.top=(ev.clientY+12)+'px';
  tt.textContent='P'+best[1].toFixed(1)+' of samples ≤ '+fmtNs(best[0]);
}
function statLine(s){
  if(!s||!s.count)return '<span class="mut">no valid samples</span>';
  let t='n='+fmtInt(s.count)+' min='+fmtNs(s.min)+' med='+fmtNs(s.median)+' mean='+fmtNs(s.mean)+
    ' p90='+fmtNs(s.p90)+' p95='+fmtNs(s.p95)+' p99='+fmtNs(s.p99);
  if(s.p999!=null)t+=' p99.9='+fmtNs(s.p999);
  t+=' max='+fmtNs(s.max)+' σ='+fmtNs(s.stddev);
  return t;
}
function renderGlobalCharts(){
  $('#gRttStats').innerHTML=statLine(M.rtt_summary);
  $('#gRecStats').innerHTML=statLine(M.recovery_summary);
  drawHist($('#gRttHist'),M.rtt_hist,C.rtt);drawCdf($('#gRttCdf'),M.rtt_hist,C.rtt);
  drawHist($('#gRecHist'),M.recovery_hist,C.loss);drawCdf($('#gRecCdf'),M.recovery_hist,C.loss);
}

/* -------------------------------------------------- session explorer */
let sortKey='id',sortDir=1;
function renderSessFilters(){
  $('#sessFilters').innerHTML =
   '<label>search <input id="f_text" size="18" placeholder="IP / port / session id" oninput="applyF()"></label>'+
   '<label>min duration(ms) <input id="f_dur" size="5" oninput="applyF()"></label>'+
   '<label>min bytes <input id="f_bytes" size="7" oninput="applyF()"></label>'+
   '<label>min retrans <input id="f_ret" size="4" oninput="applyF()"></label>'+
   '<label>min retrans% <input id="f_retp" size="4" oninput="applyF()"></label>'+
   '<label>min RTT p50(µs) <input id="f_rtt" size="5" oninput="applyF()"></label>'+
   '<label>min RTT p99(µs) <input id="f_p99" size="5" oninput="applyF()"></label>'+
   '<label>SACK <select id="f_sack" onchange="applyF()"><option value="">any</option><option>yes</option><option>no</option></select></label>'+
   '<label><input type="checkbox" id="f_loss" onchange="applyF()">loss</label>'+
   '<label><input type="checkbox" id="f_zw" onchange="applyF()">zero-win</label>'+
   '<label><input type="checkbox" id="f_rst" onchange="applyF()">RST</label>'+
   '<label><input type="checkbox" id="f_inc" onchange="applyF()">incomplete</label>';
}
function applyF(){renderSessTable();}
function sessFiltered(){
  const txt=($('#f_text')?.value||'').toLowerCase();
  const dur=parseFloat($('#f_dur')?.value)||0, bytes=parseFloat($('#f_bytes')?.value)||0;
  const ret=parseFloat($('#f_ret')?.value)||0, retp=parseFloat($('#f_retp')?.value)||0;
  const rtt=(parseFloat($('#f_rtt')?.value)||0)*1000, p99=(parseFloat($('#f_p99')?.value)||0)*1000;
  const sack=$('#f_sack')?.value||'';
  return M.sessions.filter(s=>{
    if(txt && !(s.client.toLowerCase().includes(txt)||s.server.toLowerCase().includes(txt)
      ||String(s.id).includes(txt)||s.label.toLowerCase().includes(txt)
      ||String(s.client_port).includes(txt)||String(s.server_port).includes(txt)))return false;
    if(dur && s.duration_ns < dur*1e6)return false;
    if(bytes && s.stats.payload_bytes < bytes)return false;
    if(ret && s.stats.retrans_segments < ret)return false;
    if(retp && s.stats.retrans_pct < retp)return false;
    if(rtt && !(s.stats.rtt.median>=rtt))return false;
    if(p99 && !(s.stats.rtt.p99>=p99))return false;
    if(sack==='yes' && s.sack_active!==true)return false;
    if(sack==='no' && s.sack_active!==false)return false;
    if($('#f_loss')?.checked && !s.stats.loss_events)return false;
    if($('#f_zw')?.checked && !s.stats.zero_window_events)return false;
    if($('#f_rst')?.checked && !s.stats.rst)return false;
    if($('#f_inc')?.checked && !s.partial)return false;
    return true;
  });
}
const SESS_COLS=[
 ['id','ID',s=>s.id],['client','Client',s=>s.client],['server','Server',s=>s.server],
 ['duration_ns','Duration',s=>s.duration_ns],['payload','Payload',s=>s.stats.payload_bytes],
 ['segs','Data segs',s=>s.stats.data_segments],
 ['retrans','Retx',s=>s.stats.retrans_segments],['retp','Retx %',s=>s.stats.retrans_pct],
 ['loss','Loss',s=>s.stats.loss_events],['dup','DupACK',s=>s.stats.dup_acks],
 ['ooo','OOO',s=>s.stats.ooo_packets],['sackev','SACK ev',s=>s.stats.sack_events],
 ['rtt50','RTT p50',s=>s.stats.rtt.median??-1],['rtt99','RTT p99',s=>s.stats.rtt.p99??-1],
 ['zw','ZeroWin',s=>s.stats.zero_window_events],['state','State',s=>s.state]];
function renderSessTable(){
  const rows=sessFiltered();
  const col=SESS_COLS.find(c=>c[0]===sortKey)||SESS_COLS[0];
  rows.sort((a,b)=>{const x=col[2](a),y=col[2](b);
    return (x>y?1:x<y?-1:0)*sortDir;});
  let h='<tr>'+SESS_COLS.map(c=>'<th onclick="setSort(\''+c[0]+'\')">'+c[1]+
    (sortKey===c[0]?(sortDir>0?' ▲':' ▼'):'')+'</th>').join('')+'</tr>';
  rows.forEach((s,i)=>{
    const sev=s.verdicts.some(v=>v.severity==='bad')?'bad'
             :s.verdicts.some(v=>v.severity==='warn')?'warn':'ok';
    h+='<tr class="clickable" style="--i:'+Math.min(i,30)+'" onclick="openSession('+s.id+')">'+
      '<td><span class="hdot '+sev+'" title="worst verdict severity: '+sev+'"></span>'+s.label+
      (s.partial?' <span class="badge b-warn">partial</span>':'')+'</td>'+
      '<td>'+esc(s.client)+'</td><td>'+esc(s.server)+'</td>'+
      '<td class="num">'+fmtNs(s.duration_ns)+'</td>'+
      '<td class="num">'+fmtBytes(s.stats.payload_bytes)+'</td>'+
      '<td class="num">'+fmtInt(s.stats.data_segments)+'</td>'+
      '<td class="num">'+fmtInt(s.stats.retrans_segments)+'</td>'+
      '<td class="num">'+pct(s.stats.retrans_pct)+'</td>'+
      '<td class="num">'+fmtInt(s.stats.loss_events)+'</td>'+
      '<td class="num">'+fmtInt(s.stats.dup_acks)+'</td>'+
      '<td class="num">'+fmtInt(s.stats.ooo_packets)+'</td>'+
      '<td class="num">'+fmtInt(s.stats.sack_events)+'</td>'+
      '<td class="num">'+fmtNs(s.stats.rtt.median)+'</td>'+
      '<td class="num">'+fmtNs(s.stats.rtt.p99)+'</td>'+
      '<td class="num">'+fmtInt(s.stats.zero_window_events)+'</td>'+
      '<td><span class="pill '+esc(s.state)+'">'+esc(s.state)+'</span></td></tr>';
  });
  $('#sessTable').innerHTML=h+(rows.length?'':'<tr><td colspan="16"><div class="empty">no sessions match the filters</div></td></tr>');
}
function setSort(k){if(sortKey===k)sortDir=-sortDir;else{sortKey=k;sortDir=1;}renderSessTable();}

/* ------------------------------------------------------ loss dashboard */
function allLoss(){
  const out=[];
  for(const s of M.sessions)for(const e of s.loss_events)out.push({s,e});
  return out;
}
function renderLossTable(){
  let h='<tr><th>Loss ID</th><th>Session</th><th>Dir</th><th>SEQ range</th><th>Bytes</th>'+
    '<th>Original TX</th><th>Detected</th><th>Retrans</th><th>Recovery</th>'+
    '<th>Detection</th><th>Reaction</th><th>Post-retx</th><th>Total</th>'+
    '<th>SACK</th><th>DupACKs</th><th>Class</th></tr>';
  allLoss().forEach(({s,e},i)=>{
    h+='<tr class="clickable" style="--i:'+Math.min(i,30)+'" onclick="openSession('+s.id+',\'loss\')">'+
     '<td>'+esc(e.loss_id)+'</td><td>#'+s.id+'</td><td>'+e.dir+'</td>'+
     '<td class="num">'+fmtSeq(s,e.dir,e.seq)+'–'+fmtSeq(s,e.dir,e.end)+'</td>'+
     '<td class="num">'+fmtInt(e.bytes)+'</td>'+
     '<td class="num">'+fmtTs(e.original_tx)+'</td>'+
     '<td class="num">'+fmtTs(e.evidence_ts)+'</td>'+
     '<td class="num">'+fmtTs(e.retrans_ts)+'</td>'+
     '<td class="num">'+fmtTs(e.recovery_ts)+'</td>'+
     '<td class="num">'+fmtNs(e.detection_ns)+'</td>'+
     '<td class="num">'+fmtNs(e.reaction_ns)+'</td>'+
     '<td class="num">'+fmtNs(e.post_retrans_ns)+'</td>'+
     '<td class="num">'+fmtNs(e.total_ns)+'</td>'+
     '<td>'+(e.sack?'yes':'no')+'</td><td class="num">'+e.dup_acks+'</td>'+
     '<td>'+esc(e.classification)+(e.recovered?'':' <span class="badge b-bad">unrecovered</span>')+'</td></tr>';
  });
  $('#lossTable').innerHTML=h+(allLoss().length?'':'<tr><td colspan="16"><div class="empty">no loss events in this capture</div></td></tr>');
}

/* -------------------------------------------------------- session view */
function openSession(id,tab){
  curSess=M.sessions.find(s=>s.id===id);curTab=tab||'overview';
  renderNav();
  renderDetail(true);
  $('#detail').scrollIntoView({behavior:MOTION?'smooth':'auto'});
}
const TABS=[['overview','Overview'],['sequence','Sequence'],['ack','ACK'],['sack','SACK'],
 ['loss','Loss'],['retrans','Retransmissions'],['rtt','RTT'],['window','Window'],
 ['timeline','Timeline'],['packets','Packets']];
function renderDetail(pop){
  const s=curSess;if(!s){$('#detail').style.display='none';return;}
  const d=$('#detail');
  d.style.display='block';
  if(pop){d.classList.remove('pop');void d.offsetWidth;d.classList.add('pop');}
  let h='<h2>'+s.label+' &mdash; '+esc(s.client)+' ⇄ '+esc(s.server)+'</h2>';
  h+='<div class="tabs" role="tablist">'+TABS.map(t=>'<div class="'+(curTab===t[0]?'active':'')+
    '" role="tab" tabindex="0" aria-selected="'+(curTab===t[0])+
    '" onclick="switchTab(\''+t[0]+'\')" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();switchTab(\''+t[0]+'\');}">'+
    t[1]+'</div>').join('')+'</div>';
  h+='<div id="tabBody"></div>';
  d.innerHTML=h;
  renderTab();
}
function switchTab(t){curTab=t;renderDetail();}
function renderTab(){
  const body=$('#tabBody'),s=curSess;
  const fn={overview:tabOverview,sequence:tabSequence,ack:tabAck,sack:tabSack,
    loss:tabLoss,retrans:tabRetrans,rtt:tabRtt,window:tabWindow,
    timeline:tabTimeline,packets:tabPackets}[curTab];
  body.innerHTML='<div class="tabIn">'+fn(s)+'</div>';
  const post={sack:postSack,timeline:postTimeline,rtt:postRtt,ack:postAck}[curTab];
  if(post)post(s);
}

/* --- overview */
function tabOverview(s){
  const hs=s.handshake;
  let h='<div class="grid2"><div><h3>Connection</h3><div class="kv">'+
   '<div class="k">Client</div><div>'+esc(s.client)+'</div>'+
   '<div class="k">Server</div><div>'+esc(s.server)+'</div>'+
   '<div class="k">Start</div><div>'+esc(s.start_str)+' UTC</div>'+
   '<div class="k">End</div><div>'+esc(s.end_str)+' UTC</div>'+
   '<div class="k">Duration</div><div>'+fmtNs(s.duration_ns)+'</div>'+
   '<div class="k">State</div><div>'+esc(s.state)+(s.partial?' <span class="badge b-warn">mid-capture / partial</span>':'')+'</div>'+
   '<div class="k">SYN&rarr;SYN/ACK</div><div>'+fmtNs(hs.syn_synack_ns)+(hs.syn_frame?' <span class="mut">frames '+hs.syn_frame+'&rarr;'+hs.synack_frame+'</span>':'')+'</div>'+
   '<div class="k">SYN/ACK&rarr;ACK</div><div>'+fmtNs(hs.synack_ack_ns)+'</div>'+
   '<div class="k">Establishment</div><div>'+fmtNs(hs.total_ns)+'</div>'+
   '<div class="k">SACK client</div><div>'+tri(s.sack_client)+'</div>'+
   '<div class="k">SACK server</div><div>'+tri(s.sack_server)+'</div>'+
   '<div class="k">SACK active</div><div>'+tri(s.sack_active)+'</div>'+
   '</div></div>';
  h+='<div><h3>Directions</h3><table><tr><th></th><th>A&rarr;B '+esc(s.ep_a)+'&rarr;'+esc(s.ep_b)+'</th><th>B&rarr;A</th></tr>';
  const rows=[['Packets','packets'],['Bytes (IP)','bytes'],['Payload','payload_bytes'],
   ['Unique bytes','unique_bytes'],['ACKed bytes','acked_bytes'],['Outstanding','outstanding_bytes'],
   ['Data segments','data_segments'],['Retrans segs','retrans_segments'],['Retrans bytes','retrans_bytes'],
   ['Out-of-order','ooo_packets'],['Duplicates','dup_packets'],['Keep-alives','keepalives'],
   ['SACK events','sack_events'],
   ['SACK blocks','sack_blocks'],['SACK holes','sack_holes'],['DSACK','dsack_events'],
   ['Zero-window','zero_window_events'],['MSS','mss'],['Window scale','window_scale']];
  rows.forEach((r,i)=>{h+='<tr style="--i:'+i+'"><td class="mut">'+r[0]+'</td><td class="num">'+fmtInt(s.dir_a[r[1]])+'</td><td class="num">'+fmtInt(s.dir_b[r[1]])+'</td></tr>';});
  h+='</table></div></div>';
  h+='<h3>Automated verdicts <span class="mut" style="text-transform:none">(thresholds: '+esc(JSON.stringify(M.verdict_config))+')</span></h3>';
  const GLYPH={ok:'✓',warn:'!',bad:'✕',info:'i'};
  s.verdicts.forEach((v,i)=>{h+='<div class="verdict '+v.severity+'" style="--i:'+i+'">'+
    '<div class="glyph" aria-hidden="true">'+GLYPH[v.severity]+'</div>'+
    '<b>'+esc(v.verdict)+'</b><div class="ev">'+esc(v.evidence)+'</div></div>';});
  if(s.warnings.length){h+='<h3>Capture artifact warnings</h3>';
    for(const w of s.warnings)h+='<div class="warnbox">⚠ '+esc(w)+'</div>';}
  if(s.stats.network_dups){
    h+='<h3>Multi-point observations <span class="mut" style="text-transform:none">— the same packet captured at more than one point (SPAN/leaf-to-leaf); excluded from retransmission &amp; dup-ACK statistics</span></h3>'+
     '<div>Inter-observation skew: '+statLine(s.stats.observation_skew)+'</div>'+
     '<div class="scroll" style="max-height:260px;margin-top:8px"><table><tr>'+
     '<th>Frame</th><th>Observed</th><th>First seen (frame)</th><th>Skew Δ</th><th>Dir</th><th>What changed</th><th>Confidence</th></tr>';
    s.observation_events.slice(0,2000).forEach((e,i)=>{
      h+='<tr style="--i:'+Math.min(i,30)+'"><td class="num">'+e.frame+'</td>'+
       '<td class="num">'+fmtTs(e.ts)+'</td>'+
       '<td class="num">'+fmtTs(e.orig_ts)+' <span class="mut">#'+e.orig_frame+'</span></td>'+
       '<td class="num" style="color:var(--accent)">'+fmtNs(e.delta_ns)+'</td>'+
       '<td>'+e.dir+'</td><td style="white-space:normal">'+esc(e.differs)+'</td>'+
       '<td>'+(e.confidence==='confirmed'
         ?'<span class="badge b-ok">confirmed (same IP ID)</span>'
         :'<span class="badge b-warn">likely (L2/TTL rewrite)</span>')+'</td></tr>';
    });
    h+='</table></div>';
  }
  return h;
}

/* --- sequence ledger */
function tabSequence(s){
  let h='<div class="controls"><label>search SEQ <input id="seqSearch" size="12" oninput="renderSeqRows()"></label>'+
   '<label>direction <select id="seqDir" onchange="renderSeqRows()"><option value="">both</option><option>A-&gt;B</option><option>B-&gt;A</option></select></label>'+
   '<label>state <select id="seqState" onchange="renderSeqRows()"><option value="">all</option>'+
   ['Original','ACKed','SACKed','Retransmitted','Duplicate','Out-of-order','Recovered','Keep-alive','Window-probe'].map(x=>'<option>'+x+'</option>').join('')+'</select></label>'+
   '<button onclick="exportSessionPackets()">Export session events CSV</button></div>'+
   (s.segments_truncated?'<div class="warnbox">'+fmtInt(s.segments_truncated)+' ledger rows beyond the embedding cap were omitted (large session) — statistics above remain computed from the full data.</div>':'')+
   '<div class="scroll" style="max-height:520px"><table id="seqTable"></table></div>';
  setTimeout(renderSeqRows,0);
  return h;
}
function renderSeqRows(){
  const s=curSess;if(!s)return;
  const q=$('#seqSearch')?.value.trim();
  const dir=($('#seqDir')?.value||'').replace('-&gt;','->');
  const st=$('#seqState')?.value||'';
  let rows=s.segments;
  if(dir)rows=rows.filter(r=>r.dir===dir);
  if(st)rows=rows.filter(r=>r.state===st);
  if(q!==''&&!isNaN(+q)){const v=+q;rows=rows.filter(r=>{
    let qq=v;
    if(SEQMODE==='raw'){qq=(v-seqBase(s,r.dir))%4294967296;if(qq<0)qq+=4294967296;}
    return r.seq<=qq&&qq<r.end||r.seq===qq||r.end===qq
      ||(SEQMODE==='raw'&&(r.seq<=qq+4294967296&&qq+4294967296<r.end));});}
  let h='<tr><th>Time</th><th>Frame</th><th>Dir</th><th>SEQ start</th><th>SEQ end</th><th>NEXTSEQ</th>'+
   '<th>Len</th><th>Flags</th><th>State</th><th>Orig frame</th><th>Retx delay</th>'+
   '<th>ACKed by</th><th>DATA→ACK</th><th>RTT</th><th>SACKed by</th></tr>';
  rows.slice(0,4000).forEach((r,i)=>{
    h+='<tr style="--i:'+Math.min(i,30)+'"><td class="num">'+fmtTs(r.ts)+'</td><td class="num">'+r.frame+'</td><td>'+r.dir+'</td>'+
     '<td class="num">'+fmtSeq(s,r.dir,r.seq)+'</td><td class="num">'+fmtSeq(s,r.dir,r.end)+'</td><td class="num">'+fmtSeq(s,r.dir,r.end)+'</td>'+
     '<td class="num">'+r.len+'</td><td>'+r.flags+'</td>'+
     '<td class="state-'+r.state.replace(/ /g,'-')+'">'+r.state+(r.retx_kind?' <span class="mut">('+r.retx_kind+')</span>':'')+'</td>'+
     '<td class="num">'+(r.retx_of??'-')+'</td><td class="num">'+fmtNs(r.retx_delay)+'</td>'+
     '<td class="num">'+(r.ack_frame??'-')+'</td><td class="num">'+fmtNs(r.ack_lat)+'</td>'+
     '<td class="num">'+(r.rtt_ambiguous?'<span class="b-warn">AMBIGUOUS</span>':fmtNs(r.rtt))+'</td>'+
     '<td class="num">'+(r.sack_frame??'-')+'</td></tr>';
  });
  if(rows.length>4000)h+='<tr><td colspan="15" class="mut">'+fmtInt(rows.length-4000)+' more rows not shown — refine the filter</td></tr>';
  $('#seqTable').innerHTML=h;
}

/* --- ACK tab */
function tabAck(s){
  let h='<h3>DATA → cumulative ACK latency</h3><div>'+statLine(s.stats.ack_latency)+'</div>'+
   '<canvas id="ackHist" width="700" height="170"></canvas>'+
   '<h3>Duplicate ACK trains</h3><div class="scroll" style="max-height:300px"><table><tr>'+
   '<th>Dir</th><th>ACK</th><th>First frame</th><th>First TS</th><th>Dup count</th><th>Inter-ACK gaps</th>'+
   '<th>SACK blocks</th><th>Missing range</th><th>Retrans frame</th><th>Time to retrans</th><th>Time to recovery</th></tr>';
  s.dup_ack_trains.forEach((t,i)=>{
    h+='<tr style="--i:'+i+'"><td>'+t.dir+'</td><td class="num">'+fmtSeq(s,oppDir(t.dir),t.ack)+'</td><td class="num">'+t.first_frame+'</td>'+
     '<td class="num">'+fmtTs(t.first_ts)+'</td><td class="num">'+t.count+'</td>'+
     '<td class="num">'+t.gaps_ns.slice(0,6).map(g=>fmtNs(g)).join(', ')+(t.gaps_ns.length>6?' …':'')+'</td>'+
     '<td class="num">'+t.sack_blocks+'</td>'+
     '<td class="num">'+(t.missing_seq!=null?fmtSeq(s,oppDir(t.dir),t.missing_seq)+'–'+fmtSeq(s,oppDir(t.dir),t.missing_end):'-')+'</td>'+
     '<td class="num">'+(t.retrans_frame??'-')+'</td><td class="num">'+fmtNs(t.time_to_retrans)+'</td>'+
     '<td class="num">'+fmtNs(t.time_to_recovery)+'</td></tr>';
  });
  if(!s.dup_ack_trains.length)h+='<tr><td colspan="11" class="mut">no duplicate ACK trains</td></tr>';
  return h+'</table></div>';
}
function postAck(s){drawHist($('#ackHist'),s.ack_hist,C.ack);}

/* --- SACK tab */
const sbState={};   // per-id previous drawn scoreboard (for fluid interpolation)
const sbTimers={};
function tabSack(s){
  let h='<div class="kv">'+
   '<div class="k">SACK client</div><div>'+tri(s.sack_client)+'</div>'+
   '<div class="k">SACK server</div><div>'+tri(s.sack_server)+'</div>'+
   '<div class="k">SACK active</div><div>'+tri(s.sack_active)+'</div></div>';
  for(const dir of ['A->B','B->A']){
    const snaps=s.sack_snapshots[dir]||[];
    if(!snaps.length)continue;
    const id=dir==='A->B'?'ab':'ba';
    delete sbState[id];
    h+='<h3>SACK scoreboard — data direction '+dir+' <span class="mut" style="text-transform:none">('+snaps.length+' SACK events; step chronologically)</span></h3>'+
     '<div class="controls"><button onclick="sbStep(\''+id+'\',-1)">◀ prev</button>'+
     '<input type="range" id="sb_'+id+'" min="0" max="'+(snaps.length-1)+'" value="0" style="width:340px" oninput="sbStop(\''+id+'\');sbDraw(\''+id+'\')">'+
     '<button onclick="sbStep(\''+id+'\',1)">next ▶</button>'+
     '<button id="sbPlayBtn_'+id+'" class="primary" onclick="sbPlay(\''+id+'\')">▶ play</button>'+
     '<span id="sbInfo_'+id+'" class="mut"></span></div>'+
     '<canvas id="sbCanvas_'+id+'" width="1100" height="110"></canvas>'+
     '<div class="legend"><span><span class="dot" style="background:'+C.acked+'"></span>cumulatively ACKed</span>'+
     '<span><span class="dot" style="background:'+C.sacked+'"></span>SACKed</span>'+
     '<span><span class="dot" style="background:'+C.hole+'"></span>hole / missing</span>'+
     '<span><span class="dot" style="background:'+C.out+'"></span>outstanding</span></div>';
  }
  if(s.sack_truncated||s.sack_snap_truncated)
    h+='<div class="warnbox">'+fmtInt((s.sack_truncated||0)+(s.sack_snap_truncated||0))+
     ' SACK records/snapshots beyond the embedding cap were omitted — scoreboard statistics cover all events.</div>';
  h+='<h3>SACK option records</h3><div class="scroll" style="max-height:320px"><table><tr>'+
   '<th>Frame</th><th>Time</th><th>Data dir</th><th>Cum ACK</th><th>#Blocks</th><th>Blocks (left–right)</th><th>DSACK</th></tr>';
  s.sack_records.slice(0,3000).forEach((r,i)=>{
    h+='<tr style="--i:'+Math.min(i,30)+'"><td class="num">'+r.frame+'</td><td class="num">'+fmtTs(r.ts)+'</td><td>'+r.data_dir+'</td>'+
     '<td class="num">'+fmtSeq(s,r.data_dir,r.ack)+'</td><td class="num">'+r.blocks.length+'</td>'+
     '<td class="num">'+r.blocks.map(b=>fmtSeq(s,r.data_dir,b[0])+'–'+fmtSeq(s,r.data_dir,b[1])).join(' | ')+'</td>'+
     '<td>'+(r.dsack?'<span class="badge b-warn">DSACK</span> <span class="mut">'+esc(r.dsack_reason||'')+'</span>':'-')+'</td></tr>';
  });
  if(!s.sack_records.length)h+='<tr><td colspan="7" class="mut">no SACK options observed</td></tr>';
  return h+'</table></div>';
}
function postSack(s){for(const id of ['ab','ba'])if($('#sb_'+id))sbDraw(id);}
function sbStep(id,d){sbStop(id);const el=$('#sb_'+id);el.value=Math.max(0,Math.min(+el.max,+el.value+d));sbDraw(id);}
function sbPlay(id){
  if(sbTimers[id]){sbStop(id);return;}
  const el=$('#sb_'+id);
  if(+el.value>=+el.max)el.value=0;
  $('#sbPlayBtn_'+id).textContent='⏸ pause';
  sbTimers[id]=setInterval(()=>{
    if(+el.value>=+el.max){sbStop(id);return;}
    el.value=+el.value+1;sbDraw(id);
  }, MOTION?750:400);
  sbDraw(id);
}
function sbStop(id){
  if(sbTimers[id]){clearInterval(sbTimers[id]);delete sbTimers[id];}
  const b=$('#sbPlayBtn_'+id);if(b)b.textContent='▶ play';
}
function sbDraw(id){
  const dir=id==='ab'?'A->B':'B->A';
  const snaps=curSess.sack_snapshots[dir];const i=+$('#sb_'+id).value;const sn=snaps[i];
  $('#sbInfo_'+id).textContent=' event '+(i+1)+'/'+snaps.length+' frame '+sn.frame+' '+fmtTs(sn.ts)+
    ' ACK='+fmtSeq(curSess,dir,sn.ack)+(sn.dsack?' [DSACK]':'')+(sn.ack_advanced?' [ACK advanced]':'');
  const cv=$('#sbCanvas_'+id),ctx=cv.getContext('2d');
  let lo=sn.ack,hi=sn.ack+1;
  for(const [a,b] of sn.sacked){lo=Math.min(lo,a);hi=Math.max(hi,b);}
  for(const [a,b] of sn.holes){lo=Math.min(lo,a);hi=Math.max(hi,b);}
  lo=Math.min(lo,Math.max(0,sn.ack-(hi-lo)*0.15));
  const target={ack:sn.ack,lo,hi,sacked:sn.sacked,holes:sn.holes};
  const prev=sbState[id];
  sbState[id]=target;
  const lerp=(a,b,p)=>a+(b-a)*p;
  const render=p=>{
    const L=prev?lerp(prev.lo,lo,p):lo, H=prev?lerp(prev.hi,hi,p):hi;
    const A=prev?lerp(prev.ack,sn.ack,p):sn.ack;
    const X=v=>30+(H>L?(v-L)/(H-L):0)*(cv.width-60);
    ctx.clearRect(0,0,cv.width,cv.height);
    ctx.fillStyle=C.out;ctx.beginPath();ctx.roundRect(30,40,cv.width-60,28,5);ctx.fill();
    ctx.fillStyle=C.acked;
    ctx.beginPath();ctx.roundRect(30,40,Math.max(0,X(A)-30),28,[5,0,0,5]);ctx.fill();
    const alpha=prev?Math.min(1,.35+.65*p):1;
    ctx.globalAlpha=alpha;
    for(const [a,b] of sn.sacked){ctx.fillStyle=C.sacked;ctx.fillRect(X(a),40,Math.max(2,X(b)-X(a)),28);}
    for(const [a,b] of sn.holes){ctx.fillStyle=C.hole;ctx.fillRect(X(a),40,Math.max(2,X(b)-X(a)),28);}
    ctx.globalAlpha=1;
    ctx.fillStyle='#8b95a8';ctx.font='10px monospace';
    ctx.fillText(fmtSeq(curSess,dir,Math.round(L)),30,92);
    const t2=fmtSeq(curSess,dir,Math.round(H));ctx.fillText(t2,cv.width-30-ctx.measureText(t2).width,92);
    ctx.fillStyle='#eef2f8';ctx.fillText('ACK '+fmtSeq(curSess,dir,sn.ack),Math.min(cv.width-100,Math.max(30,X(A))),30);
    ctx.strokeStyle='#eef2f8';ctx.lineWidth=1.5;
    ctx.beginPath();ctx.moveTo(X(A),34);ctx.lineTo(X(A),72);ctx.stroke();
    for(const [a,b] of sn.holes){ctx.fillStyle=C.hole;
      ctx.fillText('hole '+fmtSeq(curSess,dir,a)+'–'+fmtSeq(curSess,dir,b),Math.max(30,Math.min(cv.width-170,X(a))),105);}
  };
  if(prev)animCanvas(cv,380,render);else render(1);
}

/* --- loss tab */
function tabLoss(s){
  let h='<div>'+statLine(s.stats.recovery)+' <span class="mut">(total recovery: original TX → recovery ACK)</span></div>'+
   '<canvas id="recHist" width="700" height="150"></canvas>'+
   '<div class="scroll" style="max-height:460px"><table><tr><th>Loss ID</th><th>Dir</th><th>SEQ range</th><th>Bytes</th>'+
   '<th>Original TX</th><th>Evidence</th><th>Retrans</th><th>Recovery</th>'+
   '<th>Detection</th><th>Reaction</th><th>Post-retx</th><th>Total</th>'+
   '<th>Mechanism</th><th>SACK reports</th><th>DupACKs</th><th>Extra holes</th><th>Class</th><th></th></tr>';
  s.loss_events.forEach((e,i)=>{
    h+='<tr style="--i:'+Math.min(i,30)+'"><td>'+esc(e.loss_id)+'</td><td>'+e.dir+'</td>'+
     '<td class="num">'+fmtSeq(s,e.dir,e.seq)+'–'+fmtSeq(s,e.dir,e.end)+'</td><td class="num">'+e.bytes+'</td>'+
     '<td class="num">'+fmtTs(e.original_tx)+(e.original_frame?' <span class="mut">#'+e.original_frame+'</span>':'')+'</td>'+
     '<td class="num">'+fmtTs(e.evidence_ts)+' <span class="mut">'+esc(e.evidence_kind)+' #'+(e.evidence_frame??'-')+'</span></td>'+
     '<td class="num">'+fmtTs(e.retrans_ts)+(e.retrans_frame?' <span class="mut">#'+e.retrans_frame+'</span>':'')+
       (e.retrans_lost?' <span class="badge b-bad">retx lost too</span>':'')+'</td>'+
     '<td class="num">'+fmtTs(e.recovery_ts)+(e.recovery_frame?' <span class="mut">#'+e.recovery_frame+'</span>':'')+
       (e.partial?' <span class="badge b-warn">partial</span>':'')+'</td>'+
     '<td class="num">'+fmtNs(e.detection_ns)+'</td><td class="num">'+fmtNs(e.reaction_ns)+'</td>'+
     '<td class="num">'+fmtNs(e.post_retrans_ns)+'</td><td class="num">'+fmtNs(e.total_ns)+'</td>'+
     '<td>'+esc(e.mechanism)+'</td><td class="num">'+e.sack_reports+'</td><td class="num">'+e.dup_acks+'</td>'+
     '<td class="num">'+e.additional_holes+'</td>'+
     '<td>'+esc(e.classification)+(e.classification_evidence?' <span class="mut" title="'+esc(e.classification_evidence)+'">ⓘ</span>':'')+'</td>'+
     '<td><a onclick="jumpToSeq('+e.seq+')">sequence →</a></td></tr>';
  });
  if(!s.loss_events.length)h+='<tr><td colspan="18" class="mut">no loss events</td></tr>';
  setTimeout(()=>drawHist($('#recHist'),s.recovery_hist,C.loss),0);
  return h+'</table></div>';
}
function jumpToSeq(seq){switchTab('sequence');setTimeout(()=>{$('#seqSearch').value=seq;renderSeqRows();},50);}

/* --- retransmissions tab */
function tabRetrans(s){
  let h='<div class="scroll" style="max-height:520px"><table><tr><th>Frame</th><th>Time</th><th>Dir</th>'+
   '<th>SEQ range</th><th>Bytes</th><th>Classification</th><th>Original</th><th>Delay</th>'+
   '<th>DupACKs before</th><th>SACK</th><th>Evidence</th></tr>';
  s.retrans_events.forEach((r,i)=>{
    h+='<tr style="--i:'+Math.min(i,30)+'"><td class="num">'+r.frame+'</td><td class="num">'+fmtTs(r.ts)+'</td><td>'+r.dir+'</td>'+
     '<td class="num">'+fmtSeq(s,r.dir,r.seq)+'–'+fmtSeq(s,r.dir,r.end)+'</td><td class="num">'+r.bytes+'</td>'+
     '<td class="state-Retransmitted">'+esc(r.class)+'</td>'+
     '<td class="num">'+(r.orig_frame?'#'+r.orig_frame+' '+fmtTs(r.orig_ts):'-')+'</td>'+
     '<td class="num">'+fmtNs(r.delay)+'</td><td class="num">'+r.dup_acks+'</td>'+
     '<td>'+(r.sack?'yes':'no')+'</td><td style="white-space:normal;max-width:420px">'+esc(r.evidence)+'</td></tr>';
  });
  if(!s.retrans_events.length)h+='<tr><td colspan="11" class="mut">no retransmissions</td></tr>';
  return h+'</table></div>';
}

/* --- RTT tab */
function tabRtt(s){
  let h='<div>'+statLine(s.stats.rtt)+' <span class="mut">valid samples only (Karn); '+
    s.rtt_ambiguous.length+' ambiguous samples excluded</span></div>'+
   '<canvas id="rttHist" width="700" height="170"></canvas><canvas id="rttCdf" width="700" height="150"></canvas>'+
   (s.rtt_truncated?'<div class="warnbox">'+fmtInt(s.rtt_truncated)+' RTT sample rows beyond the embedding cap were omitted — the statistics and charts above cover ALL samples.</div>':'')+
   '<h3>Valid RTT samples</h3><div class="scroll" style="max-height:280px"><table><tr>'+
   '<th>Time</th><th>Kind</th><th>Dir</th><th>SEQ range</th><th>Data frame</th><th>ACK frame</th><th>RTT</th></tr>';
  s.rtt_samples.slice(0,3000).forEach((r,i)=>{
    h+='<tr style="--i:'+Math.min(i,30)+'"><td class="num">'+fmtTs(r.ts)+'</td><td>'+r.kind+'</td><td>'+r.dir+'</td>'+
     '<td class="num">'+fmtSeq(s,r.dir,r.seq)+'–'+fmtSeq(s,r.dir,r.end)+'</td>'+
     '<td class="num">'+r.frame_data+'</td><td class="num">'+r.frame_ack+'</td>'+
     '<td class="num">'+fmtNs(r.rtt)+'</td></tr>';
  });
  h+='</table></div>';
  if(s.rtt_ambiguous.length){
    h+='<h3>RTT AMBIGUOUS (excluded, retained for forensics)</h3><div class="scroll" style="max-height:200px"><table><tr>'+
     '<th>ACK time</th><th>Dir</th><th>SEQ range</th><th>Data frame</th><th>ACK frame</th><th>Reason</th></tr>';
    for(const r of s.rtt_ambiguous)
      h+='<tr><td class="num">'+fmtTs(r.ts)+'</td><td>'+r.dir+'</td><td class="num">'+fmtSeq(s,r.dir,r.seq)+'–'+fmtSeq(s,r.dir,r.end)+'</td>'+
       '<td class="num">'+r.frame_data+'</td><td class="num">'+r.frame_ack+'</td><td style="white-space:normal">'+esc(r.reason)+'</td></tr>';
    h+='</table></div>';
  }
  return h;
}
function postRtt(s){drawHist($('#rttHist'),s.rtt_hist,C.rtt);drawCdf($('#rttCdf'),s.rtt_hist,C.rtt);}

/* --- window tab */
function tabWindow(s){
  let h='<div class="kv">'+
   '<div class="k">A&rarr;B advertised window</div><div>min '+fmtInt(s.dir_a.window_min)+' / max '+fmtInt(s.dir_a.window_max)+' bytes (scale '+fmtInt(s.dir_a.window_scale)+')</div>'+
   '<div class="k">B&rarr;A advertised window</div><div>min '+fmtInt(s.dir_b.window_min)+' / max '+fmtInt(s.dir_b.window_max)+' bytes (scale '+fmtInt(s.dir_b.window_scale)+')</div></div>'+
   '<div class="scroll" style="max-height:420px"><table><tr><th>Time</th><th>Frame</th><th>Advertiser dir</th><th>Kind</th><th>Window</th><th>Detail</th></tr>';
  s.window_events.forEach((w,i)=>{
    h+='<tr style="--i:'+i+'"><td class="num">'+fmtTs(w.ts)+'</td><td class="num">'+w.frame+'</td><td>'+w.dir+'</td>'+
     '<td>'+esc(w.kind)+'</td><td class="num">'+fmtInt(w.window)+'</td><td style="white-space:normal">'+esc(w.detail)+'</td></tr>';
  });
  if(!s.window_events.length)h+='<tr><td colspan="6" class="mut">no window events</td></tr>';
  return h+'</table></div>';
}

/* --- timeline tab: ladder + latency time-series */
function tabTimeline(s){
  const n=s.packets.length;
  return '<h3>Sequence ladder ('+esc(s.ep_a)+' left, '+esc(s.ep_b)+' right) — click an arrow for full details</h3>'+
   '<div class="controls"><label>window start <input type="range" id="tlStart" min="0" max="'+Math.max(0,n-1)+'" value="0" style="width:320px" oninput="drawLadder()"></label>'+
   '<label>events <select id="tlCount" onchange="drawLadder(true)"><option>30</option><option selected>60</option><option>120</option><option>250</option></select></label>'+
   '<span id="tlInfo" class="mut"></span></div>'+
   '<canvas id="ladder" width="1100" height="600" onclick="ladderClick(event)" onmousemove="ladderHover(event)"></canvas>'+
   '<div id="ladderDetail" class="warnbox" style="display:none;border-color:var(--accent);background:rgba(57,135,229,.07)"></div>'+
   '<h3>Latency timeline — RTT / DATA→ACK samples with loss, retransmission, dup-ACK and zero-window markers</h3>'+
   '<div class="legend">'+
   '<span><span class="dot" style="background:'+C.dup+'"></span>dup-ACK train</span>'+
   '<span><span class="dot" style="background:'+C.rtt+'"></span>RTT sample</span>'+
   '<span><span class="dot" style="background:'+C.loss+'"></span>loss evidence</span>'+
   '<span><span class="dot" style="background:'+C.ack+'"></span>DATA→ACK</span>'+
   '<span><span class="dot" style="background:'+C.zw+'"></span>zero-window</span>'+
   '<span><span class="dot" style="background:'+C.retx+'"></span>retransmission</span></div>'+
   '<canvas id="latTl" width="1100" height="260" onmousemove="latHover(event)"></canvas>';
}
let ladderRows=[];
function postTimeline(s){drawLadder(true);drawLatTimeline(s);}
function drawLadder(animate){
  const s=curSess,cv=$('#ladder'),ctx=cv.getContext('2d');
  const start=+($('#tlStart')?.value||0),count=+($('#tlCount')?.value||60);
  const rows=s.packets.slice(start,start+count);
  ladderRows=[];
  const L=180,R=cv.width-180,top=30,step=Math.max(9,(cv.height-60)/Math.max(1,rows.length));
  $('#tlInfo').textContent=' showing '+(start+1)+'–'+(start+rows.length)+' of '+s.packets.length+' packets';
  const rowMeta=rows.map((p,i)=>{
    const y=top+i*step;
    const [frame,ts,dir,seq,end,len,flags,ack,win,sackn,state]=p;
    let color='#8b95a8';
    if(state==='Retransmitted')color=C.retx;
    else if(state==='Duplicate')color=C.loss;
    else if(state==='Capture-dup')color='#5a6478';
    else if(state==='Out-of-order')color=C.dup;
    else if(len>0)color=C.rtt;
    else if(sackn>0)color=C.zw;
    else if(flags.includes('SYN')||flags.includes('FIN')||flags.includes('RST'))color='#eef2f8';
    let lab=flags+(sackn>0?' +SACK×'+sackn:'');
    if(state==='Capture-dup')lab+=' [same packet, 2nd observation]';
    else if(len>0)lab=flags+' SEQ '+fmtSeq(s,dir,seq)+'–'+fmtSeq(s,dir,end)+' ('+len+'B)';
    if(state==='Retransmitted')lab+=' [RETX]';
    if(state==='Out-of-order')lab+=' [OOO]';
    ladderRows.push({y,p});
    return {y,p,color,lab,l2r:dir==='A->B'};
  });
  const render=pr=>{
    ctx.clearRect(0,0,cv.width,cv.height);
    ctx.strokeStyle='rgba(120,140,190,.28)';ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(L,top-14);ctx.lineTo(L,cv.height-10);ctx.moveTo(R,top-14);ctx.lineTo(R,cv.height-10);ctx.stroke();
    ctx.fillStyle='#eef2f8';ctx.font='11px monospace';
    ctx.fillText(s.ep_a,L-ctx.measureText(s.ep_a).width/2,14);
    ctx.fillText(s.ep_b,R-ctx.measureText(s.ep_b).width/2,14);
    const visible=pr*rowMeta.length;
    rowMeta.forEach((m,i)=>{
      if(i>=visible)return;
      const frac=Math.min(1,visible-i);            // arrow grows across
      const [frame,ts]=m.p;
      const x0=m.l2r?L:R, x1=m.l2r?R:L;
      const xe=x0+(x1-x0)*frac;
      ctx.strokeStyle=m.color;ctx.fillStyle=m.color;ctx.lineWidth=1.4;
      ctx.beginPath();ctx.moveTo(x0,m.y);ctx.lineTo(xe,m.y);ctx.stroke();
      if(frac>=1){
        const dx=m.l2r?-7:7;
        ctx.beginPath();ctx.moveTo(x1,m.y);ctx.lineTo(x1+dx,m.y-4);ctx.lineTo(x1+dx,m.y+4);ctx.closePath();ctx.fill();
        ctx.fillText(m.lab,(L+R)/2-ctx.measureText(m.lab).width/2,m.y-3);
        ctx.fillStyle='#8b95a8';
        ctx.fillText(fmtTs(ts),8,m.y+3);
        // inter-packet latency between this arrow and the previous one —
        // the "SYN, +Δ, SYN/ACK, +Δ, ACK, +Δ, PSH ..." reading of the flow
        if(i>0&&step>=15){
          const dt=ts-rowMeta[i-1].p[1];
          ctx.fillStyle='#7fb3f5';ctx.font='10px monospace';
          ctx.fillText('Δ '+fmtNs(dt),8,m.y-step/2+3.5);
          ctx.font='11px monospace';
        }
      }
    });
  };
  if(animate&&MOTION)animCanvas(cv,Math.min(1200,140+rows.length*14),render);
  else{if(cv._tok)cancelAnimationFrame(cv._tok);render(1);}
}
function ladderAt(ev){
  const cv=$('#ladder'),r=cv.getBoundingClientRect();
  const y=(ev.clientY-r.top)*cv.height/r.height;
  let best=null,bd=8;
  for(const row of ladderRows){const d=Math.abs(row.y-y);if(d<bd){bd=d;best=row;}}
  return best;
}
function ladderHover(ev){const b=ladderAt(ev);$('#ladder').style.cursor=b?'pointer':'default';}
function ladderClick(ev){
  const b=ladderAt(ev);if(!b)return;
  const [frame,ts,dir,seq,end,len,flags,ack,win,sackn,state]=b.p;
  const seg=curSess.segments.find(g=>g.frame===frame);
  let h='<b>Frame '+frame+'</b> '+fmtTs(ts)+' ('+esc(dir)+')<br>'+
   'SEQ '+fmtSeq(curSess,dir,seq)+' → NEXTSEQ '+fmtSeq(curSess,dir,end)+' | payload '+len+' B | flags '+esc(flags)+
   ' | ACK(raw) '+fmtInt(ack)+' | window(raw) '+fmtInt(win)+(sackn?' | SACK blocks: '+sackn:'');
  if(seg){
    h+='<br>state: '+esc(seg.state);
    if(seg.retx)h+=' | retransmission of frame '+(seg.retx_of??'?')+' after '+fmtNs(seg.retx_delay)+' ('+esc(seg.retx_kind)+')';
    if(seg.ack_frame)h+='<br>ACKed by frame '+seg.ack_frame+' | DATA→ACK '+fmtNs(seg.ack_lat);
    if(seg.rtt!=null)h+=' | RTT '+fmtNs(seg.rtt);
    if(seg.rtt_ambiguous)h+=' | RTT: AMBIGUOUS (Karn exclusion)';
    if(seg.sack_frame)h+='<br>SACKed by frame '+seg.sack_frame;
    const le=curSess.loss_events.find(e=>e.dir===seg.dir&&seg.seq<e.end&&e.seq<seg.end);
    if(le)h+='<br>loss event '+esc(le.loss_id)+': detection '+fmtNs(le.detection_ns)+
      ', reaction '+fmtNs(le.reaction_ns)+', total recovery '+fmtNs(le.total_ns);
  }
  const d=$('#ladderDetail');d.style.display='block';d.innerHTML=h;
}
let latPts=[];
function drawLatTimeline(s){
  const cv=$('#latTl'),ctx=cv.getContext('2d');
  latPts=[];
  const t0=s.start_ts,t1=Math.max(s.end_ts,t0+1);
  const samples=s.rtt_samples.map(r=>({t:r.ts,v:r.rtt,c:C.rtt,lab:'RTT '+r.kind}));
  for(const g of s.segments)if(g.ack_lat!=null&&g.ack_lat>=0&&g.len>0)
    samples.push({t:g.acked_ts,v:g.ack_lat,c:C.ack,lab:'DATA→ACK frame '+g.frame});
  samples.sort((a,b)=>a.t-b.t);
  const vmax=Math.max(1,...samples.map(q=>q.v));
  const X=t=>40+(t-t0)/(t1-t0)*(cv.width-56);
  const Y=v=>cv.height-24-(v/vmax)*(cv.height-46);
  const markers=[];
  for(const r of s.retrans_events)markers.push([r.ts,C.retx]);
  for(const e of s.loss_events)markers.push([e.evidence_ts,C.loss]);
  for(const t of s.dup_ack_trains)if(t.count>=3)markers.push([t.first_ts,C.dup]);
  for(const w of s.window_events)if(w.kind==='zero-window')markers.push([w.ts,C.zw]);
  animCanvas(cv, 800, p=>{
    ctx.clearRect(0,0,cv.width,cv.height);
    markers.forEach(([ts,color])=>{
      if(ts==null)return;
      ctx.strokeStyle=color;ctx.globalAlpha=.7*p;ctx.lineWidth=1.5;
      const yTop=12+(1-p)*(cv.height-32);
      ctx.beginPath();ctx.moveTo(X(ts),yTop);ctx.lineTo(X(ts),cv.height-20);ctx.stroke();
      ctx.globalAlpha=1;
    });
    const visible=p*samples.length;
    latPts=[];
    samples.forEach((q,i)=>{
      if(i>=visible)return;
      const pop=Math.min(1,visible-i);
      const r=1.5+1.5*pop;
      ctx.fillStyle=q.c;ctx.globalAlpha=pop;
      ctx.beginPath();ctx.arc(X(q.t),Y(q.v),r,0,7);ctx.fill();
      ctx.globalAlpha=1;
      latPts.push({x:X(q.t),y:Y(q.v),p:q});
    });
    ctx.fillStyle='#8b95a8';ctx.font='10px monospace';
    ctx.fillText(fmtNs(vmax),4,14);ctx.fillText('0',4,cv.height-22);
    ctx.fillText(fmtTs(t0),40,cv.height-6);
    const te=fmtTs(t1);ctx.fillText(te,cv.width-16-ctx.measureText(te).width,cv.height-6);
  });
}
function latHover(ev){
  const cv=$('#latTl'),r=cv.getBoundingClientRect(),tt=$('#tt');
  const x=(ev.clientX-r.left)*cv.width/r.width,y=(ev.clientY-r.top)*cv.height/r.height;
  let best=null,bd=9;
  for(const q of latPts){const d=Math.hypot(q.x-x,q.y-y);if(d<bd){bd=d;best=q;}}
  if(best){tt.style.display='block';tt.style.left=(ev.clientX+12)+'px';tt.style.top=(ev.clientY+12)+'px';
    tt.textContent=best.p.lab+'\n'+fmtNs(best.p.v)+' @ '+fmtTs(best.p.t);}
  else tt.style.display='none';
}

/* --- packets tab */
function tabPackets(s){
  let h='';
  if(s.packets_truncated)h+='<div class="warnbox">'+fmtInt(s.packets_truncated)+' packet rows omitted from the embedded report (large session) — the sequence ledger and events above remain complete.</div>';
  const multiSrc=M.capture.files&&M.capture.files.length>1;
  h+='<div class="scroll" style="max-height:560px"><table><tr><th>Frame</th><th>Time</th><th>Δ prev</th>'+
   (multiSrc?'<th>Src</th>':'')+'<th>Dir</th>'+
   '<th>SEQ('+SEQMODE+')</th><th>End</th><th>Len</th><th>Flags</th><th>ACK(raw)</th><th>Win(raw)</th><th>SACK</th><th>State</th></tr>';
  s.packets.slice(0,6000).forEach((p,i)=>{
    const dt=i>0?p[1]-s.packets[i-1][1]:null;
    h+='<tr style="--i:'+Math.min(i,30)+'"><td class="num">'+p[0]+'</td><td class="num">'+fmtTs(p[1])+'</td>'+
     '<td class="num" style="color:var(--accent)">'+(dt==null?'-':'+'+fmtNs(dt))+'</td>'+
     (multiSrc?'<td class="num">#'+(p[11]??0)+'</td>':'')+'<td>'+p[2]+'</td>'+
     '<td class="num">'+fmtSeq(s,p[2],p[3])+'</td><td class="num">'+fmtSeq(s,p[2],p[4])+'</td><td class="num">'+p[5]+'</td>'+
     '<td>'+p[6]+'</td><td class="num">'+fmtInt(p[7])+'</td><td class="num">'+fmtInt(p[8])+'</td>'+
     '<td class="num">'+(p[9]||'-')+'</td><td class="state-'+String(p[10]).replace(/ /g,'-')+'">'+ (p[10]||'-')+'</td></tr>';
  });
  return h+'</table></div>';
}

/* ------------------------------------------------------------- exports */
function dl(name,text){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([text],{type:'text/csv'}));
  a.download=name;a.click();URL.revokeObjectURL(a.href);
}
function csv(rows){return rows.map(r=>r.map(v=>{v=v==null?'':String(v);
  return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;}).join(',')).join('\n');}
function exportSessionsCsv(){
  const rows=[['session_id','client','server','start_rel_ns','end_rel_ns','duration_ns','state','partial',
   'payload_bytes','data_segments','retrans_segments','retrans_bytes','retrans_pct','dup_acks','ooo','duplicates',
   'sack_events','sack_blocks','sack_holes','dsack','loss_events','recovered','unrecovered','zero_window',
   'rtt_min_ns','rtt_median_ns','rtt_p95_ns','rtt_p99_ns','rtt_max_ns','rtt_samples']];
  for(const s of M.sessions){const t=s.stats,r=t.rtt;
    rows.push([s.id,s.client,s.server,s.start_ts,s.end_ts,s.duration_ns,s.state,s.partial,
     t.payload_bytes,t.data_segments,t.retrans_segments,t.retrans_bytes,t.retrans_pct.toFixed(4),
     t.dup_acks,t.ooo_packets,t.dup_packets,t.sack_events,t.sack_blocks,t.sack_holes,t.dsack_events,
     t.loss_events,t.recovered_losses,t.unrecovered_losses,t.zero_window_events,
     r.min,r.median,r.p95,r.p99,r.max,r.count]);}
  dl('sessions.csv',csv(rows));
}
function exportLossCsv(){
  const rows=[['loss_id','session','direction','seq','end','bytes','original_tx_rel_ns','evidence_rel_ns','evidence_kind',
   'retrans_rel_ns','recovery_rel_ns','detection_ns','reaction_ns','post_retrans_ns','total_ns',
   'sack','dup_acks','mechanism','classification','recovered']];
  for(const {s,e} of allLoss())
    rows.push([e.loss_id,s.id,e.dir,e.seq,e.end,e.bytes,e.original_tx,e.evidence_ts,e.evidence_kind,
     e.retrans_ts,e.recovery_ts,e.detection_ns,e.reaction_ns,e.post_retrans_ns,e.total_ns,
     e.sack,e.dup_acks,e.mechanism,e.classification,e.recovered]);
  dl('loss_events.csv',csv(rows));
}
function exportRetransCsv(){
  const rows=[['session','frame','ts_rel_ns','direction','seq','end','bytes','classification',
   'original_frame','original_rel_ns','delay_ns','dup_acks_before','sack_active','evidence']];
  for(const s of M.sessions)for(const r of s.retrans_events)
    rows.push([s.id,r.frame,r.ts,r.dir,r.seq,r.end,r.bytes,r.class,r.orig_frame,r.orig_ts,
     r.delay,r.dup_acks,r.sack,r.evidence]);
  dl('retransmissions.csv',csv(rows));
}
function exportRttCsv(){
  const rows=[['session','ts_rel_ns','kind','direction','seq','end','frame_data','frame_ack','rtt_ns']];
  for(const s of M.sessions)for(const r of s.rtt_samples)
    rows.push([s.id,r.ts,r.kind,r.dir,r.seq,r.end,r.frame_data,r.frame_ack,r.rtt]);
  dl('rtt_samples.csv',csv(rows));
}
function exportSackCsv(){
  const rows=[['session','frame','ts_rel_ns','data_direction','cum_ack','n_blocks','blocks','dsack','dsack_reason']];
  for(const s of M.sessions)for(const r of s.sack_records)
    rows.push([s.id,r.frame,r.ts,r.data_dir,r.ack,r.blocks.length,
     r.blocks.map(b=>b[0]+'-'+b[1]).join(';'),r.dsack,r.dsack_reason||'']);
  dl('sack_events.csv',csv(rows));
}
function exportSessionPackets(){
  const s=curSess;if(!s)return;
  const rows=[['frame','ts_rel_ns','direction','seq_rel','end_rel','payload','flags','state',
   'retransmission','retx_kind','retx_of_frame','retx_delay_ns','ack_frame','data_ack_latency_ns','rtt_ns','rtt_ambiguous']];
  for(const g of s.segments)
    rows.push([g.frame,g.ts,g.dir,g.seq,g.end,g.len,g.flags,g.state,g.retx,g.retx_kind||'',
     g.retx_of,g.retx_delay,g.ack_frame,g.ack_lat,g.rtt,g.rtt_ambiguous]);
  dl('session_'+s.id+'_events.csv',csv(rows));
}

/* --------------------------------------------------------------- boot */
function renderAll(){
  renderNav();renderHeader();renderTiles();renderGlobalCharts();
  renderSessFilters();renderSessTable();renderLossTable();
  if(curSess)renderDetail();
}
renderAll();
</script>
</body>
</html>
"""
