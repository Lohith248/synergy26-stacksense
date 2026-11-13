"""E9 explanation quality: supporting and core text is built from the scenario's own facts, and a clause is dropped when its
premise is absent. Synthetic inputs only (no scenario ids). Each rule: three project types where it applies, one where it must not."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup  # noqa: E402

BIG = {"scale.users_12_months": 100000, "scale.peak_concurrent_users": 4000}


def texts(out, layer):
    return [s["justification"] for s in sup(out, layer)]


class CiCd(unittest.TestCase):
    def test_no_free_minutes_claim_and_names_what_runs(self):
        for typ, size in (("web_app", 3), ("saas_b2b", 40), ("marketplace", 12), ("content_site", 1)):
            out = run(**{"project.type": typ, "team.size": size})
            ci = texts(out, "ci_cd")[0]
            self.assertNotIn("free minutes", ci, typ)
            self.assertIn(f"team of {size}", ci, typ)
            self.assertIn("on every push", ci, typ)
        big = texts(run(**{"project.type": "saas_b2b", "team.size": 40}), "ci_cd")[0]
        self.assertIn("$12/month", big)  # the verified GitHub Free allowance is quoted only where the reserve exceeds it
        small = texts(run(**{"project.type": "web_app", "team.size": 3}), "ci_cd")[0]
        self.assertNotIn("$12", small)


class Tenant(unittest.TestCase):
    def test_tenant_text_has_no_boards_and_names_the_mechanism(self):
        for typ in ("saas_b2b", "healthtech", "data_analytics"):
            out = run(**{"project.type": typ, "requirements.multi_tenant": True})
            t = next(s for s in sup(out, "other") if s["choice"].startswith("Tenant isolation"))
            self.assertNotIn("boards", t["justification"], typ)
            self.assertIn("another organisation's data", t["justification"], typ)
            rls = "row-level security" in t["choice"]
            self.assertEqual("enforced in the database" in t["justification"], rls, typ)  # claim follows the chosen mechanism
        out = run(**{"project.type": "saas_b2b", "requirements.multi_tenant": False})
        self.assertFalse([s for s in sup(out, "other") if s["choice"].startswith("Tenant isolation")])


class Push(unittest.TestCase):
    def test_push_names_only_the_signals_and_platforms_present(self):
        cases = [("Customers book appointments.", "bookings", ["android"]), ("Users chat with each other.", "messages", ["ios"]),
                 ("Send reminders to patients.", "reminders", ["android", "ios"])]
        for desc, word, plat in cases:
            out = run(**{"project.type": "web_app", "project.platforms": plat, "project.description": desc})
            p = next(s for s in sup(out, "other") if s["choice"].startswith("Firebase Cloud Messaging"))["justification"]
            self.assertIn(word, p)
            self.assertNotIn("immediately", p)
            self.assertEqual("APNs" in p, "ios" in plat)
        self.assertNotIn("messages", next(s for s in sup(run(**{"project.type": "web_app", "project.platforms": ["android"],
                                                                "project.description": "Customers book appointments."}), "other")
                                          if s["choice"].startswith("Firebase Cloud Messaging"))["justification"])


class Queue(unittest.TestCase):
    def test_webhooks_and_ledger_only_where_present(self):
        for typ in ("saas_b2b", "ecommerce", "marketplace"):
            out = run(**dict(BIG, **{"project.type": typ, "requirements.payments": True, "project.description": "Customers pay online."}))
            q = texts(out, "queue")[0]
            self.assertIn("ayment-gateway webhooks", q, typ)
            self.assertNotIn("ledger", q, typ)
        led = run(**dict(BIG, **{"project.type": "fintech", "requirements.payments": True, "project.description": "A double-entry ledger of wallet balances."}))
        self.assertIn("ledger postings", texts(led, "queue")[0])
        store = run(**dict(BIG, **{"project.type": "gaming", "project.platforms": ["android"], "requirements.payments": True,
                                   "project.description": "Players buy in-game coins."}))
        q = texts(store, "queue")
        if q:
            self.assertNotIn("webhooks", q[0])


class Database(unittest.TestCase):
    def test_acid_reason_names_only_what_the_input_has(self):
        for typ in ("marketplace", "ecommerce"):
            out = run(**{"project.type": typ, "requirements.payments": False, "project.description": "Browse listings."})
            j = out["stack"]["database"]["justification"]
            self.assertNotRegex(j, r"(?i)bookings|and payments", typ)
        pay = run(**{"project.type": "marketplace", "requirements.payments": True})["stack"]["database"]["justification"]
        self.assertIn("and payments", pay)
        self.assertNotIn("bookings", pay)


class Hosting(unittest.TestCase):
    def test_constraints_trail_instead_of_opening(self):
        for typ in ("web_app", "marketplace", "saas_b2b"):
            j = run(**{"project.type": typ, "infrastructure.cloud_preference": "aws"})["stack"]["hosting"]["justification"]
            self.assertFalse(j.startswith("Satisfies"), typ)
            self.assertTrue(j.rstrip().endswith(")."), typ)
            self.assertIn("Satisfies the hard constraints (", j)


class TimeSeries(unittest.TestCase):
    def test_readings_only_for_iot(self):
        wide = {"scale.workload": "write_heavy", "scale.data_volume_gb_12_months": 2000}
        iot = run(**dict(wide, **{"project.type": "iot", "project.description": "40,000 sensors send readings every 60 seconds."}))
        ts = next(s for s in sup(iot, "other") if s["choice"].startswith("Time-series"))["justification"]
        self.assertIn("append-only readings", ts)
        for typ in ("web_app", "social", "marketplace"):
            out = run(**dict(wide, **{"project.type": typ}))
            ts = [s for s in sup(out, "other") if s["choice"].startswith("Time-series")]
            for s in ts:
                self.assertNotIn("readings", s["justification"], typ)
                self.assertIn("write-heavy", s["justification"], typ)


class Observability(unittest.TestCase):
    def test_targets_are_the_inputs(self):
        out = run(**{"project.type": "web_app", "requirements.p95_latency_ms": 320, "requirements.availability": "99.95"})
        o = texts(out, "observability")[0]
        self.assertIn("320 ms p95", o)
        self.assertIn("99.95%", o)
        o2 = texts(run(**{"project.type": "web_app", "requirements.p95_latency_ms": None}), "observability")[0]
        self.assertNotIn("p95", o2)


class Storage(unittest.TestCase):
    def test_volume_only_when_given(self):
        given = run(**{"project.type": "social", "requirements.file_media_storage": True, "scale.data_volume_gb_12_months": 750})
        self.assertIn("~750 GB of files", texts(given, "storage")[0])
        none = run(**{"project.type": "social", "requirements.file_media_storage": True, "scale.data_volume_gb_12_months": None})
        j = texts(none, "storage")[0]
        self.assertTrue(j.startswith("Uploads"))
        alt = sup(none, "storage")[0]["alternatives"][0]["why_not"]
        self.assertIn("is not given", alt)


if __name__ == "__main__":
    unittest.main()
