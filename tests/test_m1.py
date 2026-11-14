"""M1: no 'strict ACID' reason against an ACID engine; KB limits tied to the item and the inputs; learning-curve reasons say why they matter;
the existing-database sentence; OTP and Cognito lines that recompute from their stated numbers; one price per stored volume; a security
supporting line for money-handling systems (planning heuristic). Each rule has several project types and a must-not-fire input."""
import copy
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import costreal  # noqa: E402
from engine.run import evaluate  # noqa: E402
import engine.recommend as rec  # noqa: E402
from test_j1 import ctx_for  # noqa: E402

BASE = {"scenario_id": "M1", "project": {"type": "web_app", "platforms": ["web"], "description": "A small web application."},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "senior", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 3000}, "timeline": {"mvp_weeks": 14},
        "priorities": {"cost": 3, "time_to_market": 3, "scalability": 3, "performance": 3, "maintainability": 3, "security": 3},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def run(**kw):
    s = copy.deepcopy(BASE)
    for path, v in kw.items():
        node, parts = s, path.replace("__", ".").split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return evaluate(s, counterfactuals=False)


def texts(out):
    st = out["stack"]
    for L in ("frontend", "backend", "database", "hosting"):
        for a in (st.get(L) or {}).get("alternatives", []):
            yield a["why_not"]


def lines(out):
    return out["estimated_monthly_cost_usd"]["assumptions"]


def line(out, start):
    return next((l for l in lines(out) if l.startswith(start)), None)


def sec(out):
    return [s for s in out["stack"]["supporting"] if s["layer"] == "other" and any(k in s["choice"] for k in ("WAF", "Cloud Armor"))]


MONEY = dict(requirements__payments=True)


class SecurityLine(unittest.TestCase):
    def test_fires_on_each_hyperscaler(self):
        for cloud, word in (("aws", "AWS WAF"), ("azure", "Front Door WAF"), ("gcp", "Cloud Armor")):
            for typ in ("fintech", "marketplace"):
                with self.subTest(cloud=cloud, typ=typ):
                    out = run(project__type=typ, infrastructure__cloud_preference=cloud, priorities__security=5, **MONEY)
                    s = sec(out)
                    self.assertEqual(len(s), 1, [x["choice"] for x in out["stack"]["supporting"]])
                    self.assertIn(word, s[0]["choice"])
                    self.assertIn("priorities.security=5", s[0]["justification"])
                    self.assertIn("planning estimate", s[0]["justification"])
                    self.assertTrue(line(out, "other: " + s[0]["choice"].split(" + ")[0]) or any(word in l for l in lines(out)))

    def test_compliance_alone_fires_with_low_security_priority(self):
        for comp in ("pci_dss", "iso27001"):
            with self.subTest(comp=comp):
                out = run(project__type="ecommerce", infrastructure__cloud_preference="aws", priorities__security=2, compliance=[comp], **MONEY)
                self.assertEqual(len(sec(out)), 1)
                self.assertIn(comp, sec(out)[0]["justification"])

    def test_must_not_fire(self):
        cases = [dict(project__type="marketplace", infrastructure__cloud_preference="aws", priorities__security=3, **MONEY),   # money, low priority
                 dict(project__type="web_app", infrastructure__cloud_preference="aws", priorities__security=5),                 # no money
                 dict(project__type="fintech", infrastructure__cloud_preference="aws", priorities__security=5,
                      infrastructure__deployment_model="self_hosted_cloud_vm", **MONEY)]                                        # no hyperscaler service
        for kw in cases:
            with self.subTest(kw=kw):
                self.assertEqual(sec(run(**kw)), [])

    def test_band_equals_lines(self):
        out = run(project__type="fintech", infrastructure__cloud_preference="azure", priorities__security=5, **MONEY)
        lo = hi = 0
        for l in lines(out):
            m = re.search(r"\$([\d,]+)-([\d,]+)/month", l)
            if m:
                lo += int(m.group(1).replace(",", ""))
                hi += int(m.group(2).replace(",", ""))
        self.assertLessEqual(abs(lo - out["estimated_monthly_cost_usd"]["min"]), 1)
        self.assertLessEqual(abs(hi - out["estimated_monthly_cost_usd"]["max"]), 1)


class AcidReason(unittest.TestCase):
    def test_no_strict_acid_claim_against_mysql(self):
        for typ in ("marketplace", "fintech", "ecommerce"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, priorities__cost=4, **MONEY)
                for a in out["stack"]["database"]["alternatives"]:
                    if "MySQL" in a["choice"]:
                        self.assertNotIn("strict ACID", a["why_not"])

    def test_still_cites_acid_against_a_non_acid_store(self):
        out = run(project__type="fintech", **MONEY)
        dyn = [a["why_not"] for a in out["stack"]["database"]["alternatives"] if "DynamoDB" in a["choice"] or "Cosmos" in a["choice"] or "Firestore" in a["choice"]]
        self.assertTrue(all("ACID" in w for w in dyn if "fits better" in w))


class LimitTails(unittest.TestCase):
    def test_mysql_limit_is_about_mysql_not_8_0(self):
        import json
        with open(os.path.join(ROOT, "kb", "technologies.json"), encoding="utf-8") as f:
            kb = json.load(f)
        my = next(d for d in kb["database"] if d["id"] == "mysql")
        self.assertFalse(any("8.0" in x for x in my["limits"]))
        self.assertTrue(my["limits"])

    def test_dotnet_ai_limit_only_with_ml_features(self):
        item = {"limits": ["Smaller data-science and AI library ecosystem than Python"]}
        for typ in ("web_app", "saas_b2b", "api_platform"):
            for ml, shown in (("none", False), ("inference_api", True), ("llm_rag", True)):
                with self.subTest(typ=typ, ml=ml):
                    self.assertEqual(bool(rec.live_limits(item, ctx_for(project__type=typ, requirements__ml_features=ml))), shown)

    def test_no_data_science_tail_on_non_ml_projects(self):
        for typ in ("web_app", "saas_b2b", "internal_tool"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, team__languages=["csharp"], priorities__maintainability=4)
                self.assertFalse([t for t in texts(out) if "data-science" in t.lower()])


class LearningReason(unittest.TestCase):
    def test_says_why_it_matters_and_stays_grounded(self):
        seen = 0
        for typ, ttm in (("web_app", 5), ("saas_b2b", 4), ("internal_tool", 3)):
            out = run(project__type=typ, priorities__time_to_market=ttm, team__experience="senior")
            for t in texts(out):
                if "learning curve" in t and "against" in t:
                    seen += 1
                    self.assertIn(f"priorities.time_to_market={ttm}", t)
                    self.assertIn("team.experience=senior", t)
        self.assertGreaterEqual(seen, 1)


class OtpAndCognito(unittest.TestCase):
    def test_msg91_line_reproduces_from_its_numbers(self):
        for users in (2000, 30000, 120000):
            with self.subTest(users=users):
                out = run(project__type="marketplace", requirements__auth="phone_otp", infrastructure__data_residency="india",
                          scale__users_12_months=users, scale__users_at_launch=users // 4, scale__peak_concurrent_users=users // 20)
                l = line(out, "Phone OTP")
                self.assertIn("Rs 90/USD", l)
                self.assertIn("18% GST", l)
                lo_rate, hi_rate = costreal.india_sms_usd()
                m = re.search(r"\$(\d+)-(\d+)/month", l)
                self.assertEqual(int(m.group(1)), round(users * 0.3 * lo_rate))
                self.assertEqual(int(m.group(2)), round(users * 1.0 * hi_rate))

    def test_cognito_line_states_flat_rate_assumption(self):
        out = run(project__type="marketplace", requirements__auth="phone_otp", infrastructure__cloud_preference="aws",
                  infrastructure__data_residency="india", scale__users_12_months=300000, scale__users_at_launch=50000, scale__peak_concurrent_users=15000)
        l = next(x for x in lines(out) if x.startswith("auth: Amazon Cognito"))
        self.assertIn("flat $0.0055", l)
        self.assertIn("no volume-tier table", l)
        self.assertIn("90,000-300,000 MAU", l)


class StoredDataOnce(unittest.TestCase):
    def test_storage_service_line_does_not_price_the_volume_again(self):
        for typ in ("social", "ecommerce", "web_app"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, requirements__file_media_storage=True, scale__data_volume_gb_12_months=200,
                          project__description="Users upload photos and documents.")
                st = line(out, "storage:")
                self.assertIsNotNone(st)
                self.assertIn("$0/month here", st)
                sd = line(out, "Stored data")
                self.assertIn("object storage: files and media", sd)

    def test_database_storage_is_labelled_as_rows_and_indexes(self):
        out = run(project__type="saas_b2b", requirements__file_media_storage=False, scale__data_volume_gb_12_months=200)
        sd = line(out, "Stored data")
        if sd:
            self.assertIn("database storage: rows and indexes", sd)


class ZeroRange(unittest.TestCase):
    def test_no_dollar_zero_dash_zero(self):
        out = run(project__type="content_site", project__platforms=["web"], budget__monthly_infra_usd=0)
        for l in lines(out) + [out["summary"]]:
            self.assertNotIn("$0-0", l)


class ExistingDatabaseSentence(unittest.TestCase):
    def test_two_clear_sentences(self):
        for typ in ("saas_b2b", "internal_tool", "web_app"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, infrastructure__existing_systems=["On-prem SQL Server 2019"], team__languages=["csharp"])
                j = next(s["justification"] for s in out["stack"]["supporting"] if "ntegration with existing" in s["choice"])
                self.assertIn("stays as it is and is read through this integration", j)
                self.assertIn("if it will be retired, say so there", j)
                self.assertNotIn("A second database exists only because", j)


if __name__ == "__main__":
    unittest.main()
