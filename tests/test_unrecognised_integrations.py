"""Track f2, A7: unrecognised existing systems get a description-driven integration instead of "assumed to sit outside".
Synthetic inputs only: no scenario ids or product titles."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402
from engine import integrations as ig  # noqa: E402

SMALL = {"scale.users_at_launch": 200, "scale.users_12_months": 900, "scale.peak_concurrent_users": 40,
         "team.size": 2, "budget.monthly_infra_usd": 150}


def warn(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


def others(out):
    return [s["choice"] for s in sup(out, "other")]


class UnrecognisedIntegrations(unittest.TestCase):
    def one(self, typ, entry, desc, **kw):
        return run(**{**SMALL, "project.type": typ, "project.description": desc, "infrastructure.existing_systems": [entry], **kw})

    def assertComponent(self, out, needle):
        self.assertTrue([c for c in others(out) if needle in c], (needle, others(out)))
        self.assertFalse([a for a in out["assumptions"] if "sit outside this design" in a], out["assumptions"])

    def test_file_exchange(self):
        for typ, entry, desc in [("internal_tool", "Payroll CSV import", "Staff lunch orders. Payroll deduction is a CSV export."),
                                 ("web_app", "Excel catalogue exported as CSV", "Library loans. Data currently lives in one Excel file."),
                                 ("saas_b2b", "Partner price lists (XML)", "Quoting tool that imports partner price lists every night.")]:
            self.assertComponent(self.one(typ, entry, desc), "File ")

    def test_webhook_feed(self):
        for typ, entry, desc in [("web_app", "Licensed results feed (push webhooks)", "Fantasy league with live scores from a licensed feed."),
                                 ("marketplace", "Carrier tracking callbacks", "Marketplace where carriers push tracking updates to us."),
                                 ("api_platform", "Partner event feed", "Receives a partner's event feed in real time.")]:
            self.assertComponent(self.one(typ, entry, desc), "Inbound webhook")

    def test_accounting_adapter(self):
        out = self.one("fintech", "Tally Prime (accounting)", "Co-op ledger. Accounts are exported to Tally Prime.")
        self.assertComponent(out, "Accounting / billing adapter")

    def test_named_protocols(self):
        for typ, entry, desc, proto in [("data_analytics", "Plant OPC UA gateway", "Dashboards of plant readings pulled from the gateway.", "OPC UA"),
                                        ("healthtech", "Ward system", "Reads admissions from the ward system over MLLP.", "HL7 v2 over MLLP"),
                                        ("web_app", "SMPP aggregator", "Sends reminders by SMS through the aggregator.", "SMPP"),
                                        ("web_app", "Core claims system (Acme Claims)", "Must call the core claims system (Acme Claims), then show the status.",
                                         "Integration adapter")]:
            out = self.one(typ, entry, desc)
            self.assertComponent(out, proto)
            self.assertTrue(warn(out, "EXISTING_SYSTEM_UNRECOGNISED"))

    def test_no_evidence_keeps_the_honest_assumption(self):
        out = self.one("web_app", "Zorblax Frobnicator", "A club website with member news.")
        self.assertTrue([a for a in out["assumptions"] if "sit outside this design" in a])
        self.assertFalse([c for c in others(out) if "Zorblax" in c])

    def test_system_being_replaced_gets_no_adapter_and_says_so(self):
        out = self.one("web_app", "Zorblax admin console", "Booking site. The old Zorblax console must be replaced by the new admin screens.")
        self.assertFalse([c for c in others(out) if "Zorblax" in c])
        self.assertTrue([a for a in out["assumptions"] if "going away" in a], out["assumptions"])
        self.assertFalse([a for a in out["assumptions"] if "sit outside this design" in a])

    def test_replace_verb_about_another_system_does_not_retire_this_one(self):
        out = self.one("web_app", "Zorblax login", "Forum site. Migrating off a creaking old board and keeping Zorblax login.")
        self.assertFalse([a for a in out["assumptions"] if "going away" in a], out["assumptions"])
        out = self.one("web_app", "Zorblax billing (to be replaced)", "Shop site that bills customers each month.")
        self.assertTrue([a for a in out["assumptions"] if "going away" in a], out["assumptions"])

    def test_description_reaches_a_database_through_the_existing_broker(self):
        out = self.one("saas_b2b", "Core DB2 database", "Reads member records from the core database via MQ.",
                       **{"infrastructure.existing_systems": ["Core DB2 database", "IBM MQ"]})
        integ = [c for c in others(out) if "Core DB2" in c]
        self.assertTrue(integ and "IBM MQ" in integ[0] and "queues" in integ[0], others(out))
        self.assertTrue(sup(out, "queue"))
        plain = self.one("saas_b2b", "Core DB2 database", "Reads member records from the core database.",
                         **{"infrastructure.existing_systems": ["Core DB2 database", "IBM MQ"]})
        self.assertFalse([c for c in others(plain) if "queues" in c])

    def test_recognised_systems_are_unchanged(self):
        out = self.one("saas_b2b", "Okta", "B2B portal; staff sign in through Okta and the portal reads reports from it.",
                       **{"requirements.auth": "enterprise_sso"})
        self.assertFalse([c for c in others(out) if "adapter" in c.lower()])
        self.assertFalse(warn(out, "EXISTING_SYSTEM_UNRECOGNISED"))

    def test_infer_unit(self):
        self.assertIsNone(ig.infer("Zorblax Frobnicator", "A club website."))
        self.assertEqual(ig.infer("Zorblax", "The app reads rows from Zorblax via MQ.")["protocol"], "MQ messaging")
        self.assertIn(ig.infer("Zorblax", "Orders are exported to Zorblax.")["kind"], ("api", "file", "accounting"))


if __name__ == "__main__":
    unittest.main()
