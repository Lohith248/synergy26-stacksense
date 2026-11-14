"""J1 (judge text fixes on P1-P6): a priority left at the neutral 3 is never the reason one option beat another, KB limits that hold only when a need
is on (WebSocket, SEO) are shown only then, OTP offline-session trade-off only with offline_support, payment fee text that is true for the region,
RBI backup wording, Auth0 / Firestore / SvelteKit / cache alternatives that are true, budget warning names Cognito MAU and SMS separately.
Every rule is tested on several project types plus inputs where it must not fire. Inputs are inline."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402
from engine import context as cx  # noqa: E402
from engine import recommend as rec  # noqa: E402
from engine.validate import validate  # noqa: E402
from engine.kb import TECH, SOURCES  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
    PUBLIC = json.load(f)

BASE = {"scenario_id": "J1", "project": {"type": "web_app", "platforms": ["web"], "description": "A small web application."},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "intermediate", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 3000}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def run(base=None, **kw):
    s = copy.deepcopy(base or BASE)
    for path, v in kw.items():
        node, parts = s, path.replace("__", ".").split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return evaluate(s, counterfactuals=False)


def ctx_for(**kw):
    s = copy.deepcopy(BASE)
    for path, v in kw.items():
        node, parts = s, path.replace("__", ".").split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    req, _, _ = validate(s)
    return cx.build(req)


def all_text(out):
    st = out["stack"]
    comps = [st[k] for k in ("frontend", "backend", "database", "hosting")] + list(st["supporting"])
    for c in comps:
        for a in c.get("alternatives", []):
            yield a["why_not"]
        if c.get("contrast"):
            yield c["contrast"]


def supporting(out, layer):
    return next((s for s in out["stack"]["supporting"] if s["layer"] == layer), None)


class NeutralPriorityIsNeverTheReason(unittest.TestCase):
    def test_public_scenarios(self):
        for sc in PUBLIC:
            out = evaluate(sc, counterfactuals=False)
            for t in all_text(out):
                self.assertNotIn("(neutral)", t, (sc["scenario_id"], t))

    def test_other_project_types(self):
        for kw in ({"project__type": "ecommerce", "priorities__cost": 3, "priorities__performance": 3, "priorities__security": 3},
                   {"project__type": "internal_tool", "priorities__time_to_market": 3, "priorities__maintainability": 3},
                   {"project__type": "content_site", "priorities__scalability": 3, "priorities__cost": 4},
                   {"project__type": "social", "project__platforms": ["android"], "priorities__performance": 3, "priorities__security": 3}):
            for t in all_text(run(**kw)):
                self.assertNotIn("(neutral)", t, (kw, t))

    def test_a_priority_the_input_sets_is_still_given(self):
        # must not fire: priorities away from 3 still lead the reason (P1 keeps its cost priority of 5)
        out = evaluate(PUBLIC[0], counterfactuals=False)
        self.assertTrue(any("priorities.cost=5" in t for t in all_text(out)))

    def test_only_neutral_gap_is_said_plainly(self):
        out = evaluate(PUBLIC[2], counterfactuals=False)  # P3: React over Vue differs only on the neutral time_to_market
        alt = next(a for a in out["stack"]["frontend"]["alternatives"] if a["choice"].startswith("Vue"))
        self.assertTrue("level with React on every priority and requirement this input states" in alt["why_not"]
                        or "No priority or requirement this input states separates Vue 3 from React" in alt["why_not"], alt["why_not"])


class NeutralFallbackWording(unittest.TestCase):
    def texts(self, **kw):
        return [t for t in all_text(run(**kw)) if "separates" in t or "level with" in t]

    def test_all_neutral_says_so_not_the_project_type(self):
        allthree = {f"priorities__{p}": 3 for p in ("cost", "time_to_market", "scalability", "performance", "maintainability", "security")}
        for t in ("iot", "web_app", "ecommerce"):
            ts = self.texts(project__type=t, **allthree)
            self.assertTrue(ts, t)
            for x in ts:
                self.assertIn("all six priorities are at the neutral 3", x)
                self.assertNotIn("project.type=", x)

    def test_names_the_neutral_priorities_it_rests_on(self):
        for sc in PUBLIC:
            for t in all_text(evaluate(sc, counterfactuals=False)):
                if "separates" in t:
                    self.assertIn("rates higher only on priorities this input leaves at the neutral 3 (priorities.", t)
                    self.assertNotIn("general ratings", t)


class LearningCurveLeadsWithTheWinner(unittest.TestCase):
    def test_p4_angular(self):
        out = evaluate(PUBLIC[3], counterfactuals=False)
        ang = next(a for a in out["stack"]["frontend"]["alternatives"] if a["choice"] == "Angular")["why_not"]
        self.assertTrue(ang.startswith("React fits better: Angular's learning curve is 4/5 for a senior team (team.experience=senior)"), ang)
        self.assertEqual(ang.lower().count("learning curve"), 1, ang)
        self.assertIn("Known limit of Angular: support lasts 24 months", ang)

    def test_no_bare_learning_fragment_anywhere(self):
        for sc in PUBLIC:
            for t in all_text(evaluate(sc, counterfactuals=False)):
                self.assertFalse(t.startswith("Learning curve"), t)


class KnowledgeBaseHasNoDuplicateKeys(unittest.TestCase):
    def test_loader_rejects_duplicates(self):
        from engine import kb
        with self.assertRaises(ValueError):
            json.loads('{"a": 1, "a": 2}', object_pairs_hook=kb._no_duplicate_keys)
        self.assertEqual(json.loads('{"a": 1, "b": {"a": 2}}', object_pairs_hook=kb._no_duplicate_keys), {"a": 1, "b": {"a": 2}})

    def test_every_kb_file_loads_clean(self):
        for name in sorted(os.listdir(os.path.join(ROOT, "kb"))):
            if name.endswith(".json"):
                with open(os.path.join(ROOT, "kb", name), encoding="utf-8") as f:
                    json.load(f, object_pairs_hook=__import__("engine.kb", fromlist=["x"])._no_duplicate_keys)

    def test_angular_source_keeps_its_claim(self):
        self.assertIn("R3:AN-01", SOURCES["angular-releases"]["claims"])


class ConditionalLimits(unittest.TestCase):
    WS = "WebSockets need Django Channels"
    SEO = "Client-rendered pages are weak for SEO"

    def test_websocket_limit_needs_realtime(self):
        for t in ("web_app", "marketplace", "internal_tool"):
            self.assertFalse(rec.limit_applies(self.WS, ctx_for(project__type=t)), t)
            self.assertTrue(rec.limit_applies(self.WS, ctx_for(project__type=t, requirements__realtime=True)), t)

    def test_seo_limit_needs_search_traffic(self):
        self.assertTrue(rec.limit_applies(self.SEO, ctx_for(requirements__seo_critical=True)))
        self.assertTrue(rec.limit_applies(self.SEO, ctx_for(project__type="content_site")))
        self.assertTrue(rec.limit_applies(self.SEO, ctx_for(project__type="ecommerce")))
        for t in ("internal_tool", "realtime_collab", "web_app"):  # must not fire
            self.assertFalse(rec.limit_applies(self.SEO, ctx_for(project__type=t)), t)

    def test_no_scenario_nothing_is_filtered(self):
        self.assertTrue(rec.limit_applies(self.WS, None))
        self.assertTrue(rec.limit_applies(self.SEO, None))

    def test_outputs_drop_the_limits_when_off(self):
        for i in (2, 3, 4):  # P3, P4, P5: no SEO need
            tr = " | ".join(evaluate(PUBLIC[i], counterfactuals=False)["stack"]["frontend"]["tradeoffs"])
            self.assertNotIn("SEO", tr, PUBLIC[i]["scenario_id"])
        p6 = evaluate(PUBLIC[5], counterfactuals=False)  # P6 has no realtime
        self.assertFalse(any("WebSocket" in t for t in p6["stack"]["backend"]["tradeoffs"] + p6["stack"]["hosting"]["tradeoffs"]))

    def test_every_kb_item_keeps_a_limit_when_conditionals_are_off(self):
        ctx = ctx_for()
        for group in ("hosting", "frontend_web", "frontend_mobile", "backend", "database"):
            for item in TECH[group]:
                if item.get("limits"):
                    self.assertTrue(rec.live_limits(item, ctx), (group, item["id"]))

    def test_cloud_run_websocket_limit_is_its_own_line(self):
        cr = next(h for h in TECH["hosting"] if h["id"] == "gcp-cloud-run")
        self.assertTrue(any(x.startswith("WebSocket connections end") for x in cr["limits"]))
        self.assertFalse(any("WebSocket" in x and "long jobs" in x for x in cr["limits"]))


class OtpOfflineTradeoff(unittest.TestCase):
    def otp(self, **kw):
        return supporting(run(requirements__auth="phone_otp", infrastructure__data_residency="india", **kw), "auth")

    def test_offline_line_only_with_offline_support(self):
        for t in ("ecommerce", "web_app", "marketplace"):
            self.assertFalse(any("valid offline" in x for x in self.otp(project__type=t)["tradeoffs"]), t)
        a = self.otp(project__type="other", project__platforms=["android"], requirements__offline_support=True)
        self.assertTrue(any("valid offline" in x for x in a["tradeoffs"]))
        self.assertTrue(any("needs network at login" in x for x in a["tradeoffs"]))


class PaymentFeeText(unittest.TestCase):
    def fee(self, **kw):
        return next(x for x in supporting_all(run(requirements__payments=True, **kw), "payments")[0]["tradeoffs"] if "Per-transaction" in x)

    def test_region_neutral_outside_india(self):
        for t, res in (("ecommerce", "eu"), ("marketplace", "us"), ("web_app", "eu")):
            fee = self.fee(project__type=t, infrastructure__data_residency=res)
            self.assertNotIn("domestic cards", fee)
            self.assertIn("set by the gateway's price list for your country", fee)

    def test_india_names_its_source(self):
        fee = self.fee(project__type="ecommerce", infrastructure__data_residency="india")
        self.assertIn("2% on domestic cards at Razorpay's standard pricing", fee)


def supporting_all(out, layer):
    return [s for s in out["stack"]["supporting"] if s["layer"] == layer]


class RbiBackupText(unittest.TestCase):
    def test_copies_stay_in_india(self):
        for cloud, second in (("aws", "ap-south-2"), ("azure", "South India"), ("gcp", "asia-south2")):
            out = run(project__type="fintech", compliance=["rbi_localisation"], infrastructure__cloud_preference=cloud,
                      requirements__payments=True, requirements__auth="phone_otp")
            j = out["stack"]["database"]["justification"]
            self.assertNotIn("no cross-region copies", j, cloud)
            self.assertIn("stay in India, in ", j, cloud)
            self.assertIn("storage only in India", j, cloud)
            self.assertNotIn("((", j, cloud)
            self.assertNotIn("))", j.replace("(Mumbai))", ""), cloud)
            self.assertIn(second, j, cloud)

    def test_not_fired_without_rbi(self):
        j = run(project__type="fintech", infrastructure__cloud_preference="aws")["stack"]["database"]["justification"]
        self.assertNotIn("RBI localisation", j)


class VendorFactsAreTrue(unittest.TestCase):
    def test_auth0_alternative_does_not_claim_data_leaves_the_region(self):
        for res in ("eu", "us"):
            a = supporting(run(requirements__auth="social", team__languages=["go"], infrastructure__data_residency=res), "auth")
            txt = " ".join(x["why_not"] for x in a["alternatives"])
            self.assertNotIn("identity data outside", txt, res)
        out = evaluate(PUBLIC[2], counterfactuals=False)  # P3: gdpr, Keycloak
        txt = " ".join(x["why_not"] for x in supporting(out, "auth")["alternatives"])
        self.assertIn("a second vendor holding identity data", txt)

    def test_firestore_alternative_is_not_called_global(self):
        out = evaluate(PUBLIC[5], counterfactuals=False)
        alts = [x["why_not"] for s in out["stack"]["supporting"] for x in s["alternatives"] if "Firestore" in x["choice"]]
        self.assertTrue(alts)
        for t in alts:
            self.assertNotIn("global service", t)

    def test_sveltekit_text_is_not_a_false_runtime_claim(self):
        out = evaluate(PUBLIC[0], counterfactuals=False)
        txt = " ".join(a["why_not"] for a in out["stack"]["frontend"]["alternatives"])
        self.assertNotIn("needs a server runtime for a site that does not", txt.lower())

    def test_azure_cache_does_not_argue_valkey_licence(self):
        out = evaluate(PUBLIC[2], counterfactuals=False)
        cache = supporting(out, "cache")
        self.assertIn("Azure Managed Redis", cache["choice"])
        self.assertNotIn("BSD", " ".join(a["why_not"] for a in cache["alternatives"]))

    def test_valkey_licence_kept_where_valkey_is_chosen(self):
        out = evaluate(PUBLIC[3], counterfactuals=False)  # P4: ElastiCache for Valkey
        cache = supporting(out, "cache")
        self.assertIn("Valkey", cache["choice"])
        self.assertIn("BSD", " ".join(a["why_not"] for a in cache["alternatives"]))

    def test_angular_support_text_matches_the_source(self):
        ang = next(f for f in TECH["frontend_web"] if f["id"] == "angular")
        self.assertIn("24 months", " ".join(ang["limits"]))
        self.assertIn("v20", " ".join(ang["limits"]))
        self.assertIn("12 active + 12 LTS", SOURCES["angular-releases"]["title"])

    def test_vendor_term_cites_the_pinning_input(self):
        out = evaluate(PUBLIC[2])  # data_residency none, region EU from gdpr
        t = out["stack"]["database"]["contrast"]
        self.assertIn("compliance=gdpr", t)
        self.assertNotIn("data_residency=none", t)


class BudgetWarningNamesItemsApart(unittest.TestCase):
    def test_cognito_mau_and_sms_are_separate_items(self):
        out = evaluate(PUBLIC[3], counterfactuals=False)
        msg = next(w["message"] for w in out["warnings"] if w["code"] == "BUDGET_AT_RISK")
        self.assertIn("Phone OTP SMS fees", msg)
        self.assertIn("Amazon Cognito monthly-active-user charges", msg)
        self.assertNotIn("Amazon SNS SMS OTP in", msg)


class ExistingDatabaseHint(unittest.TestCase):
    def test_no_write_keep_instruction_leaks(self):
        out = evaluate(PUBLIC[4], counterfactuals=False)  # P5
        j = next(s["justification"] for s in out["stack"]["supporting"] if "ntegration with existing" in s["choice"])
        self.assertNotIn("write 'keep'", j)
        self.assertIn("say so in infrastructure.existing_systems", j)


if __name__ == "__main__":
    unittest.main()
