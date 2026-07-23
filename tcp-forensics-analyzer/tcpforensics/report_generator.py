"""Self-contained interactive HTML report.

The report consumes the analysis model produced by :mod:`analyzer` — it
performs *no* TCP interpretation of its own.  All CSS/JS is embedded, no
external resources are referenced, and the file opens from disk (file://)
with no server.  CSV exports are generated client-side via Blob URLs.
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
  --bg:#0d1117;--panel:#161b22;--panel2:#1c2129;--border:#2d333b;
  --fg:#c9d1d9;--dim:#8b949e;--accent:#58a6ff;--ok:#3fb950;--warn:#d29922;
  --bad:#f85149;--purple:#bc8cff;--orange:#f0883e;--mono:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.45 var(--mono)}
h1,h2,h3{font-weight:600;margin:.4em 0}
h1{font-size:18px}h2{font-size:15px;color:var(--accent)}h3{font-size:13px;color:var(--dim)}
a{color:var(--accent);cursor:pointer;text-decoration:none}
.wrap{max-width:1500px;margin:0 auto;padding:14px}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:14px}
.tiles{display:flex;flex-wrap:wrap;gap:10px}
.tile{background:var(--panel2);border:1px solid var(--border);border-radius:6px;padding:10px 14px;min-width:130px}
.tile .v{font-size:17px;font-weight:700;color:#e6edf3}
.tile .l{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.04em}
.tile.bad .v{color:var(--bad)}.tile.warn .v{color:var(--warn)}.tile.ok .v{color:var(--ok)}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border-bottom:1px solid var(--border);padding:4px 8px;text-align:left;white-space:nowrap}
th{color:var(--dim);cursor:pointer;user-select:none;position:sticky;top:0;background:var(--panel)}
tr.clickable:hover{background:var(--panel2);cursor:pointer}
.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow:auto;max-height:480px;border:1px solid var(--border);border-radius:4px}
.badge{display:inline-block;border-radius:10px;padding:1px 8px;font-size:11px;margin:1px 2px;border:1px solid}
.b-ok{color:var(--ok);border-color:var(--ok)}
.b-warn{color:var(--warn);border-color:var(--warn)}
.b-bad{color:var(--bad);border-color:var(--bad)}
.b-info{color:var(--accent);border-color:var(--accent)}
.controls{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;align-items:center}
.controls input,.controls select,button{background:var(--panel2);color:var(--fg);
  border:1px solid var(--border);border-radius:4px;padding:4px 8px;font:12px var(--mono)}
.controls label{color:var(--dim);font-size:11px}
button{cursor:pointer}button:hover{border-color:var(--accent)}
button.primary{border-color:var(--accent);color:var(--accent)}
.tabs{display:flex;gap:2px;flex-wrap:wrap;border-bottom:1px solid var(--border);margin-bottom:10px}
.tabs div{padding:6px 14px;cursor:pointer;color:var(--dim);border:1px solid transparent;border-bottom:none;border-radius:5px 5px 0 0}
.tabs div.active{color:var(--accent);background:var(--panel2);border-color:var(--border)}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:2px 16px;font-size:12px}
.kv .k{color:var(--dim)}
canvas{background:var(--panel2);border:1px solid var(--border);border-radius:4px;max-width:100%}
.state-Original{color:var(--fg)}.state-ACKed{color:var(--ok)}.state-SACKed{color:var(--purple)}
.state-Retransmitted{color:var(--bad)}.state-Duplicate{color:var(--orange)}
.state-Out-of-order{color:var(--warn)}.state-Recovered{color:var(--ok)}
.state-Ambiguous,.state-Missing{color:var(--warn)}
.tooltip{position:fixed;background:#000c;border:1px solid var(--border);border-radius:4px;
  padding:6px 8px;font-size:11px;pointer-events:none;z-index:99;white-space:pre;display:none}
.warnbox{border-left:3px solid var(--warn);padding:6px 10px;margin:6px 0;background:var(--panel2);font-size:12px}
.verdict{border-left:3px solid var(--border);padding:6px 10px;margin:6px 0;background:var(--panel2)}
.verdict.ok{border-color:var(--ok)}.verdict.warn{border-color:var(--warn)}
.verdict.bad{border-color:var(--bad)}.verdict.info{border-color:var(--accent)}
.verdict .ev{color:var(--dim);font-size:12px;margin-top:2px;white-space:normal}
.mut{color:var(--dim)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:1000px){.grid2{grid-template-columns:1fr}}
#detail{display:none}
.legend span{margin-right:14px;font-size:11px}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:middle}
</style>
</head>
<body>
<div class="tooltip" id="tt"></div>
<div class="wrap">
  <div class="panel" id="hdr"></div>
  <div class="panel"><div class="tiles" id="tiles"></div></div>
  <div class="panel" id="latPanel">
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
  <div class="panel">
    <h2>Session Explorer</h2>
    <div class="controls" id="sessFilters"></div>
    <div class="scroll" style="max-height:420px"><table id="sessTable"></table></div>
  </div>
  <div class="panel">
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
let UNIT = 'ns';           // ns | us | ms
let curSess = null, curTab = 'overview';

/* ---------------------------------------------------------- formatting */
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function fmtInt(n){return n==null?'-':Number(n).toLocaleString('en-US');}
function fmtNs(ns){ // duration in the selected unit; underlying value stays integer ns
  if(ns==null)return '-';
  if(UNIT==='ns')return fmtInt(ns)+' ns';
  if(UNIT==='us')return (ns/1000).toLocaleString('en-US',{maximumFractionDigits:3})+' µs';
  return (ns/1e6).toLocaleString('en-US',{maximumFractionDigits:6})+' ms';
}
function fmtTs(ns){ // absolute -> relative to capture start, full ns precision
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
  return b+' B';
}
function pct(x){return x==null?'-':x.toFixed(2)+'%';}
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
   '<div class="k">Capture file</div><div>'+esc(c.path)+' <span class="mut">('+esc(c.format)+')</span></div>'+
   '<div class="k">Capture point</div><div>'+esc(c.capture_point)+' <span class="mut">capture_id='+c.capture_id+'</span></div>'+
   '<div class="k">Timestamp precision</div><div>'+precNote+'</div>'+
   '<div class="k">First packet</div><div>'+esc(c.first_ts_str)+' UTC</div>'+
   '<div class="k">Last packet</div><div>'+esc(c.last_ts_str)+' UTC</div>'+
   '<div class="k">Duration</div><div>'+esc(c.duration_str)+'</div>'+
   '<div class="k">Packets</div><div>'+fmtInt(c.packets)+' total, '+fmtInt(c.tcp_packets)+' TCP'+
     (c.truncated_frames?' <span class="b-warn badge">'+fmtInt(c.truncated_frames)+' truncated by snaplen</span>':'')+'</div>'+
   '<div class="k">Display unit</div><div>'+
     ['ns','us','ms'].map(u=>'<button '+(UNIT===u?'class="primary"':'')+
       ' onclick="setUnit(\''+u+'\')">'+(u==='us'?'µs':u)+'</button>').join(' ')+
     ' <span class="mut">display only &mdash; internal values remain integer nanoseconds</span></div>'+
   '</div>'+
   '<div class="mut" style="margin-top:6px">'+esc(M.tool.name)+' v'+esc(M.tool.version)+'</div>';
}
function setUnit(u){UNIT=u;renderAll();}

/* -------------------------------------------------------------- tiles */
function tile(label,val,cls){return '<div class="tile '+(cls||'')+'"><div class="v">'+val+'</div><div class="l">'+label+'</div></div>';}
function renderTiles(){
  const t=M.totals,r=M.rtt_summary,rec=M.recovery_summary;
  $('#tiles').innerHTML =
    tile('Sessions',fmtInt(t.sessions))+
    tile('TCP packets',fmtInt(t.tcp_packets))+
    tile('TCP payload',fmtBytes(t.payload_bytes))+
    tile('Retransmissions',fmtInt(t.retrans_segments),t.retrans_segments?'warn':'ok')+
    tile('Retrans %',pct(t.retrans_pct),t.retrans_pct>2?'bad':t.retrans_pct>0.5?'warn':'ok')+
    tile('SACK events',fmtInt(t.sack_events))+
    tile('DSACK',fmtInt(t.dsack_events))+
    tile('Loss events',fmtInt(t.loss_events),t.loss_events?'warn':'ok')+
    tile('Dup ACKs',fmtInt(t.dup_acks))+
    tile('Out-of-order',fmtInt(t.ooo_packets))+
    tile('Zero-window',fmtInt(t.zero_window_events),t.zero_window_events?'bad':'ok')+
    tile('Median RTT',fmtNs(r.median))+
    tile('P95 RTT',fmtNs(r.p95))+
    tile('P99 RTT',fmtNs(r.p99))+
    tile('Max RTT',fmtNs(r.max))+
    tile('Median recovery',fmtNs(rec.median))+
    tile('P95 recovery',fmtNs(rec.p95))+
    tile('Max recovery',fmtNs(rec.max));
}

/* ------------------------------------------------------------- charts */
function drawHist(canvas,h,color){
  const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
  if(!h||!h.counts||!h.counts.length){ctx.fillStyle='#8b949e';ctx.fillText('no samples',10,20);return;}
  const W=canvas.width,H=canvas.height,pad=34,max=Math.max(...h.counts);
  const bw=(W-pad-8)/h.counts.length;
  ctx.fillStyle=color||'#58a6ff';
  h.counts.forEach((c,i)=>{const bh=max?(H-26)*c/max:0;
    ctx.fillRect(pad+i*bw,H-18-bh,Math.max(1,bw-1),bh);});
  ctx.fillStyle='#8b949e';ctx.font='10px monospace';
  ctx.fillText(fmtNs(h.buckets[0]),pad,H-5);
  const last=fmtNs(h.buckets[h.buckets.length-1]);
  ctx.fillText(last,W-8-ctx.measureText(last).width,H-5);
  ctx.save();ctx.translate(10,H/2);ctx.rotate(-Math.PI/2);ctx.fillText('count',0,0);ctx.restore();
  ctx.fillText('max '+max,pad,12);
}
function drawCdf(canvas,h,color){
  const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
  if(!h||!h.cdf||!h.cdf.length){ctx.fillStyle='#8b949e';ctx.fillText('no samples',10,20);return;}
  const W=canvas.width,H=canvas.height,pad=34;
  const xs=h.cdf.map(p=>p[0]);const lo=xs[0],hi=xs[xs.length-1]||1;
  const X=v=>pad+(hi>lo?(v-lo)/(hi-lo):0)*(W-pad-8);
  const Y=p=>H-16-(p/100)*(H-28);
  ctx.strokeStyle=color||'#58a6ff';ctx.beginPath();
  h.cdf.forEach((p,i)=>{i?ctx.lineTo(X(p[0]),Y(p[1])):ctx.moveTo(X(p[0]),Y(p[1]));});
  ctx.stroke();
  ctx.strokeStyle='#2d333b';[50,90,95,99].forEach(p=>{ctx.beginPath();ctx.moveTo(pad,Y(p));ctx.lineTo(W-8,Y(p));ctx.stroke();});
  ctx.fillStyle='#8b949e';ctx.font='10px monospace';
  [50,90,99].forEach(p=>ctx.fillText('P'+p,2,Y(p)+3));
  ctx.fillText('CDF',pad,10);ctx.fillText(fmtNs(lo),pad,H-4);
  const last=fmtNs(hi);ctx.fillText(last,W-8-ctx.measureText(last).width,H-4);
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
  drawHist($('#gRttHist'),M.rtt_hist,'#58a6ff');drawCdf($('#gRttCdf'),M.rtt_hist,'#58a6ff');
  drawHist($('#gRecHist'),M.recovery_hist,'#f0883e');drawCdf($('#gRecCdf'),M.recovery_hist,'#f0883e');
}

/* -------------------------------------------------- session explorer */
const F={};   // filter state
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
  for(const s of rows){
    h+='<tr class="clickable" onclick="openSession('+s.id+')"><td>'+s.label+
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
      '<td>'+esc(s.state)+'</td></tr>';
  }
  $('#sessTable').innerHTML=h+(rows.length?'':'<tr><td colspan="16" class="mut">no sessions match the filters</td></tr>');
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
  for(const {s,e} of allLoss()){
    h+='<tr class="clickable" onclick="openSession('+s.id+',\'loss\')">'+
     '<td>'+esc(e.loss_id)+'</td><td>#'+s.id+'</td><td>'+e.dir+'</td>'+
     '<td class="num">'+fmtInt(e.seq)+'–'+fmtInt(e.end)+'</td>'+
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
  }
  $('#lossTable').innerHTML=h+(allLoss().length?'':'<tr><td colspan="16" class="mut">no loss events</td></tr>');
}

/* -------------------------------------------------------- session view */
function openSession(id,tab){
  curSess=M.sessions.find(s=>s.id===id);curTab=tab||'overview';
  renderDetail();
  $('#detail').scrollIntoView({behavior:'smooth'});
}
const TABS=[['overview','Overview'],['sequence','Sequence'],['ack','ACK'],['sack','SACK'],
 ['loss','Loss'],['retrans','Retransmissions'],['rtt','RTT'],['window','Window'],
 ['timeline','Timeline'],['packets','Packets']];
function renderDetail(){
  const s=curSess;if(!s){$('#detail').style.display='none';return;}
  $('#detail').style.display='block';
  let h='<h2>'+s.label+' &mdash; '+esc(s.client)+' ⇄ '+esc(s.server)+'</h2>';
  h+='<div class="tabs">'+TABS.map(t=>'<div class="'+(curTab===t[0]?'active':'')+
    '" onclick="switchTab(\''+t[0]+'\')">'+t[1]+'</div>').join('')+'</div>';
  h+='<div id="tabBody"></div>';
  $('#detail').innerHTML=h;
  renderTab();
}
function switchTab(t){curTab=t;renderDetail();}
function renderTab(){
  const body=$('#tabBody'),s=curSess;
  const fn={overview:tabOverview,sequence:tabSequence,ack:tabAck,sack:tabSack,
    loss:tabLoss,retrans:tabRetrans,rtt:tabRtt,window:tabWindow,
    timeline:tabTimeline,packets:tabPackets}[curTab];
  body.innerHTML=fn(s);
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
   ['Out-of-order','ooo_packets'],['Duplicates','dup_packets'],['SACK events','sack_events'],
   ['SACK blocks','sack_blocks'],['SACK holes','sack_holes'],['DSACK','dsack_events'],
   ['Zero-window','zero_window_events'],['MSS','mss'],['Window scale','window_scale']];
  for(const [lab,k] of rows)h+='<tr><td class="mut">'+lab+'</td><td class="num">'+fmtInt(s.dir_a[k])+'</td><td class="num">'+fmtInt(s.dir_b[k])+'</td></tr>';
  h+='</table></div></div>';
  h+='<h3>Automated verdicts <span class="mut">(thresholds: '+esc(JSON.stringify(M.verdict_config))+')</span></h3>';
  for(const v of s.verdicts)h+='<div class="verdict '+v.severity+'"><b>'+esc(v.verdict)+'</b><div class="ev">'+esc(v.evidence)+'</div></div>';
  if(s.warnings.length){h+='<h3>Capture artifact warnings</h3>';
    for(const w of s.warnings)h+='<div class="warnbox">⚠ '+esc(w)+'</div>';}
  return h;
}

/* --- sequence ledger */
function tabSequence(s){
  let h='<div class="controls"><label>search SEQ <input id="seqSearch" size="12" oninput="renderSeqRows()"></label>'+
   '<label>direction <select id="seqDir" onchange="renderSeqRows()"><option value="">both</option><option>A-&gt;B</option><option>B-&gt;A</option></select></label>'+
   '<label>state <select id="seqState" onchange="renderSeqRows()"><option value="">all</option>'+
   ['Original','ACKed','SACKed','Retransmitted','Duplicate','Out-of-order','Recovered'].map(x=>'<option>'+x+'</option>').join('')+'</select></label>'+
   '<button onclick="exportSessionPackets()">Export session events CSV</button></div>'+
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
  if(q!==''&&!isNaN(+q)){const v=+q;rows=rows.filter(r=>r.seq<=v&&v<r.end||r.seq===v||r.end===v);}
  let h='<tr><th>Time</th><th>Frame</th><th>Dir</th><th>SEQ start</th><th>SEQ end</th><th>NEXTSEQ</th>'+
   '<th>Len</th><th>Flags</th><th>State</th><th>Orig frame</th><th>Retx delay</th>'+
   '<th>ACKed by</th><th>DATA→ACK</th><th>RTT</th><th>SACKed by</th></tr>';
  for(const r of rows.slice(0,4000)){
    h+='<tr><td class="num">'+fmtTs(r.ts)+'</td><td class="num">'+r.frame+'</td><td>'+r.dir+'</td>'+
     '<td class="num">'+fmtInt(r.seq)+'</td><td class="num">'+fmtInt(r.end)+'</td><td class="num">'+fmtInt(r.end)+'</td>'+
     '<td class="num">'+r.len+'</td><td>'+r.flags+'</td>'+
     '<td class="state-'+r.state.replace(/ /g,'-')+'">'+r.state+(r.retx_kind?' <span class="mut">('+r.retx_kind+')</span>':'')+'</td>'+
     '<td class="num">'+(r.retx_of??'-')+'</td><td class="num">'+fmtNs(r.retx_delay)+'</td>'+
     '<td class="num">'+(r.ack_frame??'-')+'</td><td class="num">'+fmtNs(r.ack_lat)+'</td>'+
     '<td class="num">'+(r.rtt_ambiguous?'<span class="b-warn">AMBIGUOUS</span>':fmtNs(r.rtt))+'</td>'+
     '<td class="num">'+(r.sack_frame??'-')+'</td></tr>';
  }
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
  for(const t of s.dup_ack_trains){
    h+='<tr><td>'+t.dir+'</td><td class="num">'+fmtInt(t.ack)+'</td><td class="num">'+t.first_frame+'</td>'+
     '<td class="num">'+fmtTs(t.first_ts)+'</td><td class="num">'+t.count+'</td>'+
     '<td class="num">'+t.gaps_ns.slice(0,6).map(g=>fmtNs(g)).join(', ')+(t.gaps_ns.length>6?' …':'')+'</td>'+
     '<td class="num">'+t.sack_blocks+'</td>'+
     '<td class="num">'+(t.missing_seq!=null?fmtInt(t.missing_seq)+'–'+fmtInt(t.missing_end):'-')+'</td>'+
     '<td class="num">'+(t.retrans_frame??'-')+'</td><td class="num">'+fmtNs(t.time_to_retrans)+'</td>'+
     '<td class="num">'+fmtNs(t.time_to_recovery)+'</td></tr>';
  }
  if(!s.dup_ack_trains.length)h+='<tr><td colspan="11" class="mut">no duplicate ACK trains</td></tr>';
  return h+'</table></div>';
}
function postAck(s){drawHist($('#ackHist'),s.ack_hist,'#3fb950');}

/* --- SACK tab */
function tabSack(s){
  let h='<div class="kv">'+
   '<div class="k">SACK client</div><div>'+tri(s.sack_client)+'</div>'+
   '<div class="k">SACK server</div><div>'+tri(s.sack_server)+'</div>'+
   '<div class="k">SACK active</div><div>'+tri(s.sack_active)+'</div></div>';
  for(const dir of ['A->B','B->A']){
    const snaps=s.sack_snapshots[dir]||[];
    if(!snaps.length)continue;
    const id=dir==='A->B'?'ab':'ba';
    h+='<h3>SACK scoreboard — data direction '+dir+' <span class="mut">('+snaps.length+' SACK events; step chronologically)</span></h3>'+
     '<div class="controls"><button onclick="sbStep(\''+id+'\',-1)">◀ prev</button>'+
     '<input type="range" id="sb_'+id+'" min="0" max="'+(snaps.length-1)+'" value="0" style="width:340px" oninput="sbDraw(\''+id+'\')">'+
     '<button onclick="sbStep(\''+id+'\',1)">next ▶</button><span id="sbInfo_'+id+'" class="mut"></span></div>'+
     '<canvas id="sbCanvas_'+id+'" width="1100" height="110"></canvas>'+
     '<div class="legend"><span><span class="dot" style="background:#3fb950"></span>cumulatively ACKed</span>'+
     '<span><span class="dot" style="background:#bc8cff"></span>SACKed</span>'+
     '<span><span class="dot" style="background:#f85149"></span>hole / missing</span>'+
     '<span><span class="dot" style="background:#30363d"></span>outstanding</span></div>';
  }
  h+='<h3>SACK option records</h3><div class="scroll" style="max-height:320px"><table><tr>'+
   '<th>Frame</th><th>Time</th><th>Data dir</th><th>Cum ACK</th><th>#Blocks</th><th>Blocks (left–right)</th><th>DSACK</th></tr>';
  for(const r of s.sack_records.slice(0,3000)){
    h+='<tr><td class="num">'+r.frame+'</td><td class="num">'+fmtTs(r.ts)+'</td><td>'+r.data_dir+'</td>'+
     '<td class="num">'+fmtInt(r.ack)+'</td><td class="num">'+r.blocks.length+'</td>'+
     '<td class="num">'+r.blocks.map(b=>fmtInt(b[0])+'–'+fmtInt(b[1])).join(' | ')+'</td>'+
     '<td>'+(r.dsack?'<span class="badge b-warn">DSACK</span> <span class="mut">'+esc(r.dsack_reason||'')+'</span>':'-')+'</td></tr>';
  }
  if(!s.sack_records.length)h+='<tr><td colspan="7" class="mut">no SACK options observed</td></tr>';
  return h+'</table></div>';
}
function postSack(s){for(const id of ['ab','ba'])if($('#sb_'+id))sbDraw(id);}
function sbStep(id,d){const el=$('#sb_'+id);el.value=Math.max(0,Math.min(+el.max,+el.value+d));sbDraw(id);}
function sbDraw(id){
  const dir=id==='ab'?'A->B':'B->A';
  const snaps=curSess.sack_snapshots[dir];const i=+$('#sb_'+id).value;const sn=snaps[i];
  $('#sbInfo_'+id).textContent=' event '+(i+1)+'/'+snaps.length+' frame '+sn.frame+' '+fmtTs(sn.ts)+
    ' ACK='+fmtInt(sn.ack)+(sn.dsack?' [DSACK]':'')+(sn.ack_advanced?' [ACK advanced]':'');
  const cv=$('#sbCanvas_'+id),ctx=cv.getContext('2d');
  ctx.clearRect(0,0,cv.width,cv.height);
  let lo=sn.ack,hi=sn.ack+1;
  for(const [a,b] of sn.sacked){lo=Math.min(lo,a);hi=Math.max(hi,b);}
  for(const [a,b] of sn.holes){lo=Math.min(lo,a);hi=Math.max(hi,b);}
  lo=Math.min(lo,Math.max(0,sn.ack-(hi-lo)*0.15));
  const X=v=>30+(hi>lo?(v-lo)/(hi-lo):0)*(cv.width-60);
  ctx.fillStyle='#30363d';ctx.fillRect(30,40,cv.width-60,28);
  ctx.fillStyle='#3fb950';ctx.fillRect(30,40,Math.max(0,X(sn.ack)-30),28);
  for(const [a,b] of sn.sacked){ctx.fillStyle='#bc8cff';ctx.fillRect(X(a),40,Math.max(2,X(b)-X(a)),28);}
  for(const [a,b] of sn.holes){ctx.fillStyle='#f85149';ctx.fillRect(X(a),40,Math.max(2,X(b)-X(a)),28);}
  ctx.fillStyle='#8b949e';ctx.font='10px monospace';
  ctx.fillText(fmtInt(lo),30,90);const t2=fmtInt(hi);ctx.fillText(t2,cv.width-30-ctx.measureText(t2).width,90);
  ctx.fillStyle='#c9d1d9';ctx.fillText('ACK '+fmtInt(sn.ack),Math.min(cv.width-90,Math.max(30,X(sn.ack))),30);
  ctx.strokeStyle='#c9d1d9';ctx.beginPath();ctx.moveTo(X(sn.ack),34);ctx.lineTo(X(sn.ack),72);ctx.stroke();
  for(const [a,b] of sn.holes){ctx.fillStyle='#f85149';
    ctx.fillText('hole '+fmtInt(a)+'–'+fmtInt(b),Math.max(30,Math.min(cv.width-160,X(a))),105);}
}

/* --- loss tab */
function tabLoss(s){
  let h='<div>'+statLine(s.stats.recovery)+' <span class="mut">(total recovery: original TX → recovery ACK)</span></div>'+
   '<canvas id="recHist" width="700" height="150"></canvas>'+
   '<div class="scroll" style="max-height:460px"><table><tr><th>Loss ID</th><th>Dir</th><th>SEQ range</th><th>Bytes</th>'+
   '<th>Original TX</th><th>Evidence</th><th>Retrans</th><th>Recovery</th>'+
   '<th>Detection</th><th>Reaction</th><th>Post-retx</th><th>Total</th>'+
   '<th>Mechanism</th><th>SACK reports</th><th>DupACKs</th><th>Extra holes</th><th>Class</th><th></th></tr>';
  for(const e of s.loss_events){
    h+='<tr><td>'+esc(e.loss_id)+'</td><td>'+e.dir+'</td>'+
     '<td class="num">'+fmtInt(e.seq)+'–'+fmtInt(e.end)+'</td><td class="num">'+e.bytes+'</td>'+
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
  }
  if(!s.loss_events.length)h+='<tr><td colspan="18" class="mut">no loss events</td></tr>';
  setTimeout(()=>drawHist($('#recHist'),s.recovery_hist,'#f0883e'),0);
  return h+'</table></div>';
}
function jumpToSeq(seq){switchTab('sequence');setTimeout(()=>{$('#seqSearch').value=seq;renderSeqRows();},50);}

/* --- retransmissions tab */
function tabRetrans(s){
  let h='<div class="scroll" style="max-height:520px"><table><tr><th>Frame</th><th>Time</th><th>Dir</th>'+
   '<th>SEQ range</th><th>Bytes</th><th>Classification</th><th>Original</th><th>Delay</th>'+
   '<th>DupACKs before</th><th>SACK</th><th>Evidence</th></tr>';
  for(const r of s.retrans_events){
    h+='<tr><td class="num">'+r.frame+'</td><td class="num">'+fmtTs(r.ts)+'</td><td>'+r.dir+'</td>'+
     '<td class="num">'+fmtInt(r.seq)+'–'+fmtInt(r.end)+'</td><td class="num">'+r.bytes+'</td>'+
     '<td class="state-Retransmitted">'+esc(r.class)+'</td>'+
     '<td class="num">'+(r.orig_frame?'#'+r.orig_frame+' '+fmtTs(r.orig_ts):'-')+'</td>'+
     '<td class="num">'+fmtNs(r.delay)+'</td><td class="num">'+r.dup_acks+'</td>'+
     '<td>'+(r.sack?'yes':'no')+'</td><td style="white-space:normal;max-width:420px">'+esc(r.evidence)+'</td></tr>';
  }
  if(!s.retrans_events.length)h+='<tr><td colspan="11" class="mut">no retransmissions</td></tr>';
  return h+'</table></div>';
}

/* --- RTT tab */
function tabRtt(s){
  let h='<div>'+statLine(s.stats.rtt)+' <span class="mut">valid samples only (Karn); '+
    s.rtt_ambiguous.length+' ambiguous samples excluded</span></div>'+
   '<canvas id="rttHist" width="700" height="170"></canvas><canvas id="rttCdf" width="700" height="150"></canvas>'+
   '<h3>Valid RTT samples</h3><div class="scroll" style="max-height:280px"><table><tr>'+
   '<th>Time</th><th>Kind</th><th>Dir</th><th>SEQ range</th><th>Data frame</th><th>ACK frame</th><th>RTT</th></tr>';
  for(const r of s.rtt_samples.slice(0,3000)){
    h+='<tr><td class="num">'+fmtTs(r.ts)+'</td><td>'+r.kind+'</td><td>'+r.dir+'</td>'+
     '<td class="num">'+fmtInt(r.seq)+'–'+fmtInt(r.end)+'</td>'+
     '<td class="num">'+r.frame_data+'</td><td class="num">'+r.frame_ack+'</td>'+
     '<td class="num">'+fmtNs(r.rtt)+'</td></tr>';
  }
  h+='</table></div>';
  if(s.rtt_ambiguous.length){
    h+='<h3>RTT AMBIGUOUS (excluded, retained for forensics)</h3><div class="scroll" style="max-height:200px"><table><tr>'+
     '<th>ACK time</th><th>Dir</th><th>SEQ range</th><th>Data frame</th><th>ACK frame</th><th>Reason</th></tr>';
    for(const r of s.rtt_ambiguous)
      h+='<tr><td class="num">'+fmtTs(r.ts)+'</td><td>'+r.dir+'</td><td class="num">'+fmtInt(r.seq)+'–'+fmtInt(r.end)+'</td>'+
       '<td class="num">'+r.frame_data+'</td><td class="num">'+r.frame_ack+'</td><td style="white-space:normal">'+esc(r.reason)+'</td></tr>';
    h+='</table></div>';
  }
  return h;
}
function postRtt(s){drawHist($('#rttHist'),s.rtt_hist,'#58a6ff');drawCdf($('#rttCdf'),s.rtt_hist,'#58a6ff');}

/* --- window tab */
function tabWindow(s){
  let h='<div class="kv">'+
   '<div class="k">A&rarr;B advertised window</div><div>min '+fmtInt(s.dir_a.window_min)+' / max '+fmtInt(s.dir_a.window_max)+' bytes (scale '+fmtInt(s.dir_a.window_scale)+')</div>'+
   '<div class="k">B&rarr;A advertised window</div><div>min '+fmtInt(s.dir_b.window_min)+' / max '+fmtInt(s.dir_b.window_max)+' bytes (scale '+fmtInt(s.dir_b.window_scale)+')</div></div>'+
   '<div class="scroll" style="max-height:420px"><table><tr><th>Time</th><th>Frame</th><th>Advertiser dir</th><th>Kind</th><th>Window</th><th>Detail</th></tr>';
  for(const w of s.window_events)
    h+='<tr><td class="num">'+fmtTs(w.ts)+'</td><td class="num">'+w.frame+'</td><td>'+w.dir+'</td>'+
     '<td>'+esc(w.kind)+'</td><td class="num">'+fmtInt(w.window)+'</td><td style="white-space:normal">'+esc(w.detail)+'</td></tr>';
  if(!s.window_events.length)h+='<tr><td colspan="6" class="mut">no window events</td></tr>';
  return h+'</table></div>';
}

/* --- timeline tab: ladder + latency time-series */
function tabTimeline(s){
  const n=s.packets.length;
  return '<h3>Sequence ladder ('+esc(s.ep_a)+' left, '+esc(s.ep_b)+' right) — click an arrow for full details</h3>'+
   '<div class="controls"><label>window start <input type="range" id="tlStart" min="0" max="'+Math.max(0,n-1)+'" value="0" style="width:320px" oninput="drawLadder()"></label>'+
   '<label>events <select id="tlCount" onchange="drawLadder()"><option>30</option><option selected>60</option><option>120</option><option>250</option></select></label>'+
   '<span id="tlInfo" class="mut"></span></div>'+
   '<canvas id="ladder" width="1100" height="600" onclick="ladderClick(event)" onmousemove="ladderHover(event)"></canvas>'+
   '<div id="ladderDetail" class="warnbox" style="display:none;border-color:var(--accent)"></div>'+
   '<h3>Latency timeline — RTT / DATA→ACK samples with loss, retransmission, dup-ACK and zero-window markers</h3>'+
   '<div class="legend"><span><span class="dot" style="background:#58a6ff"></span>RTT sample</span>'+
   '<span><span class="dot" style="background:#3fb950"></span>DATA→ACK</span>'+
   '<span><span class="dot" style="background:#f85149"></span>retransmission</span>'+
   '<span><span class="dot" style="background:#f0883e"></span>loss evidence</span>'+
   '<span><span class="dot" style="background:#d29922"></span>dup-ACK train</span>'+
   '<span><span class="dot" style="background:#bc8cff"></span>zero-window</span></div>'+
   '<canvas id="latTl" width="1100" height="260" onmousemove="latHover(event)"></canvas>';
}
let ladderRows=[];
function postTimeline(s){drawLadder();drawLatTimeline(s);}
function drawLadder(){
  const s=curSess,cv=$('#ladder'),ctx=cv.getContext('2d');
  const start=+($('#tlStart')?.value||0),count=+($('#tlCount')?.value||60);
  const rows=s.packets.slice(start,start+count);
  ladderRows=[];
  ctx.clearRect(0,0,cv.width,cv.height);
  const L=180,R=cv.width-180,top=30,step=Math.max(9,(cv.height-60)/Math.max(1,rows.length));
  ctx.strokeStyle='#2d333b';
  ctx.beginPath();ctx.moveTo(L,top-14);ctx.lineTo(L,cv.height-10);ctx.moveTo(R,top-14);ctx.lineTo(R,cv.height-10);ctx.stroke();
  ctx.fillStyle='#c9d1d9';ctx.font='11px monospace';
  ctx.fillText(s.ep_a,L-ctx.measureText(s.ep_a).width/2,14);
  ctx.fillText(s.ep_b,R-ctx.measureText(s.ep_b).width/2,14);
  $('#tlInfo').textContent=' showing '+(start+1)+'–'+(start+rows.length)+' of '+s.packets.length+' packets';
  rows.forEach((p,i)=>{
    const y=top+i*step;
    const [frame,ts,dir,seq,end,len,flags,ack,win,sackn,state]=p;
    const l2r=dir==='A->B';
    let color='#8b949e';
    if(state==='Retransmitted')color='#f85149';
    else if(state==='Duplicate')color='#f0883e';
    else if(state==='Out-of-order')color='#d29922';
    else if(len>0)color='#58a6ff';
    else if(sackn>0)color='#bc8cff';
    else if(flags.includes('SYN')||flags.includes('FIN')||flags.includes('RST'))color='#e6edf3';
    ctx.strokeStyle=color;ctx.fillStyle=color;
    ctx.beginPath();ctx.moveTo(l2r?L:R,y);ctx.lineTo(l2r?R:L,y);ctx.stroke();
    const hx=l2r?R:L,dx=l2r?-7:7;
    ctx.beginPath();ctx.moveTo(hx,y);ctx.lineTo(hx+dx,y-4);ctx.lineTo(hx+dx,y+4);ctx.closePath();ctx.fill();
    let lab=flags;
    if(len>0)lab='SEQ '+fmtInt(seq)+'–'+fmtInt(end)+' ('+len+'B) '+flags;
    else if(ack!=null)lab='ACK'+(sackn?'+SACK×'+sackn:'')+' '+flags;
    if(state==='Retransmitted')lab+=' [RETX]';
    if(state==='Out-of-order')lab+=' [OOO]';
    ctx.fillText(lab,(L+R)/2-ctx.measureText(lab).width/2,y-3);
    ctx.fillStyle='#8b949e';
    const tsl=fmtTs(ts);ctx.fillText(tsl,8,y+3);
    ladderRows.push({y,p});
  });
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
   'SEQ '+fmtInt(seq)+' → NEXTSEQ '+fmtInt(end)+' | payload '+len+' B | flags '+esc(flags)+
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
  const cv=$('#latTl'),ctx=cv.getContext('2d');ctx.clearRect(0,0,cv.width,cv.height);
  latPts=[];
  const t0=s.start_ts,t1=Math.max(s.end_ts,t0+1);
  const samples=s.rtt_samples.map(r=>({t:r.ts,v:r.rtt,c:'#58a6ff',lab:'RTT '+r.kind}));
  for(const g of s.segments)if(g.ack_lat!=null&&g.ack_lat>=0)samples.push({t:g.acked_ts,v:g.ack_lat,c:'#3fb950',lab:'DATA→ACK frame '+g.frame});
  const vmax=Math.max(1,...samples.map(p=>p.v));
  const X=t=>40+(t-t0)/(t1-t0)*(cv.width-56);
  const Y=v=>cv.height-24-(v/vmax)*(cv.height-46);
  // event markers
  function mark(ts,color){if(ts==null)return;ctx.strokeStyle=color;ctx.globalAlpha=.7;
    ctx.beginPath();ctx.moveTo(X(ts),12);ctx.lineTo(X(ts),cv.height-20);ctx.stroke();ctx.globalAlpha=1;}
  for(const r of s.retrans_events)mark(r.ts,'#f85149');
  for(const e of s.loss_events)mark(e.evidence_ts,'#f0883e');
  for(const t of s.dup_ack_trains)if(t.count>=3)mark(t.first_ts,'#d29922');
  for(const w of s.window_events)if(w.kind==='zero-window')mark(w.ts,'#bc8cff');
  for(const p of samples){ctx.fillStyle=p.c;ctx.fillRect(X(p.t)-1.5,Y(p.v)-1.5,3,3);latPts.push({x:X(p.t),y:Y(p.v),p});}
  ctx.fillStyle='#8b949e';ctx.font='10px monospace';
  ctx.fillText(fmtNs(vmax),4,14);ctx.fillText('0',4,cv.height-22);
  ctx.fillText(fmtTs(t0),40,cv.height-6);
  const te=fmtTs(t1);ctx.fillText(te,cv.width-16-ctx.measureText(te).width,cv.height-6);
}
function latHover(ev){
  const cv=$('#latTl'),r=cv.getBoundingClientRect(),tt=$('#tt');
  const x=(ev.clientX-r.left)*cv.width/r.width,y=(ev.clientY-r.top)*cv.height/r.height;
  let best=null,bd=8;
  for(const q of latPts){const d=Math.hypot(q.x-x,q.y-y);if(d<bd){bd=d;best=q;}}
  if(best){tt.style.display='block';tt.style.left=(ev.clientX+12)+'px';tt.style.top=(ev.clientY+12)+'px';
    tt.textContent=best.p.lab+'\n'+fmtNs(best.p.v)+' @ '+fmtTs(best.p.t);}
  else tt.style.display='none';
}

/* --- packets tab */
function tabPackets(s){
  let h='';
  if(s.packets_truncated)h+='<div class="warnbox">'+fmtInt(s.packets_truncated)+' packet rows omitted from the embedded report (large session) — the sequence ledger and events above remain complete.</div>';
  h+='<div class="scroll" style="max-height:560px"><table><tr><th>Frame</th><th>Time</th><th>Dir</th>'+
   '<th>SEQ(rel)</th><th>End</th><th>Len</th><th>Flags</th><th>ACK(raw)</th><th>Win(raw)</th><th>SACK</th><th>State</th></tr>';
  for(const p of s.packets.slice(0,6000)){
    h+='<tr><td class="num">'+p[0]+'</td><td class="num">'+fmtTs(p[1])+'</td><td>'+p[2]+'</td>'+
     '<td class="num">'+fmtInt(p[3])+'</td><td class="num">'+fmtInt(p[4])+'</td><td class="num">'+p[5]+'</td>'+
     '<td>'+p[6]+'</td><td class="num">'+fmtInt(p[7])+'</td><td class="num">'+fmtInt(p[8])+'</td>'+
     '<td class="num">'+(p[9]||'-')+'</td><td class="state-'+String(p[10]).replace(/ /g,'-')+'">'+ (p[10]||'-')+'</td></tr>';
  }
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
  renderHeader();renderTiles();renderGlobalCharts();
  renderSessFilters();renderSessTable();renderLossTable();
  if(curSess)renderDetail();
}
renderAll();
</script>
</body>
</html>
"""
