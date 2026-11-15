"""p5b (review of p5): probe inputs from the review as tests; synthetic inputs only."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup  # noqa: E402
from engine import context as cx  # noqa: E402

ORA = ["Oracle Database 19c"]


def db_choice(out):
    return out["stack"]["database"]["choice"]


def text(out):
    return json.dumps(out, ensure_ascii=False)


class ExistingDbWrite(unittest.TestCase):
    """M1: reuse only when the existing database itself is written, and never when a sentence migrates or replaces it."""

    def test_migrated_or_replaced_not_reused(self):
        for desc in [
            "Migrate data from the Oracle database and write everything to the new PostgreSQL cluster.",  # P1
            "The service reads customer records from the Oracle database and writes new orders to Kafka.",  # P7
            "The Oracle database will be replaced by PostgreSQL next year; until then the new app must read and write the Oracle database.",  # P2
            "The new app must read and write the Oracle database until we migrate it to PostgreSQL.",  # P2b
            "Read-only reporting dashboard over the Oracle database.",  # P6
        ]:
            out = run(**{"project.description": desc, "infrastructure.existing_systems": ORA})
            self.assertNotIn("Existing Oracle", db_choice(out), desc)

    def test_written_db_still_reused(self):
        for desc, ex in [
            ("Internal claims screens for 400 back-office staff. Must read and write the existing Oracle policy database.",
             ["Oracle Database 19c (policy data)"]),  # K17 shape
            ("Must read/write the existing complaints register (old Oracle 11g DB) because 15 yrs of records live there.", ORA),  # G02 shape
        ]:
            out = run(**{"project.description": desc, "infrastructure.existing_systems": ex})
            self.assertIn("Existing Oracle", db_choice(out), desc)


class StaffOnlySignIn(unittest.TestCase):
    """M2: customers who sign in to check out are not anonymous readers."""

    P3 = ("Visitors don't need to log in to browse, but customers must sign in to check out and see order history. "
          "Staff log in to manage stock.")

    def test_customer_sign_in_is_not_staff_only(self):
        self.assertIsNone(cx.staff_login_count(self.P3.lower()))
        out = run(**{"project.type": "ecommerce", "project.description": self.P3, "infrastructure.cloud_preference": "aws",
                     "requirements.auth": "email_password", "scale.users_at_launch": 120000, "scale.users_12_months": 400000})
        self.assertNotIn("staff who sign in", text(out))
        self.assertNotIn("staff sign-ins", text(out))

    def test_type_gate(self):
        out = run(**{"project.type": "ecommerce", "infrastructure.cloud_preference": "aws", "requirements.auth": "email_password",
                     "project.description": "Readers do not need to log in. Editors log in to publish."})
        self.assertNotIn("staff sign-ins", text(out))

    def test_staff_only_still_fires(self):
        self.assertEqual(cx.staff_login_count("readers do not log in; staff users log in."), cx.STAFF_LOGIN_DEFAULT)
        self.assertEqual(cx.staff_login_count("readers do not need to log in. editors log in to publish."), cx.STAFF_LOGIN_DEFAULT)

    def test_staff_counts(self):  # S5
        self.assertEqual(cx.staff_login_count("readers do not need to log in. our 1,200 employees log in to publish."), 1200)
        self.assertEqual(cx.staff_login_count("a 24/7 newsroom of editors; readers do not log in, editors log in."), cx.STAFF_LOGIN_DEFAULT)
        self.assertEqual(cx.staff_login_count("readers never sign in; 40 reporters and 5 editors log in."), 45)


class FrontDoorTier(unittest.TestCase):
    """S1/S2/S3: Premium needs a security or scale signal; the CDN line agrees with the WAF line; Standard fees stay an estimate."""

    BASE = {"project.type": "ecommerce", "infrastructure.cloud_preference": "azure", "requirements.payments": True,
            "priorities.security": 4, "requirements.auth": "email_password"}

    def waf(self, out):
        return [s for s in sup(out, "other") if "Front Door" in s["choice"]]

    def test_bakery_gets_standard(self):  # P4: 50 users, team of 1, budget headroom only
        out = run(**{**self.BASE, "project.description": "Online shop for a small bakery.", "scale.users_at_launch": 50,
                     "scale.users_12_months": 50, "team.size": 1, "budget.monthly_infra_usd": 2200})
        w = self.waf(out)
        self.assertEqual(len(w), 1)
        self.assertIn("Standard", w[0]["choice"])
        self.assertIn("not confirmed", w[0]["justification"])
        self.assertNotIn("Premium tier for its WAF", text(out))

    def test_signal_gets_premium_and_cdn_agrees(self):
        out = run(**{**self.BASE, "project.description": "Online shop with customer accounts.", "priorities.security": 5,
                     "scale.users_at_launch": 20000, "scale.users_12_months": 60000, "budget.monthly_infra_usd": 4000})
        w = self.waf(out)
        self.assertEqual(len(w), 1)
        self.assertIn("Premium", w[0]["choice"])
        t = text(out)
        self.assertNotIn("Front Door Standard has a $35/month base fee", t)
        if any("Front Door" in s["choice"] for s in sup(out, "cdn")):
            self.assertIn("Premium tier for its WAF", t)


class CognitoAndVideo(unittest.TestCase):
    def test_cognito_lite_named(self):  # S4
        out = run(**{"infrastructure.cloud_preference": "aws", "requirements.auth": "email_password",
                     "scale.users_at_launch": 50000, "scale.users_12_months": 100000})
        if any("Cognito" in s["choice"] for s in sup(out, "auth")):
            self.assertIn("new pools default to Essentials", text(out))

    def test_video_egress_names_cdn_only_in_stack(self):  # S6
        out = run(**{"infrastructure.cloud_preference": "aws", "project.type": "internal_tool",
                     "project.description": "Video on demand streaming of recorded training lectures.",
                     "scale.users_at_launch": 3000, "scale.users_12_months": 4000})
        self.assertEqual(sup(out, "cdn"), [])
        self.assertIn("Video egress", text(out))
        self.assertNotIn("CloudFront pay-as-you-go", text(out))


if __name__ == "__main__":
    unittest.main()
