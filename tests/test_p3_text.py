"""Track p3 (15 Nov 2026): false or template sentences removed. Each test written before the change."""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_round9 import codes, run, sup  # noqa: E402


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


class NumbersAndGrammar(unittest.TestCase):
    """A-D12/A-D20: separators on large dollar amounts, impossible user counts flagged, '1 week', no '..'."""

    def test_impossible_user_count_warned(self):
        for typ in ("web_app", "ecommerce", "iot"):
            out = run(**{"project.type": typ, "scale.users_at_launch": 10 ** 12, "scale.users_12_months": 10 ** 18,
                         "scale.peak_concurrent_users": 1000})
            self.assertIn("USERS_IMPLAUSIBLE", codes(out), typ)
        for n in (3000, 2_000_000_000):
            out = run(**{"scale.users_12_months": n})
            self.assertNotIn("USERS_IMPLAUSIBLE", codes(out), n)

    def test_large_dollar_amounts_have_separators(self):
        out = run(**{"scale.users_at_launch": 10 ** 12, "scale.users_12_months": 10 ** 18, "budget.monthly_infra_usd": 10 ** 12})
        t = dump_text(out)
        self.assertIsNone(re.search(r"\$\d{7,}", t), re.findall(r".{30}\$\d{7,}", t)[:2])
        from engine.recommend import _usd_range
        self.assertEqual(_usd_range(1200, 4500, commas=False), "$1200-4500")
        self.assertEqual(_usd_range(1200, 2_500_000, commas=False), "$1,200-2,500,000")

    def test_one_week_singular(self):
        t = dump_text(run(**{"timeline.mvp_weeks": 1, "team.size": 1, "project.platforms": ["web", "android", "ios", "desktop"]}))
        self.assertIn("platforms in 1 week with", t)
        self.assertNotIn("1 weeks", t)
        t = dump_text(run(**{"timeline.mvp_weeks": 4, "team.size": 1, "project.platforms": ["web", "android", "ios", "desktop"]}))
        self.assertIn("platforms in 4 weeks with", t)

    def test_infeasible_summary_single_period(self):
        out = run(**{"project.type": "fintech", "compliance": ["rbi_localisation"], "infrastructure.data_residency": "eu",
                     "requirements.payments": True})
        self.assertNotIn("..", out.get("summary", "") + dump_text(out).replace("...", ""))


class SingleSiteWording(unittest.TestCase):
    """The 99.99% warning on a single-datacenter host says one datacenter, not one region of managed services."""

    def avail_msg(self, out):
        return " ".join(w["message"] for w in out["warnings"] if w["code"] == "AVAILABILITY_SINGLE_REGION")

    def test_single_site_says_one_datacenter(self):
        from test_p2 import vm_run
        seen = 0
        for ptype, res, desc in (("fintech", "india", "Loan servicing portal for an Indian lender."),
                                 ("saas_b2b", "eu", "Scheduling tool for European clinics."),
                                 ("web_app", "other", "Booking app for Singapore gyms; data must stay in Singapore.")):
            out = vm_run(ptype, res, "99.99", desc)
            if not out["stack"]["hosting"]["choice"].startswith("DigitalOcean"):
                continue
            seen += 1
            m = self.avail_msg(out)
            self.assertIn("beyond what one datacenter is designed", m, ptype)
            self.assertNotIn("one region of managed services", m, ptype)
        self.assertGreaterEqual(seen, 1)

    def test_multi_zone_host_keeps_region_wording(self):
        m = self.avail_msg(run(**{"infrastructure.cloud_preference": "aws", "infrastructure.data_residency": "eu",
                                  "requirements.availability": "99.99", "project.description": "Customers sign in and manage their records."}))
        self.assertIn("one region of managed services", m)


class JudgeBText(unittest.TestCase):
    """B-15: professionals are not told to see a professional; B-14: on-premises hosts have no region."""

    def test_professional_users_detected(self):
        from engine.services import professional_users
        self.assertEqual(professional_users("Lawyers upload contracts and ask questions.", "legal"), "lawyers")
        self.assertEqual(professional_users("A search tool for in-house legal teams.", "legal"), "legal teams")
        self.assertEqual(professional_users("Assistant for hospital doctors on drug interactions.", "medical"), "doctors")
        self.assertEqual(professional_users("Video visits between patients and doctors.", "medical"), "")
        self.assertEqual(professional_users("Citizens ask about tenancy law.", "legal"), "")

    def test_lay_users_keep_the_lay_notice(self):
        """MUST 1 (review p3): lay users named in the description (patients, tenants, ...) keep the 'not advice' notice."""
        from engine.services import professional_users
        for desc, kind in (("Symptom chatbot for patients and doctors: patients ask health questions.", "medical"),
                           ("Nurses log visits for patients who ask the chatbot.", "medical"),
                           ("Advocates of tenant rights built a helpline bot.", "legal"),
                           ("Lawyers publish answers that the public reads.", "legal"),
                           ("Doctors and parents use the app to track child vaccinations.", "medical"),
                           ("A bot for law firms and their customers.", "legal")):
            self.assertEqual(professional_users(desc, kind), "", desc)
        self.assertEqual(professional_users("Paralegals search case files for precedent.", "legal"), "paralegals")
        self.assertEqual(professional_users("Clinicians ask about drug doses.", "medical"), "clinicians")

    def test_patient_chatbot_keeps_not_medical_advice(self):
        out = run(**{"project.description": "Symptom chatbot for patients and doctors: patients ask health questions and get medical guidance "
                     "from an LLM before a visit.", "requirements.ml_features": "llm_rag"})
        m = " ".join(w["message"] for w in out["warnings"] if w["code"] == "LLM_ADVICE_DISCLAIMER")
        self.assertIn("'not medical advice'", m)
        self.assertNotIn("the users are", m)

    def test_disclaimer_for_lawyers_is_not_see_a_lawyer(self):
        def msg(desc):
            out = run(**{"project.description": desc, "requirements.ml_features": "llm_rag"})
            return " ".join(w["message"] for w in out["warnings"] if w["code"] == "LLM_ADVICE_DISCLAIMER")
        m = msg("Lawyers upload contracts and ask questions in natural language; answers must cite the source paragraphs.")
        self.assertIn("the users are lawyers", m)
        self.assertNotIn("qualified lawyer", m)
        m = msg("Citizens ask questions about tenancy law in natural language; answers cite the statute.")
        self.assertIn("route to a qualified lawyer", m)

    def test_on_prem_latency_has_no_region(self):
        def msg(**kw):
            out = run(**{"requirements.p95_latency_ms": 80, **kw})
            return " ".join(w["message"] for w in out["warnings"] if w["code"] == "LATENCY_TARGET_UNMEASURED")
        m = msg(**{"infrastructure.deployment_model": "on_premise"})
        self.assertIn("users near your own servers", m)
        self.assertNotIn("region and", m)
        self.assertIn(" region and no cross-region", msg(**{"infrastructure.cloud_preference": "aws"}))


if __name__ == "__main__":
    unittest.main()
