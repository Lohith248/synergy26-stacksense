"""Round 14 (12 Nov session): D12a narrower residency rule, D6 message wording, F13 multi-continent low-latency.
Each test written before the change."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from engine.run import evaluate  # noqa: E402
from engine.context import residency_from_description  # noqa: E402
from check_contract import check  # noqa: E402

BASE = {"scenario_id": "R14", "project": {"type": "web_app", "platforms": ["web"]},
        "scale": {"users_at_launch": 500, "users_12_months": 5000},
        "team": {"size": 3, "experience": "intermediate", "languages": ["python"]},
        "budget": {"monthly_infra_usd": 400}, "timeline": {"mvp_weeks": 10},
        "infrastructure": {"data_residency": "other"},
        "requirements": {"auth": "email_password"}}
C14 = os.path.join(ROOT, "..", "research", "blind4", "C14_QuoteEdge.json")


def S(base=BASE, **kw):
    s = copy.deepcopy(base)
    for path, v in kw.items():
        node, parts = s, path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return s


def run(base=BASE, **kw):
    return evaluate(S(base, **kw), counterfactuals=False)


def warn(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


def everything(out):
    return json.dumps(out, ensure_ascii=False)


class D12aSentence(unittest.TestCase):
    def test_unit(self):
        r = residency_from_description("Inventory tool. Customer data and backups must stay in Canada.")
        self.assertEqual((r["country"], r["sentence"]), ("canada", "Customer data and backups must stay in Canada."))
        r = residency_from_description("Our team is based in Toronto.")
        self.assertIsNone(r["country"])
        self.assertEqual(r["hints"], ["canada"])
        r = residency_from_description("Public tide API sold to Australian marine operators. Customer contracts require data to be stored in Australia.")
        self.assertEqual(r["country"], "australia")

    def test_explicit_sentence_pins_and_is_cited(self):
        sent = "Customer data and backups must stay in Canada."
        out = run(**{"project.description": "Inventory tool for hardware stores. " + sent})
        self.assertIsNone(warn(out, "RESIDENCY_UNSPECIFIED"))
        self.assertIn("Canada", out["stack"]["hosting"]["choice"] + out["stack"]["hosting"].get("region", "") + everything(out["stack"]["hosting"]))
        cited = [a for a in out["assumptions"] if sent in a] + [w["message"] for w in out["warnings"] if sent in w["message"]]
        self.assertTrue(cited, out["assumptions"])
        self.assertTrue(any("resolved to Canada from the description" in t for t in cited), cited)
        self.assertEqual(check(out), [])

    def test_mention_is_hint_only(self):
        out = run(**{"project.description": "Booking tool for clinics. Our team is based in Toronto."})
        w = warn(out, "RESIDENCY_UNSPECIFIED")
        self.assertEqual(w["severity"], "critical")
        self.assertIn("Canada", w["message"])
        self.assertNotIn("Canada", out["stack"]["hosting"]["choice"])
        self.assertNotIn("Toronto", json.dumps(out["stack"]["database"]))

    def test_market_mention_and_gulf_region(self):
        out = run(**{"project.description": "Online store selling in the UAE and Saudi Arabia. Local regulations require "
                                            "customer and order data to stay in the Gulf region."})
        w = warn(out, "RESIDENCY_UNSPECIFIED")
        self.assertEqual(w["severity"], "critical")
        self.assertIn("UAE", w["message"])
        self.assertIn("Saudi Arabia", w["message"])

    def test_two_countries_in_one_sentence(self):
        out = run(**{"project.description": "Records must be stored in Canada or Australia."})
        w = warn(out, "RESIDENCY_UNSPECIFIED")
        self.assertEqual(w["severity"], "critical")
        self.assertIn("Canada", w["message"])
        self.assertIn("Australia", w["message"])

    def test_conflicting_sentences(self):
        out = run(**{"project.description": "Customer data must stay in Canada. Backups must be stored in Australia."})
        w = warn(out, "RESIDENCY_UNSPECIFIED")
        self.assertEqual(w["severity"], "critical")
        self.assertIn("Canada", w["message"])
        self.assertIn("Australia", w["message"])

    def test_field_conflicts_with_sentence(self):
        out = run(**{"project.description": "Customer data must stay in Canada.", "infrastructure.residency_country": "japan"})
        w = warn(out, "RESIDENCY_UNSPECIFIED")
        self.assertEqual(w["severity"], "critical")
        self.assertIn("Japan", w["message"])
        self.assertIn("Canada", w["message"])
        self.assertIn("infrastructure.residency_country", w["fields"])
        self.assertNotIn("Tokyo", json.dumps(out["stack"]["hosting"]))

    def test_field_agrees_with_sentence(self):
        out = run(**{"project.description": "Customer data must stay in Japan.", "infrastructure.residency_country": "japan"})
        self.assertIsNone(warn(out, "RESIDENCY_UNSPECIFIED"))
        self.assertIsNotNone(warn(out, "RESIDENCY_COUNTRY"))

    def test_clear_country_no_provider_region(self):
        out = run(**{"project.description": "Customer data must stay in Saudi Arabia.", "infrastructure.cloud_preference": "aws"})
        self.assertEqual(out["status"], "infeasible")
        w = warn(out, "RESIDENCY_NO_PROVIDER_REGION")
        self.assertIn("Saudi Arabia", w["message"])
        self.assertIn("AWS", w["message"])
        self.assertIn("'any'", w["message"])
        self.assertEqual(check(out), [])


class D6Message(unittest.TestCase):
    def test_reworded(self):
        out = run(**{"infrastructure.data_residency": "none", "infrastructure.cloud_preference": "none",
                     "infrastructure.deployment_model": "managed_cloud"})
        self.assertEqual(out["status"], "infeasible")
        self.assertEqual(warn(out, "CLOUD_NONE_VS_CLOUD_DEPLOYMENT")["message"],
                         "cloud_preference 'none' means no public cloud and contradicts deployment_model 'managed_cloud', which runs on a "
                         "public cloud. To resolve: choose cloud_preference 'any' if public cloud is acceptable, or a deployment_model that "
                         "keeps the stack on your own infrastructure ('on_premise' or 'air_gapped').")


class F13MultiContinent(unittest.TestCase):
    def setUp(self):
        with open(C14, encoding="utf-8") as f:
            self.c14 = json.load(f)

    def test_c14_active_active_with_cdn(self):
        out = evaluate(copy.deepcopy(self.c14), counterfactuals=False)
        self.assertIn(out["status"], ("ok", "ok_with_warnings"))
        sup = out["stack"]["supporting"]
        mr = [s for s in sup if s["choice"].startswith("Multi-region active-active")]
        self.assertEqual(len(mr), 1, [s["choice"] for s in sup])
        self.assertIn("Europe", mr[0]["choice"])
        self.assertIn("Asia", mr[0]["choice"])
        self.assertIn("requirements.p95_latency_ms", mr[0]["driven_by"])
        self.assertTrue(any(s["layer"] == "cdn" for s in sup), [s["choice"] for s in sup])
        self.assertFalse(any(s["choice"].startswith("Second-region warm standby") for s in sup))
        self.assertIn("Multi-region", json.dumps(out["estimated_monthly_cost_usd"]))
        self.assertEqual(check(out), [])

    def test_residency_pins_single_region_warns(self):
        s = copy.deepcopy(self.c14)
        s["infrastructure"]["data_residency"] = "eu"
        out = evaluate(s, counterfactuals=False)
        self.assertFalse(any(x["choice"].startswith("Multi-region") for x in out["stack"]["supporting"]))
        w = warn(out, "LATENCY_FAR_USERS")
        self.assertEqual(w["severity"], "warning")
        self.assertIn("30 ms", w["message"])
        self.assertEqual(check(out), [])

    def test_not_triggered_without_spread_or_tight_latency(self):
        s = copy.deepcopy(self.c14)
        s["requirements"]["p95_latency_ms"] = 80
        out = evaluate(s, counterfactuals=False)
        self.assertFalse(any(x["choice"].startswith("Multi-region") for x in out["stack"]["supporting"]))
        s = copy.deepcopy(self.c14)
        s["project"]["description"] = "Low-latency pricing and quote API for trading partners."
        out = evaluate(s, counterfactuals=False)
        self.assertFalse(any(x["choice"].startswith("Multi-region") for x in out["stack"]["supporting"]))
        s["scale"]["geo_spread"] = "global"
        out = evaluate(s, counterfactuals=False)
        self.assertTrue(any(x["choice"].startswith("Multi-region") for x in out["stack"]["supporting"]))



class D12aWithinIsNotResidency(unittest.TestCase):
    def test_time_or_office_within_is_hint(self):
        from engine.context import residency_from_description as r
        for t in ("Our Toronto team syncs data within minutes.", "Files are shared within the Canada sales office."):
            with self.subTest(t=t):
                self.assertIsNone(r(t)["country"])
        self.assertEqual(r("Customer data must stay within Canada.")["country"], "canada")

if __name__ == "__main__":
    unittest.main()
