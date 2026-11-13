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


if __name__ == "__main__":
    unittest.main()
