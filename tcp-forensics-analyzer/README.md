# TCP Session, Sequence, SACK & Nanosecond Latency Forensics Analyzer

`tcpforensics` is a pure-Python (stdlib-only) PCAP/PCAPNG analyzer that
performs deep, **session-based** TCP forensics and emits a **single
self-contained interactive HTML report** that opens offline from disk.

It is not a packet counter. The analysis hierarchy is:

```
Capture → TCP Session → Direction → Sequence Range → Packet transmission
        → ACK/SACK state → Retransmission/Recovery → Nanosecond Timing → Evidence
```

## Quick start

```bash
# no dependencies to install — Python 3.10+
python -m tcpforensics capture.pcapng -o report.html
open report.html          # opens fully offline, no server required

# optional: raw analysis model as JSON, custom thresholds
python -m tcpforensics capture.pcap -o report.html --json model.json \
    --high-retrans-pct 1.0 --rto-floor-ms 150

# try it without a real capture
python examples/make_demo_capture.py demo.pcap
python -m tcpforensics demo.pcap -o demo_report.html
```

Run the validation suite:

```bash
python -m unittest discover -s tests -v
```

## What it does

**Capture honesty** — the file's native timestamp resolution (pcap
microsecond/nanosecond magic, pcapng `if_tsresol`) is detected and reported.
All internal timestamps are integer nanoseconds; the report states the
*effective precision* (e.g. "1 µs resolution → effective precision 1000 ns")
and never manufactures nanosecond accuracy from a microsecond capture. The
UI switches display units (ns/µs/ms) without touching the underlying
integers.

**Session reconstruction** — 5-tuple plus connection state (SYN/ISN, FIN,
RST). Reused 5-tuples become separate sessions; SYN retransmissions do not.
Client/server roles come from the handshake; mid-capture sessions are
supported and labelled *partial* with negotiation state reported as
*unknown*, never assumed.

**Sequence-space engine** — every raw 32-bit sequence number is unwrapped
into a 64-bit space (wraparound-aware serial arithmetic; SYN/FIN each
consume one sequence number). Each direction keeps a full sequence ledger
with states `Original / ACKed / SACKed / Retransmitted / Duplicate /
Out-of-order / Recovered / Ambiguous`.

**DATA→ACK correlation** — cumulative-ACK semantics: one ACK may cover many
segments; each byte range records when it transitioned to ACKed and its
DATA→ACK latency in integer ns.

**RTT (Karn's algorithm)** — a valid RTT sample is only taken from a range
transmitted exactly once (preferring the segment whose end matches the ACK).
Ranges that were retransmitted produce `RTT AMBIGUOUS` entries that are
excluded from statistics but retained for forensic display. Handshake RTTs
(SYN→SYN/ACK, SYN/ACK→ACK) are sampled separately. Statistics: min /
mean / median / P50 / P90 / P95 / P99 / P99.9 (only when ≥100 samples) /
max / stddev / count.

**SACK** — negotiation state per endpoint (`unknown` when the handshake was
not captured), every SACK option parsed, per-direction scoreboard with
cumulative-ACK/SACKed/hole/outstanding regions, chronological scoreboard
stepping in the report, hole first-observation timestamps, and RFC 2883
DSACK detection (block below cumulative ACK, or first block contained in the
second) driving spurious-retransmission evidence.

**Retransmissions** — detected by sequence-space overlap (never packet
equality) and classified with recorded evidence: `fast-retransmission`
(≥3 dup-ACKs or an open SACK hole), `rto-retransmission` (delay beyond a
configurable floor / 3×sRTT), `possible-spurious` (range already
ACKed/SACKed or DSACK-reported), `duplicate` (re-seen within a configurable
duplicate window — capture-level duplication), `partial` / `overlapping`,
or `ambiguous`. Every retransmission links to its original frame with the
delay in ns.

**Loss events (first-class)** — each loss episode tracks
`original TX → first evidence → retransmission → recovery ACK` with the
four nanosecond deltas (detection / reaction / post-retransmission /
total), SACK involvement, dup-ACK count, SACK report count, additional
holes during recovery, lost retransmissions, and partial vs complete
recovery.

**Reordering vs loss** — a sequence gap is *not* automatically loss: a gap
filled by a never-before-seen segment is classified as reordering (with the
evidence recorded); a gap filled by a retransmitted range is loss; unfilled
gaps are flagged as possible capture drops and classified Unknown.

**Also tracked** — duplicate-ACK trains (count, inter-ACK gaps in ns,
associated SACK blocks / missing range / retransmission / recovery timing),
receive-window analysis (scaling, zero-window episodes, probes, recovery,
window-full), handshake option negotiation (MSS, WS, SACK-permitted, TS),
and capture-artifact warnings (TSO/GSO oversize segments, snaplen
truncation, asymmetric captures, missing handshakes) so capture effects are
never silently reported as network loss.

**Verdicts** — rule-based per-session verdicts (HEALTHY, HIGH
RETRANSMISSION, HIGH RTT, RTT OUTLIERS, SACK-BASED LOSS RECOVERY OBSERVED,
REPEATED SEQUENCE HOLES, POSSIBLE PACKET REORDERING, POSSIBLE SPURIOUS
RETRANSMISSION, ZERO-WINDOW BOTTLENECK, INCOMPLETE CAPTURE, …). Every
threshold is configurable from the CLI and displayed in the report next to
the measured evidence — no unexplained conclusions.

## The report

Single HTML file, all CSS/JS embedded, zero external requests:

* top-level summary tiles (sessions, packets, payload, retransmissions,
  SACK/loss/dup-ACK/zero-window counts, RTT and recovery percentiles);
* capture-level RTT and loss-recovery histograms + CDFs;
* **Session Explorer** — searchable/filterable/sortable session table
  (IP/port/id text search, duration, bytes, retransmission count/%, RTT
  p50/p99 thresholds, SACK, loss, zero-window, RST, incomplete);
* **Loss & Recovery dashboard** across the capture, each row opening the
  owning session;
* per-session forensic view with tabs: Overview, Sequence (ledger with
  sequence-number search), ACK (dup-ACK trains + DATA→ACK distribution),
  SACK (steppable scoreboard visualization + option records), Loss,
  Retransmissions, RTT (valid + ambiguous samples, histogram, CDF),
  Window, Timeline (client/server sequence ladder with click-to-inspect +
  latency time-series with loss/retransmission/dup-ACK/zero-window
  markers), Packets;
* CSV exports generated client-side: sessions, loss events,
  retransmissions, RTT samples, SACK events, and per-session event data.

Timestamps embedded in the report are capture-start-relative integer
nanoseconds (kept below 2^53 so JavaScript renders them exactly); absolute
UTC timestamps are precomputed as strings.

## Architecture

```
tcpforensics/
  capture_reader.py     streaming pcap/pcapng + Ethernet/SLL/RAW + IPv4/IPv6/TCP decode
  timestamp_engine.py   native-resolution detection, integer-ns normalization
  models.py             compact __slots__ data model (capture_id/capture_point ready
                        for future multi-PCAP one-way latency correlation)
  tcp_sequence.py       32→64-bit unwrapping, interval sets, segment index
  tcp_session.py        session demux (5-tuple + state) and per-packet pipeline
  tcp_ack.py            cumulative DATA→ACK correlation + Karn RTT sampling
  tcp_sack.py           SACK parsing, scoreboard, holes, DSACK
  tcp_retransmission.py evidence-based retransmission classification
  tcp_loss.py           first-class loss/recovery lifecycle events
  tcp_rtt.py            RTT sample stores (valid vs ambiguous)
  tcp_window.py         receive-window tracking and events
  statistics.py         integer percentiles, histograms, CDFs
  verdicts.py           configurable rule-based verdicts with evidence
  artifacts.py          capture-artifact detection (TSO/GSO, snaplen, asymmetry)
  analyzer.py           streaming pipeline + report model assembly
  report_generator.py   self-contained HTML generation (no TCP logic in JS)
  cli.py                command-line interface
tests/                  synthetic pcap/pcapng builder + 44 validation scenarios
examples/               demo capture generator
```

Packets stream from disk through the engine one at a time; only compact
per-session state is retained. Per-session packet rows embedded in the HTML
are capped (`--max-packet-rows`, default 20 000 per session) for very large
captures — analysis results themselves are never truncated.

## Accuracy principles

* Integer-nanosecond arithmetic end to end; no floats in latency math.
* Nothing is fabricated: insufficient evidence yields `Unknown`,
  `Ambiguous`, `partial`, or a capture-artifact warning instead of a guess.
* Every conclusion is traceable to frame numbers shown in the report.

## Validation

`tests/` builds synthetic captures byte-by-byte with exact nanosecond
timestamps and asserts expected sequence-space state and timing for: normal
TCP, delayed/cumulative ACK, single/multiple loss, fast retransmit, RTO
retransmission, Karn ambiguity, SACK recovery, multiple SACK blocks, DSACK,
duplicates, spurious retransmission, reordering, 32-bit sequence
wraparound, zero window + probe + recovery, RST, mid-session capture,
5-tuple reuse, SYN retransmission, µs vs ns pcap precision, pcapng
`if_tsresol`, TSO/asymmetric-capture warnings, JS-safe timestamp encoding,
and CLI/report round-trips.
