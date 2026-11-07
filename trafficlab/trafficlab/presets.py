"""Mapping presets for CSV shapes that are KNOWN from code in the user's own repos.
Source of truth for the two collector presets: nexus_collect.py (omi23484/AI-Automation,
branch claude/nexus-buffer-traffic-analyzer-plc75i): header rows and ts_str() = '%-m/%-d/%Y %H:%M:%S'
(month-first, non-padded, 24 h, collector's LOCAL clock -> set the timezone yourself).
These describe the CSV layout only. They were NOT validated against output from a real device."""

PRESETS = {
    "nexus_collect_utilization": {
        "description": "nexus_collect.py report1_utilization.csv. Rates are the device's own load-interval average (point-in-time sample, not a counter delta).",
        "ts_formats": ["%m/%d/%Y %H:%M:%S"],
        "mapping": {
            "device": "Hostname", "interface": "Interface Name", "timestamp": "Timestamp", "zone": None,
            "counters": [],
            "gauges": [{"name": "in_bps", "column": "Receive Mbps", "parse": "rate", "default_unit": "Mbps", "unit": "bps"},
                        {"name": "out_bps", "column": "Transmit Mbps", "parse": "rate", "default_unit": "Mbps", "unit": "bps"}],
            "uptime": None,
            "speed": {"column": "Received Bandwidth", "parse": "rate", "default_unit": "Mbps"},
        },
    },
    "nexus_collect_errors": {
        "description": "nexus_collect.py report2_errors_discards.csv. Cumulative counters; width (32/64-bit) NOT known -> declared 32 (conservative): a decrease with no uptime/speed is excluded as ambiguous, never guessed.",
        "ts_formats": ["%m/%d/%Y %H:%M:%S"],
        "mapping": {
            "device": "Caption", "interface": "Interface Name", "timestamp": "Timestamp", "zone": None,
            "counters": [{"name": n, "column": c, "bits": 32, "mult": 1, "unit": "count"} for n, c in
                         (("rx_discards", "Received Discards"), ("rx_errors", "Received Errors"),
                          ("tx_discards", "Transmit Discards"), ("tx_errors", "Transmit Errors"))],
            "gauges": [], "uptime": None, "speed": None,
        },
    },
}
