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

    def test_email_products_cite_a_source_that_is_not_marked_verified(self):
        import json
        with open(os.path.join(ROOT, "kb", "sources.json"), encoding="utf-8") as f:
            srcs = {v["url"]: v for v in json.load(f).values() if isinstance(v, dict)}
        for cloud, typ, desc in (("aws", "content_site", "Newsletter sent by email."), ("azure", "saas_b2b", "Sends transactional emails."),
                                 ("gcp", "ecommerce", "Order confirmation emails.")):
            with self.subTest(cloud=cloud):
                comp = sup(run(project__type=typ, desc=desc, infrastructure__cloud_preference=cloud), "Email delivery")[0]
                self.assertTrue(comp["sources"])
                for sid in comp["sources"]:
                    self.assertEqual(srcs[sid]["status"], "official-unverified")

    def test_no_email_component_without_email_in_the_description(self):
        self.assertFalse(sup(run(desc="A small booking site for a salon."), "Email delivery"))


class ResidencySeverity(unittest.TestCase):
    def test_other_residency_is_lower_when_no_region_can_matter(self):
        static = run(project__type="content_site", desc="Portfolio with project pages and a blog.", requirements__auth="none",
                     infrastructure__data_residency="other")
        self.assertEqual(warns(static, "RESIDENCY_UNSPECIFIED")[0]["severity"], "warning")
        self.assertNotIn("stores no personal data", warns(static, "RESIDENCY_UNSPECIFIED")[0]["message"])
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

    # B1: video, audio or large files delivered to users keep the CDN whatever the sign-in
    def test_cdn_kept_for_media_delivery_behind_sign_in(self):
        cases = (("other", "200,000 paying members watch recorded video lectures."),
                 ("healthtech", "Patients download large imaging files and listen to audio guidance."),
                 ("saas_b2b", "Customers stream a podcast archive and download installers."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                out = run(project__type=typ, desc=desc, scale__users_12_months=9000, scale__peak_concurrent_users=400)
                self.assertTrue(sup(out, "cdn"), desc)

    def test_cdn_still_removed_for_signed_in_apps_without_media(self):
        for typ, desc in (("saas_b2b", "Customers manage invoices and approve purchase orders."),
                          ("fintech", "Customers see balances; video calls with an adviser are one-to-one."),
                          ("other", "Sensor event streams are aggregated into a staff report.")):
            with self.subTest(typ=typ):
                out = run(project__type=typ, desc=desc, scale__users_12_months=9000, scale__peak_concurrent_users=400)
                self.assertFalse(sup(out, "cdn"), desc)

    # B3: public-page wording counts, and the text claims absence only when it is absent
    def test_public_page_wording_keeps_the_cdn_and_the_note_never_denies_it(self):
        for typ, desc in (("fintech", "Public loan comparison pages for anyone; sign-in to apply."),
                          ("saas_b2b", "A public directory of suppliers, sign-in for buyers."),
                          ("other", "Public profiles are visible to anyone; members sign in to edit.")):
            with self.subTest(typ=typ):
                out = run(project__type=typ, desc=desc, scale__users_12_months=9000, scale__peak_concurrent_users=400)
                self.assertTrue(sup(out, "cdn"), desc)
        for typ, desc in (("saas_b2b", "Customers use the public cloud and a public API behind sign-in."),
                          ("fintech", "Public sector clients sign in to a ledger tool.")):
            with self.subTest(must_not_fire=typ):
                out = run(project__type=typ, desc=desc, scale__users_12_months=9000, scale__peak_concurrent_users=400)
                self.assertFalse(sup(out, "cdn"), desc)
                self.assertNotIn("names no public pages", warns(out, "SERVICE_NOT_ADDED")[0]["message"])

    # B4: from tier 2 (over 50,000 users or 2,000 concurrent) a signed-in app keeps the CDN; smaller ones still lose it
    def test_big_signed_in_apps_keep_the_cdn_and_small_ones_do_not(self):
        for typ in ("saas_b2b", "fintech", "healthtech", "data_analytics"):
            with self.subTest(typ=typ):
                self.assertTrue(sup(run(project__type=typ, scale__users_12_months=120000, scale__peak_concurrent_users=3000), "cdn"))
                self.assertFalse(sup(run(project__type=typ, scale__users_12_months=9000, scale__peak_concurrent_users=400), "cdn"))

    def test_tier_two_text_never_claims_one_region_without_a_geo_spread(self):
        for typ in ("internal_tool", "saas_b2b"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, desc="Used only by employees.", scale__users_12_months=120000, scale__peak_concurrent_users=3000)
                self.assertFalse(sup(out, "cdn"))
                msg = warns(out, "SERVICE_NOT_ADDED")[0]["message"]
                self.assertNotIn("served from one region", msg)
                self.assertIn("scale.geo_spread is not given", msg)
        small = run(project__type="internal_tool", desc="Used only by employees.", scale__geo_spread="single_region",
                    scale__users_12_months=9000, scale__peak_concurrent_users=400)
        self.assertIn("served from one region", warns(small, "SERVICE_NOT_ADDED")[0]["message"])


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
        for typ, systems in (("social", ["Discord OAuth"]), ("gaming", ["Steam", "LinkedIn login"]), ("marketplace", ["Discord"])):
            with self.subTest(typ=typ):
                a = self.auth(project__type=typ, requirements__auth="social", infrastructure__existing_systems=systems,
                              team__languages=["javascript"])
                first = a["choice"].split(" with ", 1)[1]
                self.assertTrue(first.startswith(systems[0].split()[0]), a["choice"])
                self.assertIn("sign-in", a["choice"])

    # B2: a vendor name in a different role is never dropped silently: it is an unrecognised system, not a sign-in provider
    def test_vendor_names_in_other_roles_raise_the_unrecognised_warning(self):
        cases = (("social", "Discord community server for support"), ("saas_b2b", "LinkedIn Sales Navigator for lead export"),
                 ("internal_tool", "Steam boiler SCADA historian"), ("marketplace", "Discord"))
        for typ, raw in cases:
            for auth in ("social", "email_password"):
                if raw == "Discord" and auth == "social":
                    continue  # a bare provider name with social sign-in is a sign-in provider (must not warn)
                with self.subTest(typ=typ, auth=auth, raw=raw):
                    out = run(project__type=typ, requirements__auth=auth, infrastructure__existing_systems=[raw], team__languages=["javascript"])
                    self.assertTrue([w for w in warns(out, "EXISTING_SYSTEM_UNRECOGNISED") if raw in w["message"]])
                    self.assertNotIn("The input names", " ".join(s["choice"] + s["justification"] for s in sup(out, "auth")))

    def test_steam_needs_a_game_context(self):
        a = self.auth(project__type="web_app", desc="Players unlock achievements and compare scores.", requirements__auth="social",
                      infrastructure__existing_systems=["Steam"], team__languages=["javascript"])
        self.assertTrue(a["choice"].split(" with ", 1)[1].startswith("Steam"), a["choice"])
        self.assertNotIn("Steam", self.auth(project__type="web_app", requirements__auth="social", infrastructure__existing_systems=["Steam"],
                                            team__languages=["javascript"])["choice"])

    def test_adfs_is_not_treated_as_an_entra_tenant(self):
        # ms_idp means Entra ID (its auth line, the Entra text, Microsoft.Identity.Web); AD FS must keep its own line
        for typ in ("healthtech", "saas_b2b", "internal_tool"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, requirements__auth="enterprise_sso", infrastructure__existing_systems=["AD FS"])
                self.assertIn("AD FS", sup(out, "auth")[0]["choice"])
                self.assertNotIn("Entra", sup(out, "auth")[0]["choice"])

    def test_no_named_provider_keeps_the_default_list(self):
        # G1: the default list follows the audience: work audience keeps Google/GitHub/Microsoft, a consumer app gets Google
        a = self.auth(project__type="saas_b2b", requirements__auth="social", team__languages=["javascript"])
        self.assertTrue(a["choice"].endswith("with Google/GitHub/Microsoft OAuth"), a["choice"])
        a = self.auth(project__type="social", requirements__auth="social", team__languages=["javascript"])
        self.assertTrue(a["choice"].endswith("with Google OAuth"), a["choice"])


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
