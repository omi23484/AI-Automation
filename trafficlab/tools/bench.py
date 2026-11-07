"""Scale benchmark on SYNTHETIC rows (fake). Usage: python3 tools/bench.py DEVICES IFACES DAYS INTERVAL_S [WORKERS]
Reports wall time per stage and peak RSS of this process (workers not included)."""
import math, os, random, resource, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timedelta
from trafficlab import ingest, counters, pipeline
from trafficlab.synth import SYN_MAPPING

dev, ifs, days, iv = (int(x) for x in sys.argv[1:5])
workers = int(sys.argv[5]) if len(sys.argv) > 5 else None
rnd = random.Random(1)
t0 = datetime(2026, 1, 5)
n = days * 86400 // iv
cnt = {(d, i): [rnd.randrange(2 ** 40), rnd.randrange(2 ** 40), 1_000_000] for d in range(dev) for i in range(ifs)}
lines = ["timestamp,device,interface,zone,in_octets,out_octets,uptime_cs,speed_mbps"]
tg = time.time()
for k in range(n):
    ts = (t0 + timedelta(seconds=k * iv)).strftime("%Y-%m-%d %H:%M:%S")
    h = (k * iv % 86400) / 3600
    f = 0.55 + 0.45 * math.sin((h - 9) / 24 * 6.2832)
    for (d, i), c in cnt.items():
        c[0] += int(1e9 * f * iv / 8 * (1 + rnd.random() * .1)); c[1] += int(4e8 * f * iv / 8); c[2] += iv * 100
        lines.append(f"{ts},SYN-{['WAN','ENT','DC'][d%3]}-{d},Eth1/{i},{['WAN','ENT','DC'][d%3]},{c[0]},{c[1]},{c[2]},10000")
text = "\n".join(lines); del lines
print(f"gen {time.time()-tg:.1f}s rows={n*dev*ifs:,} csv={len(text)/1e6:.0f}MB")
t = time.time(); ds = ingest.load_csv(text, SYN_MAPPING, ["%Y-%m-%d %H:%M:%S"]); t_ing = time.time() - t
del text
t = time.time(); sl, dq = counters.build_all(ds); t_ser = time.time() - t
t = time.time(); r = pipeline.analyze(sl, workers=workers); t_an = time.time() - t
print(f"ingest {t_ing:.1f}s  series-build {t_ser:.1f}s  analyze {t_an:.1f}s (workers={r['workers']})  series={len(sl)}  findings={len(r['findings'])}")
print(f"peak RSS (main process) {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB")
