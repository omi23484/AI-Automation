"""TCP session reconstruction and the per-packet analysis pipeline.

Sessions are identified by 5-tuple *plus* connection state: a pure SYN with
a new ISN arriving on an already-established or closed connection starts a
new Session object (5-tuple reuse), while a SYN retransmission (same ISN)
does not.  Each session owns two DirectionState objects (A->B and B->A,
A = sender of the first packet seen); the client/server roles are derived
from the handshake and exposed independently, so mid-capture sessions are
supported and clearly labelled partial.
"""

from __future__ import annotations

from .models import (ACK, FIN, RST, SYN, DupAckTrain, RetransmissionEvent,
                     SegmentRecord, TCPPacket, ST_DUPLICATE, ST_ORIGINAL,
                     ST_OUT_OF_ORDER, ST_RETRANSMITTED, flags_to_str)
from .tcp_ack import AckCorrelator
from .tcp_loss import LossManager
from .tcp_retransmission import RetransConfig, classify
from .tcp_rtt import RTTTracker
from .tcp_sack import SackScoreboard
from .tcp_sequence import IntervalSet, SegmentIndex, SeqUnwrapper
from .tcp_window import WindowTracker


class DirectionState:
    """All sequence-space state for one direction of one session."""

    def __init__(self, direction: str, capture_id: int):
        self.direction = direction
        self.unwrapper = SeqUnwrapper()
        self.isn: int | None = None          # unwrapped; SYN seq
        self.isn_raw: int | None = None
        self.rel_base: int | None = None     # base for relative display
        self.syn_seen = False
        self.syn_frames: list[int] = []
        self.fin_seen = False
        self.rst_seen = False
        self.segments: list[SegmentRecord] = []
        self.seg_index = SegmentIndex()
        self.transmitted = IntervalSet()
        self.snd_max: int | None = None
        self.rtt = RTTTracker(direction)
        self.ack_corr = AckCorrelator(direction, self.rtt)
        self.scoreboard = SackScoreboard(direction)   # for data sent this way
        self.loss = LossManager(direction, capture_id)
        self.window = WindowTracker(direction)        # window advertised this way
        self.open_gaps: list[dict] = []               # receiver-side seq gaps
        self.retrans_events: list[RetransmissionEvent] = []
        # dup-ACK tracking for ACKs *sent by* this direction
        self.dup_last_ack: int | None = None
        self.dup_train: DupAckTrain | None = None
        self.dup_ack_trains: list[DupAckTrain] = []
        # negotiated options announced by this endpoint
        self.mss: int | None = None
        self.ws: int | None = None
        self.sack_permitted: bool | None = None       # None = unknown (mid-capture)
        self.tsopt = False
        # counters
        self.packets = 0
        self.bytes = 0
        self.payload_bytes = 0
        self.retrans_segments = 0
        self.retrans_bytes = 0
        self.dup_packets = 0
        self.ooo_packets = 0
        self.oversize_segments = 0                    # > MSS: TSO/GSO suspicion
        self._window_full = False

    # ------------------------------------------------------------- helpers
    def rel(self, seq64: int | None) -> int | None:
        if seq64 is None:
            return None
        base = self.rel_base if self.rel_base is not None else 0
        return seq64 - base

    def contiguous_end(self) -> int | None:
        """End of the first contiguous transmitted block (receiver view)."""
        if not self.transmitted:
            return None
        return self.transmitted.ends[0]


class Session:
    """One reconstructed TCP connection."""

    def __init__(self, session_id: int, first_pkt: TCPPacket, cfg: RetransConfig):
        self.session_id = session_id
        self.cfg = cfg
        self.capture_id = first_pkt.capture_id
        self.capture_point = ""
        self.ep_a = (first_pkt.src_ip, first_pkt.src_port)
        self.ep_b = (first_pkt.dst_ip, first_pkt.dst_port)
        self.dir_a = DirectionState("A->B", first_pkt.capture_id)
        self.dir_b = DirectionState("B->A", first_pkt.capture_id)
        self.first_ts: int | None = None
        self.last_ts: int | None = None
        self.client_dir: str | None = None    # "A->B" means A is the client
        self.handshake_complete = False
        self.partial = True                   # until a SYN proves a fresh start
        self.syn_ts: int | None = None
        self.syn_frame: int | None = None
        self.synack_ts: int | None = None
        self.synack_frame: int | None = None
        self.est_ack_ts: int | None = None
        self.est_ack_frame: int | None = None
        self._server_isn_raw: int | None = None
        self.rst_frame: int | None = None
        self.fin_frames: list[int] = []
        self.packet_rows: list[tuple] = []
        self.warnings: list[str] = []
        self.truncated_frames = 0

    # ------------------------------------------------------------- routing
    def direction_of(self, pkt: TCPPacket) -> str:
        return "A->B" if (pkt.src_ip, pkt.src_port) == self.ep_a else "B->A"

    def dstate(self, direction: str) -> DirectionState:
        return self.dir_a if direction == "A->B" else self.dir_b

    @property
    def closed(self) -> bool:
        return (self.dir_a.rst_seen or self.dir_b.rst_seen
                or (self.dir_a.fin_seen and self.dir_b.fin_seen))

    # ================================================================ packet
    def add_packet(self, pkt: TCPPacket) -> None:
        d = self.direction_of(pkt)
        r = "B->A" if d == "A->B" else "A->B"
        snd = self.dstate(d)     # sender-side state for this packet
        rcv = self.dstate(r)     # the other direction

        if self.first_ts is None:
            self.first_ts = pkt.timestamp_ns
        self.last_ts = pkt.timestamp_ns
        if pkt.truncated:
            self.truncated_frames += 1

        snd.packets += 1
        snd.bytes += pkt.ip_total_len
        snd.payload_bytes += pkt.payload_len

        seq64 = snd.unwrapper.unwrap(pkt.seq_raw)
        if snd.rel_base is None:
            snd.rel_base = seq64
        seq_consumed = pkt.payload_len
        if pkt.flags & SYN:
            seq_consumed += 1
        if pkt.flags & FIN:
            seq_consumed += 1
        end64 = seq64 + seq_consumed

        self._handshake(pkt, d, snd, rcv, seq64)
        if pkt.flags & RST:
            snd.rst_seen = True
            if self.rst_frame is None:
                self.rst_frame = pkt.frame_number
        if pkt.flags & FIN:
            snd.fin_seen = True
            self.fin_frames.append(pkt.frame_number)

        # advertised receive window (advertised BY the sender of this packet)
        snd.window.process(pkt.frame_number, pkt.timestamp_ns, pkt.window_raw,
                           in_syn=bool(pkt.flags & SYN))

        seg = None
        if seq_consumed > 0:
            seg = self._data_segment(pkt, d, r, snd, rcv, seq64, end64)

        if pkt.flags & ACK:
            self._process_ack(pkt, d, r, snd, rcv)

        # zero-window probe: tiny segment sent into the peer's closed window
        if (seq_consumed > 0 and pkt.payload_len <= 1
                and rcv.window.zero_window_open_ts is not None
                and not (pkt.flags & (SYN | FIN | RST))):
            rcv.window.note_probe(pkt.frame_number, pkt.timestamp_ns)

        self._store_row(pkt, d, snd, seq64, end64, seg)

    # ============================================================= handshake
    def _handshake(self, pkt: TCPPacket, d: str, snd: DirectionState,
                   rcv: DirectionState, seq64: int) -> None:
        f = pkt.flags
        if f & SYN and not f & ACK:                       # SYN
            if not snd.syn_seen:
                snd.syn_seen = True
                snd.isn = seq64
                snd.isn_raw = pkt.seq_raw
                snd.rel_base = seq64
                self.client_dir = d
                self.partial = False
                self.syn_ts = pkt.timestamp_ns
                self.syn_frame = pkt.frame_number
                snd.mss, snd.ws = pkt.mss, pkt.window_scale
                snd.sack_permitted = pkt.sack_permitted
                snd.tsopt = pkt.ts_val is not None
            snd.syn_frames.append(pkt.frame_number)
        elif f & SYN and f & ACK:                         # SYN/ACK
            if not snd.syn_seen:
                snd.syn_seen = True
                snd.isn = seq64
                snd.isn_raw = pkt.seq_raw
                snd.rel_base = seq64
                self._server_isn_raw = pkt.seq_raw
                if self.client_dir is None:
                    self.client_dir = "B->A" if d == "A->B" else "A->B"
                self.synack_ts = pkt.timestamp_ns
                self.synack_frame = pkt.frame_number
                snd.mss, snd.ws = pkt.mss, pkt.window_scale
                snd.sack_permitted = pkt.sack_permitted
                snd.tsopt = pkt.ts_val is not None
                if self.syn_ts is not None:
                    rtt = pkt.timestamp_ns - self.syn_ts
                    if rtt >= 0 and self.client_dir is not None:
                        self.dstate(self.client_dir).rtt.add_sample(
                            pkt.timestamp_ns, rtt, "syn-synack",
                            self.syn_frame, pkt.frame_number, 0, 1)
            snd.syn_frames.append(pkt.frame_number)
        elif (f & ACK and not f & SYN and not self.handshake_complete
              and self.synack_ts is not None and d == self.client_dir):
            self.handshake_complete = True
            self.est_ack_ts = pkt.timestamp_ns
            self.est_ack_frame = pkt.frame_number
            rtt = pkt.timestamp_ns - self.synack_ts
            if rtt >= 0:
                sdir = "B->A" if self.client_dir == "A->B" else "A->B"
                self.dstate(sdir).rtt.add_sample(
                    pkt.timestamp_ns, rtt, "synack-ack",
                    self.synack_frame, pkt.frame_number, 0, 1)
            # window scaling becomes active only if BOTH sides offered it
            both = self.dir_a.ws is not None and self.dir_b.ws is not None
            for ds in (self.dir_a, self.dir_b):
                ds.window.scale = ds.ws if both else None
                ds.window.scale_known = True

    # ============================================================ data path
    def _data_segment(self, pkt: TCPPacket, d: str, r: str,
                      snd: DirectionState, rcv: DirectionState,
                      seq64: int, end64: int) -> SegmentRecord:
        overlaps = snd.transmitted.overlap(seq64, end64)
        full_overlap = snd.transmitted.contains_range(seq64, end64)
        seg = SegmentRecord(
            seg_id=len(snd.segments), frame_number=pkt.frame_number,
            timestamp_ns=pkt.timestamp_ns, seq=seq64, end=end64,
            payload_len=pkt.payload_len, flags=pkt.flags,
            ack_raw=pkt.ack_raw, window_raw=pkt.window_raw)
        snd.segments.append(seg)

        if snd.mss and pkt.payload_len > snd.mss:
            snd.oversize_segments += 1

        if overlaps and pkt.payload_len > 0:
            self._retransmission(pkt, d, snd, rcv, seg, overlaps, full_overlap)
        else:
            self._original_data(pkt, snd, seg, seq64, end64)

        snd.transmitted.add(seq64, end64)
        snd.seg_index.add(seq64, end64, seg.seg_id)
        snd.snd_max = end64 if snd.snd_max is None else max(snd.snd_max, end64)
        snd.ack_corr.register_segment(seg)

        # possible window-full: bytes in flight reached the peer's advertised
        # receive window (peer advertises via rcv-direction packets)
        una = snd.ack_corr.snd_una
        adv = rcv.window.last_window
        if una is not None and adv:
            in_flight = snd.snd_max - una
            if in_flight >= adv and not snd._window_full:
                snd._window_full = True
                rcv.window.note_window_full(pkt.frame_number, pkt.timestamp_ns,
                                            in_flight, adv)
            elif in_flight < adv:
                snd._window_full = False
        return seg

    def _original_data(self, pkt: TCPPacket, snd: DirectionState,
                       seg: SegmentRecord, seq64: int, end64: int) -> None:
        contig = snd.contiguous_end()
        if contig is not None and seq64 > contig:
            # sequence gap at the capture point: reordering OR loss OR capture
            # drop — do not classify yet (section 13)
            snd.open_gaps.append({
                "start": contig, "end": seq64,
                "ts": pkt.timestamp_ns, "frame": pkt.frame_number})
        # does this segment fill an earlier gap with never-before-seen data?
        for gap in snd.open_gaps:
            if gap.get("resolved"):
                continue
            if seq64 <= gap["start"] < end64 or (seq64 < gap["end"] and end64 > gap["start"]):
                gap["resolved"] = True
                gap["fill_frame"] = pkt.frame_number
                gap["fill_ts"] = pkt.timestamp_ns
                gap["fill_kind"] = "new-data"
                seg.state = ST_OUT_OF_ORDER
                snd.ooo_packets += 1
                delay = pkt.timestamp_ns - gap["ts"]
                ev = snd.loss.open_event(
                    seq=max(gap["start"], seq64), end=min(gap["end"], end64),
                    evidence_kind="seq-gap",
                    evidence_ts=gap["ts"], evidence_frame=gap["frame"],
                    original_tx_ns=None, original_frame=None,
                    classification="reordering",
                    classification_evidence=(
                        f"gap filled after {delay} ns by frame "
                        f"{pkt.frame_number} carrying data never seen before "
                        "in the capture — consistent with out-of-order "
                        "delivery, not retransmitted loss"))
                ev.recovered = True
                ev.recovery_ns = pkt.timestamp_ns
                ev.recovery_frame = pkt.frame_number
                snd.loss._open_by_start.pop(ev.seq, None)

    def _retransmission(self, pkt: TCPPacket, d: str, snd: DirectionState,
                        rcv: DirectionState, seg: SegmentRecord,
                        overlaps, full_overlap: bool) -> None:
        cands = snd.seg_index.overlapping(seg.seq, seg.end)
        orig = None
        for s, e, sid in cands:
            cand = snd.segments[sid]
            if cand is seg or cand.payload_len == 0:
                continue
            if orig is None or cand.timestamp_ns < orig.timestamp_ns:
                orig = cand
        last_tx_ts = None
        for s, e, sid in cands:
            cand = snd.segments[sid]
            if cand is seg:
                continue
            if last_tx_ts is None or cand.timestamp_ns > last_tx_ts:
                last_tx_ts = cand.timestamp_ns

        una = snd.ack_corr.snd_una
        already_acked = una is not None and seg.end <= una
        already_sacked = snd.scoreboard.sacked.contains_range(seg.seq, seg.end)
        dup_acks = rcv.dup_train.count if rcv.dup_train else 0
        hole = any(h["start"] < seg.end and seg.seq < h["end"]
                   for h in snd.scoreboard.open_holes())
        partial_overlap = bool(overlaps) and not full_overlap

        kind, evidence = classify(
            delay_since_last_tx_ns=(pkt.timestamp_ns - last_tx_ts
                                    if last_tx_ts is not None else None),
            dup_acks=dup_acks, sack_hole_over_range=hole,
            already_acked=already_acked, already_sacked=already_sacked,
            full_overlap=full_overlap, partial_overlap=partial_overlap,
            srtt_ns=snd.ack_corr.srtt_ns, cfg=self.cfg)

        seg.is_retransmission = True
        seg.retrans_kind = kind
        seg.state = ST_DUPLICATE if kind == "duplicate" else ST_RETRANSMITTED
        if orig is not None:
            seg.retrans_of_frame = orig.frame_number
            seg.retrans_delay_ns = pkt.timestamp_ns - orig.timestamp_ns
        snd.ack_corr.note_retransmission(seg.seq, seg.end)

        if kind == "duplicate":
            snd.dup_packets += 1
        else:
            snd.retrans_segments += 1
            snd.retrans_bytes += seg.payload_len

        snd.retrans_events.append(RetransmissionEvent(
            frame_number=pkt.frame_number, timestamp_ns=pkt.timestamp_ns,
            capture_id=pkt.capture_id, direction=d, seq=seg.seq, end=seg.end,
            bytes=seg.payload_len, classification=kind,
            original_frame=orig.frame_number if orig else None,
            original_ts_ns=orig.timestamp_ns if orig else None,
            delay_ns=seg.retrans_delay_ns, dup_acks_before=dup_acks,
            sack_active=hole or already_sacked, evidence=evidence))

        # a gap filled by a RE-transmitted segment is genuine loss evidence
        for gap in snd.open_gaps:
            if not gap.get("resolved") and seg.seq < gap["end"] and gap["start"] < seg.end:
                gap["resolved"] = True
                gap["fill_kind"] = "retransmission"

        if kind in ("duplicate", "possible-spurious"):
            return
        mech = ("fast-retransmit" if kind == "fast-retransmission"
                else "rto" if kind == "rto-retransmission" else "unknown")
        ev = snd.loss.note_retransmission(seg.seq, seg.end, pkt.frame_number,
                                          pkt.timestamp_ns, mech)
        if ev is None:
            # no SACK/dup-ACK evidence preceded this retransmission — open the
            # loss episode from the retransmission itself
            first_ev_ts, first_ev_frame = pkt.timestamp_ns, pkt.frame_number
            if rcv.dup_train and rcv.dup_train.count >= 1:
                first_ev_ts = rcv.dup_train.first_ts_ns
                first_ev_frame = rcv.dup_train.first_frame
            ev = snd.loss.open_event(
                seq=seg.seq, end=seg.end, evidence_kind="retransmission",
                evidence_ts=first_ev_ts, evidence_frame=first_ev_frame,
                original_tx_ns=orig.timestamp_ns if orig else None,
                original_frame=orig.frame_number if orig else None)
            snd.loss.note_retransmission(seg.seq, seg.end, pkt.frame_number,
                                         pkt.timestamp_ns, mech)
        if ev is not None:
            ev.dup_ack_count = max(ev.dup_ack_count, dup_acks)
            if rcv.dup_train and rcv.dup_train.retrans_frame is None:
                rcv.dup_train.retrans_frame = pkt.frame_number
                rcv.dup_train.time_to_retrans_ns = (
                    pkt.timestamp_ns - rcv.dup_train.first_ts_ns)

    # =============================================================== ACK path
    def _process_ack(self, pkt: TCPPacket, d: str, r: str,
                     snd: DirectionState, rcv: DirectionState) -> None:
        """This packet (direction d) ACKs data flowing in direction r."""
        ack64 = rcv.unwrapper.unwrap_no_advance(pkt.ack_raw)

        # duplicate-ACK train tracking (sender of the ACK = snd)
        is_pure_ack = (pkt.payload_len == 0
                       and not pkt.flags & (SYN | FIN | RST))
        if is_pure_ack:
            if snd.dup_last_ack is not None and ack64 == snd.dup_last_ack:
                if snd.dup_train is None:
                    snd.dup_train = DupAckTrain(
                        direction=d, ack=ack64, first_frame=pkt.frame_number,
                        first_ts_ns=pkt.timestamp_ns, count=1,
                        last_ts_ns=pkt.timestamp_ns)
                    snd.dup_ack_trains.append(snd.dup_train)
                else:
                    snd.dup_train.count += 1
                    snd.dup_train.gaps_ns.append(
                        pkt.timestamp_ns - snd.dup_train.last_ts_ns)
                    snd.dup_train.last_ts_ns = pkt.timestamp_ns
                if pkt.sack_blocks:
                    snd.dup_train.sack_blocks += len(pkt.sack_blocks)
                if snd.dup_train.count >= self.cfg.dupack_threshold:
                    miss_end = rcv.snd_max if rcv.snd_max is not None else ack64
                    for h in rcv.scoreboard.open_holes():
                        if h["start"] >= ack64:
                            miss_end = min(miss_end, h["end"])
                            break
                    snd.dup_train.missing_seq = ack64
                    snd.dup_train.missing_end = miss_end
                    if miss_end > ack64:
                        rcv.loss.open_event(
                            seq=ack64, end=miss_end, evidence_kind="dup-ack",
                            evidence_ts=snd.dup_train.first_ts_ns,
                            evidence_frame=snd.dup_train.first_frame,
                            original_tx_ns=self._first_tx_ts(rcv, ack64, miss_end),
                            original_frame=self._first_tx_frame(rcv, ack64, miss_end))
                        rcv.loss.note_dup_acks(ack64, miss_end, snd.dup_train.count)
            else:
                snd.dup_train = None
            snd.dup_last_ack = ack64
        elif pkt.payload_len > 0:
            snd.dup_train = None

        # cumulative-ACK sweep of the peer's ledger
        newly = rcv.ack_corr.process_ack(ack64, pkt.frame_number,
                                         pkt.timestamp_ns, rcv.segments)
        recovered = rcv.loss.note_cum_ack(ack64, pkt.frame_number,
                                          pkt.timestamp_ns)
        for ev in recovered:
            for train in snd.dup_ack_trains:
                if train.missing_seq is not None and train.missing_seq >= ev.seq \
                        and train.missing_seq < ev.end \
                        and train.time_to_recovery_ns is None:
                    train.time_to_recovery_ns = (pkt.timestamp_ns
                                                 - train.first_ts_ns)

        # SACK scoreboard for the peer's data
        blocks64 = []
        for left, right in pkt.sack_blocks:
            l64 = rcv.unwrapper.unwrap_no_advance(left)
            r64 = rcv.unwrapper.unwrap_no_advance(right)
            if r64 > l64:
                blocks64.append((l64, r64))
        prev_holes = {h["start"] for h in rcv.scoreboard.open_holes()}
        rec = rcv.scoreboard.process_ack(pkt.frame_number, pkt.timestamp_ns,
                                         pkt.capture_id, ack64, blocks64)
        if rec is not None:
            if rec.is_dsack:
                # DSACK: the receiver already had this data — mark overlapping
                # retransmissions as possibly spurious (section 10)
                l64, r64 = rec.blocks[0]
                for rt in rcv.retrans_events:
                    if rt.seq < r64 and l64 < rt.end \
                            and rt.classification not in ("possible-spurious",
                                                          "duplicate"):
                        rt.classification = "possible-spurious"
                        rt.evidence += ("; DSACK reported the range as already "
                                        f"received (frame {pkt.frame_number}: "
                                        f"{rec.dsack_reason})")
                rcv.loss.reclassify(l64, r64, "duplicate",
                                    f"DSACK in frame {pkt.frame_number}: "
                                    f"{rec.dsack_reason}")
            # mark ledger segments now covered by SACK
            for l64, r64 in rec.blocks if not rec.is_dsack else rec.blocks[1:]:
                for s, e, sid in rcv.seg_index.overlapping(l64, r64):
                    segr = rcv.segments[sid]
                    if segr.sacked_ts_ns is None and l64 <= segr.seq \
                            and segr.end <= r64:
                        segr.sacked_ts_ns = pkt.timestamp_ns
                        segr.sacked_by_frame = pkt.frame_number
                        if segr.state == ST_ORIGINAL:
                            segr.state = "SACKed"
        # new SACK holes -> loss evidence for the peer's data
        for h in rcv.scoreboard.open_holes():
            rcv.loss.note_sack_report(h["start"], h["end"])
            if h["start"] not in prev_holes:
                if prev_holes:
                    rcv.loss.note_additional_hole(pkt.timestamp_ns)
                rcv.loss.open_event(
                    seq=h["start"], end=h["end"], evidence_kind="sack-hole",
                    evidence_ts=h["first_ts"], evidence_frame=h["first_frame"],
                    original_tx_ns=self._first_tx_ts(rcv, h["start"], h["end"]),
                    original_frame=self._first_tx_frame(rcv, h["start"], h["end"]),
                    sack_involved=True)

    # ------------------------------------------------------------- utilities
    @staticmethod
    def _first_tx(rcv: DirectionState, start: int, end: int):
        best = None
        for s, e, sid in rcv.seg_index.overlapping(start, end):
            seg = rcv.segments[sid]
            if best is None or seg.timestamp_ns < best.timestamp_ns:
                best = seg
        return best

    def _first_tx_ts(self, rcv, start, end):
        seg = self._first_tx(rcv, start, end)
        return seg.timestamp_ns if seg else None

    def _first_tx_frame(self, rcv, start, end):
        seg = self._first_tx(rcv, start, end)
        return seg.frame_number if seg else None

    def _store_row(self, pkt: TCPPacket, d: str, snd: DirectionState,
                   seq64: int, end64: int, seg: SegmentRecord | None) -> None:
        self.packet_rows.append((
            pkt.frame_number, pkt.timestamp_ns, d,
            snd.rel(seq64), snd.rel(end64), pkt.payload_len,
            flags_to_str(pkt.flags), pkt.ack_raw, pkt.window_raw,
            len(pkt.sack_blocks),
            seg.state if seg else "",
        ))


class SessionManager:
    """Demultiplexes TCP packets into Session objects (5-tuple + state)."""

    def __init__(self, cfg: RetransConfig | None = None):
        self.cfg = cfg or RetransConfig()
        self.sessions: list[Session] = []
        self._active: dict[tuple, Session] = {}

    @staticmethod
    def _key(pkt: TCPPacket) -> tuple:
        a = (pkt.src_ip, pkt.src_port)
        b = (pkt.dst_ip, pkt.dst_port)
        return (a, b) if a <= b else (b, a)

    def feed(self, pkt: TCPPacket) -> Session:
        key = self._key(pkt)
        sess = self._active.get(key)
        if sess is not None and self._is_new_connection(sess, pkt):
            sess = None
        if sess is None:
            sess = Session(len(self.sessions), pkt, self.cfg)
            self.sessions.append(sess)
            self._active[key] = sess
        sess.add_packet(pkt)
        return sess

    @staticmethod
    def _is_new_connection(sess: Session, pkt: TCPPacket) -> bool:
        """5-tuple reuse detection: a pure SYN with a NEW ISN on a session
        that already completed a handshake or closed starts a new session; a
        SYN retransmission (same ISN) does not."""
        if not (pkt.flags & SYN) or (pkt.flags & ACK):
            return False
        d = sess.direction_of(pkt)
        ds = sess.dstate(d)
        if ds.syn_seen and ds.isn_raw == pkt.seq_raw:
            return False                      # SYN retransmission
        if sess.closed:
            return True
        if sess.handshake_complete:
            return True
        if ds.syn_seen and ds.isn_raw != pkt.seq_raw:
            return True                       # different ISN before establishment
        return False
