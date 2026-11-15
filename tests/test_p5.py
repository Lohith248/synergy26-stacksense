"""p5 (Fable review): remove false statements a judge marks down; synthetic inputs only."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402


def text(out):
    return json.dumps(out, ensure_ascii=False)


class PaymentProviderItself(unittest.TestCase):
    """Item 1: a gateway / processor / switch is the payment provider: no merchant checkout, no SAQ A, network link in scope."""

    def test_provider_shapes(self):
        cases = [
            ("fintech", "Payment gateway for online merchants: we store and process card data, tokenise cards and route payments to acquiring banks.", ["pci_dss"]),
            ("fintech", "UPI and IMPS payment switch for cooperative banks: connects member banks to NPCI, routes and settles transactions.", []),
            ("other", "Card processor for regional banks: authorises card transactions from POS terminals and routes them to Visa and Mastercard.", ["pci_dss"]),
            ("api_platform", "Payments API that connects small lenders to the card networks and settles card repayments.", []),
        ]
        for typ, desc, comp in cases:
            out = run(**{"project.type": typ, "project.description": desc, "requirements.payments": True, "compliance": comp})
            pay = sup(out, "payments")
            self.assertEqual(len(pay), 1, desc)
            self.assertIn("In-house payment core", pay[0]["choice"], desc)
            self.assertNotIn("Stripe (Checkout)", pay[0]["choice"])
            self.assertNotIn("Razorpay (UPI", pay[0]["choice"])
            self.assertNotIn("can qualify for PCI DSS SAQ A", pay[0]["justification"])
            self.assertIn("part of this design", pay[0]["justification"])

    def test_scheme_link_is_in_scope(self):
        out = run(**{"project.type": "fintech", "requirements.payments": True, "infrastructure.existing_systems": ["Visa network link (legacy)"],
                     "project.description": "Card processor for credit unions that routes card transactions to card networks."})
        self.assertNotIn("assumed to sit outside this design", text(out))

    def test_shops_keep_hosted_checkout(self):
        for typ, desc in (("ecommerce", "Online store for a weavers' cooperative; UPI and card payments through a payment gateway."),
                          ("marketplace", "Marketplace where designers sell templates; buyers pay by card and sellers get payouts."),
                          ("web_app", "Event ticketing site; we never store card data, the gateway's checkout does.")):
            out = run(**{"project.type": typ, "project.description": desc, "requirements.payments": True})
            pay = sup(out, "payments")
            self.assertTrue(pay and "In-house payment core" not in pay[0]["choice"], desc)


class MobileMoney(unittest.TestCase):
    """Item 2: mobile-money wallets need a mobile-money API or aggregator, not a card checkout; East Africa is not South Africa."""

    def test_wallet_payments(self):
        for typ, desc in (("fintech", "Savings-group app for chamas in Kenya: members contribute through M-Pesa."),
                          ("web_app", "School-fees portal for schools in Uganda; parents pay with MTN MoMo or Airtel Money."),
                          ("ecommerce", "Grocery delivery shop in East Africa accepting mobile money payments at checkout."),
                          ("other", "Offline-first point-of-sale app for kiosks in Tanzania that accepts mobile-money payments.")):
            out = run(**{"project.type": typ, "project.description": desc, "requirements.payments": True, "infrastructure.data_residency": "other"})
            pay = sup(out, "payments")
            self.assertEqual(len(pay), 1, desc)
            self.assertIn("Mobile-money", pay[0]["choice"], desc)
            self.assertNotEqual(pay[0]["provider"], "stripe")
            self.assertNotIn("SAQ A", pay[0]["justification"])
            self.assertNotIn("South Africa", text(out), desc)

    def test_card_shop_keeps_gateway(self):
        out = run(**{"project.type": "ecommerce", "project.description": "Online bookshop in Cape Town, South Africa, taking card payments.",
                     "requirements.payments": True, "infrastructure.data_residency": "other"})
        self.assertNotIn("Mobile-money", sup(out, "payments")[0]["choice"])
        self.assertIn("South Africa", text(out))


class LiveQuizWording(unittest.TestCase):
    """Item 3: a live timed quiz is not turn-based; a p95 target under the threshold is never contradicted."""

    def test_live_quiz(self):
        for desc, lat in (("Live multiplayer trivia quiz: players answer timed questions at the same moment.", 80),
                          ("Quiz show app where thousands answer each question within 10 seconds simultaneously.", 150),
                          ("Classroom quiz game played live: the teacher starts a countdown and pupils buzz in.", 90)):
            out = run(**{"project.type": "gaming", "project.description": desc, "requirements.realtime": True, "requirements.p95_latency_ms": lat})
            t = text(out)
            self.assertNotIn("turn-based", t, desc)
            self.assertIn("live, timed quiz", t, desc)
            if lat <= 100:
                self.assertNotIn("needs p95 latency of 100 ms or less", t, desc)

    def test_turn_based_kept(self):
        out = run(**{"project.type": "gaming", "project.description": "Trivia game where friends take their turns whenever they like.",
                     "requirements.realtime": True, "requirements.p95_latency_ms": 300})
        self.assertIn("turn-based", text(out))


if __name__ == "__main__":
    unittest.main()
