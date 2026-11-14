"""i2 (blind10 top fixes): Azure RAG on pgvector at small scale, small scheduled training on a CPU job, lifecycle rows (Dynamics NAV, PostgreSQL 13
successor, Azure AD B2C, SQL Server 2016 date), Go templates for Go teams, 'be kept' is not residency, SCOPE_VS_TEAM lists only the fields
requested, Graph approvals only when approvals are named, trucks/vans/cars as IoT devices. Each rule: >=3 positive cases + a must-not-fire case."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402
from engine import context as cx, costreal, domains  # noqa: E402


def ml(out):
    return sup(out, "ml")[0]


def ex(*systems, **kw):
    return run(**{"infrastructure.existing_systems": list(systems), **kw})


def eol(out, needle):
    return [w for w in out["warnings"] if w["code"] in ("END_OF_LIFE_SYSTEM", "END_OF_LIFE_SOON") and needle in w["message"]]


class AzureRagPgvector(unittest.TestCase):
    def rag(self, desc, **kw):
        return run(**{"infrastructure.cloud_preference": "azure", "requirements.ml_features": "llm_rag", "project.description": desc,
                      "scale.users_at_launch": 30, "scale.users_12_months": 80, "scale.peak_concurrent_users": 10,
                      "budget.monthly_infra_usd": 200, **kw})

    def test_internal_knowledge_bot(self):
        m = ml(self.rag("Internal wiki question answering for staff."))
        self.assertIn("pgvector", m["choice"])
        self.assertNotIn("AI Search", m["choice"])

    def test_support_bot(self):
        self.assertIn("pgvector", ml(self.rag("Customer support assistant answering from our help articles."))["choice"])

    def test_contract_search(self):
        out = self.rag("Legal clause lookup over uploaded contracts.", **{"project.type": "saas_b2b"})
        self.assertIn("pgvector", ml(out)["choice"])
        self.assertNotIn("$74", " ".join(out["estimated_monthly_cost_usd"]["assumptions"]))

    def test_hybrid_ranking_keeps_search_service(self):
        m = ml(self.rag("Question answering with hybrid search and semantic ranking over a large archive."))
        self.assertIn("AI Search", m["choice"])

    def test_large_scale_keeps_search_service(self):
        m = ml(self.rag("Question answering over documents.", **{"scale.users_at_launch": 50000, "scale.users_12_months": 400000,
                                                                  "scale.peak_concurrent_users": 8000, "budget.monthly_infra_usd": 20000}))
        self.assertIn("AI Search", m["choice"])


class SmallTrainingOnCpu(unittest.TestCase):
    def train(self, desc, cloud="aws", gb=20, **kw):
        return run(**{"infrastructure.cloud_preference": cloud, "requirements.ml_features": "training", "project.description": desc,
                      "scale.data_volume_gb_12_months": gb, "scale.users_at_launch": 40, "scale.users_12_months": 100,
                      "scale.peak_concurrent_users": 15, **kw})

    def test_weekly_risk_model_on_aws(self):
        m = ml(self.train("Weekly retraining of a small risk model for an analytics team."))
        self.assertIn("CPU", m["choice"])
        self.assertNotIn("SageMaker", m["choice"])

    def test_churn_model_on_gcp(self):
        self.assertNotIn("Vertex", ml(self.train("Nightly retrain of a churn classifier for a subscription shop.", cloud="gcp"))["choice"])

    def test_forecast_model_on_azure(self):
        out = self.train("Retrain a demand forecast each week.", cloud="azure")
        self.assertIn("CPU", ml(out)["choice"])
        self.assertNotIn("GPU-hours", " ".join(out["estimated_monthly_cost_usd"]["assumptions"]))

    def test_deep_learning_stays_managed(self):
        self.assertIn("SageMaker", ml(self.train("Train a deep learning image classifier on product photos."))["choice"])

    def test_media_models_stay_managed(self):
        for d in ("Retrain a face recognition model each week.", "Weekly retraining of an x-ray scan classifier.", "Retrain a voice transcription model."):
            self.assertIn("SageMaker", ml(self.train(d))["choice"], d)

    def test_large_data_stays_managed(self):
        self.assertIn("SageMaker", ml(self.train("Retrain a risk model.", gb=800))["choice"])


class LifecycleRows(unittest.TestCase):
    def test_nav_versions(self):
        for v, date in (("2016", "2026-04-14"), ("2017", "2027-01-11"), ("2018", "2028-01-11")):
            out = ex(f"Microsoft Dynamics NAV {v} (on-prem ERP)")
            life = [w for w in out["warnings"] if w["code"].startswith("END_OF_LIFE") and f"NAV {v}" in w["message"]]
            self.assertTrue(life, (v, codes(out)))
        self.assertTrue(eol(ex("Dynamics NAV 2016"), "2026-04-14"))

    def test_business_central_is_not_flagged(self):
        out = ex("Dynamics 365 Business Central")
        self.assertFalse([w for w in out["warnings"] if w["code"].startswith("END_OF_LIFE") and "NAV" in w["message"]])

    def test_sql_server_2016_published_date(self):
        self.assertTrue(eol(ex("SQL Server 2016 back-office database"), "2026-07-14"))

    def test_postgresql_13_has_a_successor(self):
        self.assertTrue(eol(ex("PostgreSQL 13 on an old VM"), "PostgreSQL 17 or later"))

    def test_azure_ad_b2c_is_closed_to_new_customers(self):
        for name in ("Azure AD B2C tenant", "Azure Active Directory B2C", "AAD B2C"):
            w = eol(ex(name), "closed to new customers")
            self.assertTrue(w and "Entra External ID" in w[0]["message"], name)

    def test_b2c_auth_line_agrees_with_the_closed_warning(self):
        out = ex("Azure AD B2C tenant", **{"requirements.auth": "enterprise_sso", "infrastructure.cloud_preference": "azure"})
        auth = sup(out, "auth")[0]
        self.assertIn("B2C", auth["choice"])
        self.assertIn("Entra External ID", auth["justification"])
        self.assertNotIn("employees keep one login", auth["justification"])

    def test_plain_entra_auth_line_unchanged(self):
        out = ex("Microsoft Entra ID tenant", **{"requirements.auth": "enterprise_sso", "infrastructure.cloud_preference": "azure"})
        self.assertIn("Entra ID (existing tenant)", sup(out, "auth")[0]["choice"])

    def test_b2c_word_alone_is_not_azure_b2c(self):
        self.assertFalse(eol(ex("Our B2C tenant on Shopify"), "closed to new customers"))

    def test_plain_entra_is_not_b2c(self):
        self.assertFalse(eol(ex("Microsoft Entra ID tenant"), "closed to new customers"))


class GoTemplates(unittest.TestCase):
    def go(self, ptype, desc, **kw):
        return run(**{"team.languages": ["go", "sql"], "project.type": ptype, "project.description": desc, "project.platforms": ["web"],
                      "requirements.realtime": False, **kw})

    def test_go_team_gets_go_templates_for_an_internal_tool(self):
        self.assertIn("Go html/template", self.go("internal_tool", "Staff admin screens for orders.")["stack"]["frontend"]["choice"])

    def test_go_team_content_site(self):
        self.assertIn("Go html/template", self.go("content_site", "A documentation site.", **{"requirements.seo_critical": True})["stack"]["frontend"]["choice"])

    def test_go_team_b2b_dashboard(self):
        out = self.go("saas_b2b", "Billing dashboards and reports for customers.", **{"team.size": 3})
        self.assertIn("Go html/template", out["stack"]["frontend"]["choice"])

    def test_app_like_screens_keep_a_js_framework(self):
        for d in ("Whiteboard with drag and drop shapes on a canvas.", "Kanban boards with drag-and-drop cards.", "Live order book and candlestick charts."):
            out = self.go("saas_b2b", d)
            self.assertNotIn("Go html/template", out["stack"]["frontend"]["choice"], d)

    def test_offline_editing_keeps_a_js_framework(self):
        out = self.go("saas_b2b", "Field reports for engineers.", **{"requirements.offline_support": True})
        self.assertNotIn("Go html/template", out["stack"]["frontend"]["choice"])

    def test_typescript_team_unchanged(self):
        out = run(**{"team.languages": ["typescript"], "project.type": "internal_tool", "project.description": "Staff admin screens for orders."})
        self.assertNotIn("Go html/template", out["stack"]["frontend"]["choice"])


class ResidencyBeKept(unittest.TestCase):
    def test_bare_be_kept_is_not_residency(self):
        for s in ("The records sit in a PostgreSQL database on an old VM that must be kept.",
                  "Customer data in the legacy system must be kept for audit.",
                  "Backups must be kept for seven years."):
            self.assertFalse(cx._residency_stated(s), s)

    def test_kept_with_a_place_is_residency(self):
        for s in ("Records must be kept for 7 years in the EU.", "All customer data must be kept in India.", "Records must be kept within the EU.", "Patient data must be kept on-premises."):
            self.assertTrue(cx._residency_stated(s), s)


class ScopeVsTeamFields(unittest.TestCase):
    def scope(self, **kw):
        out = run(**{"team.size": 1, "team.experience": "beginner", "timeline.mvp_weeks": 3, **kw})
        return [w for w in out["warnings"] if w["code"] == "SCOPE_VS_TEAM"]

    def test_only_realtime(self):
        w = self.scope(**{"requirements.realtime": True})
        self.assertTrue(w and "building realtime in" in w[0]["message"], w)
        self.assertNotIn("payments", w[0]["message"])

    def test_only_multi_tenancy(self):
        w = self.scope(**{"requirements.multi_tenant": True})
        self.assertTrue(w and "building multi-tenancy in" in w[0]["message"], w)

    def test_realtime_and_multi_tenancy(self):
        w = self.scope(**{"requirements.multi_tenant": True, "requirements.realtime": True})
        self.assertIn("realtime/multi-tenancy", w[0]["message"])

    def test_nothing_requested_no_warning(self):
        self.assertFalse(self.scope())


class GraphApprovals(unittest.TestCase):
    def graph(self, desc, **kw):
        out = run(**{"infrastructure.cloud_preference": "azure", "infrastructure.existing_systems": ["Microsoft Entra ID tenant"],
                      "requirements.auth": "enterprise_sso", "project.description": desc, **kw})
        return [s for s in sup(out, "other") if "Graph" in s["choice"]]

    def test_workflow_saas_has_no_graph(self):
        self.assertFalse(self.graph("B2B workflow SaaS for logistics teams.", **{"project.type": "saas_b2b"}))
        self.assertFalse(self.graph("Document workflow for law firms."))

    def test_approvals_named_gets_graph(self):
        self.assertTrue(self.graph("Managers approve leave requests and purchase approvals.", **{"project.type": "internal_tool"}))
        self.assertTrue(self.graph("Expense approval flow for staff."))
        self.assertTrue(self.graph("Leave request tool for 200 employees."))
        self.assertTrue(self.graph("Finance sign-off on every invoice."))
        self.assertTrue(self.graph("Managers authorise expenses above a limit."))


class IotDeviceNouns(unittest.TestCase):
    def test_trucks_vans_cars_count_as_devices(self):
        for noun in ("trucks", "vans", "cars", "buses", "scooters"):
            d = f"GPS units on 3,000 {noun} ping every 30 seconds."
            self.assertEqual(domains.ingest_rate(d), (3000, 30), noun)
            self.assertEqual(costreal.device_count(d), 3000, noun)

    def test_people_are_not_devices(self):
        self.assertIsNone(domains.ingest_rate("3,000 drivers report every 30 seconds."))

    def test_classic_nouns_win_over_vehicle_nouns(self):
        self.assertEqual(costreal.device_count("it detects 50,000 cars a day using 800 sensors"), 800)
        self.assertEqual(costreal.device_count("12 rigs with 4,000 sensors"), 4000)
        self.assertEqual(domains.ingest_rate("12 rigs with 4,000 sensors, each reports every 60 seconds"), (4000, 60))

    def test_noun_prefix_and_per_period_do_not_count(self):
        self.assertEqual(costreal.device_count("sensors in 2,000 cartons; 300 gateways report every 60 seconds"), 300)
        for d in ("2,000 cardholders", "500 vanilla freezers", "300 customers rights", "we see 40,000 cars a day"):
            self.assertIsNone(costreal.device_count(d), d)

    def test_vehicle_counts_unchanged(self):
        self.assertEqual(costreal.device_count("GPS trackers on 30,000 trucks ping every 10 seconds"), 30000)
        self.assertEqual(costreal.device_count("GPS units on 3,000 trucks ping every 30 seconds"), 3000)


if __name__ == "__main__":
    unittest.main()
