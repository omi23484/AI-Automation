/* tcpforensics browser engine — a faithful JavaScript port of the Python
 * analysis pipeline (capture_reader, tcp_sequence, tcp_session, tcp_ack,
 * tcp_sack, tcp_loss, tcp_retransmission, tcp_window, statistics,
 * verdicts, artifacts, analyzer).  It consumes an ArrayBuffer of a
 * pcap/pcapng file and produces the SAME model object the HTML report
 * consumes.  Parity with the Python engine is enforced by
 * tools/parity_check.py, which runs both on identical captures and
 * deep-compares the models.
 *
 * Numeric rules: all timestamps are converted to capture-relative integer
 * nanoseconds at parse time (exact in a double for captures < ~104 days);
 * absolute wall-clock values are kept as BigInt only for header strings.
 * Sequence numbers are unwrapped into a 64-bit-style space anchored near
 * 32-bit values (< 2^53).  Variance uses BigInt.
 */
"use strict";
const TFEngine = (() => {

/* ------------------------------------------------------------- helpers */
const FIN=1, SYN=2, RST=4, PSH=8, ACK=16, URG=32, ECE=64, CWR=128;
const FLAG_NAMES=[[SYN,"SYN"],[FIN,"FIN"],[RST,"RST"],[PSH,"PSH"],
                  [ACK,"ACK"],[URG,"URG"],[ECE,"ECE"],[CWR,"CWR"]];
function flagsToStr(f){
  const out=FLAG_NAMES.filter(([b])=>f&b).map(([,n])=>n);
  return out.length?out.join("/"):"-";
}
const CRC_TABLE=(()=>{const t=new Int32Array(256);
  for(let n=0;n<256;n++){let c=n;
    for(let k=0;k<8;k++)c=c&1?0xEDB88320^(c>>>1):c>>>1;t[n]=c;}return t;})();
function crc32(bytes,off,len){
  let c=0xFFFFFFFF;
  for(let i=0;i<len;i++)c=CRC_TABLE[(c^bytes[off+i])&0xFF]^(c>>>8);
  return (c^0xFFFFFFFF)>>>0;
}
const M32=4294967296, M31=2147483648;
function unwrap32(value,reference){
  if(reference==null)return value;
  let candidate=Math.floor(reference/M32)*M32+(value%M32);
  if(candidate+M31<reference)candidate+=M32;
  else if(candidate>reference+M31)candidate-=M32;
  return candidate;
}
class SeqUnwrapper{
  constructor(){this.reference=null;}
  unwrap(raw){const v=unwrap32(raw,this.reference);
    if(this.reference==null||v>this.reference)this.reference=v;return v;}
  unwrapNoAdvance(raw){return unwrap32(raw,this.reference);}
}
/* bisect helpers (Python bisect_left / bisect_right semantics) */
function bisectLeft(a,x){let lo=0,hi=a.length;
  while(lo<hi){const m=(lo+hi)>>1;if(a[m]<x)lo=m+1;else hi=m;}return lo;}
function bisectRight(a,x){let lo=0,hi=a.length;
  while(lo<hi){const m=(lo+hi)>>1;if(x<a[m])hi=m;else lo=m+1;}return lo;}

class IntervalSet{
  constructor(){this.starts=[];this.ends=[];}
  get length(){return this.starts.length;}
  intervals(){return this.starts.map((s,i)=>[s,this.ends[i]]);}
  totalBytes(){let t=0;for(let i=0;i<this.starts.length;i++)t+=this.ends[i]-this.starts[i];return t;}
  add(start,end){
    if(end<=start)return;
    const i=bisectLeft(this.ends,start), j=bisectRight(this.starts,end);
    if(i<j){start=Math.min(start,this.starts[i]);end=Math.max(end,this.ends[j-1]);
      this.starts.splice(i,j-i);this.ends.splice(i,j-i);}
    this.starts.splice(i,0,start);this.ends.splice(i,0,end);
  }
  removeBelow(boundary){
    const i=bisectRight(this.ends,boundary);
    if(i){this.starts.splice(0,i);this.ends.splice(0,i);}
    if(this.starts.length&&this.starts[0]<boundary)this.starts[0]=boundary;
  }
  overlap(start,end){
    const out=[];let i=bisectRight(this.ends,start);
    while(i<this.starts.length&&this.starts[i]<end){
      out.push([Math.max(start,this.starts[i]),Math.min(end,this.ends[i])]);i++;}
    return out;
  }
  containsRange(start,end){
    const i=bisectRight(this.ends,start);
    return i<this.starts.length&&this.starts[i]<=start&&this.ends[i]>=end;
  }
  gapsBetween(lo,hi){
    const holes=[];let cur=lo,i=bisectRight(this.ends,lo);
    while(cur<hi&&i<this.starts.length&&this.starts[i]<hi){
      if(this.starts[i]>cur)holes.push([cur,this.starts[i]]);
      cur=Math.max(cur,this.ends[i]);i++;}
    if(cur<hi)holes.push([cur,hi]);
    return holes;
  }
}
class SegmentIndex{
  constructor(){this.keys=[];this.maxLen=0;this._starts=[];}
  add(start,end,segId){
    const k=[start,end,segId];
    const i=bisectRight(this._starts,start);
    this.keys.splice(i,0,k);this._starts.splice(i,0,start);
    this.maxLen=Math.max(this.maxLen,end-start);
  }
  overlapping(start,end){
    const out=[];const lo=bisectLeft(this._starts,start-this.maxLen);
    for(let i=lo;i<this.keys.length;i++){
      const [s,e,sid]=this.keys[i];
      if(s>=end)break;
      if(e>start)out.push([s,e,sid]);
    }
    return out;
  }
}

/* ---------------------------------------------------------- statistics */
function percentile(sorted,p){
  if(!sorted.length)return null;
  if(p<=0)return sorted[0];
  if(p>=100)return sorted[sorted.length-1];
  const rank=Math.ceil(p/100*sorted.length);
  return sorted[Math.max(0,rank-1)];
}
function bigintSqrt(n){                        // isqrt for BigInt
  if(n<2n)return n;
  let x=n,y=(x+1n)/2n;
  while(y<x){x=y;y=(x+n/x)/2n;}
  return x;
}
function summarize(values,minP999=100){
  if(!values.length)return {count:0};
  const vals=[...values].sort((a,b)=>a-b);
  const n=vals.length;
  let total=0;for(const v of vals)total+=v;
  const mean=Math.floor(total/n);
  let varB=0n;
  if(n>1){const mB=BigInt(mean);
    for(const v of vals){const d=BigInt(v)-mB;varB+=d*d;}
    varB/=BigInt(n);}
  const out={count:n,min:vals[0],max:vals[n-1],mean,
    median:percentile(vals,50),p50:percentile(vals,50),
    p90:percentile(vals,90),p95:percentile(vals,95),p99:percentile(vals,99),
    stddev:Number(bigintSqrt(varB))};
  if(n>=minP999)out.p999=percentile(vals,99.9);
  return out;
}
function histogram(values,buckets=40){
  if(!values.length)return {buckets:[],counts:[],cdf:[]};
  const vals=[...values].sort((a,b)=>a-b);
  const lo=vals[0],hi=vals[vals.length-1];
  if(hi===lo)return {buckets:[lo],counts:[vals.length],cdf:[[lo,100.0]]};
  const width=Math.max(1,Math.floor((hi-lo)/buckets));
  const counts=new Array(buckets+1).fill(0);
  for(const v of vals)counts[Math.min(buckets,Math.floor((v-lo)/width))]++;
  const edges=counts.map((_,i)=>lo+i*width);
  const n=vals.length,cdf=[],step=Math.max(1,Math.floor(n/200));
  for(let i=0;i<n;i+=step)cdf.push([vals[i],Math.round((i+1)*100000/n)/1000]);
  cdf.push([vals[n-1],100.0]);
  return {buckets:edges,counts,cdf};
}

/* --------------------------------------------------------- time helpers */
function fmtNsUtc(absNsBig){
  if(absNsBig==null)return "-";
  const sec=absNsBig/1000000000n, frac=absNsBig%1000000000n;
  const d=new Date(Number(sec)*1000);
  const p=(x,w)=>String(x).padStart(w,"0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth()+1,2)}-${p(d.getUTCDate(),2)} `+
         `${p(d.getUTCHours(),2)}:${p(d.getUTCMinutes(),2)}:${p(d.getUTCSeconds(),2)}`+
         `.${p(frac,9)}`;
}
function fmtDurationNs(dur){
  if(dur==null)return "-";
  const sign=dur<0?"-":"";const a=Math.abs(dur);
  const sec=Math.floor(a/1e9),frac=a-sec*1e9;
  return `${sign}${sec}.${String(frac).padStart(9,"0")} s`;
}

/* ------------------------------------------------------- capture reader */
const LT_NULL=0, LT_ETH=1, LT_RAW=101, LT_SLL=113, LT_SLL2=276;

function macStr(u8,off){
  const h=[];for(let i=0;i<6;i++)h.push(u8[off+i].toString(16).padStart(2,"0"));
  return h.join(":");
}
function v6Str(u8,off){
  const g=[];for(let i=0;i<8;i++)
    g.push(((u8[off+i*2]<<8)|u8[off+i*2+1]).toString(16));
  // canonical :: compression (best-effort match of Python ipaddress)
  let best=-1,bestLen=0,cur=-1,curLen=0;
  for(let i=0;i<8;i++){
    if(g[i]==="0"){if(cur<0)cur=i;curLen++;
      if(curLen>bestLen){best=cur;bestLen=curLen;}}
    else {cur=-1;curLen=0;}
  }
  if(bestLen>1){
    const a=g.slice(0,best).join(":"),b=g.slice(best+bestLen).join(":");
    return a+"::"+b;
  }
  return g.join(":");
}

/* Chunked byte source: constant-memory streaming over a File/Blob (8 MB
 * slices) or a whole ArrayBuffer.  The reader keeps a rolling window of
 * unparsed bytes, so a 1 GB capture never needs a 1 GB allocation. */
const STREAM_CHUNK=8*1024*1024;
const MAX_RECORD=128*1024*1024;          // sanity bound for one record/block
class ChunkedSource{
  constructor(fileOrBuf){
    this.isBlob=typeof Blob!=="undefined"&&fileOrBuf instanceof Blob;
    this.buf=this.isBlob?null:new Uint8Array(fileOrBuf);
    this.size=this.isBlob?fileOrBuf.size:this.buf.length;
    this.file=this.isBlob?fileOrBuf:null;
  }
  async read(off,len){
    if(!this.isBlob)return this.buf.subarray(off,Math.min(this.size,off+len));
    const ab=await this.file.slice(off,Math.min(this.size,off+len)).arrayBuffer();
    return new Uint8Array(ab);
  }
}
class RollingWindow{
  constructor(src){this.src=src;this.buf=new Uint8Array(0);this.p=0;
    this.fileOff=0;this.dv=new DataView(this.buf.buffer);}
  get avail(){return this.buf.length-this.p;}
  get consumedBytes(){return this.fileOff-this.avail;}
  async ensure(n){                        // true if n bytes are available
    if(n>MAX_RECORD)return false;
    while(this.avail<n){
      if(this.fileOff>=this.src.size)return false;
      const chunk=await this.src.read(this.fileOff,
        Math.max(STREAM_CHUNK,n-this.avail));
      if(!chunk.length)return false;
      this.fileOff+=chunk.length;
      const merged=new Uint8Array(this.avail+chunk.length);
      merged.set(this.buf.subarray(this.p),0);
      merged.set(chunk,this.avail);
      this.buf=merged;this.p=0;
      this.dv=new DataView(merged.buffer,merged.byteOffset,merged.byteLength);
    }
    return true;
  }
  advance(n){this.p+=n;}
}

class CaptureReader{
  constructor(){
    this.u8=null;this.dv=null;           // current window (for decodeTcp)
    this.fileFormat="unknown";
    this.resolutions=[];                 // ticksPerSecond numbers
    this.packetCount=0;this.tcpCount=0;
    this.snaplen=null;this.truncatedFrames=0;this.warnings=[];
    this.firstAbsNs=null;this.lastAbsNs=null;   // BigInt
  }
  notePacket(absNs){
    if(this.firstAbsNs==null||absNs<this.firstAbsNs)this.firstAbsNs=absNs;
    if(this.lastAbsNs==null||absNs>this.lastAbsNs)this.lastAbsNs=absNs;
  }
  resLabel(tps){
    if(tps>=1e9)return "1 ns";
    if(tps===1e6)return "1 µs";
    if(tps===1e3)return "1 ms";
    return `1/${tps} s`;
  }
  nsPerTick(tps){return Math.max(1,Math.ceil(1e9/tps));}

  async *frames(src){
    const w=new RollingWindow(src);
    this.window=w;
    if(!await w.ensure(4))throw new Error("file too short to be a capture");
    this.u8=w.buf;this.dv=w.dv;
    const magicBE=w.dv.getUint32(w.p,false);
    if(magicBE===0xA1B2C3D4||magicBE===0xD4C3B2A1||
       magicBE===0xA1B23C4D||magicBE===0x4D3CB2A1)
      yield* this.readPcap(w,magicBE);
    else if(magicBE===0x0A0D0D0A)
      yield* this.readPcapng(w);
    else throw new Error("unrecognized capture magic 0x"+
      magicBE.toString(16).toUpperCase().padStart(8,"0"));
  }
  async *readPcap(w,magicBE){
    this.fileFormat="pcap";
    const little=(magicBE===0xD4C3B2A1||magicBE===0x4D3CB2A1);
    const nano=(magicBE===0xA1B23C4D||magicBE===0x4D3CB2A1);
    this.resolutions=[nano?1e9:1e6];
    if(!await w.ensure(24))throw new Error("truncated pcap global header");
    this.snaplen=w.dv.getUint32(w.p+16,little);
    const linktype=w.dv.getUint32(w.p+20,little);
    w.advance(24);
    let frameNo=0;
    for(;;){
      if(!await w.ensure(16))break;
      const o=w.p;
      const tsSec=w.dv.getUint32(o,little), tsFrac=w.dv.getUint32(o+4,little);
      const caplen=w.dv.getUint32(o+8,little), origlen=w.dv.getUint32(o+12,little);
      if(!await w.ensure(16+caplen)){
        this.warnings.push("capture file ends mid-record — the final packet "+
          "was discarded (interrupted or copied-while-writing capture)");
        break;
      }
      frameNo++;
      const absNs=BigInt(tsSec)*1000000000n+BigInt(nano?tsFrac:tsFrac*1000);
      const truncated=caplen<origlen;
      if(truncated)this.truncatedFrames++;
      this.packetCount++;this.notePacket(absNs);
      this.u8=w.buf;this.dv=w.dv;         // window may have re-anchored
      yield {frameNo,absNs,linktype,off:w.p+16,caplen,truncated};
      w.advance(16+caplen);
    }
  }
  async *readPcapng(w){
    this.fileFormat="pcapng";
    let little=true,frameNo=0;
    let interfaces=[];                       // [{linktype, tps}]
    for(;;){
      if(!await w.ensure(8))break;
      let btype=w.dv.getUint32(w.p,little), blen=w.dv.getUint32(w.p+4,little);
      if(w.dv.getUint32(w.p,false)===0x0A0D0D0A){    // SHB (palindromic type)
        if(!await w.ensure(24))break;
        const bom=w.dv.getUint32(w.p+8,true);
        little=(bom===0x1A2B3C4D);
        blen=w.dv.getUint32(w.p+4,little);
        interfaces=[];
        if(blen<28||!await w.ensure(blen))break;
        w.advance(blen);continue;
      }
      if(blen<12||blen%4){
        this.warnings.push(`corrupt pcapng block (type 0x${btype.toString(16)
          .toUpperCase().padStart(8,"0")}, length ${blen}) after `+
          `${this.packetCount} packets — remainder of the file skipped`);
        break;
      }
      if(!await w.ensure(blen)){
        this.warnings.push("capture file ends mid-block — the final block "+
          "was discarded (interrupted or copied-while-writing capture)");
        break;
      }
      const body=w.p+8, bodyLen=blen-12;
      const dv=w.dv,u8=w.buf;
      if(btype===0x00000001){                       // IDB
        const linktype=dv.getUint16(body,little);
        const snap=dv.getUint32(body+4,little);
        if(this.snaplen==null||(snap&&snap<this.snaplen))this.snaplen=snap||null;
        let tps=1e6, o=body+8;
        while(o+4<=body+bodyLen){
          const code=dv.getUint16(o,little), olen=dv.getUint16(o+2,little);
          if(code===0)break;
          if(code===9&&olen>=1){
            const b=u8[o+4];
            tps=(b&0x80)?Math.pow(2,b&0x7F):Math.pow(10,b);
          }
          o+=4+((olen+3)&~3);
        }
        interfaces.push({linktype,tps});
        this.resolutions.push(tps);
      } else if(btype===0x00000006){                // EPB
        if(bodyLen>=20){
          const ifId=dv.getUint32(body,little);
          const tsHi=dv.getUint32(body+4,little), tsLo=dv.getUint32(body+8,little);
          const caplen=dv.getUint32(body+12,little), origlen=dv.getUint32(body+16,little);
          if(ifId<interfaces.length){
            const {linktype,tps}=interfaces[ifId];
            const ticks=BigInt(tsHi)*4294967296n+BigInt(tsLo);
            const absNs=tps===1e9?ticks:(ticks*1000000000n)/BigInt(tps);
            frameNo++;
            const truncated=caplen<origlen;
            if(truncated)this.truncatedFrames++;
            this.packetCount++;this.notePacket(absNs);
            this.u8=w.buf;this.dv=w.dv;
            yield {frameNo,absNs,linktype,off:body+20,
                   caplen:Math.min(caplen,bodyLen-20),truncated};
          }
        }
      } else if(btype===0x00000003){                // SPB — no timestamp
        frameNo++;this.packetCount++;
      }
      w.advance(blen);
    }
  }
}

/* --------------------------------------------------------- tcp decoding */
function decodeTcp(rd,f){
  const u8=rd.u8,dv=rd.dv;
  const end=f.off+f.caplen;
  try{
    if(f.linktype===LT_ETH){
      if(f.caplen<14)return null;
      const dstMac=macStr(u8,f.off), srcMac=macStr(u8,f.off+6);
      let ethertype=dv.getUint16(f.off+12,false), o=f.off+14, vlan=null;
      while((ethertype===0x8100||ethertype===0x88A8)&&o+4<=end){
        if(vlan==null)vlan=dv.getUint16(o,false)&0x0FFF;
        ethertype=dv.getUint16(o+2,false);o+=4;
      }
      const l2=[srcMac,dstMac,vlan];
      if(ethertype===0x0800)return decodeIpv4(rd,f,o,end,l2);
      if(ethertype===0x86DD)return decodeIpv6(rd,f,o,end,l2);
      return null;
    }
    const noL2=[null,null,null];
    if(f.linktype===LT_RAW)return decodeIpAuto(rd,f,f.off,end);
    if(f.linktype===LT_NULL){
      if(f.caplen<4)return null;
      return decodeIpAuto(rd,f,f.off+4,end);
    }
    if(f.linktype===LT_SLL){
      if(f.caplen<16)return null;
      const proto=dv.getUint16(f.off+14,false);
      if(proto===0x0800)return decodeIpv4(rd,f,f.off+16,end,noL2);
      if(proto===0x86DD)return decodeIpv6(rd,f,f.off+16,end,noL2);
      return null;
    }
    if(f.linktype===LT_SLL2){
      if(f.caplen<20)return null;
      const proto=dv.getUint16(f.off,false);
      if(proto===0x0800)return decodeIpv4(rd,f,f.off+20,end,noL2);
      if(proto===0x86DD)return decodeIpv6(rd,f,f.off+20,end,noL2);
      return null;
    }
    return null;
  }catch(e){return null;}
}
function decodeIpAuto(rd,f,o,end){
  if(o>=end)return null;
  const ver=rd.u8[o]>>4, noL2=[null,null,null];
  if(ver===4)return decodeIpv4(rd,f,o,end,noL2);
  if(ver===6)return decodeIpv6(rd,f,o,end,noL2);
  return null;
}
function decodeIpv4(rd,f,o,end,l2){
  const u8=rd.u8,dv=rd.dv;
  if(end-o<20||(u8[o]>>4)!==4)return null;
  const ihl=(u8[o]&0x0F)*4;
  if(ihl<20||end-o<ihl)return null;
  const totalLen=dv.getUint16(o+2,false);
  const ipId=dv.getUint16(o+4,false);
  const flagsFrag=dv.getUint16(o+6,false);
  if(flagsFrag&0x1FFF)return null;
  const ttl=u8[o+8];
  if(u8[o+9]!==6)return null;
  const src=`${u8[o+12]}.${u8[o+13]}.${u8[o+14]}.${u8[o+15]}`;
  const dst=`${u8[o+16]}.${u8[o+17]}.${u8[o+18]}.${u8[o+19]}`;
  const availTotal=Math.min(totalLen,end-o);
  const tcpOff=o+ihl, tcpAvail=Math.max(0,availTotal-ihl);
  return decodeTcpHeader(rd,f,src,dst,tcpOff,tcpAvail,totalLen,
                         totalLen-ihl,ipId,ttl,l2);
}
function decodeIpv6(rd,f,o,end,l2){
  const u8=rd.u8,dv=rd.dv;
  if(end-o<40||(u8[o]>>4)!==6)return null;
  const payloadLen=dv.getUint16(o+4,false);
  let nxt=u8[o+6];
  const hop=u8[o+7];
  const src=v6Str(u8,o+8), dst=v6Str(u8,o+24);
  let oo=o+40;
  while((nxt===0||nxt===43||nxt===60)&&end-oo>=8){
    const hdrLen=(u8[oo+1]+1)*8;
    nxt=u8[oo];oo+=hdrLen;
  }
  if(nxt!==6)return null;
  const declaredEnd=payloadLen?o+40+payloadLen:end;
  const tcpAvail=Math.max(0,Math.min(declaredEnd,end)-oo);
  return decodeTcpHeader(rd,f,src,dst,oo,tcpAvail,40+payloadLen,
                         (40+payloadLen)-(oo-o),null,hop,l2);
}
function decodeTcpHeader(rd,f,src,dst,o,avail,ipTotalLen,declaredPayload,
                         ipId,ttl,l2){
  const u8=rd.u8,dv=rd.dv;
  if(avail<20)return null;
  const sport=dv.getUint16(o,false), dport=dv.getUint16(o+2,false);
  const seq=dv.getUint32(o+4,false), ack=dv.getUint32(o+8,false);
  const offFlags=dv.getUint16(o+12,false);
  const window=dv.getUint16(o+14,false);
  const dataOff=(offFlags>>12)*4, flags=offFlags&0x01FF;
  if(dataOff<20)return null;
  const payloadLen=Math.max(0,declaredPayload-dataOff);
  let mss=null,wscale=null,tsVal=null,tsEcr=null,sackPermitted=false;
  const sackBlocks=[];
  let i=o+20;const optEnd=o+Math.min(dataOff,avail);
  while(i<optEnd){
    const kind=u8[i];
    if(kind===0)break;
    if(kind===1){i++;continue;}
    if(i+1>=optEnd)break;
    const olen=u8[i+1];
    if(olen<2||i+olen>optEnd)break;
    if(kind===2&&olen===4)mss=dv.getUint16(i+2,false);
    else if(kind===3&&olen===3)wscale=u8[i+2];
    else if(kind===4)sackPermitted=true;
    else if(kind===5){
      for(let j=i+2;j+8<=i+olen;j+=8)
        sackBlocks.push([dv.getUint32(j,false),dv.getUint32(j+4,false)]);
    }
    else if(kind===8&&olen===10){
      tsVal=dv.getUint32(i+2,false);tsEcr=dv.getUint32(i+6,false);
    }
    i+=olen;
  }
  const capPayload=Math.max(0,avail-dataOff);
  const payloadCrc=payloadLen?crc32(u8,o+dataOff,capPayload):0;
  return {
    frame:f.frameNo, absNs:f.absNs, tsRel:0 /* filled by caller */,
    srcIp:src,dstIp:dst,srcPort:sport,dstPort:dport,
    seqRaw:seq,ackRaw:ack,flags:flags&0xFF,windowRaw:window,
    payloadLen,ipTotalLen,truncated:f.truncated,
    mss,windowScale:wscale,sackPermitted,sackBlocks,tsVal,tsEcr,
    ipId,ttl,srcMac:l2[0],dstMac:l2[1],vlan:l2[2],payloadCrc,
  };
}

/* ------------------------------------------------------- retrans config */
const DEFAULT_CFG={
  dupackThreshold:3,
  rtoFloorNs:200000000,
  duplicateWindowNs:2000000,
  srttRtoMultiplier:3,
  observationWindowNs:20000000,
};
function classifyRetrans(o,cfg){
  const ev=[];
  if(o.delay!=null)ev.push(`delay since previous transmission ${o.delay} ns`);
  if(o.dupAcks)ev.push(`${o.dupAcks} duplicate ACKs observed before retransmission`);
  if(o.sackHole)ev.push("open SACK hole covered the range");
  if(o.alreadyAcked)ev.push("range was already cumulatively ACKed");
  if(o.alreadySacked)ev.push("range was already SACKed");
  if(o.alreadyAcked||o.alreadySacked){
    if(o.delay!=null&&o.delay<=cfg.duplicateWindowNs)
      return ["duplicate",[...ev,`re-seen within ${cfg.duplicateWindowNs} ns `+
        "duplicate window (possible capture-level duplication)"].join("; ")];
    return ["possible-spurious",ev.join("; ")];
  }
  let base=null;
  if(!o.fullOverlap&&o.partialOverlap)base="partial-retransmission";
  else if(!o.fullOverlap)base="overlapping-retransmission";
  const fastSignal=o.dupAcks>=cfg.dupackThreshold||o.sackHole;
  let rtoSignal=false;
  if(o.delay!=null){
    if(o.delay>=cfg.rtoFloorNs)rtoSignal=true;
    else if(o.srtt&&o.delay>=cfg.srttRtoMultiplier*o.srtt&&!fastSignal)rtoSignal=true;
  }
  let kind;
  if(fastSignal&&!rtoSignal)kind="fast-retransmission";
  else if(rtoSignal&&!fastSignal){kind="rto-retransmission";
    ev.push(`delay exceeded RTO heuristic (floor ${cfg.rtoFloorNs} ns / `+
      `${cfg.srttRtoMultiplier}x sRTT)`);}
  else if(fastSignal&&rtoSignal){kind="fast-retransmission";
    ev.push("both fast-retx and RTO signals present; dup-ACK/SACK evidence "+
      "takes precedence");}
  else {kind="retransmission";
    ev.push("no dup-ACK/SACK trigger visible and delay below RTO heuristic "+
      "— mechanism ambiguous");}
  if(base){
    ev.push(`sequence overlap was ${base.replace(/-/g," ")}`);
    if(kind==="retransmission")kind=base;
  }
  return [kind,ev.join("; ")];
}

/* ----------------------------------------------------------- rtt/window */
class RTTTracker{
  constructor(direction){this.direction=direction;this.samples=[];this.ambiguous=[];}
  addSample(ts,rtt,kind,frameData,frameAck,seq,end){
    if(rtt<0)return;
    this.samples.push({ts,rtt,kind,dir:this.direction,frameData,frameAck,seq,end});
  }
  addAmbiguous(ts,frameData,frameAck,seq,end,reason){
    this.ambiguous.push({ts,frame_data:frameData,frame_ack:frameAck,seq,end,reason});
  }
}
class WindowTracker{
  constructor(direction){
    this.direction=direction;this.scale=null;this.scaleKnown=false;
    this.lastWindow=null;this.zeroOpenTs=null;this.events=[];
    this.zeroCount=0;this.updateCount=0;this.minW=null;this.maxW=null;
  }
  effective(raw,inSyn){
    if(inSyn||!this.scaleKnown||this.scale==null)return raw;
    return raw*Math.pow(2,this.scale);
  }
  process(frame,ts,raw,inSyn){
    const win=this.effective(raw,inSyn);
    this.minW=this.minW==null?win:Math.min(this.minW,win);
    this.maxW=this.maxW==null?win:Math.max(this.maxW,win);
    const prev=this.lastWindow;this.lastWindow=win;
    if(win===0&&!inSyn){
      if(this.zeroOpenTs==null){
        this.zeroOpenTs=ts;this.zeroCount++;
        this.events.push({kind:"zero-window",dir:this.direction,frame,ts,
          window:0,detail:"advertised receive window dropped to 0"});
      }
      return;
    }
    if(this.zeroOpenTs!=null&&win>0){
      this.events.push({kind:"window-recovery",dir:this.direction,frame,ts,
        window:win,detail:`zero-window episode ended after ${ts-this.zeroOpenTs} ns`});
      this.zeroOpenTs=null;
    }
    if(prev!=null&&win>prev)this.updateCount++;
  }
  noteProbe(frame,ts){
    this.events.push({kind:"zero-window-probe",dir:this.direction,frame,ts,
      window:0,detail:"probe into a zero receive window"});
  }
  noteWindowFull(frame,ts,inFlight,win){
    this.events.push({kind:"window-full",dir:this.direction,frame,ts,
      window:win,detail:`bytes in flight ${inFlight} reached advertised window ${win}`});
  }
}

/* ------------------------------------------------------- ack correlator */
class AckCorrelator{
  constructor(direction,rtt){
    this.direction=direction;this.rtt=rtt;
    // parallel arrays sorted by end, with a head pointer instead of shifts —
    // in-order appends and cumulative pops are O(1) amortized even on
    // million-segment one-sided captures
    this.ends=[];this.ids=[];this.head=0;
    this.retransmittedRanges=new IntervalSet();
    this.sndUna=null;this.srtt=null;
  }
  registerSegment(seg){
    if(!this.ends.length||seg.end>=this.ends[this.ends.length-1]){
      this.ends.push(seg.end);this.ids.push(seg.segId);   // common fast path
      return;
    }
    let lo=this.head,hi=this.ends.length;
    while(lo<hi){const m=(lo+hi)>>1;
      if(seg.end<this.ends[m])hi=m;else lo=m+1;}
    this.ends.splice(lo,0,seg.end);this.ids.splice(lo,0,seg.segId);
  }
  noteRetransmission(start,end){this.retransmittedRanges.add(start,end);}
  processAck(ack64,ackFrame,ackTs,segments){
    if(this.sndUna!=null&&ack64<=this.sndUna)return [];
    this.sndUna=ack64;
    const newly=[];
    while(this.head<this.ends.length&&this.ends[this.head]<=ack64){
      const segId=this.ids[this.head++];
      const seg=segments[segId];
      if(seg.ackedTs!=null)continue;
      seg.ackedTs=ackTs;seg.ackedBy=ackFrame;
      seg.ackLat=ackTs-seg.ts;
      if(seg.retx)seg.state="Recovered";
      else if(seg.state==="Original"||seg.state==="SACKed")seg.state="ACKed";
      newly.push(seg);
    }
    if(this.head>8192){                    // reclaim consumed prefix
      this.ends=this.ends.slice(this.head);
      this.ids=this.ids.slice(this.head);
      this.head=0;
    }
    if(!newly.length)return newly;
    newly.sort((a,b)=>a.end-b.end);
    const dataNewly=newly.filter(s=>s.payloadLen>0);
    for(const seg of newly){
      const amb=seg.retx||this.retransmittedRanges.overlap(seg.seq,seg.end).length>0;
      if(amb&&seg.payloadLen>0)seg.rttAmb=true;
    }
    if(!dataNewly.length)return newly;
    let sampleSeg=null;
    for(const seg of dataNewly)if(seg.end===ack64)sampleSeg=seg;
    if(sampleSeg==null)sampleSeg=dataNewly[dataNewly.length-1];
    const amb=sampleSeg.retx||
      this.retransmittedRanges.overlap(sampleSeg.seq,sampleSeg.end).length>0;
    if(amb){
      this.rtt.addAmbiguous(ackTs,sampleSeg.frame,ackFrame,
        sampleSeg.seq,sampleSeg.end,
        "range retransmitted; ACK could match either transmission "+
        "(Karn's algorithm exclusion)");
    }else{
      const rtt=ackTs-sampleSeg.ts;
      if(rtt>=0){
        sampleSeg.rtt=rtt;
        this.rtt.addSample(ackTs,rtt,"data-ack",sampleSeg.frame,ackFrame,
          sampleSeg.seq,sampleSeg.end);
        this.srtt=this.srtt==null?rtt:Math.floor((7*this.srtt+rtt)/8);
      }
    }
    return newly;
  }
}

/* ------------------------------------------------------ sack scoreboard */
class SackScoreboard{
  constructor(direction){
    this.direction=direction;
    this.sacked=new IntervalSet();
    this.cumAck=null;this.records=[];this.holes=new Map();
    this.holeHistory=[];this.snapshots=[];
    this.dsackCount=0;this.sackBlockTotal=0;
  }
  processAck(frame,ts,ack64,blocks64){
    const prevAck=this.cumAck;
    if(this.cumAck==null||ack64>this.cumAck)this.cumAck=ack64;
    if(this.cumAck!=null){
      for(const h of this.holes.values())
        if(!h.closed&&h.end<=this.cumAck){
          h.closed=true;h.closed_ts=ts;h.closed_frame=frame;
        }
      this.sacked.removeBelow(this.cumAck);
    }
    if(!blocks64.length)return null;
    const [isDsack,reason]=this.detectDsack(ack64,blocks64);
    const rec={frame,ts,ack:ack64,blocks:blocks64,dsack:isDsack,
               dsack_reason:reason};
    this.records.push(rec);
    this.sackBlockTotal+=blocks64.length;
    const board=isDsack?blocks64.slice(1):blocks64;
    if(isDsack)this.dsackCount++;
    for(const [l,r] of board)if(r>l)this.sacked.add(l,r);
    if(this.cumAck!=null)this.sacked.removeBelow(this.cumAck);
    this.updateHoles(frame,ts);
    this.snapshots.push({frame,ts,ack:this.cumAck,
      sacked:this.sacked.intervals(),
      holes:this.openHoles().map(h=>[h.start,h.end]),
      dsack:isDsack,
      ack_advanced:prevAck!=null&&this.cumAck!=null&&this.cumAck>prevAck});
    return rec;
  }
  updateHoles(frame,ts){
    if(this.cumAck==null||!this.sacked.length)return;
    const hi=this.sacked.ends[this.sacked.ends.length-1];
    for(const [start,end] of this.sacked.gapsBetween(this.cumAck,hi)){
      const existing=this.holes.get(start);
      if(existing&&!existing.closed){
        if(end!==existing.end)existing.end=Math.min(existing.end,end);
        continue;
      }
      if(!this.holes.has(start)){
        const h={start,end,first_ts:ts,first_frame:frame,closed:false,
                 closed_ts:null,closed_frame:null};
        this.holes.set(start,h);this.holeHistory.push(h);
      }
    }
    for(const h of this.holes.values())
      if(!h.closed&&this.sacked.containsRange(h.start,h.end)){
        h.closed=true;h.closed_ts=ts;h.closed_frame=frame;
      }
  }
  openHoles(){return [...this.holes.values()].filter(h=>!h.closed);}
  detectDsack(ack64,blocks){
    const [l0,r0]=blocks[0];
    if(r0<=ack64)return [true,"first SACK block entirely below cumulative ACK"];
    if(blocks.length>=2){
      const [l1,r1]=blocks[1];
      if(l1<=l0&&r0<=r1)return [true,"first SACK block contained in second block"];
    }
    return [false,null];
  }
}

/* --------------------------------------------------------- loss manager */
class LossManager{
  constructor(direction){
    this.direction=direction;this.events=[];this.openByStart=new Map();
    this.nextId=0;
  }
  openEvent(o){
    const ex=this.findOverlap(o.seq,o.end);
    if(ex){
      if(ex.first_evidence_ns==null||o.evidenceTs<ex.first_evidence_ns){
        ex.first_evidence_ns=o.evidenceTs;ex.first_evidence_frame=o.evidenceFrame;
        ex.evidence_kind=o.evidenceKind;
      }
      ex.sack_involved=ex.sack_involved||!!o.sackInvolved;
      return ex;
    }
    const ev={loss_id:this.nextId++,direction:this.direction,
      seq:o.seq,end:o.end,bytes:o.end-o.seq,
      original_tx_ns:o.originalTx??null,original_frame:o.originalFrame??null,
      first_evidence_ns:o.evidenceTs,first_evidence_frame:o.evidenceFrame,
      evidence_kind:o.evidenceKind,
      retrans_ns:null,retrans_frame:null,retrans_lost:false,
      recovery_ns:null,recovery_frame:null,recovered:false,partial:false,
      sack_involved:!!o.sackInvolved,dup_ack_count:0,sack_report_count:0,
      additional_holes:0,likely_mechanism:"unknown",
      classification:o.classification||"loss",
      classification_evidence:o.classificationEvidence||""};
    this.events.push(ev);this.openByStart.set(o.seq,ev);
    return ev;
  }
  findOverlap(seq,end){
    for(const ev of this.openByStart.values())
      if(ev.seq<end&&seq<ev.end&&!ev.recovered)return ev;
    return null;
  }
  noteRetransmission(seq,end,frame,ts,mechanism){
    const ev=this.findOverlap(seq,end);
    if(!ev)return null;
    if(ev.retrans_ns==null){
      ev.retrans_ns=ts;ev.retrans_frame=frame;ev.likely_mechanism=mechanism;
    }else ev.retrans_lost=true;
    return ev;
  }
  noteDupAcks(seq,end,count){
    const ev=this.findOverlap(seq,end);
    if(ev)ev.dup_ack_count=Math.max(ev.dup_ack_count,count);
  }
  noteSackReport(seq,end){
    const ev=this.findOverlap(seq,end);
    if(ev){ev.sack_report_count++;ev.sack_involved=true;}
  }
  noteAdditionalHole(ts){
    for(const ev of this.openByStart.values())
      if(!ev.recovered&&ev.first_evidence_ns!=null&&ev.first_evidence_ns<ts)
        ev.additional_holes++;
  }
  noteCumAck(ack64,frame,ts){
    const recovered=[];
    for(const [start,ev] of [...this.openByStart]){
      if(ev.end<=ack64){
        ev.recovered=true;ev.recovery_ns=ts;ev.recovery_frame=frame;
        ev.partial=false;
        this.openByStart.delete(start);
        recovered.push(ev);
      }else if(ev.seq<ack64&&ack64<ev.end)ev.partial=true;
    }
    return recovered;
  }
  reclassify(seq,end,classification,evidence,evidenceTs){
    for(const ev of this.events)
      if(ev.seq<end&&seq<ev.end){
        if(evidenceTs!=null&&ev.recovered&&ev.recovery_ns!=null&&
           ev.recovery_ns<evidenceTs)continue;
        ev.classification=classification;
        ev.classification_evidence=evidence;
      }
  }
}

/* ------------------------------------------------------------- session */
class DirectionState{
  constructor(direction){
    this.direction=direction;
    this.unwrapper=new SeqUnwrapper();
    this.isn=null;this.isnRaw=null;this.relBase=null;
    this.synSeen=false;this.synFrames=[];
    this.finSeen=false;this.rstSeen=false;
    this.segments=[];this.segIndex=new SegmentIndex();
    this.transmitted=new IntervalSet();this.sndMax=null;
    this.rtt=new RTTTracker(direction);
    this.ackCorr=new AckCorrelator(direction,this.rtt);
    this.scoreboard=new SackScoreboard(direction);
    this.loss=new LossManager(direction);
    this.window=new WindowTracker(direction);
    this.openGaps=[];this.retransEvents=[];
    this.dupLastAck=null;this.dupLastWin=null;this.dupTrain=null;
    this.dupAckTrains=[];
    this.mss=null;this.ws=null;this.sackPermitted=null;this.tsopt=false;
    this.packets=0;this.bytes=0;this.payloadBytes=0;
    this.retransSegments=0;this.retransBytes=0;
    this.dupPackets=0;this.oooPackets=0;this.keepaliveCount=0;
    this.oversizeSegments=0;this.gapOverflow=0;this.windowFull=false;
    this.recentFp=new Map();this.fpPruneAt=0;
    this.networkDups=0;this.observationEvents=[];
  }
  rel(seq64){
    if(seq64==null)return null;
    return seq64-(this.relBase!=null?this.relBase:0);
  }
  contiguousEnd(){
    if(!this.transmitted.length)return null;
    return this.transmitted.ends[0];
  }
}
const MAX_OPEN_GAPS=1024;

class Session{
  constructor(id,pkt,cfg,rowLimit){
    this.id=id;this.cfg=cfg;this.rowLimit=rowLimit;this.rowsDropped=0;
    this.captureId=pkt.captureId||0;
    this.epA=[pkt.srcIp,pkt.srcPort];this.epB=[pkt.dstIp,pkt.dstPort];
    this.dirA=new DirectionState("A->B");this.dirB=new DirectionState("B->A");
    this.firstTs=null;this.lastTs=null;
    this.clientDir=null;this.handshakeComplete=false;this.partial=true;
    this.synTs=null;this.synFrame=null;this.synackTs=null;this.synackFrame=null;
    this.estAckTs=null;this.estAckFrame=null;
    this.rstFrame=null;this.finFrames=[];
    this.packetRows=[];this.truncatedFrames=0;
  }
  directionOf(pkt){
    return (pkt.srcIp===this.epA[0]&&pkt.srcPort===this.epA[1])?"A->B":"B->A";
  }
  dstate(d){return d==="A->B"?this.dirA:this.dirB;}
  get closed(){
    return this.dirA.rstSeen||this.dirB.rstSeen||
           (this.dirA.finSeen&&this.dirB.finSeen);
  }
  addPacket(pkt){
    const d=this.directionOf(pkt), r=d==="A->B"?"B->A":"A->B";
    const snd=this.dstate(d), rcv=this.dstate(r);
    if(this.firstTs==null)this.firstTs=pkt.tsRel;
    this.lastTs=pkt.tsRel;
    if(pkt.truncated)this.truncatedFrames++;

    const dup=this.observationDuplicate(pkt,snd);
    if(dup){
      snd.networkDups++;snd.packets++;snd.bytes+=pkt.ipTotalLen;
      this.storeRow(pkt,d,snd,snd.unwrapper.unwrapNoAdvance(pkt.seqRaw),
                    null,null,"Capture-dup");
      return;
    }
    snd.packets++;snd.bytes+=pkt.ipTotalLen;snd.payloadBytes+=pkt.payloadLen;

    const seq64=snd.unwrapper.unwrap(pkt.seqRaw);
    if(snd.relBase==null)snd.relBase=seq64;
    let consumed=pkt.payloadLen;
    if(pkt.flags&SYN)consumed++;
    if(pkt.flags&FIN)consumed++;
    const end64=seq64+consumed;

    this.handshake(pkt,d,snd,rcv,seq64);
    if(pkt.flags&RST){snd.rstSeen=true;
      if(this.rstFrame==null)this.rstFrame=pkt.frame;}
    if(pkt.flags&FIN){snd.finSeen=true;this.finFrames.push(pkt.frame);}

    if(!this.dirA.window.scaleKnown&&this.dirA.synSeen&&this.dirB.synSeen&&
       !(pkt.flags&SYN)){
      const both=this.dirA.ws!=null&&this.dirB.ws!=null;
      for(const ds of [this.dirA,this.dirB]){
        ds.window.scale=both?ds.ws:null;ds.window.scaleKnown=true;
      }
    }
    snd.window.process(pkt.frame,pkt.tsRel,pkt.windowRaw,!!(pkt.flags&SYN));

    let seg=null;
    if(consumed>0)seg=this.dataSegment(pkt,d,r,snd,rcv,seq64,end64);
    if(pkt.flags&ACK)this.processAck(pkt,d,r,snd,rcv);
    if(consumed>0&&pkt.payloadLen<=1&&rcv.window.zeroOpenTs!=null&&
       !(pkt.flags&(SYN|FIN|RST)))
      rcv.window.noteProbe(pkt.frame,pkt.tsRel);
    this.storeRow(pkt,d,snd,seq64,end64,seg,null);
  }

  handshake(pkt,d,snd,rcv,seq64){
    const f=pkt.flags;
    if((f&SYN)&&!(f&ACK)){
      if(!snd.synSeen){
        snd.synSeen=true;snd.isn=seq64;snd.isnRaw=pkt.seqRaw;snd.relBase=seq64;
        if(this.clientDir==null)this.clientDir=d;
        this.partial=false;
        this.synTs=pkt.tsRel;this.synFrame=pkt.frame;
        snd.mss=pkt.mss;snd.ws=pkt.windowScale;
        snd.sackPermitted=pkt.sackPermitted;snd.tsopt=pkt.tsVal!=null;
      }
      snd.synFrames.push(pkt.frame);
    }else if((f&SYN)&&(f&ACK)){
      if(!snd.synSeen){
        snd.synSeen=true;snd.isn=seq64;snd.isnRaw=pkt.seqRaw;snd.relBase=seq64;
        if(this.clientDir==null)this.clientDir=d==="A->B"?"B->A":"A->B";
        this.synackTs=pkt.tsRel;this.synackFrame=pkt.frame;
        snd.mss=pkt.mss;snd.ws=pkt.windowScale;
        snd.sackPermitted=pkt.sackPermitted;snd.tsopt=pkt.tsVal!=null;
        if(this.synTs!=null&&this.clientDir!=null){
          const cds=this.dstate(this.clientDir);
          const rtt=pkt.tsRel-this.synTs;
          if(cds.synFrames.length>1)
            cds.rtt.addAmbiguous(pkt.tsRel,this.synFrame,pkt.frame,0,1,
              "SYN was retransmitted; SYN/ACK could answer either SYN "+
              "(Karn's algorithm exclusion)");
          else if(rtt>=0)
            cds.rtt.addSample(pkt.tsRel,rtt,"syn-synack",
              this.synFrame,pkt.frame,0,1);
        }
      }
      snd.synFrames.push(pkt.frame);
    }else if((f&ACK)&&!(f&SYN)&&!this.handshakeComplete&&
             this.synackTs!=null&&d===this.clientDir){
      this.handshakeComplete=true;
      this.estAckTs=pkt.tsRel;this.estAckFrame=pkt.frame;
      const rtt=pkt.tsRel-this.synackTs;
      const sdir=this.clientDir==="A->B"?"B->A":"A->B";
      const sds=this.dstate(sdir);
      if(sds.synFrames.length>1)
        sds.rtt.addAmbiguous(pkt.tsRel,this.synackFrame,pkt.frame,0,1,
          "SYN/ACK was retransmitted; the ACK could answer either copy "+
          "(Karn's algorithm exclusion)");
      else if(rtt>=0)
        sds.rtt.addSample(pkt.tsRel,rtt,"synack-ack",
          this.synackFrame,pkt.frame,0,1);
      const both=this.dirA.ws!=null&&this.dirB.ws!=null;
      for(const ds of [this.dirA,this.dirB]){
        ds.window.scale=both?ds.ws:null;ds.window.scaleKnown=true;
      }
    }
  }

  dataSegment(pkt,d,r,snd,rcv,seq64,end64){
    const overlaps=snd.transmitted.overlap(seq64,end64);
    const fullOverlap=snd.transmitted.containsRange(seq64,end64);
    const seg={segId:snd.segments.length,frame:pkt.frame,ts:pkt.tsRel,
      seq:seq64,end:end64,payloadLen:pkt.payloadLen,len:pkt.payloadLen,
      flags:pkt.flags,ackRaw:pkt.ackRaw,winRaw:pkt.windowRaw,
      state:"Original",retx:false,retxKind:null,retxOf:null,retxDelay:null,
      ackedTs:null,ackedBy:null,ackLat:null,rtt:null,rttAmb:false,
      sackedTs:null,sackedBy:null};
    snd.segments.push(seg);
    if(snd.mss&&pkt.payloadLen>snd.mss)snd.oversizeSegments++;

    const una=snd.ackCorr.sndUna;
    const tiny=pkt.payloadLen<=1&&!(pkt.flags&(SYN|FIN|RST))&&
               una!=null&&seq64<=una;
    if(tiny&&rcv.window.zeroOpenTs!=null){
      seg.state="Window-probe";
    }else if(tiny&&overlaps.length&&pkt.payloadLen>0&&end64<=una){
      seg.state="Keep-alive";snd.keepaliveCount++;
    }else if(overlaps.length&&pkt.payloadLen>0){
      this.retransmission(pkt,d,snd,rcv,seg,overlaps,fullOverlap);
    }else{
      this.originalData(pkt,snd,seg,seq64,end64);
    }
    snd.transmitted.add(seq64,end64);
    snd.segIndex.add(seq64,end64,seg.segId);
    snd.sndMax=snd.sndMax==null?end64:Math.max(snd.sndMax,end64);
    if(seg.state!=="Keep-alive"&&seg.state!=="Window-probe")
      snd.ackCorr.registerSegment(seg);

    const una2=snd.ackCorr.sndUna, adv=rcv.window.lastWindow;
    if(una2!=null&&adv){
      const inFlight=snd.sndMax-una2;
      if(inFlight>=adv&&!snd.windowFull){
        snd.windowFull=true;
        rcv.window.noteWindowFull(pkt.frame,pkt.tsRel,inFlight,adv);
      }else if(inFlight<adv)snd.windowFull=false;
    }
    return seg;
  }

  originalData(pkt,snd,seg,seq64,end64){
    const contig=snd.contiguousEnd();
    if(contig!=null&&seq64>contig){
      if(snd.openGaps.length<MAX_OPEN_GAPS)
        snd.openGaps.push({start:contig,end:seq64,ts:pkt.tsRel,frame:pkt.frame});
      else snd.gapOverflow++;
    }
    for(const gap of snd.openGaps){
      if(gap.resolved)continue;
      if((seq64<=gap.start&&gap.start<end64)||(seq64<gap.end&&end64>gap.start)){
        gap.resolved=true;gap.fill_frame=pkt.frame;gap.fill_ts=pkt.tsRel;
        gap.fill_kind="new-data";
        seg.state="Out-of-order";snd.oooPackets++;
        const delay=pkt.tsRel-gap.ts;
        const ev=snd.loss.openEvent({
          seq:Math.max(gap.start,seq64),end:Math.min(gap.end,end64),
          evidenceKind:"seq-gap",evidenceTs:gap.ts,evidenceFrame:gap.frame,
          originalTx:null,originalFrame:null,classification:"reordering",
          classificationEvidence:`gap filled after ${delay} ns by frame `+
            `${pkt.frame} carrying data never seen before in the capture — `+
            "consistent with out-of-order delivery, not retransmitted loss"});
        ev.recovered=true;ev.recovery_ns=pkt.tsRel;ev.recovery_frame=pkt.frame;
        snd.loss.openByStart.delete(ev.seq);
      }
    }
  }

  retransmission(pkt,d,snd,rcv,seg,overlaps,fullOverlap){
    const cands=snd.segIndex.overlapping(seg.seq,seg.end);
    let orig=null,lastTx=null;
    for(const [,,sid] of cands){
      const cand=snd.segments[sid];
      if(cand===seg)continue;
      if(cand.payloadLen>0&&(orig==null||cand.ts<orig.ts))orig=cand;
      if(lastTx==null||cand.ts>lastTx)lastTx=cand.ts;
    }
    const una=snd.ackCorr.sndUna;
    const alreadyAcked=una!=null&&seg.end<=una;
    const alreadySacked=snd.scoreboard.sacked.containsRange(seg.seq,seg.end);
    const dupAcks=rcv.dupTrain?rcv.dupTrain.count:0;
    const hole=snd.scoreboard.openHoles().some(
      h=>h.start<seg.end&&seg.seq<h.end);
    const partialOverlap=overlaps.length>0&&!fullOverlap;
    const [kind,evidence]=classifyRetrans({
      delay:lastTx!=null?pkt.tsRel-lastTx:null,
      dupAcks,sackHole:hole,alreadyAcked,alreadySacked,
      fullOverlap,partialOverlap,srtt:snd.ackCorr.srtt},this.cfg);
    seg.retx=true;seg.retxKind=kind;
    seg.state=kind==="duplicate"?"Duplicate":"Retransmitted";
    if(orig){seg.retxOf=orig.frame;seg.retxDelay=pkt.tsRel-orig.ts;}
    snd.ackCorr.noteRetransmission(seg.seq,seg.end);
    if(kind==="duplicate")snd.dupPackets++;
    else {snd.retransSegments++;snd.retransBytes+=seg.payloadLen;}
    snd.retransEvents.push({frame:pkt.frame,ts:pkt.tsRel,dir:d,
      seq:seg.seq,end:seg.end,bytes:seg.payloadLen,cls:kind,
      origFrame:orig?orig.frame:null,origTs:orig?orig.ts:null,
      delay:seg.retxDelay,dupAcks,sack:hole||alreadySacked,evidence});
    for(const gap of snd.openGaps)
      if(!gap.resolved&&seg.seq<gap.end&&gap.start<seg.end){
        gap.resolved=true;gap.fill_kind="retransmission";
      }
    if(kind==="duplicate"||kind==="possible-spurious")return;
    const mech=kind==="fast-retransmission"?"fast-retransmit":
               kind==="rto-retransmission"?"rto":"unknown";
    let ev=snd.loss.noteRetransmission(seg.seq,seg.end,pkt.frame,pkt.tsRel,mech);
    if(!ev){
      let evTs=pkt.tsRel,evFrame=pkt.frame;
      if(rcv.dupTrain&&rcv.dupTrain.count>=1){
        evTs=rcv.dupTrain.first_ts;evFrame=rcv.dupTrain.first_frame;
      }
      ev=snd.loss.openEvent({seq:seg.seq,end:seg.end,
        evidenceKind:"retransmission",evidenceTs:evTs,evidenceFrame:evFrame,
        originalTx:orig?orig.ts:null,originalFrame:orig?orig.frame:null});
      snd.loss.noteRetransmission(seg.seq,seg.end,pkt.frame,pkt.tsRel,mech);
    }
    if(ev){
      ev.dup_ack_count=Math.max(ev.dup_ack_count,dupAcks);
      if(rcv.dupTrain&&rcv.dupTrain.retrans_frame==null){
        rcv.dupTrain.retrans_frame=pkt.frame;
        rcv.dupTrain.time_to_retrans=pkt.tsRel-rcv.dupTrain.first_ts;
      }
    }
  }

  processAck(pkt,d,r,snd,rcv){
    const ack64=rcv.unwrapper.unwrapNoAdvance(pkt.ackRaw);
    const pureAck=pkt.payloadLen===0&&!(pkt.flags&(SYN|FIN|RST));
    if(pureAck){
      if(snd.dupLastAck!=null&&ack64===snd.dupLastAck&&
         pkt.windowRaw===snd.dupLastWin){
        if(snd.dupTrain==null){
          snd.dupTrain={dir:d,ack:ack64,first_frame:pkt.frame,
            first_ts:pkt.tsRel,count:1,last_ts:pkt.tsRel,gaps_ns:[],
            sack_blocks:0,missing_seq:null,missing_end:null,
            retrans_frame:null,time_to_retrans:null,time_to_recovery:null};
          snd.dupAckTrains.push(snd.dupTrain);
        }else{
          snd.dupTrain.count++;
          snd.dupTrain.gaps_ns.push(pkt.tsRel-snd.dupTrain.last_ts);
          snd.dupTrain.last_ts=pkt.tsRel;
        }
        if(pkt.sackBlocks.length)snd.dupTrain.sack_blocks+=pkt.sackBlocks.length;
        if(snd.dupTrain.count>=this.cfg.dupackThreshold){
          let missEnd=rcv.sndMax!=null?rcv.sndMax:ack64;
          for(const h of rcv.scoreboard.openHoles())
            if(h.start>=ack64){missEnd=Math.min(missEnd,h.end);break;}
          snd.dupTrain.missing_seq=ack64;snd.dupTrain.missing_end=missEnd;
          if(missEnd>ack64){
            const ft=this.firstTx(rcv,ack64,missEnd);
            rcv.loss.openEvent({seq:ack64,end:missEnd,evidenceKind:"dup-ack",
              evidenceTs:snd.dupTrain.first_ts,
              evidenceFrame:snd.dupTrain.first_frame,
              originalTx:ft?ft.ts:null,originalFrame:ft?ft.frame:null});
            rcv.loss.noteDupAcks(ack64,missEnd,snd.dupTrain.count);
          }
        }
      }else snd.dupTrain=null;
      snd.dupLastAck=ack64;snd.dupLastWin=pkt.windowRaw;
    }else if(pkt.payloadLen>0)snd.dupTrain=null;

    rcv.ackCorr.processAck(ack64,pkt.frame,pkt.tsRel,rcv.segments);
    const recovered=rcv.loss.noteCumAck(ack64,pkt.frame,pkt.tsRel);
    for(const ev of recovered)
      for(const train of snd.dupAckTrains)
        if(train.missing_seq!=null&&train.missing_seq>=ev.seq&&
           train.missing_seq<ev.end&&train.time_to_recovery==null)
          train.time_to_recovery=pkt.tsRel-train.first_ts;

    const blocks64=[];
    for(const [l,rr] of pkt.sackBlocks){
      const l64=rcv.unwrapper.unwrapNoAdvance(l);
      const r64=rcv.unwrapper.unwrapNoAdvance(rr);
      if(r64>l64)blocks64.push([l64,r64]);
    }
    const prevHoles=new Set(rcv.scoreboard.openHoles().map(h=>h.start));
    const rec=rcv.scoreboard.processAck(pkt.frame,pkt.tsRel,ack64,blocks64);
    if(rec){
      if(rec.dsack){
        const [l64,r64]=rec.blocks[0];
        for(const rt of rcv.retransEvents)
          if(rt.seq<r64&&l64<rt.end&&
             rt.cls!=="possible-spurious"&&rt.cls!=="duplicate"){
            rt.cls="possible-spurious";
            rt.evidence+=`; DSACK reported the range as already received `+
              `(frame ${pkt.frame}: ${rec.dsack_reason})`;
          }
        rcv.loss.reclassify(l64,r64,"duplicate",
          `DSACK in frame ${pkt.frame}: ${rec.dsack_reason}`,pkt.tsRel);
      }
      const board=rec.dsack?rec.blocks.slice(1):rec.blocks;
      for(const [l64,r64] of board)
        for(const [,,sid] of rcv.segIndex.overlapping(l64,r64)){
          const segr=rcv.segments[sid];
          if(segr.sackedTs==null&&l64<=segr.seq&&segr.end<=r64){
            segr.sackedTs=pkt.tsRel;segr.sackedBy=pkt.frame;
            if(segr.state==="Original")segr.state="SACKed";
          }
        }
    }
    for(const h of rcv.scoreboard.openHoles()){
      rcv.loss.noteSackReport(h.start,h.end);
      if(!prevHoles.has(h.start)){
        if(prevHoles.size)rcv.loss.noteAdditionalHole(pkt.tsRel);
        const ft=this.firstTx(rcv,h.start,h.end);
        rcv.loss.openEvent({seq:h.start,end:h.end,evidenceKind:"sack-hole",
          evidenceTs:h.first_ts,evidenceFrame:h.first_frame,
          originalTx:ft?ft.ts:null,originalFrame:ft?ft.frame:null,
          sackInvolved:true});
      }
    }
  }

  firstTx(rcv,start,end){
    let best=null;
    for(const [,,sid] of rcv.segIndex.overlapping(start,end)){
      const seg=rcv.segments[sid];
      if(best==null||seg.ts<best.ts)best=seg;
    }
    return best;
  }

  observationDuplicate(pkt,snd){
    const fpKey=[pkt.seqRaw,pkt.ackRaw,pkt.flags,pkt.payloadLen,
      pkt.payloadCrc,pkt.ipId,pkt.tsVal,pkt.tsEcr,pkt.windowRaw,
      pkt.sackBlocks.map(b=>b[0]+"-"+b[1]).join(",")].join("|");
    // a different source capture file IS a different observation point
    const sig=[pkt.captureId,pkt.ttl,pkt.srcMac,pkt.dstMac,pkt.vlan].join("|");
    const now=pkt.tsRel;
    if(now>=snd.fpPruneAt){
      const cutoff=now-this.cfg.observationWindowNs;
      for(const [k,v] of snd.recentFp)if(v.ts<cutoff)snd.recentFp.delete(k);
      snd.fpPruneAt=now+Math.floor(this.cfg.observationWindowNs/2);
    }
    const entry=snd.recentFp.get(fpKey);
    const fresh={frame:pkt.frame,ts:now,sigs:new Set([sig]),lastSig:
      [pkt.captureId,pkt.ttl,pkt.srcMac,pkt.dstMac,pkt.vlan]};
    if(!entry||now-entry.ts>this.cfg.observationWindowNs){
      snd.recentFp.set(fpKey,fresh);return null;
    }
    const strong=pkt.ipId!=null&&pkt.ipId!==0;
    const seenSig=entry.sigs.has(sig);
    let confidence;
    if(strong){
      if(seenSig&&now-entry.ts>this.cfg.duplicateWindowNs){
        snd.recentFp.set(fpKey,fresh);return null;
      }
      confidence="confirmed";
    }else if(seenSig){
      snd.recentFp.set(fpKey,fresh);return null;
    }else confidence="likely";
    const ps=entry.lastSig, diffs=[];
    if(pkt.ttl!=null&&ps[1]!=null&&pkt.ttl!==ps[1])
      diffs.push(`TTL ${ps[1]}→${pkt.ttl}`);
    if(pkt.srcMac&&ps[2]&&pkt.srcMac!==ps[2])diffs.push("src MAC rewritten");
    if(pkt.dstMac&&ps[3]&&pkt.dstMac!==ps[3])diffs.push("dst MAC rewritten");
    if(pkt.vlan!==ps[4]&&(pkt.vlan!=null||ps[4]!=null))
      diffs.push(`VLAN ${ps[4]==null?"null":ps[4]}→${pkt.vlan==null?"null":pkt.vlan}`);
    if(pkt.captureId!==ps[0])
      diffs.push(`capture file #${ps[0]}→#${pkt.captureId}`);
    const ev={frame:pkt.frame,ts:now,orig_frame:entry.frame,orig_ts:entry.ts,
      delta_ns:now-entry.ts,
      differs:diffs.length?diffs.join(", "):
        "L2/TTL identical (same-point SPAN duplication)",
      confidence};
    snd.observationEvents.push(ev);
    entry.frame=pkt.frame;entry.ts=now;entry.sigs.add(sig);
    entry.lastSig=[pkt.captureId,pkt.ttl,pkt.srcMac,pkt.dstMac,pkt.vlan];
    return ev;
  }

  storeRow(pkt,d,snd,seq64,end64,seg,stateOverride){
    if(this.packetRows.length>=this.rowLimit){this.rowsDropped++;return;}
    this.packetRows.push([pkt.frame,pkt.tsRel,d,
      snd.rel(seq64),snd.rel(end64),pkt.payloadLen,
      flagsToStr(pkt.flags),pkt.ackRaw,pkt.windowRaw,pkt.sackBlocks.length,
      stateOverride?stateOverride:(seg?seg.state:""),pkt.captureId]);
  }
}

class SessionManager{
  constructor(cfg,rowLimit){
    this.cfg=cfg;this.rowLimit=rowLimit;
    this.sessions=[];this.active=new Map();
  }
  key(pkt){
    const a=pkt.srcIp+"~"+pkt.srcPort, b=pkt.dstIp+"~"+pkt.dstPort;
    return a<=b?a+"|"+b:b+"|"+a;
  }
  feed(pkt){
    const key=this.key(pkt);
    let sess=this.active.get(key);
    if(sess&&this.isNewConnection(sess,pkt))sess=null;
    if(!sess){
      sess=new Session(this.sessions.length,pkt,this.cfg,this.rowLimit);
      this.sessions.push(sess);this.active.set(key,sess);
    }
    sess.addPacket(pkt);
  }
  isNewConnection(sess,pkt){
    if(!(pkt.flags&SYN)||(pkt.flags&ACK))return false;
    const d=sess.directionOf(pkt), ds=sess.dstate(d);
    if(ds.synSeen&&ds.isnRaw===pkt.seqRaw)return false;
    if(sess.closed)return true;
    if(sess.handshakeComplete)return true;
    if(ds.synSeen&&ds.isnRaw!==pkt.seqRaw)return true;
    return false;
  }
}

/* ------------------------------------------------------------ verdicts */
const VERDICT_CFG={low_retrans_pct:0.5,high_retrans_pct:2.0,
  high_rtt_ns:100000000,rtt_outlier_ratio:10.0,repeated_holes:3,
  reordering_events:1,zero_window_events:1,spurious_retrans:1};
function evaluateVerdicts(st,cfg){
  const out=[];
  const add=(verdict,severity,evidence)=>out.push({verdict,severity,evidence});
  if(st.partial)
    add("INCOMPLETE CAPTURE","info","Connection establishment was not "+
      "observed — the capture begins mid-session; byte accounting and "+
      "negotiation state are partial.");
  if(st.rst)
    add("SESSION RESET","warn",`RST observed (frame ${st.rst_frame}); the `+
      "session was aborted rather than closed with FIN.");
  const rp=st.retrans_pct, segs=st.retrans_segments||0;
  if(rp!=null&&(st.data_segments||0)>0){
    if(segs===0)
      add("HEALTHY","ok",`No retransmitted segments detected in `+
        `${st.data_segments} data segments.`);
    else if(rp<cfg.low_retrans_pct)
      add("LOW RETRANSMISSION","ok",`${segs} retransmitted segments = `+
        `${rp.toFixed(2)}% of data segments (threshold: below `+
        `${cfg.low_retrans_pct}%).`);
    else if(rp>=cfg.high_retrans_pct)
      add("HIGH RETRANSMISSION","bad",`${segs} retransmitted segments = `+
        `${rp.toFixed(2)}% of data segments (threshold: `+
        `${cfg.high_retrans_pct}%). ${st.retrans_bytes||0} bytes retransmitted.`);
  }
  const rtt=st.rtt||{}, med=rtt.median, p99=rtt.p99;
  if(med!=null&&med>cfg.high_rtt_ns)
    add("HIGH RTT","bad",`Median valid RTT ${med} ns exceeds threshold `+
      `${cfg.high_rtt_ns} ns (${rtt.count} valid samples; ambiguous samples `+
      "excluded per Karn's algorithm).");
  if(med&&p99&&med>0&&p99/med>=cfg.rtt_outlier_ratio)
    add("RTT OUTLIERS","warn",`P99 RTT ${p99} ns is ${(p99/med).toFixed(1)}x `+
      `the median ${med} ns (threshold ratio: ${cfg.rtt_outlier_ratio}).`);
  const sackRec=st.sack_recovered_losses||0, lossTotal=st.loss_events||0;
  if(sackRec){
    const rec=st.recovery||{};
    let extra="";
    if(rec.median!=null)
      extra=` Median recovery ${rec.median} ns, P95 ${rec.p95} ns.`;
    add("SACK-BASED LOSS RECOVERY OBSERVED","info",
      `${sackRec} of ${lossTotal} loss events show SACK involvement during `+
      `recovery.${extra}`);
  }
  if((st.sack_holes||0)>=cfg.repeated_holes)
    add("REPEATED SEQUENCE HOLES","warn",`${st.sack_holes} distinct SACK `+
      `holes observed (threshold: ${cfg.repeated_holes}).`);
  if((st.ooo_packets||0)>=cfg.reordering_events)
    add("POSSIBLE PACKET REORDERING","warn",`${st.ooo_packets} segments `+
      "filled sequence gaps with data never previously seen in the capture "+
      "— consistent with reordering rather than loss.");
  if((st.spurious_retrans||0)>=cfg.spurious_retrans)
    add("POSSIBLE SPURIOUS RETRANSMISSION","warn",`${st.spurious_retrans} `+
      "retransmissions of data that was already ACKed/SACKed or was "+
      "DSACK-reported as received.");
  if((st.zero_window_events||0)>=cfg.zero_window_events)
    add("ZERO-WINDOW BOTTLENECK","bad",`${st.zero_window_events} zero-window `+
      "episodes observed — the receiver stalled the sender "+
      "(application-side bottleneck).");
  if(st.unrecovered_losses)
    add("UNRECOVERED LOSS","bad",`${st.unrecovered_losses} loss events were `+
      "never covered by a cumulative ACK within the capture.");
  if(!out.length)
    add("NO FINDINGS","ok","No rule produced a finding for this session.");
  return out;
}

/* ------------------------------------------------------------ artifacts */
function sessionArtifacts(sess){
  const warns=[], a=sess.dirA, b=sess.dirB;
  if(a.oversizeSegments||b.oversizeSegments){
    const n=a.oversizeSegments+b.oversizeSegments;
    warns.push(`${n} segments exceed the negotiated MSS — likely `+
      "TSO/GSO/GRO/LRO offload in a host-based capture; segment boundaries "+
      "and per-segment timing may not reflect on-wire packets.");
  }
  if(sess.truncatedFrames)
    warns.push(`${sess.truncatedFrames} frames truncated by snap length — `+
      "TCP payloads incomplete (analysis uses IP-declared lengths).");
  if(sess.partial)
    warns.push("Capture begins mid-session (no handshake observed): "+
      "negotiation state is Unknown and relative sequence numbers are "+
      "anchored at the first observed segment.");
  for(const [ds,name] of [[a,"A->B"],[b,"B->A"]]){
    const una=ds.ackCorr.sndUna;
    if(una!=null&&ds.sndMax!=null&&una>ds.sndMax)
      warns.push(`ACKs in direction ${name==="A->B"?"B->A":"A->B"} cover `+
        `${una-ds.sndMax} bytes never seen in ${name} — asymmetric capture `+
        "or capture drops; missing data must not be interpreted as network "+
        "loss.");
    if(una!=null&&ds.sndMax==null&&ds.packets===0)
      warns.push(`Direction ${name} carried no packets — one-sided `+
        "(asymmetric) capture for this session.");
  }
  const ndups=a.networkDups+b.networkDups;
  if(ndups){
    const deltas=[...a.observationEvents,...b.observationEvents]
      .map(e=>e.delta_ns).sort((x,y)=>x-y);
    const med=percentile(deltas,50);
    warns.push(`${ndups} frames are the SAME packet observed more than once `+
      "(multi-point SPAN / mirrored feed / routed-hop capture) — recognized "+
      "by identical TCP content and IP ID with unchanged or rewritten "+
      "MAC/VLAN/TTL, and excluded from retransmission, duplicate and "+
      `dup-ACK statistics. Median inter-observation skew: ${med} ns `+
      "(see Overview → Multi-point observations).");
  }
  if(a.gapOverflow||b.gapOverflow){
    const n=a.gapOverflow+b.gapOverflow;
    warns.push(`${n} additional sequence gaps beyond the per-session `+
      "tracking bound were not individually tracked — gap-level "+
      "classification for this session is partial.");
  }
  for(const [ds,name] of [[a,"A->B"],[b,"B->A"]]){
    const unresolved=ds.openGaps.filter(g=>!g.resolved);
    if(unresolved.length){
      const bytes=unresolved.reduce((t,g)=>t+(g.end-g.start),0);
      warns.push(`${unresolved.length} sequence gap(s) in ${name} `+
        `(${bytes} bytes) were never filled within the capture — possible `+
        "capture drop or truncated capture; classified as Unknown, not as "+
        "network loss.");
    }
  }
  return warns;
}

/* --------------------------------------------------------- serialization */
function dirStats(ds){
  let dataSegs=0;
  for(const s of ds.segments)
    if(s.payloadLen>0&&!s.retx&&s.state!=="Keep-alive"&&
       s.state!=="Window-probe")dataSegs++;
  let acked=0;
  if(ds.ackCorr.sndUna!=null&&ds.relBase!=null)
    acked=Math.max(0,ds.ackCorr.sndUna-ds.relBase);
  let outstanding=0;
  if(ds.sndMax!=null&&ds.ackCorr.sndUna!=null)
    outstanding=Math.max(0,ds.sndMax-ds.ackCorr.sndUna);
  return {packets:ds.packets,bytes:ds.bytes,payload_bytes:ds.payloadBytes,
    unique_bytes:ds.transmitted.totalBytes(),
    acked_bytes:acked,outstanding_bytes:outstanding,
    data_segments:dataSegs,retrans_segments:ds.retransSegments,
    retrans_bytes:ds.retransBytes,dup_packets:ds.dupPackets,
    ooo_packets:ds.oooPackets,keepalives:ds.keepaliveCount,
    network_dups:ds.networkDups,
    sack_events:ds.scoreboard.records.length,
    sack_blocks:ds.scoreboard.sackBlockTotal,
    sack_holes:ds.scoreboard.holeHistory.length,
    dsack_events:ds.scoreboard.dsackCount,
    zero_window_events:ds.window.zeroCount,
    seq_base_raw:ds.relBase!=null?(ds.relBase%M32+M32)%M32:0,
    window_min:ds.window.minW,window_max:ds.window.maxW,
    window_scale:ds.ws,mss:ds.mss,sack_permitted:ds.sackPermitted,
    tcp_timestamps:ds.tsopt};
}
function segmentsJson(ds,direction){
  return ds.segments.map(s=>({frame:s.frame,ts:s.ts,dir:direction,
    seq:ds.rel(s.seq),end:ds.rel(s.end),seq_raw:s.seq,len:s.payloadLen,
    flags:flagsToStr(s.flags),state:s.state,retx:s.retx,
    retx_kind:s.retxKind,retx_of:s.retxOf,retx_delay:s.retxDelay,
    acked_ts:s.ackedTs,ack_frame:s.ackedBy,ack_lat:s.ackLat,
    rtt:s.rtt,rtt_ambiguous:s.rttAmb,
    sacked_ts:s.sackedTs,sack_frame:s.sackedBy}));
}
function sessionToJson(sess,firstAbsNs){
  const a=sess.dirA,b=sess.dirB;
  const da=dirStats(a),db=dirStats(b);
  let clientEp,serverEp,cd,sd,clientDir;
  if(sess.clientDir==null||sess.clientDir==="A->B"){
    clientEp=sess.epA;serverEp=sess.epB;cd=da;sd=db;clientDir="A->B";
  }else{
    clientEp=sess.epB;serverEp=sess.epA;cd=db;sd=da;clientDir="B->A";
  }
  const rttSamples=[];
  for(const ds of [a,b])
    for(const s of ds.rtt.samples)
      rttSamples.push({ts:s.ts,rtt:s.rtt,kind:s.kind,dir:s.dir,
        frame_data:s.frameData,frame_ack:s.frameAck,
        seq:ds.rel(s.seq),end:ds.rel(s.end)});
  const rttAmbiguous=[];
  for(const ds of [a,b])
    for(const x of ds.rtt.ambiguous)
      rttAmbiguous.push({...x,dir:ds.direction});
  const ackLat=[];
  for(const ds of [a,b])
    for(const s of ds.segments)
      if(s.ackLat!=null&&s.ackLat>=0&&s.payloadLen>0)ackLat.push(s.ackLat);
  const rttVals=rttSamples.map(s=>s.rtt);

  const lossEvents=[],recoveryVals=[];
  let sackRecovered=0;
  for(const ds of [a,b])
    for(const ev of ds.loss.events){
      const detection=(ev.original_tx_ns!=null&&ev.first_evidence_ns!=null)?
        ev.first_evidence_ns-ev.original_tx_ns:null;
      const reaction=(ev.first_evidence_ns!=null&&ev.retrans_ns!=null)?
        ev.retrans_ns-ev.first_evidence_ns:null;
      const postRetrans=(ev.retrans_ns!=null&&ev.recovery_ns!=null)?
        ev.recovery_ns-ev.retrans_ns:null;
      const total=(ev.original_tx_ns!=null&&ev.recovery_ns!=null)?
        ev.recovery_ns-ev.original_tx_ns:null;
      lossEvents.push({
        loss_id:`S${sess.id}-L${ev.loss_id}-${ds.direction}`,
        dir:ev.direction,seq:ds.rel(ev.seq),end:ds.rel(ev.end),
        bytes:ev.bytes,original_tx:ev.original_tx_ns,
        original_frame:ev.original_frame,
        evidence_ts:ev.first_evidence_ns,evidence_frame:ev.first_evidence_frame,
        evidence_kind:ev.evidence_kind,
        retrans_ts:ev.retrans_ns,retrans_frame:ev.retrans_frame,
        retrans_lost:ev.retrans_lost,
        recovery_ts:ev.recovery_ns,recovery_frame:ev.recovery_frame,
        recovered:ev.recovered,partial:ev.partial,
        detection_ns:detection,reaction_ns:reaction,
        post_retrans_ns:postRetrans,total_ns:total,
        sack:ev.sack_involved,dup_acks:ev.dup_ack_count,
        sack_reports:ev.sack_report_count,
        additional_holes:ev.additional_holes,
        mechanism:ev.likely_mechanism,classification:ev.classification,
        classification_evidence:ev.classification_evidence});
      if(ev.classification==="loss"&&ev.recovered){
        if(ev.sack_involved)sackRecovered++;
        if(total!=null)recoveryVals.push(total);
      }
    }
  const retransEvents=[];let spurious=0;
  for(const ds of [a,b])
    for(const rt of ds.retransEvents){
      if(rt.cls==="possible-spurious")spurious++;
      retransEvents.push({frame:rt.frame,ts:rt.ts,dir:rt.dir,
        seq:ds.rel(rt.seq),end:ds.rel(rt.end),bytes:rt.bytes,"class":rt.cls,
        orig_frame:rt.origFrame,orig_ts:rt.origTs,delay:rt.delay,
        dup_acks:rt.dupAcks,sack:rt.sack,evidence:rt.evidence});
    }
  const dupTrains=[];let totalDupAcks=0;
  for(const [ds,dname] of [[a,"A->B"],[b,"B->A"]]){
    const peer=ds===a?b:a;
    for(const t of ds.dupAckTrains){
      totalDupAcks+=t.count;
      dupTrains.push({dir:dname,ack:peer.rel(t.ack),
        first_frame:t.first_frame,first_ts:t.first_ts,count:t.count,
        gaps_ns:t.gaps_ns,sack_blocks:t.sack_blocks,
        missing_seq:peer.rel(t.missing_seq),missing_end:peer.rel(t.missing_end),
        retrans_frame:t.retrans_frame,time_to_retrans:t.time_to_retrans,
        time_to_recovery:t.time_to_recovery});
    }
  }
  const windowEvents=[];
  for(const ds of [a,b])
    for(const w of ds.window.events)
      windowEvents.push({kind:w.kind,dir:w.dir,frame:w.frame,ts:w.ts,
        window:w.window,detail:w.detail});
  const observationEvents=[];
  for(const [ds,dname] of [[a,"A->B"],[b,"B->A"]])
    for(const ev of ds.observationEvents)
      observationEvents.push({...ev,dir:dname});
  const obsDeltas=observationEvents.map(e=>e.delta_ns);
  const sackRecords=[];
  for(const ds of [a,b])
    for(const rec of ds.scoreboard.records)
      sackRecords.push({frame:rec.frame,ts:rec.ts,data_dir:ds.direction,
        ack:ds.rel(rec.ack),
        blocks:rec.blocks.map(([l,r])=>[ds.rel(l),ds.rel(r)]),
        dsack:rec.dsack,dsack_reason:rec.dsack_reason});
  const sackSnapshots={};
  for(const [ds,dname] of [[a,"A->B"],[b,"B->A"]])
    sackSnapshots[dname]=ds.scoreboard.snapshots.map(s=>({
      frame:s.frame,ts:s.ts,ack:ds.rel(s.ack),
      sacked:s.sacked.map(([x,y])=>[ds.rel(x),ds.rel(y)]),
      holes:s.holes.map(([x,y])=>[ds.rel(x),ds.rel(y)]),
      dsack:s.dsack,ack_advanced:s.ack_advanced}));
  const hs={complete:sess.handshakeComplete,
    syn_frame:sess.synFrame,syn_ts:sess.synTs,
    synack_frame:sess.synackFrame,synack_ts:sess.synackTs,
    ack_frame:sess.estAckFrame,ack_ts:sess.estAckTs,
    syn_synack_ns:(sess.synTs!=null&&sess.synackTs!=null)?
      sess.synackTs-sess.synTs:null,
    synack_ack_ns:(sess.synackTs!=null&&sess.estAckTs!=null)?
      sess.estAckTs-sess.synackTs:null,
    total_ns:(sess.synTs!=null&&sess.estAckTs!=null)?
      sess.estAckTs-sess.synTs:null};
  let sackActive=null;
  if(a.sackPermitted!=null&&b.sackPermitted!=null)
    sackActive=!!(a.sackPermitted&&b.sackPermitted);
  else if(a.scoreboard.records.length||b.scoreboard.records.length)
    sackActive=true;
  let lossCount=0,recoveredCount=0;
  for(const e of lossEvents)
    if(e.classification==="loss"){lossCount++;if(e.recovered)recoveredCount++;}
  const dataSegments=da.data_segments+db.data_segments;
  const retransSegments=da.retrans_segments+db.retrans_segments;
  const denom=dataSegments+retransSegments;
  const stats={payload_bytes:da.payload_bytes+db.payload_bytes,
    data_segments:denom,retrans_segments:retransSegments,
    retrans_bytes:da.retrans_bytes+db.retrans_bytes,
    retrans_pct:denom?100.0*retransSegments/denom:0.0,
    dup_acks:totalDupAcks,
    ooo_packets:da.ooo_packets+db.ooo_packets,
    dup_packets:da.dup_packets+db.dup_packets,
    sack_events:da.sack_events+db.sack_events,
    sack_blocks:da.sack_blocks+db.sack_blocks,
    sack_holes:da.sack_holes+db.sack_holes,
    dsack_events:da.dsack_events+db.dsack_events,
    loss_events:lossCount,recovered_losses:recoveredCount,
    unrecovered_losses:lossCount-recoveredCount,
    sack_recovered_losses:sackRecovered,spurious_retrans:spurious,
    zero_window_events:da.zero_window_events+db.zero_window_events,
    network_dups:da.network_dups+db.network_dups,
    observation_skew:summarize(obsDeltas),
    rst:a.rstSeen||b.rstSeen,rst_frame:sess.rstFrame,
    fin:a.finSeen||b.finSeen,partial:sess.partial,
    rtt:summarize(rttVals),ack_latency:summarize(ackLat),
    recovery:summarize(recoveryVals)};
  const verdicts=evaluateVerdicts(stats,VERDICT_CFG);
  const warnings=sessionArtifacts(sess);
  const absStart=sess.firstTs!=null?firstAbsNs+BigInt(sess.firstTs):null;
  const absEnd=sess.lastTs!=null?firstAbsNs+BigInt(sess.lastTs):null;
  return {id:sess.id,
    label:`Session #${String(sess.id).padStart(5,"0")}`,
    client:`${clientEp[0]}:${clientEp[1]}`,
    server:`${serverEp[0]}:${serverEp[1]}`,
    client_ip:clientEp[0],server_ip:serverEp[0],
    client_port:clientEp[1],server_port:serverEp[1],
    client_dir:clientDir,
    ep_a:`${sess.epA[0]}:${sess.epA[1]}`,ep_b:`${sess.epB[0]}:${sess.epB[1]}`,
    capture_id:sess.captureId,
    start_ts:sess.firstTs,end_ts:sess.lastTs,
    start_str:fmtNsUtc(absStart),end_str:fmtNsUtc(absEnd),
    duration_ns:sess.firstTs!=null?sess.lastTs-sess.firstTs:0,
    partial:sess.partial,
    state:stats.rst?"reset":
          (a.finSeen&&b.finSeen)?"closed":
          stats.fin?"half-closed":
          sess.handshakeComplete?"established":"partial",
    handshake:hs,
    sack_client:cd.sack_permitted,sack_server:sd.sack_permitted,
    sack_active:sackActive,
    dir_a:da,dir_b:db,stats,verdicts,warnings,
    segments:[...segmentsJson(a,"A->B"),...segmentsJson(b,"B->A")],
    rtt_samples:rttSamples,rtt_ambiguous:rttAmbiguous,
    rtt_hist:histogram(rttVals),ack_hist:histogram(ackLat),
    recovery_hist:histogram(recoveryVals),
    loss_events:lossEvents,retrans_events:retransEvents,
    dup_ack_trains:dupTrains,window_events:windowEvents,
    observation_events:observationEvents,
    sack_records:sackRecords,sack_snapshots:sackSnapshots,
    packets:sess.packetRows,packets_truncated:sess.rowsDropped};
}

/* --------------------------------------------------------------- driver */
const SER_CAPS={segments:20000,rtt_samples:20000,sack_records:10000,
                sack_snapshots:10000};
/* analyze one capture (File/ArrayBuffer) or SEVERAL (array): multiple
 * captures are k-way merged into one timeline by timestamp — a file
 * boundary is an observation point for multi-point duplicate recognition,
 * exactly mirroring the Python engine. */
async function analyze(input,fileName,progress){
  const inputs=Array.isArray(input)?input:[input];
  const names=inputs.map((f,i)=>(f&&f.name)||fileName||("capture"+i));
  const multi=inputs.length>1;
  const srcs=inputs.map(f=>new ChunkedSource(f));
  const totalBytes=srcs.reduce((t,s)=>t+s.size,0);
  const readers=srcs.map(()=>new CaptureReader());
  const gens=srcs.map((s,i)=>readers[i].frames(s));
  const mgr=new SessionManager({...DEFAULT_CFG},20000);
  // prime one pending frame per stream, then always consume the earliest
  const pending=new Array(gens.length).fill(null);
  for(let i=0;i<gens.length;i++){
    const r=await gens[i].next();
    pending[i]=r.done?null:r.value;
  }
  let n=0,globalFrame=0,anchor=null;
  const CHUNK=20000;let sinceYield=0;
  const consumed=()=>readers.reduce(
    (t,rd)=>t+(rd.window?rd.window.consumedBytes:0),0);
  for(;;){
    let best=-1;
    for(let i=0;i<pending.length;i++){
      if(pending[i]&&(best<0||pending[i].absNs<pending[best].absNs))best=i;
    }
    if(best<0)break;
    const f=pending[best], rd=readers[best];
    globalFrame++;
    f.frameNo=globalFrame;
    if(anchor==null){
      for(const r of readers)
        if(r.firstAbsNs!=null&&(anchor==null||r.firstAbsNs<anchor))
          anchor=r.firstAbsNs;
    }
    const pkt=decodeTcp(rd,f);
    if(pkt){
      pkt.captureId=best;
      // capture-relative ns anchored at the merged timeline's first packet
      pkt.tsRel=Number(f.absNs-anchor);
      rd.tcpCount++;
      mgr.feed(pkt);
      n++;
    }
    const r=await gens[best].next();
    pending[best]=r.done?null:r.value;
    if(progress&&++sinceYield>=CHUNK){
      sinceYield=0;
      progress(readers.reduce((t,x)=>t+x.packetCount,0),n,
               mgr.sessions.length,consumed(),totalBytes);
      await new Promise(res=>setTimeout(res,0));
    }
  }
  if(progress)progress(readers.reduce((t,x)=>t+x.packetCount,0),n,
                       mgr.sessions.length,totalBytes,totalBytes);

  const firstAbsNs=anchor!=null?anchor:0n;
  const sessions=mgr.sessions.map(s=>sessionToJson(s,firstAbsNs));
  const totals={sessions:mgr.sessions.length,tcp_packets:n,
    payload_bytes:0,retrans_segments:0,data_segments:0,
    sack_events:0,dsack_events:0,loss_events:0,recovered_losses:0,
    dup_acks:0,ooo_packets:0,dup_packets:0,zero_window_events:0,resets:0,
    network_dups:0};
  const globalRtt=[],globalRecovery=[];
  for(const sj of sessions){
    const st=sj.stats;
    totals.payload_bytes+=st.payload_bytes;
    totals.retrans_segments+=st.retrans_segments;
    totals.data_segments+=st.data_segments;
    totals.sack_events+=st.sack_events;
    totals.dsack_events+=st.dsack_events;
    totals.loss_events+=st.loss_events;
    totals.recovered_losses+=st.recovered_losses;
    totals.dup_acks+=st.dup_acks;
    totals.ooo_packets+=st.ooo_packets;
    totals.dup_packets+=st.dup_packets;
    totals.zero_window_events+=st.zero_window_events;
    totals.network_dups+=st.network_dups;
    if(st.rst)totals.resets++;
    for(const s of sj.rtt_samples)globalRtt.push(s.rtt);
    for(const e of sj.loss_events)
      if(e.total_ns!=null&&e.classification==="loss")
        globalRecovery.push(e.total_ns);
  }
  totals.retrans_pct=totals.data_segments?
    100.0*totals.retrans_segments/totals.data_segments:0.0;
  // bound embedded row listings (statistics above cover the full data) —
  // identical caps and ordering to the Python engine, so parity holds
  for(const sj of sessions){
    for(const [key,cnt] of [["segments","segments_truncated"],
                            ["rtt_samples","rtt_truncated"],
                            ["sack_records","sack_truncated"]]){
      const cap=key==="sack_records"?SER_CAPS.sack_records:SER_CAPS[key];
      if(sj[key].length>cap){
        sj[cnt]=sj[key].length-cap;sj[key]=sj[key].slice(0,cap);
      }else sj[cnt]=0;
    }
    sj.sack_snap_truncated=0;
    for(const dname of Object.keys(sj.sack_snapshots)){
      const snaps=sj.sack_snapshots[dname];
      if(snaps.length>SER_CAPS.sack_snapshots){
        sj.sack_snap_truncated+=snaps.length-SER_CAPS.sack_snapshots;
        sj.sack_snapshots[dname]=snaps.slice(0,SER_CAPS.sack_snapshots);
      }
    }
  }
  const rd0=readers[0];
  const allRes=readers.flatMap(r=>r.resolutions);
  const coarsest=allRes.length?Math.min(...allRes):null;
  let lastAbs=null;
  for(const r of readers)
    if(r.lastAbsNs!=null&&(lastAbs==null||r.lastAbsNs>lastAbs))
      lastAbs=r.lastAbsNs;
  const durationNs=(anchor!=null&&lastAbs!=null)?Number(lastAbs-anchor):0;
  const formats=[];
  for(const r of readers)
    if(!formats.includes(r.fileFormat))formats.push(r.fileFormat);
  const snaplens=readers.map(r=>r.snaplen).filter(x=>x!=null);
  let warnings=multi
    ?readers.flatMap((r,i)=>r.warnings.map(w=>`${names[i]}: ${w}`))
    :readers.flatMap(r=>r.warnings);
  if(multi)
    warnings=[`merged timeline of ${readers.length} capture files — frames `+
      "interleaved by timestamp; a file boundary is treated as an "+
      "observation point for multi-point duplicate recognition",...warnings];
  const pathLabel=multi?names.join(" + "):names[0];
  const capture={path:pathLabel,capture_id:0,capture_point:pathLabel,
    format:formats.join("+"),
    resolution_label:coarsest!=null?rd0.resLabel(coarsest):"unknown",
    effective_precision_ns:coarsest!=null?rd0.nsPerTick(coarsest):1000000000,
    nanosecond_native:!!(coarsest&&coarsest>=1e9),
    first_ts:0,first_ts_str:fmtNsUtc(anchor),
    last_ts:durationNs,last_ts_str:fmtNsUtc(lastAbs),
    duration_ns:durationNs,duration_str:fmtDurationNs(durationNs),
    packets:readers.reduce((t,r)=>t+r.packetCount,0),
    tcp_packets:readers.reduce((t,r)=>t+r.tcpCount,0),
    snaplen:snaplens.length?Math.min(...snaplens):null,
    truncated_frames:readers.reduce((t,r)=>t+r.truncatedFrames,0),
    warnings,
    files:names.map((nm,i)=>({name:nm,packets:readers[i].packetCount,
      tcp_packets:readers[i].tcpCount,format:readers[i].fileFormat}))};
  return {tool:{name:"tcpforensics",version:"1.0.0-web"},
    capture,totals,
    rtt_summary:summarize(globalRtt),rtt_hist:histogram(globalRtt),
    recovery_summary:summarize(globalRecovery),
    recovery_hist:histogram(globalRecovery),
    verdict_config:{...VERDICT_CFG},
    sessions};
}

return {analyze};
})();
