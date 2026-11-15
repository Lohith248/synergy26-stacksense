"""H2 (blind9 A4): compliance notes follow the input: minors under GDPR/DPDP, HIPAA safeguards on managed cloud, SOC 2 audit cost, PCI
service-provider shape, and a data-path warning for a vendor with no data location under a named residency. Several project types each,
plus inputs where the rule must not fire."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "H2C", "project": {"type": "web_app", "platforms": ["web"], "description": "x"},
        "scale": {"users_at_launch": 800, "users_12_months": 6000, "peak_concurrent_users": 150},
        "team": {"size": 3, "experience": "intermediate", "languages": ["typescript"], "has_devops": False},
        "budget": {"monthly_infra_usd": 900}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password", "payments": False}}


def run(desc, typ="web_app", comp=(), infra=None, req=None):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, description=desc)
    s["compliance"] = list(comp)
    s["infrastructure"].update(infra or {})
    s["requirements"].update(req or {})
    return evaluate(s, counterfactuals=False)


def note(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


class Minors(unittest.TestCase):
    def test_minors_extend_gdpr_and_dpdp_notes(self):
        cases = (("gdpr", "GDPR_OBLIGATIONS", "social", "Chat app for teenagers aged 13 to 17 across Europe.", "Art. 8"),
                 ("gdpr", "GDPR_OBLIGATIONS", "web_app", "Maths practice site for children in primary school, many under 13.", "Art. 8"),
                 ("dpdp", "DPDP_OBLIGATIONS", "gaming", "Quiz game where players are 10 to 16 years old.", "parent or lawful guardian"),
                 ("dpdp", "DPDP_OBLIGATIONS", "web_app", "Tuition app for classes 6 to 10, many students under 18.", "parent or lawful guardian"))
        for reg, code, typ, desc, key in cases:
            with self.subTest(desc=desc):
                w = note(run(desc, typ, [reg]), code)
                self.assertIn("minors", w["message"])
                self.assertIn(key, w["message"])
                self.assertIn("project.description", w["fields"])

    def test_minors_must_not_fire(self):
        for reg, code, desc in (("gdpr", "GDPR_OBLIGATIONS", "Accounting tool for small businesses."),
                                ("dpdp", "DPDP_OBLIGATIONS", "Payroll portal. There are no children or minors among the users."),
                                ("gdpr", "GDPR_OBLIGATIONS", "Dashboard for university lecturers and adult learners.")):
            with self.subTest(desc=desc):
                self.assertNotIn("Children:", note(run(desc, comp=[reg]), code)["message"])

    def test_without_the_regime_there_is_no_note(self):
        self.assertIsNone(note(run("Tuition app for students under 18."), "GDPR_OBLIGATIONS"))


class Soc2Hipaa(unittest.TestCase):
    def test_soc2_note_names_audit_cost_and_vendor_reports(self):
        for typ, desc in (("saas_b2b", "Invoice tool for companies."), ("api_platform", "Data API for analysts."), ("web_app", "Booking portal.")):
            with self.subTest(typ=typ):
                m = note(run(desc, typ, ["soc2"]), "SOC2_CONTROLS")["message"]
                self.assertIn("independent auditor", m)
                self.assertIn("as much as or more than the infrastructure", m)
                self.assertIn("vendors that publish", m)

    def test_hipaa_managed_cloud_names_safeguards(self):
        for typ, desc in (("healthtech", "Patient portal for a US clinic."), ("web_app", "Therapy booking."), ("saas_b2b", "Lab results sharing for clinics.")):
            with self.subTest(typ=typ):
                m = note(run(desc, typ, ["hipaa"], infra={"data_residency": "us"}), "HIPAA_BAA_REQUIRED")["message"]
                for word in ("in transit and at rest", "audit logs", "role-based access", "BAA coverage"):
                    self.assertIn(word, m)

    def test_hipaa_on_premises_keeps_its_own_note(self):
        out = run("Patient portal for a US clinic.", "healthtech", ["hipaa"],
                  infra={"deployment_model": "on_premise", "cloud_preference": "none", "data_residency": "us"})
        m = note(out, "HIPAA_BAA_REQUIRED")["message"]
        self.assertIn("on-premises", m)
        self.assertNotIn("A BAA does not configure", m)


class WordingChecks(unittest.TestCase):
    def test_exact_wording_of_the_reviewed_sentences(self):
        self.assertIn("tracking or behavioural monitoring of children, and targeted advertising directed at them",
                      note(run("Quiz game for kids aged 8 to 12.", comp=["dpdp"]), "DPDP_OBLIGATIONS")["message"])
        self.assertIn("where you rely on consent as the lawful basis", note(run("Quiz game for kids aged 8 to 12.", comp=["gdpr"]), "GDPR_OBLIGATIONS")["message"])
        self.assertIn("can cost as much as or more than the infrastructure for a small product (planning heuristic)",
                      note(run("Invoice tool.", comp=["soc2"]), "SOC2_CONTROLS")["message"])


class PciServiceProvider(unittest.TestCase):
    def test_payment_service_provider_shape_drops_saq_a(self):
        cases = (("api_platform", "Payment orchestration API for merchants: accepts card payments and routes to acquirers."),
                 ("fintech", "We are a payment service provider vaulting cards for merchants and settling with acquirers."),
                 ("api_platform", "Card tokenization service for merchants who accept card payments."))
        for typ, desc in cases:
            with self.subTest(desc=desc):
                w = note(run(desc, typ, ["pci_dss"], infra={"data_residency": "us"}, req={"payments": True}), "PCI_SCOPE")
                self.assertEqual(w["severity"], "warning")
                self.assertIn("service provider", w["message"])
                self.assertIn("does not apply", w["message"])
                self.assertIn("segmented", w["message"])
                self.assertIn("over 300,000 card transactions a year", w["message"])
                self.assertIn("card-scheme rules", w["message"])
                self.assertNotIn("official-unverified", w["message"])
                self.assertNotIn("At this scale", w["message"])

    def test_ordinary_shop_keeps_saq_a(self):
        for typ, desc in (("ecommerce", "Online shop that accepts card payments through a hosted checkout."),
                          ("marketplace", "Marketplace where buyers pay by card via Stripe."),
                          ("web_app", "Ticket shop; payments are handled by the payment gateway's hosted page.")):
            with self.subTest(desc=desc):
                w = note(run(desc, typ, ["pci_dss"], req={"payments": True}), "PCI_SCOPE")
                self.assertEqual(w["severity"], "info")
                self.assertIn("SAQ A", w["message"])


class DataPath(unittest.TestCase):
    def test_vendor_in_the_data_path_without_a_location_warns_under_residency(self):
        for typ, desc, req in (("social", "Group chat for friends in Europe with phone-number sign-in.", {"auth": "phone_otp"}),
                               ("web_app", "Neighbourhood help app with phone-number sign-in.", {"auth": "phone_otp"}),
                               ("saas_b2b", "Tutoring platform with live video classes between tutor and student.", {})):
            with self.subTest(desc=desc):
                w = note(run(desc, typ, infra={"data_residency": "eu"}, req=req), "DATA_PATH_RESIDENCY")
                self.assertEqual(w["severity"], "warning")
                self.assertIn("not confirmed to stay in the EU", w["message"])

    def test_must_not_fire(self):
        out = run("Group chat for friends with phone-number sign-in.", "social", req={"auth": "phone_otp"})  # no residency
        self.assertIsNone(note(out, "DATA_PATH_RESIDENCY"))
        out = run("Group chat for friends in India with phone-number sign-in.", "social", infra={"data_residency": "india"},
                  req={"auth": "phone_otp"})  # in-region SMS route
        self.assertIsNone(note(out, "DATA_PATH_RESIDENCY"))
        out = run("Tutoring platform with live video classes.", "saas_b2b",
                  infra={"data_residency": "eu", "deployment_model": "on_premise", "cloud_preference": "none"})  # self-hosted
        self.assertIsNone(note(out, "DATA_PATH_RESIDENCY"))


if __name__ == "__main__":
    unittest.main()
