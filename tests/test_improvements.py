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


class RelaxedLabel(unittest.TestCase):  # item 6
    def test_contradiction_names_relaxed_constraint(self):
        with open(os.path.join(ROOT, "scenarios", "edge_cases", "E3_contradictions.json"), encoding="utf-8") as f:
            out = run(json.load(f))
        self.assertEqual(out["status"], "ok_with_warnings")
        self.assertTrue(out["summary"].startswith("Relaxed recommendation"), out["summary"])
        relaxed = [a for a in out["assumptions"] if a.startswith("Relaxed:")]
        self.assertTrue(any("budget.monthly_infra_usd" in a for a in relaxed), relaxed)

    def test_no_label_without_critical(self):
        for i in range(1, 7):
            out = run(P(i))
            self.assertFalse(out["summary"].startswith("Relaxed"), i)
            self.assertFalse([a for a in out["assumptions"] if a.startswith("Relaxed:")], i)


class Explanations(unittest.TestCase):  # item 7
    NOISE = ("(project.type)", "(scale.users_12_months)", "(project.platforms)")

    def test_alternatives_are_real_options(self):
        for i in range(1, 7):
            out = run(P(i))
            for layer in ("backend", "database", "hosting"):
                alts = out["stack"][layer]["alternatives"]
                viable = [a for a in alts if not a["why_not"].startswith("Excluded")]
                self.assertGreaterEqual(len(alts), 1)
                if len(viable) >= 2:
                    for a in alts:
                        if a["why_not"].startswith("Excluded"):
                            self.assertFalse(any(n in a["why_not"] for n in self.NOISE), (i, layer, a))

    def test_justification_skips_neutral_priorities(self):
        for i in range(1, 7):
            st = run(P(i))["stack"]
            for layer in ("backend", "database", "hosting"):
                self.assertNotIn("(priority 3/5)", st[layer]["justification"], (i, layer))

    def test_disbursal_wording(self):
        pay = [s for s in run(P(4))["stack"]["supporting"] if s["layer"] == "payments"][0]
        self.assertIn("disburs", pay["choice"].lower())
        self.assertNotIn("service providers", pay["choice"])

    def test_cross_cloud_existing_service_flagged(self):
        for cloud in ("aws", "gcp"):
            out = run(P(5, infrastructure__cloud_preference=cloud))
            self.assertIn("EXISTING_CROSS_CLOUD_SERVICE", {w["code"] for w in out["warnings"]}, cloud)

    def test_ci_cost_follows_team_size(self):
        with open(os.path.join(ROOT, "scenarios", "edge_cases", "E4_overengineering_trap.json"), encoding="utf-8") as f:
            out = run(json.load(f))
        ci = [a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("ci_cd")]
        self.assertTrue(all("$0-4" in a or "$0-0" in a for a in ci), ci)

    def test_hosting_plan_sized_to_scale(self):
        self.assertNotIn("and up", core(run(P(3)), "hosting"))
        self.assertIn("Premium", core(run(P(3)), "hosting"))
        self.assertIn("Basic", core(run(P(5)), "hosting"))


PUBLIC_CORES = {  # regression guard: public-scenario cores after items 1-7 (change only with a recorded reason)
    1: ("Astro", "None", "None", "Cloudflare Pages"),
    2: ("Next.js", "NestJS", "PostgreSQL", "Azure App Service"),
    3: ("React (Vite SPA)", "Go", "PostgreSQL", "Azure App Service"),
    4: ("React (Vite SPA)", "Spring Boot", "Amazon RDS for PostgreSQL", "ECS on Fargate"),
    5: ("React (Vite SPA)", ".NET", "Azure SQL", "Azure App Service"),
    6: ("React Native", "Django", "PostgreSQL", "Azure App Service"),
}


class Breadth(unittest.TestCase):  # item 8
    def test_kb_sizes(self):
        from engine.kb import TECH
        self.assertGreaterEqual(len(TECH["database"]), 8)
        self.assertGreaterEqual(len(TECH["frontend_web"]), 9)
        names = " ".join(x["name"] for x in TECH["frontend_web"])
        self.assertIn("Vue", names)
        self.assertIn("Nuxt", names)

    def test_public_cores_stable(self):
        for i, want in PUBLIC_CORES.items():
            out = run(P(i))
            for layer, w in zip(("frontend", "backend", "database", "hosting"), want):
                self.assertIn(w, core(out, layer), (i, layer))

    def test_vue_team_gets_vue(self):
        out = run(P(2, team__languages=["vue", "python"]))
        self.assertIn("Nuxt", core(out, "frontend"))


if __name__ == "__main__":
    unittest.main()
