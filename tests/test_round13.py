"""Round 13 (12 Nov session, judge round 4 batch C): explanation wording of alternatives. F9, F11, F18 + earlier
judge findings (supporting boilerplate, excluded-option padding, summary length, invalid_input assumptions).
Each test written before the change. Blind inputs are read from ../research when present."""
import collections
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.run import evaluate  # noqa: E402
from test_round9 import PUBLIC  # noqa: E402
from test_round11 import blind, ev  # noqa: E402
from test_round12 import all_scenarios  # noqa: E402

CORE = ("frontend", "backend", "database", "hosting")
_CACHE = {}


def outs():
    if not _CACHE:
        for k, s in all_scenarios():
            _CACHE.setdefault(k, ev(s))
    return _CACHE


def why_nots(out, core_only=False):
    st = out.get("stack")
    if not st:
        return []
    res = []
    for layer in CORE:
        res += [(layer, a) for a in st[layer]["alternatives"]]
    if not core_only:
        res += [(s["layer"], a) for s in st.get("supporting", []) for a in s["alternatives"]]
    return res


class F9DecisiveReason(unittest.TestCase):
    def test_no_score_wording_in_why_not(self):
        for sid, out in outs().items():
            for layer, a in why_nots(out):
                w = a["why_not"]
                self.assertNotIn("points behind", w, (sid, layer, w))
                self.assertNotIn("points higher", w, (sid, layer, w))
                self.assertNotIn("(priority", w, (sid, layer, w))
                self.assertNotIn("is stronger on:", w, (sid, layer, w))
                self.assertNotIn("score ", w.lower(), (sid, layer, w))

    def test_lead_is_grounded_in_an_input_value(self):
        """Every scored (non-excluded) core alternative names an input path with its value, e.g. 'priorities.cost=5'."""
        for sid, out in outs().items():
            for layer, a in why_nots(out, core_only=True):
                w = a["why_not"]
                if w.startswith("Excluded") or "tie-break" in w:
                    continue
                if " rather than " in w or "Tauri" in a["choice"] or "Developer portal" in a["choice"]:
                    continue
                if out["stack"][layer].get("kb_id") in (None, "none") or out["stack"][layer]["choice"] == "None":
                    continue
                self.assertRegex(w, r"[a-z_]+\.[a-z_0-9]+=", (sid, layer, w))

    def test_close_call_marker(self):
        """P1 hosting runner-up is within 0.5 points: the text says '(close call)' and gives no number."""
        alt = outs()["P1"]["stack"]["hosting"]["alternatives"][0]
        self.assertIn("close call", alt["why_not"])

    def test_skill_override_keeps_reason(self):
        s = copy.deepcopy(PUBLIC["P3"])
        s["team"]["languages"] = ["php"]
        b = evaluate(s, counterfactuals=False)["stack"]["backend"]
        self.assertLess(b["score_margin"], 0)
        self.assertIn("team-language preference", b["alternatives"][0]["why_not"])


class F11LicenceFiller(unittest.TestCase):
    def test_no_sqlserver_alternative_without_signal(self):
        for sid, out in outs().items():
            if not out.get("stack"):
                continue
            s = dict(all_scenarios())[sid] if sid not in PUBLIC else PUBLIC[sid]
            text = repr(s).lower()
            signal = any(x in text for x in ("sql server", "mssql", "csharp", ".net", "c#"))
            if signal:
                continue
            for a in out["stack"]["database"]["alternatives"]:
                self.assertNotIn("SQL Server", a["choice"], (sid, a))
                self.assertNotIn("Azure SQL", a["choice"], (sid, a))


class ExcludedPadding(unittest.TestCase):
    def test_at_most_one_excluded_and_only_when_needed(self):
        for sid, out in outs().items():
            if not out.get("stack"):
                continue
            for layer in ("backend", "database", "hosting"):
                alts = out["stack"][layer]["alternatives"]
                ex = [a for a in alts if a["why_not"].startswith("Excluded")]
                real = [a for a in alts if not a["why_not"].startswith("Excluded")]
                self.assertLessEqual(len(ex), 1, (sid, layer, alts))
                if ex:
                    self.assertLess(len(real), 2, (sid, layer, alts))
                self.assertGreaterEqual(len(alts), 1, (sid, layer))

    def test_excluded_names_the_constraint_value(self):
        for sid, out in outs().items():
            for layer, a in why_nots(out, core_only=True):
                if a["why_not"].startswith("Excluded") and "deployment_model" in a["why_not"]:
                    self.assertRegex(a["why_not"], r"deployment_model=\w+ rules out", (sid, a))


class SupportingBoilerplate(unittest.TestCase):
    def test_supporting_why_not_cites_inputs(self):
        for sid, out in outs().items():
            for layer, a in why_nots(out):
                w = a["why_not"]
                self.assertNotEqual(w, "equivalent; GitHub chosen for its marketplace of deploy actions", sid)
                self.assertNotEqual(w, "bloats backups and costs more per GB", sid)
                self.assertNotEqual(w, "extra vendor; add later for richer error grouping", sid)
                if a["choice"] == "Storing files in the database":
                    self.assertIn("GB", w)
                    self.assertRegex(w, r"\d+ GB", (sid, w))
                if a["choice"] == "GitLab CI":
                    self.assertRegex(w, r"team of \d+", (sid, w))

    def test_most_repeated_why_not_is_rare(self):
        c = collections.Counter(a["why_not"] for out in outs().values() for _, a in why_nots(out))
        top, n = c.most_common(1)[0]
        self.assertLessEqual(n, 15, (n, top))


class F18NearestFlip(unittest.TestCase):
    def test_no_vague_no_flip_claim(self):
        for sid in ("P1", "P2", "P3", "P4", "P5", "P6"):
            out = evaluate(copy.deepcopy(PUBLIC[sid]))
            for layer in CORE:
                for e in out["stack"][layer]["what_would_change"]:
                    self.assertNotIn("No single-field edit", e["new_choice"], (sid, layer))
                    self.assertIsNotNone(e["path"], (sid, layer, e))


class Readability(unittest.TestCase):
    def test_summary_short_and_region_once(self):
        for sid in ("P1", "P2", "P3", "P4", "P5", "P6"):
            s = outs()[sid]["summary"]
            self.assertLessEqual(len(s), 270, (sid, len(s), s))
        s = outs()["P2"]["summary"]
        self.assertEqual(s.count("Central India (Pune)"), 1, s)

    def test_single_platform_justification_does_not_repeat_choice(self):
        j = outs()["P1"]["stack"]["frontend"]["justification"]
        self.assertFalse(j.startswith("Web: Astro"), j)
        j4 = outs()["P4"]["stack"]["frontend"]["justification"]
        self.assertTrue(j4.startswith("Web: "), j4)  # multi-platform keeps its labels

    def test_invalid_input_has_no_default_list(self):
        out = outs()["E1"]
        self.assertEqual(out["status"], "invalid_input")
        self.assertFalse([a for a in out["assumptions"] if "applied." in a], out["assumptions"])
        self.assertLessEqual(len(out["assumptions"]), 2, out["assumptions"])


class BlindExamples(unittest.TestCase):
    def test_b03_backend_alternative_reason_not_numeric(self):
        out = ev(blind("B03"))
        for a in out["stack"]["backend"]["alternatives"]:
            self.assertNotRegex(a["why_not"], r"\d+\.\d points", a)


if __name__ == "__main__":
    unittest.main()
