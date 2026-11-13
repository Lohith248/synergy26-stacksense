"""E45: a gap in the knowledge base must never surface as a false critical hard-constraint failure.

PAYMENT_DATA_LOCATION and LLM_REGION_CHECK are warnings that name what is known and what to check; critical stays
only for conflicts the engine can prove. Each rule is exercised on several project types plus cases where it must not fire."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.kb import SOURCES  # noqa: E402
from test_round9 import run, sup  # noqa: E402

EU = {"infrastructure.data_residency": "eu", "compliance": ["gdpr"], "requirements.payments": True}
EU_PAYING = [
    ("marketplace", {**EU, "project.type": "marketplace", "project.platforms": ["web"],
                     "project.description": "Marketplace where sellers list handmade goods and are paid out weekly to their bank accounts."}),
    ("saas", {**EU, "project.type": "saas_b2b", "infrastructure.cloud_preference": "aws", "team.languages": ["java"],
              "project.description": "Per-seat project planning tool for agencies, billed monthly by card."}),
    ("mobile", {**EU, "project.type": "web_app", "project.platforms": ["android", "ios"], "team.languages": ["kotlin"],
                "project.description": "Language-learning mobile app with a paid yearly plan."}),
]


def warn(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


class StripeEuResidencyIsAWarning(unittest.TestCase):
    def test_warning_names_mechanism_for_every_project_type(self):
        for name, kw in EU_PAYING:
            out = run(**kw)
            pay = sup(out, "payments")
            self.assertTrue(pay and pay[0]["provider"] == "stripe", name)
            (w,) = warn(out, "PAYMENT_DATA_LOCATION")
            self.assertEqual(w["severity"], "warning", name)
            for text in ("Stripe Payments Europe, Limited", "Data Privacy Framework", "Standard Contractual Clauses",
                         "not an EU-only storage commitment", "Check the Stripe DPA"):
                self.assertIn(text, w["message"], name)
            self.assertNotIn("not verified in the knowledge base", w["message"], name)
            self.assertIn("requirements.payments", w["fields"], name)
            self.assertIn("infrastructure.data_residency", w["fields"], name)

    def test_gap_alone_leaves_status_and_summary_unrelaxed(self):
        for name, kw in EU_PAYING:
            out = run(**kw)
            self.assertEqual(out["status"], "ok_with_warnings", name)
            self.assertFalse(any(w["severity"] == "critical" for w in out["warnings"]), name)
            self.assertFalse(out["summary"].startswith("Relaxed recommendation"), name)
            self.assertFalse(any(a.startswith("Relaxed:") or "does not satisfy" in a for a in out["assumptions"]), name)
            self.assertTrue(any(a.startswith("Payments: data_residency 'eu'") and "not as proof" in a for a in out["assumptions"]), name)

    def test_sources_cited_exist_and_unverified_ones_are_not_marked_verified(self):
        out = run(**EU_PAYING[0][1])
        urls = sup(out, "payments")[0]["sources"]
        by_url = {v["url"]: v for k, v in SOURCES.items() if not k.startswith("_")}
        for u in urls:
            self.assertIn(u, by_url)
        self.assertIn("https://stripe.com/en-ie/legal/ssa", urls)
        self.assertEqual(SOURCES["stripe-ssa"]["status"], "verified")
        self.assertEqual(SOURCES["stripe-dpa"]["status"], "verified")
        self.assertEqual(SOURCES["stripe-dpf-list"]["status"], "official-unverified")
        self.assertIn("not confirmed", SOURCES["stripe-dpf-list"]["title"])

    def test_text_does_not_depend_on_the_project(self):
        msgs = {warn(run(**kw), "PAYMENT_DATA_LOCATION")[0]["message"] for _, kw in EU_PAYING}
        self.assertEqual(len(msgs), 1)  # the vendor facts are the same for any project; no project text is echoed

    def test_country_residency_is_not_confirmed_warning(self):
        for desc in ("Telehealth booking portal for clinics.", "Online course shop paid by card."):
            out = run(**{"requirements.payments": True, "infrastructure.data_residency": "other",
                         "infrastructure.residency_country": "japan", "project.type": "ecommerce", "project.description": desc})
            (w,) = warn(out, "PAYMENT_DATA_LOCATION")
            self.assertEqual(w["severity"], "warning")
            self.assertIn("not confirmed in the knowledge base", w["message"])
            self.assertIn("Japan", w["message"])
            self.assertNotIn("Stripe Payments Europe", w["message"])  # the EEA entity says nothing about Japan


class NegativeCases(unittest.TestCase):
    def test_non_eu_residency_unchanged(self):
        out = run(**{"requirements.payments": True, "infrastructure.data_residency": "us"})
        self.assertFalse(warn(out, "PAYMENT_DATA_LOCATION"))
        out = run(**{"requirements.payments": True, "infrastructure.data_residency": "none"})
        self.assertFalse(warn(out, "PAYMENT_DATA_LOCATION"))
        out = run(**{"requirements.payments": True, "infrastructure.data_residency": "india", "project.type": "fintech",
                     "compliance": ["rbi_localisation"]})
        self.assertFalse(warn(out, "PAYMENT_DATA_LOCATION"))
        self.assertIn("RBI_LOCALISATION", [w["code"] for w in out["warnings"]])
        self.assertIn("Razorpay", sup(out, "payments")[0]["choice"])

    def test_real_region_conflict_stays_critical(self):
        # a database that must stay outside the EU under eu residency is a conflict the engine proves
        out = run(**{**EU, "infrastructure.existing_systems": ["Amazon RDS PostgreSQL in us-east-1 (must stay)"]})
        (w,) = warn(out, "EXISTING_DB_RESIDENCY_CONFLICT")
        self.assertEqual(w["severity"], "critical")
        self.assertTrue(out["summary"].startswith("Relaxed recommendation"))
        self.assertTrue(any(a.startswith("Relaxed:") and "does not satisfy" in a for a in out["assumptions"]))
        # and the payment gap on the same run is still only a warning
        self.assertEqual(warn(out, "PAYMENT_DATA_LOCATION")[0]["severity"], "warning")

    def test_hipaa_and_unspecified_residency_stay_critical_or_warning_as_before(self):
        out = run(**{"compliance": ["hipaa"], "project.type": "healthtech", "infrastructure.data_residency": "eu"})
        self.assertIn("HIPAA_BAA_REQUIRED", [w["code"] for w in out["warnings"]])
        out = run(**{"infrastructure.data_residency": "other"})
        self.assertEqual(warn(out, "RESIDENCY_UNSPECIFIED")[0]["severity"], "critical")

    def test_on_premise_gateway_conflict_stays_critical(self):
        out = run(**{"requirements.payments": True, "infrastructure.cloud_preference": "none",
                     "infrastructure.deployment_model": "on_premise"})
        self.assertEqual(warn(out, "EXTERNAL_PAYMENT_GATEWAY")[0]["severity"], "critical")


LLM = {"requirements.ml_features": "llm_rag", "infrastructure.data_residency": "eu"}
LLM_STACKS = [
    ("aws saas", {**LLM, "project.type": "saas_b2b", "infrastructure.cloud_preference": "aws",
                  "project.description": "Contract analysis tool for law firms with a document question-answering assistant."}),
    ("gcp support", {**LLM, "project.type": "web_app", "infrastructure.cloud_preference": "gcp",
                     "project.description": "Help-centre assistant that answers from a company's own support articles."}),
    ("aws internal", {**LLM, "project.type": "internal_tool", "infrastructure.cloud_preference": "aws",
                      "project.description": "Internal HR policy assistant for employees."}),
]


class LlmRegionCheck(unittest.TestCase):
    def test_never_critical_when_service_sits_inside_the_residency_area(self):
        for name, kw in LLM_STACKS:
            out = run(**kw)
            ml = sup(out, "ml")[0]
            self.assertEqual(ml["data_location"], "eu", name)
            (w,) = warn(out, "LLM_REGION_CHECK")
            self.assertEqual(w["severity"], "warning", name)
            self.assertIn("not confirmed", w["message"], name)
            self.assertFalse(any(x["severity"] == "critical" for x in out["warnings"]), name)
            self.assertFalse(any("does not satisfy" in a for a in out["assumptions"]), name)
            self.assertFalse(out["summary"].startswith("Relaxed"), name)

    def test_bedrock_message_names_the_chosen_region(self):
        out = run(**LLM_STACKS[0][1])
        ml = sup(out, "ml")[0]
        self.assertIn("Amazon Bedrock in eu-central-1", ml["choice"])
        w = warn(out, "LLM_REGION_CHECK")[0]
        self.assertIn("eu-central-1", w["message"])
        self.assertIn("inside the EU", w["message"])

    def test_known_model_region_needs_no_warning(self):
        out = run(**{**LLM, "infrastructure.cloud_preference": "azure"})
        self.assertFalse(warn(out, "LLM_REGION_CHECK"))
        self.assertIn("Sweden Central", sup(out, "ml")[0]["choice"])

    def test_no_residency_no_warning(self):
        out = run(**{"requirements.ml_features": "llm_rag", "infrastructure.cloud_preference": "aws"})
        self.assertFalse(warn(out, "LLM_REGION_CHECK"))


if __name__ == "__main__":
    unittest.main()
