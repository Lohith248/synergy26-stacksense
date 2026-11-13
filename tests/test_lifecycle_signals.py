"""E11: lifecycle of existing systems, accurate existing-system text, skill mismatch and description-fact signals.
Every rule is stated without a scenario, tested on several project types plus inputs where it must not fire.
Inputs are inline (nothing outside the worktree is read)."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "LS", "project": {"type": "web_app", "platforms": ["web"], "description": "A small web application."},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "intermediate", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 2000}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none",
                           "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def build(base=BASE, desc=None, **kw):
    s = copy.deepcopy(base)
    if desc is not None:
        s["project"]["description"] = desc
    for path, v in kw.items():
        node, parts = s, path.replace("__", ".").split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return s


def run(base=BASE, desc=None, **kw):
    return evaluate(build(base, desc, **kw), counterfactuals=False)


def warns(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


def sup(out, needle):
    return [s for s in out["stack"]["supporting"] if needle in s["choice"] or needle in s["layer"]]


def eol(out, raw):
    return [w for w in out["warnings"] if w["code"] in ("END_OF_LIFE_SYSTEM", "END_OF_LIFE_SOON") and raw in w["message"]]


class LegacyLifecycle(unittest.TestCase):
    """A legacy OS, runtime or database named in existing_systems gets an end-of-life warning from KB lifecycle data."""

    CASES = [  # (existing_systems entry, project type, expected date in the message)
        ("Windows Server 2008 R2", "internal_tool", "2020-01-15"),
        ("WinServer 2008", "saas_b2b", "2020-01-15"),
        ("Visual Basic 6 desktop client", "internal_tool", "2008-04-08"),
        ("VB6 order-entry app", "ecommerce", "2008-04-08"),
        ("PostgreSQL 11", "web_app", "2023-11-09"),
        ("postgres 12 on a VM", "saas_b2b", "2024-11-21"),
        ("MySQL 5.6", "web_app", "2021-02-01"),
        ("Windows Server 2003 R2 file server", "internal_tool", "2015-07-15"),
        ("Windows 7 kiosks", "internal_tool", "2020-01-15"),
        ("PHP 8.2 monolith", "web_app", None),
    ]

    def test_eol_warning_with_date(self):
        for raw, typ, date in self.CASES:
            with self.subTest(raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                hit = eol(out, raw)
                self.assertTrue(hit, raw)
                if date:
                    self.assertIn(date, hit[0]["message"])
                    self.assertEqual(hit[0]["code"], "END_OF_LIFE_SYSTEM")
                else:
                    self.assertEqual(hit[0]["code"], "END_OF_LIFE_SOON")  # security support ends 2026-12-31, inside 90 days
                self.assertFalse([w for w in out["warnings"] if w["code"] == "EXISTING_SYSTEM_UNRECOGNISED" and raw in w["message"]], raw)

    def test_vb6_runtime_caveat_is_in_the_text(self):
        out = run(infrastructure__existing_systems=["Visual Basic 6 desktop client"])
        self.assertIn("runtime is supported only for the support lifetime of the Windows version", eol(out, "Visual Basic")[0]["message"])

    def test_supported_versions_do_not_get_eol(self):
        for raw in ("PostgreSQL 17", "Windows Server 2022", "VB.NET 10 service", "Visual Basic for Applications macros", "MySQL 8.4"):
            with self.subTest(raw=raw):
                out = run(infrastructure__existing_systems=[raw])
                self.assertFalse(eol(out, raw), raw)

    def test_windows_server_2016_is_soon_and_2019_is_extended_support(self):
        out = run(infrastructure__existing_systems=["Windows Server 2016"])
        self.assertEqual(eol(out, "Windows Server 2016")[0]["code"], "END_OF_LIFE_SOON")
        out = run(infrastructure__existing_systems=["Windows Server 2019"])
        self.assertFalse(eol(out, "Windows Server 2019"))
        self.assertTrue([w for w in warns(out, "EXISTING_SYSTEM_EXTENDED_SUPPORT") if "2029-01-10" in w["message"]])

    def test_new_lifecycle_sources_are_verified(self):
        with open(os.path.join(ROOT, "kb", "sources.json"), encoding="utf-8") as f:
            src = json.load(f)
        for sid in ("winserver-2008", "winserver-2003r2", "winserver-2016", "winserver-2019", "windows-7", "vb6-support", "php-supported"):
            self.assertEqual(src[sid]["status"], "verified", sid)
            self.assertIn("13 Nov 2026", " ".join(src[sid]["claims"]), sid)


class ExistingSystemText(unittest.TestCase):
    def test_database_reason_does_not_claim_a_match_when_the_version_differs(self):
        for typ in ("web_app", "saas_b2b", "internal_tool"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, infrastructure__existing_systems=["PostgreSQL 11"])
                why = out["stack"]["database"]["justification"]
                if "PostgreSQL" not in out["stack"]["database"]["choice"]:
                    continue
                self.assertNotIn("atches the existing PostgreSQL 11", why)
                self.assertIn("not that version", why)

    def test_database_reason_still_matches_without_a_version(self):
        out = run(infrastructure__existing_systems=["PostgreSQL"])
        if "PostgreSQL" in out["stack"]["database"]["choice"]:
            self.assertIn("atches the existing PostgreSQL", out["stack"]["database"]["justification"])

    def test_integration_text_does_not_say_reuse_the_server_beside_a_new_database(self):
        for typ in ("web_app", "saas_b2b"):
            with self.subTest(typ=typ):
                out = run(project__type=typ, infrastructure__existing_systems=["PostgreSQL 11"])
                comp = sup(out, "Integration with existing PostgreSQL 11")
                if not comp:
                    continue
                self.assertNotIn("Reuse the PostgreSQL server", comp[0]["justification"])
                self.assertIn("move its data into the new database and retire it", comp[0]["justification"])

    def test_kept_database_still_reuses_the_server(self):
        out = run(infrastructure__existing_systems=["PostgreSQL 14 (must stay, system of record)"])
        self.assertIn("must stay", out["stack"]["database"]["justification"])

    def test_existing_ci_system_is_named_in_the_ci_component(self):
        for raw, typ in (("Jenkins", "saas_b2b"), ("TeamCity server", "web_app"), ("CircleCI", "internal_tool")):
            with self.subTest(raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                ci = sup(out, "ci_cd")[0]
                self.assertIn("The existing " + raw, ci["justification"])
                self.assertIn("infrastructure.existing_systems", ci["driven_by"])
                self.assertTrue([a for a in ci["alternatives"] if a["choice"].startswith("Keep " + raw)])
                self.assertFalse([w for w in out["warnings"] if w["code"] == "EXISTING_SYSTEM_UNRECOGNISED" and raw in w["message"]])

    def test_ci_component_unchanged_without_an_existing_ci(self):
        out = run()
        ci = sup(out, "ci_cd")[0]
        self.assertNotIn("existing", ci["justification"].lower())
        self.assertNotIn("infrastructure.existing_systems", ci["driven_by"])

    def test_existing_orchestrator_is_integrated_not_replaced(self):
        for raw, typ in (("Apache Airflow 2.x on EC2", "data_analytics"), ("Prefect server", "web_app"), ("Dagster", "saas_b2b")):
            with self.subTest(raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                comp = sup(out, "Integration with existing " + raw)
                self.assertTrue(comp, raw)
                self.assertIn("instead of adding a second scheduler", comp[0]["justification"])

    def test_existing_object_store_is_not_called_a_legacy_application(self):
        for raw in ("S3 bucket with legacy imagery", "Azure Blob Storage account", "GCS bucket"):
            with self.subTest(raw=raw):
                out = run(infrastructure__existing_systems=[raw])
                comp = sup(out, "Integration with existing " + raw)
                self.assertTrue(comp, raw)
                self.assertNotIn("strangle", comp[0]["justification"])
                self.assertIn("read them in place", comp[0]["justification"])

    def test_existing_cloud_database_is_not_reached_through_an_on_prem_relay(self):
        for raw, cloud in (("Azure SQL Database", "azure"), ("Amazon RDS for MySQL", "aws"), ("Cloud SQL for PostgreSQL 12 (managed)", "gcp")):
            with self.subTest(raw=raw):
                out = run(infrastructure__cloud_preference=cloud, infrastructure__existing_systems=[raw])
                comp = [s for s in sup(out, "Integration with existing") if raw in s["choice"]]
                self.assertTrue(comp, raw)
                self.assertNotIn("Hybrid Connection", comp[0]["choice"])
                self.assertNotIn("on-prem", comp[0]["justification"] + " ".join(a["choice"] for a in comp[0]["alternatives"]))

    def test_on_prem_database_keeps_the_relay_wording(self):
        out = run(infrastructure__cloud_preference="azure", infrastructure__existing_systems=["On-prem SQL Server 2019"])
        comp = sup(out, "Integration with existing On-prem SQL Server 2019")
        self.assertIn("Hybrid Connection", comp[0]["choice"])


class UiSkillMismatch(unittest.TestCase):
    """B: SKILL_MISMATCH also covers the web and mobile UI layer for a small non-senior or beginner team."""

    def ui(self, out):
        return [w for w in warns(out, "SKILL_MISMATCH") if w["message"].startswith(("Web UI", "Mobile UI"))]

    def test_fires_on_three_project_types(self):
        cases = [
            dict(project__type="saas_b2b", project__platforms=["web", "android"], team__languages=["ruby"], team__size=2, team__experience="intermediate"),
            dict(project__type="web_app", project__platforms=["web"], team__languages=["swift"], team__size=3, team__experience="intermediate"),
            dict(project__type="internal_tool", project__platforms=["web"], team__languages=["r", "matlab"], team__size=3, team__experience="beginner"),
            dict(project__type="data_analytics", project__platforms=["web"], team__languages=["r"], team__size=14, team__experience="beginner"),
        ]
        for kw in cases:
            with self.subTest(kw=kw):
                hits = self.ui(run(**kw))
                self.assertTrue(hits, kw)
                self.assertIn("team.languages", hits[0]["fields"])
                self.assertIn("not in the team's languages", hits[0]["message"])

    def test_names_the_mobile_toolkit_for_a_ruby_team(self):
        out = run(project__type="saas_b2b", project__platforms=["web", "android"], team__languages=["ruby"], team__size=2)
        msg = " ".join(w["message"] for w in self.ui(out))
        self.assertIn("Mobile UI: Kotlin + Jetpack Compose", msg)
        self.assertIn("(ruby)", msg)

    def test_layer_choice_is_not_changed_by_the_warning(self):
        kw = dict(project__platforms=["web", "android"], team__languages=["ruby"], team__size=2)
        a = run(**kw)
        self.assertIn("Kotlin", a["stack"]["frontend"]["choice"])

    def test_does_not_fire_when_the_team_writes_the_language(self):
        for kw in (dict(team__languages=["typescript"], project__platforms=["web"]),
                   dict(team__languages=["kotlin"], project__platforms=["web", "android"], team__size=2),
                   dict(team__languages=["javascript"], project__platforms=["web", "android"], team__size=2)):
            with self.subTest(kw=kw):
                self.assertFalse(self.ui(run(**kw)), kw)

    def test_does_not_fire_for_a_large_or_senior_team_or_a_planned_hire(self):
        self.assertFalse(self.ui(run(project__platforms=["web"], team__languages=["python"], team__size=12, team__experience="intermediate")))
        self.assertFalse(self.ui(run(project__platforms=["web"], team__languages=["go", "python"], team__size=5, team__experience="senior")))
        self.assertFalse(self.ui(run(project__platforms=["web", "android"], team__languages=["ruby"], team__size=2, team__hiring_languages=["kotlin"])))


class DescriptionFacts(unittest.TestCase):
    """C: facts a description states that no enum field carries (uploads vs file_media_storage, SMS, e-mail delivery, app-store
    billing). Each is a DESC_RULES keyword signal with the shared negation guard."""

    def codes(self, out):
        return {w["code"] for w in out["warnings"]}

    def test_uploads_contradicting_the_storage_field_is_surfaced_and_storage_added(self):
        cases = [("marketplace", "Crowdfunding site. Organisers must upload hospital bills as PDFs for verification."),
                 ("saas_b2b", "Contract workflow where clients upload signed contracts as PDF files."),
                 ("internal_tool", "Staff upload expense receipts and managers approve them."),
                 ("web_app", "Members upload their ID document to join.")]
        for typ, desc in cases:
            with self.subTest(typ=typ):
                out = run(project__type=typ, desc=desc, requirements__file_media_storage=False)
                hit = warns(out, "UPLOADS_VS_STORAGE_FIELD")
                self.assertEqual(len(hit), 1, desc)
                self.assertIn("requirements.file_media_storage", hit[0]["fields"])
                self.assertIn("upload", hit[0]["message"])
                self.assertTrue(sup(out, "storage"), desc)

    def test_uploads_does_not_fire_when_field_true_negated_or_not_a_file(self):
        base = dict(project__type="saas_b2b")
        self.assertFalse(warns(run(desc="Clients upload signed contracts as PDF files.", requirements__file_media_storage=True, **base), "UPLOADS_VS_STORAGE_FIELD"))
        for desc in ("There is no upload of documents in this release.", "Users do not upload files; staff enter everything.",
                     "Sensors upload readings every minute.", "Devices upload telemetry to the cloud."):
            with self.subTest(desc=desc):
                out = run(desc=desc, requirements__file_media_storage=False, **base)
                self.assertFalse(warns(out, "UPLOADS_VS_STORAGE_FIELD"), desc)

    def test_sms_without_a_provider_gets_a_named_note(self):
        cases = [("healthtech", "SMS reminders for appointments."), ("saas_b2b", "Customers get appointment alerts by SMS."),
                 ("ecommerce", "Order updates are sent as text message alerts."), ("internal_tool", "Parents receive an SMS when a child is absent.")]
        for typ, desc in cases:
            with self.subTest(typ=typ):
                out = run(project__type=typ, desc=desc)
                hit = warns(out, "SMS_PROVIDER_NOT_SELECTED")
                self.assertEqual(len(hit), 1, desc)
                self.assertEqual(hit[0]["severity"], "info")
                self.assertIn("not in the cost band", hit[0]["message"])
                self.assertTrue([a for a in out["assumptions"] if "SMS provider" in a])

    def test_sms_not_fired_for_negation_chat_or_phone_otp_auth(self):
        for desc in ("We do not send SMS; reminders go by push.", "No SMS, only in-app messages.", "Users chat and send messages to each other."):
            with self.subTest(desc=desc):
                self.assertFalse(warns(run(desc=desc), "SMS_PROVIDER_NOT_SELECTED"), desc)
        out = run(desc="Login uses a phone OTP.", requirements__auth="phone_otp")
        self.assertFalse(warns(out, "SMS_PROVIDER_NOT_SELECTED"))

    def test_otp_in_description_without_phone_otp_auth_is_named(self):
        out = run(desc="Staff confirm payouts with a one-time password.", requirements__auth="email_password")
        self.assertTrue(warns(out, "SMS_PROVIDER_NOT_SELECTED"))

    def test_sms_in_an_air_gapped_network_is_a_warning(self):
        out = run(desc="Staff get SMS reminders.", infrastructure__deployment_model="air_gapped", infrastructure__cloud_preference="none")
        hit = warns(out, "SMS_NEEDS_TELECOM_LINK")
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["severity"], "warning")

    def test_email_delivery_component_for_list_and_transactional_mail(self):
        cases = [("content_site", "Paid newsletter for writers: posts go out by email.", ["web"]),
                 ("saas_b2b", "Invoicing tool that sends transactional emails to customers.", ["web"]),
                 ("ecommerce", "Shop that sends order confirmation emails.", ["web"]),
                 ("web_app", "Club site with a mailing list for members.", ["web"])]
        for typ, desc, plat in cases:
            with self.subTest(typ=typ):
                out = run(project__type=typ, desc=desc, project__platforms=plat)
                comp = sup(out, "Email delivery")
                self.assertEqual(len(comp), 1, desc)
                self.assertIn("not in the cost band", " ".join(comp[0]["tradeoffs"]))
                self.assertIn("project.description", comp[0]["driven_by"])

    def test_email_delivery_not_added_when_negated_unmentioned_or_self_hosted(self):
        for desc in ("There is no newsletter.", "We will not send transactional emails.", "A small booking site for a salon."):
            with self.subTest(desc=desc):
                self.assertFalse(sup(run(desc=desc), "Email delivery"), desc)
        out = run(desc="Staff get a weekly newsletter.", infrastructure__deployment_model="on_premise", infrastructure__cloud_preference="none")
        self.assertFalse(sup(out, "Email delivery"))

    def test_app_store_subscription_wording_selects_store_billing(self):
        for typ, desc in (("ai_ml_product", "Language app. Subscriptions are sold through the app stores."),
                          ("social", "Mood journal with a premium plan billed via the Apple App Store and Google Play."),
                          ("healthtech", "Meditation app whose subscriptions are purchased on the Play Store.")):
            with self.subTest(typ=typ):
                out = run(project__type=typ, desc=desc, project__platforms=["ios", "android"], requirements__payments=True)
                choice = sup(out, "payments")[0]["choice"]
                self.assertIn("In-App Purchase", choice, desc)
                self.assertNotIn("Stripe", choice)

    def test_store_billing_not_selected_for_distribution_wording_or_marketplaces(self):
        out = run(project__type="social", desc="Our app is available on the App Store and Google Play.", project__platforms=["ios", "android"],
                  requirements__payments=True)
        self.assertNotIn("In-App Purchase", sup(out, "payments")[0]["choice"])
        out = run(project__type="marketplace", desc="Sellers are paid through the app stores.", project__platforms=["ios", "android"], requirements__payments=True)
        self.assertNotIn("In-App Purchase", sup(out, "payments")[0]["choice"])


if __name__ == "__main__":
    unittest.main()
