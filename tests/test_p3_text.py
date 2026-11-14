"""Track p3 (15 Nov 2026): false or template sentences removed. Each test written before the change."""
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


if __name__ == "__main__":
    unittest.main()
