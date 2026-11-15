"""p6: false statements found in review, as probe tests (synthetic inputs only)."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402
from engine import costreal  # noqa: E402

EU_PSP = {"project.type": "fintech", "infrastructure.cloud_preference": "azure", "infrastructure.data_residency": "eu",
          "requirements.payments": True, "compliance": ["pci_dss", "gdpr"],
          "project.description": "We are a payment processor for EU merchants; our in-house payment core handles card authorisation and settlement."}
UPI_DESC = "A UPI and IMPS payment switch: we are the payment processor connecting banks to NPCI."
UPI_PSP = {"project.type": "fintech", "infrastructure.data_residency": "india", "requirements.payments": True,
           "compliance": ["pci_dss"], "project.description": UPI_DESC}


def pay(out):
    return sup(out, "payments")[0]


def pci(out):
    return next(w["message"] for w in out["warnings"] if w["code"] == "PCI_SCOPE")


class InHousePaymentCore(unittest.TestCase):
    """Item 1: an in-house payment core runs on the stack, so it inherits the stack's residency region and is never saas."""

    def test_eu_core_inherits_region(self):
        out = run(**EU_PSP)
        p = pay(out)
        self.assertIn("In-house payment core", p["choice"])
        self.assertEqual(p["deployment"], "self_hosted")
        self.assertEqual(p["data_location"], "eu")
        self.assertNotIn("RESIDENCY_UNVERIFIED_SERVICE", codes(out))
        self.assertFalse(any(w["severity"] == "critical" for w in out["warnings"]), out["summary"])

    def test_merchant_checkout_stays_saas(self):
        out = run(**{**EU_PSP, "project.description": "Online shop for EU customers paying by card at checkout."})
        p = pay(out)
        self.assertNotIn("In-house", p["choice"])
        self.assertEqual(p["deployment"], "saas")


class PciNoCards(unittest.TestCase):
    """Item 2: the PCI note agrees with the payments text when the description names no card data."""

    def test_upi_switch_pci_only_if_cards_added(self):
        out = run(**UPI_PSP)
        msg = pci(out)
        self.assertIn("applies only if cards are added later", msg)
        self.assertNotIn("raw card numbers", msg)
        self.assertIn("applies only if cards are added later", pay(out)["justification"])

    def test_card_switch_keeps_full_scope(self):
        out = run(**{**UPI_PSP, "project.description": UPI_DESC + " It also routes RuPay and Visa card payments."})
        msg = pci(out)
        self.assertIn("cardholder data as a service provider", msg)
        self.assertNotIn("applies only if cards are added later", msg)


class NpciOnlyForIndia(unittest.TestCase):
    """Item 3: NPCI is named only for India or UPI inputs."""

    def test_eu_gateway_no_npci(self):
        self.assertNotIn("NPCI", json.dumps(pay(run(**EU_PSP))["tradeoffs"]))

    def test_upi_switch_names_npci(self):
        self.assertIn("Scheme/NPCI certification", json.dumps(pay(run(**UPI_PSP))["tradeoffs"]))


class SourcesDeduped(unittest.TestCase):
    """Item 3: the payment component's sources never repeat a URL; order is first seen."""

    def test_payment_core_sources_unique_first_seen(self):
        src = pay(run(**EU_PSP))["sources"]
        self.assertEqual(src, list(dict.fromkeys(src)))
        self.assertTrue(src[0].startswith("https://blog.pcisecuritystandards.org/"))

    def test_merchant_checkout_sources_unique(self):
        src = pay(run(**{**EU_PSP, "project.description": "Online shop for EU customers paying by card at checkout."}))["sources"]
        self.assertEqual(len(src), len(set(src)))


class CognitoLargeMau(unittest.TestCase):
    """Item 4: above the read tiers the lower bound is not silently capped at 1,000,000 MAU."""

    def test_lower_bound_counts_every_mau(self):
        lo, hi = costreal.cognito_band(40_000_000)
        self.assertEqual(lo, round(costreal.cognito_usd(12_000_000)))
        self.assertGreater(lo, 50_000)
        note = costreal.cognito_note(40_000_000)
        self.assertIn("planning estimate", note)
        self.assertNotIn("counts only the first", note)

    def test_below_threshold_unchanged(self):
        lo, hi = costreal.cognito_band(2_000_000)  # 600,000-2,000,000 MAU: the lower bound is inside the read tiers
        self.assertEqual(lo, round(costreal.cognito_usd(600_000)))
        self.assertNotIn("both bounds apply the last verified rate", costreal.cognito_note(2_000_000))


class OnPremExistingDb(unittest.TestCase):
    """Item 5: a database kept on an on-premises stack inherits the on-premises location and is reached over the LAN."""
    BASE = {"infrastructure.data_residency": "india", "infrastructure.existing_systems": ["Oracle Database 19c"],
            "team.languages": ["java"],
            "project.description": "Internal claims system in our own data centre; it must read and write the existing Oracle database."}

    def test_on_prem_oracle_pinned_and_lan(self):
        out = run(**{**self.BASE, "infrastructure.deployment_model": "on_premise"})
        self.assertIn("Existing Oracle", out["stack"]["database"]["choice"])
        self.assertNotIn("RESIDENCY_UNVERIFIED_SERVICE", codes(out))
        why = out["stack"]["database"]["justification"]
        self.assertIn("local network (LAN)", why)
        self.assertNotIn("VPN", why)

    def test_cloud_stack_keeps_check_and_private_path(self):
        out = run(**{**self.BASE, "infrastructure.deployment_model": "managed_cloud"})
        self.assertIn("Existing Oracle", out["stack"]["database"]["choice"])
        self.assertIn("RESIDENCY_UNVERIFIED_SERVICE", codes(out))
        self.assertIn("VPN / private link", out["stack"]["database"]["justification"])


if __name__ == "__main__":
    unittest.main()
