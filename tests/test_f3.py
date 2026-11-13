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


if __name__ == "__main__":
    unittest.main()
