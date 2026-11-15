"""q3: no false statement, no silent constraint break (synthetic inputs only; no holdout scenario is copied)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402


def nocode(test, kw, code="RESIDENCY_TRANSFER_OUT"):
    out = run(**kw)
    test.assertNotEqual(out["status"], "invalid_input", out.get("validation_errors"))
    test.assertNotIn(code, codes(out), kw.get("project.description"))
    return out


def warn(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


CLINIC_EU = {"project.type": "healthtech", "infrastructure.data_residency": "eu", "compliance": ["gdpr"],
             "project.description": "Physiotherapy clinic booking and treatment notes. Nightly backups of patient records are copied "
                                    "to our disaster-recovery bucket in us-east-1."}
SHOP_IN = {"project.type": "ecommerce", "infrastructure.data_residency": "india",
           "project.description": "Grocery delivery storefront. Order events are replicated to the analytics team's dataset in "
                                  "asia-southeast1 for weekly reporting."}
FLEET_US = {"project.type": "iot", "infrastructure.data_residency": "us",
            "infrastructure.existing_systems": ["Tableau Server hosted in Frankfurt"],
            "project.description": "Cold-chain truck monitoring. Shipment temperature records are synced to Tableau Server for dashboards."}
LEDGER_RBI = {"project.type": "fintech", "infrastructure.data_residency": "none", "compliance": ["rbi_localisation"],
              "requirements.payments": True,
              "project.description": "Merchant loyalty points and payouts. Payment records are mirrored to the group risk cluster in Virginia."}


class TransferOutOfResidency(unittest.TestCase):
    """Item 1: a stated transfer of regulated data out of the residency area is a critical warning."""

    def assertFires(self, out, *words):
        ws = warn(out, "RESIDENCY_TRANSFER_OUT")
        self.assertTrue(ws, codes(out))
        self.assertEqual(ws[0]["severity"], "critical")
        self.assertEqual(out["status"], "ok_with_warnings")
        self.assertIn("aggregated or anonymised", ws[0]["message"])
        for w in words:
            self.assertIn(w, ws[0]["message"])
        return ws[0]

    def test_backup_copy_to_us_region_under_eu(self):
        w = self.assertFires(run(**CLINIC_EU), "us-east-1", "the EU", "GDPR")
        self.assertIn("project.description", w["fields"])
        self.assertIn("infrastructure.data_residency", w["fields"])

    def test_replication_to_singapore_under_india(self):
        self.assertFires(run(**SHOP_IN), "asia-southeast1", "Singapore", "India")

    def test_existing_system_abroad_and_component_agrees(self):
        out = run(**FLEET_US)
        w = self.assertFires(out, "Frankfurt", "the United States")
        self.assertIn("infrastructure.existing_systems", w["fields"])
        comp = next(s for s in sup(out, "other") if "Tableau" in s["choice"])
        self.assertTrue(comp["justification"].startswith("Residency limits this integration"), comp["justification"])
        self.assertIn("not part of this plan", comp["justification"])

    def test_rbi_says_india_only(self):
        w = self.assertFires(run(**LEDGER_RBI), "Virginia", "stored only in India")
        self.assertIn("compliance", w["fields"])

    def test_entry_only_location(self):
        out = run(**{"project.type": "saas_b2b", "infrastructure.data_residency": "india",
                     "infrastructure.existing_systems": ["HubSpot CRM account in the US region"],
                     "project.description": "Subscription billing for gyms; new members are pushed to the CRM."})
        self.assertFires(out, "United States")

    # must-not-fire
    def test_no_residency(self):
        nocode(self, {**CLINIC_EU, "infrastructure.data_residency": "none", "compliance": []})

    def test_place_inside_area(self):
        for kw in ({**SHOP_IN, "project.description": "Order events are replicated to the reporting replica in ap-south-1."},
                   {**SHOP_IN, "project.description": "Order events are replicated to the reporting replica in Mumbai."},
                   {**CLINIC_EU, "project.description": "Nightly backups of patient records are copied to a bucket in Frankfurt."}):
            nocode(self, kw)

    def test_audience_without_transfer(self):
        nocode(self, {**SHOP_IN, "project.description": "Grocery storefront; we also have customers in the US and Singapore buying gift boxes."})

    def test_negated(self):
        for d in ("Payment data never leaves India and is not replicated to us-east-1.",
                  "Order records are never exported to Singapore or the US."):
            nocode(self, {**SHOP_IN, "project.description": d})


if __name__ == "__main__":
    unittest.main()
