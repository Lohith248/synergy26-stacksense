"""E6: existing_systems entries the knowledge base does not know by name are classified by keyword (database, message broker,
identity, API, system of record, health interchange) and handled by category. Each test written before the change."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes, dump  # noqa: E402

AWS = {"infrastructure.cloud_preference": "aws"}


def ex(*systems, **kw):
    return run(**{"infrastructure.existing_systems": list(systems), **kw})


def warn(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


def integrations(out, needle):
    return [s for s in sup(out, "other") if s["choice"].startswith("Integration with existing") and needle in s["choice"]]


class UnrecognisedDatabase(unittest.TestCase):
    def test_db2_mainframe_must_stay_is_the_database(self):
        out = ex("Db2 mainframe (must stay)", **AWS)
        db = out["stack"]["database"]
        self.assertIn("Db2", db["choice"])
        self.assertIn("reused", db["choice"])
        self.assertEqual(db["deployment"], "self_hosted")
        self.assertIn("infrastructure.existing_systems", db["driven_by"])

    def test_kept_database_gets_an_integration_component_and_hybrid_style(self):
        out = ex("Db2 mainframe (must stay)", **AWS)
        self.assertTrue(integrations(out, "Db2"), [s["choice"] for s in sup(out, "other")])
        self.assertEqual(out["architecture_style"], "hybrid")

    def test_database_that_may_move_is_integrated_not_reused(self):
        out = ex("Sybase ASE database")
        self.assertNotIn("reused", out["stack"]["database"]["choice"])
        self.assertTrue(integrations(out, "Sybase"))

    def test_classification_is_stated(self):
        out = ex("Informix database (must stay)")
        w = warn(out, "EXISTING_SYSTEM_UNRECOGNISED")
        self.assertTrue(w and w[0]["severity"] == "info" and "database" in w[0]["message"], w)


class UnrecognisedBrokerIdentityApi(unittest.TestCase):
    def test_mq_broker_is_the_broker(self):
        out = ex("IBM MQ broker (must stay)")
        q = sup(out, "queue")
        self.assertTrue(q and "IBM MQ" in q[0]["choice"] and "reused" in q[0]["choice"], q)
        self.assertIn("infrastructure.existing_systems", q[0]["driven_by"])

    def test_broker_not_needed_is_only_noted(self):
        out = ex("ActiveMQ queue server")
        self.assertIn("EXISTING_BROKER_AVAILABLE", codes(out))
        self.assertFalse(sup(out, "queue"))

    def test_active_directory_stays_a_recognised_identity_system(self):
        out = ex("Active Directory", **{"requirements.auth": "enterprise_sso"})
        self.assertFalse(warn(out, "EXISTING_SYSTEM_UNRECOGNISED"))
        self.assertTrue(sup(out, "auth")[0]["choice"].startswith("Microsoft Entra ID (OIDC)"))

    def test_saml_sso_gateway_is_reused_for_enterprise_sso(self):
        out = ex("Corporate SAML SSO gateway (must stay)", **{"requirements.auth": "enterprise_sso"})
        a = sup(out, "auth")
        self.assertTrue(a and "Corporate SAML SSO gateway" in a[0]["choice"] and "existing" in a[0]["choice"], a)
        self.assertNotIn("EXISTING_IDP_NOT_USED", codes(out))

    def test_leading_dot_of_a_name_is_kept(self):
        out = ex(".NET Core 3.1 API", **AWS)
        self.assertTrue(integrations(out, ".NET Core 3.1 API"), [s["choice"] for s in sup(out, "other")])

    def test_soap_billing_service_is_an_api_integration(self):
        out = ex("SOAP billing service")
        self.assertTrue(integrations(out, "SOAP billing service"), [s["choice"] for s in sup(out, "other")])
        w = warn(out, "EXISTING_SYSTEM_UNRECOGNISED")
        self.assertTrue(w and "API" in w[0]["message"], w)


class UnrecognisedRecords(unittest.TestCase):
    def test_core_banking_must_stay_is_integrated_in_hybrid_style(self):
        out = ex("Core banking system (must stay)", **AWS)
        self.assertTrue(integrations(out, "Core banking system"))
        self.assertEqual(out["architecture_style"], "hybrid")

    def test_hl7_interface_engine(self):
        out = ex("HL7 interface engine")
        self.assertTrue(integrations(out, "HL7 interface engine"))
        self.assertIn("health", warn(out, "EXISTING_SYSTEM_UNRECOGNISED")[0]["message"])


class StillIgnored(unittest.TestCase):
    def test_no_keyword_is_ignored_with_an_assumption(self):
        # f2/A7: "spreadsheet" now names a file exchange (File import job); an entry with no kind-of-system word stays ignored
        raw = "Stamp collection notebook"
        out = ex(raw)
        self.assertIn("EXISTING_SYSTEM_UNRECOGNISED", codes(out))
        self.assertFalse(integrations(out, "Stamp"))
        self.assertTrue(any(raw in a and "no component" in a for a in out["assumptions"]), out["assumptions"])

    def test_keywords_are_whole_words(self):
        # f2/A7: "Mqtt" is the MQTT protocol, so it gets an MQTT adapter (never the message-broker keyword 'mq', which is not matched inside it)
        for raw in ("Dbase hobby notes", "Broken windows tracker"):
            with self.subTest(raw=raw):
                out = ex(raw)
                self.assertFalse(integrations(out, raw))
                self.assertTrue(any(raw in a and "no component" in a for a in out["assumptions"]))
        out = ex("Mqtt sensor gateway")
        self.assertFalse(integrations(out, "Mqtt"))
        self.assertTrue([s for s in sup(out, "other") if s["choice"].startswith("MQTT adapter")])
        self.assertFalse([w for w in warn(out, "EXISTING_SYSTEM_UNRECOGNISED") if "message broker" in w["message"]])

    def test_a_spreadsheet_entry_is_a_file_exchange(self):
        out = ex("Stamp collection spreadsheet")
        self.assertTrue([s for s in sup(out, "other") if s["choice"].startswith("File import job")])
        self.assertFalse(any("no component" in a for a in out["assumptions"]))


class KnownEntriesUnchanged(unittest.TestCase):
    def test_known_systems_keep_their_own_handling(self):
        out = ex("Oracle Database 19c (must remain system of record)", "Okta", "Kafka cluster (must stay)", **{"requirements.auth": "enterprise_sso"})
        self.assertEqual(out["stack"]["database"]["choice"], "Existing Oracle Database (self-managed, reused)")
        self.assertIn("Okta", sup(out, "auth")[0]["choice"])
        self.assertIn("Apache Kafka", sup(out, "queue")[0]["choice"])
        self.assertFalse(warn(out, "EXISTING_SYSTEM_UNRECOGNISED"))
        self.assertFalse([a for a in out["assumptions"] if "no component" in a])

    def test_list_order_does_not_matter(self):
        a = ex("Db2 mainframe (must stay)", "IBM MQ broker", "SOAP billing service", "Okta", "Stamp collection")
        b = ex("Stamp collection", "Okta", "SOAP billing service", "IBM MQ broker", "Db2 mainframe (must stay)")
        self.assertEqual(dump(a), dump(b))


class MauiForDotnetTeams(unittest.TestCase):
    def test_csharp_team_gets_maui_for_cross_platform_mobile(self):
        out = run(**{"team.languages": ["csharp"], "project.platforms": ["android", "ios"]})
        self.assertIn("MAUI", out["stack"]["frontend"]["choice"], out["stack"]["frontend"]["choice"])


if __name__ == "__main__":
    unittest.main()
