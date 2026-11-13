"""F4/A3 (blind8): lifecycle gaps for legacy products, self-hosted Microsoft products never read as Microsoft 365, END_OF_LIFE_SUSPECTED
for unrecognised old-release markers, and a retiring system's integration is a one-off read.
Every rule is tested on several project types plus inputs where it must not fire. Inputs are inline."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402
from engine import context as cx  # noqa: E402
from engine.kb import SOURCES  # noqa: E402

BASE = {"scenario_id": "F4A3", "project": {"type": "web_app", "platforms": ["web"], "description": "A small web application."},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "intermediate", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 2000}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none",
                           "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def run(existing, typ="web_app", desc=None):
    s = copy.deepcopy(BASE)
    s["project"]["type"] = typ
    if desc:
        s["project"]["description"] = desc
    s["infrastructure"]["existing_systems"] = existing if isinstance(existing, list) else [existing]
    return evaluate(s, counterfactuals=False)


def warns(out, code, raw=None):
    return [w for w in out["warnings"] if w["code"] == code and (raw is None or raw in w["message"])]


def sup(out, needle):
    return [s for s in out["stack"]["supporting"] if needle in s["choice"]]


class NewLifecycleEntries(unittest.TestCase):
    CASES = [  # (existing_systems entry, project type)
        ("Java 6 / Struts 1 intranet app", "internal_tool"), ("JDK 1.6 batch server", "saas_b2b"), ("Java SE 7 payroll client", "web_app"),
        ("Struts 1.3 portal", "ecommerce"), ("Adobe Flash admin console", "internal_tool"), ("old Flash app for kiosks", "web_app"),
        ("Oracle Forms 6i billing system", "internal_tool"), ("Oracle Forms and Reports 10g", "saas_b2b"), ("Oracle Forms 11g", "web_app"),
        ("phpBB 3.0 forum database (MySQL)", "community"), ("phpBB 3.2 board", "web_app"),
        ("SharePoint Server 2013", "internal_tool"), ("SharePoint 2010 document store", "saas_b2b"), ("SharePoint Server 2016", "web_app"),
        ("Mosquitto 1.6 MQTT broker", "iot_platform"), ("Silverlight dashboard", "internal_tool"), ("ColdFusion 9 intranet", "web_app"),
        ("Classic ASP order screens", "internal_tool"), ("asp 3.0 reports", "ecommerce"), (".NET Framework 4.5.2 service", "saas_b2b"),
        (".NET Framework 4.0 desktop app", "internal_tool"), ("Apache Tomcat 7.0.99", "web_app"), ("Tomcat 6", "saas_b2b"), ("Tomcat 8.5 cluster", "internal_tool"),
        ("IE 11 only kiosks", "internal_tool"),
    ]

    def test_each_gets_an_eol_warning_not_the_unrecognised_note(self):
        for raw, typ in self.CASES:
            with self.subTest(raw=raw):
                out = run(raw, typ if typ in ("web_app", "saas_b2b", "ecommerce", "internal_tool") else "web_app")
                self.assertTrue(warns(out, "END_OF_LIFE_SYSTEM", raw), [w["code"] + w["message"][:60] for w in out["warnings"]])
                self.assertFalse([w for w in warns(out, "EXISTING_SYSTEM_UNRECOGNISED", raw) if "not in the knowledge base;" in w["message"]], raw)
                self.assertFalse(warns(out, "END_OF_LIFE_SUSPECTED", raw), raw)

    def test_added_dates_are_soft_and_sources_unverified(self):
        for raw in ("Java 6 / Struts 1 intranet app", "Adobe Flash admin console", "SharePoint Server 2013", "Tomcat 7.0.99", "Silverlight dashboard"):
            with self.subTest(raw=raw):
                msg = warns(run(raw), "END_OF_LIFE_SYSTEM", raw)[0]["message"]
                self.assertIn("has not re-checked the exact date", msg)
                self.assertNotRegex(msg, r"\d{4}-\d{2}-\d{2}")
        for sid in {lc["src"] for lc in cx.TECH["lifecycle"] if lc.get("soft")}:
            self.assertEqual(SOURCES[sid]["status"], "official-unverified", sid)
            self.assertNotEqual(SOURCES[sid]["status"], "verified", sid)

    def test_sharepoint_2010_uses_the_extended_end_date(self):
        m = warns(run("SharePoint 2010 document store", "saas_b2b"), "END_OF_LIFE_SYSTEM")[0]["message"]
        self.assertIn("around April 2021", m)
        self.assertNotIn("October 2020", m)

    def test_tomcat_8_lines_have_their_own_dates(self):
        for raw, want, never in (("Tomcat 8.0.53", "around June 2018", "2024"), ("Apache Tomcat 8.5.100", "around March 2024", "2018")):
            with self.subTest(raw=raw):
                m = warns(run(raw), "END_OF_LIFE_SYSTEM")[0]["message"]
                self.assertIn(want, m)
                self.assertNotIn(never, m)
        m = warns(run("Tomcat 8 app server"), "END_OF_LIFE_SYSTEM")[0]["message"]  # no minor line: both dates, no single one
        self.assertIn("8.0 ended in June 2018 and 8.5 in March 2024; check which line", m)
        self.assertNotIn("around", m)

    def test_every_product_an_entry_names_gets_its_warning(self):
        for raw, names in (("Java 6 / Struts 1 intranet app", ("Oracle Java SE 6", "Apache Struts 1.x")),
                           ("SQL Server 2008 on Windows Server 2008", ("SQL Server 2008/2008 R2", "Windows Server 2008 / 2008 R2")),
                           ("Tomcat 6 with Oracle 10g", ("Apache Tomcat 6.x", "Oracle Database 10.2"))):
            with self.subTest(raw=raw):
                msgs = " | ".join(w["message"] for w in warns(run(raw, "internal_tool"), "END_OF_LIFE_SYSTEM", raw))
                for n in names:
                    self.assertIn(f"({n}", msgs)
        self.assertEqual(len(warns(run("Struts 1.3 portal"), "END_OF_LIFE_SYSTEM")), 1)  # one product, one warning

    def test_no_date_is_printed_for_entries_without_a_confident_year(self):
        for raw in ("Oracle Forms 6i billing system", "ColdFusion 9 intranet"):
            msg = warns(run(raw), "END_OF_LIFE_SYSTEM", raw)[0]["message"]
            self.assertIn("older than any release its vendor still lists as supported", msg)
            self.assertNotRegex(msg, r"\d{4}-\d{2}-\d{2}")

    def test_older_lines_and_legacy_use_their_own_wording(self):
        m = warns(run("Mosquitto 1.6 MQTT broker"), "END_OF_LIFE_SYSTEM")[0]["message"]
        self.assertIn("older release line than the current Mosquitto 2.x", m)
        self.assertIn("does not confirm whether it still receives security fixes", m)
        m = warns(run("Classic ASP order screens", "internal_tool"), "END_OF_LIFE_SYSTEM")[0]["message"]
        self.assertIn("legacy technology without new development", m)
        self.assertNotIn("reached end of support", m)

    def test_supported_or_unrelated_names_do_not_fire(self):
        for raw in ("Java 17 service", "Java 21 LTS", "JDK 1.8 batch", "Tomcat 10.1", "Tomcat 9", "SharePoint Online", ".NET Framework 4.8",
                    ".NET Framework 4.6.2 service", ".NET Framework 4.8.1", "phpBB 3.3", "Mosquitto 2.0 broker", "ColdFusion 2023", "Struts 2.5 app",
                    "Flash storage array", "flash sale module", "Classic rock catalogue", "Apache Airflow 2.x on EC2", "Kafka 3.x cluster"):
            with self.subTest(raw=raw):
                out = run(raw)
                self.assertFalse(warns(out, "END_OF_LIFE_SYSTEM", raw) or warns(out, "END_OF_LIFE_SUSPECTED", raw), raw)

    def test_ie11_spellings(self):
        for raw in ("IE11 kiosks", "ie 11 only", "Internet Explorer 11 intranet"):
            with self.subTest(raw=raw):
                self.assertTrue(warns(run(raw, "internal_tool"), "END_OF_LIFE_SYSTEM", raw), raw)


class SelfHostedMicrosoft(unittest.TestCase):
    def test_versioned_sharepoint_is_not_the_microsoft_365_profile(self):
        desc = "Managers approve requests; approvals are sent by e-mail and Teams message."
        for typ in ("internal_tool", "saas_b2b", "web_app"):
            with self.subTest(typ=typ):
                out = run(["SharePoint Server 2013"], typ, desc)
                text = json.dumps(out["stack"]["supporting"]) + json.dumps(out["assumptions"])
                self.assertNotIn("Microsoft Graph", text)
                self.assertNotIn("Entra tenant", text)

    def test_exchange_on_prem_and_server_editions(self):
        for raw in ("Exchange 2010 mail server", "SharePoint Server (on-premises)", "Exchange Server 2016"):
            with self.subTest(raw=raw):
                text = json.dumps(run([raw], "internal_tool", "Approvals are sent by e-mail.")["stack"]["supporting"])
                self.assertNotIn("Microsoft Graph", text)

    def test_microsoft_365_keeps_its_profile(self):
        for raw in ("Microsoft 365", "SharePoint Online", "Office 365 tenant"):
            with self.subTest(raw=raw):
                out = run([raw], "internal_tool", "Managers approve requests; notices go by Outlook mail.")
                self.assertTrue(sup(out, "Microsoft Graph"), raw)


class SuspectedEndOfLife(unittest.TestCase):
    def test_old_release_markers_raise_a_warning(self):
        for raw, typ in (("Clipper stock control app", "internal_tool"), ("Windows NT 4 print server", "saas_b2b"),
                         ("Order system v1.x", "web_app"), ("PowerBuilder 6 client", "ecommerce"), ("Billing suite 2003", "internal_tool"),
                         ("Warehouse tool 9i schema", "web_app")):
            with self.subTest(raw=raw):
                out = run(raw, typ)
                w = warns(out, "END_OF_LIFE_SUSPECTED", raw)
                self.assertTrue(w, raw)
                self.assertEqual(w[0]["severity"], "warning")
                self.assertIn("no lifecycle data", w[0]["message"])

    def test_edition_years_after_a_product_word_raise_a_warning(self):
        for raw, typ in (("Dynamics NAV 2009 ledger", "saas_b2b"), ("Sage 2012 payroll", "internal_tool"), ("Stock control Suite 2005", "ecommerce")):
            with self.subTest(raw=raw):
                self.assertTrue(warns(run(raw, typ), "END_OF_LIFE_SUSPECTED", raw), raw)

    def test_a_contract_or_upgrade_year_is_not_a_release(self):
        for raw, typ in (("Salesforce org (2014 contract)", "saas_b2b"), ("SAP ECC 6.0 (EHP 7, upgraded 2015)", "internal_tool"),
                         ("Oracle EBS, licensed 2011", "ecommerce"), ("CRM go-live 2013", "web_app"), ("Intranet (built in 2010)", "internal_tool")):
            with self.subTest(raw=raw):
                self.assertFalse(warns(run(raw, typ), "END_OF_LIFE_SUSPECTED", raw), raw)

    def test_recent_or_dated_history_does_not_fire(self):
        for raw in ("PostgreSQL 17 (data since 2012)", "Salesforce org", "Legacy ERP in use since 2009", "Reports exported from 2008 onwards (SAP)",
                    "Okta tenant", "Stamp collection spreadsheet"):
            with self.subTest(raw=raw):
                self.assertFalse(warns(run(raw), "END_OF_LIFE_SUSPECTED", raw), raw)

    def test_recognised_lifecycle_entries_do_not_double_warn(self):
        out = run("Oracle Forms 6i billing system")
        self.assertFalse(warns(out, "END_OF_LIFE_SUSPECTED"))


class RetiringSystemIntegration(unittest.TestCase):
    def test_description_says_migrating_off_gives_read_once_then_retire(self):
        cases = (("phpBB 3.0 forum database (MySQL)", "web_app", "We are migrating off the old phpBB 3.0 install."),
                 ("Legacy MySQL 5.7 shop database", "ecommerce", "The old MySQL 5.7 database will be replaced by the new platform."),
                 ("phpBB 3.2 forum database (MySQL)", "saas_b2b", "Replace the phpBB 3.2 board."))
        for raw, typ, desc in cases:
            with self.subTest(raw=raw):
                out = run(raw, typ, desc)
                comp = [s for s in out["stack"]["supporting"] if s["choice"].startswith("Integration with existing")]
                self.assertTrue(comp, raw)
                self.assertIn("read its data once", comp[0]["justification"])
                self.assertNotIn("Leave it running as it is", comp[0]["justification"])

    def test_a_system_that_stays_keeps_the_live_integration_text(self):
        for raw, typ, desc in (("MySQL 5.7 shop database", "ecommerce", "Keep the MySQL 5.7 database; we only add a mobile app."),
                               ("phpBB 3.0 forum database (MySQL)", "web_app", "The phpBB 3.0 forum stays as it is and we read from it."),
                               ("Postgres 11 reporting database", "saas_b2b", "A small web application.")):
            with self.subTest(raw=raw):
                out = run(raw, typ, desc)
                for s in out["stack"]["supporting"]:
                    if s["choice"].startswith("Integration with existing"):
                        self.assertNotIn("read its data once", s["justification"])


if __name__ == "__main__":
    unittest.main()
