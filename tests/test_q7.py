"""q7: existing systems the project replaces are migrated, not integrated for good (item 2); existing systems the description
forbids changing are read only (item 3). Synthetic inputs only."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.run import evaluate  # noqa: E402
from test_round9 import BASE  # noqa: E402

MIGRATE = "keep it read-only during the transition, then cut over with a rollback path"


def run(typ, desc, existing, deployment="managed_cloud", platforms=("web",)):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, description=desc, platforms=list(platforms))
    s["infrastructure"].update(existing_systems=list(existing), deployment_model=deployment)
    if deployment == "on_premise":
        s["infrastructure"]["cloud_preference"] = "none"
    out = evaluate(s, counterfactuals=False)
    assert out["stack"], out["warnings"]
    return out


def line(out, word):
    hits = [c for c in out["stack"]["supporting"] if word.lower() in c["choice"].lower()]
    return hits[0] if hits else None


def migrated(out, word):
    """The system is migrated: its component says so, or (no knowledge-base pattern, so no component) its end-of-life warning does."""
    c = line(out, word)
    if c:
        return MIGRATE in c["justification"]
    eol = [w for w in out["warnings"] if w["code"] == "END_OF_LIFE_SYSTEM" and word in w["message"]]
    return bool(eol) and all("retires or replaces it" in w["message"] for w in eol)


def text(out):
    import json
    return json.dumps(out, ensure_ascii=False)


class ReplacedSystemIsMigrated(unittest.TestCase):
    def test_project_rebuilds_the_system(self):
        cases = (("web_app", "One portal for 12 clinics: patient booking, billing, prescriptions and lab reports. Booking currently "
                  "runs on a Classic ASP site an agency built in 2009.", ["Classic ASP booking website (2009)"], "Classic ASP"),
                 ("internal_tool", "Leave, payroll and attendance for 300 factory staff. Attendance is today kept in a Visual Basic 6 "
                  "application on one PC.", ["Visual Basic 6 attendance application"], "Visual Basic"),
                 ("saas_b2b", "A subscription platform for 30 gyms with memberships, class schedules and invoices. Memberships currently "
                  "live in a PHP 5.6 membership portal.", ["PHP 5.6 membership portal (custom code)"], "PHP 5.6"))
        for typ, desc, ex, word in cases:
            out = run(typ, desc, ex)
            self.assertTrue(migrated(out, word), typ)
            c = line(out, word)
            if c:
                self.assertIn("takes over what it does", c["justification"], typ)
            self.assertNotIn("outside MVP scope", text(out), typ)
            self.assertNotIn("until then it is integrated as it is", text(out), typ)

    def test_modernised_api_is_migrated(self):
        cases = (("ecommerce", "Online shop for handmade rugs. The current storefront runs on a Python 2.7 Flask API that we want "
                  "to modernise.", ["Python 2.7 Flask API"]),
                 ("iot", "Ovens in 40 bakeries report temperatures. Its Python 2.7 Flask API is being rewritten.", ["Python 2.7 Flask API"]),
                 ("web_app", "Booking site for a ferry operator. The Node.js 8 API is being decommissioned.", ["Node.js 8 booking API"]))
        for typ, desc, ex in cases:
            out = run(typ, desc, ex)
            c = line(out, "API")
            self.assertIsNotNone(c, typ)
            self.assertIn(MIGRATE, c["justification"], typ)
            self.assertNotIn("Replacing it", text(out), typ)
            eol = [w for w in out["warnings"] if w["code"] == "END_OF_LIFE_SYSTEM"]
            self.assertTrue(eol and "retires or replaces it" in eol[0]["message"], typ)

    def test_retired_devices_get_no_adapter(self):
        out = run("web_app", "Couriers scan parcels with new Android phones. The old Windows CE 6.0 handhelds are being phased out.",
                  ["Windows CE 6.0 handheld terminals"], platforms=("android",))
        self.assertIsNone(line(out, "Windows CE"))
        self.assertNotIn("adapter for Windows CE", text(out))

    def test_kept_or_integrated_systems_are_not_migrated(self):
        cases = (("web_app", "Distributor ordering portal. We will not replace Tally; invoices currently go to Tally.", ["Tally ERP 9"], "Tally"),
                 ("web_app", "Patient booking and billing for clinics. Booking currently runs on the Classic ASP booking website, "
                  "which stays; the new portal syncs with it.", ["Classic ASP booking website (2009)"], "Classic ASP"),
                 ("internal_tool", "Attendance reports for 300 staff. Attendance is currently recorded in a Visual Basic 6 attendance "
                  "application; the reports read from it.", ["Visual Basic 6 attendance application"], "Visual Basic"),
                 ("web_app", "Ticket desk for a city library. We also have an old PHP 5.6 events website.", ["PHP 5.6 events website"], "PHP 5.6"))
        for typ, desc, ex, word in cases:
            out = run(typ, desc, ex)
            self.assertFalse(migrated(out, word), (typ, word))
            self.assertNotIn("takes over what it does", text(out), (typ, word))


READ_ONLY = "so access is read-only"


def db_lines(out):
    return [out["stack"]["database"]] + [c for c in out["stack"]["supporting"] if "existing" in c["choice"].lower()]


class UntouchableSystemIsReadOnly(unittest.TestCase):
    def test_no_touch_wording_makes_the_integration_read_only(self):
        cases = (("data_analytics", "Loan dashboards for a credit society. Core jobs write to Db2 every night; we need daily dashboards "
                  "without touching the core.", ["IBM Db2 for z/OS"], "on_premise", "Db2"),
                 ("internal_tool", "Claims reports for an insurer. The Oracle 19c policy database must not be modified.",
                  ["Oracle 19c policy database"], "managed_cloud", "Oracle"),
                 ("web_app", "A parts catalogue for dealers, read from the existing SQL Server 2019 database through a read-only replica.",
                  ["SQL Server 2019 parts database"], "managed_cloud", "SQL Server"),
                 ("healthtech", "Appointment reminders for a hospital. The hospital's MySQL 8.0 patient database is read-only for us: "
                  "no writes to it.", ["MySQL 8.0 patient database"], "managed_cloud", "MySQL"))
        for typ, desc, ex, dep, word in cases:
            out = run(typ, desc, ex, deployment=dep)
            c = line(out, word)
            self.assertIsNotNone(c, typ)
            self.assertIn(READ_ONLY, c["justification"], typ)
            self.assertIn("never writes to it", c["justification"], typ)
            for x in db_lines(out):
                self.assertNotIn("must read and write", x["justification"], typ)
                self.assertNotIn("reads and writes the existing", x["justification"], typ)

    def test_kept_database_that_must_not_change_is_read_in_place(self):
        out = run("internal_tool", "Shift planning for a hospital. Keep the existing PostgreSQL 15 database; it must not be modified.",
                  ["PostgreSQL 15 HR database"])
        just = out["stack"]["database"]["justification"]
        self.assertIn("reused", out["stack"]["database"]["choice"])
        self.assertIn("never writes to it", just)
        self.assertNotIn("reads and writes", just)

    def test_must_not_fire(self):
        cases = (("internal_tool", "Claims reports for an insurer from the Oracle 19c database; reports must not slow the core.",
                  ["Oracle 19c database"], "Oracle"),
                 ("web_app", "Admissions currently run on a PHP 5.6 site that nobody dares to touch; the new portal reads from it.",
                  ["PHP 5.6 admissions website"], "PHP"),
                 ("ecommerce", "Order history must read and write the existing MySQL 8.0 database.", ["MySQL 8.0 database"], "MySQL"))
        for typ, desc, ex, word in cases:
            out = run(typ, desc, ex)
            self.assertNotIn(READ_ONLY, text(out), typ)


def run_scale(typ, desc, existing, workload="read_heavy", gb=400):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, description=desc)
    s["infrastructure"]["existing_systems"] = list(existing)
    s["scale"].update(workload=workload, data_volume_gb_12_months=gb)
    out = evaluate(s, counterfactuals=False)
    assert out["stack"], out["warnings"]
    return out


def unrecognised(out, raw):
    return [w for w in out["warnings"] if w["code"] == "EXISTING_SYSTEM_UNRECOGNISED" and raw in w["message"]]


class WellKnownProductsRecognised(unittest.TestCase):
    def test_warehouses_are_recognised(self):
        cases = (("data_analytics", "Weekly sales dashboards for a retail chain.", "Snowflake"),
                 ("ecommerce", "Online store for spare parts; marketing analytics run elsewhere.", "Google BigQuery"),
                 ("fintech", "Loan servicing portal for a lender.", "Amazon Redshift cluster"),
                 ("saas_b2b", "Fleet maintenance planning for logistics firms.", "Databricks lakehouse"))
        for typ, desc, raw in cases:
            out = run_scale(typ, desc, [raw], workload="balanced", gb=50)
            c = line(out, raw)
            self.assertIsNotNone(c, raw)
            self.assertIn("existing data warehouse / lakehouse", c["justification"], raw)
            self.assertFalse(unrecognised(out, raw), raw)

    def test_game_sdk_and_hl7_engine_are_recognised(self):
        cases = (("gaming", "A co-op PC game with leaderboards, sold on Steam.", "Steamworks", "platform SDK for games sold on Steam"),
                 ("healthtech", "Lab results portal for a hospital group.", "Mirth Connect", "HL7 integration engine"),
                 ("internal_tool", "Ward bed board for nurses.", "NextGen Connect integration engine", "HL7 integration engine"),
                 ("web_app", "Referral tracking between clinics.", "Mirth Connect 4.4", "HL7 integration engine"))
        for typ, desc, raw, says in cases:
            out = run_scale(typ, desc, [raw], workload="balanced", gb=20)
            c = line(out, raw)
            self.assertIsNotNone(c, raw)
            self.assertIn(says, c["justification"], raw)
            self.assertFalse(unrecognised(out, raw), raw)

    def test_existing_warehouse_is_reused_not_duplicated(self):
        cases = (("data_analytics", "Weekly sales dashboards for a retail chain.", "Snowflake"),
                 ("data_analytics", "Claims analytics for an insurer.", "Amazon Redshift"),
                 ("ecommerce", "Online store with sales analytics dashboards for the buying team.", "Google BigQuery"))
        for typ, desc, raw in cases:
            out = run_scale(typ, desc, [raw])
            self.assertFalse([c for c in out["stack"]["supporting"] if c["choice"].startswith("Analytics warehouse")], raw)
            self.assertTrue(any(w["code"] == "SERVICE_NOT_ADDED" and f"existing '{raw}' is reused" in w["message"] for w in out["warnings"]), raw)
            bi = [c for c in out["stack"]["supporting"] if c["choice"].startswith("BI dashboards")]
            self.assertTrue(bi and f"query the existing '{raw}' warehouse" in bi[0]["justification"], raw)

    def test_must_not_fire(self):
        # no warehouse entry: the new warehouse is still added; a 'snowflake schema' entry is not Snowflake; a retired warehouse is replaced
        out = run_scale("data_analytics", "Weekly sales dashboards; a snowflake schema in the reports.", [])
        self.assertTrue([c for c in out["stack"]["supporting"] if c["choice"].startswith("Analytics warehouse")])
        out = run_scale("data_analytics", "Weekly sales dashboards.", ["SQL Server snowflake schema reporting database"])
        self.assertNotIn("existing data warehouse / lakehouse", text(out))
        out = run_scale("data_analytics", "Weekly sales dashboards. Redshift is being decommissioned.", ["Amazon Redshift"])
        self.assertTrue([c for c in out["stack"]["supporting"] if c["choice"].startswith("Analytics warehouse")])
        self.assertNotIn("is reused as the analytics store", text(out))


class ReviewFixes(unittest.TestCase):
    """Review of q7 on 15 Nov: a warehouse outside the residency area is not the project's analytics store; the end-of-life text for a
    retired system makes no claim about data it may not hold."""

    @staticmethod
    def res_run(typ, residency, existing, compliance=()):
        s = copy.deepcopy(BASE)
        s["project"].update(type=typ, description="Operational records with weekly reporting for managers.")
        s["infrastructure"].update(existing_systems=[existing], data_residency=residency)
        s["compliance"] = list(compliance)
        out = evaluate(s, counterfactuals=False)
        assert out["stack"], out["warnings"]
        return out

    def test_warehouse_outside_the_residency_area(self):
        for typ, res, raw, comp in (("fintech", "india", "Snowflake account in AWS us-east-1", ["rbi_localisation"]),
                                    ("healthtech", "eu", "BigQuery datasets in us-central1", ["gdpr"]),
                                    ("saas_b2b", "india", "Amazon Redshift cluster in us-west-2", ["dpdp"])):
            out = self.res_run(typ, res, raw, comp)
            j = line(out, raw.split(" ")[0] if not raw.startswith("Amazon") else "Redshift")["justification"]
            self.assertTrue(j.startswith("Residency limits this integration"), (raw, j[:120]))
            self.assertIn("not this project's analytics store", j, raw)
            self.assertNotIn("treat it as this project's analytics store", j, raw)
            self.assertIn("RESIDENCY_TRANSFER_OUT", [w["code"] for w in out["warnings"]], raw)

    def test_warehouse_abroad_is_not_reused_as_the_analytics_store(self):
        s = copy.deepcopy(BASE)
        s["project"].update(type="data_analytics", description="Dashboards and ad-hoc SQL for analysts over transaction data.")
        s["scale"]["data_volume_gb_12_months"] = 4000
        s["infrastructure"].update(existing_systems=["Snowflake account in AWS us-east-1"], data_residency="india")
        s["compliance"] = ["rbi_localisation"]
        out = evaluate(s, counterfactuals=False)
        self.assertNotIn("is reused as the analytics store", text(out))
        self.assertNotIn("Dashboards query the existing", text(out))
        self.assertIn("RESIDENCY_TRANSFER_OUT", [w["code"] for w in out["warnings"]])
        # the same warehouse in the residency area is reused as before
        s["infrastructure"]["existing_systems"] = ["Snowflake account in AWS ap-south-1 (Mumbai)"]
        self.assertIn("is reused as the analytics store", text(evaluate(s, counterfactuals=False)))

    def test_warehouse_inside_the_area_or_without_residency_keeps_its_text(self):
        for res, raw in (("none", "Snowflake account in AWS us-east-1"), ("india", "Snowflake account in AWS ap-south-1 (Mumbai)"),
                         ("us", "BigQuery datasets in us-central1")):
            out = self.res_run("saas_b2b", res, raw)
            j = line(out, raw.split(" ")[0])["justification"]
            self.assertIn("treat it as this project's analytics store", j, (res, raw))
            self.assertNotIn("Residency limits this integration", j, (res, raw))

    def test_retired_end_of_life_system_wording(self):
        for typ, raw in (("internal_tool", "Windows CE 6.0 handheld scanners (being retired)"),
                         ("ecommerce", "Magento 1.9 storefront (to be retired)"),
                         ("web_app", "Adobe Flash admin console (to be replaced)")):
            out = run(typ, "A new system for the operations team.", [raw])
            w = [x["message"] for x in out["warnings"] if x["code"] == "END_OF_LIFE_SYSTEM"]
            self.assertTrue(w, raw)
            self.assertIn("move what still depends on it to its replacement", w[0], raw)
            self.assertNotIn("migrate what it holds", w[0], raw)
            self.assertNotIn("vendor, the input", w[0], raw)

    def test_cloud_warehouse_on_a_self_hosted_stack_is_flagged(self):
        for typ, raw, dep in (("data_analytics", "Snowflake account", "on_premise"),
                              ("internal_tool", "Google BigQuery datasets", "on_premise"),
                              ("healthtech", "Amazon Redshift cluster", "air_gapped")):
            out = run(typ, "Reports for managers.", [raw], deployment=dep)
            w = [x for x in out["warnings"] if x["code"] == "EXTERNAL_EXISTING_SERVICE" and raw in x["message"]]
            self.assertTrue(w, (raw, dep))
            self.assertEqual(w[0]["severity"], "critical")
            self.assertIn("no route to the internet" if dep == "air_gapped" else "data leaves your premises", w[0]["message"])

    def test_cloud_warehouse_on_cloud_or_retired_is_not_flagged(self):
        for raw, dep in (("Snowflake account", "managed_cloud"), ("Snowflake account (being retired)", "on_premise"),
                         ("Google BigQuery datasets", "self_hosted_cloud_vm")):
            out = run("data_analytics", "Reports for managers.", [raw], deployment=dep)
            self.assertFalse([x for x in out["warnings"] if x["code"] == "EXTERNAL_EXISTING_SERVICE" and "warehouse" in x["message"]], (raw, dep))

    def test_kept_end_of_life_system_keeps_the_isolation_wording(self):
        out = run("internal_tool", "A new system for the operations team.", ["Windows CE 6.0 handheld scanners"])
        w = [x["message"] for x in out["warnings"] if x["code"] == "END_OF_LIFE_SYSTEM"]
        self.assertIn("keep it behind an isolated interface", w[0])
        self.assertNotIn("the input retires or replaces it", w[0])


if __name__ == "__main__":
    unittest.main()
