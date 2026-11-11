"""Round 6 (12 Nov session): review findings and Round 5 items 4-9. Each test written before the change."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from engine.run import evaluate  # noqa: E402
from check_contract import check  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
    PUBLIC = json.load(f)


def with_existing(system, cf=False):
    s = copy.deepcopy(PUBLIC[1])
    s["infrastructure"]["existing_systems"] = [system]
    out = evaluate(s, counterfactuals=cf)
    return {w["code"] for w in out["warnings"]}


class LifecycleSpellings(unittest.TestCase):
    """Review finding: common spellings slipped past the substring match (reproduced: no lifecycle warning)."""

    def test_common_spellings_are_recognised(self):
        for raw in ("Node.js 18 API", "NodeJS 20 service", "node-18 worker", "ASP.NET Core 8 API", "Angular 1.x app"):
            self.assertIn("END_OF_LIFE_SYSTEM", with_existing(raw), raw)
        self.assertIn("END_OF_LIFE_SOON", with_existing("PostgreSQL14 cluster"))

    def test_newer_versions_are_not_flagged(self):
        for raw in ("Node.js 22 API", "Node 180 widgets", "Python 3.13", ".NET 10 API", "PostgreSQL 16", "Angular 17 app"):
            self.assertFalse(with_existing(raw) & {"END_OF_LIFE_SYSTEM", "END_OF_LIFE_SOON"}, raw)


class RedirectedOutput(unittest.TestCase):
    """Review finding, reproduced: `run E3 --explain > file` crashed with UnicodeEncodeError on a cp1252 console."""

    def test_explain_survives_a_legacy_output_encoding(self):
        import subprocess
        import tempfile
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        with tempfile.TemporaryDirectory() as d:
            for scen in ("edge_cases/E3_contradictions.json", "hidden_like/H02_FieldPulse.json"):
                r = subprocess.run([sys.executable, os.path.join(ROOT, "stacksense.py"), "run", os.path.join(ROOT, "scenarios", scen),
                                    "--out", d, "--explain"], capture_output=True, env=env)
                self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-300:])
                self.assertIn("\nCost: ", r.stdout.decode("utf-8"))  # whole explanation printed, decodes as UTF-8


CORE = ("frontend", "backend", "database", "hosting")
_OUT = {}


def pub(i):
    if i not in _OUT:
        _OUT[i] = evaluate(copy.deepcopy(PUBLIC[i - 1]))
    return _OUT[i]


class Confidence(unittest.TestCase):
    """Round 5 item 4: one confidence label per core layer from stability and score_margin, plus a contrastive sentence."""

    def test_label_follows_the_documented_rule(self):
        for i in range(1, 7):
            for layer in CORE:
                c = pub(i)["stack"][layer]
                conf, st, m = c["confidence"], c["stability"]["score"], c.get("score_margin")
                want = ("low" if st < 0.7 or (m is not None and m < 1.0) else
                        "high" if st >= 0.9 and (m is None or m >= 2.0) else "medium")
                self.assertEqual(conf["label"], want, (i, layer, st, m))
                self.assertIn(f"{st:.2f}", conf["basis"], (i, layer))
                if m is not None:
                    self.assertIn(f"margin {m}", conf["basis"], (i, layer))

    def test_known_cases(self):
        self.assertEqual(pub(2)["stack"]["backend"]["confidence"]["label"], "low")   # 0.63 stability, 0.8 margin
        self.assertEqual(pub(5)["stack"]["backend"]["confidence"]["label"], "high")  # 1.00 stability, 9.2 margin

    def test_contrast_names_the_runner_up_and_the_accepted_tradeoff(self):
        seen = 0
        for i in range(1, 7):
            for layer in CORE:
                c = pub(i)["stack"][layer]
                if not c["alternatives"]:
                    self.assertNotIn("contrast", c)
                    continue
                seen += 1
                alt = c["alternatives"][0]["choice"].split(" (")[0]
                self.assertIn(" rather than " + alt, c["contrast"], (i, layer))
                if c["tradeoffs"]:
                    self.assertIn("Trade-off accepted: " + c["tradeoffs"][0][:20], c["contrast"], (i, layer))
        self.assertGreater(seen, 15)

    def test_explain_prints_confidence_and_contrast(self):
        import stacksense
        text = stacksense.explain(pub(2))
        self.assertIn("confidence low", text)
        self.assertIn(" rather than ", text)


if __name__ == "__main__":
    unittest.main()
