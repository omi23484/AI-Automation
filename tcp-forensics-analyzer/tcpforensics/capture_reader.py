"""Streaming PCAP / PCAPNG reader and TCP decoder (pure stdlib).

Packets are decoded one at a time and yielded as compact
:class:`~tcpforensics.models.TCPPacket` objects; the raw capture bytes are
never held in memory.  Timestamp resolution is taken from the file itself:

* classic pcap: magic 0xA1B2C3D4 -> microseconds, 0xA1B23C4D -> nanoseconds
* pcapng: per-interface ``if_tsresol`` option (default 10^-6)

and every timestamp is normalized to integer nanoseconds.
"""

from __future__ import annotations

import struct
from typing import BinaryIO, Iterator

from .models import TCPPacket
from .timestamp_engine import CaptureTimeInfo, TimestampResolution

PCAP_MAGIC_US_BE = 0xA1B2C3D4
PCAP_MAGIC_US_LE = 0xD4C3B2A1
PCAP_MAGIC_NS_BE = 0xA1B23C4D
PCAP_MAGIC_NS_LE = 0x4D3CB2A1
PCAPNG_SHB = 0x0A0D0D0A

# link types we can decode
LINKTYPE_NULL = 0
LINKTYPE_ETHERNET = 1
LINKTYPE_RAW = 101
LINKTYPE_LINUX_SLL = 113
LINKTYPE_LINUX_SLL2 = 276


class CaptureError(Exception):
    pass


class CaptureReader:
    """Iterates (frame_number, timestamp_ns, linktype, frame_bytes, truncated)."""

    def __init__(self, path: str, capture_id: int = 0, capture_point: str = ""):
        self.path = path
        self.capture_id = capture_id
        self.capture_point = capture_point or path
        self.time_info = CaptureTimeInfo()
        self.snaplen: int | None = None
        self.truncated_frames = 0
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ file
    def frames(self) -> Iterator[tuple[int, int, int, bytes, bool]]:
        with open(self.path, "rb") as fh:
            head = fh.read(4)
            if len(head) < 4:
                raise CaptureError("file too short to be a capture")
            magic_be = struct.unpack(">I", head)[0]
            if magic_be in (PCAP_MAGIC_US_BE, PCAP_MAGIC_US_LE,
                            PCAP_MAGIC_NS_BE, PCAP_MAGIC_NS_LE):
                yield from self._read_pcap(fh, magic_be)
            elif magic_be == PCAPNG_SHB:
                yield from self._read_pcapng(fh)
            else:
                raise CaptureError(f"unrecognized capture magic 0x{magic_be:08X}")

    # ------------------------------------------------------------------ pcap
    def _read_pcap(self, fh: BinaryIO, magic_be: int):
        self.time_info.file_format = "pcap"
        if magic_be in (PCAP_MAGIC_US_BE, PCAP_MAGIC_NS_BE):
            endian = ">"
        else:
            endian = "<"
        nano = magic_be in (PCAP_MAGIC_NS_BE, PCAP_MAGIC_NS_LE)
        res = TimestampResolution(1_000_000_000 if nano else 1_000_000)
        self.time_info.resolutions = [res]
        hdr = fh.read(20)
        if len(hdr) < 20:
            raise CaptureError("truncated pcap global header")
        _vmaj, _vmin, _tz, _sig, snaplen, linktype = struct.unpack(endian + "HHiIII", hdr)
        self.snaplen = snaplen
        frame_no = 0
        rec = struct.Struct(endian + "IIII")
        while True:
            rh = fh.read(16)
            if len(rh) < 16:
                break
            ts_sec, ts_frac, caplen, origlen = rec.unpack(rh)
            data = fh.read(caplen)
            if len(data) < caplen:
                self.warnings.append(
                    "capture file ends mid-record — the final packet was "
                    "discarded (interrupted or copied-while-writing capture)")
                break
            frame_no += 1
            ts_ns = ts_sec * 1_000_000_000 + (ts_frac if nano else ts_frac * 1_000)
            truncated = caplen < origlen
            if truncated:
                self.truncated_frames += 1
            self.time_info.packet_count += 1
            self.time_info.note_packet(ts_ns)
            yield frame_no, ts_ns, linktype, data, truncated

    # ---------------------------------------------------------------- pcapng
    def _read_pcapng(self, fh: BinaryIO):
        self.time_info.file_format = "pcapng"
        fh.seek(0)
        frame_no = 0
        endian = "<"
        interfaces: list[tuple[int, TimestampResolution]] = []  # (linktype, res)
        while True:
            bh = fh.read(8)
            if len(bh) < 8:
                break
            btype, blen = struct.unpack(endian + "II", bh)
            if btype == PCAPNG_SHB:
                body = fh.read(16)          # BOM + version + section length
                if len(body) < 16:
                    break
                bom = struct.unpack("<I", body[0:4])[0]
                endian = "<" if bom == 0x1A2B3C4D else ">"
                if endian == ">":
                    blen = struct.unpack(">I", bh[4:8])[0]
                # a new section resets the interface list
                interfaces = []
                remaining = blen - 8 - 16   # options + trailing block length
                if remaining > 0:
                    fh.read(remaining)
                continue
            if blen < 12 or blen % 4:
                # corrupt block: stop at the damage instead of discarding the
                # whole capture; everything read so far stays analyzable
                self.warnings.append(
                    f"corrupt pcapng block (type 0x{btype:08X}, "
                    f"length {blen}) after {self.time_info.packet_count} "
                    "packets — remainder of the file skipped")
                break
            body = fh.read(blen - 12)
            fh.read(4)  # trailing block-length
            if len(body) < blen - 12:
                self.warnings.append(
                    "capture file ends mid-block — the final block was "
                    "discarded (interrupted or copied-while-writing capture)")
                break
            if btype == 0x00000001:  # IDB
                linktype = struct.unpack(endian + "H", body[0:2])[0]
                snaplen = struct.unpack(endian + "I", body[4:8])[0]
                if self.snaplen is None or (snaplen and snaplen < self.snaplen):
                    self.snaplen = snaplen or None
                res = self._parse_if_tsresol(body[8:], endian)
                interfaces.append((linktype, res))
                self.time_info.resolutions.append(res)
            elif btype == 0x00000006:  # Enhanced Packet Block
                if len(body) < 20:
                    continue
                if_id, ts_hi, ts_lo, caplen, origlen = struct.unpack(
                    endian + "IIIII", body[0:20])
                data = body[20:20 + caplen]
                if if_id >= len(interfaces):
                    continue
                linktype, res = interfaces[if_id]
                ticks = (ts_hi << 32) | ts_lo
                ts_ns = res.to_ns(ticks)
                frame_no += 1
                truncated = caplen < origlen
                if truncated:
                    self.truncated_frames += 1
                self.time_info.packet_count += 1
                self.time_info.note_packet(ts_ns)
                yield frame_no, ts_ns, linktype, data, truncated
            elif btype == 0x00000003:  # Simple Packet Block — no timestamp
                # cannot be used for latency forensics; count and skip
                frame_no += 1
                self.time_info.packet_count += 1
            # other block types (NRB, ISB, custom) are skipped

    @staticmethod
    def _parse_if_tsresol(optbytes: bytes, endian: str) -> TimestampResolution:
        off = 0
        while off + 4 <= len(optbytes):
            code, olen = struct.unpack(endian + "HH", optbytes[off:off + 4])
            off += 4
            val = optbytes[off:off + olen]
            off += (olen + 3) & ~3
            if code == 0:
                break
            if code == 9 and olen >= 1:  # if_tsresol
                b = val[0]
                if b & 0x80:
                    return TimestampResolution(2 ** (b & 0x7F))
                return TimestampResolution(10 ** b)
        return TimestampResolution(1_000_000)  # pcapng default 10^-6

    # ------------------------------------------------------------- tcp decode
    def tcp_packets(self) -> Iterator[TCPPacket]:
        for frame_no, ts_ns, linktype, data, truncated in self.frames():
            pkt = decode_tcp(frame_no, ts_ns, linktype, data, truncated,
                             self.capture_id)
            if pkt is not None:
                self.time_info.tcp_packet_count += 1
                yield pkt


# ============================================================ frame decoding

def decode_tcp(frame_no: int, ts_ns: int, linktype: int, data: bytes,
               truncated: bool, capture_id: int) -> TCPPacket | None:
    """Decode link -> IP -> TCP; return None for anything that is not TCP."""
    try:
        if linktype == LINKTYPE_ETHERNET:
            if len(data) < 14:
                return None
            ethertype = struct.unpack(">H", data[12:14])[0]
            off = 14
            while ethertype in (0x8100, 0x88A8) and len(data) >= off + 4:  # VLAN
                ethertype = struct.unpack(">H", data[off + 2:off + 4])[0]
                off += 4
            payload = data[off:]
            if ethertype == 0x0800:
                return _decode_ipv4(frame_no, ts_ns, payload, truncated, capture_id)
            if ethertype == 0x86DD:
                return _decode_ipv6(frame_no, ts_ns, payload, truncated, capture_id)
            return None
        if linktype == LINKTYPE_RAW:
            return _decode_ip_auto(frame_no, ts_ns, data, truncated, capture_id)
        if linktype == LINKTYPE_NULL:
            if len(data) < 4:
                return None
            return _decode_ip_auto(frame_no, ts_ns, data[4:], truncated, capture_id)
        if linktype == LINKTYPE_LINUX_SLL:
            if len(data) < 16:
                return None
            proto = struct.unpack(">H", data[14:16])[0]
            if proto == 0x0800:
                return _decode_ipv4(frame_no, ts_ns, data[16:], truncated, capture_id)
            if proto == 0x86DD:
                return _decode_ipv6(frame_no, ts_ns, data[16:], truncated, capture_id)
            return None
        if linktype == LINKTYPE_LINUX_SLL2:
            if len(data) < 20:
                return None
            proto = struct.unpack(">H", data[0:2])[0]
            if proto == 0x0800:
                return _decode_ipv4(frame_no, ts_ns, data[20:], truncated, capture_id)
            if proto == 0x86DD:
                return _decode_ipv6(frame_no, ts_ns, data[20:], truncated, capture_id)
            return None
        return None
    except (struct.error, IndexError):
        return None


def _decode_ip_auto(frame_no, ts_ns, data, truncated, capture_id):
    if not data:
        return None
    ver = data[0] >> 4
    if ver == 4:
        return _decode_ipv4(frame_no, ts_ns, data, truncated, capture_id)
    if ver == 6:
        return _decode_ipv6(frame_no, ts_ns, data, truncated, capture_id)
    return None


def _decode_ipv4(frame_no, ts_ns, data, truncated, capture_id):
    if len(data) < 20 or data[0] >> 4 != 4:
        return None
    ihl = (data[0] & 0x0F) * 4
    if ihl < 20 or len(data) < ihl:
        return None
    total_len = struct.unpack(">H", data[2:4])[0]
    flags_frag = struct.unpack(">H", data[6:8])[0]
    if flags_frag & 0x1FFF:      # non-first fragment: no TCP header
        return None
    proto = data[9]
    if proto != 6:
        return None
    src = ".".join(str(b) for b in data[12:16])
    dst = ".".join(str(b) for b in data[16:20])
    ip_payload_len = max(0, min(total_len, len(data)) - ihl)
    return _decode_tcp_header(frame_no, ts_ns, src, dst, data[ihl:ihl + ip_payload_len],
                              total_len, truncated, capture_id,
                              declared_payload=total_len - ihl)


def _decode_ipv6(frame_no, ts_ns, data, truncated, capture_id):
    if len(data) < 40 or data[0] >> 4 != 6:
        return None
    payload_len = struct.unpack(">H", data[4:6])[0]
    nxt = data[6]
    src = _v6(data[8:24])
    dst = _v6(data[24:40])
    off = 40
    # walk simple extension headers
    while nxt in (0, 43, 60) and len(data) >= off + 8:
        hdr_len = (data[off + 1] + 1) * 8
        nxt = data[off]
        off += hdr_len
    if nxt != 6:
        return None
    tcp_bytes = data[off:40 + payload_len] if payload_len else data[off:]
    return _decode_tcp_header(frame_no, ts_ns, src, dst, tcp_bytes,
                              40 + payload_len, truncated, capture_id,
                              declared_payload=(40 + payload_len) - off)


def _v6(b: bytes) -> str:
    import ipaddress
    return str(ipaddress.IPv6Address(b))


def _decode_tcp_header(frame_no, ts_ns, src, dst, tcp, ip_total_len,
                       truncated, capture_id, declared_payload):
    if len(tcp) < 20:
        return None
    (sport, dport, seq, ack, off_flags, window, _cksum, _urg) = struct.unpack(
        ">HHIIHHHH", tcp[0:20])
    data_off = (off_flags >> 12) * 4
    flags = off_flags & 0x01FF
    if data_off < 20:
        return None
    # payload length from IP declaration (robust against snaplen truncation)
    payload_len = max(0, declared_payload - data_off)
    opts = tcp[20:data_off]
    mss = wscale = ts_val = ts_ecr = None
    sack_permitted = False
    sack_blocks: list[tuple[int, int]] = []
    i = 0
    while i < len(opts):
        kind = opts[i]
        if kind == 0:
            break
        if kind == 1:
            i += 1
            continue
        if i + 1 >= len(opts):
            break
        olen = opts[i + 1]
        if olen < 2 or i + olen > len(opts):
            break
        body = opts[i + 2:i + olen]
        if kind == 2 and len(body) == 2:
            mss = struct.unpack(">H", body)[0]
        elif kind == 3 and len(body) == 1:
            wscale = body[0]
        elif kind == 4:
            sack_permitted = True
        elif kind == 5:
            for j in range(0, len(body) - 7, 8):
                left, right = struct.unpack(">II", body[j:j + 8])
                sack_blocks.append((left, right))
        elif kind == 8 and len(body) == 8:
            ts_val, ts_ecr = struct.unpack(">II", body)
        i += olen
    return TCPPacket(
        frame_number=frame_no, timestamp_ns=ts_ns, capture_id=capture_id,
        src_ip=src, dst_ip=dst, src_port=sport, dst_port=dport,
        seq_raw=seq, ack_raw=ack, flags=flags & 0xFF, window_raw=window,
        payload_len=payload_len, ip_total_len=ip_total_len, truncated=truncated,
        mss=mss, window_scale=wscale, sack_permitted=sack_permitted,
        sack_blocks=tuple(sack_blocks), ts_val=ts_val, ts_ecr=ts_ecr,
    )
