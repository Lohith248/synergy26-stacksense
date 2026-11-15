"""q8: payments reuse a provider the organisation already has (BRIEF-q2 item 1); a plan to store card data gets a warning (item 3).
Synthetic inputs only."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup  # noqa: E402


def pay(out):
    p = sup(out, "payments")
    return p[0] if p else None


def warn(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


EU_SAAS = {"project.type": "saas_b2b", "requirements.payments": True, "infrastructure.data_residency": "eu",
           "requirements.multi_tenant": True}


class ExistingProviderReused(unittest.TestCase):
    def test_existing_systems_adyen_eu_saas(self):
        out = run(**EU_SAAS, **{"project.description": "B2B invoicing tool; customers pay monthly subscriptions through our existing Adyen merchant account.",
                                "infrastructure.existing_systems": ["Adyen"]})
        p = pay(out)
        self.assertTrue(p["choice"].startswith("Adyen (existing merchant account reused)"), p["choice"])
        self.assertEqual(p["provider"], "adyen")
        for a in p["alternatives"]:  # no alternative argues against the provider the customer already has
            self.assertFalse(a["choice"].startswith("Adyen"), a)
        loc = warn(out, "PAYMENT_DATA_LOCATION")
        self.assertIsNotNone(loc)
        self.assertTrue(loc["message"].startswith("Adyen processes payer data"), loc["message"])
        self.assertNotIn("Stripe processes", json.dumps(out))

    def test_description_only_mollie_ecommerce(self):
        out = run(**{"project.type": "ecommerce", "requirements.payments": True,
                     "project.description": "Online shop for handmade furniture. Orders are paid through our existing Mollie account."})
        p = pay(out)
        self.assertTrue(p["choice"].startswith("Mollie"), p["choice"])
        self.assertIn("not in the knowledge base", p["justification"])  # fees and regions are not invented
        self.assertNotIn("Stripe Billing", p["choice"])

    def test_india_marketplace_payu(self):
        out = run(**{"project.type": "marketplace", "requirements.payments": True, "infrastructure.data_residency": "india",
                     "project.description": "Marketplace for home tutors in Pune. We already have a PayU merchant account and want to keep using it."})
        p = pay(out)
        self.assertTrue(p["choice"].startswith("PayU"), p["choice"])
        self.assertTrue(all(not a["choice"].startswith("PayU") for a in p["alternatives"]))
        self.assertNotIn("Razorpay's standard pricing", json.dumps(p))  # fee text does not borrow the default gateway's price

    def test_existing_default_provider_keeps_stripe_but_says_reused(self):
        out = run(**{"project.type": "web_app", "requirements.payments": True,
                     "project.description": "Booking app for yoga studios.", "infrastructure.existing_systems": ["Stripe account (existing)"]})
        p = pay(out)
        self.assertTrue(p["choice"].startswith("Stripe"), p["choice"])
        self.assertIn("existing account reused", p["choice"])
        self.assertTrue(all("Stripe" not in a["choice"] for a in p["alternatives"]))

    def test_square_pos_for_a_fintech(self):
        out = run(**{"project.type": "fintech", "requirements.payments": True,
                     "project.description": "Loyalty wallet for a cafe chain. We already use Square POS in every branch."})
        self.assertTrue(pay(out)["choice"].startswith("Square"), pay(out)["choice"])

    def test_must_not_fire(self):
        for desc, ex in [
            ("Subscription analytics SaaS. We compared Adyen and Stripe last year and have not chosen one.", []),
            ("Subscription SaaS for gyms. We are migrating away from PayU to a new provider.", ["PayU"]),
            ("Subscription SaaS for gyms; our competitor uses Adyen for its checkout.", []),
            ("Subscription SaaS for gyms. We left Mollie last year.", []),
            ("Subscription SaaS for gyms.", ["Mollie (contract cancelled in 2025)"]),
            ("Subscription SaaS for gyms. We have a PayPal button for donations only.", ["PayPal button for donations only"]),
            ("Subscription SaaS for clubs; clubs keep their own existing Mollie accounts for bar sales.", []),
            ("Subscription SaaS for co-working spaces; we already have 900 square metres of desks.", []),
            ("Subscription SaaS for card shops; we already have a magnetic stripe reader at the till.", []),
        ]:
            out = run(**EU_SAAS, **{"project.description": desc, "infrastructure.existing_systems": ex})
            p = pay(out)
            self.assertTrue(p["choice"].startswith("Stripe"), (desc, p["choice"]))
            self.assertNotIn("existing", p["choice"].lower(), desc)


if __name__ == "__main__":
    unittest.main()
