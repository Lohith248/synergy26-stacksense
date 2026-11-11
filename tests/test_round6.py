"""Round 6 (12 Nov session): review findings and Round 5 items 4-9. Each test written before the change."""
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


def with_existing(system, cf=False):
    s = copy.deepcopy(PUBLIC[1])
    s["infrastructure"]["existing_systems"] = [system]
    out = evaluate(s, counterfactuals=cf)
    return {w["code"] for w in out["warnings"]}


class LifecycleSpellings(unittest.TestCase):
    """Review finding: common spellings slipped past the substring match (reproduced: no lifecycle warning)."""

    def test_common_spellings_are_recognised(self):
        for raw in ("Node.js 18 API", "NodeJS 20 service", "node-18 worker", "ASP.NET Core 8 API", "Angular 1.x app"):
            self.assertIn("END_OF_LIFE_SYSTEM", with_existing(raw), raw)
        self.assertIn("END_OF_LIFE_SOON", with_existing("PostgreSQL14 cluster"))

    def test_newer_versions_are_not_flagged(self):
        for raw in ("Node.js 22 API", "Node 180 widgets", "Python 3.13", ".NET 10 API", "PostgreSQL 16", "Angular 17 app"):
            self.assertFalse(with_existing(raw) & {"END_OF_LIFE_SYSTEM", "END_OF_LIFE_SOON"}, raw)


if __name__ == "__main__":
    unittest.main()
