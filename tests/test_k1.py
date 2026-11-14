"""K1 (blind10 re-grade on 30d4d2d): the staff sign-in inference is limited to the organisation's own people, the queue does not claim to schedule a
cron training job, SOC 2 names the engineering controls, and Prometheus/Grafana on the app VM adds no extra bill at tiers 0-1.
Each rule: several project types plus inputs where it must not fire."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "K1", "project": {"type": "web_app", "platforms": ["web"], "description": "x"},
        "scale": {"users_at_launch": 800, "users_12_months": 6000, "peak_concurrent_users": 150},
        "team": {"size": 3, "experience": "intermediate", "languages": ["typescript"], "has_devops": False},
        "budget": {"monthly_infra_usd": 600}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password", "realtime": False, "full_text_search": False, "offline_support": False, "ml_features": "none",
                         "payments": False}}


def run(desc, typ="web_app", plats=("web",), req=None, infra=None, scale=None, comp=None, budget=None):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, platforms=list(plats), description=desc)
    s["requirements"].update(req or {})
    s["infrastructure"].update(infra or {})
    s["scale"].update(scale or {})
    if budget:
        s["budget"]["monthly_infra_usd"] = budget
    if comp:
        s["compliance"] = comp
    return evaluate(s, counterfactuals=False)


def warn(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


def sup(out, layer):
    return [s for s in out["stack"]["supporting"] if s["layer"] == layer]


def staff_items(out):
    return [s for s in sup(out, "auth") if s["choice"].startswith("Staff sign-in")]


ON_PREM = {"deployment_model": "on_premise", "cloud_preference": "none"}


class StaffSigninAudience(unittest.TestCase):
    def test_customers_and_citizens_are_not_the_organisations_staff(self):
        cases = (("ecommerce", "Distributor adding a B2B ordering portal for its customers' purchasing staff.", {"cloud_preference": "azure", "existing_systems": ["Active Directory"]}),
                 ("web_app", "City corporation citizen portal for tax payment. Staff already use an LDAP directory.", dict(ON_PREM, existing_systems=["Employee LDAP directory"])),
                 ("marketplace", "Supplier portal where our suppliers' employees upload price lists.", dict(ON_PREM, existing_systems=["Active Directory"])),
                 ("saas_b2b", "Customer portal for dealers; the dealers' staff track orders.", dict(ON_PREM, existing_systems=["Active Directory"])))
        for typ, desc, infra in cases:
            with self.subTest(desc=desc):
                out = run(desc, typ, infra=infra)
                self.assertEqual(staff_items(out), [])
                self.assertIsNone(warn(out, "STAFF_SIGNIN_VIA_IDP"))
                self.assertIsNotNone(warn(out, "EXISTING_IDP_NOT_USED"))

    def test_the_organisations_own_staff_still_get_the_item(self):
        cases = (("internal_tool", "Parts ordering for our factory staff.", dict(ON_PREM, existing_systems=["Active Directory"])),
                 ("web_app", "Student portal where teachers publish grades.", dict(ON_PREM, existing_systems=["Active Directory"])),
                 ("healthtech", "Clinic booking system used by clinicians.", dict(ON_PREM, existing_systems=["Active Directory"])),
                 ("internal_tool", "Employee leave tracker for the company.", dict(ON_PREM, existing_systems=["LDAP directory"])),
                 ("ecommerce", "Online shop. Staff sign in through our Okta tenant to manage orders.", {"existing_systems": ["Okta workforce identity"]}))
        for typ, desc, infra in cases:
            with self.subTest(desc=desc):
                out = run(desc, typ, infra=infra)
                self.assertEqual(len(staff_items(out)), 1)
                self.assertIsNotNone(warn(out, "STAFF_SIGNIN_VIA_IDP"))


class QueueDoesNotScheduleCronTraining(unittest.TestCase):
    def queue_texts(self, out):
        return " ".join(s["justification"] for s in sup(out, "queue"))

    def test_small_retrain_runs_as_a_cron_job_and_the_queue_does_not_claim_it(self):
        for cloud, typ, desc in (("azure", "internal_tool", "Quarterly demand forecast retrained from 2 GB of sales."),
                                 ("aws", "web_app", "Churn model retrained weekly from a small table."),
                                 ("gcp", "saas_b2b", "Lead scoring retrained nightly on a few thousand rows.")):
            with self.subTest(cloud=cloud):
                out = run(desc, typ, req={"ml_features": "training"}, infra={"cloud_preference": cloud}, scale={"users_12_months": 40, "users_at_launch": 20, "peak_concurrent_users": 5})
                self.assertIn("Scheduled CPU training job", " ".join(s["choice"] for s in sup(out, "ml")))
                self.assertNotIn("chedules training jobs", self.queue_texts(out))
                self.assertEqual(sup(out, "queue"), [])

    def test_heavy_training_is_still_queued_and_other_queue_reasons_stay(self):
        out = run("Fine-tune a deep learning model on user images.", req={"ml_features": "training"}, infra={"cloud_preference": "aws"})
        self.assertIn("chedules training jobs", self.queue_texts(out))
        out = run("Quarterly forecast retrain.", req={"ml_features": "training", "payments": True}, infra={"cloud_preference": "aws"},
                  scale={"users_12_months": 200000, "users_at_launch": 50000, "peak_concurrent_users": 4000})  # tier 3: no longer a CPU job
        self.assertIn("chedules training jobs", self.queue_texts(out))
        self.assertIn("Payment-gateway webhooks", self.queue_texts(out))


class Soc2Controls(unittest.TestCase):
    def test_soc2_names_secrets_iac_review_gate_and_retention(self):
        for cloud, typ, vault in (("aws", "api_platform", "AWS Secrets Manager"), ("azure", "saas_b2b", "Azure Key Vault"), ("gcp", "web_app", "Google Secret Manager")):
            with self.subTest(cloud=cloud):
                m = warn(run("Address API for developers.", typ, comp=["soc2"], infra={"cloud_preference": cloud}), "SOC2_CONTROLS")["message"]
                for word in (vault, "infrastructure defined as code", "pull-request review", "retention"):
                    self.assertIn(word, m)

    def test_no_soc2_no_controls_text(self):
        for comp in (None, ["gdpr"], ["iso27001"]):
            with self.subTest(comp=comp):
                out = run("Address API for developers.", "api_platform", comp=comp)
                self.assertIsNone(warn(out, "SOC2_CONTROLS"))
                self.assertNotIn("Secrets Manager", " ".join(w["message"] for w in out["warnings"] if w["code"].endswith("_CONTROLS")))


class PrometheusOnTheAppVm(unittest.TestCase):
    VM = {"deployment_model": "self_hosted_cloud_vm", "cloud_preference": "any"}

    def obs(self, out):
        """(choice, the cost line the band carries for the observability item)"""
        line = next((a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("observability:")), None)  
        return sup(out, "observability")[0]["choice"], line

    def test_self_hosted_vm_observability_is_free_at_small_tiers(self):
        for typ, desc in (("web_app", "Booking site for a clinic."), ("internal_tool", "Stock tracker."), ("saas_b2b", "Invoice tool.")):
            with self.subTest(typ=typ):
                o = self.obs(run(desc, typ, infra=self.VM, scale={"users_at_launch": 30, "users_12_months": 100, "peak_concurrent_users": 10}))
                self.assertIn("Prometheus/Grafana on the VM", o[0])
                self.assertIn("$0-0/month extra", o[1])

    def test_managed_cloud_monitoring_keeps_its_band(self):
        o = self.obs(run("Booking site for a clinic.", infra={"cloud_preference": "aws"}, scale={"users_at_launch": 30, "users_12_months": 100, "peak_concurrent_users": 10}))
        self.assertNotIn("month extra", o[1])


if __name__ == "__main__":
    unittest.main()
