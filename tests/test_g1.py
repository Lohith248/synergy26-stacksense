"""G1 (D19-g1): store billing is a knowledge-base gap, not a proven residency conflict; an existing Azure SQL database is recognised;
a second database states why it exists; discontinued services name no unsourced replacement; the OTP cost line names the chosen
provider; default social providers follow the audience; the time-series text does not call uploaded files readings.
Every rule is tested on several project types plus inputs where it must not fire. Inputs are inline."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "G1", "project": {"type": "web_app", "platforms": ["web"], "description": "A small web application."},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "intermediate", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 3000}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def run(**kw):
    s = copy.deepcopy(BASE)
    for path, v in kw.items():
        node, parts = s, path.replace("__", ".").split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return evaluate(s, counterfactuals=False)


def warns(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


def sup(out, needle):
    return [s for s in out["stack"]["supporting"] if needle in s["choice"] or needle in s["layer"]]


MOBILE = dict(project__platforms=["ios", "android"], requirements__payments=True)


class StoreBillingLocation(unittest.TestCase):
    CASES = [
        dict(project__type="ai_ml_product", infrastructure__data_residency="eu", compliance=["gdpr"],
             project__description="Language tutor app. Subscriptions are sold through the app stores."),
        dict(project__type="gaming", infrastructure__data_residency="india", compliance=["dpdp"],
             project__description="Fantasy points game with premium packs sold in the app."),
        dict(project__type="social", infrastructure__data_residency="us", compliance=[],
             project__description="Photo sharing app with a paid premium tier bought in the app."),
    ]

    def test_gap_is_a_warning_naming_the_mechanism(self):
        for kw in self.CASES:
            with self.subTest(kw=kw["project__type"]):
                out = run(**MOBILE, **kw)
                self.assertFalse([w for w in out["warnings"] if w["code"] == "RESIDENCY_UNVERIFIED_SERVICE" and "Play" in w["message"]])
                w = [x for x in warns(out, "PAYMENT_DATA_LOCATION") if "Google Play" in x["message"]]
                self.assertEqual([x["severity"] for x in w], ["warning"])
                self.assertIn("purchase receipts", w[0]["message"])
                self.assertIn("a gap, not a proven conflict", w[0]["message"])

    def test_rbi_localisation_keeps_it_critical(self):
        out = run(**MOBILE, project__type="fintech", infrastructure__data_residency="india", compliance=["rbi_localisation", "dpdp"],
                  project__description="Wallet app. Premium subscriptions are sold through the app stores.")
        w = [x for x in warns(out, "PAYMENT_DATA_LOCATION") if "Google Play" in x["message"]]
        self.assertEqual([x["severity"] for x in w], ["critical"])
        self.assertIn("rbi_localisation", w[0]["message"])

    def test_web_gateway_has_no_store_warning(self):
        out = run(requirements__payments=True, infrastructure__data_residency="eu", compliance=["gdpr"])
        self.assertFalse([w for w in out["warnings"] if "Google Play" in w["message"]])


class ExistingAzureSql(unittest.TestCase):
    def test_azure_sql_is_recognised_and_second_database_reason_is_stated(self):
        for typ, langs in (("saas_b2b", ["csharp"]), ("internal_tool", ["csharp", "typescript"]), ("web_app", ["csharp"])):
            with self.subTest(typ=typ):
                out = run(project__type=typ, team__languages=langs, infrastructure__cloud_preference="azure",
                          infrastructure__existing_systems=["Azure SQL Database"])
                self.assertFalse([w for w in warns(out, "EXISTING_SYSTEM_UNRECOGNISED") if "Azure SQL" in w["message"]])
                self.assertIn("Azure SQL", out["stack"]["database"]["choice"])
                comp = sup(out, "Integration with existing Azure SQL")
                self.assertTrue(comp)
                self.assertIn("A second database exists only because", comp[0]["justification"])

    def test_different_engine_names_the_new_database(self):
        out = run(project__type="saas_b2b", infrastructure__existing_systems=["Oracle Database 19c"])
        comp = sup(out, "Integration with existing Oracle")
        self.assertIn("A second database exists only because", comp[0]["justification"])
        self.assertIn("scored best for this input", comp[0]["justification"])

    def test_kept_or_retired_database_has_no_second_database_text(self):
        for raw in ("Azure SQL Database (must stay)", "Azure SQL Database, to be retired"):
            with self.subTest(raw=raw):
                out = run(infrastructure__cloud_preference="azure", infrastructure__existing_systems=[raw])
                for s in sup(out, "Azure SQL"):
                    self.assertNotIn("A second database exists", s["justification"])


class DiscontinuedServices(unittest.TestCase):
    def test_no_replacement_is_invented(self):
        for typ, raw in (("saas_b2b", "Firebase Dynamic Links"), ("social", "Firebase Dynamic Links"), ("web_app", "Heroku free dynos")):
            with self.subTest(typ=typ, raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                w = [x for x in warns(out, "END_OF_LIFE_SYSTEM") if raw in x["message"]]
                self.assertEqual(len(w), 1)
                self.assertIn("no replacement named in the knowledge base", w[0]["message"])
                self.assertNotIn("Universal Links", w[0]["message"])

    def test_a_version_line_keeps_the_upgrade_wording(self):
        out = run(infrastructure__existing_systems=["Python 2 batch scripts"])
        w = [x for x in warns(out, "END_OF_LIFE_SYSTEM") if "Python 2" in x["message"]]
        self.assertTrue(w)
        self.assertIn("keep it behind an isolated interface", w[0]["message"])
        self.assertNotIn("no replacement named", w[0]["message"])


class OtpLineProvider(unittest.TestCase):
    def line(self, out):
        return [a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("Phone OTP")]

    def test_line_names_the_chosen_provider(self):
        cases = [(dict(infrastructure__data_residency="india"), "MSG91"),
                 (dict(infrastructure__cloud_preference="aws"), "Amazon SNS"),
                 (dict(project__type="ecommerce"), "Twilio Verify")]
        for kw, name in cases:
            with self.subTest(name=name):
                out = run(requirements__auth="phone_otp", **kw)
                self.assertEqual(len(self.line(out)), 1)
                self.assertIn(name, self.line(out)[0])

    def test_self_hosted_aggregator_is_not_named_as_twilio(self):
        out = run(requirements__auth="phone_otp", infrastructure__deployment_model="on_premise", infrastructure__cloud_preference="none")
        self.assertIn("reference rate", self.line(out)[0])
        self.assertIn("price is not in the knowledge base", self.line(out)[0])

    def test_no_otp_no_line(self):
        self.assertFalse(self.line(run()))


class SocialDefaults(unittest.TestCase):
    def auth(self, out):
        return sup(out, "auth")[0]["choice"]

    def test_consumer_apps_do_not_get_github_or_microsoft(self):
        for typ, plats in (("social", ["ios", "android"]), ("ecommerce", ["web", "ios"]), ("gaming", ["web", "android"])):
            with self.subTest(typ=typ):
                c = self.auth(run(project__type=typ, project__platforms=plats, requirements__auth="social"))
                self.assertIn("Google", c)
                self.assertNotIn("GitHub", c)
                self.assertNotIn("Microsoft", c)
                self.assertEqual("Apple" in c, "ios" in plats)

    def test_work_or_developer_audience_keeps_the_work_providers(self):
        for kw in (dict(project__type="saas_b2b"), dict(project__type="api_platform"),
                   dict(project__type="web_app", project__description="A code review tool for developers.")):
            with self.subTest(kw=kw):
                self.assertIn("GitHub", self.auth(run(requirements__auth="social", **kw)))


class TimeSeriesText(unittest.TestCase):
    def ts(self, **kw):
        out = run(scale__workload="write_heavy", scale__data_volume_gb_12_months=20000, **kw)
        return sup(out, "Time-series")[0]["justification"]

    def test_uploaded_files_are_not_called_readings(self):
        for typ in ("saas_b2b", "ecommerce", "social"):
            with self.subTest(typ=typ):
                t = self.ts(project__type=typ, requirements__file_media_storage=True)
                self.assertNotIn("append-only readings", t)
                self.assertIn("uploaded files sit in object storage", t)

    def test_sensor_workload_still_says_readings(self):
        t = self.ts(project__type="iot", project__description="5,000 sensors report every minute.")
        self.assertIn("append-only readings", t)


if __name__ == "__main__":
    unittest.main()
