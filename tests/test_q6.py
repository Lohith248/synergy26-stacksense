"""q6: deprecated-technology coverage. Lifecycle rows built from an endoflife.date snapshot (aggregator, cited as such) and from
vendor lifecycle pages read on 15 Nov 2026. Positive: existing-system strings on many products and spellings, across project types,
produce END_OF_LIFE_SYSTEM. Must-not-fire: current versions, look-alikes, quantities and products named without a version.
Sweep: nothing the knowledge base can recommend matches a past-end-of-life row. Inputs are inline, written for this file."""
import copy
import glob
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402
from engine import context as cx  # noqa: E402
from engine.kb import TECH, SOURCES, AS_OF  # noqa: E402

BASE = {"scenario_id": "Q6", "project": {"type": "web_app", "platforms": ["web"], "description": "A small web application."},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "intermediate", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 3000}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password"}}

TYPES = ("web_app", "internal_tool", "saas_b2b", "ecommerce", "data_analytics", "iot")


def run(systems, typ="web_app"):
    s = copy.deepcopy(BASE)
    s["project"]["type"] = typ
    s["infrastructure"]["existing_systems"] = list(systems)
    return evaluate(s, counterfactuals=False)


def eol(out, raw):
    return [w for w in out["warnings"] if w["code"] == "END_OF_LIFE_SYSTEM" and f"'{raw}'" in w["message"]]


def life_names(raw):
    return [r["name"] for r in cx.lifecycle_hits(cx.lifecycle_text(f" {raw.lower()} "))]


POSITIVE = ("Node 12", "Node.js 12 order API", "NodeJS v12", "Nuxt 2 storefront", "Apache Kafka 3.6 cluster", "Kafka 3.6",
            "Keycloak 24", "Hadoop 2.7", "Postgres 9.6", "Drupal 7 site", "Magento 1.9 store", "Ubuntu 19.10 box", "K8s 1.24",
            "Kubernetes 1.24", "Python 3.5 scripts", "Go 1.16 service", "MariaDB 10.3", "Redis 5", "Laravel 5.8", "Spring Boot 1.5",
            "Next.js 12 storefront", "React Native 0.63 app", "Bootstrap 3 theme", "RabbitMQ 3.8", "Spark 2.4 jobs", "Airflow 1.10",
            "nginx 1.18", "JBoss EAP 6", "Couchbase Server 6.5", "Debian 6 servers", "SLES 12 SP3", "Exchange 2010", "WordPress 4.6", "Moodle 3.9",
            "Joomla 3", "Grafana 7", "Android 9 handhelds", "macOS 10.13 workstations", "ESXi 5.5 hosts", "Erlang/OTP 21",
            "Windows XP POS terminals", "Windows CE 6.0 handheld scanners", "MS Access 2010 database", "Atom editor plugins",
            "Windows Server 2003", "CentOS 5")


class Positive(unittest.TestCase):
    def test_lifecycle_rows_match_common_spellings(self):
        missing = [raw for raw in POSITIVE if not life_names(raw)]
        self.assertEqual(missing, [])

    def test_end_of_life_warning_on_several_project_types(self):
        for i, raw in enumerate(POSITIVE[:30]):
            typ = TYPES[i % len(TYPES)]
            with self.subTest(raw=raw, typ=typ):
                out = run([raw], typ)
                self.assertEqual(len(eol(out, raw)), 1, [w["code"] for w in out["warnings"]])

    def test_aggregator_rows_say_where_the_date_comes_from(self):
        msg = eol(run(["Kafka 3.6"], "data_analytics"), "Kafka 3.6")[0]["message"]
        self.assertIn("endoflife.date, a community-maintained aggregator", msg)
        self.assertIn("not the vendor's own page", msg)
        for lc in TECH["lifecycle"]:
            if lc["src"].startswith("eoldate-"):
                self.assertIn("endoflife.date", lc["name"], lc["pattern"])
                self.assertEqual(SOURCES[lc["src"]]["status"], "source-reported", lc["src"])
                self.assertTrue(SOURCES[lc["src"]]["url"].startswith("https://endoflife.date/"), lc["src"])

    def test_vendor_rows_cite_a_verified_page(self):
        for raw, sid in (("Windows XP POS terminals", "ms-windows-xp-lifecycle"), ("Windows CE 6.0 handheld scanners", "ms-windows-ce6-lifecycle"),
                         ("MS Access 2010 database", "ms-access-2010-lifecycle"), ("Atom editor plugins", "github-atom-sunset")):
            rows = cx.lifecycle_hits(cx.lifecycle_text(f" {raw.lower()} "))
            self.assertEqual(rows[0]["src"], sid, raw)
            self.assertEqual(SOURCES[sid]["status"], "verified")
            self.assertNotIn("endoflife.date", rows[0]["name"])

    def test_paid_extended_support_is_not_called_end_of_life(self):
        for raw, typ in (("RHEL 7 file servers", "internal_tool"), ("IBM MQ 9.1", "data_analytics"), ("JDK 8 batch jobs", "saas_b2b")):
            out = run([raw], typ)
            self.assertEqual(eol(out, raw), [], raw)
            info = [w for w in out["warnings"] if w["code"] == "EXISTING_SYSTEM_EXTENDED_SUPPORT" and raw in w["message"]]
            self.assertEqual(len(info), 1, raw)

    def test_retired_editor_gets_no_integration_component(self):
        out = run(["Atom editor plugins"], "internal_tool")
        self.assertIn("discontinued service", eol(out, "Atom editor plugins")[0]["message"])


NEGATIVE = ("Node.js 24", "Java 25", "Python 3.13", "PostgreSQL 17", "Kafka 4.1", "Kafka 4.x", "Keycloak 26", "Ubuntu 24.04",
            "Windows Server 2025", ".NET 10", "node 120 sensors", "java 8-week course", "redis", "kafka", "keycloak", "hadoop",
            "Angular 21", "Apache 2.0 licensed library", "Redis 7.4", "MySQL 8.4", "Go 1.26", "Kubernetes 1.35", "Debian 13", "RHEL 9",
            "Python 3.12", "PHP 8.4", "Laravel 12", "node 12-week rollout", "Django 5.2", "Grafana 12", "GitLab 19", "macOS 15",
            "iOS 18", "Cisco IOS 12 routers", "Bootstrap 5", "Next.js 15", "Windows 11", "Windows 10 IoT Enterprise LTSC", "atom feeds",
            "Windows Server 2003 R2")


class MustNotFire(unittest.TestCase):
    def test_current_versions_and_look_alikes_match_no_new_row(self):
        fired = {}
        for raw in NEGATIVE:
            rows = [r for r in cx.lifecycle_hits(cx.lifecycle_text(f" {raw.lower()} ")) if r["src"].startswith(("eoldate-", "ms-", "github-atom"))]
            if rows:
                fired[raw] = [r["name"] for r in rows]
        self.assertEqual(fired, {})

    def test_no_end_of_life_warning(self):
        for raw in ("Node.js 24", "Keycloak 26", "kafka", "java 8-week course", "Kubernetes 1.35", "Windows 11"):
            with self.subTest(raw=raw):
                self.assertEqual(eol(run([raw], "saas_b2b"), raw), [])

    def test_existing_hand_made_row_still_wins(self):
        rows = cx.lifecycle_hits(cx.lifecycle_text(" windows server 2003 r2 "))
        self.assertEqual([r["pattern"] for r in rows], ["windows server 2003 r2"])


def recommendable():
    names = set()
    for g in ("hosting", "frontend_web", "frontend_mobile", "backend", "database"):
        for item in TECH[g]:
            names.add(item["name"])
    for p in glob.glob(os.path.join(ROOT, "outputs", "P*_output.json")):
        with open(p, encoding="utf-8") as f:
            out = json.load(f)

        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in ("choice", "name") and isinstance(v, str):
                        names.add(v)
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(out.get("recommendation", out))
    return names


class Sweep(unittest.TestCase):
    def test_nothing_the_engine_recommends_is_past_end_of_life(self):
        bad = {}
        for n in sorted(recommendable()):
            rows = [r["name"] for r in cx.lifecycle_hits(cx.lifecycle_text(f" {n.lower()} ")) if r["eol"] <= AS_OF]
            if rows:
                bad[n] = rows
        self.assertEqual(bad, {})


if __name__ == "__main__":
    unittest.main()
