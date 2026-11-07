import unittest
import json
from helpers import *
from trafficlab.store import CRStore
from trafficlab import crmatch

H = 3600 * 1000


def cr(**kw):
    d = {"cr_id": "CR1", "title": "t", "status": "Implemented", "planned_start": "2026-01-10 00:00:00", "planned_end": "2026-01-10 02:00:00",
         "scope": [{"device": "A", "interface": ""}]}
    d.update(kw)
    return d


class Store(unittest.TestCase):
    def test_create_update_log(self):
        st = CRStore()
        st.upsert(cr())
        st.upsert(cr(status="Closed", notes="done"))
        log = st.log("CR1")
        fields = [(l["field"], l["old"], l["new"]) for l in log]
        self.assertIn(("status", "Implemented", "Closed"), fields)
        self.assertIn(("notes", "", "done"), fields)

    def test_window_raw_preserved_and_parsed(self):
        st = CRStore()
        c = st.upsert(cr())
        self.assertEqual(c["planned_start_raw"], "2026-01-10 00:00:00")
        self.assertEqual(c["planned_start_ms"], T0_MS + 5 * 86400 * 1000)

    def test_bad_window_rejected_not_stored(self):
        st = CRStore()
        with self.assertRaises(ValueError):
            st.upsert(cr(planned_start="next tuesday"))
        self.assertIsNone(st.get("CR1"))

    def test_bad_status_rejected(self):
        with self.assertRaises(ValueError):
            CRStore().upsert(cr(status="Whatever"))

    def test_export_import_roundtrip(self):
        a = CRStore()
        a.upsert(cr())
        a.link("CR1", "F-123")
        dump = json.loads(json.dumps(a.export_json()))
        b = CRStore()
        self.assertEqual(b.import_json(dump), 1)
        got = b.get("CR1")
        self.assertEqual(got["linked_findings"], ["F-123"])
        self.assertEqual(got["planned_start_ms"], a.get("CR1")["planned_start_ms"])
        self.assertEqual(got["scope"], [{"device": "A", "interface": ""}])

    def test_import_rejects_foreign_format(self):
        with self.assertRaises(ValueError):
            CRStore().import_json({"format": "x"})


class Match(unittest.TestCase):
    def setUp(self):
        st = CRStore()
        st.upsert(cr())
        self.crs = st.list()
        self.s = self.crs[0]["planned_start_ms"]

    def w(self, a, b):
        return {"start_ms": a, "end_ms": b}

    def test_overlap(self):
        m = crmatch.match(self.w(self.s + H, self.s + 3 * H), [("A", "e1")], self.crs)
        self.assertEqual(m[0]["relation"], "overlaps")
        self.assertIn("not proven cause", m[0]["label"])

    def test_follows_within_lookahead(self):
        m = crmatch.match(self.w(self.s + 10 * H, self.s + 11 * H), [("A", "e1")], self.crs)
        self.assertEqual(m[0]["relation"], "follows")
        self.assertAlmostEqual(m[0]["delta_s"], 8 * 3600)

    def test_beyond_lookahead_none(self):
        self.assertEqual(crmatch.match(self.w(self.s + 40 * H, self.s + 41 * H), [("A", "e1")], self.crs), [])

    def test_before_cr_none(self):
        self.assertEqual(crmatch.match(self.w(self.s - 5 * H, self.s - 4 * H), [("A", "e1")], self.crs), [])

    def test_wrong_device_none(self):
        self.assertEqual(crmatch.match(self.w(self.s, self.s + H), [("B", "e1")], self.crs), [])

    def test_interface_scope(self):
        st = CRStore()
        st.upsert(cr(scope=[{"device": "A", "interface": "e2"}]))
        crs = st.list()
        self.assertEqual(crmatch.match(self.w(self.s, self.s + H), [("A", "e1")], crs), [])
        self.assertEqual(len(crmatch.match(self.w(self.s, self.s + H), [("A", "e2")], crs)), 1)

    def test_actual_window_preferred(self):
        st = CRStore()
        st.upsert(cr(actual_start="2026-01-12 00:00:00", actual_end="2026-01-12 01:00:00"))
        crs = st.list()
        self.assertEqual(crmatch.match(self.w(self.s, self.s + H), [("A", "e1")], crs), [])  # planned window ignored


if __name__ == "__main__":
    unittest.main()
