"""Round 12 (12 Nov session, judge round 4 batch B): cost realism. F5, F7, F12, F16 + strict-judge B1-B6.
Each test written before the change. Blind inputs are read from ../research when present."""
import glob
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_round9 import PUBLIC  # noqa: E402
from test_round11 import blind, ev  # noqa: E402

RESEARCH = os.path.join(os.path.dirname(ROOT), "research")
RANGE = re.compile(r"\$([\d,]+(?:\.\d+)?)-([\d,]+(?:\.\d+)?)/month")


def all_scenarios():
    out = [(k, v) for k, v in PUBLIC.items()]
    files = sorted(glob.glob(os.path.join(ROOT, "scenarios", "edge_cases", "*.json"))
                   + glob.glob(os.path.join(RESEARCH, "blind3", "B*.json")) + glob.glob(os.path.join(RESEARCH, "blind4", "C*.json")))
    for p in files:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        for s in (d if isinstance(d, list) else [d]):
            out.append((os.path.basename(p).split("_")[0], s))
    return out


def lines(out):
    return out["estimated_monthly_cost_usd"]["assumptions"]


def line(out, start):
    return next((l for l in lines(out) if l.startswith(start)), None)


def rng(text):
    m = RANGE.search(text)
    return float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))


class B1BandEqualsItsLines(unittest.TestCase):
    def test_lines_sum_to_band(self):
        n = 0
        for sid, s in all_scenarios():
            out = ev(s)
            c = out.get("estimated_monthly_cost_usd") or {}
            if c.get("min") is None:
                continue
            lo = hi = 0.0
            for l in c["assumptions"]:
                m = RANGE.search(l)  # the first "$a-b/month" of a line is that line's amount
                if m:
                    lo += float(m.group(1).replace(",", ""))
                    hi += float(m.group(2).replace(",", ""))
            with self.subTest(sid=sid):
                self.assertLessEqual(abs(lo - c["min"]), 1, (sid, lo, c["min"], c["assumptions"]))
                self.assertLessEqual(abs(hi - c["max"]), 1, (sid, hi, c["max"], c["assumptions"]))
            n += 1
        self.assertGreaterEqual(n, 6)

    def test_ha_and_stored_data_lines_carry_amounts(self):
        p4 = ev(PUBLIC["P4"])
        self.assertIsNotNone(RANGE.search(line(p4, "Availability") or ""), lines(p4))
        self.assertIsNotNone(RANGE.search(line(p4, "Stored data") or ""), lines(p4))


class B2BudgetWarningNamesLargestLines(unittest.TestCase):
    def test_c09_names_stored_data(self):
        out = ev(blind("C09"))
        w = [w for w in out["warnings"] if w["code"].startswith("BUDGET")]
        self.assertTrue(w)
        self.assertIn("Stored data", w[0]["message"])

    def test_largest_upper_bound_named_first(self):
        out = ev(blind("C11"))
        w = next(w for w in out["warnings"] if w["code"].startswith("BUDGET"))
        top = max(((rng(l)[1], l) for l in lines(out) if RANGE.search(l)), key=lambda x: x[0])
        label = top[1].split(":")[0]
        self.assertIn(label[:20], w["message"])
        self.assertNotIn("other (up to", w["message"])  # layer slug is not a name


class B3HaTierMatchesPrice(unittest.TestCase):
    def test_azure_pg_ha_is_general_purpose(self):
        out = ev(blind("C08"))
        db = line(out, "Database")
        self.assertIn("General Purpose", db)
        self.assertNotIn("Sized for a Burstable", db)
        self.assertGreaterEqual(rng(db)[0], 366)

    def test_app_service_zone_redundant_floor(self):
        out = ev(blind("C08"))
        h, ha = line(out, "Hosting"), line(out, "Availability")
        self.assertIn("Premium v3", h)
        self.assertGreaterEqual(rng(h)[0] + rng(ha)[0], 120)

    def test_small_tier_label_inside_band(self):
        db = line(ev(PUBLIC["P2"]), "Database")
        self.assertIn("B1ms", db)  # the band's floor names the size that costs that much


class B4SelfHostedAndFloors(unittest.TestCase):
    def test_every_self_hosted_tool_has_a_line(self):
        for sid in ("C09", "B10", "E7", "C14"):
            out = ev(blind(sid)) if sid[0] in "BC" else ev(_edge(sid))
            txt = " ".join(lines(out))
            for s in out["stack"]["supporting"]:
                if s["deployment"] == "self_hosted" and not s["choice"].startswith("Existing"):
                    with self.subTest(sid=sid, choice=s["choice"]):
                        self.assertIn(s["choice"].split(" — ")[0], txt)

    def test_fabric_capacity_floor(self):
        l = line(ev(blind("C09")), "other: Analytics warehouse")
        self.assertGreaterEqual(rng(l)[0], 263)
        self.assertIn("F2", l)

    def test_db_storage_scales_with_data(self):
        out = ev(blind("C09"))
        self.assertGreaterEqual(rng(line(out, "Stored data"))[0], 800)


class B5SmsOnceAndVideoEgress(unittest.TestCase):
    def test_sms_counted_once(self):
        out = ev(PUBLIC["P4"])
        auth = line(out, "auth:")
        self.assertIn("Phone OTP line", auth)
        self.assertIn("0.0055", auth)  # Cognito Lite per-MAU rate (R5 verified)

    def test_video_egress_line(self):
        out = ev(blind("C11"))
        v = line(out, "Video egress")
        self.assertIsNotNone(v, lines(out))
        self.assertGreaterEqual(rng(v)[1], 10000)
        self.assertIn("reference", v)


class B6OnPremSummary(unittest.TestCase):
    def test_onprem_summary(self):
        for sid in ("E7", "B11"):
            out = ev(_edge(sid)) if sid[0] == "E" else ev(blind(sid))
            self.assertIn("cloud bill $0; hardware/licences excluded", out["summary"])


class F16RagSearchFloor(unittest.TestCase):
    def test_c10_ai_search_basic(self):
        out = ev(blind("C10"))
        ml = line(out, "ml:")
        self.assertGreaterEqual(rng(ml)[0], 74)
        s = next(s for s in out["stack"]["supporting"] if s["layer"] == "ml")
        self.assertNotIn("embeddings stored next to the data", s["justification"])


def _edge(sid):
    p = glob.glob(os.path.join(ROOT, "scenarios", "edge_cases", sid + "_*.json"))[0]
    with open(p, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    unittest.main()
