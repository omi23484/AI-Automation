const pptx = require('pptxgenjs');
const p = new pptx();
p.defineLayout({ name: 'W', width: 13.333, height: 7.5 });
p.layout = 'W';

// ---- palette (mirrors the NetPulse product) ----
const C = {
  bg:'0A0E17', panel:'151C2C', panel2:'1E2740', line:'2A3550',
  text:'E6EDF7', muted:'93A1BC', dim:'6B7A96',
  cyan:'38BDF8', indigo:'818CF8', pink:'F472B6',
  green:'34D399', amber:'FBBF24', orange:'FB923C', red:'F43F5E',
  formula:'A9E7FF', white:'FFFFFF'
};
const F = { head:'Cambria', body:'Calibri', mono:'Courier New' };
const EMU = { w:13.333, h:7.5 };

function bg(s){ s.background = { color:C.bg }; }
function card(s,x,y,w,h,fill=C.panel,opts={}){
  s.addShape('roundRect',{x,y,w,h,fill:{color:fill},line:{color:opts.line||C.line,width:opts.lw||1},rectRadius:0.09,
    shadow:opts.shadow?{type:'outer',color:'000000',opacity:0.35,blur:8,offset:3,angle:90}:undefined});
}
function circle(s,x,y,d,color,glyph){
  s.addShape('ellipse',{x,y,w:d,h:d,fill:{color},line:{type:'none'}});
  if(glyph) s.addText(glyph,{x,y,w:d,h:d,align:'center',valign:'middle',fontFace:F.body,fontSize:d*22,bold:true,color:C.bg,margin:0});
}
function title(s,t,kicker){
  if(kicker) s.addText(kicker.toUpperCase(),{x:0.6,y:0.34,w:12,h:0.3,fontFace:F.body,fontSize:12,bold:true,color:C.cyan,charSpacing:2,margin:0});
  s.addText(t,{x:0.6,y:0.6,w:12.1,h:0.72,fontFace:F.head,fontSize:29,bold:true,color:C.text,margin:0});
}
function formula(s,x,y,w,txt,h){
  const hh = h|| (0.42 + 0.28*(txt.split('\n').length-1));
  card(s,x,y,w,hh,C.panel2,{line:C.line});
  s.addText(txt,{x:x+0.18,y,w:w-0.36,h:hh,fontFace:F.mono,fontSize:13.5,color:C.formula,valign:'middle',margin:0,lineSpacingMultiple:1.06});
  return hh;
}
function body(s,x,y,w,runs,fs=14){
  s.addText(runs,{x,y,w,h:0.3,fontFace:F.body,fontSize:fs,color:C.text,valign:'top',margin:0,paraSpaceAfter:5,lineSpacingMultiple:1.02});
}
function bullets(s,x,y,w,items,fs=13.5){
  s.addText(items.map((it,i)=>({text:it.t||it,options:{bullet:{code:'2022',indent:14},color:it.c||C.text,bold:!!it.b,breakLine:true,paraSpaceAfter:6}})),
    {x,y,w,h:0.3,fontFace:F.body,fontSize:fs,valign:'top',margin:0});
}
function chip(s,x,y,label,color){
  const w=Math.max(0.55,0.16+label.length*0.085);
  s.addShape('roundRect',{x,y,w,h:0.3,fill:{color:C.panel2},line:{color,width:1},rectRadius:0.06});
  s.addText(label,{x,y,w,h:0.3,align:'center',valign:'middle',fontFace:F.body,fontSize:10.5,bold:true,color,margin:0});
  return w;
}
function foot(s,n){
  s.addText([{text:'NetPulse',options:{bold:true,color:C.cyan}},{text:'  ·  Dashboard logic & formulas  ·  v27',options:{color:C.dim}}],
    {x:0.6,y:7.06,w:9,h:0.3,fontFace:F.body,fontSize:9,margin:0});
  s.addText(String(n),{x:12.5,y:7.06,w:0.4,h:0.3,align:'right',fontFace:F.body,fontSize:9,color:C.dim,margin:0});
}
let N=0; const S=()=>{const s=p.addSlide();bg(s);N++;return s;};

/* ============================ 1 · TITLE ============================ */
{ const s=S();
  s.addShape('ellipse',{x:9.3,y:-2.2,w:6.5,h:6.5,fill:{color:C.panel},line:{type:'none'}});
  s.addShape('ellipse',{x:10.9,y:3.6,w:4.6,h:4.6,fill:{color:C.panel2},line:{type:'none'}});
  circle(s,0.62,1.7,0.34,C.cyan);
  s.addText('NETPULSE ANALYTICS ENGINE',{x:1.12,y:1.66,w:9,h:0.4,fontFace:F.body,fontSize:13,bold:true,color:C.cyan,charSpacing:2,margin:0});
  s.addText('Dashboard Logic & Formulas',{x:0.6,y:2.3,w:11,h:1.1,fontFace:F.head,fontSize:44,bold:true,color:C.text,margin:0});
  s.addText('Exactly how every graph, verdict, AI summary and risk score is computed —\nthe real formulas behind the screen, straight from the engine.',
    {x:0.62,y:3.55,w:9.4,h:1,fontFace:F.body,fontSize:16,color:C.muted,margin:0,lineSpacingMultiple:1.12});
  const items=['Utilization & p95','Time-in-state','Robust forecast (Theil–Sen)','Risk score','Anomaly detection','Verdict engine','AI summaries','Dashboard graphs'];
  let cx=0.62; items.forEach((t,i)=>{ if(i===4){cx=0.62;} const yy=i<4?4.75:5.2; const w=chip(s,cx,yy,t,i<4?C.cyan:C.indigo); cx+=w+0.18; });
  s.addText('worse-of-TX/RX · daily p95 · min/max envelope · dow×hour baseline · business-hours aware',
    {x:0.62,y:5.75,w:11,h:0.3,fontFace:F.mono,fontSize:11,color:C.dim,margin:0});
  foot(s,N);
}

/* ============================ 2 · PIPELINE ============================ */
{ const s=S(); title(s,'From raw poll to verdict — the data pipeline','how a number becomes a decision');
  const steps=[
    ['1','Ingest','Parse XLSX/CSV offline; understand headers by meaning; normalize units to bps',C.cyan],
    ['2','Per-sample','utilization = worse of TX/RX vs each direction’s own capacity; flag impossible values',C.indigo],
    ['3','Aggregate','p95 / avg / peak, time-in-state, dow×hour baseline & heatmap per link',C.pink],
    ['4','Model','Robust forecast, anomaly detection, risk score — all on the cleaned series',C.amber],
    ['5','Explain','Verdict ladder → level + reason + action; technical & plain-English AI summaries',C.green],
  ];
  const x0=0.6,w=2.42,gap=0.13,y=1.9,h=3.5;
  steps.forEach((st,i)=>{ const x=x0+i*(w+gap);
    card(s,x,y,w,h,C.panel,{shadow:true});
    circle(s,x+0.22,y+0.24,0.5,st[3],st[0]);
    s.addText(st[1],{x:x+0.82,y:y+0.3,w:w-0.9,h:0.4,fontFace:F.head,fontSize:16,bold:true,color:C.text,margin:0});
    s.addText(st[2],{x:x+0.22,y:y+1.0,w:w-0.42,h:h-1.2,fontFace:F.body,fontSize:12,color:C.muted,margin:0,valign:'top',lineSpacingMultiple:1.08});
    if(i<4) s.addText('→',{x:x+w-0.02,y:y+h/2-0.3,w:0.2,h:0.4,align:'center',fontFace:F.body,fontSize:18,bold:true,color:C.dim,margin:0});
  });
  card(s,0.6,5.65,12.14,1.2,C.panel2);
  s.addText([{text:'One rule underlies everything:  ',options:{bold:true,color:C.text}},
    {text:'utilization is measured per direction against that direction’s own capacity, and the worse of the two is the link’s load. Every graph, threshold, forecast and verdict reads from that single normalized series.',options:{color:C.muted}}],
    {x:0.85,y:5.72,w:11.6,h:1.05,fontFace:F.body,fontSize:13.5,valign:'middle',margin:0,lineSpacingMultiple:1.05});
  foot(s,N);
}

/* ============================ 3 · UTILIZATION ============================ */
{ const s=S(); title(s,'Utilization — the base metric','per sample, per direction, worse-of-two');
  let y=1.85;
  body(s,0.6,y,7.5,[{text:'Each direction is compared to its ',options:{}},{text:'own',options:{bold:true,color:C.cyan}},{text:' capacity (links can be asymmetric), then the busier direction wins:',options:{}}]);
  y+=0.7;
  y+=formula(s,0.6,y,7.7,'uT = tx / speedTx        (or txp/100 if no rate)\nuR = rx / speedRx        (or rxp/100 if no rate)\nutilization = max(uT, uR)')+0.2;
  body(s,0.6,y,7.7,[{text:'Missing a rate but have a %?  ',options:{bold:true,color:C.text}},{text:'tx = txp/100 × speedTx  (and rx likewise).',options:{}}]); y+=0.55;
  body(s,0.6,y,7.7,[{text:'Peak utilization',options:{bold:true,color:C.pink}},{text:' (microbursts the averages hide): ',options:{}}]); y+=0.42;
  y+=formula(s,0.6,y,7.7,'pu = max( ptx/speedTx , prx/speedRx )')+0.25;
  body(s,0.6,y,7.7,[{text:'Guard — physically impossible values ',options:{bold:true,color:C.red}},{text:'(counter-wrap / wrong bandwidth column):',options:{}}]); y+=0.42;
  formula(s,0.6,y,7.7,'bad = util>1.2  OR  rate>1.2×capacity   →  excluded');

  // right column: illustrative
  card(s,8.55,1.85,4.2,4.85,C.panel,{shadow:true});
  s.addText('Worked example',{x:8.8,y:2.05,w:3.7,h:0.35,fontFace:F.head,fontSize:15,bold:true,color:C.text,margin:0});
  const rows=[['TX rate','3.6 Gbps'],['TX capacity','10 Gbps'],['→ uT','36%'],['RX rate','7.1 Gbps'],['RX capacity','10 Gbps'],['→ uR','71%']];
  let ry=2.55; rows.forEach(r=>{ const em=r[0].startsWith('→');
    s.addText(r[0],{x:8.8,y:ry,w:2.2,h:0.32,fontFace:em?F.body:F.mono,fontSize:12,bold:em,color:em?C.cyan:C.muted,margin:0});
    s.addText(r[1],{x:11.0,y:ry,w:1.55,h:0.32,align:'right',fontFace:F.mono,fontSize:12,bold:em,color:em?C.text:C.muted,margin:0}); ry+=0.4; });
  s.addShape('line',{x:8.8,y:ry+0.02,w:3.75,h:0,line:{color:C.line,width:1}}); ry+=0.15;
  s.addText([{text:'utilization = ',options:{color:C.muted}},{text:'71%',options:{bold:true,color:C.red}}],{x:8.8,y:ry,w:3.75,h:0.5,fontFace:F.body,fontSize:20,margin:0});
  s.addText('the worse direction (RX) sets the load',{x:8.8,y:ry+0.55,w:3.75,h:0.4,fontFace:F.body,fontSize:11,italic:true,color:C.dim,margin:0});
  foot(s,N);
}

/* ============================ 4 · AGGREGATES / PERCENTILE ============================ */
{ const s=S(); title(s,'p95, average, peak — and how a percentile is taken','the headline numbers on every card');
  const defs=[
    ['p95','38BDF8','95th-percentile utilization — the sustained busy level. The capacity-assessment basis; ignores rare one-off spikes.'],
    ['avg','818CF8','mean utilization across all valid samples.'],
    ['max','FB923C','single highest sample utilization.'],
    ['pkP95 / pkMax','F472B6','p95 and max of the peak columns — catches microbursts between polls.'],
  ];
  let y=1.9; defs.forEach(d=>{ circle(s,0.62,y+0.02,0.34,d[1]);
    s.addText(d[0],{x:1.1,y,w:2.1,h:0.35,fontFace:F.mono,fontSize:14,bold:true,color:d[1],margin:0});
    s.addText(d[2],{x:3.15,y:y-0.02,w:4.95,h:0.7,fontFace:F.body,fontSize:12.5,color:C.muted,margin:0,valign:'top',lineSpacingMultiple:1.04}); y+=0.82; });

  card(s,8.5,1.9,4.25,4.8,C.panel,{shadow:true});
  s.addText('percentile(arr, p)',{x:8.75,y:2.08,w:3.8,h:0.35,fontFace:F.mono,fontSize:14,bold:true,color:C.cyan,margin:0});
  s.addText('linear interpolation between order statistics',{x:8.75,y:2.44,w:3.8,h:0.3,fontFace:F.body,fontSize:11,italic:true,color:C.dim,margin:0});
  formula(s,8.72,2.85,3.85,'a = sort(arr)\ni = p * (n - 1)\nlo = floor(i)\nhi = ceil(i)\nreturn a[lo] +\n (a[hi]-a[lo])*(i-lo)',2.35);
  s.addText([{text:'p=0.95, n=100  →  i=94.05\n',options:{color:C.muted}},{text:'blends the 95th & 96th values.',options:{color:C.text}}],
    {x:8.75,y:5.4,w:3.8,h:0.9,fontFace:F.mono,fontSize:11.5,margin:0,lineSpacingMultiple:1.1});
  s.addText('p95 for the headline is taken over all samples; the forecast re-takes it per day (next).',
    {x:0.62,y:5.55,w:7.5,h:1,fontFace:F.body,fontSize:13,italic:true,color:C.muted,margin:0,valign:'top',lineSpacingMultiple:1.08});
  foot(s,N);
}

/* ============================ 5 · THRESHOLDS / STATE ============================ */
{ const s=S(); title(s,'Thresholds & state classification','how a % becomes normal / warning / high / critical');
  y=1.9;
  formula(s,0.6,y,7.7,'state(util) =  util ≥ crit  → critical\n               util ≥ high  → high\n               util ≥ warn  → warning\n               else          → normal',1.75); y+=1.95;
  body(s,0.6,y,7.7,[{text:'Bands resolve in priority order — ',options:{}},{text:'per-link  ›  per-class  ›  global',options:{bold:true,color:C.cyan}},{text:', with optional separate off-hours bands.',options:{}}]);
  y+=0.7;
  bullets(s,0.6,y,7.7,[
    {t:'Global default   warn 60% · high 75% · crit 90%',b:false},
    {t:'Trading class    warn 45% · high 60% · crit 80%   (tighter)',c:C.amber},
    {t:'Backup class     warn 75% · high 88% · crit 96%   (looser)',c:C.muted},
    {t:'Off-hours bands optional — a link judged against different limits at night',c:C.muted},
  ],12.5);

  // band ladder viz
  const bx=8.6,bw=4.15; card(s,bx,1.9,bw,4.8,C.panel,{shadow:true});
  s.addText('Global bands',{x:bx+0.25,y:2.05,w:bw-0.5,h:0.3,fontFace:F.head,fontSize:14,bold:true,color:C.text,margin:0});
  const seg=[['critical','90–100%',C.red],['high','75–90%',C.orange],['warning','60–75%',C.amber],['normal','0–60%',C.green]];
  let sy=2.5; seg.forEach(g=>{ const hgt=g[0]==='normal'?1.35:0.62;
    s.addShape('roundRect',{x:bx+0.25,y:sy,w:bw-0.5,h:hgt,fill:{color:g[2]},line:{type:'none'},rectRadius:0.05});
    s.addText([{text:g[0]+'   ',options:{bold:true}},{text:g[1],options:{}}],{x:bx+0.45,y:sy,w:bw-0.8,h:hgt,valign:'middle',fontFace:F.body,fontSize:13,color:C.bg,margin:0}); sy+=hgt+0.12; });
  foot(s,N);
}

/* ============================ 6 · BUSINESS HOURS ============================ */
{ const s=S(); title(s,'Business hours — minute-accurate & timezone-consistent','the lens for congestion, upgrades and anomalies');
  y=1.9;
  formula(s,0.6,y,8.1,'isBH(ts):\n  day in businessHours.days          (e.g. Mon-Fri)\n  AND  startHr:startMin <= clock < endHr:endMin',1.4); y+=1.6;
  body(s,0.6,y,8.1,[{text:'Market-hours preset:  ',options:{bold:true,color:C.text}},{text:'09:15 – 15:30, Mon–Fri',options:{fontFace:F.mono,color:C.cyan}},{text:'  (SEBI/BSE).',options:{}}]); y+=0.6;
  bullets(s,0.6,y,8.1,[
    {t:'Minute-accurate — 09:15 and 15:30 are honoured, not rounded to the hour.',b:true},
    {t:'All timestamps sit on one wall-clock (the configured zone), so the report cover, the breach rows and the market-hour flags never disagree across browsers.'},
    {t:'Feeds: business-hour breach counts, the upgrade policy, the dow×hour anomaly baseline, heat-maps, and chart shading.',c:C.muted},
  ],13);

  const cx=9.0,cw=3.75; card(s,cx,1.9,cw,4.15,C.panel,{shadow:true});
  s.addText('Used by',{x:cx+0.25,y:2.05,w:cw-0.5,h:0.3,fontFace:F.head,fontSize:14,bold:true,color:C.text,margin:0});
  const us=[['⏱','Business-hour breaches'],['↑','Upgrade policy trigger'],['◉','Anomaly dow×hour baseline'],['▦','Utilization heat-map'],['░','Chart hour shading']];
  let uy=2.5; us.forEach(u=>{ circle(s,cx+0.28,uy,0.36,C.indigo,u[0]); s.addText(u[1],{x:cx+0.78,y:uy,w:cw-1.0,h:0.36,valign:'middle',fontFace:F.body,fontSize:12.5,color:C.text,margin:0}); uy+=0.63; });
  foot(s,N);
}

/* ============================ 7 · TIME-IN-STATE ============================ */
{ const s=S(); title(s,'Time-in-state distribution','how much of the window is spent busy');
  y=1.9;
  body(s,0.6,y,7.6,[{text:'Every valid sample is classified, then normalized to a share of time. Off-hours samples use off-hours bands when configured:',options:{}}]); y+=0.72;
  formula(s,0.6,y,7.6,'for each sample:\n   dist[ state(util, bandsFor(ts)) ] += 1\ndist[k] /= totalSamples',1.35); y+=1.55;
  body(s,0.6,y,7.6,[{text:'Business-day breach counters',options:{bold:true,color:C.orange}},{text:' drive verdicts:',options:{}}]); y+=0.45;
  formula(s,0.6,y,7.6,'breachesBH = # samples  util ≥ crit  AND isBH\nbhDays     = # distinct days  util ≥ high AND isBH',1.05);

  // donut-ish stacked bar illustration
  const dx=8.5,dw=4.25; card(s,dx,1.9,dw,4.8,C.panel,{shadow:true});
  s.addText('Example link — share of time',{x:dx+0.25,y:2.05,w:dw-0.5,h:0.3,fontFace:F.head,fontSize:14,bold:true,color:C.text,margin:0});
  const dd=[['normal',62,C.green],['warning',21,C.amber],['high',12,C.orange],['critical',5,C.red]];
  let dy=2.6; dd.forEach(d=>{
    s.addText(d[0],{x:dx+0.25,y:dy,w:1.4,h:0.34,fontFace:F.body,fontSize:12,color:d[2],bold:true,margin:0});
    s.addShape('roundRect',{x:dx+1.55,y:dy+0.03,w:(dw-2.3)*d[1]/100,h:0.28,fill:{color:d[2]},line:{type:'none'},rectRadius:0.03});
    s.addText(d[1]+'%',{x:dx+dw-0.72,y:dy,w:0.55,h:0.34,align:'right',fontFace:F.mono,fontSize:12,color:C.text,margin:0}); dy+=0.55; });
  s.addShape('line',{x:dx+0.25,y:dy+0.05,w:dw-0.5,h:0,line:{color:C.line,width:1}}); dy+=0.2;
  s.addText([{text:'17% ',options:{bold:true,color:C.orange}},{text:'of time at high+critical\n',options:{color:C.muted}},{text:'→ feeds “Recurring Business-Hour Congestion”',options:{color:C.dim,italic:true}}],
    {x:dx+0.25,y:dy,w:dw-0.5,h:1,fontFace:F.body,fontSize:12.5,margin:0,lineSpacingMultiple:1.1});
  foot(s,N);
}

/* ============================ 8 · FORECAST 1 (Theil-Sen) ============================ */
{ const s=S(); title(s,'Capacity forecast · 1 — robust trend (Theil–Sen)','a single spike day cannot bend the trend');
  y=1.88;
  body(s,0.6,y,7.7,[{text:'Build a ',options:{}},{text:'daily series',options:{bold:true,color:C.cyan}},{text:' — each day’s chosen percentile (p95 / p99 / max):',options:{}}]); y+=0.6;
  formula(s,0.6,y,7.7,'daily[d] = percentile( that day’s utils , metric )'); y+=0.62;
  body(s,0.6,y,7.7,[{text:'Fit the slope as the ',options:{}},{text:'median of all pairwise slopes',options:{bold:true,color:C.cyan}},{text:' (real day spacing on x):',options:{}}]); y+=0.58;
  y+=formula(s,0.6,y,7.7,'slope = median{ (yj - yi) / (xj - xi) }\ninter = median{ y - slope*x }')+0.2;
  bullets(s,0.6,y,7.7,[
    {t:'Busy-weekday model: if weekdays run hotter (median > weekend×1.35+0.02), fit weekdays only — a business link is capped by its busy days.',b:false,c:C.muted},
    {t:'x-axis uses real elapsed days, so polling gaps don’t distort the slope.',c:C.muted},
  ],12);

  // illustrative scatter+trend chart
  const cx=8.55; card(s,cx,1.88,4.2,4.85,C.panel,{shadow:true});
  s.addText('Daily p95 + robust trend',{x:cx+0.22,y:2.02,w:3.8,h:0.3,fontFace:F.head,fontSize:13.5,bold:true,color:C.text,margin:0});
  const pts=[]; for(let i=0;i<40;i++){pts.push(0.42+i*0.006 + (Math.sin(i*1.7)*0.05) + (i===27?0.22:0));}
  const line=[]; for(let i=0;i<40;i++){line.push(0.43+i*0.006);}
  s.addChart('line',[
    {name:'daily p95',labels:pts.map((_,i)=>String(i)),values:pts},
    {name:'trend',labels:line.map((_,i)=>String(i)),values:line},
  ],{x:cx+0.15,y:2.35,w:3.9,h:4.2,chartColors:[C.cyan.replace('#',''),C.pink],lineSize:[1.4,2.4],lineDataSymbol:['circle','none'],lineDataSymbolSize:3,
    showLegend:true,legendPos:'b',legendColor:C.muted,legendFontSize:9,showTitle:false,
    catAxisHidden:true,valAxisLabelColor:C.dim,valAxisLabelFontSize:8,valGridLine:{color:C.line,size:1},catGridLine:{style:'none'},
    valAxisMinVal:0,valAxisMaxVal:0.9,chartColorsOpacity:[100,100]});
  foot(s,N);
}

/* ============================ 9 · FORECAST 2 (selection + outputs) ============================ */
{ const s=S(); title(s,'Capacity forecast · 2 — selection & outputs','backtested, clamped, turned into dates');
  y=1.88;
  bullets(s,0.6,y,7.6,[
    {t:'Two candidate fits — full-window vs recent (last max(7, n/2) days).',b:true},
    {t:'Pick the one with lower backtest error (MAE) on the held-out last ~20% of days.',},
    {t:'Slope clamped to ±0.04/day (±4%/day plausibility ceiling); current & projections clamped to plausible ranges.',c:C.muted},
  ],13); y+=1.7;
  formula(s,0.6,y,7.6,'current = clamp( slope · lastDay + inter , 0 , 1.5 )\n\ntime→T =  current ≥ T   → 0        (already there)\n         slope > 0    → (T − current) / slope\n         else         → —          (never at this trend)',1.9);

  // right: outputs
  const cx=8.5,cw=4.25; card(s,cx,1.88,cw,4.82,C.panel,{shadow:true});
  s.addText('What it produces',{x:cx+0.25,y:2.03,w:cw-0.5,h:0.3,fontFace:F.head,fontSize:14,bold:true,color:C.text,margin:0});
  const outs=[
    ['t80 / t90 / t95','days until 80 / 90 / 95%',C.cyan],
    ['proj[30/60/90/180]','projected util at horizon',C.indigo],
    ['growthMoM','median 1st-third vs last-third, scaled to /30d, clamped ±3',C.pink],
    ['window','[t90 − lead , t90] upgrade window',C.amber],
    ['conf','history span + backtest + model agreement (≤ 0.95)',C.green],
  ];
  let oy=2.5; outs.forEach(o=>{ s.addText(o[0],{x:cx+0.25,y:oy,w:cw-0.5,h:0.3,fontFace:F.mono,fontSize:12.5,bold:true,color:o[2],margin:0});
    s.addText(o[1],{x:cx+0.25,y:oy+0.3,w:cw-0.5,h:0.45,fontFace:F.body,fontSize:11.5,color:C.muted,margin:0,valign:'top',lineSpacingMultiple:1.02}); oy+=0.82; });
  foot(s,N);
}

/* ============================ 10 · DIRECTION + PROVISIONING ============================ */
{ const s=S(); title(s,'Forecast direction & provisioning target','which way saturates first, and how much headroom');
  y=1.9;
  body(s,0.6,y,7.6,[{text:'Direction knob — ',options:{bold:true,color:C.cyan}},{text:'combined (overall util) or split (TX & RX forecast separately). In split mode the ',options:{}},{text:'binding',options:{bold:true}},{text:' direction is the one that saturates first:',options:{}}]); y+=0.85;
  formula(s,0.6,y,7.6,'bindingDir = argmin( t90_TX , t90_RX )'); y+=0.7;
  body(s,0.6,y,7.6,[{text:'Metric knob:',options:{bold:true,color:C.cyan}},{text:'  p95 (sustained) · p99 · max — sets which daily level the trend is fit to.',options:{}}]); y+=0.75;
  body(s,0.6,y,7.6,[{text:'Provisioning target — ',options:{bold:true,color:C.amber}},{text:'“provision to N× peak”:',options:{}}]); y+=0.5;
  formula(s,0.6,y,7.6,'recommendedCapacity = peak × speed × N\npeak-utilization ceiling = 100 / N  %',1.05);

  const cx=8.5,cw=4.25; card(s,cx,1.9,cw,4.8,C.panel,{shadow:true});
  s.addText('N× peak → ceiling',{x:cx+0.25,y:2.05,w:cw-0.5,h:0.3,fontFace:F.head,fontSize:14,bold:true,color:C.text,margin:0});
  const tab=[['N','ceiling','headroom'],['1.25','80%','1.25×'],['1.5','67%','1.5×'],['2.0','50%','2.0×'],['3.0','33%','3.0×']];
  let ty=2.55; tab.forEach((r,i)=>{ const hd=i===0;
    [0,1,2].forEach(c=>s.addText(r[c],{x:cx+0.25+c*1.28,y:ty,w:1.25,h:0.34,align:c?'center':'left',fontFace:hd?F.body:F.mono,fontSize:12,bold:hd,color:hd?C.cyan:C.text,margin:0}));
    ty+=0.42; if(hd) s.addShape('line',{x:cx+0.25,y:ty-0.05,w:cw-0.5,h:0,line:{color:C.line,width:1}}); });
  s.addText([{text:'peak = ',options:{color:C.muted}},{text:'max(pkP95, max)',options:{fontFace:F.mono,color:C.text}},{text:'\nA link at 50% peak with N=2 already meets the target.',options:{color:C.dim,italic:true}}],
    {x:cx+0.25,y:5.0,w:cw-0.5,h:1.4,fontFace:F.body,fontSize:12,margin:0,valign:'top',lineSpacingMultiple:1.1});
  foot(s,N);
}

/* ============================ 11 · RISK SCORE ============================ */
{ const s=S(); title(s,'Risk score — 0 to 100','six weighted factors × business impact');
  y=1.88;
  formula(s,0.6,y,7.5,'nl(v)  = clamp(v,0,1) ^ 1.4     (hot links hurt more)\nraw    = SUM(factor_i) / SUM(weight_i)\nscore  = round( clamp(raw * impactMul, 0,1) * 100 )',1.75); y+=1.95;
  const facs=[
    ['Peak util','nl(pkP95) × 0.9',C.pink],['Avg util','nl(avg) × 0.7',C.indigo],
    ['Trend','clamp(slope·60/0.5) × 0.8',C.cyan],['Growth','clamp(growth/0.3) × 0.7',C.amber],
    ['Violations','clamp(bhDays/14) × 1.0',C.orange],['Anomalies','clamp(anoms/4) × 0.6',C.green],
  ];
  let fx=0.6,fy=y; facs.forEach((f,i)=>{ const x=0.6+(i%2)*3.9; const yy=y+Math.floor(i/2)*0.62;
    circle(s,x,yy+0.02,0.28,f[2]); s.addText(f[0],{x:x+0.4,y:yy,w:1.5,h:0.3,fontFace:F.body,fontSize:12,bold:true,color:C.text,margin:0});
    s.addText(f[1],{x:x+1.55,y:yy,w:2.3,h:0.3,fontFace:F.mono,fontSize:10.5,color:C.muted,margin:0}); });

  // impact multiplier + weights chart
  const cx=8.5,cw=4.25; card(s,cx,1.88,cw,4.82,C.panel,{shadow:true});
  s.addText('Business-impact multiplier',{x:cx+0.25,y:2.02,w:cw-0.5,h:0.3,fontFace:F.head,fontSize:13.5,bold:true,color:C.text,margin:0});
  const im=[['Critical','×1.25',C.red],['High','×1.05',C.orange],['Medium','×0.85',C.amber],['Low','×0.65',C.green]];
  let iy=2.5; im.forEach(m=>{ s.addText(m[0],{x:cx+0.3,y:iy,w:2,h:0.32,fontFace:F.body,fontSize:12.5,color:m[2],bold:true,margin:0});
    s.addText(m[1],{x:cx+cw-1.3,y:iy,w:1.0,h:0.32,align:'right',fontFace:F.mono,fontSize:13,color:C.text,margin:0}); iy+=0.44; });
  s.addShape('line',{x:cx+0.3,y:iy+0.03,w:cw-0.6,h:0,line:{color:C.line,width:1}}); iy+=0.2;
  s.addText('Device / site / infra risk',{x:cx+0.3,y:iy,w:cw-0.6,h:0.3,fontFace:F.head,fontSize:12.5,bold:true,color:C.cyan,margin:0}); iy+=0.42;
  s.addText('agg = 0.6·(impact-weighted mean) + 0.4·(worst link)',{x:cx+0.3,y:iy,w:cw-0.6,h:0.7,fontFace:F.mono,fontSize:10.5,color:C.muted,margin:0,valign:'top',lineSpacingMultiple:1.1});
  foot(s,N);
}

/* ============================ 12 · ANOMALY DETECTION ============================ */
{ const s=S(); title(s,'Anomaly detection — three detectors','baseline-relative, guarded against false positives');
  const dets=[
    ['Traffic spike','38BDF8','Same weekday+hour baseline (mean m, std sd, n).','z = (util − m) / sd\nfire if  n≥5  AND  sd>0.001\n         AND z>3.2  AND jump≥8pp\n         AND util>15%'],
    ['Weekend on business link','F472B6','Compares medians, not a fixed cut — so a 24×7 link won’t false-fire.','fire if class in {Core,Trading,\n   Internet,Customer}\n   AND wkendMed > 20%\n   AND wkendMed >= 0.6 * weekdayMed'],
    ['RX/TX imbalance','FBBF24','Sustained directional asymmetry across dual-direction samples.','ratios = max(tx,rx)/min(tx,rx)\nfire if median(ratios) > 6\n         AND ≥10 samples'],
  ];
  let x=0.6; const w=3.95,gap=0.13,yy=1.9,h=4.5;
  dets.forEach((d,i)=>{ const xx=0.6+i*(w+gap);
    card(s,xx,yy,w,h,C.panel,{shadow:true});
    circle(s,xx+0.25,yy+0.25,0.42,d[1]);
    s.addText(d[0],{x:xx+0.8,y:yy+0.24,w:w-0.95,h:0.6,fontFace:F.head,fontSize:15,bold:true,color:C.text,margin:0,valign:'middle'});
    s.addText(d[2],{x:xx+0.25,y:yy+0.95,w:w-0.5,h:1.0,fontFace:F.body,fontSize:12,color:C.muted,margin:0,valign:'top',lineSpacingMultiple:1.06});
    card(s,xx+0.22,yy+2.05,w-0.44,2.25,C.panel2,{line:C.line});
    s.addText(d[3],{x:xx+0.38,y:yy+2.15,w:w-0.72,h:2.05,fontFace:F.mono,fontSize:11,color:C.formula,margin:0,valign:'top',lineSpacingMultiple:1.12});
  });
  s.addText([{text:'std = ',options:{color:C.muted,fontFace:F.mono}},{text:'sqrt( mean((x - m)^2) )',options:{color:C.formula,fontFace:F.mono}},{text:'   ·   every detector requires a meaningful sample so a thin baseline can’t manufacture a spike.',options:{color:C.dim,italic:true}}],
    {x:0.6,y:6.55,w:12,h:0.35,fontFace:F.body,fontSize:11.5,margin:0});
  foot(s,N);
}

/* ============================ 13 · VERDICT ENGINE ============================ */
{ const s=S(); title(s,'Verdict engine — the decision ladder','first matching rule wins → level · reason · action');
  const ladder=[
    ['Data Quality Issue','warning','badCount ≥ 30% of samples',C.amber],
    ['Insufficient Data','warning','count < 8 samples',C.amber],
    ['Link Upgrade Recommended','critical','upgradeDays ≥ policy days (in look-back window)',C.red],
    ['Recurring BH Congestion','critical','bhDays ≥ 5  AND  (crit>2%  OR  high>10%)',C.red],
    ['Critical Congestion','critical','critical share > 3%',C.red],
    ['Capacity Planning Required','high','t90 ≤ horizon  AND  growing',C.orange],
    ['Weekend / Imbalance / Microbursts','warning','matching anomaly, or pkP95≥crit while p95<high',C.amber],
    ['Traffic Pattern Changed','warning','≥ 1 behavioural anomaly',C.amber],
    ['Idle / Under-utilized','normal','p95 < 3%',C.green],
    ['Monitor','warning','high+warning share > 15%  OR  growing',C.amber],
    ['Healthy','normal','none of the above',C.green],
  ];
  let ly=1.82; const rowH=0.42;
  ladder.forEach((r,i)=>{ const x=0.6, w=8.55;
    if(i%2===0) s.addShape('rect',{x,y:ly,w,h:rowH,fill:{color:C.panel},line:{type:'none'}});
    s.addShape('roundRect',{x:x+0.1,y:ly+0.09,w:0.24,h:0.24,fill:{color:r[3]},line:{type:'none'},rectRadius:0.03});
    s.addText(r[0],{x:x+0.5,y:ly,w:4.3,h:rowH,valign:'middle',fontFace:F.body,fontSize:12,bold:true,color:C.text,margin:0});
    s.addText(r[2],{x:x+4.75,y:ly,w:3.7,h:rowH,valign:'middle',fontFace:F.mono,fontSize:9.8,color:C.muted,margin:0});
    ly+=rowH; });
  // right: confidence + output
  const cx=9.4,cw=3.35; card(s,cx,1.82,cw,4.85,C.panel,{shadow:true});
  s.addText('Each verdict carries',{x:cx+0.22,y:1.96,w:cw-0.44,h:0.3,fontFace:F.head,fontSize:13,bold:true,color:C.text,margin:0});
  bullets(s,cx+0.22,2.4,cw-0.44,[{t:'level (colour)',b:true,c:C.cyan},{t:'plain reason'},{t:'recommended action'},{t:'confidence + comparison'}],12);
  s.addShape('line',{x:cx+0.22,y:4.05,w:cw-0.44,h:0,line:{color:C.line,width:1}});
  s.addText('confidence',{x:cx+0.22,y:4.15,w:cw-0.44,h:0.3,fontFace:F.mono,fontSize:12,bold:true,color:C.cyan,margin:0});
  s.addText('0.4 + count/300·0.35\n   + r²·0.2 + bhDays/7\n   (capped 0.97)',{x:cx+0.22,y:4.5,w:cw-0.44,h:1.2,fontFace:F.mono,fontSize:11,color:C.muted,margin:0,valign:'top',lineSpacingMultiple:1.14});
  foot(s,N);
}

/* ============================ 14 · AI SUMMARY (TECH) ============================ */
{ const s=S(); title(s,'AI summary — technical','templated from the computed facts (no black box)');
  y=1.9;
  body(s,0.6,y,7.7,[{text:'Deterministic sentences assembled from the same numbers the graphs use — reproducible and auditable:',options:{}}]); y+=0.7;
  bullets(s,0.6,y,7.7,[
    {t:'p95 load + bandwidth:  “Busy-period load (p95) is X% — about Y on this Z link.”',b:true},
    {t:'bhDays crossings, if any.'},
    {t:'Growth: direction + %/month when |growthMoM| ≥ 3%, else “roughly flat”.'},
    {t:'t90 timing + upgrade window (“reaches 90% in ~N days”).'},
    {t:'Anomaly count · impossible samples excluded · forecast confidence + model note.'},
  ],13);

  const cx=8.55,cw=4.2; card(s,cx,1.9,cw,4.8,C.panel2,{shadow:true,line:C.cyan});
  s.addText('SAMPLE OUTPUT',{x:cx+0.25,y:2.05,w:cw-0.5,h:0.3,fontFace:F.body,fontSize:10,bold:true,color:C.cyan,charSpacing:1.5,margin:0});
  s.addText('“Busy-period load (p95) is 71% — about 7.1 Gbps on this 10 Gbps link. It crossed the high/critical line on 6 business days. Traffic is growing ~14%/month. If this continues, it reaches 90% in about 38 days — plan the upgrade in the 12–38 day window. Forecast confidence 82% (recent trend).”',
    {x:cx+0.25,y:2.5,w:cw-0.5,h:4.0,fontFace:F.body,fontSize:13.5,color:C.text,italic:true,margin:0,valign:'top',lineSpacingMultiple:1.16});
  foot(s,N);
}

/* ============================ 15 · AI SUMMARY (PLAIN) ============================ */
{ const s=S(); title(s,'AI summary — plain English','same facts, no jargon, for management');
  y=1.9;
  body(s,0.6,y,7.7,[{text:'Health phrase is chosen from the verdict level and p95 — no p95/MoM terms leak through:',options:{}}]); y+=0.7;
  const map=[['critical','“running very busy”',C.red],['high','“getting busy”',C.orange],['warning','“mostly fine but worth watching”',C.amber],['p95 < 5%','“barely used”',C.dim],['else','“healthy”',C.green]];
  let my=y; map.forEach(m=>{ s.addShape('roundRect',{x:0.6,y:my,w:1.75,h:0.34,fill:{color:C.panel2},line:{color:m[2],width:1},rectRadius:0.05});
    s.addText(m[0],{x:0.6,y:my,w:1.75,h:0.34,align:'center',valign:'middle',fontFace:F.mono,fontSize:11,color:m[2],bold:true,margin:0});
    s.addText(m[1],{x:2.5,y:my,w:5.6,h:0.34,valign:'middle',fontFace:F.body,fontSize:13,color:C.text,margin:0}); my+=0.48; });
  body(s,0.6,my+0.1,7.7,[{text:'Then: busy %, a months-to-full estimate, and an impact note if the link is business-critical.',options:{color:C.muted}}]);

  const cx=8.55,cw=4.2; card(s,cx,1.9,cw,4.8,C.panel2,{shadow:true,line:C.green});
  s.addText('SAMPLE OUTPUT',{x:cx+0.25,y:2.05,w:cw-0.5,h:0.3,fontFace:F.body,fontSize:10,bold:true,color:C.green,charSpacing:1.5,margin:0});
  s.addText('“In plain terms, the NYC trading link Core-01 Ethernet1/2 is running very busy. At its busiest it uses about 71% of the line’s capacity. Traffic is climbing, and at this pace the link would run low on spare room in roughly 1 month. It would be wise to plan an upgrade before then. This is a business-critical link, so any problem here has high impact.”',
    {x:cx+0.25,y:2.5,w:cw-0.5,h:4.0,fontFace:F.body,fontSize:13.5,color:C.text,italic:true,margin:0,valign:'top',lineSpacingMultiple:1.16});
  foot(s,N);
}

/* ============================ 16 · DASHBOARD GRAPHS ============================ */
{ const s=S(); title(s,'The dashboard graphs — what each one draws','and the maths that keeps them honest at scale');
  const g=[
    ['Traffic & Utilization','38BDF8','Per-sample TX / RX / Peak vs time. Threshold bands, minute-accurate business-hour shading, maintenance shading, anomaly markers.'],
    ['Min/max envelope','818CF8','downsampleMM keeps the extreme point of each bucket, so spikes survive even when 40k+ points render as ≤1400.'],
    ['Utilization rhythm','F472B6','dow×hour heat-map = mean utilization per weekday-hour cell; reveals the weekly busy pattern.'],
    ['Business vs off-hours','FBBF24','Side-by-side p95 / avg / peak + state split, judged against each window’s own bands.'],
    ['Forecast','34D399','Daily p95 series + the projection line (current + slope·days) with the upgrade window shaded.'],
    ['Digital twin','FB923C','Site / device LEDs coloured by the verdict level; aggregate risk rolls up per device and site.'],
  ];
  let x=0.6; const w=3.95,gap=0.14,yy=1.85,h=2.28;
  g.forEach((d,i)=>{ const xx=0.6+(i%3)*(w+gap); const yr=1.85+Math.floor(i/3)*(h+0.2);
    card(s,xx,yr,w,h,C.panel,{shadow:true});
    circle(s,xx+0.24,yr+0.22,0.36,d[1]);
    s.addText(d[0],{x:xx+0.72,y:yr+0.2,w:w-0.85,h:0.5,valign:'middle',fontFace:F.head,fontSize:14,bold:true,color:C.text,margin:0});
    s.addText(d[2],{x:xx+0.24,y:yr+0.78,w:w-0.48,h:h-0.9,fontFace:F.body,fontSize:11.5,color:C.muted,margin:0,valign:'top',lineSpacingMultiple:1.06});
  });
  s.addText([{text:'downsampleMM:  ',options:{fontFace:F.mono,bold:true,color:C.cyan}},{text:'bucket = ceil(n / (maxPts/2));  keep the min and the max of each bucket  →  the chart is fast and never loses a spike.',options:{color:C.muted}}],
    {x:0.6,y:6.62,w:12.1,h:0.4,fontFace:F.body,fontSize:12,margin:0});
  foot(s,N);
}

/* ============================ 17 · CHEAT SHEET ============================ */
{ const s=S(); title(s,'One-page formula reference','every number on the screen, in one place');
  const col=[
    ['util','max(tx/spTx, rx/spRx)  worse dir'],
    ['peak (pu)','max(ptx/spTx, prx/spRx)'],
    ['p95','percentile(utils, 0.95)'],
    ['state','>=crit crit / >=high high / >=warn warn'],
    ['isBH','day in days AND start<=clock<end (tz)'],
    ['bhDays','# distinct days  util>=high AND isBH'],
    ['slope','median pairwise dy/dx (Theil-Sen)'],
    ['time->T','(T - current) / slope   (slope>0)'],
    ['growthMoM','(last3rd-first3rd)/max(first,.03)*30/span'],
    ['risk','round(clamp(SUMf/SUMw * impactMul,0,1)*100)'],
    ['spike','z>3.2 & n>=5 & jump>=8pp & util>15%'],
    ['recCap','peak * speed * N   (ceiling 100/N%)'],
  ];
  const colW=6.0, rowH=0.62;
  col.forEach((r,i)=>{ const c=Math.floor(i/6); const row=i%6;
    const x=0.6+c*(colW+0.35), yy=1.9+row*(rowH+0.14);
    card(s,x,yy,colW,rowH,C.panel);
    s.addText(r[0],{x:x+0.18,y:yy,w:1.5,h:rowH,valign:'middle',fontFace:F.mono,fontSize:12.5,bold:true,color:C.cyan,margin:0});
    s.addShape('line',{x:x+1.72,y:yy+0.1,w:0,h:rowH-0.2,line:{color:C.line,width:1}});
    s.addText(r[1],{x:x+1.9,y:yy,w:colW-2.05,h:rowH,valign:'middle',fontFace:F.mono,fontSize:11,color:C.text,margin:0,lineSpacingMultiple:1.0});
  });
  foot(s,N);
}

/* ============================ 18 · CLOSE ============================ */
{ const s=S();
  s.addShape('ellipse',{x:-2.3,y:3.4,w:6.6,h:6.6,fill:{color:C.panel},line:{type:'none'}});
  s.addShape('ellipse',{x:9.6,y:-2.4,w:5.6,h:5.6,fill:{color:C.panel2},line:{type:'none'}});
  s.addText('Every pixel is explainable',{x:0.7,y:2.5,w:11.5,h:1,fontFace:F.head,fontSize:40,bold:true,color:C.text,margin:0});
  s.addText('No black box: each graph, verdict and summary traces back to one normalized,\nbusiness-hours-aware utilization series and the formulas in this deck.',
    {x:0.72,y:3.7,w:10,h:1,fontFace:F.body,fontSize:16,color:C.muted,margin:0,lineSpacingMultiple:1.12});
  let cx=0.72; ['worse-of-TX/RX','daily p95','Theil–Sen','weighted risk','dow×hour baseline','verdict ladder'].forEach(t=>{const w=chip(s,cx,4.9,t,C.cyan);cx+=w+0.16;});
  s.addText('NetPulse · v27 · offline single-file analytics',{x:0.72,y:5.6,w:11,h:0.3,fontFace:F.mono,fontSize:12,color:C.dim,margin:0});
  foot(s,N);
}

p.writeFile({ fileName: '/tmp/claude-0/-home-user-AI-Automation/30bf4683-5df2-597c-b7f6-4ce623c49831/scratchpad/NetPulse-Dashboard-Logic.pptx' })
  .then(f=>console.log('WROTE', f)).catch(e=>{console.error(e);process.exit(1);});
