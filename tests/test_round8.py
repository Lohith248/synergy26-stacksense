"""Round 8 (12 Nov session): data_residency 'other' resolved to a named jurisdiction (D12, R15 region list).
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
from engine.context import detect_country  # noqa: E402
from check_contract import check  # noqa: E402

BASE = {"scenario_id": "R8", "project": {"type": "web_app", "platforms": ["web"]},
        "scale": {"users_at_launch": 500, "users_12_months": 5000},
        "team": {"size": 3, "experience": "intermediate", "languages": ["python"]},
        "budget": {"monthly_infra_usd": 400}, "timeline": {"mvp_weeks": 10},
        "infrastructure": {"data_residency": "other"},
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
    out = evaluate(S(**kw), counterfactuals=False)
    return out


def warn(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


def data_layers(out):
    st = out["stack"]
    return [st["database"], st["hosting"]] + [s for s in st["supporting"] if s.get("data_bearing")]


class Detection(unittest.TestCase):
    def test_keywords(self):
        self.assertEqual(detect_country("API sold to Australian marine operators")[0], "australia")
        self.assertEqual(detect_country("Shops in Dubai and Abu Dhabi")[0], "uae")
        self.assertEqual(detect_country("Patients across the U.K.")[0], "united_kingdom")
        self.assertEqual(detect_country("Clinics in Seoul")[0], "south_korea")

    def test_collisions(self):
        self.assertIsNone(detect_country("Ranchers in New Mexico and Arizona")[0])
        self.assertIsNone(detect_country("Customers in the EU only")[0])
        self.assertIsNone(detect_country("Sanctions screening for North Korea exposure")[0])
        self.assertIsNone(detect_country("Sold in SA and nearby markets")[0])
        self.assertIsNone(detect_country("A tide, swell and sea-state API")[0])
        self.assertIsNone(detect_country("Students in New England colleges")[0])
        self.assertIsNone(detect_country("Clinics in New South Wales")[0])
        self.assertEqual(detect_country("Clinics in New South Wales and Sydney")[0], "australia")

    def test_ambiguous_and_several(self):
        cid, word, plaus = detect_country("Gulf customers")
        self.assertIsNone(cid)
        self.assertIn("uae", plaus)
        self.assertIn("saudi_arabia", plaus)
        cid, word, plaus = detect_country("Selling in the UAE and Saudi Arabia")
        self.assertIsNone(cid)
        self.assertEqual(set(plaus), {"uae", "saudi_arabia"})


class FromDescription(unittest.TestCase):
    def test_b04_like_australia_any_cloud(self):
        out = run(**{"project.description": "REST API sold to Australian marine operators; data stored in Australia.",
                     "project.type": "api_platform", "project.platforms": ["api_only"],
                     "team.languages": ["rust"], "team.experience": "senior", "team.has_devops": True,
                     "budget.monthly_infra_usd": 700, "requirements.auth": "none"})
        self.assertEqual(check(out), [])
        self.assertIsNone(warn(out, "RESIDENCY_UNSPECIFIED"))
        w = warn(out, "RESIDENCY_FROM_DESCRIPTION")
        self.assertEqual(w["severity"], "warning")
        self.assertIn("Australia", w["message"])
        # round 14 (participant decision D12a): the residency sentence is cited, not the first matched place word
        self.assertIn('"data stored in Australia."', w["message"])
        self.assertIn("infrastructure.residency_country", w["message"])
        self.assertIn("project.description", w["fields"])
        for c in (out["stack"]["database"], out["stack"]["hosting"]):
            self.assertTrue(any(k in c["choice"] for k in ("Sydney", "Australia East", "australia-southeast1")), c["choice"])
            self.assertIn("infrastructure.data_residency", c["driven_by"])
        self.assertIn("project.description", out["stack"]["hosting"]["driven_by"])
        self.assertTrue(any("Australia" in a and "project.description" in a for a in out["assumptions"]))

    def test_ambiguous_gulf_stays_critical(self):
        out = run(**{"project.description": "Online store for Gulf customers; data must stay in the region."})
        w = warn(out, "RESIDENCY_UNSPECIFIED")
        self.assertEqual(w["severity"], "critical")
        self.assertTrue(w["message"].startswith("data_residency 'other' does not name a jurisdiction; regions could not be verified."))
        self.assertIn("UAE", w["message"])
        self.assertIn("infrastructure.residency_country", w["message"])

    def test_no_keyword_message_unchanged(self):
        out = run(**{"project.description": "A booking tool."})
        self.assertEqual(warn(out, "RESIDENCY_UNSPECIFIED")["message"],
                         "data_residency 'other' does not name a jurisdiction; regions could not be verified. State the country so every data store can be pinned.")

    def test_new_mexico_does_not_pick_mexico(self):
        out = run(**{"project.description": "Water-rights records for ranchers in New Mexico."})
        self.assertEqual(warn(out, "RESIDENCY_UNSPECIFIED")["severity"], "critical")
        self.assertNotIn("Mexico Central", json.dumps(out["stack"]))


class ExplicitCountry(unittest.TestCase):
    def test_uae_gcp_infeasible(self):
        out = run(**{"infrastructure.residency_country": "uae", "infrastructure.cloud_preference": "gcp"})
        self.assertEqual(out["status"], "infeasible")
        self.assertIsNone(out["stack"])
        w = next(w for w in out["warnings"] if w["severity"] == "critical")
        self.assertIn("UAE", w["message"])
        self.assertIn("infrastructure.residency_country", w["fields"])
        self.assertIn("infrastructure.cloud_preference", w["fields"])
        self.assertEqual(check(out), [])

    def test_saudi_aws_infeasible_and_any_excludes_aws(self):
        out = run(**{"infrastructure.residency_country": "saudi_arabia", "infrastructure.cloud_preference": "aws"})
        self.assertEqual(out["status"], "infeasible")
        self.assertIn("Saudi Arabia", " ".join(w["message"] for w in out["warnings"]))
        out = run(**{"infrastructure.residency_country": "saudi_arabia"})
        self.assertEqual(check(out), [])
        self.assertIn("Dammam", out["stack"]["hosting"]["choice"])
        alts = json.dumps(out["stack"]["hosting"]["alternatives"])
        self.assertIn("Saudi Arabia", alts)
        info = warn(out, "RESIDENCY_COUNTRY")
        self.assertEqual(info["severity"], "info")
        self.assertIn("infrastructure.residency_country", out["stack"]["hosting"]["driven_by"])

    def test_supabase_excluded_where_none(self):
        # tiny budget would normally pick Supabase; Supabase has no Indonesia region (R15)
        out = run(**{"infrastructure.residency_country": "indonesia", "budget.monthly_infra_usd": 10})
        self.assertNotIn("Supabase", out["stack"]["database"]["choice"])
        # round 13: an excluded option is listed only when fewer than two eligible alternatives exist
        alts = out["stack"]["database"]["alternatives"]
        sb = [a for a in alts if "Supabase" in a["choice"]]
        self.assertTrue(all("Indonesia" in a["why_not"] for a in sb), alts)
        self.assertTrue(sb or len([a for a in alts if not a["why_not"].startswith("Excluded")]) >= 2, alts)

    def test_supabase_kept_where_listed(self):
        out = run(**{"infrastructure.residency_country": "japan", "budget.monthly_infra_usd": 10})
        for c in data_layers(out)[:2]:
            self.assertTrue(any(k in c["choice"] for k in ("Tokyo", "Japan East", "asia-northeast1")), c["choice"])

    def test_country_ignored_with_other_residency(self):
        out = run(**{"infrastructure.data_residency": "india", "infrastructure.residency_country": "japan"})
        w = warn(out, "RESIDENCY_COUNTRY_IGNORED")
        self.assertEqual(w["severity"], "warning")
        self.assertIn("india", w["message"])
        self.assertIn("japan", w["message"])
        h = out["stack"]["hosting"]["choice"]
        self.assertTrue(any(k in h for k in ("Mumbai", "Pune")), h)
        self.assertNotIn("Tokyo", json.dumps(out["stack"]))

    def test_invalid_country_is_validation_error(self):
        out = run(**{"infrastructure.residency_country": "atlantis"})
        self.assertEqual(out["status"], "invalid_input")

    def test_second_region_only_when_listed(self):
        out = run(**{"infrastructure.residency_country": "japan", "infrastructure.cloud_preference": "aws",
                     "requirements.availability": "99.99", "budget.monthly_infra_usd": 3000})
        self.assertIn("Osaka", json.dumps(out["stack"]["supporting"]))
        out = run(**{"infrastructure.residency_country": "singapore", "infrastructure.cloud_preference": "aws",
                     "requirements.availability": "99.99", "budget.monthly_infra_usd": 3000})
        self.assertFalse(any(s["choice"].startswith("Second-region") for s in out["stack"]["supporting"]))
        w = warn(out, "AVAILABILITY_SINGLE_REGION")
        self.assertIn("Singapore", w["message"])
        self.assertEqual(check(out), [])

    def test_payments_no_india_gateway(self):
        out = run(**{"infrastructure.residency_country": "brazil", "requirements.payments": True,
                     "project.type": "ecommerce"})
        pay = next(s for s in out["stack"]["supporting"] if s["layer"] == "payments")
        self.assertNotIn("Razorpay", pay["choice"])
        self.assertIsNotNone(warn(out, "PAYMENT_LOCAL_ACQUIRING"))
        self.assertEqual(check(out), [])


if __name__ == "__main__":
    unittest.main()
