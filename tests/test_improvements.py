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


class TrafficShape(unittest.TestCase):  # items 12-13
    def test_spiky_or_seasonal_cited(self):
        for f in ("H08_UtsavMart.json",):
            with open(os.path.join(ROOT, "scenarios", "hidden_like", f), encoding="utf-8") as fh:
                out = run(json.load(fh))
            h = out["stack"]["hosting"]
            self.assertIn("scale.traffic_pattern", h["driven_by"] + [p for a in h["alternatives"] for p in [a["why_not"]]], f)

    def test_fintech_python_go_not_on_functions(self):
        for langs in (["python"], ["go"]):
            out = run(P(4, team__languages=langs))
            self.assertNotIn("Lambda", core(out, "hosting"), langs)

    def test_read_heavy_cache(self):
        s = P(5, scale__peak_concurrent_users=1500)
        layers = [x["layer"] for x in run(s)["stack"]["supporting"]]
        self.assertIn("cache", layers)
        self.assertNotIn("cache", [x["layer"] for x in run(P(5))["stack"]["supporting"]])


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
    6: ("React Native", "Django", "PostgreSQL", "Cloud Run"),  # round 2: spiky traffic + cost 5 favour scale-to-zero
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


class Counterfactuals(unittest.TestCase):  # item 9
    def test_each_listed_edit_really_flips_the_layer(self):
        from engine.validate import validate
        from engine.recommend import recommend
        for i in range(1, 7):
            out = run(P(i))
            req, errs, _ = validate(P(i))
            self.assertFalse(errs)
            for layer in ("frontend", "backend", "database", "hosting"):
                wwc = out["stack"][layer]["what_would_change"]
                self.assertTrue(1 <= len(wwc) <= 3, (i, layer))
                for e in wwc:
                    if e["path"] is None:
                        continue
                    r2 = dict(req)
                    r2[e["path"]] = e["value"]
                    alt = recommend(r2, [], None, probe=True)
                    self.assertNotEqual(alt["stack"][layer]["kb_id"], out["stack"][layer]["kb_id"], (i, layer, e))
                    self.assertEqual(alt["stack"][layer]["choice"], e["new_choice"])

    def test_margin_reported(self):
        st = run(P(2))["stack"]
        for layer in ("backend", "database", "hosting"):
            self.assertIsInstance(st[layer]["score_margin"], (int, float))
            self.assertGreaterEqual(st[layer]["score_margin"], 0)


class WebUI(unittest.TestCase):  # item 11
    def test_serve_evaluates_like_cli(self):
        import threading
        import urllib.request
        from engine.web import make_server
        srv = make_server(port=0)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            page = urllib.request.urlopen(base + "/").read().decode("utf-8")
            self.assertIn("<title>StackSense</title>", page)
            self.assertNotIn("https://", page.split("<script>")[0])  # no external assets
            schema = json.loads(urllib.request.urlopen(base + "/api/schema").read())
            self.assertIn("project.type", [f["path"] for f in schema])
            body = json.dumps(P(2)).encode("utf-8")
            req = urllib.request.Request(base + "/api/evaluate", data=body, headers={"Content-Type": "application/json"})
            got = json.loads(urllib.request.urlopen(req).read())
            self.assertEqual(got, [evaluate(P(2))])
            samples = json.loads(urllib.request.urlopen(base + "/api/samples").read())
            self.assertGreaterEqual(len(samples), 15)
        finally:
            srv.shutdown()
            srv.server_close()


def H(prefix):
    d = os.path.join(ROOT, "scenarios", "hidden_like")
    name = next(f for f in sorted(os.listdir(d)) if f.startswith(prefix))
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return json.load(f)


def supp(out, layer=None):
    return [x for x in out["stack"]["supporting"] if layer is None or x["layer"] == layer]


class Domains(unittest.TestCase):  # round 2, items 14-23
    def test_one_new_language(self):
        for i in (3, 4):
            for langs in (["php"], ["ruby"]):
                out = run(P(i, team__languages=langs))
                b = core(out, "backend")
                if not ("Node" in b or "Laravel" in b or "Rails" in b):
                    # a mismatched pick is allowed only when clearly better, and the warning must name the skill-matched option
                    msg = " ".join(w["message"] for w in out["warnings"] if w["code"] == "SKILL_MISMATCH")
                    self.assertTrue("Laravel" in msg or "Rails" in msg, (i, langs, b))

    def test_store_billing_for_digital_goods(self):
        out = run(H("H01"))
        pay = supp(out, "payments")[0]["choice"]
        self.assertIn("Google Play Billing", pay)
        self.assertIn("StoreKit", pay)
        self.assertNotIn("Stripe (Checkout)", pay)
        # physical services in a mobile app keep a payment gateway (P2)
        self.assertIn("Razorpay", supp(run(P(2)), "payments")[0]["choice"])

    def test_game_engine_and_servers(self):
        out = run(H("H01"))
        self.assertIn("Unity", core(out, "frontend"))
        self.assertTrue(any("game servers" in x["choice"] for x in supp(out, "realtime")))
        self.assertTrue(any("leaderboard" in x["justification"] for x in supp(out, "cache")))
        for i in range(1, 7):  # never a game engine for a non-game
            self.assertNotIn("Unity", core(run(P(i)), "frontend"))

    def test_iot_ingestion_and_rate(self):
        out = run(H("H02"))
        self.assertTrue(any("MQTT" in x["choice"] for x in supp(out, "other")))
        self.assertIn("IOT_INGEST_RATE", {w["code"] for w in out["warnings"]})
        self.assertTrue(any("partition" in x["choice"] for x in supp(out, "other")))
        s = H("H02")
        s["infrastructure"]["cloud_preference"] = "gcp"
        names = " ".join(x["choice"] for x in supp(run(s)))
        self.assertNotIn("Cloud IoT Core", names.replace("Google Cloud IoT Core", ""))
        self.assertIn("Mosquitto", names)

    def test_analytics_warehouse_and_bi(self):
        names = " ".join(x["choice"] for x in supp(run(H("H03")), "other"))
        self.assertIn("BigQuery", names)
        self.assertIn("Metabase", names)

    def test_api_gateway_and_metering(self):
        out = run(H("H06"))
        self.assertTrue(any(x["choice"].startswith("API gateway") for x in supp(out, "other")))
        self.assertIn("usage-based", supp(out, "payments")[0]["choice"])

    def test_b2b_federation(self):
        auth = supp(run(H("H07")), "auth")[0]["choice"]
        self.assertTrue("per-customer" in auth or "per-tenant" in auth or "one SAML/OIDC provider per customer" in auth, auth)
        # P5 keeps the company's own Entra tenant
        self.assertIn("Entra", supp(run(P(5)), "auth")[0]["choice"])

    def test_desktop_by_language(self):
        self.assertIn("WPF", core(run(H("H11")), "frontend"))

    def test_hipaa_push(self):
        self.assertIn("PHI_IN_PUSH", {w["code"] for w in run(H("H05"))["warnings"]})

    def test_static_cost_bands(self):
        out = run(H("H12"))
        self.assertLessEqual(out["estimated_monthly_cost_usd"]["max"], 30)

    def test_all_hidden_like_pass_contract(self):
        for f in sorted(os.listdir(os.path.join(ROOT, "scenarios", "hidden_like"))):
            run(H(f[:3]))


if __name__ == "__main__":
    unittest.main()
