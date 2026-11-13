"""Over-engineering guard (D16, track E12). Synthetic inputs only (no scenario ids or product names).
Each rule: three or more project types where it fires, at least two where it must not, and boundary cases."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import S, run, sup, codes  # noqa: E402
from engine import overeng as ov  # noqa: E402
from engine.run import evaluate  # noqa: E402

NONE_AUTH = {"requirements.auth": "none", "team.size": 1, "team.experience": "beginner", "budget.monthly_infra_usd": 20}


def static(out):
    return (out["architecture_style"] == "static" and out["stack"]["backend"]["choice"] == "None"
            and out["stack"]["database"]["choice"] == "None")


def dynamic(out):
    return out["stack"]["backend"]["choice"] != "None" and out["stack"]["database"]["choice"] != "None"


class StaticEligible(unittest.TestCase):
    """Rule 1: nothing dynamic in the fields, and payments (if any) are a hosted button or link -> static; traffic never changes it."""

    def test_hosted_payments_site_is_static(self):
        cases = [
            ("other", "Small church website: service times and an online donation button. Volunteers update the text. No user accounts."),
            ("content_site", "Photography studio site with a gallery. Clients pay a deposit through a Stripe payment link."),
            ("web_app", "Neighbourhood association brochure site with news. Dues are collected with a hosted checkout page."),
            ("other", "Open-source project documentation with a PayPal donate button."),
        ]
        for typ, desc in cases:
            out = run(**{**NONE_AUTH, "project.type": typ, "project.description": desc, "requirements.payments": True})
            self.assertTrue(static(out), (typ, out["architecture_style"], out["stack"]["backend"]["choice"]))
            self.assertEqual(out["stack"]["hosting"]["kb_id"] in ("cloudflare-pages", "github-pages", "netlify", "aws-s3-cloudfront",
                                                                  "azure-static-web-apps", "firebase-hosting"), True)
            pay = sup(out, "payments")
            self.assertEqual(len(pay), 1, typ)
            self.assertNotIn("webhook", pay[0]["justification"].replace("no webhook server", ""), typ)  # no false webhook claim
            self.assertIn("hosted", pay[0]["justification"])
            self.assertNotIn("cache", [s["layer"] for s in out["stack"]["supporting"]])
            self.assertNotIn("cdn", [s["layer"] for s in out["stack"]["supporting"]])  # the static host is the CDN
            self.assertTrue(any("over-engineering guard" in a for a in out["assumptions"]), typ)

    def test_why_not_quotes_inputs_and_says_when_to_add_a_backend(self):
        out = run(**{**NONE_AUTH, "project.type": "other", "requirements.payments": True,
                     "project.description": "Church site with a donation button. No accounts."})
        alts = out["stack"]["backend"]["alternatives"]
        text = " ".join(a["why_not"] for a in alts)
        self.assertIn("requirements.auth is none", text)
        self.assertIn("donation button", text)
        self.assertIn("add a backend when accounts, stored user data or server-side payments appear", text)
        self.assertIn("add a database when", " ".join(a["why_not"] for a in out["stack"]["database"]["alternatives"]))
        self.assertNotIn("SCOPE_VS_TEAM", codes(out))  # a hosted button is not a payments build

    def test_editorial_content_under_generic_type_is_static(self):
        cases = [("web_app", "Marketing site and blog for a bakery with the menu and opening hours."),
                 ("internal_tool", "Read-only company handbook: policy pages for staff."),
                 ("web_app", "Documentation site for a library, published as static pages.")]
        for typ, desc in cases:
            out = run(**{**NONE_AUTH, "project.type": typ, "project.description": desc, "requirements.payments": False})
            self.assertTrue(static(out), typ)

    def test_high_traffic_alone_does_not_add_backend_or_database(self):
        big = {"scale.users_at_launch": 200000, "scale.users_12_months": 5000000, "scale.peak_concurrent_users": 100000,
               "scale.workload": "read_heavy", "budget.monthly_infra_usd": 40}
        for typ, desc, pay in (("content_site", "Public news pages read by millions.", False),
                               ("web_app", "Marketing site and blog for a product with millions of visitors.", False),
                               ("other", "Charity site with press releases and a donation button.", True)):
            out = run(**{**NONE_AUTH, **big, "project.type": typ, "project.description": desc, "requirements.payments": pay})
            self.assertTrue(static(out), typ)
            self.assertNotIn("SCALE_VS_BUDGET", codes(out), typ)
            self.assertIn("CDN", out["stack"]["backend"]["justification"], typ)  # traffic is explained, not ignored
            self.assertIn("5,000,000", out["stack"]["backend"]["justification"], typ)

    # ---- must not fire
    def test_donor_accounts_keep_the_backend(self):
        for kw in ({"requirements.auth": "email_password"},
                   {"project.description": "Church site with a donation button; donors get donor accounts and a giving history."},
                   {"project.description": "Church site with a donation button. Members log in to see their giving."}):
            args = {**NONE_AUTH, "project.type": "other", "requirements.payments": True,
                    "project.description": "Church site with a donation button."}
            args.update(kw)
            self.assertTrue(dynamic(run(**args)), kw)

    def test_blog_with_logins_keeps_the_backend(self):
        for typ in ("web_app", "content_site"):
            out = run(**{**NONE_AUTH, "requirements.auth": "email_password", "project.type": typ,
                         "project.description": "Blog and news site where readers sign up and leave comments."})
            self.assertTrue(dynamic(out), typ)

    def test_high_traffic_api_keeps_the_backend(self):
        out = run(**{**NONE_AUTH, "project.type": "api_platform", "project.platforms": ["api_only"], "scale.users_12_months": 5000000,
                     "project.description": "Public weather API with millions of calls."})
        self.assertTrue(dynamic(out))

    def test_payments_without_hosted_evidence_keep_the_backend(self):
        for desc in ("Studio site. Checkout is built into the site and orders are stored.", "Site with blog pages and online payments.",
                     "Church site. We do not offer a donation button; gifts are taken in person."):
            out = run(**{**NONE_AUTH, "project.type": "other", "requirements.payments": True, "project.description": desc})
            self.assertTrue(dynamic(out), desc)

    def test_dynamic_types_deployment_and_existing_systems_keep_the_backend(self):
        base = {**NONE_AUTH, "requirements.payments": True, "project.description": "Shop with a payment link on each product page."}
        self.assertTrue(dynamic(run(**{**base, "project.type": "ecommerce"})))
        self.assertTrue(dynamic(run(**{**base, "project.type": "other", "project.description": "Site with a donation button.",
                                       "infrastructure.deployment_model": "on_premise"})))
        self.assertTrue(dynamic(run(**{**base, "project.type": "other", "project.description": "Site with a donation button.",
                                       "infrastructure.existing_systems": ["WordPress 6 on shared hosting"]})))
        self.assertTrue(dynamic(run(**{**base, "project.type": "other", "project.description": "Site with a donation button.",
                                       "compliance": ["hipaa"]})))
        self.assertTrue(dynamic(run(**{**base, "project.type": "other", "project.description": "Site with a donation button.",
                                       "scale.workload": "write_heavy"})))

    def test_boundaries_of_the_signals(self):
        # negated button: payments are then not hosted -> backend
        out = run(**{**NONE_AUTH, "project.type": "other", "requirements.payments": True,
                     "project.description": "Club site. There is no donation button; payments are handled in the app."})
        self.assertTrue(dynamic(out))
        # editorial words but a soft type with a login field stays dynamic
        out = run(**{**NONE_AUTH, "requirements.auth": "social", "project.type": "web_app",
                     "project.description": "Marketing site and blog."})
        self.assertTrue(dynamic(out))
        # a soft type without editorial evidence stays dynamic
        self.assertTrue(dynamic(run(**{**NONE_AUTH, "project.type": "web_app", "project.description": "An app for teams."})))
        # type 'other' without payments was already static and still is
        self.assertTrue(static(run(**{**NONE_AUTH, "project.type": "other", "requirements.payments": False,
                                      "project.description": "Landing page."})))

    def test_no_scenario_names_in_engine(self):
        import glob
        for p in glob.glob(os.path.join(ROOT, "engine", "*.py")):
            with open(p, encoding="utf-8") as f:
                src = f.read()
            for name in ("GraceGives", "InkLetter", "CharityRise", "TryOnAR", "SchoolOne", "LedgerBridge", "UniTime"):
                self.assertNotIn(name, src, p)


if __name__ == "__main__":
    unittest.main()
