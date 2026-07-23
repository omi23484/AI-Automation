const pptx = require('pptxgenjs');
const p = new pptx();
p.defineLayout({ name:'W', width:13.333, height:7.5 }); p.layout='W';

const C={ bg:'FFFFFF', panel:'F2F8FB', panel2:'E7F1F7', ink:'13293D', muted:'5C6F82', dim:'8A9AAB',
  teal:'0E7C86', cyan:'1E9DB8', amber:'E4890C', green:'2FA36B', red:'D14343', navy:'0F2436', line:'DBE6EE', white:'FFFFFF' };
const F={ head:'Cambria', body:'Calibri' };

function light(s){ s.background={color:C.bg}; }
function dark(s){ s.background={color:C.navy}; }
function card(s,x,y,w,h,fill,opts={}){ s.addShape('roundRect',{x,y,w,h,fill:{color:fill||C.panel},line:{color:opts.line||C.line,width:opts.lw||1},rectRadius:0.11,
  shadow:opts.shadow?{type:'outer',color:'8FA6B8',opacity:0.28,blur:9,offset:3,angle:90}:undefined}); }
function circ(s,x,y,d,color,glyph,gcol){ s.addShape('ellipse',{x,y,w:d,h:d,fill:{color},line:{type:'none'}});
  if(glyph)s.addText(glyph,{x,y,w:d,h:d,align:'center',valign:'middle',fontFace:F.body,fontSize:d*20,bold:true,color:gcol||C.white,margin:0}); }
function kicker(s,t){ s.addText(t.toUpperCase(),{x:0.7,y:0.5,w:12,h:0.3,fontFace:F.body,fontSize:12.5,bold:true,color:C.teal,charSpacing:2,margin:0}); }
function title(s,t){ s.addText(t,{x:0.7,y:0.82,w:12,h:0.95,fontFace:F.head,fontSize:32,bold:true,color:C.ink,margin:0}); }
function foot(s,n){ s.addText([{text:'NetPulse',options:{bold:true,color:C.teal}},{text:'  ·  in plain English',options:{color:C.dim}}],{x:0.7,y:7.04,w:9,h:0.3,fontFace:F.body,fontSize:9,margin:0});
  s.addText(String(n),{x:12.4,y:7.04,w:0.4,h:0.3,align:'right',fontFace:F.body,fontSize:9,color:C.dim,margin:0}); }
function bullets(s,x,y,w,items,fs=15){ s.addText(items.map(it=>({text:it.t||it,options:{bullet:{code:'2022',indent:16},color:it.c||C.ink,bold:!!it.b,breakLine:true,paraSpaceAfter:9}})),
  {x,y,w,h:0.3,fontFace:F.body,fontSize:fs,valign:'top',margin:0}); }
let N=0; const S=()=>{const s=p.addSlide();N++;return s;};

/* 1 · TITLE */
{ const s=S(); dark(s);
  s.addShape('ellipse',{x:9.6,y:-2.4,w:6.5,h:6.5,fill:{color:'163449'},line:{type:'none'}});
  s.addShape('ellipse',{x:11.3,y:3.7,w:4.4,h:4.4,fill:{color:'12405A'},line:{type:'none'}});
  circ(s,0.72,1.75,0.36,C.cyan);
  s.addText('NETPULSE',{x:1.22,y:1.72,w:9,h:0.4,fontFace:F.body,fontSize:14,bold:true,color:C.cyan,charSpacing:3,margin:0});
  s.addText('Your network capacity,\nin plain English',{x:0.7,y:2.4,w:11,h:1.7,fontFace:F.head,fontSize:44,bold:true,color:C.white,margin:0,lineSpacingMultiple:1.02});
  s.addText('A simple tool that watches how full your network links are — and tells you, in\nordinary words, which ones need attention and when.',
    {x:0.72,y:4.5,w:10,h:1,fontFace:F.body,fontSize:16,color:'C7D6E2',margin:0,lineSpacingMultiple:1.15});
  s.addText('No jargon in this deck — promise.',{x:0.72,y:5.6,w:10,h:0.4,fontFace:F.body,fontSize:13,italic:true,color:C.cyan,margin:0});
  foot(s,N);
}

/* 2 · ONE BIG IDEA */
{ const s=S(); light(s); kicker(s,'The one big idea'); title(s,'It’s a fuel gauge for every network link');
  s.addText('Each link between your sites and systems can only carry so much traffic. NetPulse reads how full each one gets, and lights up early — long before it runs out of room.',
    {x:0.72,y:1.95,w:6.4,h:2,fontFace:F.body,fontSize:16.5,color:C.ink,margin:0,valign:'top',lineSpacingMultiple:1.25});
  bullets(s,0.72,3.9,6.4,[{t:'Green = plenty of room',c:C.green,b:true},{t:'Amber = getting busy, plan ahead',c:C.amber,b:true},{t:'Red = act now',c:C.red,b:true}],15.5);
  // gauge visual
  const gx=8.0,gy=2.3,gw=4.4;
  card(s,gx,gy,gw,3.0,C.panel,{shadow:true});
  s.addText('How full is this link?',{x:gx+0.3,y:gy+0.28,w:gw-0.6,h:0.35,fontFace:F.head,fontSize:15,bold:true,color:C.ink,margin:0});
  const bx=gx+0.4,bw=gw-0.8,by=gy+1.25,bh=0.5;
  s.addShape('roundRect',{x:bx,y:by,w:bw,h:bh,fill:{color:'DDE8EF'},line:{type:'none'},rectRadius:0.08});
  s.addShape('roundRect',{x:bx,y:by,w:bw*0.65,h:bh,fill:{color:C.teal},line:{type:'none'},rectRadius:0.08});
  // 75% tick
  s.addShape('line',{x:bx+bw*0.75,y:by-0.16,w:0,h:bh+0.32,line:{color:C.red,width:2,dashType:'dash'}});
  s.addText('act line',{x:bx+bw*0.75-0.5,y:by+bh+0.16,w:1,h:0.25,align:'center',fontFace:F.body,fontSize:10,bold:true,color:C.red,margin:0});
  s.addText('65% full now',{x:bx,y:by-0.5,w:bw,h:0.3,fontFace:F.body,fontSize:13,bold:true,color:C.teal,margin:0});
  s.addText('Comfortable — but we’re watching the climb.',{x:gx+0.4,y:gy+2.45,w:gw-0.8,h:0.4,fontFace:F.body,fontSize:11.5,italic:true,color:C.muted,margin:0});
  foot(s,N);
}

/* 3 · HOW BUSY */
{ const s=S(); light(s); kicker(s,'What "busy" means'); title(s,'We measure rush hour, not 3 a.m.');
  s.addText('A link is quiet at night and busy during the day. What matters is how full it gets when it’s genuinely busy — so that’s what we measure. And we ignore one freak spike, the same way you’d ignore a single odd traffic jam when judging a road.',
    {x:0.72,y:1.95,w:6.5,h:2.4,fontFace:F.body,fontSize:16.5,color:C.ink,margin:0,valign:'top',lineSpacingMultiple:1.25});
  s.addText([{text:'We call this the ',options:{color:C.muted}},{text:'busy level',options:{bold:true,color:C.teal}},{text:' — the honest “how full at rush hour” number.',options:{color:C.muted}}],
    {x:0.72,y:4.5,w:6.5,h:0.6,fontFace:F.body,fontSize:14,margin:0});
  // two bars: quiet vs busy
  const gx=8.1,gy=2.2,gw=4.3;card(s,gx,gy,gw,3.4,C.panel,{shadow:true});
  const base=gy+3.0;const draw=(cx,h,col,lbl,val)=>{s.addShape('roundRect',{x:cx,y:base-h,w:1.1,h,fill:{color:col},line:{type:'none'},rectRadius:0.06});
    s.addText(val,{x:cx-0.2,y:base-h-0.35,w:1.5,h:0.3,align:'center',fontFace:F.body,fontSize:13,bold:true,color:col,margin:0});
    s.addText(lbl,{x:cx-0.3,y:base+0.1,w:1.7,h:0.3,align:'center',fontFace:F.body,fontSize:11,color:C.muted,margin:0});};
  draw(gx+0.7,0.5,C.dim,'3 a.m.','12%'); draw(gx+2.5,2.1,C.teal,'rush hour','64%');
  s.addText('same link, two times of day',{x:gx+0.3,y:gy+0.25,w:gw-0.6,h:0.3,fontFace:F.head,fontSize:13.5,bold:true,color:C.ink,margin:0});
  foot(s,N);
}

/* 4 · SPARE ROOM */
{ const s=S(); light(s); kicker(s,'The golden rule'); title(s,'Never run a link near full');
  bullets(s,0.72,2.05,6.6,[
    {t:'Keep every important link comfortably below full — roughly two-thirds.',b:false},
    {t:'Own about 1.5× the busiest load you expect, so there’s always spare room.'},
    {t:'The moment a link crosses ~75% full, that’s the signal to add capacity — not wait for it to break.',c:C.ink},
  ],16);
  s.addText('This is the single habit that prevents outages: add road before the traffic jam, not after.',
    {x:0.72,y:4.9,w:6.6,h:0.9,fontFace:F.body,fontSize:14,italic:true,color:C.muted,margin:0,lineSpacingMultiple:1.2});
  // glass filled 65% with red line at 75%
  const gx=8.5,gy=1.9,gw=2.2,gh=4.1;card(s,gx-0.5,gy-0.2,gw+2.2,gh+0.5,C.panel,{shadow:true});
  s.addShape('roundRect',{x:gx,y:gy,w:gw,h:gh,fill:{color:'EAF2F7'},line:{color:C.line,width:1},rectRadius:0.1});
  const fillH=gh*0.65;s.addShape('roundRect',{x:gx,y:gy+gh-fillH,w:gw,h:fillH,fill:{color:C.teal},line:{type:'none'},rectRadius:0.1});
  const y75=gy+gh*0.25;s.addShape('line',{x:gx-0.15,y:y75,w:gw+0.3,h:0,line:{color:C.red,width:2.5,dashType:'dash'}});
  s.addText('75% — act here',{x:gx+gw+0.05,y:y75-0.16,w:2.0,h:0.35,fontFace:F.body,fontSize:12.5,bold:true,color:C.red,margin:0,valign:'middle'});
  s.addText('65% today',{x:gx+gw+0.05,y:gy+gh-fillH-0.16,w:2.0,h:0.35,fontFace:F.body,fontSize:12.5,bold:true,color:C.teal,margin:0,valign:'middle'});
  foot(s,N);
}

/* 5 · FORECAST */
{ const s=S(); light(s); kicker(s,'The forecast'); title(s,'A weather forecast for your links');
  s.addText('NetPulse looks at how each link has been trending and estimates when it will run low on room. Crucially, it gives a sensible range — “in about 6 to 10 weeks” — not a fake-exact day, because real traffic is bumpy.',
    {x:0.72,y:1.95,w:6.3,h:2.2,fontFace:F.body,fontSize:16.5,color:C.ink,margin:0,valign:'top',lineSpacingMultiple:1.25});
  card(s,0.72,4.5,6.3,1.5,C.panel2,{line:C.cyan});
  s.addText([{text:'“At this pace, this link reaches the act line in about ',options:{color:C.ink}},{text:'6–10 weeks',options:{bold:true,color:C.teal}},{text:' — plan the upgrade now.”',options:{color:C.ink}}],
    {x:0.95,y:4.62,w:5.85,h:1.3,fontFace:F.body,fontSize:15,italic:true,valign:'middle',margin:0,lineSpacingMultiple:1.2});
  // rising trend with a widening range band — reliable native chart
  const gx=7.5,gy=2.1,gw=5.1,gh=3.6;card(s,gx,gy,gw,gh,C.panel,{shadow:true});
  s.addText('busy level, climbing toward the act line',{x:gx+0.35,y:gy+0.22,w:gw-0.7,h:0.3,fontFace:F.head,fontSize:13,bold:true,color:C.ink,margin:0});
  const labs=Array.from({length:12},(_,i)=>String(i));
  const mid=labs.map((_,i)=>0.30+i*0.05);
  const hi=mid.map((v,i)=>Math.min(1,v+i*0.012));
  const lo=mid.map((v,i)=>Math.max(0,v-i*0.012));
  const thr=labs.map(()=>0.75);
  s.addChart('line',[
    {name:'range-hi',labels:labs,values:hi},{name:'range-lo',labels:labs,values:lo},
    {name:'busy level',labels:labs,values:mid},{name:'act line',labels:labs,values:thr}],
    {x:gx+0.25,y:gy+0.6,w:gw-0.5,h:gh-1.1,chartColors:['BFE0E4','BFE0E4',C.teal.replace('#',''),C.red],
     lineSize:[1.25,1.25,3,1.5],lineDash:['solid','solid','solid','dash'],lineDataSymbol:['none','none','none','none'],
     showLegend:false,showTitle:false,catAxisHidden:true,valAxisHidden:true,valAxisMinVal:0,valAxisMaxVal:1,
     catGridLine:{style:'none'},valGridLine:{style:'none'}});
  s.addText('shaded = the range · red dashes = the act line',{x:gx+0.35,y:gy+gh-0.42,w:gw-0.7,h:0.3,fontFace:F.body,fontSize:10.5,italic:true,color:C.muted,margin:0});
  foot(s,N);
}

/* 6 · TRAFFIC LIGHT */
{ const s=S(); light(s); kicker(s,'The verdict'); title(s,'Every link gets a traffic light');
  const cards=[['GREEN',C.green,'Healthy','Plenty of room. Nothing to do.'],
    ['AMBER',C.amber,'Watch it','Getting busy or growing. Plan ahead.'],
    ['RED',C.red,'Act now','Very busy or about to fill — upgrade / investigate.']];
  const w=3.9,gap=0.25,y=2.2,h=3.5,x0=0.72;
  cards.forEach((c,i)=>{const x=x0+i*(w+gap);card(s,x,y,w,h,C.white,{shadow:true,line:C.line});
    circ(s,x+w/2-0.45,y+0.4,0.9,c[1]);
    s.addText(c[0],{x,y:y+1.45,w,h:0.35,align:'center',fontFace:F.body,fontSize:13,bold:true,color:c[1],charSpacing:2,margin:0});
    s.addText(c[2],{x,y:y+1.8,w,h:0.5,align:'center',fontFace:F.head,fontSize:20,bold:true,color:C.ink,margin:0});
    s.addText(c[3],{x:x+0.3,y:y+2.45,w:w-0.6,h:0.9,align:'center',fontFace:F.body,fontSize:13,color:C.muted,margin:0,valign:'top',lineSpacingMultiple:1.15});});
  s.addText('Each light comes with a plain reason and a suggested next step — no decoding required.',
    {x:0.72,y:6.05,w:12,h:0.4,fontFace:F.body,fontSize:13.5,italic:true,color:C.muted,margin:0});
  foot(s,N);
}

/* 7 · ANOMALIES */
{ const s=S(); light(s); kicker(s,'Something looks off'); title(s,'We flag the unusual — and say why');
  s.addText('If a link behaves oddly — busy at a time it’s normally quiet, or traffic lopsided in one direction — NetPulse points it out and explains, in plain words, what looked wrong and why it counted as unusual.',
    {x:0.72,y:1.95,w:6.4,h:2.2,fontFace:F.body,fontSize:16.5,color:C.ink,margin:0,valign:'top',lineSpacingMultiple:1.25});
  card(s,0.72,4.5,6.4,1.55,C.panel2,{line:C.amber});
  s.addText([{text:'“This link hit 92% on Sunday night — but it’s usually near 20% then. That’s well outside its normal pattern, so we flagged it.”',options:{italic:true,color:C.ink}}],
    {x:0.95,y:4.62,w:5.95,h:1.35,fontFace:F.body,fontSize:14.5,valign:'middle',margin:0,lineSpacingMultiple:1.2});
  // quiet line with one clear spike — reliable native chart
  const gx=7.6,gy=2.2,gw=5.0,gh=3.2;card(s,gx,gy,gw,gh,C.panel,{shadow:true});
  s.addText('a Sunday-night spike vs the usual quiet',{x:gx+0.35,y:gy+0.22,w:gw-0.7,h:0.3,fontFace:F.head,fontSize:13,bold:true,color:C.ink,margin:0});
  const labs=Array.from({length:14},(_,i)=>String(i));
  const vals=labs.map((_,i)=>i===8?0.92:0.18+Math.random()*0.06);
  s.addChart('line',[{name:'busy level',labels:labs,values:vals}],
    {x:gx+0.25,y:gy+0.6,w:gw-0.5,h:gh-1.1,chartColors:[C.teal.replace('#','')],lineSize:2.5,
     lineDataSymbol:['circle'],lineDataSymbolSize:4,showLegend:false,showTitle:false,
     catAxisHidden:true,valAxisHidden:true,valAxisMinVal:0,valAxisMaxVal:1,catGridLine:{style:'none'},valGridLine:{style:'none'}});
  circ(s,gx+gw*0.5,gy+0.66,0.3,C.red,'!',C.white);
  s.addText('unusual for this time → flagged, with the reason',{x:gx+0.35,y:gy+gh-0.42,w:gw-0.7,h:0.3,fontFace:F.body,fontSize:10.5,italic:true,color:C.muted,margin:0});
  foot(s,N);
}

/* 8 · RHYTHM */
{ const s=S(); light(s); kicker(s,'When are links busy?'); title(s,'See the weekly rhythm at a glance');
  s.addText('A simple colour grid shows each link’s week: rows are days, columns are hours. Darker means busier. In one glance you can see the daily peaks — and whether the busy window is creeping wider.',
    {x:0.72,y:1.95,w:6.2,h:2.3,fontFace:F.body,fontSize:16.5,color:C.ink,margin:0,valign:'top',lineSpacingMultiple:1.25});
  bullets(s,0.72,4.5,6.2,[{t:'Light = quiet',c:C.muted},{t:'Deep teal / red = busy',c:C.teal},{t:'Each square also shows its number',c:C.muted}],14);
  // mini heatmap 7x12
  const gx=7.6,gy=2.0,cell=0.34,cols=12,rows=7;card(s,gx-0.25,gy-0.25,cols*cell+1.3,rows*cell+1.1,C.panel,{shadow:true});
  const days=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  for(let r=0;r<rows;r++){ s.addText(days[r],{x:gx-0.2,y:gy+r*cell,w:0.7,h:cell,valign:'middle',fontFace:F.body,fontSize:8,color:C.muted,margin:0});
    for(let c=0;c<cols;c++){ const business=(r<5&&c>=3&&c<=9); const v=business? (0.45+Math.random()*0.5):(0.08+Math.random()*0.22);
      const col = v>0.75?C.red:v>0.55?'E4890C':v>0.3?C.teal:'BFE0E4';
      s.addShape('rect',{x:gx+0.55+c*cell,y:gy+r*cell,w:cell-0.05,h:cell-0.05,fill:{color:col},line:{type:'none'}}); } }
  s.addText('darker = busier · working hours light up',{x:gx+0.4,y:gy+rows*cell+0.15,w:cols*cell,h:0.3,fontFace:F.body,fontSize:10.5,italic:true,color:C.muted,margin:0});
  foot(s,N);
}

/* 9 · REPORTS */
{ const s=S(); light(s); kicker(s,'One click, audit-ready'); title(s,'Reports you can hand over as-is');
  circ(s,0.8,2.2,1.0,C.teal,'▤');
  s.addText('Press a button, get a clean spreadsheet or PDF that shows exactly which links are running hot, when each is likely to need more capacity, and the evidence behind it.',
    {x:2.1,y:2.15,w:5.2,h:2,fontFace:F.body,fontSize:16,color:C.ink,margin:0,valign:'top',lineSpacingMultiple:1.25});
  const items=[['Which links need attention','ranked, with a plain verdict'],['When each fills up','a sensible date range, not a guess'],['How much to add','the recommended capacity'],['The proof','every busy moment, timestamped']];
  const x0=8.0,y0=1.95,w=4.6,rh=1.15;card(s,x0-0.2,y0-0.15,w+0.4,rh*4+0.3,C.panel,{shadow:true});
  items.forEach((it,i)=>{const y=y0+i*rh;circ(s,x0+0.05,y+0.12,0.5,C.cyan,String(i+1));
    s.addText(it[0],{x:x0+0.7,y:y,w:w-0.9,h:0.4,fontFace:F.head,fontSize:14.5,bold:true,color:C.ink,margin:0});
    s.addText(it[1],{x:x0+0.7,y:y+0.42,w:w-0.9,h:0.5,fontFace:F.body,fontSize:12,color:C.muted,margin:0,valign:'top'});});
  foot(s,N);
}

/* 10 · RULES */
{ const s=S(); light(s); kicker(s,'How it fits the rules'); title(s,'Three promises the rules ask for');
  const rows=[['Build with spare room','Size links well above the busy peak, and never run near full.',C.teal],
    ['Watch it and act early','Catch links crossing the safe line and add capacity before they break.',C.amber],
    ['Keep records & report','Hold the history and produce clean, audit-ready reports on demand.',C.green]];
  const y0=2.15,rh=1.45;
  rows.forEach((r,i)=>{const y=y0+i*rh;card(s,0.72,y,11.9,rh-0.25,C.panel,{shadow:i===0});
    circ(s,1.0,y+0.28,0.72,r[2],'✓');
    s.addText(r[0],{x:2.0,y:y+0.22,w:4.2,h:0.7,valign:'middle',fontFace:F.head,fontSize:18,bold:true,color:C.ink,margin:0});
    s.addText(r[1],{x:6.2,y:y+0.2,w:6.2,h:0.8,valign:'middle',fontFace:F.body,fontSize:14,color:C.muted,margin:0,lineSpacingMultiple:1.1});});
  s.addText('NetPulse is strongest on the planning and reporting — promises one and three, and the early-warning half of two.',
    {x:0.72,y:6.55,w:12,h:0.4,fontFace:F.body,fontSize:12.5,italic:true,color:C.muted,margin:0});
  foot(s,N);
}

/* 11 · IS / ISN'T */
{ const s=S(); light(s); kicker(s,'Being straight with you'); title(s,'What it is — and what it isn’t');
  card(s,0.72,2.15,5.9,3.9,'EAF6EF',{line:C.green,shadow:true});
  circ(s,1.0,2.45,0.7,C.green,'✓');
  s.addText('What it IS',{x:1.9,y:2.5,w:4,h:0.5,valign:'middle',fontFace:F.head,fontSize:19,bold:true,color:C.green,margin:0});
  bullets(s,1.05,3.5,5.2,[{t:'The planning & reporting brain'},{t:'Trends, forecasts, capacity advice'},{t:'Audit-ready reports & records'},{t:'Plain-English verdicts and reasons'}],14.5);
  card(s,6.75,2.15,5.9,3.9,'FBEEEE',{line:C.red,shadow:true});
  circ(s,7.03,2.45,0.7,C.red,'✕');
  s.addText('What it ISN’T',{x:7.95,y:2.5,w:4,h:0.5,valign:'middle',fontFace:F.head,fontSize:19,bold:true,color:C.red,margin:0});
  bullets(s,7.1,3.5,5.2,[{t:'The always-on, second-by-second live monitor'},{t:'A replacement for your alerting system'},{t:'A device that fixes outages itself'}],14.5);
  s.addText('Think of it as the analyst that reads the meters and writes the plan — working alongside your live monitoring, not instead of it.',
    {x:0.72,y:6.3,w:12,h:0.6,fontFace:F.body,fontSize:13.5,italic:true,color:C.muted,margin:0,lineSpacingMultiple:1.15});
  foot(s,N);
}

/* 12 · CLOSE */
{ const s=S(); dark(s);
  s.addShape('ellipse',{x:-2.3,y:3.4,w:6.4,h:6.4,fill:{color:'163449'},line:{type:'none'}});
  s.addShape('ellipse',{x:9.9,y:-2.3,w:5.4,h:5.4,fill:{color:'12405A'},line:{type:'none'}});
  s.addText('No black box.',{x:0.8,y:2.5,w:11,h:0.9,fontFace:F.head,fontSize:40,bold:true,color:C.white,margin:0});
  s.addText('Everything it tells you, it can show you why.',{x:0.8,y:3.45,w:11,h:0.8,fontFace:F.head,fontSize:26,color:C.cyan,margin:0});
  s.addText('A fuel gauge, a forecast, and a clear report — for every link you run.',
    {x:0.82,y:4.5,w:10,h:0.6,fontFace:F.body,fontSize:16,color:'C7D6E2',margin:0});
  foot(s,N);
}

p.writeFile({ fileName:'/tmp/claude-0/-home-user-AI-Automation/30bf4683-5df2-597c-b7f6-4ce623c49831/scratchpad/NetPulse-Plain-English.pptx' })
  .then(f=>console.log('WROTE',f)).catch(e=>{console.error(e);process.exit(1);});
