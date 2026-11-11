"""Session A step 3: known gaps, tests written before the changes."""
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


class OneNewLanguage(unittest.TestCase):
    def test_ruby_team_gets_the_language_the_web_ui_needs_anyway(self):
        out = run(P(3, team__languages=["ruby"]))
        b = out["stack"]["backend"]["choice"]
        self.assertIn("Node", b, b)
        msg = " ".join(w["message"] for w in out["warnings"] if w["code"] == "SKILL_MISMATCH")
        self.assertIn("Rails", msg)

    def test_teams_with_a_matching_backend_keep_it(self):
        for langs, want in ((["php"], ("Laravel", "Node")), (["java"], ("Spring",)), (["python"], ("Python",))):
            b = run(P(3, team__languages=langs))["stack"]["backend"]["choice"]
            self.assertTrue(any(w in b for w in want), (langs, b))


if __name__ == "__main__":
    unittest.main()
