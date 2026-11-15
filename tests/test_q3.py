"""q3: no false statement, no silent constraint break (synthetic inputs only; no holdout scenario is copied)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_round9 import run, sup, codes  # noqa: E402


def nocode(test, kw, code="RESIDENCY_TRANSFER_OUT"):
    out = run(**kw)
    test.assertNotEqual(out["status"], "invalid_input", out.get("validation_errors"))
    test.assertNotIn(code, codes(out), kw.get("project.description"))
    return out


def warn(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


CLINIC_EU = {"project.type": "healthtech", "infrastructure.data_residency": "eu", "compliance": ["gdpr"],
             "project.description": "Physiotherapy clinic booking and treatment notes. Nightly backups of patient records are copied "
                                    "to our disaster-recovery bucket in us-east-1."}
SHOP_IN = {"project.type": "ecommerce", "infrastructure.data_residency": "india",
           "project.description": "Grocery delivery storefront. Order events are replicated to the analytics team's dataset in "
                                  "asia-southeast1 for weekly reporting."}
FLEET_US = {"project.type": "iot", "infrastructure.data_residency": "us",
            "infrastructure.existing_systems": ["Tableau Server hosted in Frankfurt"],
            "project.description": "Cold-chain truck monitoring. Shipment temperature records are synced to Tableau Server for dashboards."}
LEDGER_RBI = {"project.type": "fintech", "infrastructure.data_residency": "none", "compliance": ["rbi_localisation"],
              "requirements.payments": True,
              "project.description": "Merchant loyalty points and payouts. Payment records are mirrored to the group risk cluster in Virginia."}


class TransferOutOfResidency(unittest.TestCase):
    """Item 1: a stated transfer of regulated data out of the residency area is a critical warning."""

    def assertFires(self, out, *words):
        ws = warn(out, "RESIDENCY_TRANSFER_OUT")
        self.assertTrue(ws, codes(out))
        self.assertEqual(ws[0]["severity"], "critical")
        self.assertEqual(out["status"], "ok_with_warnings")
        self.assertIn("aggregated or anonymised", ws[0]["message"])
        for w in words:
            self.assertIn(w, ws[0]["message"])
        return ws[0]

    def test_backup_copy_to_us_region_under_eu(self):
        w = self.assertFires(run(**CLINIC_EU), "us-east-1", "the EU", "GDPR")
        self.assertIn("project.description", w["fields"])
        self.assertIn("infrastructure.data_residency", w["fields"])

    def test_replication_to_singapore_under_india(self):
        self.assertFires(run(**SHOP_IN), "asia-southeast1", "Singapore", "India")

    def test_existing_system_abroad_and_component_agrees(self):
        out = run(**FLEET_US)
        w = self.assertFires(out, "Frankfurt", "the United States")
        self.assertIn("infrastructure.existing_systems", w["fields"])
        comp = next(s for s in sup(out, "other") if "Tableau" in s["choice"])
        self.assertTrue(comp["justification"].startswith("Residency limits this integration"), comp["justification"])
        self.assertIn("not part of this plan", comp["justification"])

    def test_rbi_says_india_only(self):
        w = self.assertFires(run(**LEDGER_RBI), "Virginia", "stored only in India")
        self.assertIn("compliance", w["fields"])

    def test_entry_only_location(self):
        out = run(**{"project.type": "saas_b2b", "infrastructure.data_residency": "india",
                     "infrastructure.existing_systems": ["HubSpot CRM account in the US region"],
                     "project.description": "Subscription billing for gyms; new members are pushed to the CRM."})
        self.assertFires(out, "United States")

    # must-not-fire
    def test_no_residency(self):
        nocode(self, {**CLINIC_EU, "infrastructure.data_residency": "none", "compliance": []})

    def test_place_inside_area(self):
        for kw in ({**SHOP_IN, "project.description": "Order events are replicated to the reporting replica in ap-south-1."},
                   {**SHOP_IN, "project.description": "Order events are replicated to the reporting replica in Mumbai."},
                   {**CLINIC_EU, "project.description": "Nightly backups of patient records are copied to a bucket in Frankfurt."}):
            nocode(self, kw)

    def test_audience_without_transfer(self):
        nocode(self, {**SHOP_IN, "project.description": "Grocery storefront; we also have customers in the US and Singapore buying gift boxes."})

    def test_negated(self):
        for d in ("Payment data never leaves India and is not replicated to us-east-1.",
                  "Order records are never exported to Singapore or the US."):
            nocode(self, {**SHOP_IN, "project.description": d})


from test_p2 import ops_run  # noqa: E402


def avt(out):
    ws = warn(out, "AVAILABILITY_VS_TEAM")
    return ws[0] if ws else None


class AvailabilityVsTeam(unittest.TestCase):
    """Item 2: a small team without DevOps or one or two beginners is never told it can staff a rota; self-run stacks get no managed claim."""

    def test_no_devops_teams_get_the_gap_as_a_warning(self):
        for ptype, size, avail in (("ecommerce", 4, "99.95"), ("iot", 3, "99.95"), ("healthtech", 5, "99.99")):
            w = avt(ops_run(ptype, size, False, avail))
            self.assertEqual(w["severity"], "warning", ptype)
            self.assertNotIn("can staff", w["message"])
            self.assertIn("nobody in the inputs owns out-of-hours on-call", w["message"])

    def test_beginner_pair_with_devops(self):
        w = avt(ops_run("marketplace", 2, True, "99.95", exp="beginner"))
        self.assertEqual(w["severity"], "warning")
        self.assertIn("cannot cover a 24/7 rota alone", w["message"])
        self.assertNotIn("nobody in the inputs", w["message"])

    def test_self_run_stacks_do_not_claim_managed_services(self):
        for ptype, dep in (("internal_tool", "on_premise"), ("fintech", "self_hosted_cloud_vm"), ("healthtech", "air_gapped")):
            w = avt(ops_run(ptype, 3, False, "99.95", dep=dep))
            self.assertIsNotNone(w, dep)
            self.assertNotIn("Managed multi-zone", w["message"], dep)
            self.assertIn(dep, w["message"])

    def test_managed_cloud_keeps_managed_wording(self):
        self.assertIn("Managed multi-zone services were preferred", avt(ops_run("saas_b2b", 4, False, "99.95"))["message"])

    # must-not-fire
    def test_staffed_team_or_standard_target(self):
        self.assertIsNone(avt(ops_run("web_app", 8, False, "99.95")))
        self.assertIsNone(avt(ops_run("web_app", 4, True, "99.99")))
        self.assertIsNone(avt(ops_run("web_app", 3, False, "99.9")))


import json  # noqa: E402
import re  # noqa: E402

from engine import dbvocab  # noqa: E402

PG_ONLY = re.compile(r"BRIN|WAL|streaming replica|pg_\w+|pgvector|pg_trgm|TimescaleDB|CREATE POLICY|postgresql\.org/docs", re.I)
NON_PG = [  # each keeps a non-PostgreSQL database the input names, on a different project type
    {"project.type": "healthtech", "team.languages": ["csharp"], "infrastructure.deployment_model": "on_premise", "requirements.availability": "99.95",
     "requirements.rpo_minutes": 2, "infrastructure.existing_systems": ["Microsoft SQL Server 2022 ward database (must stay)"],
     "project.description": "Ward round checklists and bed allocation for a district hospital."},
    {"project.type": "iot", "team.languages": ["csharp"], "infrastructure.cloud_preference": "azure", "scale.workload": "write_heavy",
     "scale.data_volume_gb": 900, "infrastructure.existing_systems": ["SQL Server 2019 telemetry database (keep)"],
     "project.description": "Water pumping stations report pressure every ten seconds."},
    {"project.type": "ecommerce", "team.languages": ["php"], "infrastructure.deployment_model": "on_premise", "requirements.availability": "99.95",
     "infrastructure.existing_systems": ["MySQL 8.4 product catalogue database (keep as system of record)"],
     "project.description": "Garden centre catalogue with click-and-collect orders."},
    {"project.type": "saas_b2b", "team.languages": ["php"], "requirements.multi_tenant": True, "requirements.ml_features": "llm_rag",
     "infrastructure.existing_systems": ["MySQL 8.0 database (must remain)"],
     "project.description": "Tender tracking for construction firms with an assistant that answers from uploaded tender documents."},
    {"project.type": "social", "team.languages": ["javascript"], "requirements.ml_features": "llm_rag",
     "infrastructure.existing_systems": ["MongoDB 7 replica set (must stay)"],
     "project.description": "Birdwatching community with sightings, comments and an assistant that answers from past sightings."},
    {"project.type": "iot", "team.languages": ["javascript"], "scale.workload": "write_heavy", "scale.data_volume_gb": 800,
     "infrastructure.deployment_model": "self_hosted_cloud_vm", "requirements.availability": "99.95", "requirements.rpo_minutes": 1,
     "infrastructure.existing_systems": ["MongoDB 7 cluster (keep)"], "project.description": "Cold-store sensors report temperature every minute."},
    {"project.type": "fintech", "team.languages": ["csharp"], "requirements.multi_tenant": True, "infrastructure.cloud_preference": "azure",
     "requirements.availability": "99.99", "infrastructure.existing_systems": ["SQL Server 2022 loan ledger (system of record)"],
     "project.description": "Equipment leasing portal for small workshops."},
    {"project.type": "data_analytics", "team.languages": ["python"], "scale.workload": "write_heavy", "scale.data_volume_gb": 2000,
     "infrastructure.deployment_model": "on_premise", "requirements.rpo_minutes": 3, "infrastructure.existing_systems": ["MySQL 8.4 sales database (keep)"],
     "project.description": "Weekly sales reports for a chain of pharmacies."},
    {"project.type": "internal_tool", "team.languages": ["java"], "infrastructure.deployment_model": "on_premise", "requirements.rpo_minutes": 2,
     "infrastructure.existing_systems": ["SQL Server 2017 HR database (keep)"], "project.description": "Leave requests and approvals for staff."},
]


class DatabaseVocabulary(unittest.TestCase):
    """Item 3: no PostgreSQL-only term on a stack whose database is not PostgreSQL."""

    def test_sweep_non_postgres_outputs(self):
        engines = set()
        for kw in NON_PG:
            out = run(**kw)
            self.assertNotEqual(out["status"], "invalid_input", out["validation_errors"])
            db = out["stack"]["database"]["choice"]
            self.assertNotIn("postgres", db.lower(), kw["project.description"])
            engines.add(db.split()[1])
            for comp in [out["stack"][k] for k in ("frontend", "backend", "database", "hosting") if out["stack"].get(k)] + out["stack"]["supporting"]:
                text = json.dumps({k: v for k, v in comp.items() if k != "alternatives"}, ensure_ascii=False)
                self.assertIsNone(PG_ONLY.search(text), (db, comp["choice"], PG_ONLY.search(text)))
            rest = json.dumps([out["warnings"], out["assumptions"], out["estimated_monthly_cost_usd"]], ensure_ascii=False)
            self.assertIsNone(PG_ONLY.search(rest), (db, PG_ONLY.search(rest)))
        self.assertEqual(engines, {"SQL", "MySQL", "MongoDB"})

    def test_engine_terms(self):
        self.assertIn("Always On availability group", dbvocab.standby("sqlserver"))
        self.assertIn("log shipping", dbvocab.rpo("sqlserver"))
        self.assertIn("binary-log", dbvocab.rpo("mysql"))
        self.assertIn("replica set", dbvocab.rpo("mongodb"))
        self.assertIn("columnstore", dbvocab.time_partitions("sqlserver")[0])
        self.assertIn("RANGE", dbvocab.time_partitions("mysql")[0])
        for e in ("sqlserver", "mysql", "mongodb", "dynamodb", "cosmosdb"):
            for f in (dbvocab.standby, dbvocab.rpo, dbvocab.replica):
                self.assertIsNone(PG_ONLY.search(f(e)), (e, f.__name__))
            self.assertIsNone(PG_ONLY.search(dbvocab.time_partitions(e)[0]), e)

    # must-not-fire: PostgreSQL keeps its own terms
    def test_postgres_keeps_wal_and_brin(self):
        self.assertIn("WAL", dbvocab.rpo("postgresql"))
        self.assertIn("BRIN", dbvocab.time_partitions("postgresql")[0])
        out = run(**{"project.type": "iot", "scale.workload": "write_heavy", "scale.data_volume_gb": 900, "infrastructure.deployment_model": "on_premise",
                     "requirements.rpo_minutes": 2, "project.description": "Weather stations report wind speed every minute."})
        self.assertIn("PostgreSQL", out["stack"]["database"]["choice"])
        self.assertIn("WAL", json.dumps(out["warnings"]))


if __name__ == "__main__":
    unittest.main()
