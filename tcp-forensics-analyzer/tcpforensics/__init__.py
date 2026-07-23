"""tcpforensics — TCP session, sequence, SACK & nanosecond latency forensics.

Pure-stdlib PCAP/PCAPNG TCP analyzer.  All internal timestamps are integer
nanoseconds.  The analysis hierarchy is:

    Capture -> TCP Session -> Direction -> Sequence Range -> Transmission
            -> ACK/SACK state -> Retransmission/Recovery -> Timing
"""

__version__ = "1.0.0"
