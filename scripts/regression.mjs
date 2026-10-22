// One runnable regression check for diff/netpulse.html — drives the real page in Chromium.
//   node scripts/regression.mjs            (exit code 1 on any failure)
// Covers: every view renders; every export builds; maintenance is evaluated live; link merge;
// workspaces are isolated; a refused storage write rolls back; the multi-link PDF/Excel pack
// agrees with the legacy Threshold Report's printed numbers; the offline invariant holds.
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
let chromium;
try{({chromium}=await import('playwright'));}catch(e){({chromium}=await import('/opt/node22/lib/node_modules/playwright/index.mjs'));}
const HTML=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../diff/netpulse.html');
const exe=process.env.CHROMIUM||(fs.existsSync('/opt/pw-browsers/chromium')?'/opt/pw-browsers/chromium':undefined);

let fails=0;const check=(name,ok,detail='')=>{console.log(`${ok?'  ok  ':' FAIL '} ${name}${detail?'  — '+detail:''}`);if(!ok)fails++;};
const b=await chromium.launch({executablePath:exe});
const ctx=await b.newContext({timezoneId:'Asia/Kolkata',locale:'en-US'});
const p=await ctx.newPage();
const errs=[];p.on('pageerror',e=>errs.push('pageerror: '+e.message));
p.on('console',m=>{if(m.type()==='error'&&!/favicon/.test(m.text()))errs.push('console: '+m.text());});
p.on('dialog',d=>d.accept());
await p.goto('file://'+HTML);await p.waitForTimeout(1200);

// ---- deterministic dataset: 5 links, 200 days hourly, per-class thresholds, off-hours bands, a maintenance window
await p.evaluate(async()=>{
  let seed=424242;const rnd=()=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed/0x7fffffff;};
  S.samples=[];S.maintenance=[];S.ifmeta={};S.ifinfo={};S.analytics=null;
  S.cfg.institution='Acme Networks';S.cfg.thresholdsOff={warn:0.75,high:0.88,crit:0.96};
  S.cfg.upgradeRule={utilPct:80,days:5,businessHoursOnly:true,lookbackDays:90,mode:'recommend'};
  const HR=3600000,t0=new Date(2026,2,1).getTime(),N=200*24;
  [['LON-Core-01','Ethernet1/1',10e9,0.62,0.30],['LON-Core-02','Ethernet1/2',10e9,0.30,0.20],['NYC-Leaf-11','Ethernet2/3',1e9,0.70,0.35],
   ['NYC-Edge-05','Gi0/0/1',1e9,0.20,0.10],['SIN-Bkp-01','Te1/0/1',10e9,0.55,0.50]].forEach(([dev,intf,sp,base,amp])=>{
    for(let k=0;k<N;k++){const ts=t0+k*HR,d=new Date(ts),bh=d.getDay()>=1&&d.getDay()<=5&&d.getHours()>=9&&d.getHours()<17;
      const u=Math.max(0.01,base*(bh?1:0.55)*(1+k/N*0.35)+amp*(rnd()-0.5)*0.9+(rnd()>0.985?0.25:0)),tx=u*sp*(0.85+rnd()*0.3),rx=u*sp*(0.4+rnd()*0.3);
      S.samples.push({ifid:dev+'|'+intf,dev,intf,ts,tx,rx,ptx:null,prx:null,pu:null,speed:sp,speedTx:sp,speedRx:sp,util:Math.max(tx,rx)/sp,batch:'b1'});}
  });
  // persist exactly as an upload would, so workspace switches reload real stored data
  S.batches=[{id:'b1',file:'seed.xlsx',ts:Date.now(),who:'t',rows:S.samples.length,added:S.samples.length,coverage:[t0,t0+N*HR],checksum:'c',src:'xlsx',intervalNote:'',entities:5,map:{},headers:[]}];
  await IDB.put('spl:b1',S.samples);await IDB.put('batches',S.batches);
  S.analytics=null;
});

console.log('views');
for(const v of ['exec','noc','twin','capacity','upgrade','trends','anomalies','historical','links','uploads','maintenance','reports','audit','admin']){
  const before=errs.length;await p.evaluate(v=>go(v),v);await p.waitForTimeout(120);
  check('renders '+v,errs.length===before);}
await p.evaluate(()=>{const a=A();go('intf',{id:a.ifs[0].ifid});});await p.waitForTimeout(300);
check('renders a link page',errs.length===0,errs[0]||'');

console.log('exports build');
const ex=await p.evaluate(async()=>{
  const got=[];window.dl=(blob,name)=>got.push({name,size:blob.size});const out={};
  const t=(k,f)=>{try{f();out[k]='ok';}catch(e){out[k]=e.message;}};
  const id=A().ifs[0].ifid;
  t('policy xlsx',()=>genUpgradePolicyXlsx('all'));t('regulatory xlsx',()=>genRegReport('all','xlsx'));
  t('threshold report html',()=>breachReportHTML(A().ifs[0],'all','warn'));t('link html',()=>exportLink(id,'html'));
  out.files=got.length;return out;
});
for(const [k,v] of Object.entries(ex))if(k!=='files')check('export '+k,v==='ok',v==='ok'?'':v);

console.log('maintenance is evaluated live (v60)');
const m=await p.evaluate(()=>{
  const r0=A().ifs.find(r=>r.dev==='LON-Core-01'),endFull=r0.end;
  S.maintenance=[{scope:'all',target:'',start:endFull-30*86400000,end:endFull+1,reason:'t',who:'t'}];S.analytics=null;
  const r1=A().ifs.find(r=>r.dev==='LON-Core-01'),shortened=r1.end<endFull,excl=r1.excluded&&r1.excluded.n>0;
  S.maintenance=[];S.analytics=null;const r2=A().ifs.find(r=>r.dev==='LON-Core-01');
  return {shortened,excl,restored:r2.end===endFull&&r2.count===r0.count};
});
check('a window hides data and says so',m.shortened&&m.excl);check('deleting the window restores it',m.restored);

console.log('link merge (v61)');
const lm=await p.evaluate(()=>{const before=S.samples.length,r=applyLinkMerge({'NYC-Edge-05|Gi0/0/1':'SIN-Bkp-01|Te1/0/1'});
  const ok=!S.samples.some(x=>x.ifid==='NYC-Edge-05|Gi0/0/1');return {moved:r.moved,dupes:r.dupes,ok,left:S.samples.length,before};});
check('samples re-keyed, duplicates skipped',lm.ok&&lm.moved+lm.dupes===200*24,`moved ${lm.moved}, duplicate ${lm.dupes}`);

console.log('workspaces (v62)');
const ws=await p.evaluate(async()=>{
  const keep=S.samples.length;await wsSave([...wsList(),{id:'ws_t',name:'Test'}]);await wsSwitch('ws_t');
  const fresh={samples:S.samples.length,ws:S.ws};await wsSwitch('default');
  return {fresh,back:S.samples.length===keep};
});
check('a new workspace starts empty',ws.fresh.samples===0&&ws.fresh.ws==='ws_t');check('switching back restores the data',ws.back);

console.log('storage safety (v63)');
const sq=await p.evaluate(async()=>{
  const real=IDB.put;IDB.put=(k,v)=>String(k).startsWith('spl:')?Promise.reject(new DOMException('x','QuotaExceededError')):real(k,v);
  const n0=S.samples.length;let msg=null;
  try{await commitOneFile({parsed:{name:'f',rowCount:1,headers:[]},built:{samples:[{ifid:'z|z',dev:'z',intf:'z',ts:1,util:.1}],info:{}}},{},new Set());}catch(e){msg=e.message;}
  IDB.put=real;return {rolledBack:S.samples.length===n0,said:/storage is full/i.test(msg||'')};
});
check('a refused write rolls back and says why',sq.rolledBack&&sq.said);

console.log('multi-link reports (v64)');
await p.evaluate(()=>{S.analytics=null;});
const bk=await p.evaluate(async()=>{
  const list=[...A().ifs],w=bulkWindow(list,183),o={...w,hours:'all',bands:'warn',graph:true,byDate:true,byDateTime:true};
  const preps=list.map(r=>bulkPrep(r,o)),rows=[];
  for(const P of preps){
    const r=P.r,html=breachReportHTML(r,'all','warn');                       // the legacy, printed number
    const printed=+html.match(/class="n" style="color:#b45309">([\d,]+)<\/div><div class="t">At\/above Warning/)[1].replace(/,/g,'');
    const own=hitCalc(r,{winStart:Math.max(r.start,r.end-183*86400000),winEnd:r.end,hours:'all',bands:'warn'});
    const byDay=Object.values(P.H.byDay).reduce((s,d)=>s+d.n,0);
    rows.push({link:r.dev,printed,own:own.breaches.length,bulk:P.total,byDay});}
  const sheets=bulkXlsx(preps,o),dt=sheets.filter(s=>s.name.startsWith('Hits by Date-Time')).reduce((s,x)=>s+x.rows.length-1,0);
  const pdfs=await bulkPdfFiles(preps,o,'each'),one=await bulkPdfFiles(preps,o,'one');
  const head=async f=>{const u=new Uint8Array(await f.blob.slice(0,5).arrayBuffer());return String.fromCharCode(...u);};
  const xl=await xlsxBlobZ(sheets),xh=new Uint8Array(await xl.slice(0,2).arrayBuffer());
  return {rows,dt,total:preps.reduce((s,P)=>s+P.total,0),pdfN:pdfs.length,pdfHead:await head(pdfs[0]),oneHead:await head(one[0]),xlsxZip:String.fromCharCode(...xh)==='PK',
    charts:sheets.reduce((s,x)=>s+(x.charts||[]).length,0),links:list.length};
});
check('bulk hit count == legacy Threshold Report, every link',bk.rows.every(r=>r.printed===r.bulk&&r.own===r.bulk),bk.rows.map(r=>`${r.printed}/${r.bulk}`).join(' '));
check('hits-by-date and date-time rows both sum to the hit total',bk.rows.every(r=>r.byDay===r.bulk)&&bk.dt===bk.total,`${bk.total} hits`);
check('one valid PDF per link + one combined',bk.pdfN===bk.links&&bk.pdfHead==='%PDF-'&&bk.oneHead==='%PDF-');
check('Excel is a zip with a chart per link + the top-links chart',bk.xlsxZip&&bk.charts===bk.links+1,`${bk.charts} charts`);

console.log('offline invariant');
const html=fs.readFileSync(HTML,'utf8');
const bad=html.split('\n').map((l,i)=>[i+1,l]).filter(([,l])=>/https?:\/\/(?!schemas\.openxmlformats|www\.w3\.org|schemas\.microsoft)|fonts\.google|cdn\.|<script[^>]*src=|<link |@import|\bfetch\(|XMLHttpRequest|WebSocket|EventSource/.test(l)&&!/^\s*(\/\/|\*|\/\*|\(Google)/.test(l.trim())&&!/NEVER|never introduce|Never introduce|invariant|CDN URLs/i.test(l));
check('no network references',bad.length===0,bad.slice(0,2).map(([n,l])=>n+': '+l.trim().slice(0,70)).join(' | '));
check('page raised no console / page errors',errs.length===0,errs.slice(0,2).join(' | '));

await b.close();
console.log(fails?`\n${fails} check(s) FAILED`:'\nall checks passed');
process.exit(fails?1:0);
