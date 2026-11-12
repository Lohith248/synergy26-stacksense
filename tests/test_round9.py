"""Round 9 (12 Nov session): existing-system reuse (DB / identity provider / message broker), FREE_TIER_LIMITS,
description cap, list-order invariance, API-only summary wording, phone_otp provider by residency.
Each test written before the change."""
import copy
import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
    _PUB = json.load(f)
PUBLIC = {s["scenario_id"]: s for s in (_PUB if isinstance(_PUB, list) else _PUB.get("scenarios", _PUB))}

BASE = {"scenario_id": "R9", "project": {"type": "web_app", "platforms": ["web"], "description": ""},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "intermediate", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 2000}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none",
                           "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def S(**kw):
    s = copy.deepcopy(BASE)
    for path, v in kw.items():
        node, parts = s, path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return s


def run(**kw):
    return evaluate(S(**kw), counterfactuals=False)


def codes(out):
    return [w["code"] for w in out["warnings"]]


def sup(out, layer):
    return [s for s in out["stack"]["supporting"] if s["layer"] == layer]


def dump(out):
    return json.dumps(out, indent=2, ensure_ascii=False)


class ExistingDatabaseKept(unittest.TestCase):
    def test_oracle_system_of_record_is_the_database(self):
        out = run(**{"infrastructure.existing_systems": ["Oracle Database 11g (must remain system of record)"],
                     "team.languages": ["java", "sql"]})
        db = out["stack"]["database"]
        self.assertIn("Oracle", db["choice"])
        self.assertIn("existing", db["choice"].lower())
        self.assertIn("reused", db["choice"].lower())
        self.assertIn("infrastructure.existing_systems", db["driven_by"])
        self.assertTrue(any("migrat" in (a["choice"] + a["why_not"]).lower() for a in db["alternatives"]))
        self.assertIn("END_OF_LIFE_SYSTEM", codes(out))  # lifecycle warning kept
        self.assertFalse(any("Oracle" in s["choice"] and s["layer"] == "other" for s in out["stack"]["supporting"]))

    def test_keep_phrase_in_description_sentence(self):
        out = run(**{"infrastructure.existing_systems": ["PostgreSQL 16 cluster"],
                     "project.description": "Order tracking. The existing PostgreSQL cluster must remain the source of truth for orders."})
        db = out["stack"]["database"]
        self.assertIn("PostgreSQL", db["choice"])
        self.assertIn("reused", db["choice"].lower())

    def test_self_managed_mongo_stays_self_managed(self):
        out = run(**{"infrastructure.existing_systems": ["MongoDB 6 replica set (must stay)"],
                     "infrastructure.cloud_preference": "aws"})
        db = out["stack"]["database"]
        self.assertIn("MongoDB", db["choice"])
        self.assertNotIn("Atlas", db["choice"])
        self.assertEqual(db["deployment"], "self_hosted")
        self.assertIn("END_OF_LIFE_SYSTEM", codes(out))

    def test_existing_db_without_keep_words_is_integrated_not_reused(self):
        out = run(**{"infrastructure.existing_systems": ["Oracle Database 19c"]})
        self.assertNotIn("reused", out["stack"]["database"]["choice"].lower())
        self.assertTrue(any("Oracle" in s["choice"] for s in sup(out, "other")))

    def test_keep_word_in_other_sentence_does_not_count(self):
        out = run(**{"infrastructure.existing_systems": ["SQL Server 2016 back-office database"],
                     "project.description": "Tills must keep taking payments offline. Existing back office runs SQL Server 2016."})
        self.assertNotIn("reused", out["stack"]["database"]["choice"].lower())

    def test_reused_db_cost_not_in_band(self):
        out = run(**{"infrastructure.existing_systems": ["Oracle Database 19c (system of record)"]})
        lines = out["estimated_monthly_cost_usd"]["assumptions"]
        self.assertTrue(any("existing" in x.lower() and "oracle" in x.lower() for x in lines), lines)


class ExistingIdentityProvider(unittest.TestCase):
    def test_saas_and_self_hosted_idps_are_reused(self):
        for raw, name in [("Okta (workforce and customer SSO)", "Okta"), ("Auth0 tenant", "Auth0"),
                          ("Keycloak 24 realm", "Keycloak"), ("Ping Identity (PingFederate)", "Ping"),
                          ("Google Workspace (SSO / directory)", "Google Workspace")]:
            with self.subTest(raw=raw):
                out = run(**{"infrastructure.existing_systems": [raw], "requirements.auth": "enterprise_sso"})
                auth = sup(out, "auth")
                self.assertEqual(len(auth), 1)
                self.assertIn(name, auth[0]["choice"])
                self.assertIn("existing", auth[0]["choice"].lower())
                self.assertNotIn("Entra", auth[0]["choice"])
                self.assertIn("infrastructure.existing_systems", auth[0]["driven_by"])
                self.assertNotIn("EXISTING_SYSTEM_UNRECOGNISED", codes(out))

    def test_okta_gets_no_microsoft_extras(self):
        out = run(**{"infrastructure.existing_systems": ["Okta"], "requirements.auth": "enterprise_sso",
                     "project.description": "Approval workflow for purchase requests.", "team.languages": ["csharp"]})
        text = dump(out)
        self.assertNotIn("Microsoft Graph", text)
        self.assertNotIn("Microsoft.Identity.Web", text)

    def test_ping_is_a_word_not_a_substring(self):
        out = run(**{"infrastructure.existing_systems": ["Shopping cart service"], "requirements.auth": "enterprise_sso"})
        self.assertNotIn("existing", sup(out, "auth")[0]["choice"].lower())

    def test_p5_entra_unchanged(self):
        out = evaluate(copy.deepcopy(PUBLIC["P5"]), counterfactuals=False)
        self.assertEqual(sup(out, "auth")[0]["choice"], "Microsoft Entra ID (existing tenant) via OpenID Connect")


class ExistingBroker(unittest.TestCase):
    def test_kafka_reused_no_competing_broker(self):
        out = run(**{"infrastructure.existing_systems": ["Apache Kafka cluster (self-managed, 3 brokers)"],
                     "infrastructure.cloud_preference": "aws", "scale.workload": "write_heavy",
                     "scale.users_12_months": 200000, "scale.peak_concurrent_users": 5000})
        q = sup(out, "queue")
        self.assertEqual(len(q), 1)
        self.assertIn("Kafka", q[0]["choice"])
        self.assertNotIn("SQS", q[0]["choice"])
        self.assertIn("infrastructure.existing_systems", q[0]["driven_by"])
        self.assertNotIn("EXISTING_SYSTEM_UNRECOGNISED", codes(out))

    def test_rabbitmq_reused_even_without_queue_need(self):
        out = run(**{"infrastructure.existing_systems": ["RabbitMQ 3.13 (must stay)"]})
        q = sup(out, "queue")
        self.assertEqual(len(q), 1)
        self.assertIn("RabbitMQ", q[0]["choice"])
        self.assertNotIn("EXISTING_SYSTEM_UNRECOGNISED", codes(out))


class ExistingAppLanguage(unittest.TestCase):
    def test_existing_java_app_credits_jvm_backend(self):
        s = S(**{"infrastructure.existing_systems": ["Java 8 application on Tomcat 7"], "team.languages": ["java", "javascript"]})
        from engine.validate import validate
        from engine import context as cx, select as sl
        req, _, _ = validate(s)
        c = cx.build(req)
        c["ui_needs_js"] = True
        terms = {b.id: b.term("existing_lang") for b in sl.backend_candidates(c, None)}
        self.assertGreater(terms["java-spring"], 0)
        self.assertEqual(terms["node-nestjs"], 0)

    def test_frontend_framework_is_not_a_backend_language(self):
        from engine import context as cx
        self.assertEqual(cx.existing_langs(["AngularJS 1.x frontend", "Oracle Database 11g"]), set())
        self.assertEqual(cx.existing_langs(["Legacy PHP 7 monolith", "Django 3 admin"]), {"php", "python"})


class FreeTier(unittest.TestCase):
    def test_p1_zero_budget_free_tier_limits(self):
        out = evaluate(copy.deepcopy(PUBLIC["P1"]), counterfactuals=False)
        c = out["estimated_monthly_cost_usd"]
        self.assertEqual(c["min"], 0)
        self.assertGreater(c["max"], 0)
        w = next(w for w in out["warnings"] if w["code"] == "FREE_TIER_LIMITS")
        self.assertEqual(w["severity"], "info")
        self.assertEqual(out["status"], "ok")

    def test_paid_budget_has_no_free_tier_warning(self):
        self.assertNotIn("FREE_TIER_LIMITS", codes(run()))


class DescriptionCap(unittest.TestCase):
    def test_huge_description_is_fast_and_truncated(self):
        desc = ("Inventory app for small shops. " * 70000)[:2_000_000]
        t = time.time()
        out = evaluate(S(**{"project.description": desc}))
        self.assertLess(time.time() - t, 5)
        w = next(w for w in out["warnings"] if w["code"] == "DESCRIPTION_TRUNCATED")
        self.assertEqual(w["severity"], "info")
        self.assertTrue(any("20,000" in a for a in out["assumptions"]))

    def test_keywords_after_cap_are_ignored(self):
        desc = "x" * 20000 + " double-entry ledger"
        out = run(**{"project.description": desc})
        self.assertFalse(any("ledger" in s["choice"].lower() for s in out["stack"]["supporting"]))
        self.assertIn("DESCRIPTION_TRUNCATED", codes(out))

    def test_at_cap_not_truncated(self):
        self.assertNotIn("DESCRIPTION_TRUNCATED", codes(run(**{"project.description": "y" * 20000})))


LIST_PATHS = [("project", "platforms"), ("team", "languages"), ("team", "hiring_languages"), ("compliance",),
              ("infrastructure", "existing_systems")]


def _get(s, path):
    n = s
    for k in path:
        n = n.get(k) if isinstance(n, dict) else None
    return n


def _set(s, path, v):
    n = s
    for k in path[:-1]:
        n = n[k]
    n[path[-1]] = v


class ListOrderInvariance(unittest.TestCase):
    def check(self, s):
        base = dump(evaluate(copy.deepcopy(s)))
        for path in LIST_PATHS:
            v = _get(s, path)
            if not isinstance(v, list) or len(v) < 2:
                continue
            for perm in (v[::-1], v[1:] + v[:1]):
                s2 = copy.deepcopy(s)
                _set(s2, path, list(perm))
                with self.subTest(sid=s.get("scenario_id"), path=".".join(path), perm=perm):
                    self.assertEqual(dump(evaluate(s2)), base)

    def test_public_scenarios(self):
        for sid in sorted(PUBLIC):
            self.check(PUBLIC[sid])

    def test_p4_platforms_named_case(self):
        a = copy.deepcopy(PUBLIC["P4"])
        b = copy.deepcopy(PUBLIC["P4"])
        a["project"]["platforms"] = ["web", "android", "ios"]
        b["project"]["platforms"] = ["android", "ios", "web"]
        self.assertEqual(dump(evaluate(a)), dump(evaluate(b)))

    def test_mixed_existing_and_hiring(self):
        s = S(**{"infrastructure.existing_systems": ["Okta", "Apache Kafka", "On-prem SQL Server 2019", "SAP S/4HANA", "Mystery CRM"],
                 "team.hiring_languages": ["go", "python"], "compliance": ["soc2", "gdpr", "iso27001"],
                 "requirements.auth": "enterprise_sso", "project.platforms": ["web", "ios", "android"]})
        self.check(s)


class ApiOnlySummary(unittest.TestCase):
    def test_no_none_frontend_in_summary(self):
        out = run(**{"project.type": "api_platform", "project.platforms": ["api_only"], "team.languages": ["rust"]})
        self.assertEqual(out["stack"]["frontend"]["choice"], "None")
        self.assertNotIn(": None", out["summary"])
        self.assertNotIn("None on", out["summary"])
        self.assertIn(out["stack"]["backend"]["choice"], out["summary"])


class PhoneOtpByResidency(unittest.TestCase):
    INDIA_WORDS = ("MSG91", "DLT", "TRAI", "India SMS", "Rs 0.")

    def cases(self):
        for res, extra in [("india", {}), ("eu", {}), ("us", {}), ("none", {}),
                           ("other", {"infrastructure.residency_country": "japan"}),
                           ("none", {"compliance": ["dpdp"]})]:
            for cloud, dep in [("any", "managed_cloud"), ("aws", "managed_cloud"), ("none", "on_premise"), ("none", "air_gapped")]:
                kw = {"requirements.auth": "phone_otp", "infrastructure.data_residency": res,
                      "infrastructure.cloud_preference": cloud, "infrastructure.deployment_model": dep}
                kw.update(extra)
                india = res == "india" or "compliance" in extra
                yield kw, india

    def test_india_only_text(self):
        for kw, india in self.cases():
            out = run(**kw)
            if not out["stack"]:
                continue
            text = dump(out)
            with self.subTest(**{k.split(".")[-1]: str(v) for k, v in kw.items()}):
                if india and kw["infrastructure.deployment_model"] != "air_gapped":
                    self.assertTrue(any(w in text for w in ("MSG91", "DLT")))
                elif not india:
                    for w in self.INDIA_WORDS:
                        self.assertNotIn(w, text)

    def test_outside_india_generic_provider(self):
        for res in ("eu", "us", "none"):
            out = run(**{"requirements.auth": "phone_otp", "infrastructure.data_residency": res})
            self.assertIn("Twilio Verify", sup(out, "auth")[0]["choice"])


if __name__ == "__main__":
    unittest.main()
