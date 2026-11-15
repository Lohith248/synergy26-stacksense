"""H1 (D19-h1, blind round 9): lifecycle rows with a named successor for legacy infrastructure, retired services never become integration
components, an 'older version of a known product' fallback, a per-row warning horizon (SAP ECC), peak capped at total users for sizing,
the time-series item gated on time-ordered wording, COBOL no longer an old-release marker.
Every rule is tested on several project types plus inputs where it must not fire. Inputs are inline."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402
from engine import context as cx  # noqa: E402
from engine.kb import TECH  # noqa: E402

BASE = {"scenario_id": "H1", "project": {"type": "web_app", "platforms": ["web"], "description": "A small web application."},
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


def eol_for(out, raw):
    return [w for w in out["warnings"] if w["code"] in ("END_OF_LIFE_SYSTEM", "END_OF_LIFE_SOON", "END_OF_LIFE_SUSPECTED") and raw in w["message"]]


def integrations(out):
    return [s for s in out["stack"]["supporting"] if "ntegration with existing" in s["choice"]]


class LifecycleRowsNameASuccessor(unittest.TestCase):
    def test_legacy_infrastructure_rows(self):
        cases = (("MySQL 5.5", "MySQL 8.4"), ("CentOS 6 servers", "AlmaLinux"), ("Nginx on Ubuntu 14.04 server", "Ubuntu LTS"),
                 ("VMware vSphere 7 cluster", "vSphere 8"), ("MongoDB 3.6", "supported"), ("Django 1.8 monolith", "Django LTS"),
                 ("Windows Server 2012 R2 virtual machine", "Windows Server 2025"))
        for typ, (raw, succ) in zip(("web_app", "fintech", "internal_tool", "healthtech", "ecommerce", "saas_b2b", "marketplace"), cases):
            with self.subTest(typ=typ, raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                w = eol_for(out, raw)
                self.assertEqual([x["code"] for x in w], ["END_OF_LIFE_SYSTEM"])
                self.assertIn("Upgrade or replacement options (knowledge-base suggestion)", w[0]["message"])
                self.assertIn(succ, w[0]["message"])

    def test_supported_versions_do_not_fire(self):
        for typ, raw in (("web_app", "MySQL 8.4"), ("saas_b2b", "Ubuntu 24.04 server"), ("ecommerce", "MongoDB 8.0"), ("fintech", "Django 5.2 app")):
            with self.subTest(raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                self.assertEqual(eol_for(out, raw), [])

    def test_unverified_dates_use_soft_wording(self):
        out = run(infrastructure__existing_systems=["CentOS 6 servers"])
        m = eol_for(out, "CentOS 6")[0]["message"]
        self.assertIn("has not re-checked the exact date", m)
        self.assertNotIn("2020-11-30", m)
        for sid, status in (("centos6-eol", "official-unverified"), ("vsphere6-eogs", "verified"),
                            ("vsphere7-eogs", "verified"), ("sap-bs7-maintenance", "verified")):
            from engine.kb import SOURCES
            self.assertEqual(SOURCES[sid]["status"], status)

    def test_every_new_row_cites_a_known_source(self):
        from engine.kb import SOURCES
        for lc in TECH["lifecycle"]:
            self.assertIn(lc["src"], SOURCES if lc["src"] != "statement" else {"statement": 1}, lc["pattern"])


class SapEccHorizon(unittest.TestCase):
    def test_future_end_of_mainstream_maintenance_is_flagged(self):
        for typ, raw in (("internal_tool", "SAP ECC 6.0 ERP"), ("ecommerce", "SAP ERP 6.0 EHP7"), ("saas_b2b", "SAP Business Suite 7")):
            with self.subTest(typ=typ):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                w = eol_for(out, raw)
                self.assertEqual([x["code"] for x in w], ["END_OF_LIFE_SOON"])
                self.assertIn("end of mainstream maintenance on 2027-12-31", w[0]["message"])
                self.assertIn("S/4HANA", w[0]["message"])

    def test_s4hana_and_other_sap_products_do_not_fire(self):
        for raw in ("SAP S/4HANA Cloud", "SAP SuccessFactors"):
            out = run(infrastructure__existing_systems=[raw])
            self.assertEqual(eol_for(out, raw), [])

    def test_a_row_without_a_horizon_keeps_90_days(self):
        out = run(infrastructure__existing_systems=["Node 24 service"])
        self.assertEqual(eol_for(out, "Node 24"), [])


class RetiredServicesAreNotIntegrated(unittest.TestCase):
    def test_retired_services_get_no_component_and_name_candidates(self):
        for typ, raw in (("iot", "Google Cloud IoT Core device registry"), ("social", "MongoDB Atlas Device Sync (Realm Sync)"),
                         ("web_app", "Realm Sync for the mobile app")):
            with self.subTest(raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                self.assertEqual([s for s in integrations(out) if "Realm" in s["choice"] or "Device Sync" in s["choice"] or "IoT Core" in s["choice"]], [])
                w = eol_for(out, raw)
                self.assertEqual(len(w), 1)
                self.assertIn("discontinued service", w[0]["message"])
                self.assertIn("not a vendor recommendation", w[0]["message"])
                self.assertTrue(any("no integration component is added" in a for a in out["assumptions"]))

    def test_live_services_with_similar_names_are_still_integrated_or_unflagged(self):
        for raw in ("AWS IoT Core", "MongoDB Atlas cluster", "Keycloak realm"):
            out = run(infrastructure__existing_systems=[raw])
            self.assertEqual(eol_for(out, raw), [], raw)
        out = run(infrastructure__existing_systems=["MongoDB 6.0 replica set"])
        self.assertTrue(integrations(out))


class OlderVersionOfAKnownProduct(unittest.TestCase):
    def test_versions_below_the_oldest_known_line_are_suspected(self):
        # q6: MySQL 4.1, CentOS 5, Ubuntu 12.04, PostgreSQL 9.6, PHP 4, vSphere 5.5 and Windows Server 2003 now have dated lifecycle rows
        # (END_OF_LIFE_SYSTEM, tests/test_q6.py); the fallback is exercised with releases older than any row
        cases = (("web_app", "MySQL 3.22 database", "MySQL 3.22"), ("fintech", "CentOS 4 box", "CentOS Linux 4"),
                 ("saas_b2b", "PostgreSQL 6.0", "PostgreSQL 6.0"), ("ecommerce", "PHP 3 scripts", "PHP 3"), ("healthtech", "vSphere 4.1 hosts", "VMware vSphere 4.1"))
        for typ, raw, fam in cases:
            with self.subTest(raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                w = eol_for(out, raw)
                self.assertEqual([x["code"] for x in w], ["END_OF_LIFE_SUSPECTED"])
                self.assertIn("an older version of a known product", w[0]["message"])
                self.assertIn(fam, w[0]["message"])
                self.assertIn("not confirmed in the knowledge base", w[0]["message"])

    def test_known_rows_and_current_versions_do_not_use_the_fallback(self):
        for raw in ("MySQL 5.5", "CentOS 6", "Ubuntu 22.04", "PostgreSQL 16", "PHP 8.3", "vSphere 8", "Windows Server 2022", "MongoDB 7.0"):
            with self.subTest(raw=raw):
                out = run(infrastructure__existing_systems=[raw])
                self.assertFalse([w for w in out["warnings"] if w["code"] == "END_OF_LIFE_SUSPECTED" and "older version of a known product" in w["message"]])

    def test_description_text_is_not_scanned(self):
        out = run(project__description="Runs on a node 3 cluster; our python 3 team knows mysql 4 users.", infrastructure__existing_systems=["Salesforce"])
        self.assertFalse(warns(out, "END_OF_LIFE_SUSPECTED"))


class CountsAreNotVersions(unittest.TestCase):
    def test_a_number_before_a_count_noun_does_not_fire(self):
        for typ, raw in (("web_app", "Postgres 2 replicas"), ("fintech", "MySQL 3 replicas"), ("saas_b2b", "MongoDB 3 node replica set"),
                         ("ecommerce", "PHP 2 web servers"), ("healthtech", "vSphere 3 hosts"), ("internal_tool", "ESXi 2 hosts"),
                         ("marketplace", "CentOS 5 boxes"), ("web_app", "MySQL 4 read replicas")):
            with self.subTest(raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                self.assertFalse([w for w in out["warnings"] if w["code"] == "END_OF_LIFE_SUSPECTED" and "older version of a known product" in w["message"]])

    def test_a_real_old_version_still_fires(self):
        out = run(infrastructure__existing_systems=["Postgres 9.6 primary"])
        self.assertTrue(eol_for(out, "Postgres 9.6"))


class OtherReviewFixes(unittest.TestCase):
    def test_mysql_57_date_and_django_wording(self):
        out = run(infrastructure__existing_systems=["MySQL 5.7"])
        self.assertIn("2023-10-25", eol_for(out, "MySQL 5.7")[0]["message"])
        out = run(project__type="saas_b2b", infrastructure__existing_systems=["Django 1.8 monolith"])
        self.assertIn("ended by 2020-04-01 at the latest", eol_for(out, "Django 1.8")[0]["message"])

    def test_the_ondevice_realm_database_is_not_retired(self):
        for raw in ("Realm database on the phones", "Realm DB offline cache"):
            out = run(infrastructure__existing_systems=[raw])
            self.assertFalse([w for w in eol_for(out, raw) if "discontinued" in w["message"]])

    def test_vsphere6_is_verified_and_hard_dated(self):
        out = run(infrastructure__existing_systems=["vSphere 6.7 cluster"])
        self.assertIn("2022-10-15", eol_for(out, "vSphere 6.7")[0]["message"])


class CobolIsNotAnOldReleaseMarker(unittest.TestCase):
    def test_cobol_alone_is_no_eol_marker(self):
        for typ, raw in (("fintech", "IBM z/OS mainframe running COBOL batch"), ("internal_tool", "COBOL claims engine"), ("saas_b2b", "COBOL back office")):
            with self.subTest(raw=raw):
                out = run(project__type=typ, infrastructure__existing_systems=[raw])
                self.assertEqual(eol_for(out, raw), [])

    def test_other_markers_still_fire(self):
        out = run(infrastructure__existing_systems=["Lotus Notes mail archive"])
        self.assertTrue(eol_for(out, "Lotus Notes"))


class PeakCapAtTotalUsers(unittest.TestCase):
    def test_peak_above_users_is_capped_for_sizing(self):
        for typ in ("web_app", "ecommerce", "saas_b2b"):
            with self.subTest(typ=typ):
                capped = run(project__type=typ, scale__users_at_launch=2000, scale__users_12_months=5000, scale__peak_concurrent_users=90000)
                honest = run(project__type=typ, scale__users_at_launch=2000, scale__users_12_months=5000, scale__peak_concurrent_users=500)  # 10% of 5,000 users, the absent-peak rule
                self.assertEqual(capped["estimated_monthly_cost_usd"]["max"], honest["estimated_monthly_cost_usd"]["max"])
                self.assertEqual(capped["stack"]["hosting"]["choice"], honest["stack"]["hosting"]["choice"])
                w = warns(capped, "PEAK_EXCEEDS_USERS")
                self.assertEqual(len(w), 1)
                self.assertIn("Sizing uses ~500 concurrent users instead", w[0]["message"])
                self.assertTrue(any("is not used for sizing: ~500 concurrent users" in a for a in capped["assumptions"]))

    def test_a_peak_given_as_a_rate_is_not_capped_or_warned(self):
        out = run(project__type="api_platform", project__platforms=["api_only"], scale__users_at_launch=300, scale__users_12_months=3000, scale__peak_concurrent_users=5000,
                  project__description="Payment API. About 5,000 transactions per second at peak.")
        self.assertFalse(warns(out, "PEAK_EXCEEDS_USERS"))
        self.assertTrue(any("a request rate from the description" in a for a in out["assumptions"]))
        self.assertFalse(any("people, not requests per second" in a for a in out["assumptions"]))

    def test_rate_wording_variants(self):
        for desc in ("Handles 2,000 req/s at peak.", "Peaks at 800 txns/sec.", "About 1,500 calls/s.", "5k ops/s sustained.", "Roughly 3000 tps."):
            with self.subTest(desc=desc):
                out = run(project__type="api_platform", project__platforms=["api_only"], scale__users_at_launch=100, scale__users_12_months=900,
                          scale__peak_concurrent_users=3000, project__description=desc)
                self.assertFalse(warns(out, "PEAK_EXCEEDS_USERS"))

    def test_a_peak_below_users_is_untouched(self):
        out = run(scale__users_12_months=50000, scale__peak_concurrent_users=900)
        self.assertFalse(warns(out, "PEAK_EXCEEDS_USERS"))
        self.assertFalse(any("is not used for sizing" in a for a in out["assumptions"]))


class TimeSeriesNeedsMoreThanWriteHeavy(unittest.TestCase):
    def ts(self, out):
        return [s for s in out["stack"]["supporting"] if s["choice"].startswith("Time-series storage")]

    def test_write_heavy_alone_adds_nothing(self):
        for typ, desc in (("social", "A photo-sharing community app."), ("realtime_collab", "Team chat for schools."), ("marketplace", "A classifieds marketplace.")):
            with self.subTest(typ=typ):
                out = run(project__type=typ, project__description=desc, scale__workload="write_heavy", scale__data_volume_gb_12_months=2000,
                          scale__users_12_months=40000, scale__users_at_launch=5000)
                self.assertEqual(self.ts(out), [])

    def test_time_ordered_wording_still_adds_it(self):
        for typ, desc in (("data_analytics", "Collects application metrics from many services."), ("fintech", "Keeps an append-only ledger of transfers."),
                          ("internal_tool", "Stores audit logs and access logs for every action.")):
            with self.subTest(typ=typ):
                out = run(project__type=typ, project__description=desc, scale__workload="write_heavy", scale__data_volume_gb_12_months=2000,
                          scale__users_12_months=40000, scale__users_at_launch=5000)
                self.assertEqual(len(self.ts(out)), 1)

    def test_metrics_readings_and_trend_wording_adds_it(self):
        for typ, desc in (("saas_b2b", "Observability SaaS that stores application performance data."),
                          ("internal_tool", "Collects server CPU and memory stats from every host and graphs them over time."),
                          ("healthtech", "Wearable app storing heart-rate readings for each user."),
                          ("other", "PLCs push temperature and pressure values every second for trend charts.")):
            with self.subTest(typ=typ):
                out = run(project__type=typ, project__description=desc, scale__workload="write_heavy", scale__data_volume_gb_12_months=2000,
                          scale__users_12_months=40000, scale__users_at_launch=5000)
                self.assertEqual(len(self.ts(out)), 1)

    def test_negated_wording_does_not_add_it(self):
        out = run(project__type="social", project__description="A photo community; there are no metrics or logs to keep.", scale__workload="write_heavy",
                  scale__data_volume_gb_12_months=2000, scale__users_12_months=40000, scale__users_at_launch=5000)
        self.assertEqual(self.ts(out), [])

    def test_iot_is_unchanged(self):
        out = run(project__type="iot", project__description="Sensors report every minute.", scale__workload="write_heavy", scale__data_volume_gb_12_months=100)
        self.assertEqual(len(self.ts(out)), 1)


if __name__ == "__main__":
    unittest.main()
