"""Round 4: findings of an independent Opus 5.5 review, each reproduced by running the engine before the fix."""
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


def codes(out):
    return {w["code"] for w in out["warnings"]}


class PeakWarning(unittest.TestCase):
    def test_only_when_peak_equals_launch_users(self):
        for i in (3, 4):  # peak 5,000 / 10,000 vs launch 1,000 / 10,000
            s = PUBLIC[i - 1]["scale"]
            self.assertEqual("PEAK_EQUALS_LAUNCH_USERS" in codes(run(P(i))), s["peak_concurrent_users"] == s["users_at_launch"], i)
        out = run(P(3, scale__peak_concurrent_users=2000, scale__users_at_launch=2000))
        self.assertIn("PEAK_EQUALS_LAUNCH_USERS", codes(out))


class LanguageBonus(unittest.TestCase):
    def test_hiring_is_not_counted_twice(self):
        out = run(P(3, team__languages=["python"], team__hiring_languages=["typescript"]))
        j = out["stack"]["backend"]["justification"]
        self.assertFalse("plans to hire" in j and "one new language" in j, j)

    def test_teams_keep_own_language_and_ruby_still_gets_node(self):
        self.assertIn("Python", run(P(3, team__languages=["python"]))["stack"]["backend"]["choice"])
        self.assertIn("Node", run(P(3, team__languages=["ruby"]))["stack"]["backend"]["choice"])


class Wording(unittest.TestCase):
    def test_hipaa_residency_does_not_invent_a_law(self):
        m = next(w["message"] for w in run(P(5, compliance=["hipaa"], infrastructure__data_residency="india"))["warnings"]
                 if w["code"] == "HIPAA_RESIDENCY")
        self.assertIn("does not require", m)
        self.assertNotIn("expectations", m)

    def test_vertex_alternative_does_not_overclaim_marketplace(self):
        with open(os.path.join(ROOT, "engine", "services.py"), encoding="utf-8") as f:
            self.assertNotIn("is the managed option to price", f.read())


if __name__ == "__main__":
    unittest.main()
