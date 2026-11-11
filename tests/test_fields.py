"""Session A step 4: `stacksense.py fields` documents every input; the effects are checked against a real sweep."""
import contextlib
import copy
import glob
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import perturb as pt  # noqa: E402
import stacksense  # noqa: E402
from engine.run import evaluate  # noqa: E402
from engine.validate import FIELDS  # noqa: E402

PATHS = [f[0] for f in FIELDS]
DESCRIPTIONS = ["Loan disbursal and EMI collection with a ledger", "Used only by employees on the intranet",
                "50,000 sensors send readings every 30 seconds", "Real-time multiplayer game with leaderboards"]


def cli(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = stacksense.main(list(args))
    return rc, buf.getvalue()


def bases():
    with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
        out = list(json.load(f))
    for p in sorted(glob.glob(os.path.join(ROOT, "scenarios", "hidden_like", "*.json")) +
                    glob.glob(os.path.join(ROOT, "scenarios", "edge_cases", "E[3-9]*.json"))):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        out.append(d[0] if isinstance(d, list) else d)
    return out


def snapshot(doc):
    st = doc["stack"]
    return {"core": pt.core(doc), "supp": pt.supp(doc),
            "cost": (doc["estimated_monthly_cost_usd"]["min"], doc["estimated_monthly_cost_usd"]["max"]),
            "warn": sorted({w["code"] for w in doc["warnings"]}),
            "text": json.dumps({k: st[k] for k in pt.CORE}, sort_keys=True)}


def observed_effects():
    """field -> categories that really changed in a one-field sweep over 18+ scenarios."""
    obs = {p: set() for p in PATHS}
    for sc in bases():
        b = snapshot(evaluate(copy.deepcopy(sc), counterfactuals=False))
        for path, kind, _r, _d, extra in FIELDS:
            vs = DESCRIPTIONS if path == "project.description" else pt.variants(path, kind, pt.get(sc, path), extra)
            for v in vs:
                s2 = copy.deepcopy(sc)
                pt.put(s2, path, v)
                doc = evaluate(s2, counterfactuals=False)
                if doc["status"] in ("invalid_input", "infeasible"):
                    continue
                c = snapshot(doc)
                flips = {k for k in pt.CORE if c["core"][k] != b["core"][k]}
                obs[path] |= flips
                if c["supp"] != b["supp"]:
                    obs[path].add("supporting")
                if c["cost"] != b["cost"]:
                    obs[path].add("cost")
                if c["warn"] != b["warn"]:
                    obs[path].add("warnings")
                if not flips and c["text"] != b["text"]:
                    obs[path].add("ranking")
    return obs


class FieldsCommand(unittest.TestCase):
    def test_text_lists_every_field_with_type_default_rule_and_effects(self):
        rc, text = cli("fields")
        self.assertEqual(rc, 0)
        for path, kind, required, default, extra in FIELDS:
            self.assertIn(path, text)
        for needle in ("required", "default: 'steady'", "one of any, aws, gcp, azure, none",
                       ">= 1", "1 to 5", "affects:"):
            self.assertIn(needle, text)

    def test_json_is_machine_readable_and_complete(self):
        rc, text = cli("fields", "--json")
        rows = json.loads(text)
        self.assertEqual([r["field"] for r in rows], PATHS)
        for r in rows:
            self.assertTrue({"field", "type", "required", "default", "rule", "affects", "how", "optional_extra"} <= set(r), r)
            self.assertTrue(r["how"].strip(), r["field"])
        by = {r["field"]: r for r in rows}
        self.assertEqual(by["project.type"]["required"], True)
        self.assertEqual(by["scale.traffic_pattern"]["default"], "steady")
        self.assertEqual(by["scale.peak_rps"]["optional_extra"], True)
        self.assertEqual(by["project.name"]["affects"], [])

    def test_documented_effects_cover_a_real_sweep(self):
        by = {r["field"]: set(r["affects"]) for r in json.loads(cli("fields", "--json")[1])}
        obs = observed_effects()
        missing = {p: sorted(obs[p] - by[p]) for p in PATHS if obs[p] - by[p]}
        self.assertFalse(missing, "effects seen in the sweep but not documented: %s" % missing)
        dead = [p for p in PATHS if by[p] and not obs[p]]
        self.assertFalse(dead, "documented as affecting something but nothing moved in the sweep: %s" % dead)


if __name__ == "__main__":
    unittest.main()
