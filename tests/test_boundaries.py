"""Boundary set B01-B34 (review dispositions.json). Expectations are invariants, not exact stacks.

Authored before the selection logic. Base: scenarios/stacksense_public_scenarios.json
(sha256 6a4aa08bd2fddfaf6a6498188867848d721c5cb6822164b27a783ae8ead76d57), $[i] = P(i+1).
"""
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from engine.load import parse_text  # noqa: E402
from engine.run import evaluate  # noqa: E402
from check_contract import check  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
    PUBLIC = json.load(f)


def P(i):
    return copy.deepcopy(PUBLIC[i - 1])


def run(s):
    out = evaluate(s)
    errs = check(out)
    assert not errs, errs
    return out


def comps(out):
    st = out["stack"]
    return [st[k] for k in ("frontend", "backend", "database", "hosting")] + st.get("supporting", [])


def err_fields(out):
    return {e["field"] for e in out["validation_errors"]}


def warn_codes(out, sev=None):
    return {w["code"] for w in out["warnings"] if sev is None or w["severity"] == sev}


def blob(out):
    return json.dumps(out["stack"]).lower()


class Contract(unittest.TestCase):
    def test_B01_all_public_valid(self):
        for i in range(1, 7):
            out = run(P(i))
            self.assertIn(out["status"], ("ok", "ok_with_warnings"), out["scenario_id"])
            self.assertEqual(out["scenario_id"], f"P{i}")

    def test_B02_required_only_equals_explicit_defaults(self):
        s = P(1)
        mini = {"project": {k: s["project"][k] for k in ("type", "platforms")},
                "scale": {k: s["scale"][k] for k in ("users_at_launch", "users_12_months")},
                "team": {k: s["team"][k] for k in ("size", "experience", "languages")},
                "budget": s["budget"], "timeline": s["timeline"]}
        explicit = copy.deepcopy(mini)
        explicit["scale"].update(traffic_pattern="steady", workload="balanced")
        explicit["team"]["has_devops"] = False
        explicit["infrastructure"] = {"cloud_preference": "any", "deployment_model": "managed_cloud",
                                      "data_residency": "none"}
        explicit["requirements"] = {"realtime": False, "offline_support": False, "full_text_search": False,
                                    "file_media_storage": False, "payments": False, "auth": "none",
                                    "multi_tenant": False, "ml_features": "none", "seo_critical": False,
                                    "availability": "99.9"}
        explicit["compliance"] = []
        explicit["priorities"] = {k: 3 for k in ("cost", "time_to_market", "scalability", "performance",
                                                 "maintainability", "security")}
        a, b = run(mini), run(explicit)
        self.assertEqual(a["stack"], b["stack"])
        joined = " ".join(a["assumptions"]).lower()
        for key in ("traffic_pattern", "deployment_model", "availability", "priorities.cost"):
            self.assertIn(key, joined)
        partial = P(2)
        partial["priorities"] = {"cost": 5}
        out = run(partial)
        self.assertIn("priorities.security", " ".join(out["assumptions"]))

    def test_B03_missing_required(self):
        s = P(2)
        del s["team"]["size"]
        out = run(s)
        self.assertEqual(out["status"], "invalid_input")
        self.assertIsNone(out["stack"])
        self.assertIn("team.size", err_fields(out))

    def test_B04_all_errors_reported(self):
        s = P(2)
        s["scale"]["users_at_launch"] = -5
        s["priorities"]["cost"] = 7
        s["infrastructure"]["deployment_model"] = "cloud"
        s["requirements"]["realtime"] = "yes"
        out = run(s)
        self.assertEqual(out["status"], "invalid_input")
        self.assertTrue({"scale.users_at_launch", "priorities.cost", "infrastructure.deployment_model",
                         "requirements.realtime"} <= err_fields(out))

    def test_B05_bool_and_fraction_not_integers(self):
        for bad in (True, 2.5, "2"):
            s = P(1)
            s["team"]["size"] = bad
            self.assertEqual(run(s)["status"], "invalid_input", bad)
        s = P(1)
        s["team"]["size"] = 1.0
        self.assertEqual(run(s)["status"], "invalid_input")  # D3: integers must be JSON integers

    def test_B06_nonfinite(self):
        base = json.dumps(P(1))
        for tok in ("NaN", "Infinity", "-Infinity", "1e400"):
            text = base.replace('"monthly_infra_usd": 0', f'"monthly_infra_usd": {tok}')
            items = parse_text(text)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["status"], "invalid_input", tok)

    def test_B07_duplicate_keys(self):
        text = json.dumps(P(1)).replace('"budget": {"monthly_infra_usd": 0}',
                                        '"budget": {"monthly_infra_usd": 0}, "budget": {"monthly_infra_usd": 5}')
        out = parse_text(text)[0]
        self.assertEqual(out["status"], "invalid_input")
        self.assertIn("budget", err_fields(out))

    def test_B08_bom(self):
        text = "﻿" + json.dumps(P(1))
        out = parse_text(text)[0]
        self.assertEqual(out["stack"], run(P(1))["stack"])

    def test_B09_latency(self):
        for val, ok in ((None, True), ("absent", True), (0, False), ("300", False), (300, True)):
            s = P(2)
            if val == "absent":
                del s["requirements"]["p95_latency_ms"]
            else:
                s["requirements"]["p95_latency_ms"] = val
            self.assertEqual(run(s)["status"] != "invalid_input", ok, val)

    def test_B10_languages(self):
        for langs in ([], ["zig"]):
            s = P(1)
            s["team"]["languages"] = langs
            self.assertNotEqual(run(s)["status"], "invalid_input", langs)
        s = P(1)
        s["team"]["languages"] = ["JavaScript"]
        out = run(s)
        self.assertNotEqual(out["status"], "invalid_input")
        self.assertIn("lower", " ".join(out["assumptions"]).lower())

    def test_B11_malformed(self):
        for text in ("{not json", "42", "", "[]", "[1]"):
            items = parse_text(text)
            self.assertTrue(items, text)
            for out in items:
                self.assertEqual(out["status"], "invalid_input", text)
                self.assertFalse(check(out), text)

    def test_B12_array_and_single_agree(self):
        with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
            items = parse_text(f.read())
        self.assertEqual([o["scenario_id"] for o in items], [f"P{i}" for i in range(1, 7)])
        for i, o in enumerate(items, 1):
            self.assertEqual(o, run(P(i)))
        arr = [P(1), "broken", P(3)]
        res = parse_text(json.dumps(arr))
        self.assertEqual([r["status"] == "invalid_input" for r in res], [False, True, False])


class HardConstraints(unittest.TestCase):
    def _self_hostable(self, out):
        for c in comps(out):
            if c["choice"] != "None":
                self.assertIn(c.get("deployment"), ("self_hosted", "client", "none", "library"),
                              f"{c['choice']} is {c.get('deployment')}")
        self.assertNotIn("cdn", [s["layer"] for s in out["stack"].get("supporting", [])])

    def test_B13_on_premise_self_hostable_only(self):
        for i in (1, 2, 5):
            s = P(i)
            s["infrastructure"]["deployment_model"] = "on_premise"
            if i == 5:
                s["infrastructure"]["cloud_preference"] = "any"
            out = run(s)
            self.assertIsNotNone(out["stack"], i)
            self._self_hostable(out)

    def test_B14_air_gapped(self):
        s = P(1)
        s["infrastructure"]["deployment_model"] = "air_gapped"
        out = run(s)
        self._self_hostable(out)
        s = P(2)
        s["infrastructure"]["deployment_model"] = "air_gapped"
        out = run(s)
        crit = warn_codes(out, "critical")
        self.assertTrue(any("OTP" in c or "PHONE" in c for c in crit), crit)
        self.assertTrue(any("PAYMENT" in c for c in crit), crit)

    def test_B15_aws_explicit(self):
        out = run(P(4))
        for c in comps(out):
            if c.get("provider"):
                self.assertIn(c["provider"], ("aws", "neutral"), c["choice"])
        self.assertIn(out["stack"]["hosting"]["provider"], ("aws",))
        self.assertIn("ap-south", json.dumps(out["stack"]["hosting"]))

    def test_B16_azure_switch_is_local(self):
        s = P(4)
        s["infrastructure"]["cloud_preference"] = "azure"
        out = run(s)
        self.assertEqual(out["stack"]["hosting"]["provider"], "azure")
        self.assertEqual(out["stack"]["backend"]["choice"], run(P(4))["stack"]["backend"]["choice"])

    def test_B17_gcp_with_entra(self):
        s = P(5)
        s["infrastructure"]["cloud_preference"] = "gcp"
        out = run(s)
        self.assertEqual(out["stack"]["hosting"]["provider"], "gcp")
        self.assertIn("entra", blob(out))

    def test_B18_residency(self):
        out = run(P(2))
        for c in comps(out):
            if c.get("data_bearing"):
                self.assertEqual(c.get("data_location"), "india", c["choice"])
        s = P(2)
        s["infrastructure"]["data_residency"] = "eu"
        s["compliance"] = []
        out = run(s)
        for c in comps(out):
            if c.get("data_bearing"):
                self.assertEqual(c.get("data_location"), "eu", c["choice"])
        s["infrastructure"]["data_residency"] = "other"
        out = run(s)
        self.assertIn("RESIDENCY_UNSPECIFIED", warn_codes(out))

    def test_B19_cloud_none_vs_managed(self):
        s = P(1)
        s["infrastructure"]["cloud_preference"] = "none"
        out = run(s)
        self.assertEqual(out["status"], "infeasible")
        crit = [w for w in out["warnings"] if w["severity"] == "critical"]
        self.assertTrue(any({"infrastructure.cloud_preference", "infrastructure.deployment_model"} <= set(w["fields"])
                            for w in crit))
        s["infrastructure"]["deployment_model"] = "on_premise"
        self.assertNotEqual(run(s)["status"], "infeasible")

    def test_B20_air_gapped_with_aws(self):
        s = P(4)
        s["infrastructure"]["deployment_model"] = "air_gapped"
        self.assertEqual(run(s)["status"], "infeasible")

    def test_B21_pci(self):
        s = P(2)
        s["compliance"].append("pci_dss")
        out = run(s)
        pay = [c for c in out["stack"]["supporting"] if c["layer"] == "payments"]
        self.assertTrue(pay)
        text = json.dumps(out).lower()
        self.assertNotIn("certified compliant", text)
        self.assertIn("pci", json.dumps(pay).lower())

    def test_B22_hipaa(self):
        s = P(3)
        s["compliance"].append("hipaa")
        out = run(s)
        self.assertIn("hipaa", json.dumps(out).lower())
        self.assertTrue(any("HIPAA" in w["code"] for w in out["warnings"]))

    def test_B23_existing_sql_server_lifecycle(self):
        out = run(P(5))
        self.assertFalse(any(w["code"] == "END_OF_LIFE_SYSTEM" for w in out["warnings"]))
        self.assertIn("sql server", blob(out))
        s = P(5)
        s["infrastructure"]["existing_systems"] = ["On-prem SQL Server 2012"]
        out = run(s)
        self.assertTrue(any(w["code"] == "END_OF_LIFE_SYSTEM" for w in out["warnings"]))

    def test_B24_no_existing_systems(self):
        s = P(5)
        s["infrastructure"]["existing_systems"] = []
        out = run(s)
        self.assertNotIn("on-prem sql server", blob(out))
        self.assertTrue(any(c["layer"] == "auth" for c in out["stack"]["supporting"]))


class SoftAndSemantic(unittest.TestCase):
    def test_B25_zero_budget(self):
        out = run(P(1))
        self.assertEqual(out["estimated_monthly_cost_usd"]["min"], 0)
        self.assertEqual(out["architecture_style"], "static")
        self.assertEqual(out["stack"]["backend"]["choice"], "None")
        self.assertEqual(out["stack"]["database"]["choice"], "None")

    def test_B26_low_budget_warned(self):
        s = P(2)
        s["budget"]["monthly_infra_usd"] = 15
        out = run(s)
        self.assertEqual(out["status"], "ok_with_warnings")
        self.assertIn("BUDGET_EXCEEDED", warn_codes(out))

    def test_B27_big_budget_no_microservices(self):
        s = P(3)
        s["budget"]["monthly_infra_usd"] = 1000000
        self.assertNotEqual(run(s)["architecture_style"], "microservices")

    def test_B28_static_scale_trap(self):
        s = P(1)
        s["scale"]["users_12_months"] = 3000000
        s["scale"]["peak_concurrent_users"] = 50000
        out = run(s)
        self.assertEqual(out["architecture_style"], "static")
        self.assertNotIn("kubernetes", blob(out))

    def test_B29_contradictions(self):
        s = P(1)
        s["requirements"]["availability"] = "99.99"
        s["project"]["platforms"] = ["web", "android", "ios", "desktop", "api_only"]
        out = run(s)
        self.assertEqual(out["status"], "ok_with_warnings")
        fields = {f for w in out["warnings"] for f in w["fields"]}
        self.assertIn("requirements.availability", fields)
        self.assertIn("project.platforms", fields)

    def test_B30_skill_mismatch(self):
        s = P(5)
        s["team"]["languages"] = ["python"]
        out = run(s)
        self.assertNotEqual(out["stack"]["backend"]["choice"], run(P(5))["stack"]["backend"]["choice"])

    def test_B31_offline_toggle(self):
        on = run(P(6))
        s = P(6)
        s["requirements"]["offline_support"] = False
        off = run(s)
        self.assertIn("offline", blob(on))
        self.assertEqual(on["stack"]["hosting"]["choice"], off["stack"]["hosting"]["choice"])
        self.assertEqual(on["stack"]["database"]["choice"], off["stack"]["database"]["choice"])

    def test_B32_description_only_moves_supporting(self):
        a = run(P(4))
        s = P(4)
        s["project"]["description"] = "Small personal loans. KYC document upload, credit scoring model, double-entry ledger."
        b = run(s)
        for k in ("frontend", "backend", "database", "hosting"):
            self.assertEqual(a["stack"][k]["choice"], b["stack"][k]["choice"], k)
        self.assertIn("upi", json.dumps(a["stack"]["supporting"]).lower())

    def test_B33_renamed_metadata(self):
        for i in range(1, 7):
            s = P(i)
            s["scenario_id"] = "ZZ"
            s["project"]["name"] = "Renamed"
            a, b = run(P(i)), run(s)
            self.assertEqual(a["stack"], b["stack"])
            self.assertEqual(a["estimated_monthly_cost_usd"], b["estimated_monthly_cost_usd"])
            self.assertEqual(a["warnings"], b["warnings"])


class Determinism(unittest.TestCase):
    def test_B34_bytes_across_processes_and_seeds(self):
        src = os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json")
        outs = []
        for seed in ("0", "1"):
            d = tempfile.mkdtemp()
            env = dict(os.environ, PYTHONHASHSEED=seed, STACKSENSE_LLM="off")
            subprocess.run([sys.executable, "-I", os.path.join(ROOT, "stacksense.py"), "run", src,
                            "--out", d, "--no-llm"], check=True, env=env, capture_output=True)
            outs.append({n: open(os.path.join(d, n), "rb").read() for n in sorted(os.listdir(d))})
        self.assertEqual(len(outs[0]), 6)
        self.assertEqual(outs[0], outs[1])

    def test_no_network(self):
        real = socket.socket.connect

        def boom(*a, **k):
            raise AssertionError("network used")
        socket.socket.connect = boom
        try:
            for i in range(1, 7):
                run(P(i))
        finally:
            socket.socket.connect = real


if __name__ == "__main__":
    unittest.main()
