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


STATIC = {"requirements.auth": "none", "project.platforms": ["web"], "team.size": 3, "team.languages": ["javascript"], "budget.monthly_infra_usd": 300,
          "scale.users_at_launch": 20000, "scale.users_12_months": 3000000, "scale.peak_concurrent_users": 100000, "requirements.seo_critical": True}


def publisher(out):
    return [s for s in sup(out, "other") if "scheduled publisher" in s["choice"]]


class RefreshedStatic(unittest.TestCase):
    """A18: a static site whose data is republished on a schedule gets a scheduled publisher, atomic publish and a short cache lifetime."""

    CASES = [
        ("content_site", "Public results site: the commission publishes tallies in batches roughly every 5 min; the page shows the latest numbers."),
        ("other", "Public scoreboard for a city marathon. Timing mats upload splits and the page shows the latest standings, refreshed every 2 minutes."),
        ("web_app", "Public air-quality bulletin for a city. Readings arrive every 15 minutes from the monitoring network; the page shows the current readings. Read-only."),
        ("content_site", "Transit information site: departure boards are republished every 30 seconds from the operator's feed."),
    ]

    def test_scheduled_publisher_for_different_project_types(self):
        for typ, desc in self.CASES:
            out = run(**{**STATIC, "project.type": typ, "project.description": desc})
            self.assertEqual(out["architecture_style"], "static", typ)
            self.assertEqual(out["stack"]["backend"]["choice"], "None", typ)
            self.assertEqual(out["stack"]["database"]["choice"], "None", typ)
            self.assertNotIn("Markdown", out["stack"]["database"]["justification"].replace("not as Markdown", ""), typ)
            self.assertIn("scheduled publisher", out["stack"]["backend"]["justification"], typ)
            pub = publisher(out)
            self.assertEqual(len(pub), 1, typ)
            for word in ("atomic publish", "short time", "latest"):
                self.assertIn(word, pub[0]["justification"], typ)
            self.assertTrue(any("Static site with data refreshed" in a for a in out["assumptions"]), typ)

    def test_interval_is_read_from_the_text(self):
        out = run(**{**STATIC, "project.type": "other", "project.description": "Scoreboard refreshed every 2 minutes with the latest standings."})
        self.assertIn("about every 2 minutes", publisher(out)[0]["justification"])
        self.assertIn("24 seconds", publisher(out)[0]["justification"])  # a fifth of the interval (planning heuristic)

    def test_egress_estimate_and_budget_warning(self):
        args = {**STATIC, "project.type": "content_site", "scale.users_12_months": 40000000, "scale.users_at_launch": 5000000,
                "scale.peak_concurrent_users": 2500000, "budget.monthly_infra_usd": 900,
                "project.description": "Election results; tallies come in batches every 5 min and the page shows the latest numbers."}
        big = run(**{**args, "infrastructure.cloud_preference": "aws"})  # a host that bills transfer
        self.assertIn("CloudFront", big["stack"]["hosting"]["choice"])
        w = [x for x in big["warnings"] if x["code"] == "CDN_EGRESS_AT_RISK"]
        self.assertEqual(len(w), 1)
        self.assertIn("users x", w[0]["message"])
        self.assertIn("scale.users_12_months", w[0]["fields"])
        self.assertIn("BUDGET_AT_RISK", codes(big))
        self.assertGreater(big["estimated_monthly_cost_usd"]["max"], 900)
        free = run(**args)  # the default host does not bill static requests: an assumption line, no warning
        self.assertIn("Cloudflare", free["stack"]["hosting"]["choice"])
        self.assertNotIn("CDN_EGRESS_AT_RISK", codes(free))
        self.assertTrue(any(l.startswith("CDN egress:") and "does not bill" in l for l in free["estimated_monthly_cost_usd"]["assumptions"]))
        small = run(**{**STATIC, "project.type": "content_site", "scale.users_12_months": 3000, "scale.users_at_launch": 100,
                       "scale.peak_concurrent_users": 50, "budget.monthly_infra_usd": 300,
                       "project.description": "Club fixtures page; scores are republished every 10 minutes."})
        self.assertNotIn("CDN_EGRESS_AT_RISK", codes(small))
        self.assertEqual(len(publisher(small)), 1)

    def test_must_not_fire(self):
        # editorial static site: nothing is refreshed on a schedule
        out = run(**{**STATIC, "project.type": "content_site", "project.description": "Parish website with news and service times. Volunteers edit the pages."})
        self.assertEqual(publisher(out), [])
        self.assertNotIn("scheduled publisher", out["stack"]["backend"]["justification"])
        self.assertIn("Markdown", out["stack"]["database"]["justification"])
        # a dynamic product keeps its backend even when its text says every 5 minutes
        out = run(**{**STATIC, "project.type": "saas_b2b", "requirements.auth": "email_password", "project.description": "Dashboard that refreshes every 5 minutes."})
        self.assertEqual(publisher(out), [])
        self.assertNotEqual(out["stack"]["backend"]["choice"], "None")
        # realtime asked for in the fields: not a static site
        out = run(**{**STATIC, "project.type": "other", "requirements.realtime": True, "project.description": "Live scores updated every 10 seconds."})
        self.assertEqual(publisher(out), [])


def server_stack(out):
    st = out["stack"]
    return st["backend"]["choice"] != "None" and st["hosting"]["choice"] != "None (distributed binary)" and st["database"]["choice"] != "SQLite (embedded, on the device)"


class LocalFirstNeedsNoSharedData(unittest.TestCase):
    """Review fix B1/N3: shared data, sync with others, a LAN, or an existing server named only in the description keep the server stack."""

    SHARED = [
        ("other", "Desktop app for a field survey team of 12; each laptop collects records and syncs records with the team so everyone sees the others' entries."),
        ("internal_tool", "Till software where three cashiers share one inventory database on the LAN."),
        ("other", "A program for a family to share a household budget across their three laptops."),
        ("web_app", "Back-office tool used by several users at the same time on different computers."),
        ("other", "Volunteers on separate machines work from a central database of members."),
    ]
    EXISTING = [
        ("other", "Desktop tool that pulls our existing PostgreSQL reports and shows them offline."),
        ("internal_tool", "Viewer for orders held in the company's MySQL database."),
        ("other", "Reads prices from the REST API of the supplier and shows them in a desktop window."),
    ]

    def test_shared_data_and_existing_servers_keep_the_server_stack(self):
        for typ, desc in self.SHARED + self.EXISTING:
            out = run(**{**DESKTOP, "project.type": typ, "project.description": desc})
            self.assertTrue(server_stack(out), desc)
            self.assertNotIn("Static site", out["summary"], desc)

    def test_single_machine_text_stays_local_first(self):
        for typ, desc in (("other", "Personal journal for one person on one laptop; entries never leave the computer."),
                          ("other", "Lab logger on one laptop plots the measurements in real time. Optional later upload of the finished log to a club server."),
                          ("internal_tool", "Desktop program that needs no server and no network; results can be exported to CSV and shared by e-mail afterwards."),
                          ("other", "Photo organiser; back up the library to an external disk."),
                          ("other", "Notes app with multiple colours and multiple fonts, used by one person.")):
            out = run(**{**DESKTOP, "project.type": typ, "project.description": desc})
            self.assertEqual(out["stack"]["hosting"]["choice"], "None (distributed binary)", desc)
            self.assertEqual(out["stack"]["backend"]["choice"], "None", desc)


class RefreshWording(unittest.TestCase):
    """Review fix N1/N2: an explicit cadence or feed is needed; the cache-lifetime text and the scheduler minimum are stated honestly."""

    def test_cadence_words_fire(self):
        for typ, desc in (("content_site", "Public dashboard of city statistics, refreshed daily from the statistics office."),
                          ("other", "Price comparison pages rebuilt every night from a supplier feed."),
                          ("web_app", "Read-only page of river levels; the readings are pulled from an API hourly."),
                          ("content_site", "League tables scraped from the federation site and shown on a public page.")):
            out = run(**{**STATIC, "project.type": typ, "project.description": desc, "scale.users_12_months": 500000})
            self.assertEqual(len(publisher(out)), 1, desc)

    def test_bare_current_or_latest_and_human_edits_do_not_fire(self):
        for typ, desc in (("content_site", "Docs site listing current prices of our products, rebuilt on each release."),
                          ("content_site", "Parish website updated weekly by volunteers with the latest news and the current service times."),
                          ("other", "Shows the latest results of the school quiz once the teacher publishes them."),
                          ("content_site", "Portfolio with the newest data-visualisation projects.")):
            out = run(**{**STATIC, "project.type": typ, "project.description": desc})
            self.assertEqual(publisher(out), [], desc)

    def test_cache_lifetime_text_is_honest(self):
        short = publisher(run(**{**STATIC, "project.type": "other", "project.description": "Departure boards republished every 30 seconds from the operator's feed."}))[0]["justification"]
        self.assertIn("10 seconds", short)
        self.assertIn("would be 6 seconds", short)
        self.assertNotIn("a fifth of the refresh interval", short)
        day = publisher(run(**{**STATIC, "project.type": "content_site", "project.description": "Public dashboard of statistics, refreshed daily."}))[0]["justification"]
        self.assertIn("900 seconds: the planning-heuristic cap applies", day)
        nominal = publisher(run(**{**STATIC, "project.type": "other", "project.description": "Scoreboard refreshed every 10 minutes."}))[0]["justification"]
        self.assertIn("120 seconds: a fifth of the refresh interval", nominal)

    def test_interval_below_the_scheduler_minimum_is_a_tradeoff(self):
        for cloud, interval, expect in ((None, "30 seconds", True), (None, "2 minutes", True), (None, "10 minutes", False),
                                        ("aws", "30 seconds", True), ("aws", "5 minutes", False)):
            kw = {**STATIC, "project.type": "other", "project.description": f"Scoreboard refreshed every {interval}."}
            if cloud:
                kw["infrastructure.cloud_preference"] = cloud
            tr = " ".join(publisher(run(**kw))[0]["tradeoffs"])
            self.assertEqual("shorter than the shortest interval" in tr, expect, (cloud, interval))


if __name__ == "__main__":
    unittest.main()
