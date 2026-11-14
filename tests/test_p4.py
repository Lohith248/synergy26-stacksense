"""P4 (judge C re-score): hosted payment page + web form stays static, provider kept; synthetic inputs only."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402
from test_overengineering import NONE_AUTH, static, dynamic  # noqa: E402


def pay_site(typ, desc, **kw):
    return run(**{**NONE_AUTH, "project.type": typ, "project.description": desc, "requirements.payments": True,
                  "budget.monthly_infra_usd": 15, **kw})


class HostedPaymentWithForm(unittest.TestCase):
    """Item 1: a hosted payment page or link plus a named web form needs no backend, database or second processor."""

    def test_form_and_hosted_page_stay_static(self):
        cases = [
            ("content_site", "Small charity website with stories, a volunteer sign-up form and a Donate button that opens a hosted PayPal donation page.", "paypal"),
            ("other", "Yoga studio pages with a contact form; class passes are bought through a Stripe payment link.", "stripe"),
            ("content_site", "Temple trust site with festival news and an enquiry form. Offerings go through a Razorpay payment link.", "razorpay"),
            ("web_app", "Marketing site and blog for a choir with a newsletter sign-up form and a PayPal donate button.", "paypal"),
        ]
        for typ, desc, prov in cases:
            out = pay_site(typ, desc)
            self.assertTrue(static(out), (typ, out["stack"]["backend"]["choice"]))
            pay = sup(out, "payments")
            self.assertEqual(len(pay), 1, typ)
            self.assertEqual(pay[0]["provider"], prov, typ)
            self.assertIn("hosted", pay[0]["choice"])
            self.assertNotIn("Stripe (Checkout)", pay[0]["choice"])
            form = [s for s in sup(out, "other") if s["choice"].startswith("Web form:")]
            self.assertEqual(len(form), 1, typ)
            self.assertLessEqual(out["estimated_monthly_cost_usd"]["min"], 15, typ)
            self.assertNotIn("BUDGET_EXCEEDED", codes(out), typ)
            self.assertNotIn("SCOPE_VS_TEAM", codes(out), typ)

    def test_donate_button_alternative_only_for_donations(self):  # review SHOULD 2
        def alts(typ, desc):
            return [a["choice"] for a in sup(pay_site(typ, desc), "payments")[0]["alternatives"]]
        for typ, desc in (("content_site", "Charity news site; donations go through a Stripe payment link."),
                          ("other", "NGO pages with a Razorpay payment link for donations."),
                          ("web_app", "Marketing site and blog for an animal shelter; donations go through a Stripe payment link.")):
            self.assertIn("PayPal Donate button", alts(typ, desc), desc)
        for typ, desc in (("other", "Yoga studio pages with a contact form; class passes are bought through a Stripe payment link."),
                          ("content_site", "Bakery site; cake orders are paid through a Razorpay payment link.")):  # must not fire: a shop
            self.assertNotIn("PayPal Donate button", alts(typ, desc), desc)
            self.assertTrue(alts(typ, desc), desc)

    def test_named_provider_without_form_is_kept(self):
        out = pay_site("other", "Open-source project documentation with a PayPal donate button.")
        self.assertTrue(static(out))
        self.assertEqual(sup(out, "payments")[0]["provider"], "paypal")
        self.assertFalse([s for s in sup(out, "other") if s["choice"].startswith("Web form:")])

    # ---- must not fire
    def test_accounts_or_unhosted_payments_keep_the_backend(self):
        for desc, kw in (
            ("Charity site with a volunteer sign-up form; volunteers log in to see their shifts. Donate button opens a hosted PayPal page.", {}),
            ("Charity site with a contact form and donor accounts with a giving history; PayPal donate button.", {}),
            ("Charity site with a volunteer sign-up form. Donations are taken by card on our own checkout and stored.", {}),
            ("Charity site with a contact form and a PayPal donate button.", {"requirements.auth": "email_password"}),
        ):
            out = pay_site("content_site", desc, **kw)
            self.assertTrue(dynamic(out), desc)
            self.assertFalse([s for s in sup(out, "other") if s["choice"].startswith("Web form:")], desc)

    def test_form_plus_per_person_history_keeps_the_backend(self):  # review MUST 1 (probe Q1): stored per-person data is not form-only
        for typ, desc in (
            ("content_site", "Small NGO website with a volunteer sign-up form; volunteers then log their hours and see their past shifts on the site. "
                             "A Donate button opens a hosted PayPal donation page."),
            ("other", "Yoga studio pages with a sign-up form; members see their past bookings online. Class passes are bought through a Stripe payment link."),
            ("web_app", "Choir site with a registration form where singers view their profile and attendance history. PayPal donate button."),
            ("content_site", "Temple trust site with a newsletter sign-up form; devotees check their orders on a personal dashboard. Offerings go through a Razorpay payment link."),
        ):
            out = pay_site(typ, desc)
            self.assertTrue(dynamic(out), desc)
            self.assertFalse([s for s in sup(out, "other") if s["choice"].startswith("Web form:")], desc)

    def test_form_with_no_per_person_data_stays_static(self):  # must not fire: the cue is about stored data, not the form itself
        out = pay_site("content_site", "Small NGO website with stories from our schools, a volunteer sign-up form and a Donate button that opens "
                                       "a hosted PayPal donation page. One volunteer updates it a few times a month.")
        self.assertTrue(static(out))

    def test_form_without_payments_is_unchanged(self):
        # content site without payments was static before p4 and gets no form item (rule scoped to hosted payments)
        out = run(**{**NONE_AUTH, "project.type": "content_site", "requirements.payments": False,
                     "project.description": "Club pages with a contact form."})
        self.assertFalse([s for s in sup(out, "other") if s["choice"].startswith("Web form:")])


def onprem_sqlserver(typ, gb):
    return run(**{"project.type": typ, "infrastructure.deployment_model": "on_premise", "infrastructure.existing_systems": ["Microsoft SQL Server 2019"],
                  "team.languages": ["csharp"], "budget.monthly_infra_usd": 0, "scale.data_volume_gb_12_months": gb})


def lic(out):
    return [a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("SQL Server licence")]


class KbFacts(unittest.TestCase):
    """Item 2: SQL Server is free only as Express (10 GB per database); Django's own auth is not described as missing reset e-mails."""

    def test_sqlserver_licence_is_stated(self):
        for typ, gb in (("healthtech", 300), ("web_app", 50), ("internal_tool", 11)):
            out = onprem_sqlserver(typ, gb)
            self.assertEqual(out["stack"]["database"]["choice"], "SQL Server 2022 (self-hosted)", typ)
            self.assertNotIn("no licence or subscription fee", out["stack"]["database"]["justification"], typ)
            self.assertIn("needs Standard or Enterprise licences", lic(out)[0], typ)
        out = onprem_sqlserver("internal_tool", 5)
        self.assertIn("~5 GB fits it", lic(out)[0])
        self.assertIn("free Express edition (up to 10 GB per database)", out["stack"]["database"]["justification"])

    def test_postgres_keeps_no_licence_text(self):  # must not fire
        out = run(**{"project.type": "web_app", "infrastructure.deployment_model": "on_premise", "team.languages": ["python"],
                     "budget.monthly_infra_usd": 0})
        self.assertIn("No licence or subscription fee", out["stack"]["database"]["justification"])
        self.assertFalse(lic(out))

    def test_django_auth_alternative_is_true(self):
        import json
        raw = json.load(open(os.path.join(ROOT, "..", "research", "fable-review-2026-11-14", "judgeC", "inputs", "C08_mvp_zero_budget.json"), encoding="utf-8"))             if os.path.exists(os.path.join(ROOT, "..", "research", "fable-review-2026-11-14", "judgeC", "inputs", "C08_mvp_zero_budget.json")) else None
        if raw is None:
            self.skipTest("research folder not present")
        from engine.run import evaluate
        out = evaluate(raw, counterfactuals=False)
        a = [s for s in sup(out, "auth") if s["choice"].startswith("Supabase Auth")]
        if out["stack"]["backend"]["kb_id"] == "python-django" and a:
            text = " ".join(x["why_not"] for x in a[0]["alternatives"])
            self.assertNotIn("you would own password storage", text)
            self.assertIn("password-reset e-mail views", text)
            self.assertNotIn("row-level security policies can use the signed-in user id", a[0]["justification"])


def ha_run(typ, cloud, avail="99.95"):
    return run(**{"project.type": typ, "infrastructure.cloud_preference": cloud, "requirements.availability": avail,
                  "budget.monthly_infra_usd": 3000, "scale.users_12_months": 50000, "scale.peak_concurrent_users": 2000})


class AvailabilityBilledOnce(unittest.TestCase):
    """Item 3: a host that replicates across zones itself (Cloud Run) does not get the hosting line billed a second time."""

    def test_zone_replicated_host_has_no_second_instance_line(self):
        for typ in ("web_app", "marketplace", "saas_b2b"):
            for avail in ("99.95", "99.99"):
                out = ha_run(typ, "gcp", avail)
                self.assertEqual(out["stack"]["hosting"]["kb_id"], "gcp-cloud-run", typ)
                a = out["estimated_monthly_cost_usd"]["assumptions"]
                self.assertFalse([x for x in a if "the hosting line counted again" in x], typ)
                self.assertTrue([x for x in a if "replicated across the zones of their region" in x], typ)

    def test_instance_hosts_keep_the_second_instance(self):  # must not fire
        for cloud in ("aws", "azure"):
            a = ha_run("web_app", cloud)["estimated_monthly_cost_usd"]["assumptions"]
            self.assertTrue([x for x in a if "the hosting line counted again" in x], cloud)
            self.assertFalse([x for x in a if "replicated across the zones of their region" in x], cloud)


def vol_run(typ, cloud, gb, files=False, **kw):
    return run(**{"project.type": typ, "infrastructure.cloud_preference": cloud, "scale.data_volume_gb_12_months": gb,
                  "requirements.file_media_storage": files, "budget.monthly_infra_usd": 20000, "scale.users_12_months": 500000,
                  "scale.peak_concurrent_users": 20000, **kw})


class StorageLimit(unittest.TestCase):
    """Item 4: a year-one volume above the managed database's per-instance limit is warned about, with the scale-out route."""

    def test_volume_above_limit_warns(self):
        for typ, cloud, gb, files, product in (("social", "gcp", 200000, True, "Cloud SQL"), ("web_app", "aws", 100000, False, "Amazon RDS"),
                                               ("saas_b2b", "azure", 40000, False, "Azure Database for PostgreSQL")):
            out = vol_run(typ, cloud, gb, files)
            w = [x for x in out["warnings"] if x["code"] == "DB_STORAGE_LIMIT"]
            self.assertEqual(len(w), 1, typ)
            self.assertIn(product, w[0]["message"])
            self.assertIn("shard", w[0]["message"])
            self.assertEqual("Media files" in w[0]["message"], files, typ)

    def lim(self, out):
        return [x for x in out["warnings"] if x["code"] == "DB_STORAGE_LIMIT"]

    def test_gib_limits_are_compared_in_gb(self):  # review MUST 2: 32,767 GiB = 35,184 GB, 64 TiB = 70,369 GB
        for typ, cloud, gb, fires in (("ai_ml_product", "azure", 33000, False), ("saas_b2b", "azure", 35000, False), ("saas_b2b", "azure", 35300, True),
                                      ("web_app", "aws", 68000, False), ("social", "aws", 70500, True)):
            self.assertEqual(len(self.lim(vol_run(typ, cloud, gb))), int(fires), (cloud, gb))

    def test_severity_and_azure_v2_route(self):  # review SHOULD 1
        out = vol_run("social", "gcp", 200000, True)
        self.assertEqual(self.lim(out)[0]["severity"], "info")  # media go to object storage: only the relational share counts
        self.assertEqual(self.lim(vol_run("web_app", "aws", 100000))[0]["severity"], "warning")
        for typ, gb, files in (("saas_b2b", 40000, False), ("social", 50000, True), ("marketplace", 60000, False)):
            m = self.lim(vol_run(typ, "azure", gb, files))[0]
            self.assertEqual(m["severity"], "info" if files else "warning", typ)
            self.assertIn("Premium SSD v2", m["message"])
            self.assertLess(m["message"].index("Premium SSD v2"), m["message"].index("shard"), typ)
        m = self.lim(vol_run("web_app", "azure", 80000))[0]["message"]  # above v2 too: v2 is not offered as the fix
        self.assertIn("above Premium SSD v2", m)

    def test_volume_below_limit_or_self_hosted_is_quiet(self):  # must not fire
        for kw in ({"scale.data_volume_gb_12_months": 20000}, {"infrastructure.deployment_model": "on_premise"}):
            out = vol_run("web_app", "gcp", 200000, **kw)
            self.assertNotIn("DB_STORAGE_LIMIT", codes(out), kw)


def infer_run(typ, langs, **kw):
    return run(**{"project.type": typ, "team.languages": langs, "team.size": 10, "requirements.ml_features": "inference_api",
                  "project.description": "Recommends items to users from their history.", "scale.users_12_months": 200000,
                  "budget.monthly_infra_usd": 5000, **kw})


class InferenceSkillGap(unittest.TestCase):
    """Item 5: a separate Python inference service for a team without Python gets SKILL_MISMATCH (D24-p2 rule, inference side)."""

    def gap(self, out):
        return [w for w in out["warnings"] if w["code"] == "SKILL_MISMATCH" and w["message"].startswith("ML inference")]

    def test_python_service_without_python_warns(self):
        for typ, langs in (("social", ["go", "typescript"]), ("ecommerce", ["java"]), ("fintech", ["csharp"])):
            out = infer_run(typ, langs)
            ml = [s for s in sup(out, "ml") if s["choice"].startswith("Separate Python inference service")]
            self.assertTrue(ml, typ)
            g = self.gap(out)
            self.assertEqual(len(g), 1, typ)
            self.assertIn(langs[0], g[0]["message"])

    def test_python_team_or_no_languages_is_quiet(self):  # must not fire
        self.assertFalse(self.gap(infer_run("social", ["go", "python"])))
        self.assertFalse(self.gap(infer_run("social", [])))


if __name__ == "__main__":
    unittest.main()
