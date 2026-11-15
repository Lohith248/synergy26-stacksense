"""I1 (blind9 re-grade on f51d385): payments text follows PCI_SCOPE, the peak text names the sizing basis, an existing directory is used for staff,
no false Entra claims, description-only deliverables (CMS, image-heavy pages, offline downloads, WAN outage), hybrid retrieval, 0 GB with files.
Each rule: several project types plus inputs where it must not fire."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "I1", "project": {"type": "web_app", "platforms": ["web"], "description": "x"},
        "scale": {"users_at_launch": 800, "users_12_months": 6000, "peak_concurrent_users": 150},
        "team": {"size": 3, "experience": "intermediate", "languages": ["typescript"], "has_devops": False},
        "budget": {"monthly_infra_usd": 600}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password", "realtime": False, "full_text_search": False, "offline_support": False, "ml_features": "none",
                         "payments": False}}


def run(desc, typ="web_app", plats=("web",), req=None, infra=None, scale=None, comp=None):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, platforms=list(plats), description=desc)
    s["requirements"].update(req or {})
    s["infrastructure"].update(infra or {})
    s["scale"].update(scale or {})
    if comp:
        s["compliance"] = comp
    return evaluate(s, counterfactuals=False)


def warn(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


def sup(out, layer):
    return [s for s in out["stack"]["supporting"] if s["layer"] == layer]


class PaymentsFollowPciScope(unittest.TestCase):
    def test_service_provider_shape_drops_the_saq_a_sentence(self):
        cases = (("api_platform", ("api_only",), "Payment orchestration API for merchants: accepts card payments and routes them to acquirers."),
                 ("fintech", ("web",), "A payment service provider that authorises card transactions on behalf of merchants and settles to their banks."),
                 ("saas_b2b", ("web",), "Merchant acquiring platform with a card vault and tokenisation for retailers."))
        for typ, plats, desc in cases:
            with self.subTest(typ=typ):
                out = run(desc, typ, plats, req={"payments": True}, comp=["pci_dss"])
                self.assertIsNotNone(warn(out, "PCI_SCOPE"))
                pay = sup(out, "payments")[0]["justification"]
                self.assertNotIn("can qualify for PCI DSS SAQ A", pay)
                self.assertIn("SAQ A shortcut do not apply", pay)

    def test_a_shop_that_names_its_psp_keeps_saq_a(self):
        out = run("An online shop; customers pay at checkout through our PSP, an acquirer we already use.", "ecommerce", req={"payments": True}, comp=["pci_dss"])
        self.assertIn("can qualify for PCI DSS SAQ A", sup(out, "payments")[0]["justification"])

    def test_ordinary_shop_keeps_the_hosted_checkout_sentence(self):
        for typ, desc in (("ecommerce", "Online shop where customers pay by card."), ("web_app", "Course site with paid subscriptions."),
                          ("marketplace", "Marketplace where buyers pay sellers by card.")):
            with self.subTest(typ=typ):
                out = run(desc, typ, req={"payments": True}, comp=["pci_dss"])
                self.assertIn("can qualify for PCI DSS SAQ A", sup(out, "payments")[0]["justification"])


class PeakBasisText(unittest.TestCase):
    def test_peak_text_names_the_users_used_for_sizing(self):
        out = run("Help desk", scale={"users_at_launch": 5000, "users_12_months": 800, "peak_concurrent_users": 90000})
        w = warn(out, "PEAK_EXCEEDS_USERS")
        self.assertIn("10% of the 5,000 users used for sizing", w["message"])
        self.assertNotIn("10% of users_12_months", w["message"])

    def test_plain_case_keeps_users_12_months(self):
        out = run("Help desk", scale={"users_at_launch": 100, "users_12_months": 5000, "peak_concurrent_users": 90000})
        self.assertIn("10% of users_12_months", warn(out, "PEAK_EXCEEDS_USERS")["message"])


class ExistingDirectory(unittest.TestCase):
    def test_on_premises_directory_gets_a_staff_item_and_no_unused_code(self):
        cases = (("healthtech", "Telehealth for a clinic group where clinicians record notes."), ("internal_tool", "Parts ordering for a factory."),
                 ("web_app", "Student portal where teachers publish grades."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                out = run(desc, typ, infra={"deployment_model": "on_premise", "cloud_preference": "none", "existing_systems": ["Active Directory"]})
                items = [s for s in sup(out, "auth") if s["choice"].startswith("Staff sign-in")]
                self.assertEqual(len(items), 1)
                self.assertIn("Active Directory", items[0]["choice"])
                self.assertIsNone(warn(out, "EXISTING_IDP_NOT_USED"))
                self.assertIsNotNone(warn(out, "STAFF_SIGNIN_VIA_IDP"))

    def test_customer_roles_and_consumer_shops_must_not_get_inferred_staff(self):
        on = {"deployment_model": "on_premise", "cloud_preference": "none", "existing_systems": ["Active Directory"]}
        for typ, desc in (("marketplace", "Estate agents list properties and buyers browse them."), ("saas_b2b", "Support agents of our customers answer tickets."),
                          ("ecommerce", "Online shop for consumers; restaurant managers order supplies."), ("web_app", "Customer admins manage their own team.")):
            with self.subTest(desc=desc):
                out = run(desc, typ, infra=on)
                self.assertEqual([s for s in sup(out, "auth") if s["choice"].startswith("Staff sign-in")], [])

    def test_plain_ldap_on_azure_does_not_take_the_entra_connect_branch(self):
        out = run("Staff portal.", "internal_tool", req={"auth": "enterprise_sso"},
                  infra={"cloud_preference": "azure", "deployment_model": "self_hosted_cloud_vm", "existing_systems": ["OpenLDAP"]})
        self.assertTrue(sup(out, "auth")[0]["choice"].startswith("Keycloak"))

    def test_cloud_directory_without_staff_wording_must_not_get_a_staff_item(self):
        out = run("Public booking site for a salon.", "web_app", infra={"existing_systems": ["Active Directory"]})
        self.assertEqual([s for s in sup(out, "auth") if s["choice"].startswith("Staff sign-in")], [])
        self.assertIsNotNone(warn(out, "EXISTING_IDP_NOT_USED"))

    def test_azure_vm_with_directory_uses_entra_connect_and_no_false_claims(self):
        out = run("Purchase approval portal. Staff use their domain logins.", "internal_tool", req={"auth": "enterprise_sso"},
                  infra={"cloud_preference": "azure", "deployment_model": "self_hosted_cloud_vm", "existing_systems": ["On-prem Active Directory"]})
        a = sup(out, "auth")[0]
        self.assertTrue(a["choice"].startswith("Microsoft Entra ID") and "Entra Connect" in a["choice"], a["choice"])
        text = " ".join(s["justification"] + " ".join(x["why_not"] for x in s["alternatives"]) for s in out["stack"]["supporting"])
        self.assertNotIn("not allowed under this deployment model", text)
        self.assertNotIn("existing Entra tenant", text)

    def test_app_service_with_directory_does_not_say_vm(self):
        out = run("Purchase approval portal.", "internal_tool", req={"auth": "enterprise_sso"},
                  infra={"cloud_preference": "azure", "deployment_model": "managed_cloud", "existing_systems": ["Active Directory"]})
        text = sup(out, "auth")[0]["justification"]
        self.assertNotIn("the VM", text)
        self.assertNotIn("password hashes", text)

    def test_on_premises_still_says_entra_is_not_allowed(self):
        out = run("Staff portal.", "internal_tool", req={"auth": "enterprise_sso"},
                  infra={"cloud_preference": "none", "deployment_model": "on_premise", "existing_systems": ["Active Directory"]})
        a = sup(out, "auth")[0]
        self.assertTrue(a["choice"].startswith("Keycloak"))
        self.assertIn("not allowed under this deployment model", a["alternatives"][0]["why_not"])

    def test_aws_vm_with_directory_is_not_called_entra_or_cloud_forbidden(self):
        out = run("Staff portal.", "internal_tool", req={"auth": "enterprise_sso"},
                  infra={"cloud_preference": "aws", "deployment_model": "self_hosted_cloud_vm", "existing_systems": ["Active Directory"]})
        a = sup(out, "auth")[0]
        self.assertTrue(a["choice"].startswith("Keycloak"))
        self.assertNotIn("not allowed", a["alternatives"][0]["why_not"])


class DescriptionDeliverables(unittest.TestCase):
    def test_cms_note(self):
        for typ, desc in (("content_site", "A regional newsroom. Editors publish through a CMS."),
                          ("ecommerce", "A shop whose marketing team manages pages in a headless CMS."),
                          ("web_app", "Club site: the content team updates news in the CMS.")):
            with self.subTest(typ=typ):
                self.assertIsNotNone(warn(run(desc, typ), "DESC_CMS_NOT_SELECTED"))

    def test_cms_must_not_fire(self):
        for desc, infra in (("A shop with a product catalogue.", {}), ("We do not need a CMS; developers edit the pages.", {}),
                            ("Editors publish through a CMS.", {"existing_systems": ["WordPress CMS"]})):
            with self.subTest(desc=desc):
                self.assertIsNone(warn(run(desc, "content_site", infra=infra), "DESC_CMS_NOT_SELECTED"))

    def test_image_note(self):
        for typ, desc in (("content_site", "Readers browse photo galleries of events."), ("ecommerce", "A shop with many product photos for each item."),
                          ("web_app", "A real-estate portal with an image-heavy listing page.")):
            with self.subTest(typ=typ):
                self.assertIsNotNone(warn(run(desc, typ), "DESC_IMAGE_OPTIMISATION"))

    def test_cms_colour_profiles_and_admin_dashboard_must_not_fire(self):
        for desc in ("Print shop that converts files with CMS colour profiles.", "Staff edit orders in the admin dashboard."):
            with self.subTest(desc=desc):
                self.assertIsNone(warn(run(desc, "content_site"), "DESC_CMS_NOT_SELECTED"))

    def test_image_must_not_fire(self):
        self.assertIsNone(warn(run("Staff view photo galleries of site inspections.", "internal_tool"), "DESC_IMAGE_OPTIMISATION"))
        self.assertIsNone(warn(run("Users upload a profile photo.", "web_app"), "DESC_IMAGE_OPTIMISATION"))
        self.assertIsNone(warn(run("Photo galleries of events.", "web_app", plats=("android",)), "DESC_IMAGE_OPTIMISATION"))

    def test_offline_download_note(self):
        for typ, desc in (("web_app", "Video lessons that can be downloaded for offline study."),
                          ("content_site", "Subscribers download episodes to watch offline on the train."),
                          ("web_app", "Course recordings are downloaded by students for offline use.")):
            with self.subTest(desc=desc):
                w = warn(run(desc, typ, plats=("android",), req={"offline_support": True, "file_media_storage": True}), "DESC_OFFLINE_DOWNLOADS")
                self.assertIsNotNone(w)
                self.assertIn("CDN", w["message"])

    def test_offline_download_must_not_fire(self):
        for desc in ("Students stream video lessons.", "Staff download invoices as PDF.", "No offline downloads are needed; video lessons are streamed."):
            with self.subTest(desc=desc):
                self.assertIsNone(warn(run(desc, "web_app"), "DESC_OFFLINE_DOWNLOADS"))

    def test_wan_outage_assumption_names_on_site_components(self):
        on = {"deployment_model": "on_premise", "cloud_preference": "none"}
        for typ, desc in (("iot", "Plant monitoring. The plant network must keep working if the WAN link to head office is down."),
                          ("healthtech", "Clinic records. The clinic must keep working when the internet link is down."),
                          ("internal_tool", "Warehouse tool. The site keeps working if the WAN goes down.")):
            with self.subTest(typ=typ):
                out = run(desc, typ, infra=on)
                a = [x for x in out["assumptions"] if x.startswith("Local-first operation")]
                self.assertEqual(len(a), 1)
                self.assertIn("PostgreSQL", a[0])

    def test_site_down_paging_is_not_a_wan_outage(self):
        out = run("If the site goes down, the on-call engineer is paged.", "internal_tool", infra={"deployment_model": "on_premise", "cloud_preference": "none"})
        self.assertEqual([x for x in out["assumptions"] if x.startswith("Local-first operation")], [])

    def test_wan_outage_must_not_fire_in_the_cloud(self):
        out = run("The tool must keep working if the WAN link is down.", "internal_tool")
        self.assertEqual([x for x in out["assumptions"] if x.startswith("Local-first operation")], [])


class HybridRetrievalAndZeroGb(unittest.TestCase):
    def rag(self, desc, typ="ai_ml_product", **kw):
        out = run(desc, typ, req={"ml_features": "llm_rag", **kw.pop("req", {})}, **kw)
        return sup(out, "ml")[0]["justification"]

    def test_hybrid_named_for_exact_terms_or_a_large_corpus(self):
        for desc in ("Staff ask questions over our manuals and need exact part numbers found as well as meaning.",
                     "Question answering over 2 million research documents.",
                     "Support assistant that combines keyword and semantic search over the knowledge base."):
            with self.subTest(desc=desc):
                self.assertIn("Hybrid retrieval", self.rag(desc))

    def test_hybrid_must_not_fire_for_a_small_plain_corpus(self):
        self.assertNotIn("Hybrid retrieval", self.rag("Question answering over our 300 policy documents."))
        self.assertNotIn("Hybrid retrieval", self.rag("Chat assistant that answers questions about the product."))

    def test_zero_gb_with_files(self):
        for typ, desc in (("web_app", "Ticket tracker where staff attach scans."), ("ecommerce", "Shop with product photos."),
                          ("internal_tool", "Contract store.")):
            with self.subTest(typ=typ):
                out = run(desc, typ, req={"file_media_storage": True}, scale={"data_volume_gb_12_months": 0})
                self.assertEqual(warn(out, "DATA_VOLUME_ZERO_WITH_FILES")["severity"], "warning")
                self.assertTrue(any("minimum of 1 GB" in a for a in out["assumptions"]))

    def test_zero_gb_without_files_is_silent(self):
        out = run("Ticket tracker.", req={"file_media_storage": False}, scale={"data_volume_gb_12_months": 0})
        self.assertIsNone(warn(out, "DATA_VOLUME_ZERO_WITH_FILES"))
        out = run("Ticket tracker with files.", req={"file_media_storage": True}, scale={"data_volume_gb_12_months": 20})
        self.assertIsNone(warn(out, "DATA_VOLUME_ZERO_WITH_FILES"))


if __name__ == "__main__":
    unittest.main()
