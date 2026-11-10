"""Acceptance tests for IMPROVEMENT-PLAN.md items, written before each change.

They encode findings of the perturbation sweep (tools/perturb.py): single-field edits that produced
implausible choices. Expectations are invariants a senior reviewer would hold, not exact stacks.
"""
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
    errs = check(out)
    assert not errs, errs
    return out


def core(out, layer):
    return out["stack"][layer]["choice"]


class LanguageFit(unittest.TestCase):  # item 1
    def test_java_team_keeps_java(self):
        for i in (3, 4):
            for langs in (["java"], ["kotlin"]):
                out = run(P(i, team__languages=langs))
                self.assertIn("Spring", core(out, "backend"), (i, langs))
            # a mixed Java + TypeScript team may reasonably get either of its own languages
            out = run(P(i, team__languages=["java", "typescript"]))
            self.assertTrue(any(x in core(out, "backend") for x in ("Spring", "Node")), core(out, "backend"))

    def test_python_team_realtime_collab(self):
        out = run(P(3, team__languages=["python", "typescript"]))
        self.assertTrue(any(x in core(out, "backend") for x in ("Python", "Node")), core(out, "backend"))
        out = run(P(3, team__languages=["python"]))
        self.assertIn("Python", core(out, "backend"))

    def test_go_team_fintech(self):
        out = run(P(4, team__languages=["go"]))
        self.assertIn("Go", core(out, "backend"))
        self.assertNotIn("SKILL_MISMATCH", {w["code"] for w in out["warnings"]})


class ServerlessFit(unittest.TestCase):  # item 2
    def test_realtime_not_on_functions(self):
        out = run(P(2, infrastructure__cloud_preference="aws"))
        self.assertNotIn("Lambda", core(out, "hosting"))

    def test_jvm_dotnet_not_on_functions(self):
        out = run(P(4, priorities__cost=5))
        self.assertNotIn("Lambda", core(out, "hosting"))
        out = run(P(5, infrastructure__cloud_preference="aws"))
        self.assertNotIn("Lambda", core(out, "hosting"))

    def test_realtime_service_matches_host(self):
        s = P(6, infrastructure__cloud_preference="aws")
        s["requirements"]["realtime"] = True
        s["team"]["languages"] = ["typescript"]
        out = run(s)
        rt = [x for x in out["stack"]["supporting"] if x["layer"] == "realtime"]
        if "Lambda" in core(out, "hosting"):
            self.assertIn("API Gateway WebSocket", rt[0]["choice"])


class StaticHosts(unittest.TestCase):  # item 3
    def test_static_site_on_explicit_cloud(self):
        want = {"aws": "S3", "azure": "Static Web Apps", "gcp": "Firebase Hosting"}
        for cloud, name in want.items():
            out = run(P(1, infrastructure__cloud_preference=cloud))
            self.assertIn(name, core(out, "hosting"), cloud)
            self.assertEqual(core(out, "backend"), "None")
            self.assertLessEqual(out["estimated_monthly_cost_usd"]["max"], 5, cloud)


class NativeSinglePlatform(unittest.TestCase):  # item 4
    def test_android_only_non_js_team(self):
        for langs in (["kotlin"], ["python"], ["java", "python"]):
            out = run(P(6, team__languages=langs))
            self.assertIn("Jetpack Compose", core(out, "frontend"), langs)
            self.assertNotIn("Multiplatform", core(out, "frontend"), langs)


class LowBudget(unittest.TestCase):  # item 5
    def test_zero_budget_dynamic_app_fits(self):
        s = P(1, project__type="web_app", requirements__auth="email_password")
        out = run(s)
        self.assertEqual(out["estimated_monthly_cost_usd"]["min"], 0, out["estimated_monthly_cost_usd"])
        self.assertNotIn("BUDGET_EXCEEDED", {w["code"] for w in out["warnings"]})

    def test_funded_scenarios_keep_cloud_database(self):
        for i in (2, 3, 4, 5, 6):
            self.assertNotIn("Supabase", core(run(P(i)), "database"), i)

    def test_third_party_db_excluded_under_explicit_cloud(self):
        for cloud in ("aws", "azure", "gcp"):
            s = P(1, project__type="web_app", requirements__auth="email_password", infrastructure__cloud_preference=cloud)
            self.assertNotIn("Supabase", core(run(s), "database"), cloud)


if __name__ == "__main__":
    unittest.main()
