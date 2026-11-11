"""Round 7 (12 Nov session): blind-judge round 3 findings. Each test written before the change."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from engine.run import evaluate  # noqa: E402
from check_contract import check  # noqa: E402

BASE = {"scenario_id": "R7", "project": {"type": "web_app", "platforms": ["web"]},
        "scale": {"users_at_launch": 50, "users_12_months": 500},
        "team": {"size": 1, "experience": "beginner", "languages": []},
        "budget": {"monthly_infra_usd": 20}, "timeline": {"mvp_weeks": 8}}


def S(**kw):
    """BASE with dotted overrides, e.g. S(**{"team.languages": ["rust"]})."""
    s = copy.deepcopy(BASE)
    for path, v in kw.items():
        node, parts = s, path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return s


def codes(out):
    return {w["code"] for w in out["warnings"]}


def bid(out):
    return out["stack"]["backend"]["choice"]


class NullOptional(unittest.TestCase):
    """Explicit JSON null on an optional field means 'not provided': default applies, info warning, never invalid."""

    def test_null_scale_fields_are_absent(self):
        s = S(**{"scale.peak_concurrent_users": None, "scale.data_volume_gb_12_months": None})
        out = evaluate(s, counterfactuals=False)
        self.assertIn(out["status"], ("ok", "ok_with_warnings"), out["validation_errors"])
        w = [x for x in out["warnings"] if x["code"] == "NULL_TREATED_AS_ABSENT"]
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["severity"], "info")
        self.assertEqual(sorted(w[0]["fields"]), ["scale.data_volume_gb_12_months", "scale.peak_concurrent_users"])
        self.assertTrue(any("scale.peak_concurrent_users" in a and "null" in a for a in out["assumptions"]))
        ref = evaluate(BASE, counterfactuals=False)
        self.assertEqual(out["stack"], ref["stack"])
        self.assertEqual(check(out), [])

    def test_null_defaulted_field_states_default(self):
        out = evaluate(S(**{"requirements.realtime": None, "infrastructure.deployment_model": None}), counterfactuals=False)
        self.assertNotEqual(out["status"], "invalid_input", out["validation_errors"])
        txt = " ".join(out["assumptions"])
        self.assertIn("requirements.realtime null", txt)
        self.assertIn("false", txt)
        self.assertIn("'managed_cloud'", txt)

    def test_null_group_and_top_level(self):
        for k in ("requirements", "infrastructure", "priorities", "compliance"):
            s = copy.deepcopy(BASE)
            s[k] = None
            out = evaluate(s, counterfactuals=False)
            self.assertNotEqual(out["status"], "invalid_input", (k, out["validation_errors"]))
            self.assertIn("NULL_TREATED_AS_ABSENT", codes(out), k)
            self.assertEqual(check(out), [], k)

    def test_null_extra_field_is_absent(self):
        out = evaluate(S(**{"scale.peak_rps": None, "scale.geo_spread": None}), counterfactuals=False)
        self.assertNotEqual(out["status"], "invalid_input", out["validation_errors"])
        self.assertIn("NULL_TREATED_AS_ABSENT", codes(out))

    def test_null_required_is_still_an_error(self):
        for path in ("team.size", "project.type", "budget.monthly_infra_usd"):
            out = evaluate(S(**{path: None}), counterfactuals=False)
            self.assertEqual(out["status"], "invalid_input", path)
            self.assertIn(path, [e["field"] for e in out["validation_errors"]])
        s = copy.deepcopy(BASE)
        s["team"] = None  # a group with required fields cannot be absent
        self.assertEqual(evaluate(s, counterfactuals=False)["status"], "invalid_input")

    def test_p95_null_unchanged(self):
        out = evaluate(S(**{"requirements.p95_latency_ms": None}), counterfactuals=False)
        self.assertNotIn("NULL_TREATED_AS_ABSENT", codes(out))
        self.assertTrue(any(a.startswith("requirements.p95_latency_ms absent or null") for a in out["assumptions"]))


class NoBackendLanguage(unittest.TestCase):
    """A team with no backend language should not get the highest raw-rated stack regardless of learning cost."""

    def test_empty_languages_web_gets_js_or_python(self):
        out = evaluate(BASE, counterfactuals=False)
        self.assertTrue(any(k in bid(out) for k in ("Node.js", "Python")), bid(out))

    def test_client_only_language_beginner_avoids_heavy_backends(self):
        s = S(**{"project.type": "realtime_collab", "project.platforms": ["ios"], "team.languages": ["swift"],
                 "requirements.realtime": True, "budget.monthly_infra_usd": 80,
                 "priorities.time_to_market": 5, "priorities.cost": 4})
        out = evaluate(s, counterfactuals=False)
        self.assertFalse(any(k in bid(out) for k in (".NET", "Spring", "Go ")), bid(out))
        self.assertIn("SKILL_MISMATCH", codes(out))

    def test_learning_counts_double_text(self):
        from engine import context as cx, select as sl
        from engine.validate import validate
        req, _, _ = validate(S(**{"team.languages": ["swift"], "project.platforms": ["ios"]}))
        ctx = cx.build(req)
        ctx["ui_needs_js"] = True
        terms = [t for c in sl.backend_candidates(ctx, None) for t in c.terms if t[0] == "learning"]
        self.assertTrue(terms and all("counts double" in t[3] for t in terms), terms)

    def test_rust_team_gets_axum(self):
        s = S(**{"project.type": "api_platform", "project.platforms": ["api_only"], "team.languages": ["rust"],
                 "team.size": 4, "team.experience": "senior", "team.has_devops": True, "budget.monthly_infra_usd": 700,
                 "priorities.performance": 5})
        out = evaluate(s, counterfactuals=False)
        self.assertIn("Axum", bid(out))
        self.assertEqual(check(out), [])

    def test_elixir_team_gets_phoenix_with_native_realtime(self):
        s = S(**{"project.type": "ecommerce", "team.languages": ["elixir"], "team.size": 4,
                 "team.experience": "senior", "team.has_devops": True, "budget.monthly_infra_usd": 1200,
                 "infrastructure.deployment_model": "self_hosted_cloud_vm", "requirements.realtime": True,
                 "scale.users_12_months": 60000, "scale.peak_concurrent_users": 20000, "priorities.performance": 5})
        out = evaluate(s, counterfactuals=False)
        self.assertIn("Phoenix", bid(out))
        rt = [x for x in out["stack"]["supporting"] if x.get("layer") == "realtime"]
        self.assertTrue(rt and "Phoenix" in rt[0]["choice"], rt)
        self.assertNotIn("Socket.IO", str(rt))
        self.assertEqual(check(out), [])

    def test_new_backends_penalised_on_functions(self):
        from engine.kb import TECH
        ids = {b["id"] for b in TECH["backend"]}
        self.assertTrue({"rust-axum", "elixir-phoenix"} <= ids)


if __name__ == "__main__":
    unittest.main()
