"""Synthetic capture builder for validation tests.

Crafts Ethernet/IPv4/TCP frames byte-by-byte and writes them as classic
pcap (microsecond or nanosecond) or pcapng (with if_tsresol), so every test
controls exact timestamps and TCP header contents.
"""

from __future__ import annotations

import struct


# ------------------------------------------------------------- TCP options
def opt_mss(mss: int) -> bytes:
    return struct.pack(">BBH", 2, 4, mss)


def opt_wscale(shift: int) -> bytes:
    return struct.pack(">BBB", 3, 3, shift)


def opt_sack_perm() -> bytes:
    return struct.pack(">BB", 4, 2)


def opt_sack(blocks) -> bytes:
    body = b"".join(struct.pack(">II", l, r) for l, r in blocks)
    return struct.pack(">BB", 5, 2 + len(body)) + body


def opt_ts(val: int, ecr: int) -> bytes:
    return struct.pack(">BBII", 8, 10, val, ecr)


def _pad_opts(opts: bytes) -> bytes:
    while len(opts) % 4:
        opts += b"\x01"          # NOP padding
    return opts


# ------------------------------------------------------------------ frames
def tcp_frame(src: str, dst: str, sport: int, dport: int, seq: int, ack: int,
              flags: int, payload: bytes = b"", window: int = 65535,
              options: bytes = b"", ip_id: int = 0, ttl: int = 64,
              src_mac: str = "04:04:04:04:04:04",
              dst_mac: str = "02:02:02:02:02:02",
              vlan: int | None = None) -> bytes:
    options = _pad_opts(options)
    data_off = (20 + len(options)) // 4
    tcp = struct.pack(">HHIIHHHH", sport, dport, seq & 0xFFFFFFFF,
                      ack & 0xFFFFFFFF, (data_off << 12) | flags,
                      window, 0, 0) + options + payload
    total_len = 20 + len(tcp)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, total_len, ip_id & 0xFFFF,
                     0x4000, ttl, 6, 0, _ip(src), _ip(dst))
    eth = _mac(dst_mac) + _mac(src_mac)
    if vlan is not None:
        eth += struct.pack(">HH", 0x8100, vlan & 0x0FFF) + b"\x08\x00"
    else:
        eth += b"\x08\x00"
    return eth + ip + tcp


def _mac(m: str) -> bytes:
    return bytes(int(x, 16) for x in m.split(":"))


def _ip(a: str) -> bytes:
    return bytes(int(x) for x in a.split("."))


# ----------------------------------------------------------------- writers
def write_pcap(path: str, frames: list[tuple[int, bytes]], nano: bool = False,
               snaplen: int = 262144) -> None:
    """frames = [(timestamp_ns, frame_bytes), ...]"""
    with open(path, "wb") as fh:
        magic = 0xA1B23C4D if nano else 0xA1B2C3D4
        fh.write(struct.pack(">IHHiIII", magic, 2, 4, 0, 0, snaplen, 1))
        for ts_ns, frame in frames:
            sec, rem = divmod(ts_ns, 1_000_000_000)
            frac = rem if nano else rem // 1000
            fh.write(struct.pack(">IIII", sec, frac, len(frame), len(frame)))
            fh.write(frame)


def write_pcapng(path: str, frames: list[tuple[int, bytes]],
                 tsresol_pow10: int = 9) -> None:
    """pcapng with one Ethernet interface at 10^-tsresol_pow10 resolution."""
    with open(path, "wb") as fh:
        # SHB
        body = struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)
        fh.write(_block(0x0A0D0D0A, body))
        # IDB with if_tsresol option
        opt = struct.pack("<HHB3x", 9, 1, tsresol_pow10)
        end = struct.pack("<HH", 0, 0)
        fh.write(_block(0x00000001, struct.pack("<HHI", 1, 0, 262144) + opt + end))
        ticks_per_s = 10 ** tsresol_pow10
        for ts_ns, frame in frames:
            ticks = ts_ns * ticks_per_s // 1_000_000_000
            pad = (-len(frame)) % 4
            body = struct.pack("<IIIII", 0, ticks >> 32, ticks & 0xFFFFFFFF,
                               len(frame), len(frame)) + frame + b"\x00" * pad
            fh.write(_block(0x00000006, body))


def _block(btype: int, body: bytes) -> bytes:
    blen = 12 + len(body)
    return struct.pack("<II", btype, blen) + body + struct.pack("<I", blen)


# ----------------------------------------------------- scripted TCP flows
FIN, SYN, RST, PSH, ACK = 1, 2, 4, 8, 16

CLIENT = "10.0.0.1"
SERVER = "10.0.0.2"
CPORT, SPORT = 40000, 80


class Flow:
    """Scripted bidirectional TCP flow with explicit nanosecond timestamps."""

    def __init__(self, client_isn: int = 1000, server_isn: int = 50000,
                 client=CLIENT, server=SERVER, cport=CPORT, sport=SPORT):
        self.frames: list[tuple[int, bytes]] = []
        self.cisn, self.sisn = client_isn, server_isn
        self.client, self.server = client, server
        self.cport, self.sport = cport, sport

    def add(self, ts_ns: int, frame: bytes) -> None:
        self.frames.append((ts_ns, frame))

    def c2s(self, ts, seq, ack, flags, payload=b"", window=65535, options=b"",
            **l23):
        self.add(ts, tcp_frame(self.client, self.server, self.cport, self.sport,
                               seq, ack, flags, payload, window, options, **l23))

    def s2c(self, ts, seq, ack, flags, payload=b"", window=65535, options=b"",
            **l23):
        self.add(ts, tcp_frame(self.server, self.client, self.sport, self.cport,
                               seq, ack, flags, payload, window, options, **l23))

    def handshake(self, t0: int, rtt_ns: int = 100_000,
                  client_opts: bytes | None = None,
                  server_opts: bytes | None = None) -> int:
        """SYN at t0, SYN/ACK at t0+rtt, ACK at t0+2*rtt.  Returns next ts."""
        if client_opts is None:
            client_opts = opt_mss(1460) + opt_sack_perm() + opt_wscale(7)
        if server_opts is None:
            server_opts = opt_mss(1460) + opt_sack_perm() + opt_wscale(7)
        self.c2s(t0, self.cisn, 0, SYN, options=client_opts)
        self.s2c(t0 + rtt_ns, self.sisn, self.cisn + 1, SYN | ACK,
                 options=server_opts)
        self.c2s(t0 + 2 * rtt_ns, self.cisn + 1, self.sisn + 1, ACK)
        return t0 + 2 * rtt_ns
