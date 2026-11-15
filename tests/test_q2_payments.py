"""q2: payments honour a provider the organisation already has; requested local methods are named; card-number storage plans get a warning.
Synthetic inputs only."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402


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
        self.assertTrue(p["choice"].startswith("Adyen"), p["choice"])
        self.assertIn("existing", p["choice"].lower())
        self.assertEqual(p["provider"], "adyen")
        self.assertNotIn("Stripe", p["choice"])
        for a in p["alternatives"]:  # no alternative argues against the provider the customer already has
            self.assertFalse(a["choice"].startswith("Adyen"), a)
        loc = warn(out, "PAYMENT_DATA_LOCATION")
        if loc:
            self.assertIn("Adyen", loc["message"])
            self.assertNotIn("Stripe processes", loc["message"])
        self.assertNotIn("Stripe processes", json.dumps(out))

    def test_description_only_mollie_ecommerce(self):
        out = run(**{"project.type": "ecommerce", "requirements.payments": True,
                     "project.description": "Online shop for handmade furniture. Orders are paid through our existing Mollie account."})
        p = pay(out)
        self.assertTrue(p["choice"].startswith("Mollie"), p["choice"])
        self.assertIn("not in the knowledge base", p["justification"])  # fees and regions are not invented
        self.assertNotIn("Stripe Billing", p["choice"])
        self.assertIsNone(warn(out, "PAYMENT_LOCAL_ACQUIRING"))

    def test_india_marketplace_payu(self):
        out = run(**{"project.type": "marketplace", "requirements.payments": True, "infrastructure.data_residency": "india",
                     "project.description": "Marketplace for home tutors in Pune. We already have a PayU merchant account and want to keep using it."})
        p = pay(out)
        self.assertTrue(p["choice"].startswith("PayU"), p["choice"])
        self.assertNotIn("Razorpay (UPI", p["choice"])
        self.assertTrue(all(not a["choice"].startswith("PayU") for a in p["alternatives"]))

    def test_existing_default_provider_keeps_stripe_but_says_reused(self):
        out = run(**{"project.type": "web_app", "requirements.payments": True,
                     "project.description": "Booking app for yoga studios.", "infrastructure.existing_systems": ["Stripe account (existing)"]})
        p = pay(out)
        self.assertTrue(p["choice"].startswith("Stripe"), p["choice"])
        self.assertIn("existing", p["justification"].lower())
        self.assertTrue(all("Stripe" not in a["choice"] for a in p["alternatives"]))

    def test_must_not_fire(self):
        for desc, ex in [
            ("Subscription analytics SaaS. We compared Adyen and Stripe last year and have not chosen one.", []),
            ("Subscription SaaS for gyms. We are migrating away from PayU to a new provider.", ["PayU"]),
            ("Subscription SaaS for gyms; our competitor uses Adyen for its checkout.", []),
        ]:
            out = run(**EU_SAAS, **{"project.description": desc, "infrastructure.existing_systems": ex})
            p = pay(out)
            self.assertTrue(p["choice"].startswith("Stripe"), (desc, p["choice"]))
            self.assertNotIn("existing", p["choice"].lower(), desc)


class RequestedMethodsNamed(unittest.TestCase):
    def test_brazil_marketplace_pix_boleto(self):
        out = run(**{"project.type": "marketplace", "requirements.payments": True, "infrastructure.data_residency": "other",
                     "infrastructure.residency_country": "brazil",
                     "project.description": "Marketplace for used bikes in Curitiba; buyers pay with Pix or boleto and sellers are paid monthly."})
        j = pay(out)["justification"]
        self.assertIn("Pix", j)
        self.assertIn("Boleto", j)
        self.assertRegex(j, r"verified in the knowledge base|not confirmed in the knowledge base")

    def test_dutch_shop_ideal(self):
        out = run(**{"project.type": "ecommerce", "requirements.payments": True, "infrastructure.data_residency": "eu",
                     "project.description": "Webshop for Dutch plant lovers; most customers want to pay with iDEAL."})
        self.assertIn("iDEAL", pay(out)["justification"])

    def test_existing_adyen_sepa_names_provider(self):
        out = run(**EU_SAAS, **{"project.description": "Payroll SaaS; clients pay by SEPA Direct Debit through our existing Adyen merchant account.",
                                "infrastructure.existing_systems": ["Adyen"]})
        j = pay(out)["justification"]
        self.assertIn("SEPA Direct Debit", j)
        self.assertIn("Adyen support for", j)

    def test_must_not_fire(self):
        for desc in ["Webshop for kitchen knives; card payments only.", "Webshop for kitchen knives; we do not accept boleto."]:
            out = run(**{"project.type": "ecommerce", "requirements.payments": True, "project.description": desc})
            j = pay(out)["justification"]
            self.assertNotIn("Payment methods the description asks for", j, desc)


class CardStoragePlanWarned(unittest.TestCase):
    def test_ecommerce_with_pci_is_critical(self):
        out = run(**{"project.type": "ecommerce", "requirements.payments": True, "compliance": ["pci_dss"],
                     "project.description": "Coffee subscription shop. We plan to keep customers' full card numbers in our own database for re-billing."})
        w = warn(out, "CARD_DATA_STORAGE")
        self.assertIsNotNone(w)
        self.assertEqual(w["severity"], "critical")
        for word in ("PCI DSS", "SAQ D", "CVV", "token", "replaces"):
            self.assertIn(word, w["message"])

    def test_marketplace_cvv_critical_without_pci_listed(self):
        out = run(**{"project.type": "marketplace", "requirements.payments": True,
                     "project.description": "Ticket resale marketplace; we save card numbers and CVV codes so buyers can check out in one click."})
        self.assertEqual(warn(out, "CARD_DATA_STORAGE")["severity"], "critical")

    def test_web_app_is_warning(self):
        out = run(**{"project.type": "web_app", "requirements.payments": True,
                     "project.description": "Gym booking site. Members' credit card numbers will be stored in our database so staff can charge no-show fees."})
        self.assertEqual(warn(out, "CARD_DATA_STORAGE")["severity"], "warning")

    def test_must_not_fire(self):
        for desc in ["Coffee subscription shop. We never store card numbers; the gateway keeps them.",
                     "Coffee subscription shop. Card numbers must not be stored on our servers.",
                     "Coffee subscription shop. We store order history and delivery addresses in our database."]:
            out = run(**{"project.type": "ecommerce", "requirements.payments": True, "compliance": ["pci_dss"], "project.description": desc})
            self.assertIsNone(warn(out, "CARD_DATA_STORAGE"), desc)


if __name__ == "__main__":
    unittest.main()
