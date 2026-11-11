"""Session A step 2: did-you-mean hints, unknown-key info warnings, extra contradiction checks.
Expectations were written before the code (IMPROVEMENT-PLAN / HANDOFF Session A, step 2)."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from engine.run import evaluate  # noqa: E402
from check_contract import check  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
    PUBLIC = json.load(f)


def P(i, **edits):
    s = copy.deepcopy(PUBLIC[i - 1])
    for path, v in edits.items():
        d = s
        parts = path.split("__")
        for p in parts[:-1]:
            d = d[p]
        d[parts[-1]] = v
    return s


def run(s):
    out = evaluate(s)
    assert not check(out), check(out)
    return out


def errs(out):
    return {e["field"]: e["message"] for e in out["validation_errors"]}


def codes(out, sev=None):
    return {w["code"] for w in out["warnings"] if sev is None or w["severity"] == sev}


class DidYouMean(unittest.TestCase):
    def test_enum_typo(self):
        out = run(P(1, infrastructure__cloud_preference="gcpp"))
        self.assertEqual(out["status"], "invalid_input")
        self.assertIn("Did you mean 'gcp'?", errs(out)["infrastructure.cloud_preference"])

    def test_enum_case_typo(self):
        self.assertIn("Did you mean 'aws'?", errs(run(P(1, infrastructure__cloud_preference="AWS")))["infrastructure.cloud_preference"])

    def test_list_value_typo(self):
        out = run(P(2, project__platforms=["web", "andriod"]))
        self.assertIn("Did you mean 'android'?", errs(out)["project.platforms"])

    def test_no_hint_for_garbage(self):
        out = run(P(1, infrastructure__cloud_preference="zzzzzz"))
        self.assertNotIn("Did you mean", errs(out)["infrastructure.cloud_preference"])

    def test_misspelled_required_key(self):
        s = P(1)
        s["project"]["plaforms"] = s["project"].pop("platforms")
        m = errs(run(s))["project.platforms"]
        self.assertIn("plaforms", m)
        self.assertIn("Did you mean 'platforms'?", m)

    def test_misspelled_group(self):
        s = P(1)
        s["teem"] = s.pop("team")
        out = run(s)
        self.assertIn("teem", errs(out)["team.size"])
        self.assertIn("'team'", errs(out)["team.size"])


class UnknownKeys(unittest.TestCase):
    def find(self, out, path):
        return [w for w in out["warnings"] if w["code"] == "UNKNOWN_FIELD" and w["fields"] == [path]]

    def test_unknown_nested_key_is_info_and_harmless(self):
        base = run(P(2))
        out = run(P(2, project__colour="red"))
        w = self.find(out, "project.colour")
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["severity"], "info")
        self.assertIn("ignored", w[0]["message"])
        self.assertEqual(out["stack"], base["stack"])
        self.assertEqual(out["status"], base["status"])

    def test_unknown_top_level_key(self):
        out = run(P(1, notes="x"))
        self.assertEqual(len(self.find(out, "notes")), 1)

    def test_misspelled_optional_key_gets_hint(self):
        s = P(2)
        s["priorities"]["securty"] = 5
        w = self.find(run(s), "priorities.securty")
        self.assertEqual(len(w), 1)
        self.assertIn("Did you mean 'security'?", w[0]["message"])

    def test_public_scenarios_have_no_unknown_keys(self):
        for i in range(1, 7):
            self.assertNotIn("UNKNOWN_FIELD", codes(run(P(i))), i)

    def test_listed_on_invalid_input_too(self):
        out = run(P(1, infrastructure__cloud_preference="gcpp", project__colour="red"))
        self.assertEqual(out["status"], "invalid_input")
        self.assertEqual(len(self.find(out, "project.colour")), 1)


class MoreContradictions(unittest.TestCase):
    def test_offline_with_api_only(self):
        out = run(P(2, project__platforms=["api_only"], requirements__offline_support=True))
        self.assertIn("OFFLINE_WITHOUT_CLIENT", codes(out, "warning"))

    def test_offline_with_a_client_is_fine(self):
        self.assertNotIn("OFFLINE_WITHOUT_CLIENT", codes(run(P(6))))

    def test_seo_on_internal_tool(self):
        out = run(P(5, requirements__seo_critical=True))
        self.assertIn("SEO_ON_INTERNAL_TOOL", codes(out, "warning"))
        self.assertNotIn("SEO_ON_INTERNAL_TOOL", codes(run(P(5))))

    def test_hipaa_outside_us(self):
        for res in ("india", "eu", "other"):
            out = run(P(5, compliance=["hipaa"], infrastructure__data_residency=res))
            self.assertIn("HIPAA_RESIDENCY", codes(out, "warning"), res)
        for res in ("us", "none"):
            out = run(P(5, compliance=["hipaa"], infrastructure__data_residency=res))
            self.assertNotIn("HIPAA_RESIDENCY", codes(out), res)

    def test_budget_far_above_need(self):
        out = run(P(5, budget__monthly_infra_usd=20000))
        self.assertIn("BUDGET_FAR_ABOVE_NEED", codes(out, "info"))
        for i in range(1, 7):
            self.assertNotIn("BUDGET_FAR_ABOVE_NEED", codes(run(P(i))), i)

    def test_public_statuses_unchanged_by_new_checks(self):
        got = [run(P(i))["status"] for i in range(1, 7)]
        for i in range(1, 7):
            with open(os.path.join(ROOT, "outputs", f"P{i}_output.json"), encoding="utf-8") as f:
                self.assertEqual(got[i - 1], json.load(f)["status"], i)


if __name__ == "__main__":
    unittest.main()
