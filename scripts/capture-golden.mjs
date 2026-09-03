import {chromium} from '/opt/node22/lib/node_modules/playwright/index.mjs';
import fs from 'fs';
const OUT='/home/user/AI-Automation/server/tests/NetPulse.Analytics.Tests/golden';
const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
const p=await b.newPage();
await p.goto('file:///home/user/AI-Automation/diff/netpulse.html');
await p.waitForTimeout(1200);

const data=await p.evaluate(()=>{
  // Pin every configuration value the algorithms read, so the fixture is reproducible
  // and the C# port can be handed the identical inputs.
  S.cfg.forecastCI=0.8;
  S.cfg.upgradeLeadDays=42;
  S.cfg.riskWeights={peak:0.30,avg:0.15,trend:0.20,growth:0.15,violations:0.12,anomaly:0.08};
  const cfg={forecastCI:S.cfg.forecastCI,upgradeLeadDays:S.cfg.upgradeLeadDays,riskWeights:S.cfg.riskWeights};

  // deterministic pseudo-random so the fixture never drifts between runs
  let seed=20260903;
  const rnd=()=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed/0x7fffffff;};

  const DAY=86400000, d0=Date.UTC(2026,0,1);
  const mkDaily=(n,f)=>{const a=[];for(let i=0;i<n;i++)a.push({d:d0+i*DAY,p95:f(i,new Date(d0+i*DAY).getUTCDay())});return a;};

  const cases=[];
  const add=(name,daily,p95,cls)=>cases.push({name,cfg,
    daily:daily.map(x=>({d:x.d,p95:x.p95})),p95,cls,
    forecast:JSON.parse(JSON.stringify(forecastFrom(daily,p95,cls)))});

  // 1. flat, no trend
  add('flat',            mkDaily(120,()=>0.40),0.40,'WAN');
  // 2. steady linear growth
  add('linear-growth',   mkDaily(120,i=>0.30+i*0.0025),0.60,'Core');
  // 3. decline
  add('decline',         mkDaily(120,i=>0.80-i*0.002),0.55,'Core');
  // 4. busy weekday / quiet weekend (exercises the deseasonalize + weekday branch)
  add('busy-weekday',    mkDaily(140,(i,dow)=>(dow===0||dow===6?0.12:0.55+i*0.0015)),0.62,'Trading');
  // 5. noisy growth
  add('noisy-growth',    mkDaily(150,i=>Math.max(0,0.25+i*0.003+(rnd()-0.5)*0.09)),0.58,'Internet');
  // 6. step change midway (backtest should prefer the recent window)
  add('step-change',     mkDaily(120,i=>i<70?0.30:0.72),0.70,'Core');
  // 7. already saturated
  add('saturated',       mkDaily(90,i=>0.94+i*0.0004),0.95,'Core');
  // 8. too little history for a trend
  add('too-short',       mkDaily(4,()=>0.5),0.5,'WAN');
  // 9. spiky — a single outlier must not bend the trend (Theil-Sen property)
  add('single-spike',    mkDaily(100,i=>i===50?1.4:0.35),0.36,'Backup');
  // 10. long history
  add('two-years',       mkDaily(730,i=>0.20+i*0.0006),0.55,'Core');

  // --- boundary cases: each one pins a branch that survived mutation testing ---
  // 11-12. slope beyond the ±4 %/day plausibility ceiling (pins SlopeCeiling)
  add('steep-growth-clamped',  mkDaily(60,i=>Math.min(1.5,0.05+i*0.06)),0.90,'Core');
  add('steep-decline-clamped', mkDaily(60,i=>Math.max(0,1.20-i*0.055)),0.30,'Core');
  // 13-15. weekday/weekend ratio either side of the 1.35x + 0.02 branch boundary
  add('weekday-ratio-just-under', mkDaily(120,(i,dow)=>(dow===0||dow===6?0.40:0.52+i*0.0004)),0.52,'WAN');
  add('weekday-ratio-just-over',  mkDaily(120,(i,dow)=>(dow===0||dow===6?0.40:0.57+i*0.0004)),0.57,'WAN');
  add('weekend-hotter',           mkDaily(120,(i,dow)=>(dow===0||dow===6?0.70:0.25+i*0.0004)),0.35,'Backup');
  // 16-17. very low utilization (pins the max(cur,0.03) floor in growthMoM)
  add('near-zero-growing', mkDaily(120,i=>0.004+i*0.00012),0.02,'Management');
  add('near-zero-flat',    mkDaily(120,()=>0.001),0.001,'Management');
  // 18. exactly at the 5-day minimum-history boundary
  add('exactly-five-days', mkDaily(5,i=>0.3+i*0.01),0.34,'WAN');
  // 19. the 8-point backtest boundary
  add('exactly-eight-days',mkDaily(8,i=>0.3+i*0.01),0.37,'WAN');
  // 20. already above every threshold (time-to-threshold must be 0, not negative)
  add('over-100pct', mkDaily(60,i=>1.05+i*0.001),1.08,'Core');

  // 21. raw fitted slope above the ±4 %/day ceiling, on a short unsaturated ramp
  //     (a long steep ramp saturates at the 1.5 clamp and fits flat instead)
  add('slope-above-ceiling', mkDaily(20,i=>0.05+i*0.045),0.83,'Core');
  add('slope-below-floor',   mkDaily(20,i=>1.00-i*0.045),0.12,'Core');
  // 22. 0 < t90 < 15, the only region where max(c0+15, t90) actually binds
  add('upgrade-window-floor', mkDaily(30,i=>0.80+i*0.003),0.80,'Core');
  // 23. weekday/weekend cycle. NOTE: the 7-day rolling median that runs first
  //     flattens a 5-on/2-off cycle completely, so the busy-weekday branch cannot
  //     fire. Kept as a regression witness for that behaviour.
  add('weekly-cycle-9to1', mkDaily(140,(i,dow)=>(dow===0||dow===6?0.10:0.90)),0.90,'Trading');

  // riskScore cases
  const risks=[];
  const addRisk=(name,f)=>risks.push({name,cfg,input:f,result:JSON.parse(JSON.stringify(riskScore(f)))});
  addRisk('idle-low',      {p95:0.05,avg:0.03,pk:0.09,slope:0,     growth:0,    breachesBH:0, anomalies:0, impact:'Low',     speed:1e9,  cls:'Backup'});
  addRisk('busy-critical', {p95:0.88,avg:0.71,pk:0.97,slope:0.002, growth:0.22, breachesBH:9, anomalies:3, impact:'Critical',speed:1e10, cls:'Trading'});
  addRisk('growing-medium',{p95:0.55,avg:0.40,pk:0.68,slope:0.0012,growth:0.31, breachesBH:2, anomalies:1, impact:'Medium',  speed:1e9,  cls:'WAN'});
  addRisk('negative-trend',{p95:0.62,avg:0.48,pk:0.75,slope:-0.003,growth:-0.4, breachesBH:0, anomalies:0, impact:'High',    speed:1e9,  cls:'Core'});
  addRisk('no-peak',       {p95:0.44,avg:0.30,pk:null,slope:0.0008,growth:0.10, breachesBH:1, anomalies:0, impact:'High',    speed:1e9,  cls:'Core'});

  addRisk('all-zero',      {p95:0,avg:0,pk:0,slope:0,growth:0,breachesBH:0,anomalies:0,impact:'Low',speed:1e9,cls:'Backup'});
  addRisk('all-saturated', {p95:1.4,avg:1.3,pk:1.6,slope:0.05,growth:2.0,breachesBH:60,anomalies:40,impact:'Critical',speed:1e9,cls:'Trading'});
  addRisk('negative-growth',{p95:0.5,avg:0.4,pk:0.6,slope:-0.01,growth:-1.5,breachesBH:0,anomalies:0,impact:'Medium',speed:1e9,cls:'WAN'});

  // percentile / statistics primitives
  const samples=[];for(let i=0;i<1000;i++)samples.push(+(rnd()*100).toFixed(6));
  const pct={};for(const q of [0,0.05,0.25,0.5,0.75,0.9,0.95,0.99,0.999,1])pct[q]=percentile(samples,q);
  const rm={};for(const w of [3,7,15])rm[w]=rollingMedian(samples.slice(0,60),w);

  // theilSen directly
  const tsPts=[];for(let i=0;i<80;i++)tsPts.push({x:i,y:0.2+i*0.004+(rnd()-0.5)*0.05});
  const ts={};for(const ci of [0.5,0.8,0.95])ts[ci]=theilSen(tsPts.map(p=>({...p})),ci);

  return {cfg,cases,risks,
    primitives:{samples,percentiles:pct,rollingMedian:rm,
      theilSenPoints:tsPts.map(p=>({x:p.x,y:p.y})),theilSen:ts,
      mean:mean(samples),max:amax(samples),min:Math.min(...samples)}};
});

const w=(f,o)=>{fs.writeFileSync(`${OUT}/${f}`,JSON.stringify(o,null,1));console.log(f,fs.statSync(`${OUT}/${f}`).size,'bytes');};
w('forecast.json',{cfg:data.cfg,cases:data.cases});
w('risk.json',{cfg:data.cfg,cases:data.risks});
w('primitives.json',data.primitives);
console.log('forecast cases:',data.cases.length,'| risk cases:',data.risks.length);
console.log('sample forecast (linear-growth):',JSON.stringify(data.cases[1].forecast).slice(0,220));
await b.close();
