"""Track p3 (15 Nov 2026): false or template sentences removed. Each test written before the change."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_round9 import run, sup  # noqa: E402


def bi(out):
    return next(s for s in sup(out, "other") if s["choice"].startswith("BI dashboards"))["justification"]


class MetabaseSignIn(unittest.TestCase):
    """Metabase open source signs in with its own accounts, Google Sign-in or LDAP; SAML/OIDC/JWT SSO is a paid plan."""

    def test_sso_needs_paid_plan(self):
        for kw in ({"requirements.auth": "enterprise_sso"},
                   {"requirements.auth": "enterprise_sso", "infrastructure.cloud_preference": "gcp"},
                   {"infrastructure.existing_systems": ["Okta"]}):
            j = bi(run(**{"project.type": "data_analytics", **kw}))
            self.assertIn("Pro or Enterprise plan", j, kw)
            self.assertNotIn("signed in through the same identity provider", j)

    def test_no_sso_input_names_oss_options_only(self):
        for auth in ("email_password", "social"):
            j = bi(run(**{"project.type": "data_analytics", "requirements.auth": auth}))
            self.assertIn("own accounts, Google Sign-in or LDAP", j)
            self.assertNotIn("identity provider", j)
            self.assertNotIn("Pro or Enterprise", j)


def dump_text(out):
    return json.dumps(out, ensure_ascii=False)


class TemplateLeaks(unittest.TestCase):
    """A-D5: each templated sentence names only what the input says."""

    def test_push_names_the_events_described(self):
        from engine.services import job_events
        self.assertEqual(job_events("Video visits and appointment booking for clinics"), "new bookings")
        self.assertEqual(job_events("Drivers accept jobs near them"), "new jobs")
        self.assertEqual(job_events("Managers assign tasks to field staff"), "new assignments")
        self.assertEqual(job_events("Customers book slots; dispatch sends a technician"), "new bookings or jobs")

    def test_push_on_booking_app_never_says_jobs(self):
        t = dump_text(run(**{"project.type": "healthtech", "project.platforms": ["web", "android", "ios"],
                             "project.description": "Patients book appointments with doctors."}))
        self.assertIn("hear about new bookings", t)
        self.assertNotIn("new jobs", t)

    def test_scheduler_names_the_timed_work(self):
        for typ, desc, want, never in (("saas_b2b", "Dashboards for agencies; nightly imports from ad platforms.", "Nightly and other scheduled jobs", "Reminders"),
                                       ("web_app", "Clinic app that sends appointment reminders.", "Reminders and other timed work", "Nightly"),
                                       ("internal_tool", "Sends a daily digest email to managers.", "Scheduled jobs run", "Reminders")):
            t = dump_text(run(**{"project.type": typ, "project.description": desc}))
            self.assertIn(want, t, typ)
            self.assertNotIn(never + " and other", t, typ)

    def test_waf_reason_matches_money_input(self):
        paid = dump_text(run(**{"project.type": "ecommerce", "requirements.payments": True, "priorities.security": 5,
                                "infrastructure.cloud_preference": "aws"}))
        fin = dump_text(run(**{"project.type": "fintech", "priorities.security": 5, "infrastructure.cloud_preference": "aws"}))
        self.assertIn("Taking payments with priorities.security=5", paid)
        self.assertIn("Financial data (project.type=fintech) with priorities.security=5", fin)
        for t in (paid, fin):
            self.assertNotIn("Money handling", t)

    def test_india_region_strength_only_for_india_residency(self):
        from engine.recommend import kb_fact
        item = {"strengths": ["Cheapest predictable VM pricing with an India region"]}
        self.assertIsNone(kb_fact(item, {"req": {"infrastructure.data_residency": "other"}}))
        self.assertIsNone(kb_fact(item, {"req": {"infrastructure.data_residency": "eu"}}))
        self.assertEqual(kb_fact(item, {"req": {"infrastructure.data_residency": "india"}}), item["strengths"][0])
        two = {"strengths": ["Regional location asia-south1 (Mumbai) available", "Offline sync in mobile SDKs"]}
        self.assertEqual(kb_fact(two, {"req": {"infrastructure.data_residency": "us"}}), "Offline sync in mobile SDKs")

    def test_static_site_never_claims_a_single_author(self):
        t = dump_text(run(**{"project.type": "content_site", "requirements.auth": "none",
                             "project.description": "Exam results published as a static list once a year."}))
        self.assertNotIn("single author", t)


class LanguageAndRegionHonesty(unittest.TestCase):
    """Holdout review: library names in the backend's language; Central India rates labelled outside India; no Agones without Kubernetes."""

    def test_job_queue_names_backend_language_only(self):
        from engine.domains import db_queue_name
        self.assertEqual(db_queue_name({"langs": ["python"]}), "Database-backed job queue in the app (e.g. Celery)")
        self.assertEqual(db_queue_name({"langs": ["csharp"]}), "Database-backed job queue in the app (e.g. Hangfire)")
        self.assertEqual(db_queue_name({"langs": ["javascript", "typescript"]}), "Database-backed job queue in the app (e.g. Graphile Worker)")
        for langs in (["go"], ["java", "kotlin"], ["elixir"]):
            n = db_queue_name({"langs": langs})
            for lib in ("Celery", "Hangfire", "Graphile"):
                self.assertNotIn(lib, n, langs)
            self.assertIn("jobs table", n)

    def test_central_india_rate_labelled_outside_india(self):
        for res in ("eu", "us"):
            t = dump_text(run(**{"infrastructure.cloud_preference": "azure", "infrastructure.data_residency": res,
                                 "team.languages": ["csharp"], "requirements.availability": "99.95"}))
            self.assertIn("Central India reference rate", t, res)
        t = dump_text(run(**{"infrastructure.cloud_preference": "azure", "infrastructure.data_residency": "india",
                             "team.languages": ["csharp"], "requirements.availability": "99.95"}))
        self.assertNotIn("reference rate; other regions", t)

    def test_no_agones_without_kubernetes(self):
        from engine.domains import game_server_product
        self.assertNotIn("Agones (", game_server_product("digitalocean", False, "", False)[0])
        self.assertNotIn("Agones (", game_server_product("on_premise", False, "", False)[0])
        self.assertTrue(game_server_product("on_premise", False, "", True)[0].startswith("Agones"))
        self.assertTrue(game_server_product("aws", True, "", False)[0].startswith("Amazon GameLift"))

    def test_app_like_reason_names_the_signal(self):
        from engine.select import heavy_client_why
        def ctx(desc, offline=False, collab=False):
            return {"req": {"project.description": desc, "requirements.offline_support": offline}, "desc": {"collab": collab}}
        self.assertIn("offline use", heavy_client_why(ctx("Replace our spreadsheets", offline=True)))
        self.assertIn("'kanban'", heavy_client_why(ctx("A kanban board for teams")))
        self.assertIn("collaboration", heavy_client_why(ctx("Teams collaborate on docs", collab=True)))
        w = heavy_client_why(ctx("Replace our spreadsheets", offline=True))
        for never in ("drag-and-drop", "canvas", "trading", "collaboration"):
            self.assertNotIn(never, w)


if __name__ == "__main__":
    unittest.main()
