"""Round 10 (12 Nov session): adversarial review of round 9 (existing-systems reuse). Each test written before the fix;
inputs are the reviewer's probes (modifications of ../research/blind4/C05_ClaimDesk.json and the public scenarios)."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.run import evaluate  # noqa: E402
from engine import context as cx  # noqa: E402
from test_round9 import PUBLIC, run, codes, sup, dump  # noqa: E402

D = "Claims portal for a regional insurer."


def kept(existing, desc=D, **kw):
    out = run(**{"infrastructure.existing_systems": existing, "project.description": desc, **kw})
    return out, out["stack"]["database"]


def warn(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


class KeptDbDeployment(unittest.TestCase):  # item 1
    def test_managed_services_are_managed(self):
        for raw in ("MongoDB Atlas cluster (must stay)", "Amazon RDS PostgreSQL in us-east-1 (must stay)"):
            with self.subTest(raw=raw):
                _, db = kept([raw])
                self.assertIn("reused", db["choice"])
                self.assertEqual(db["deployment"], "managed")
                self.assertIn("managed service", db["choice"])

    def test_on_prem_stays_self_managed(self):
        _, db = kept(["SQL Server 2019 on-prem (must stay)"])
        self.assertEqual(db["deployment"], "self_hosted")


class KeptDbLocation(unittest.TestCase):  # item 2
    def test_region_contradicts_residency(self):
        out, db = kept(["Amazon RDS PostgreSQL in us-east-1 (must stay)"], **{"infrastructure.data_residency": "eu"})
        self.assertEqual(db["data_location"], "us")
        self.assertEqual(warn(out, "EXISTING_DB_RESIDENCY_CONFLICT")[0]["severity"], "critical")
        self.assertEqual(out["status"], "ok_with_warnings")

    def test_region_matches_residency(self):
        out, db = kept(["Amazon RDS PostgreSQL in eu-central-1 (must stay)"], **{"infrastructure.data_residency": "eu"})
        self.assertEqual(db["data_location"], "eu")
        self.assertFalse(warn(out, "EXISTING_DB_RESIDENCY_CONFLICT") + warn(out, "RESIDENCY_UNVERIFIED_SERVICE"))

    def test_unknown_location_under_rbi(self):
        out, db = kept(["SQL Server 2022 (must stay)"], **{"infrastructure.data_residency": "india",
                                                            "compliance": ["rbi_localisation"], "project.type": "fintech"})
        self.assertEqual(db["data_location"], "unverified")
        w = warn(out, "RESIDENCY_UNVERIFIED_SERVICE")
        self.assertTrue(w and w[0]["severity"] == "critical" and "SQL Server" in w[0]["message"])
        self.assertEqual(out["status"], "ok_with_warnings")

    def test_named_city_matches(self):
        out, db = kept(["SQL Server 2022 in our Mumbai data centre (must stay)"], **{"infrastructure.data_residency": "india"})
        self.assertEqual(db["data_location"], "india")
        self.assertFalse(warn(out, "RESIDENCY_UNVERIFIED_SERVICE"))

    def test_saas_db_under_air_gap_is_a_contradiction(self):
        for dm in ("air_gapped", "on_premise"):
            with self.subTest(dm=dm):
                out, db = kept(["MongoDB Atlas cluster (must stay)"], **{"infrastructure.deployment_model": dm,
                                                                         "infrastructure.cloud_preference": "none"})
                self.assertEqual(warn(out, "EXTERNAL_EXISTING_DATABASE")[0]["severity"], "critical")
                self.assertEqual(out["status"], "ok_with_warnings")

    def test_no_residency_no_location_warning(self):
        out, db = kept(["PostgreSQL 16 (must stay)"])
        self.assertIsNone(db["data_location"])
        self.assertFalse(warn(out, "RESIDENCY_UNVERIFIED_SERVICE"))


class KeepPhrases(unittest.TestCase):  # item 3
    def assertKept(self, existing, desc=D, want=True):
        _, db = kept(existing, desc)
        self.assertEqual("reused" in db["choice"], want, (existing, desc, db["choice"]))

    def test_false_positives(self):
        for ex, desc in [(["Oracle Database 19c"], D + " We will replace Oracle, keep costs low."),
                         (["MongoDB 7"], D + " Migrate off MongoDB, the team stays small."),
                         (["PostgreSQL 14"], D + " The old Postgres must not remain after launch."),
                         (["MySQL 8.4"], D + " Retain no customer data in MySQL after cutover."),
                         (["PostgreSQL 14"], D + " Reuse our Postgres monitoring dashboards for the new database."),
                         (["PostgreSQL 16 (to be retired, do not keep)"], D),
                         (["MySQL 8.0 - we will not keep it"], D)]:
            with self.subTest(ex=ex, desc=desc):
                self.assertKept(ex, desc, False)

    def test_oracle_non_database_products(self):
        for raw in ("Oracle Cloud Infrastructure tenancy (we keep it)", "Oracle E-Business Suite R12 (stays)"):
            with self.subTest(raw=raw):
                out, db = kept([raw])
                self.assertNotIn("Oracle", db["choice"])
                self.assertFalse(any("Oracle Database" in s["choice"] for s in sup(out, "other")))

    def test_true_positives(self):
        for ex, desc in [(["Oracle Database 19c (must stay)"], D), (["Oracle Database 19c (must remain the source of truth)"], D),
                         (["Oracle Database 19c (system of record)"], D),
                         (["Oracle Database 19c"], D + " The Oracle database cannot be migrated."),
                         (["Oracle Database 19c"], D + " The Oracle database must be preserved."),
                         (["Oracle Database 19c"], D + " The Oracle database cannot be decommissioned."),
                         (["Oracle Database 19c"], D + " The Oracle database stays as-is."),
                         (["Oracle 19c"], D + " Keep the Oracle database for finance."),
                         (["PostgreSQL 16 cluster"], D + " The existing PostgreSQL cluster must remain the source of truth.")]:
            with self.subTest(ex=ex, desc=desc):
                self.assertKept(ex, desc, True)


class SeveralDatabases(unittest.TestCase):  # item 4
    def test_kept_one_wins_over_first(self):
        out, db = kept(["Oracle 19c reporting copy", "PostgreSQL 16 (must stay)"])
        self.assertIn("PostgreSQL", db["choice"])
        self.assertIn("reused", db["choice"])
        self.assertTrue(any("Oracle" in s["choice"] for s in sup(out, "other")))

    def test_two_kept_names_the_other(self):
        out, db = kept(["MySQL 8.4 (must stay)", "PostgreSQL 16 (must stay)"])
        self.assertIn("reused", db["choice"])
        w = warn(out, "SEVERAL_KEPT_DATABASES")
        self.assertTrue(w and w[0]["severity"] == "info")
        other = "PostgreSQL 16" if "MySQL" in db["choice"] else "MySQL 8.4"
        self.assertIn(other, w[0]["message"])


class ExistingLanguage(unittest.TestCase):  # item 5
    def test_incidental_words(self):
        self.assertEqual(cx.existing_langs(["Kubernetes node pool"]), set())
        self.assertEqual(cx.existing_langs(["Flask-shaped logo asset library"]), set())
        self.assertEqual(cx.existing_langs(["Java 8 app (to be decommissioned, rewrite in Python)"]), set())
        self.assertEqual(cx.existing_langs(["Billing service (rewrite in Go 1.23)"]), set())

    def test_real_apps(self):
        self.assertEqual(cx.existing_langs(["Java 8 application on Tomcat 7"]), {"java"})
        self.assertEqual(cx.existing_langs(["Node.js 18 API"]), {"javascript"})
        self.assertEqual(cx.existing_langs(["Legacy Spring Boot billing service"]), {"java"})
        self.assertEqual(cx.existing_langs(["Express.js backend"]), {"javascript"})

    def test_public_probes_unchanged(self):
        for sid, fake in (("P6", "Kubernetes node pool"), ("P2", "Flask-shaped logo asset library")):
            with self.subTest(sid=sid):
                base = evaluate(copy.deepcopy(PUBLIC[sid]), counterfactuals=False)
                s = copy.deepcopy(PUBLIC[sid])
                s["infrastructure"]["existing_systems"] = list(s["infrastructure"].get("existing_systems", [])) + [fake]
                out = evaluate(s, counterfactuals=False)
                self.assertEqual(out["stack"]["backend"]["choice"], base["stack"]["backend"]["choice"])


class ExistingBroker(unittest.TestCase):  # item 6
    def test_no_queue_without_need(self):
        out = run(**{"infrastructure.existing_systems": ["Kafka cluster (Amazon MSK)"], "scale.users_12_months": 200,
                     "scale.users_at_launch": 100, "scale.peak_concurrent_users": 20, "scale.workload": "read_heavy",
                     "project.description": "Simple internal staff directory."})
        self.assertEqual(sup(out, "queue"), [])
        self.assertTrue(warn(out, "EXISTING_BROKER_AVAILABLE"))

    def test_used_when_queue_needed_cross_cloud_noted(self):
        out = run(**{"infrastructure.existing_systems": ["Kafka cluster (Amazon MSK)"], "infrastructure.cloud_preference": "azure",
                     "scale.workload": "write_heavy", "scale.users_12_months": 200000, "scale.peak_concurrent_users": 5000})
        q = sup(out, "queue")
        self.assertEqual(len(q), 1)
        self.assertIn("Kafka", q[0]["choice"])
        self.assertTrue(any("AWS" in t for t in q[0]["tradeoffs"]), q[0]["tradeoffs"])

    def test_amqp_service_bus_is_not_rabbitmq(self):
        out = run(**{"infrastructure.existing_systems": ["AMQP-compatible Azure Service Bus"]})
        self.assertNotIn("RabbitMQ", dump(out))


class LedgerOnNoSql(unittest.TestCase):  # item 7
    def test_ledger_warning(self):
        out = run(**{"infrastructure.existing_systems": ["MongoDB 7 (must stay)"], "project.type": "fintech",
                     "requirements.payments": True, "project.description": "Wallet ledger with double-entry postings."})
        self.assertIn("MongoDB", out["stack"]["database"]["choice"])
        w = warn(out, "LEDGER_ON_NON_RELATIONAL_DB")
        self.assertTrue(w and w[0]["severity"] == "warning" and "relational" in w[0]["message"])

    def test_relational_kept_no_warning(self):
        out = run(**{"infrastructure.existing_systems": ["PostgreSQL 16 (must stay)"], "project.type": "fintech",
                     "requirements.payments": True, "project.description": "Wallet ledger with double-entry postings."})
        self.assertFalse(warn(out, "LEDGER_ON_NON_RELATIONAL_DB"))


class Identity(unittest.TestCase):  # item 8
    def test_workforce_okta_not_for_customers(self):
        for a in ("email_password", "social"):
            with self.subTest(auth=a):
                out = run(**{"infrastructure.existing_systems": ["Okta workforce tenant"], "requirements.auth": a,
                             "project.description": "Customer self-service portal."})
                self.assertNotIn("Okta", sup(out, "auth")[0]["choice"])
        out = run(**{"infrastructure.existing_systems": ["Okta workforce tenant"], "requirements.auth": "enterprise_sso"})
        self.assertIn("Okta", sup(out, "auth")[0]["choice"])

    def test_customer_okta_still_reused(self):
        out = run(**{"infrastructure.existing_systems": ["Okta (workforce and customer SSO)"], "requirements.auth": "email_password"})
        self.assertIn("Okta", sup(out, "auth")[0]["choice"])

    def test_two_idps_two_brokers_named(self):
        out = run(**{"infrastructure.existing_systems": ["Okta", "Microsoft Entra ID", "Kafka", "RabbitMQ 3.12 (must stay)"],
                     "requirements.auth": "enterprise_sso"})
        w = warn(out, "SEVERAL_EXISTING_SYSTEMS")
        text = " ".join(x["message"] for x in w)
        self.assertTrue(w and all(x["severity"] == "info" for x in w))
        self.assertIn("Okta", text)
        self.assertIn("Kafka", text)


class WholeWordPatterns(unittest.TestCase):  # item 9
    def test_substrings_do_not_match(self):
        for raw in ("WhatsApp Business API", "Admongo", "Shopping cart plugin", "Mapping service (Leaflet)", "Teamspeak server"):
            with self.subTest(raw=raw):
                out = run(**{"infrastructure.existing_systems": [raw], "requirements.auth": "enterprise_sso"})
                self.assertIn("EXISTING_SYSTEM_UNRECOGNISED", codes(out))

    def test_intended_inputs_match(self):
        for raw in ("PostgreSQL 16", "Postgres 14", "MongoDB 6", "Mongo 5", "MySQL 8", "MariaDB 10", "SQL Server 2019", "MSSQL",
                    "Oracle Database 19c", "Oracle 11g", "Apache Kafka", "Amazon MSK", "Confluent Cloud", "RabbitMQ 3.13",
                    "Okta", "Auth0", "Keycloak 24", "Microsoft Entra ID", "Azure AD", "On-prem Active Directory", "OpenLDAP",
                    "Google Workspace", "SAP S/4HANA", "Salesforce CRM", "Stripe", "Microsoft 365", "Legacy PHP 7 monolith",
                    "Ping Identity"):
            with self.subTest(raw=raw):
                out = run(**{"infrastructure.existing_systems": [raw], "requirements.auth": "enterprise_sso"})
                self.assertNotIn("EXISTING_SYSTEM_UNRECOGNISED", codes(out))


if __name__ == "__main__":
    unittest.main()
