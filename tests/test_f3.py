"""Track f3: local-first desktop archetype (A2), offline uniqueness/payments (A12), periodically refreshed static data (A18).
Synthetic inputs only (no scenario ids or product names). Each rule: >=3 project types where it fires and >=1 where it must not."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402

DESKTOP = {"project.platforms": ["desktop"], "requirements.auth": "none", "team.size": 1, "team.experience": "senior",
           "team.languages": ["rust"], "budget.monthly_infra_usd": 5, "scale.users_12_months": 2000, "scale.users_at_launch": 0,
           "scale.peak_concurrent_users": 20, "requirements.offline_support": True}


class LocalFirstDesktop(unittest.TestCase):
    def test_fires_for_different_project_types(self):
        cases = [
            ("other", "Contest logging tool that runs on a laptop with no internet. Optional upload of the finished log to a club server afterwards."),
            ("internal_tool", "Desktop workbench for renaming and tagging photo archives on one computer. Works offline."),
            ("web_app", "Personal budgeting program that keeps its data on the user's computer and exports CSV."),
            ("content_site", "Offline reader for a large reference library, installed on the user's computer."),
        ]
        for typ, desc in cases:
            out = run(**{**DESKTOP, "project.type": typ, "project.description": desc})
            st = out["stack"]
            self.assertEqual(st["backend"]["choice"], "None", typ)
            self.assertEqual(st["database"]["choice"], "SQLite (embedded, on the device)", typ)
            self.assertEqual(st["hosting"]["choice"], "None (distributed binary)", typ)
            self.assertNotEqual(out["architecture_style"], "static", typ)
            self.assertNotIn("Static site", out["summary"], typ)
            other = " ".join(s["choice"] for s in sup(out, "other"))
            self.assertIn("Embedded database", other, typ)
            self.assertNotIn("Service worker", other, typ)
            self.assertNotIn("Workbox", other, typ)
            self.assertNotIn("CDN", " ".join(s["layer"] for s in st["supporting"]).upper(), typ)
            self.assertEqual(out["estimated_monthly_cost_usd"]["min"], 0, typ)

    def test_optional_endpoint_only_when_the_text_names_it(self):
        with_up = run(**{**DESKTOP, "project.type": "other", "project.description": "Offline tool. Optional upload of results to a club server later."})
        without = run(**{**DESKTOP, "project.type": "other", "project.description": "Offline tool for one operator on one laptop."})
        self.assertIn("optional", with_up["stack"]["backend"]["justification"])
        self.assertIn("append-only", with_up["stack"]["backend"]["justification"])
        self.assertNotIn("optional", without["stack"]["backend"]["justification"])
        self.assertNotIn("endpoint", without["stack"]["backend"]["justification"])
        self.assertIn("optional upload endpoint", with_up["stack"]["hosting"]["justification"])
        self.assertNotIn("optional upload endpoint", without["stack"]["hosting"]["justification"])

    def test_must_not_fire_when_a_server_is_needed(self):
        base = {**DESKTOP, "project.type": "other", "project.description": "Offline-capable desktop tool."}
        for label, change in (("web client too (PWA-desktop path)", {"project.platforms": ["web", "desktop"]}),
                              ("accounts", {"requirements.auth": "email_password"}),
                              ("payments", {"requirements.payments": True}),
                              ("realtime", {"requirements.realtime": True}),
                              ("mobile client", {"project.platforms": ["desktop", "android"]}),
                              ("server-product type", {"project.type": "saas_b2b"}),
                              ("HIPAA data", {"compliance": ["hipaa"]})):
            out = run(**{**base, **change})
            self.assertNotEqual(out["stack"]["hosting"]["choice"], "None (distributed binary)", label)
            self.assertNotEqual(out["stack"]["database"]["choice"], "SQLite (embedded, on the device)", label)

    def test_web_plus_desktop_keeps_pwa_path(self):
        out = run(**{**DESKTOP, "project.platforms": ["web", "desktop"], "project.type": "content_site",
                     "project.description": "Reference library with articles."})
        self.assertIn("installable PWA (desktop)", out["stack"]["frontend"]["choice"])
        self.assertNotEqual(out["stack"]["hosting"]["choice"], "None (distributed binary)")


OFFLINE = {"requirements.offline_support": True, "requirements.auth": "email_password", "project.platforms": ["android", "web"],
           "team.size": 5, "team.languages": ["kotlin"], "budget.monthly_infra_usd": 2000}


class OfflineConflicts(unittest.TestCase):
    """A12: OFFLINE_UNIQUENESS, OFFLINE_PAYMENTS and the append-only policy for ledger/booking/ticket-like data."""

    def test_uniqueness_warning_for_different_project_types(self):
        cases = [
            ("other", "Gate staff scan tickets on handhelds and block duplicate entries across all gates; the link drops often."),
            ("marketplace", "Field agents book appointments for farm visits; no two agents may book the same slot."),
            ("healthtech", "Clinic check-in tablets in rural camps record each patient once; duplicate records must be avoided."),
            ("internal_tool", "Warehouse staff redeem one-time vouchers at the exit using handhelds."),
        ]
        for typ, desc in cases:
            out = run(**{**OFFLINE, "project.type": typ, "project.description": desc})
            w = [x for x in out["warnings"] if x["code"] == "OFFLINE_UNIQUENESS"]
            self.assertEqual(len(w), 1, typ)
            self.assertEqual(w[0]["severity"], "warning", typ)
            self.assertIn("requirements.offline_support", w[0]["fields"], typ)
            self.assertIn("cannot be guaranteed offline", w[0]["message"], typ)
            off = next(s for s in sup(out, "other") if s["choice"].startswith("Offline-first sync"))
            self.assertIn("append-only command log", off["justification"], typ)
            self.assertNotIn("last-writer-wins", off["justification"], typ)

    def test_uniqueness_must_not_fire(self):
        base = {**OFFLINE, "project.type": "other", "project.description": "Field survey app: agents record household answers on phones with patchy coverage."}
        out = run(**base)
        self.assertNotIn("OFFLINE_UNIQUENESS", codes(out))
        off = next(s for s in sup(out, "other") if s["choice"].startswith("Offline-first sync"))
        self.assertIn("last-writer-wins", off["justification"])  # the policy follows the data
        self.assertNotIn("append-only command log", off["justification"])
        # same wording without offline_support: no warning
        out = run(**{**base, "requirements.offline_support": False, "project.description": "Gate staff scan tickets and block duplicate entries."})
        self.assertNotIn("OFFLINE_UNIQUENESS", codes(out))
        # double-entry bookkeeping is not a cross-device uniqueness rule (the ledger policy still applies)
        out = run(**{**base, "project.description": "Co-op staff record deliveries in a double-entry ledger on phones with patchy coverage."})
        self.assertNotIn("OFFLINE_UNIQUENESS", codes(out))
        # a single-device local-first app has no other device to disagree with
        out = run(**{**DESKTOP, "project.type": "other", "project.description": "Logger that rejects a duplicate entry on the same laptop."})
        self.assertNotIn("OFFLINE_UNIQUENESS", codes(out))

    def test_offline_payments_for_different_project_types(self):
        for typ, desc in (("other", "Kiosks renew bus passes; depots lose internet for hours."),
                          ("ecommerce", "Market stall app takes orders on tablets with poor coverage."),
                          ("marketplace", "Delivery riders collect fees by card on phones in basements.")):
            out = run(**{**OFFLINE, "project.type": typ, "project.description": desc, "requirements.payments": True})
            w = [x for x in out["warnings"] if x["code"] == "OFFLINE_PAYMENTS"]
            self.assertEqual(len(w), 1, typ)
            self.assertIn("payment pending", w[0]["message"], typ)
            self.assertIn("requirements.payments", w[0]["fields"], typ)

    def test_offline_payments_must_not_fire(self):
        out = run(**{**OFFLINE, "project.type": "ecommerce", "project.description": "Online shop.", "requirements.payments": True,
                     "requirements.offline_support": False})
        self.assertNotIn("OFFLINE_PAYMENTS", codes(out))
        out = run(**{**OFFLINE, "project.type": "other", "project.description": "Offline notes."})
        self.assertNotIn("OFFLINE_PAYMENTS", codes(out))

    def test_ledger_data_gets_append_only_policy(self):
        out = run(**{**OFFLINE, "project.type": "fintech", "project.description": "Co-op staff record deliveries and settlements in a double-entry ledger at centres with patchy coverage."})
        off = next(s for s in sup(out, "other") if s["choice"].startswith("Offline-first sync"))
        self.assertIn("append-only command log", off["justification"])


if __name__ == "__main__":
    unittest.main()
