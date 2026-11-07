"""Week-over-week mode. SYNTHETIC workbooks (written here with a tiny xlsx writer) in the REAL export shape described by the
weekly-dashboard repo: title block, unit-bearing string cells, Sheet1..4 names, file-name stamp. Values invented."""
import io
import os
import random
import unittest
import zipfile
from datetime import datetime, timedelta
from helpers import *
from trafficlab import weekly
from trafficlab.config import make_config
from trafficlab.store import CRStore
from trafficlab.units import parse_rate


def col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(rows, sheet="Sheet1", extra_sheets=3):
    """Minimal valid xlsx with inline strings (all text, as in the real exports)."""
    def sheet_xml(rs):
        out = ['<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
        for ri, r in enumerate(rs, 1):
            out.append(f'<row r="{ri}">')
            for ci, v in enumerate(r):
                if v is None:
                    continue
                v = str(v).replace("&", "&amp;").replace("<", "&lt;")
                out.append(f'<c r="{col(ci)}{ri}" t="inlineStr"><is><t>{v}</t></is></c>')
            out.append("</row>")
        out.append("</sheetData></worksheet>")
        return "".join(out)
    names = [sheet] + [f"Sheet{k}" for k in range(2, 2 + extra_sheets)]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        wb = "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{wb}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
                   "".join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1)) + "</Relationships>")
        for i in range(1, len(names) + 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(rows if i == 1 else [["unrelated"]]))
    return b.getvalue()


HDR = ["Node Name", "IP_Address", "Description", "Interface Name", "Link_Name", "Site", "Timestamp", "Received Bandwidth", "Minimum Receive bps", "Peak Receive",
       "Average Receive", "Received Percent Utilization", "Transmit Bandwidth", "Minimum Transmit bps", "Peak Transmit", "Average Transmit", "Transmit Percent Utilization"]
LINKS = [("rtr-a", "Gi0/0/0"), ("rtr-b", "Gi0/0/1"), ("rtr-c", "Gi0/0/2"), ("rtr-d", "Gi0/0/3")]


def fmt_rate(bps):
    return f"{bps / 1e9:.2f} Gbps" if bps >= 1e9 else f"{bps / 1e6:.2f} Mbps"


def week_rows(wk, rnd, events):
    rows = [["Report: Utilization of Links", None], [None], list(HDR)]
    for n, (dev, ifc) in enumerate(LINKS):
        base = (1.0e9 + 0.2e9 * n) * (1 + rnd.gauss(0, 0.03))
        f = events.get((dev, wk), 1.0)
        a_in, a_out = base * f, base * 0.6 * f
        sp = 10e9
        rows.append([dev, "10.0.0." + str(n), "d", ifc, f"L{n}", "S", None, "10.00 Gbps", "1.2 Mbps", fmt_rate(a_in * 3), fmt_rate(a_in), f"{100 * a_in / sp:.2f} %",
                     "10.00 Gbps", "1.0 Mbps", fmt_rate(a_out * 3), fmt_rate(a_out), f"{100 * a_out / sp:.2f} %"])
    return rows


def build_files(weeks=24, seed=5, events=None, skip=()):
    rnd = random.Random(seed)
    start = datetime(2026, 2, 2)           # Monday; report generated at 00:00:16 covers the week BEFORE
    files = []
    for w in range(weeks):
        if w in skip:
            continue
        g = start + timedelta(days=7 * w)
        name = g.strftime("%Y_%m_%d_00_00_16") + "_Utilization of Links_Last 7 Days WP.xlsx"
        files.append((name, make_xlsx(week_rows(w, rnd, events or {}))))
    return files


class Units(unittest.TestCase):
    def test_rate_cells(self):
        self.assertAlmostEqual(parse_rate("1.06 Gbps"), 1.06e9)
        self.assertAlmostEqual(parse_rate("850 Kbps"), 850e3)


class Reader(unittest.TestCase):
    def test_xlsx_inline_strings_title_block_and_sheet_names(self):
        sheets = weekly.read_xlsx(make_xlsx([["title"], [None], ["a", None, "c"]]))
        self.assertEqual([n for n, _ in sheets], ["Sheet1", "Sheet2", "Sheet3", "Sheet4"])
        rows = sheets[0][1]
        self.assertEqual(rows[2], ["a", None, "c"])             # blank cell keeps column alignment

    def test_header_by_meaning_not_position(self):
        h = weekly.resolve_header(["Hostname", "Port", "In Peak (Mbps)", "Avg Util %"])
        self.assertEqual(set(h), {"device", "interface", "peak_in_bps", "util_avg_pct"})
        self.assertEqual(h["peak_in_bps"][2], "Mbps")              # unit from header
        self.assertIsNone(weekly.resolve_header(["foo", "bar"]))

    def test_week_assignment_basis(self):
        w = weekly.week_of("2026_02_02_00_00_16_Utilization of Links_Last 7 Days WP.xlsx", "UTC")
        self.assertTrue(w["assumption"])
        self.assertEqual(w["end_ms"] - w["start_ms"], weekly.WEEK_MS)
        self.assertEqual(w["ts_raw"], "2026_02_02_00_00_16")
        iso = weekly.week_of("2026-W23/Interface_Utilization_Weekly.xlsx", "UTC")
        self.assertFalse(iso["assumption"])
        self.assertEqual(weekly.week_of("2026-W23/x.xlsx", "UTC", {"x.xlsx": "2026-01-05"})["basis"], "explicit override")
        self.assertIsNone(weekly.week_of("report.xlsx", "UTC"))


class Detection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ev = {("rtr-b", 16): 3.0, ("rtr-c", 11): 1.5, ("rtr-c", 12): 1.5, ("rtr-c", 13): 1.5}
        for w in range(11, 24):
            ev[("rtr-c", w)] = 1.5            # level shift +50% from week 11 on
        ev[("rtr-b", 16)] = 3.0               # one-week spike on rtr-b
        cls.files = build_files(24, events=ev, skip=(7,))
        cls.series, cls.rep = weekly.build_series(cls.files, make_config())
        st = CRStore()
        # CR on rtr-c covering the week that starts the new level (week index 11)
        st.upsert({"cr_id": "CR-W", "title": "t", "status": "Implemented", "planned_start": "2026-04-20 00:00:00", "planned_end": "2026-04-22 00:00:00", "scope": [{"device": "rtr-c"}]})
        cls.res = weekly.analyze_weekly(cls.series, make_config(), st)

    def test_series_and_units(self):
        s = [x for x in self.series if x.key == "rtr-a|Gi0/0/0|avg_in_bps"][0]
        self.assertEqual(s.unit, "bps")
        self.assertEqual(s.speed_bps, 10e9)
        self.assertTrue(0.5e9 < s.rate[0] < 2e9)
        self.assertEqual(s.ts_raw[0], "2026_02_02_00_00_16")      # raw stamp preserved
        self.assertEqual(len(s.rate), 23)                         # week 7 file missing

    def test_missing_week_is_a_marked_gap_not_filled(self):
        s = [x for x in self.series if x.key == "rtr-a|Gi0/0/0|avg_in_bps"][0]
        gaps = [e for e in s.excluded if e["type"] == "gap"]
        self.assertEqual(len(gaps), 1)
        self.assertIn("1 week(s) missing", gaps[0]["detail"])
        self.assertTrue(any("missing-week gaps" in i["message"] for i in self.rep["issues"]))

    def test_validation_flags_assumed_week_once(self):
        msgs = [i["message"] for i in self.rep["issues"] if "ASSUMED" in i["message"]]
        self.assertEqual(len(msgs), 1)
        self.assertTrue(any("cross-check" in i["message"] and "0/" in i["message"] for i in self.rep["issues"]))

    def test_pct_twins_not_duplicated(self):
        self.assertFalse(any(s.metric == "util_in_pct" for s in self.series))
        self.assertTrue(any("not analysed separately" in i["message"] for i in self.rep["issues"]))

    def test_spike_found_on_the_right_link_and_week(self):
        sp = [f for f in self.res["findings"] if f["kind"] == "anomaly" and f["device"] == "rtr-b" and not f.get("continuation_of")]
        self.assertTrue(sp)
        self.assertTrue(all(f["direction"] == "high" for f in sp))
        self.assertTrue(all(f["window"]["granularity"] == "weekly" for f in sp))
        # week index 16 => file stamp 2026-02-02 + 16 weeks = 2026_05_25
        self.assertIn("2026_05_25_00_00_16", {f["window"]["end_raw"] for f in sp})

    def test_level_shift_found_and_cr_candidate(self):
        sh = [f for f in self.res["findings"] if f["kind"] == "pattern_shift" and f["device"] == "rtr-c"]
        self.assertTrue(sh)
        f = sh[0]
        self.assertEqual(f["direction"], "up")
        self.assertAlmostEqual(f["numbers"]["change_pct"], 50, delta=12)
        self.assertEqual(f["window"]["end_raw"], "2026_04_20_00_00_16")     # week 11 stamp
        self.assertEqual([c["cr_id"] for c in f["cr_candidates"]], ["CR-W"])

    def test_untouched_link_has_no_primary_findings(self):
        self.assertEqual([f for f in self.res["findings"] if f["device"] == "rtr-a" and not f.get("continuation_of")], [])

    def test_continuation_tagged_not_hidden(self):
        cont = [f for f in self.res["findings"] if f.get("continuation_of")]
        for f in cont:
            self.assertEqual(f["device"], "rtr-c")

    def test_result_shape_compatible_with_ui(self):
        r = self.res
        for k in ("findings", "clusters", "series", "config", "elapsed_s", "workers"):
            self.assertIn(k, r)
        self.assertIn("tier_counts", r["series"][0]["baseline"])
        self.assertIn("status", r["series"][0]["shift_status"])

    def test_too_few_weeks_refused(self):
        s, _ = weekly.build_series(build_files(5), make_config())
        r = weekly.analyze_weekly(s, make_config())
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["series"][0]["shift_status"]["status"], "insufficient_history")
        self.assertEqual(r["series"][0]["baseline"]["tier_counts"]["trailing_weeks"], 0)

    def test_conflicting_duplicate_week_excluded(self):
        f = build_files(10)
        dup = (f[3][0].replace("00_00_16", "00_05_00"), f[3][1])     # different file name, same covered week?  stamp differs -> new week
        s, rep = weekly.build_series(f + [(f[3][0].replace("Last 7", "Copy of Last 7"), make_xlsx(week_rows(3, random.Random(99), {})))], make_config())
        self.assertTrue(rep["conflicts"])
        self.assertTrue(any(e["type"] == "conflict" for x in s for e in x.excluded))

    def test_csv_input_and_garbage_file(self):
        csv_text = "Hostname,Interface,Avg Receive (Mbps),Avg Transmit (Mbps)\nr1,Gi0/1,100,50\nr2,Gi0/2,200,70\n"
        files = [(f"2026-W{w:02d}/links.csv", csv_text.replace("100", str(100 + w))) for w in range(10, 20)] + [("junk.xlsx", b"not a zip"), ("2026-W30/other.csv", "a,b\n1,2\n")]
        s, rep = weekly.build_series(files, make_config())
        self.assertEqual(len([x for x in s if x.device == "r1" and x.metric == "avg_in_bps"]), 1)
        self.assertEqual(s[0].rate[0], 110e6)                       # header unit Mbps applied
        self.assertTrue(any("cannot read" in i["message"] for i in rep["issues"]))
        self.assertTrue(any("no recognizable" in i["message"] for i in rep["issues"]))
        self.assertGreater(rep["cells"]["unit_from_header"], 0)


WK = os.environ.get("TRAFFICLAB_WEEKLY_FIXTURES")


@unittest.skipUnless(WK and os.path.isdir(WK), "set TRAFFICLAB_WEEKLY_FIXTURES to weekly-dashboard/samples/field-shape (generated by that repo, not real traffic)")
class FieldShape(unittest.TestCase):
    def test_real_shape_files_parse(self):
        import glob
        files = [(os.path.basename(p), open(p, "rb").read()) for p in sorted(glob.glob(WK + "/*Utilization of Links*"))]
        s, rep = weekly.build_series(files, make_config())
        self.assertEqual(len(rep["weeks"]), 26)
        self.assertTrue(all(f["recognized"] for f in rep["files"]))
        self.assertEqual(rep["cells"]["bad"], 0)
        r = weekly.analyze_weekly(s, make_config())
        self.assertGreater(len(r["series"]), 100)


if __name__ == "__main__":
    unittest.main()
