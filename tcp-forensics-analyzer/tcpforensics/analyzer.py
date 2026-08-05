"""Analysis pipeline: capture -> sessions -> statistics -> report model.

Streams packets straight from the reader into the session engine (packets
are analyzed as they are read and only compact per-session state is kept),
prints stage progress, and finally produces a plain-dict model that the
report generator serializes into the HTML.
"""

from __future__ import annotations

import heapq
import sys
from pathlib import Path

from . import __version__
from .artifacts import session_artifacts
from .capture_reader import CaptureReader, decode_tcp
from .models import flags_to_str
from .statistics import histogram, summarize
from .tcp_retransmission import RetransConfig
from .tcp_session import DirectionState, Session, SessionManager
from .timestamp_engine import format_duration_ns, format_ns_utc
from .verdicts import VerdictConfig, evaluate

PROGRESS_EVERY = 50_000


def _progress(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg, file=sys.stderr, flush=True)


def _merged_tcp_packets(readers: list[CaptureReader]):
    """K-way merge of several captures' frame streams by timestamp.

    Frames get a single global numbering in merge order (ties broken by
    file order), and every TCPPacket carries the capture_id of its source
    file — a file boundary IS an observation point, so the multi-point
    dedup treats "same packet in capture A and capture B" exactly like
    "same packet on two leafs".  Per-file frame streams are assumed
    time-ordered (as written by capture tools); k-way merging makes the
    combined stream globally ordered.
    """
    heap: list = []
    gens = []
    for i, rd in enumerate(readers):
        g = rd.frames()
        gens.append(g)
        try:
            f = next(g)
            heap.append((f[1], i, f))
        except StopIteration:
            pass
    heapq.heapify(heap)
    frame_no = 0
    while heap:
        _ts, i, f = heapq.heappop(heap)
        frame_no += 1
        pkt = decode_tcp(frame_no, f[1], f[2], f[3], f[4], i)
        if pkt is not None:
            readers[i].time_info.tcp_packet_count += 1
            yield pkt
        try:
            nf = next(gens[i])
            heapq.heappush(heap, (nf[1], i, nf))
        except StopIteration:
            pass


def analyze_capture(path, *, capture_id: int = 0, capture_point: str = "",
                    retrans_cfg: RetransConfig | None = None,
                    verdict_cfg: VerdictConfig | None = None,
                    max_packet_rows: int = 20_000,
                    max_segment_rows: int = 20_000,
                    max_rtt_rows: int = 20_000,
                    max_sack_rows: int = 10_000,
                    quiet: bool = False) -> dict:
    """Analyze one capture (str path) or several merged (list of paths)."""
    paths = [path] if isinstance(path, (str, Path)) else [str(p) for p in path]
    retrans_cfg = retrans_cfg or RetransConfig()
    verdict_cfg = verdict_cfg or VerdictConfig()

    readers = [CaptureReader(p, capture_id=(capture_id if len(paths) == 1
                                            else i),
                             capture_point=capture_point)
               for i, p in enumerate(paths)]
    mgr = SessionManager(retrans_cfg, row_limit=max_packet_rows)

    _progress("[1/4] Reading packets & reconstructing sessions ...", quiet)
    n = 0
    for pkt in _merged_tcp_packets(readers):
        mgr.feed(pkt)
        n += 1
        if n % PROGRESS_EVERY == 0:
            _progress(f"      {n:,} TCP packets, "
                      f"{len(mgr.sessions):,} sessions ...", quiet)
    total_pkts = sum(rd.time_info.packet_count for rd in readers)
    _progress(f"      done: {total_pkts:,} packets, "
              f"{n:,} TCP, {len(mgr.sessions):,} sessions", quiet)

    _progress("[2/4] Finalizing sequence space, SACK scoreboards, "
              "RTT, loss/retransmission ...", quiet)
    sessions_json = []
    global_rtt: list[int] = []
    global_recovery: list[int] = []
    totals = {
        "sessions": len(mgr.sessions), "tcp_packets": n,
        "payload_bytes": 0, "retrans_segments": 0, "data_segments": 0,
        "sack_events": 0, "dsack_events": 0, "loss_events": 0,
        "recovered_losses": 0, "dup_acks": 0, "ooo_packets": 0,
        "dup_packets": 0, "zero_window_events": 0, "resets": 0,
        "network_dups": 0,
    }
    for sess in mgr.sessions:
        sj = _session_to_json(sess, verdict_cfg)
        sessions_json.append(sj)
        st = sj["stats"]
        totals["payload_bytes"] += st["payload_bytes"]
        totals["retrans_segments"] += st["retrans_segments"]
        totals["data_segments"] += st["data_segments"]
        totals["sack_events"] += st["sack_events"]
        totals["dsack_events"] += st["dsack_events"]
        totals["loss_events"] += st["loss_events"]
        totals["recovered_losses"] += st["recovered_losses"]
        totals["dup_acks"] += st["dup_acks"]
        totals["ooo_packets"] += st["ooo_packets"]
        totals["dup_packets"] += st["dup_packets"]
        totals["zero_window_events"] += st["zero_window_events"]
        totals["network_dups"] += st["network_dups"]
        totals["resets"] += 1 if st["rst"] else 0
        global_rtt.extend(s["rtt"] for s in sj["rtt_samples"])
        global_recovery.extend(
            e["total_ns"] for e in sj["loss_events"]
            if e["total_ns"] is not None and e["classification"] == "loss")

    _progress("[3/4] Computing capture-level statistics ...", quiet)
    totals["retrans_pct"] = (100.0 * totals["retrans_segments"]
                             / totals["data_segments"]
                             if totals["data_segments"] else 0.0)
    multi = len(readers) > 1
    names = [Path(p).name for p in paths]
    all_res = [r for rd in readers for r in rd.time_info.resolutions]
    res = min(all_res, key=lambda r: r.ticks_per_second) if all_res else None
    firsts = [rd.time_info.first_ts_ns for rd in readers
              if rd.time_info.first_ts_ns is not None]
    lasts = [rd.time_info.last_ts_ns for rd in readers
             if rd.time_info.last_ts_ns is not None]
    first_ts = min(firsts) if firsts else None
    last_ts = max(lasts) if lasts else None
    formats = []
    for rd in readers:
        if rd.time_info.file_format not in formats:
            formats.append(rd.time_info.file_format)
    snaplens = [rd.snaplen for rd in readers if rd.snaplen is not None]
    warnings = ([w for rd in readers for w in rd.warnings] if not multi else
                [f"{Path(rd.path).name}: {w}"
                 for rd in readers for w in rd.warnings])
    if multi:
        warnings.insert(0, f"merged timeline of {len(readers)} capture "
                           "files — frames interleaved by timestamp; a file "
                           "boundary is treated as an observation point for "
                           "multi-point duplicate recognition")
    capture = {
        "path": paths[0] if not multi else " + ".join(names),
        "capture_id": capture_id,
        "capture_point": capture_point or
                         (paths[0] if not multi else " + ".join(names)),
        "format": "+".join(formats),
        "resolution_label": res.label if res else "unknown",
        "effective_precision_ns": res.ns_per_tick if res else 1_000_000_000,
        "nanosecond_native": bool(res and res.ticks_per_second >= 1_000_000_000),
        "first_ts": first_ts,
        "first_ts_str": format_ns_utc(first_ts),
        "last_ts": last_ts,
        "last_ts_str": format_ns_utc(last_ts),
        "duration_ns": (last_ts - first_ts
                        if first_ts is not None and last_ts is not None else 0),
        "duration_str": format_duration_ns(
            last_ts - first_ts
            if first_ts is not None and last_ts is not None else 0),
        "packets": sum(rd.time_info.packet_count for rd in readers),
        "tcp_packets": sum(rd.time_info.tcp_packet_count for rd in readers),
        "snaplen": min(snaplens) if snaplens else None,
        "truncated_frames": sum(rd.truncated_frames for rd in readers),
        "warnings": warnings,
        "files": [{"name": nm,
                   "packets": rd.time_info.packet_count,
                   "tcp_packets": rd.time_info.tcp_packet_count,
                   "format": rd.time_info.file_format}
                  for nm, rd in zip(names, readers)],
    }
    model = {
        "tool": {"name": "tcpforensics", "version": __version__},
        "capture": capture,
        "totals": totals,
        "rtt_summary": summarize(global_rtt),
        "rtt_hist": histogram(global_rtt),
        "recovery_summary": summarize(global_recovery),
        "recovery_hist": histogram(global_recovery),
        "verdict_config": (verdict_cfg or VerdictConfig()).to_dict(),
        "sessions": sessions_json,
    }
    # Bound what is EMBEDDED per session for very large captures.  All
    # statistics/verdicts/histograms above were computed from the full data
    # engine-side; only the row listings are capped, with counts surfaced.
    for sj, sess in zip(sessions_json, mgr.sessions):
        sj["packets_truncated"] = sess.rows_dropped
        if len(sj["packets"]) > max_packet_rows:
            sj["packets_truncated"] += len(sj["packets"]) - max_packet_rows
            sj["packets"] = sj["packets"][:max_packet_rows]
        for key, cap, cnt in (("segments", max_segment_rows, "segments_truncated"),
                              ("rtt_samples", max_rtt_rows, "rtt_truncated"),
                              ("sack_records", max_sack_rows, "sack_truncated")):
            if len(sj[key]) > cap:
                sj[cnt] = len(sj[key]) - cap
                sj[key] = sj[key][:cap]
            else:
                sj[cnt] = 0
        sj["sack_snap_truncated"] = 0
        for dname, snaps in sj["sack_snapshots"].items():
            if len(snaps) > max_sack_rows:
                sj["sack_snap_truncated"] += len(snaps) - max_sack_rows
                sj["sack_snapshots"][dname] = snaps[:max_sack_rows]
    _rebase_timestamps(model)
    _progress("[4/4] Analysis model ready.", quiet)
    return model


# Keys holding absolute epoch-ns timestamps in the model.  Epoch nanoseconds
# (~1.7e18) exceed JavaScript's 2^53 safe-integer range, so the embedded
# model carries capture-start-relative nanoseconds (exact in a double for
# captures up to ~104 days); absolute UTC strings are precomputed in Python.
_TS_KEYS = frozenset({
    "ts", "first_ts", "last_ts", "start_ts", "end_ts", "syn_ts", "synack_ts",
    "ack_ts", "acked_ts", "sacked_ts", "original_tx", "evidence_ts",
    "retrans_ts", "recovery_ts", "orig_ts",
})


def _rebase_timestamps(model: dict) -> None:
    base = model["capture"]["first_ts"] or 0

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in _TS_KEYS and isinstance(v, int):
                    obj[k] = v - base
                else:
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    for sj in model["sessions"]:
        sj["packets"] = [[r[0], r[1] - base, *r[2:]] for r in sj["packets"]]
    walk(model)


# =========================================================== serialization

def _dir_stats(ds: DirectionState) -> dict:
    data_segs = sum(1 for s in ds.segments if s.payload_len > 0
                    and not s.is_retransmission
                    and s.state not in ("Keep-alive", "Window-probe"))
    acked = 0
    if ds.ack_corr.snd_una is not None and ds.rel_base is not None:
        acked = max(0, ds.ack_corr.snd_una - ds.rel_base)
    outstanding = 0
    if ds.snd_max is not None and ds.ack_corr.snd_una is not None:
        outstanding = max(0, ds.snd_max - ds.ack_corr.snd_una)
    return {
        "packets": ds.packets, "bytes": ds.bytes,
        "payload_bytes": ds.payload_bytes,
        "unique_bytes": ds.transmitted.total_bytes(),
        "acked_bytes": acked, "outstanding_bytes": outstanding,
        "data_segments": data_segs,
        "retrans_segments": ds.retrans_segments,
        "retrans_bytes": ds.retrans_bytes,
        "dup_packets": ds.dup_packets, "ooo_packets": ds.ooo_packets,
        "keepalives": ds.keepalive_count,
        "network_dups": ds.network_dups,
        "sack_events": len(ds.scoreboard.records),
        "sack_blocks": ds.scoreboard.sack_block_total,
        "sack_holes": len(ds.scoreboard.hole_history),
        "dsack_events": ds.scoreboard.dsack_count,
        "zero_window_events": ds.window.zero_window_count,
        "seq_base_raw": (ds.rel_base & 0xFFFFFFFF
                         if ds.rel_base is not None else 0),
        "window_min": ds.window.min_window, "window_max": ds.window.max_window,
        "window_scale": ds.ws,
        "mss": ds.mss,
        "sack_permitted": ds.sack_permitted,
        "tcp_timestamps": ds.tsopt,
    }


def _segments_json(sess: Session, ds: DirectionState, direction: str) -> list:
    rows = []
    for s in ds.segments:
        rows.append({
            "frame": s.frame_number, "ts": s.timestamp_ns, "dir": direction,
            "seq": ds.rel(s.seq), "end": ds.rel(s.end),
            "seq_raw": s.seq, "len": s.payload_len,
            "flags": flags_to_str(s.flags), "state": s.state,
            "retx": s.is_retransmission, "retx_kind": s.retrans_kind,
            "retx_of": s.retrans_of_frame, "retx_delay": s.retrans_delay_ns,
            "acked_ts": s.acked_ts_ns, "ack_frame": s.acked_by_frame,
            "ack_lat": s.ack_latency_ns,
            "rtt": s.rtt_ns, "rtt_ambiguous": s.rtt_ambiguous,
            "sacked_ts": s.sacked_ts_ns, "sack_frame": s.sacked_by_frame,
        })
    return rows


def _session_to_json(sess: Session, verdict_cfg: VerdictConfig) -> dict:
    a, b = sess.dir_a, sess.dir_b
    da, db = _dir_stats(a), _dir_stats(b)

    if sess.client_dir in (None, "A->B"):
        client_ep, server_ep = sess.ep_a, sess.ep_b
        cd, sd = da, db
        client_dir = "A->B"
    else:
        client_ep, server_ep = sess.ep_b, sess.ep_a
        cd, sd = db, da
        client_dir = "B->A"

    rtt_samples = []
    for ds in (a, b):
        for s in ds.rtt.samples:
            rtt_samples.append({"ts": s.timestamp_ns, "rtt": s.rtt_ns,
                                "kind": s.kind, "dir": s.direction,
                                "frame_data": s.frame_data,
                                "frame_ack": s.frame_ack,
                                "seq": ds.rel(s.seq), "end": ds.rel(s.end)})
    rtt_ambiguous = [dict(x, dir=ds.direction)
                     for ds in (a, b) for x in ds.rtt.ambiguous]
    ack_lat = [s.ack_latency_ns for ds in (a, b) for s in ds.segments
               if s.ack_latency_ns is not None and s.ack_latency_ns >= 0
               and s.payload_len > 0]
    rtt_vals = [s["rtt"] for s in rtt_samples]

    loss_events = []
    recovery_vals = []
    sack_recovered = 0
    for ds in (a, b):
        for ev in ds.loss.events:
            loss_events.append({
                "loss_id": f"S{sess.session_id}-L{ev.loss_id}-{ds.direction}",
                "dir": ev.direction,
                "seq": ds.rel(ev.seq), "end": ds.rel(ev.end),
                "bytes": ev.bytes,
                "original_tx": ev.original_tx_ns,
                "original_frame": ev.original_frame,
                "evidence_ts": ev.first_evidence_ns,
                "evidence_frame": ev.first_evidence_frame,
                "evidence_kind": ev.evidence_kind,
                "retrans_ts": ev.retrans_ns, "retrans_frame": ev.retrans_frame,
                "retrans_lost": ev.retrans_lost,
                "recovery_ts": ev.recovery_ns,
                "recovery_frame": ev.recovery_frame,
                "recovered": ev.recovered, "partial": ev.partial,
                "detection_ns": ev.detection_ns,
                "reaction_ns": ev.reaction_ns,
                "post_retrans_ns": ev.post_retrans_recovery_ns,
                "total_ns": ev.total_recovery_ns,
                "sack": ev.sack_involved, "dup_acks": ev.dup_ack_count,
                "sack_reports": ev.sack_report_count,
                "additional_holes": ev.additional_holes,
                "mechanism": ev.likely_mechanism,
                "classification": ev.classification,
                "classification_evidence": ev.classification_evidence,
            })
            if ev.classification == "loss" and ev.recovered:
                if ev.sack_involved:
                    sack_recovered += 1
                if ev.total_recovery_ns is not None:
                    recovery_vals.append(ev.total_recovery_ns)

    retrans_events = []
    spurious = 0
    for ds in (a, b):
        for rt in ds.retrans_events:
            if rt.classification == "possible-spurious":
                spurious += 1
            retrans_events.append({
                "frame": rt.frame_number, "ts": rt.timestamp_ns,
                "dir": rt.direction,
                "seq": ds.rel(rt.seq), "end": ds.rel(rt.end),
                "bytes": rt.bytes, "class": rt.classification,
                "orig_frame": rt.original_frame, "orig_ts": rt.original_ts_ns,
                "delay": rt.delay_ns, "dup_acks": rt.dup_acks_before,
                "sack": rt.sack_active, "evidence": rt.evidence})

    dup_trains = []
    total_dup_acks = 0
    for ds, dname in ((a, "A->B"), (b, "B->A")):
        peer = b if ds is a else a
        for t in ds.dup_ack_trains:
            dups = t.count  # count counts duplicates beyond the original ACK
            total_dup_acks += dups
            dup_trains.append({
                "dir": dname, "ack": peer.rel(t.ack), "first_frame": t.first_frame,
                "first_ts": t.first_ts_ns, "count": dups,
                "gaps_ns": t.gaps_ns, "sack_blocks": t.sack_blocks,
                "missing_seq": peer.rel(t.missing_seq),
                "missing_end": peer.rel(t.missing_end),
                "retrans_frame": t.retrans_frame,
                "time_to_retrans": t.time_to_retrans_ns,
                "time_to_recovery": t.time_to_recovery_ns})

    observation_events = []
    for ds, dname in ((a, "A->B"), (b, "B->A")):
        for ev in ds.observation_events:
            observation_events.append(dict(ev, dir=dname))
    obs_deltas = [e["delta_ns"] for e in observation_events]

    window_events = []
    for ds in (a, b):
        for w in ds.window.events:
            window_events.append({"kind": w.kind, "dir": w.direction,
                                  "frame": w.frame_number, "ts": w.timestamp_ns,
                                  "window": w.window_bytes, "detail": w.detail})

    sack_records = []
    for ds in (a, b):
        for rec in ds.scoreboard.records:
            sack_records.append({
                "frame": rec.frame_number, "ts": rec.timestamp_ns,
                "data_dir": ds.direction, "ack": ds.rel(rec.ack),
                "blocks": [[ds.rel(l), ds.rel(r)] for l, r in rec.blocks],
                "dsack": rec.is_dsack, "dsack_reason": rec.dsack_reason})
    sack_snapshots = {}
    for ds, dname in ((a, "A->B"), (b, "B->A")):
        sack_snapshots[dname] = [{
            "frame": s["frame"], "ts": s["ts"], "ack": ds.rel(s["ack"]),
            "sacked": [[ds.rel(x), ds.rel(y)] for x, y in s["sacked"]],
            "holes": [[ds.rel(x), ds.rel(y)] for x, y in s["holes"]],
            "dsack": s["dsack"], "ack_advanced": s["ack_advanced"],
        } for s in ds.scoreboard.snapshots]

    hs = {
        "complete": sess.handshake_complete,
        "syn_frame": sess.syn_frame, "syn_ts": sess.syn_ts,
        "synack_frame": sess.synack_frame, "synack_ts": sess.synack_ts,
        "ack_frame": sess.est_ack_frame, "ack_ts": sess.est_ack_ts,
        "syn_synack_ns": (sess.synack_ts - sess.syn_ts
                          if sess.syn_ts is not None
                          and sess.synack_ts is not None else None),
        "synack_ack_ns": (sess.est_ack_ts - sess.synack_ts
                          if sess.synack_ts is not None
                          and sess.est_ack_ts is not None else None),
        "total_ns": (sess.est_ack_ts - sess.syn_ts
                     if sess.syn_ts is not None
                     and sess.est_ack_ts is not None else None),
    }

    sack_active = None
    if a.sack_permitted is not None and b.sack_permitted is not None:
        sack_active = bool(a.sack_permitted and b.sack_permitted)
    elif len(sess.dir_a.scoreboard.records) or len(sess.dir_b.scoreboard.records):
        sack_active = True   # observed in use mid-capture

    loss_count = sum(1 for e in loss_events if e["classification"] == "loss")
    recovered_count = sum(1 for e in loss_events
                          if e["classification"] == "loss" and e["recovered"])
    data_segments = da["data_segments"] + db["data_segments"]
    retrans_segments = da["retrans_segments"] + db["retrans_segments"]
    denom = data_segments + retrans_segments
    stats = {
        "payload_bytes": da["payload_bytes"] + db["payload_bytes"],
        "data_segments": denom,
        "retrans_segments": retrans_segments,
        "retrans_bytes": da["retrans_bytes"] + db["retrans_bytes"],
        "retrans_pct": (100.0 * retrans_segments / denom) if denom else 0.0,
        "dup_acks": total_dup_acks,
        "ooo_packets": da["ooo_packets"] + db["ooo_packets"],
        "dup_packets": da["dup_packets"] + db["dup_packets"],
        "sack_events": da["sack_events"] + db["sack_events"],
        "sack_blocks": da["sack_blocks"] + db["sack_blocks"],
        "sack_holes": da["sack_holes"] + db["sack_holes"],
        "dsack_events": da["dsack_events"] + db["dsack_events"],
        "loss_events": loss_count,
        "recovered_losses": recovered_count,
        "unrecovered_losses": loss_count - recovered_count,
        "sack_recovered_losses": sack_recovered,
        "spurious_retrans": spurious,
        "zero_window_events": (da["zero_window_events"]
                               + db["zero_window_events"]),
        "network_dups": da["network_dups"] + db["network_dups"],
        "observation_skew": summarize(obs_deltas),
        "rst": a.rst_seen or b.rst_seen,
        "rst_frame": sess.rst_frame,
        "fin": a.fin_seen or b.fin_seen,
        "partial": sess.partial,
        "rtt": summarize(rtt_vals),
        "ack_latency": summarize(ack_lat),
        "recovery": summarize(recovery_vals),
    }
    verdicts = evaluate(stats, verdict_cfg)
    warnings = session_artifacts(sess)

    return {
        "id": sess.session_id,
        "label": f"Session #{sess.session_id:05d}",
        "client": f"{client_ep[0]}:{client_ep[1]}",
        "server": f"{server_ep[0]}:{server_ep[1]}",
        "client_ip": client_ep[0], "server_ip": server_ep[0],
        "client_port": client_ep[1], "server_port": server_ep[1],
        "client_dir": client_dir,
        "ep_a": f"{sess.ep_a[0]}:{sess.ep_a[1]}",
        "ep_b": f"{sess.ep_b[0]}:{sess.ep_b[1]}",
        "capture_id": sess.capture_id,
        "start_ts": sess.first_ts, "end_ts": sess.last_ts,
        "start_str": format_ns_utc(sess.first_ts),
        "end_str": format_ns_utc(sess.last_ts),
        "duration_ns": (sess.last_ts - sess.first_ts
                        if sess.first_ts is not None else 0),
        "partial": sess.partial,
        "state": ("reset" if stats["rst"] else
                  "closed" if (a.fin_seen and b.fin_seen) else
                  "half-closed" if stats["fin"] else
                  "established" if sess.handshake_complete else "partial"),
        "handshake": hs,
        "sack_client": cd["sack_permitted"],
        "sack_server": sd["sack_permitted"],
        "sack_active": sack_active,
        "dir_a": da, "dir_b": db,
        "stats": stats,
        "verdicts": verdicts,
        "warnings": warnings,
        "segments": (_segments_json(sess, a, "A->B")
                     + _segments_json(sess, b, "B->A")),
        "rtt_samples": rtt_samples,
        "rtt_ambiguous": rtt_ambiguous,
        "rtt_hist": histogram(rtt_vals),
        "ack_hist": histogram(ack_lat),
        "recovery_hist": histogram(recovery_vals),
        "loss_events": loss_events,
        "retrans_events": retrans_events,
        "dup_ack_trains": dup_trains,
        "window_events": window_events,
        "observation_events": observation_events,
        "sack_records": sack_records,
        "sack_snapshots": sack_snapshots,
        "packets": [list(r) for r in sess.packet_rows],
    }
