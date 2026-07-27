"""Generate a demo nanosecond capture exercising most analyzer features.

    python examples/make_demo_capture.py demo.pcap
    python -m tcpforensics demo.pcap -o demo_report.html
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.pcap_builder import (ACK, FIN, PSH, RST, Flow, opt_sack, write_pcap)

T0 = 1_700_000_000 * 1_000_000_000
frames = []


def add(flow):
    frames.extend(flow.frames)


# --- session 1: healthy bulk transfer -----------------------------------
f = Flow(client="10.10.10.20", server="10.20.20.50", cport=52144, sport=9000)
b = f.handshake(T0, 120_000)
d = b + 50_000
seq = 1001
for i in range(20):
    f.c2s(d + i * 40_000, seq, 50001, ACK | (PSH if i % 4 == 3 else 0),
          b"D" * 1000)
    seq += 1000
    if i % 2 == 1:
        f.s2c(d + i * 40_000 + 95_000, 50001, seq, ACK)
f.c2s(d + 900_000, seq, 50001, FIN | ACK)
f.s2c(d + 950_000, 50001, seq + 1, FIN | ACK)
f.c2s(d + 1_000_000, seq + 1, 50002, ACK)
add(f)

# --- session 2: loss + dup-ACKs + SACK + fast retransmit ----------------
f = Flow(client="10.10.10.21", server="10.20.20.50", cport=41000, sport=9000)
b = f.handshake(T0 + 2_000_000_000, 150_000)
d = b + 60_000
f.c2s(d + 0,      1001, 50001, ACK, b"a" * 500)
f.c2s(d + 12_000, 1501, 50001, ACK, b"b" * 500)      # lost on path
f.c2s(d + 24_000, 2001, 50001, ACK, b"c" * 500)
f.c2s(d + 36_000, 2501, 50001, ACK, b"d" * 500)
f.c2s(d + 48_000, 3001, 50001, ACK, b"e" * 500)
f.s2c(d + 60_000, 50001, 1501, ACK)
f.s2c(d + 74_000, 50001, 1501, ACK, options=opt_sack([(2001, 2501)]))
f.s2c(d + 88_000, 50001, 1501, ACK, options=opt_sack([(2001, 3001)]))
f.s2c(d + 102_000, 50001, 1501, ACK, options=opt_sack([(2001, 3501)]))
f.c2s(d + 121_500, 1501, 50001, ACK, b"b" * 500)     # fast retransmit
f.s2c(d + 173_800, 50001, 3501, ACK)                 # recovery
f.c2s(d + 300_000, 3501, 50001, FIN | ACK)
f.s2c(d + 350_000, 50001, 3502, FIN | ACK)
f.c2s(d + 400_000, 3502, 50002, ACK)
add(f)

# --- session 3: reordering (no loss) ------------------------------------
f = Flow(client="10.10.10.22", server="10.20.20.51", cport=41500, sport=443)
b = f.handshake(T0 + 4_000_000_000, 90_000)
d = b + 40_000
f.c2s(d, 1001, 50001, ACK, b"1" * 400)
f.c2s(d + 8_000, 1801, 50001, ACK, b"3" * 400)       # arrives early
f.c2s(d + 11_500, 1401, 50001, ACK, b"2" * 400)      # late (reordered)
f.s2c(d + 70_000, 50001, 2201, ACK)
add(f)

# --- session 4: zero-window stall ---------------------------------------
f = Flow(client="10.10.10.23", server="10.20.20.52", cport=42000, sport=8080)
b = f.handshake(T0 + 6_000_000_000, 200_000)
d = b + 50_000
f.c2s(d, 1001, 50001, ACK, b"Z" * 1200)
f.s2c(d + 90_000, 50001, 2201, ACK, window=0)
f.c2s(d + 5_090_000, 2201, 50001, ACK, b"p")          # probe after 5 ms
f.s2c(d + 9_100_000, 50001, 2202, ACK, window=500)    # window reopens
f.c2s(d + 9_200_000, 2202, 50001, ACK, b"Z" * 800)
f.s2c(d + 9_300_000, 50001, 3002, ACK)
add(f)

# --- session 5: RST abort ------------------------------------------------
f = Flow(client="10.10.10.24", server="10.20.20.53", cport=42500, sport=6379)
b = f.handshake(T0 + 8_000_000_000, 80_000)
f.c2s(b + 30_000, 1001, 50001, ACK, b"PING\r\n")
f.s2c(b + 95_000, 50001, 1007, RST | ACK)
add(f)

# --- session 6: RTO retransmission + spurious/DSACK ----------------------
f = Flow(client="10.10.10.25", server="10.20.20.50", cport=43000, sport=9000)
b = f.handshake(T0 + 10_000_000_000, 110_000)
d = b + 40_000
f.c2s(d, 1001, 50001, ACK, b"r" * 600)
f.c2s(d + 320_000_000, 1001, 50001, ACK, b"r" * 600)   # RTO retransmit
f.s2c(d + 320_090_000, 50001, 1601, ACK)
f.c2s(d + 321_000_000, 1001, 50001, ACK, b"r" * 600)   # spurious again
f.s2c(d + 321_080_000, 50001, 1601, ACK,
      options=opt_sack([(1001, 1601)]))                # DSACK
add(f)

# --- session 7: multi-point SPAN — same packets seen on two leafs --------
f = Flow(client="10.10.10.27", server="10.20.20.55", cport=44000, sport=9200)
from tests.pcap_builder import SYN, opt_mss, opt_sack_perm, opt_wscale
opts = opt_mss(1460) + opt_sack_perm() + opt_wscale(7)
t = T0 + 14_000_000_000
f.c2s(t, 1000, 0, SYN, options=opts, ip_id=201, ttl=64,
      src_mac="aa:aa:aa:00:00:01", vlan=100)
f.c2s(t + 9_200, 1000, 0, SYN, options=opts, ip_id=201, ttl=63,
      src_mac="cc:cc:cc:00:00:02", vlan=200)          # egress leaf
f.s2c(t + 130_000, 60000, 1001, SYN | ACK, options=opts, ip_id=801, ttl=64)
f.c2s(t + 260_000, 1001, 60001, ACK, ip_id=202, ttl=64,
      src_mac="aa:aa:aa:00:00:01", vlan=100)
f.c2s(t + 269_400, 1001, 60001, ACK, ip_id=202, ttl=63,
      src_mac="cc:cc:cc:00:00:02", vlan=200)
d = t + 300_000
seq, ipid = 1001, 203
for i in range(4):
    f.c2s(d + i * 50_000, seq, 60001, ACK | PSH, b"M" * 700, ip_id=ipid,
          ttl=64, src_mac="aa:aa:aa:00:00:01", vlan=100)
    f.c2s(d + i * 50_000 + 8_000 + i * 900, seq, 60001, ACK | PSH, b"M" * 700,
          ip_id=ipid, ttl=63, src_mac="cc:cc:cc:00:00:02", vlan=200)
    seq += 700; ipid += 1
    f.s2c(d + i * 50_000 + 120_000, 60000 + 1, seq, ACK, ip_id=802 + i)
add(f)

# --- session 8: mid-capture partial session ------------------------------
f = Flow(client="10.10.10.26", server="10.20.20.54", cport=43500, sport=5201)
d = T0 + 12_000_000_000
seq = 900_000
for i in range(6):
    f.c2s(d + i * 30_000, seq, 4_000_000, ACK, b"m" * 1400)
    seq += 1400
    f.s2c(d + i * 30_000 + 62_000, 4_000_000, seq, ACK)
add(f)

frames.sort(key=lambda x: x[0])
out = sys.argv[1] if len(sys.argv) > 1 else "demo.pcap"
write_pcap(out, frames, nano=True)
print(f"wrote {out}: {len(frames)} frames")
