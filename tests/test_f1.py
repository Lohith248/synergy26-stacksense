"""F1: named email product (A19), residency severity by hosting (A11), CDN only for a public audience (A8), analytics warehouse guard (A17),
named identity providers (A16), on-premises compliance and availability text (A15, first half).
Each rule is stated over input fields, tested on several project types plus inputs where it must not fire. Inputs are inline."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "F1", "project": {"type": "web_app", "platforms": ["web"], "description": "A small web application."},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "intermediate", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 2000}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def run(desc=None, **kw):
    s = copy.deepcopy(BASE)
    if desc is not None:
        s["project"]["description"] = desc
    for path, v in kw.items():
        node, parts = s, path.replace("__", ".").split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return evaluate(s, counterfactuals=False)


def sup(out, needle):
    return [s for s in out["stack"]["supporting"] if needle in s["choice"] or needle in s["layer"]]


def warns(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


ONPREM = {"infrastructure__cloud_preference": "none", "infrastructure__deployment_model": "on_premise"}
AIRGAP = {"infrastructure__cloud_preference": "none", "infrastructure__deployment_model": "air_gapped"}


class EmailProduct(unittest.TestCase):
    def test_email_component_names_a_product_for_the_host_cloud(self):
        cases = [("aws", "content_site", "Paid newsletter for writers: posts go out by email.", "Amazon SES"),
                 ("azure", "saas_b2b", "Invoicing tool that sends transactional emails to customers.", "Azure Communication Services Email"),
                 ("gcp", "ecommerce", "Shop that sends order confirmation emails.", "Resend"),
                 ("any", "web_app", "Club site with a mailing list for members.", None)]
        for cloud, typ, desc, product in cases:
            with self.subTest(cloud=cloud):
                out = run(project__type=typ, desc=desc, infrastructure__cloud_preference=cloud)
                comp = sup(out, "Email delivery")
                self.assertEqual(len(comp), 1)
                self.assertNotIn("managed transactional/list", comp[0]["choice"])
                self.assertNotIn("No provider is selected", comp[0]["justification"])
                if product:
                    self.assertIn(product, comp[0]["choice"])
                else:  # any cloud: a named product anyway
                    self.assertTrue(any(n in comp[0]["choice"] for n in ("Amazon SES", "Azure Communication Services Email", "Resend")), comp[0]["choice"])
                self.assertIn("planning estimate", " ".join(comp[0]["tradeoffs"]))

    def test_no_email_component_without_email_in_the_description(self):
        self.assertFalse(sup(run(desc="A small booking site for a salon."), "Email delivery"))


class ResidencySeverity(unittest.TestCase):
    def test_other_residency_is_lower_when_no_region_can_matter(self):
        static = run(project__type="content_site", desc="Portfolio with project pages and a blog.", requirements__auth="none",
                     infrastructure__data_residency="other")
        self.assertEqual(warns(static, "RESIDENCY_UNSPECIFIED")[0]["severity"], "warning")
        for name, extra in (("on_premise", ONPREM), ("air_gapped", AIRGAP)):
            with self.subTest(deploy=name):
                out = run(project__type="internal_tool", infrastructure__data_residency="other", **extra)
                w = warns(out, "RESIDENCY_UNSPECIFIED")[0]
                self.assertEqual(w["severity"], "info")
                self.assertIn("own premises", w["message"])

    def test_other_residency_stays_critical_on_a_cloud_host_with_data(self):
        for typ in ("web_app", "saas_b2b", "healthtech"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, infrastructure__data_residency="other")
                self.assertEqual(warns(out, "RESIDENCY_UNSPECIFIED")[0]["severity"], "critical")

    def test_a_stated_place_stays_critical_even_on_premises(self):
        out = run(desc="Records must be stored in Canada or Australia.", infrastructure__data_residency="other", **ONPREM)
        self.assertEqual(warns(out, "RESIDENCY_UNSPECIFIED")[0]["severity"], "critical")


class CdnAudience(unittest.TestCase):
    def cdn(self, **kw):
        return sup(run(**kw), "cdn")

    def test_no_cdn_when_every_route_is_signed_in(self):
        for typ in ("saas_b2b", "healthtech", "fintech", "data_analytics", "ai_ml_product", "other"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, scale__users_12_months=9000, scale__peak_concurrent_users=400)
                self.assertFalse(sup(out, "cdn"), typ)
                self.assertTrue(warns(out, "SERVICE_NOT_ADDED"), typ)

    def test_cdn_kept_for_public_audiences(self):
        cases = (dict(project__type="ecommerce", requirements__auth="email_password"),
                 dict(project__type="saas_b2b", requirements__seo_critical=True),
                 dict(project__type="saas_b2b", scale__geo_spread="global"),
                 dict(project__type="healthtech", requirements__auth="none", desc="Public information pages and a blog about clinic services."),
                 dict(project__type="social"))
        for kw in cases:
            with self.subTest(kw=kw):
                kw = dict(kw, scale__users_12_months=9000, scale__peak_concurrent_users=400)
                self.assertTrue(self.cdn(**kw), kw)

    def test_cdn_text_names_public_pages_only_when_the_input_has_them(self):
        out = run(project__type="saas_b2b", scale__users_12_months=9000, scale__peak_concurrent_users=400, scale__geo_spread="global")
        self.assertNotIn("public pages", sup(out, "cdn")[0]["justification"])
        out = run(project__type="ecommerce", scale__users_12_months=9000, scale__peak_concurrent_users=400)
        self.assertIn("public pages", sup(out, "cdn")[0]["justification"])


class WarehouseGuard(unittest.TestCase):
    ANALYTICS = dict(project__type="data_analytics", scale__workload="read_heavy")

    def wh(self, **kw):
        return sup(run(**dict(self.ANALYTICS, **kw)), "Analytics warehouse")

    def test_small_audience_and_volume_use_the_application_database(self):
        for kw in (dict(scale__data_volume_gb_12_months=300, scale__users_12_months=60, scale__peak_concurrent_users=10),
                   dict(scale__data_volume_gb_12_months=450, scale__users_12_months=1500, scale__peak_concurrent_users=30,
                        desc="Dashboards and reports for the operations team."),
                   dict(project__type="internal_tool", desc="Staff reports and dashboards.", scale__data_volume_gb_12_months=400,
                        scale__users_12_months=80, scale__peak_concurrent_users=12)):
            with self.subTest(kw=kw):
                out = run(**dict(self.ANALYTICS, **kw))
                self.assertFalse(sup(out, "Analytics warehouse"))
                self.assertTrue([w for w in warns(out, "SERVICE_NOT_ADDED") if "Analytics warehouse" in w["message"]] or kw.get("project__type"))

    def test_warehouse_kept_for_many_readers_or_a_large_volume(self):
        self.assertTrue(self.wh(scale__data_volume_gb_12_months=300, scale__users_12_months=40000, scale__peak_concurrent_users=800))
        self.assertTrue(self.wh(scale__data_volume_gb_12_months=800, scale__users_12_months=150, scale__peak_concurrent_users=40))
        self.assertTrue(self.wh(scale__data_volume_gb_12_months=300, scale__users_12_months=900, scale__peak_concurrent_users=60))

    def test_air_gapped_adds_no_second_engine_below_a_terabyte(self):
        small = self.wh(scale__data_volume_gb_12_months=500, scale__users_12_months=40000, scale__peak_concurrent_users=800, **AIRGAP)
        self.assertFalse(small)
        big = self.wh(scale__data_volume_gb_12_months=2500, scale__users_12_months=40000, scale__peak_concurrent_users=800, **AIRGAP)
        self.assertTrue(big)


class NamedIdentityProviders(unittest.TestCase):
    def auth(self, **kw):
        return sup(run(**kw), "auth")[0]

    def test_adfs_is_reused_through_oidc_or_saml(self):
        for cloud, extra in (("none", ONPREM), ("any", {})):
            with self.subTest(cloud=cloud):
                a = self.auth(project__type="healthtech", requirements__auth="enterprise_sso",
                              infrastructure__existing_systems=["Active Directory Federation Services (ADFS)"], **extra)
                self.assertIn("AD FS", a["choice"])
                self.assertIn("OpenID Connect/SAML", a["choice"])
                self.assertNotIn("Keycloak 26", a["choice"])

    def test_plain_active_directory_is_not_adfs(self):
        a = self.auth(requirements__auth="enterprise_sso", infrastructure__existing_systems=["Active Directory"], **ONPREM)
        self.assertNotIn("AD FS", a["choice"])

    def test_named_social_providers_come_first(self):
        for typ, systems in (("social", ["Discord OAuth"]), ("web_app", ["Steam", "LinkedIn login"]), ("marketplace", ["Discord"])):
            with self.subTest(typ=typ):
                a = self.auth(project__type=typ, requirements__auth="social", infrastructure__existing_systems=systems,
                              team__languages=["javascript"])
                first = a["choice"].split(" with ", 1)[1]
                self.assertTrue(first.startswith(systems[0].split()[0]), a["choice"])
                self.assertIn("sign-in", a["choice"])

    def test_no_named_provider_keeps_the_default_list(self):
        a = self.auth(project__type="social", requirements__auth="social", team__languages=["javascript"])
        self.assertTrue(a["choice"].endswith("with Google/GitHub/Microsoft OAuth"), a["choice"])


class OnPremisesComplianceAndAvailability(unittest.TestCase):
    def test_hipaa_on_premises_does_not_ask_for_a_cloud_baa(self):
        for typ, extra in (("healthtech", ONPREM), ("internal_tool", AIRGAP), ("saas_b2b", ONPREM)):
            with self.subTest(typ=typ):
                w = warns(run(project__type=typ, compliance=["hipaa"], infrastructure__data_residency="us", **extra), "HIPAA_BAA_REQUIRED")[0]
                self.assertNotIn("with the cloud provider", w["message"])
                self.assertIn("audit logs", w["message"])
                self.assertIn("physical access", w["message"])

    def test_hipaa_on_a_cloud_still_asks_for_the_baa(self):
        w = warns(run(project__type="healthtech", compliance=["hipaa"], infrastructure__data_residency="us"), "HIPAA_BAA_REQUIRED")[0]
        self.assertIn("Business Associate Agreement with the cloud provider", w["message"])

    def test_on_premises_availability_names_a_standby_server_not_a_zero_dollar_instance(self):
        for typ in ("healthtech", "saas_b2b", "internal_tool"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, requirements__availability="99.95", **ONPREM)
                text = " ".join(out["estimated_monthly_cost_usd"]["assumptions"])
                self.assertNotIn("second app instance in another zone", text)
                self.assertIn("hardware", text)
                self.assertIn("standby database server", out["stack"]["database"]["justification"])

    def test_cloud_availability_text_is_unchanged(self):
        out = run(requirements__availability="99.95")
        self.assertIn("second app instance in another zone", " ".join(out["estimated_monthly_cost_usd"]["assumptions"]))
        self.assertNotIn("standby database server", out["stack"]["database"]["justification"])


if __name__ == "__main__":
    unittest.main()
