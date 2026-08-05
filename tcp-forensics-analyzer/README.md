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

Two ways to run the same analysis:

**In the browser (zero install)** — open
`standalone/tcp-forensics-standalone.html` in any modern browser and drop a
`.pcap`/`.pcapng` on it. Parsing, session reconstruction, sequence-space,
SACK, loss and latency analysis all run locally in the page; nothing leaves
the machine. The browser engine is a line-for-line port of the Python
engine, and `tools/parity_check.py` proves both produce identical analysis
models on the same captures (verified on the synthetic scenario corpus and
real Wireshark wiki captures). Built for scale: the file is parsed in
streamed 8 MB slices inside a Web Worker (never loaded whole), embedded
row listings are bounded while statistics cover all data, and the hot
paths are amortized — a measured 1 GiB / 785k-packet capture analyzes in
~18 s on ~38 MB of JS heap with a live progress bar. Rebuild after engine
changes with `python tools/build_standalone.py`; generate scale-test
captures with `python tools/make_bulk_capture.py out.pcap --gib 1`.

**Command line** —

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

**Liveness traffic** — TCP keep-alives (a ≤1-byte segment at `snd_una−1` on
an idle connection) and zero-window probes are recognized explicitly and
never counted as retransmissions, duplicates, loss, or latency samples.
Duplicate-ACK detection follows RFC 5681: the ACK number *and* the
advertised window must repeat — pure window updates never count as loss
signalling. Karn's exclusion also applies to the handshake: a retransmitted
SYN or SYN/ACK makes the corresponding handshake RTT sample ambiguous.

**Multi-point / SPAN capture intelligence** — captures taken at several
points in the network (SPAN on two leafs, both sides of a routed hop, VLAN
translation, mirrored feeds) show the SAME packet more than once with
rewritten MACs, VLAN and decremented TTL.  The engine fingerprints recent
packets (full TCP content + IPv4 ID + timestamps + window + SACK blocks)
and tracks the set of observation-point signatures per fingerprint: an
identical non-zero IP ID means the same IP packet (a real retransmission is
a NEW IP packet with a new ID) — confirmed; with weak IDs (Linux DF /
IPv6), a NEW L2/TTL signature marks the same packet at another point
("likely") while a REPEATED signature is a new packet generation, so
genuine dup-ACK trains and retransmissions in interleaved two-point
captures are never swallowed.  Recognized observation duplicates are
excluded from retransmission/duplicate/dup-ACK/latency statistics, and the
inter-observation skew (leaf-to-leaf traversal latency) is reported per
event with min/median/P95 statistics.

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
* a per-session flow ladder that reads SYN → Δ → SYN/ACK → Δ → ACK → Δ →
  PSH/ACK … with the inter-packet latency printed between every pair of
  consecutive packets (also available as a Δ-prev column in the Packets
  tab);
* a relative/raw switch for all SEQ/ACK displays (sticky-nav knob):
  relative numbers are ISN-anchored, raw numbers are the on-wire 32-bit
  values, and sequence search accepts input in whichever mode is active;
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

The dashboard uses a dark glassmorphism visual style with fluid,
GPU-friendly animation: staggered panel/tile entrances, count-up summary
tiles, animated histogram/CDF draws, a progressively drawn sequence ladder,
an auto-playing SACK scoreboard that interpolates between events, and
animated event markers on the latency timeline. The chart series palette
(dup-ACK magenta, RTT blue, loss orange, DATA→ACK aqua, zero-window violet,
retransmission red) was validated for color-vision-deficiency separation,
lightness band and contrast against the dark chart surface, and every mark
type is also distinguished by shape and legend label — never color alone.
All motion is disabled automatically under `prefers-reduced-motion`.

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
* Evidence never rewrites history: a DSACK arriving after a loss event has
  already recovered marks the later spurious copy without reclassifying the
  original, genuine loss.
* Corrupt or truncated captures degrade gracefully: everything before the
  damage is analyzed and the damage itself is reported as a capture warning
  in the report header.

## Validation

Real-world corpus: `tools/validate_samples.py <dir>` batch-runs the
analyzer over a directory of captures with cross-consistency checks; the
tool has been validated against 12 TCP captures from the Wireshark wiki
sample set (http.cap, telnet-cooked.pcap, tcp-ecn-sample.pcap,
pcapng-example.pcapng, the 200722 window-scale/tcp pcapng pair,
http_redirects.pcapng, http_with_jpegs.cap and more) — all parse cleanly
with plausible session/RTT/retransmission results (e.g. telnet-cooked's
known 370 ms RTO retransmission at frame 53).  Non-pcap formats such as
NetMon .cap files are rejected with a clear error rather than misparsed.

`tests/` builds synthetic captures byte-by-byte with exact nanosecond
timestamps and asserts expected sequence-space state and timing for: normal
TCP, delayed/cumulative ACK, single/multiple loss, fast retransmit, RTO
retransmission, Karn ambiguity, SACK recovery, multiple SACK blocks, DSACK,
duplicates, spurious retransmission, reordering, 32-bit sequence
wraparound, zero window + probe + recovery, RST, mid-session capture,
5-tuple reuse, SYN retransmission, µs vs ns pcap precision, pcapng
`if_tsresol`, TSO/asymmetric-capture warnings, JS-safe timestamp encoding,
and CLI/report round-trips.
