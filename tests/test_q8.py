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


class CardStoragePlanWarned(unittest.TestCase):
    def test_ecommerce_with_pci_is_critical(self):
        out = run(**{"project.type": "ecommerce", "requirements.payments": True, "compliance": ["pci_dss"],
                     "project.description": "Coffee subscription shop. We plan to keep customers' full card numbers in our own database for re-billing."})
        w = warn(out, "CARD_DATA_STORAGE")
        self.assertIsNotNone(w)
        self.assertEqual(w["severity"], "critical")
        for word in ("PCI DSS", "SAQ D", "CVV", "token", "replaces", "full card numbers in our own database"):
            self.assertIn(word, w["message"])
        self.assertIn("compliance", w["fields"])
        self.assertIn("replaced by the provider's tokens", pay(out)["justification"])

    def test_marketplace_cvv_critical_without_pci_listed(self):
        out = run(**{"project.type": "marketplace", "requirements.payments": True,
                     "project.description": "Ticket resale marketplace; we save card numbers and CVV codes so buyers can check out in one click."})
        w = warn(out, "CARD_DATA_STORAGE")
        self.assertEqual(w["severity"], "critical")
        self.assertNotIn("compliance", w["fields"])

    def test_web_app_is_warning(self):
        out = run(**{"project.type": "web_app", "requirements.payments": True,
                     "project.description": "Gym booking site. Members' credit card numbers will be stored in our database so staff can charge no-show fees."})
        self.assertEqual(warn(out, "CARD_DATA_STORAGE")["severity"], "warning")

    def test_healthtech_pans_in_capitals(self):
        out = run(**{"project.type": "healthtech", "requirements.payments": True,
                     "project.description": "Clinic billing portal. The billing table stores PANs and expiry dates so the front desk can retry a declined copay."})
        self.assertEqual(warn(out, "CARD_DATA_STORAGE")["severity"], "warning")

    def test_must_not_fire(self):
        for desc in ["Coffee subscription shop. We never store card numbers; the gateway keeps them.",
                     "Coffee subscription shop. Card numbers must not be stored on our servers.",
                     "Coffee subscription shop. We store order history and delivery addresses in our database.",
                     "Coffee subscription shop. We store only the last four digits of the card number for receipts.",
                     "Coffee subscription shop. We save loyalty card numbers so members collect points.",
                     "Coffee subscription shop. Staff upload card-sized photos of each blend and we keep them in the catalogue.",
                     "Coffee subscription shop. For KYC we record the customer's PAN card and Aadhaar number.",
                     "Coffee subscription shop. The provider's vault stores card details and gives us a token.",
                     "Coffee subscription shop. We keep SIM card details of the delivery riders."]:
            out = run(**{"project.type": "ecommerce", "requirements.payments": True, "compliance": ["pci_dss"], "project.description": desc})
            self.assertIsNone(warn(out, "CARD_DATA_STORAGE"), desc)
            self.assertNotIn("replaced by the provider's tokens", pay(out)["justification"], desc)


if __name__ == "__main__":
    unittest.main()
