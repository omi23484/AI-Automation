"""Build the fully self-contained in-browser analyzer.

    python tools/build_standalone.py [-o standalone/tcp-forensics-standalone.html]

Fuses the report template (UI unchanged, single-sourced from
report_generator) with the JavaScript analysis engine (webengine.js) and a
drag-and-drop landing screen.  The result is ONE offline HTML file: open
it in a browser, drop a .pcap/.pcapng, and the full forensic report is
computed locally — no Python, no server, nothing leaves the machine.

Model parity between the browser engine and the Python engine is enforced
by tools/parity_check.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tcpforensics.report_generator import _TEMPLATE

ROOT = Path(__file__).resolve().parents[1]

LANDING_HTML = """  <div class="panel" id="landing" style="--i:0">
    <h1>TCP Session, Sequence, SACK &amp; Nanosecond Latency Forensics</h1>
    <p style="color:var(--dim);max-width:760px">Fully offline in-browser
    analyzer. Drop a <b>.pcap</b> / <b>.pcapng</b> capture below — parsing,
    TCP session reconstruction, sequence-space, SACK, loss and nanosecond
    latency analysis all run locally in this page. Nothing leaves this
    machine. (Streamed parsing in a background worker: multi-GB captures
    are practical — memory is bounded by per-session state, not file size.)</p>
    <div id="dropzone" tabindex="0" role="button"
         aria-label="drop a capture file or press Enter to browse">
      <div style="font-size:30px;opacity:.6">⇣</div>
      <div>Drop capture here — or <u>browse</u></div>
      <div class="mut" style="font-size:11px;margin-top:6px">.pcap · .pcapng ·
        nanosecond &amp; microsecond timestamps · Ethernet / SLL / RAW</div>
      <input type="file" id="fileInput" accept=".pcap,.pcapng,.cap"
             style="display:none">
    </div>
    <div id="anProgress" class="mut" style="display:none;margin-top:12px"></div>
    <div id="anBar" style="display:none;height:6px;border-radius:4px;
         background:rgba(120,140,190,.15);margin-top:8px;overflow:hidden">
      <div id="anBarFill" style="height:100%;width:0%;border-radius:4px;
           background:linear-gradient(90deg,var(--accent),var(--accent2));
           transition:width .2s"></div>
    </div>
  </div>
"""

LANDING_CSS = """
/* ---- standalone landing / loader ---- */
body.noModel .nav a{display:none}
#dropzone{border:2px dashed var(--border2);border-radius:14px;padding:44px 20px;
  text-align:center;cursor:pointer;font-family:var(--ui);color:var(--fg);
  transition:border-color .2s,background .2s,transform .2s;margin-top:14px}
#dropzone:hover,#dropzone:focus-visible,#dropzone.drag{
  border-color:var(--accent);background:rgba(57,135,229,.06);
  transform:scale(1.005)}
"""

LOADER_JS = """
/* ---- standalone loader: Web Worker analysis with streamed file reads ---- */
function tfProgressText(file,pkts,tcp,sess,done,total){
  const prog=document.getElementById('anProgress');
  const fill=document.getElementById('anBarFill');
  const pct=total?Math.min(100,100*done/total):0;
  if(fill)fill.style.width=pct.toFixed(1)+'%';
  prog.textContent='Analyzing '+file.name+' ('+(done/1048576).toFixed(0)+' / '+
    (total/1048576).toFixed(0)+' MB, '+pct.toFixed(0)+'%): '+
    pkts.toLocaleString()+' packets, '+tcp.toLocaleString()+' TCP, '+
    sess+' sessions ...';
}
function tfShowModel(model){
  M=model;curSess=null;curTab='overview';TILES_ANIMATED=false;
  document.body.classList.remove('noModel');
  for(const el of document.querySelectorAll('.wrap>.panel'))
    el.style.display=el.id==='landing'?'none':'';
  renderAll();
  window.scrollTo({top:0});
}
function tfFail(file,msg){
  const prog=document.getElementById('anProgress');
  prog.textContent='Could not analyze '+file.name+': '+msg;
}
let tfWorker=null;
function tfGetWorker(){
  if(tfWorker!==null)return tfWorker;
  try{
    const engine=document.getElementById('enginesrc').textContent;
    const shim=engine+';'+
      'onmessage=async e=>{'+
      ' if(e.data&&e.data.cmd==="analyze"){'+
      '  try{'+
      '   const model=await TFEngine.analyze(e.data.file,e.data.name,'+
      '     (p,t,s,d,tot)=>postMessage({type:"progress",p,t,s,d,tot}));'+
      '   postMessage({type:"done",model});'+
      '  }catch(err){postMessage({type:"error",message:String(err&&err.message||err)});}'+
      ' }};';
    tfWorker=new Worker(URL.createObjectURL(
      new Blob([shim],{type:'text/javascript'})));
  }catch(e){tfWorker=false;}          // blob workers unavailable: run inline
  return tfWorker;
}
async function tfAnalyzeFile(file){
  const prog=document.getElementById('anProgress');
  prog.style.display='block';
  document.getElementById('anBar').style.display='block';
  prog.textContent='Reading '+file.name+' ...';
  const w=tfGetWorker();
  if(w){
    w.onmessage=e=>{
      const m=e.data;
      if(m.type==='progress')tfProgressText(file,m.p,m.t,m.s,m.d,m.tot);
      else if(m.type==='done')tfShowModel(m.model);
      else if(m.type==='error')tfFail(file,m.message);
    };
    w.postMessage({cmd:'analyze',file,name:file.name});
    return;
  }
  try{                                 // main-thread fallback (still streamed)
    const model=await TFEngine.analyze(file,file.name,
      (p,t,s,d,tot)=>tfProgressText(file,p,t,s,d,tot));
    tfShowModel(model);
  }catch(e){tfFail(file,e.message);console.error(e);}
}
(function(){
  const dz=document.getElementById('dropzone');
  const fi=document.getElementById('fileInput');
  dz.addEventListener('click',()=>fi.click());
  dz.addEventListener('keydown',e=>{
    if(e.key==='Enter'||e.key===' '){e.preventDefault();fi.click();}});
  fi.addEventListener('change',()=>{if(fi.files[0])tfAnalyzeFile(fi.files[0]);});
  for(const ev of ['dragover','dragenter'])
    dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add('drag');});
  for(const ev of ['dragleave','drop'])
    dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove('drag');});
  dz.addEventListener('drop',e=>{
    const f=e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files[0];
    if(f)tfAnalyzeFile(f);
  });
  // also accept a drop anywhere on the page
  document.addEventListener('dragover',e=>e.preventDefault());
  document.addEventListener('drop',e=>{
    e.preventDefault();
    const f=e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files[0];
    if(f)tfAnalyzeFile(f);
  });
})();
"""


def build() -> str:
    html = _TEMPLATE
    # empty embedded model; the loader assigns M after in-browser analysis
    html = html.replace("%%DATA%%", "null")
    html = html.replace(
        "const M = JSON.parse(document.getElementById('data').textContent);",
        "let M = null;\n"
        "try{const _d=document.getElementById('data').textContent.trim();\n"
        "  M=(_d&&_d!=='null')?JSON.parse(_d):null;}catch(_e){M=null;}")
    html = html.replace("<title>TCP Forensics Report</title>",
                        "<title>TCP Forensics Analyzer</title>")
    # landing styles
    html = html.replace("</style>", LANDING_CSS + "</style>", 1)
    # landing panel + a "new capture" affordance in the nav
    html = html.replace('<div class="wrap">',
                        '<div class="wrap">\n' + LANDING_HTML, 1)
    html = html.replace('<span class="spacer"></span>',
                        '<a onclick="location.reload()" title="analyze another '
                        'capture">↺ new capture</a>\n  '
                        '<span class="spacer"></span>', 1)
    # boot: with no model, show only the landing panel
    boot = ("if(M){renderAll();}\n"
            "else{document.body.classList.add('noModel');\n"
            "  for(const el of document.querySelectorAll('.wrap>.panel'))\n"
            "    if(el.id!=='landing')el.style.display='none';\n"
            "  renderNav();}\n")
    marker = "\nrenderAll();\n</script>"
    assert marker in html, "template boot marker not found"
    html = html.replace(marker, "\n" + boot + "</script>")
    # engine + loader
    engine = (ROOT / "tcpforensics" / "webengine.js").read_text(encoding="utf-8")
    assert "</script" not in engine, "engine source may not contain </script"
    inject = ("<script id=\"enginesrc\">\n" + engine + "\n</script>\n"
              "<script>\n" + LOADER_JS + "\n</script>\n</body>")
    html = html.replace("</body>", inject, 1)
    return html


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output",
                    default=str(ROOT / "standalone" /
                                "tcp-forensics-standalone.html"))
    args = ap.parse_args()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    print(f"standalone analyzer written to {out} "
          f"({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
