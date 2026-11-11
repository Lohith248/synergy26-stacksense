"""Round 5 (research R9/R10): no-LLM guard, deterministic rank stability. Tests written before the code."""
import ast
import copy
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from engine.run import evaluate  # noqa: E402
from check_contract import check  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
    PUBLIC = json.load(f)

CORE = ("frontend", "backend", "database", "hosting")
PRIO = ("cost", "time_to_market", "scalability", "performance", "maintainability", "security")
FORBIDDEN = {"openai", "anthropic", "google", "cohere", "mistralai", "ollama", "langchain", "litellm", "transformers",
             "requests", "httpx", "aiohttp", "urllib", "urllib3", "http.client", "socket", "ssl", "websockets", "ftplib", "smtplib"}
LOCAL_SERVER = {os.path.join("engine", "web.py"): {"http.server"}}  # the optional 127.0.0.1 UI only


def imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            found |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0:
            found.add(n.module)
    return found


class NoLlmGuard(unittest.TestCase):
    def test_runtime_has_no_llm_or_outbound_network_imports(self):
        files = glob.glob(os.path.join(ROOT, "engine", "*.py")) + [os.path.join(ROOT, "stacksense.py")]
        self.assertGreater(len(files), 10)
        for p in files:
            rel = os.path.relpath(p, ROOT)
            for mod in imports(p) - LOCAL_SERVER.get(rel, set()):
                self.assertFalse(mod.split(".")[0] in FORBIDDEN or mod in FORBIDDEN, f"{rel} imports {mod}")

    def test_the_guard_can_fail(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write("import anthropic\nfrom urllib import request\n")
            self.assertEqual({m.split(".")[0] for m in imports(p)} & FORBIDDEN, {"anthropic", "urllib"})

    def test_no_llm_flag_changes_nothing(self):
        scen = os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for out, extra in ((a, []), (b, ["--no-llm"])):
                subprocess.run([sys.executable, "-I", os.path.join(ROOT, "stacksense.py"), "run", scen, "--out", out] + extra,
                               check=True, capture_output=True)
            for i in range(1, 7):
                name = f"P{i}_output.json"
                with open(os.path.join(a, name), "rb") as fa, open(os.path.join(b, name), "rb") as fb, \
                        open(os.path.join(ROOT, "outputs", name), "rb") as fc:
                    ba = fa.read()
                    self.assertEqual(ba, fb.read(), name)
                    self.assertEqual(ba, fc.read(), name)  # committed outputs are what the engine produces


def grid(scale):
    """The documented weight grid: every single priority at every other value 1-5, then every ordered pair
    'favour one (5) over another (1)'. Vectors equal to the scenario's own weights are skipped."""
    cur = {k: scale["priorities"][k] for k in PRIO}
    out = []
    for k in PRIO:
        out += [{k: v} for v in range(1, 6) if v != cur[k]]
    for i, a in enumerate(PRIO):
        for b in PRIO[i + 1:]:
            for hi, lo in ((a, b), (b, a)):
                if cur[hi] != 5 or cur[lo] != 1:
                    out.append({hi: 5, lo: 1})
    return out


def kb(doc, layer):
    return doc["stack"][layer]["kb_id"]


class RankStability(unittest.TestCase):
    def test_every_core_layer_reports_stability(self):
        for i, s in enumerate(PUBLIC, 1):
            out = evaluate(copy.deepcopy(s))
            self.assertFalse(check(out), check(out))
            for layer in CORE:
                st = out["stack"][layer]["stability"]
                self.assertTrue(0 <= st["score"] <= 1, (i, layer))
                self.assertGreaterEqual(st["vectors_tested"], 30)
                self.assertIn(st["label"], ("robust", "moderate", "sensitive"))
                self.assertEqual(st["label"], "robust" if st["score"] >= 0.9 else "moderate" if st["score"] >= 0.7 else "sensitive")
                self.assertTrue(isinstance(st["alternatives"], list))

    def test_score_matches_an_independent_recomputation(self):
        for i in (1, 4, 6):
            s = PUBLIC[i - 1]
            out = evaluate(copy.deepcopy(s))
            vectors = grid(s)
            for layer in CORE:
                same = 0
                for v in vectors:
                    s2 = copy.deepcopy(s)
                    s2["priorities"].update(v)
                    same += kb(evaluate(s2, counterfactuals=False), layer) == kb(out, layer)
                st = out["stack"][layer]["stability"]
                self.assertEqual(st["vectors_tested"], len(vectors), (i, layer))
                self.assertAlmostEqual(st["score"], round(same / len(vectors), 2), 2, (i, layer))

    def test_flip_point_really_flips_and_is_nearest(self):
        seen = 0
        for i, s in enumerate(PUBLIC, 1):
            out = evaluate(copy.deepcopy(s))
            for layer in CORE:
                fp = out["stack"][layer]["stability"]["flip_point"]
                if fp is None:
                    continue
                seen += 1
                s2 = copy.deepcopy(s)
                s2["priorities"][fp["priority"]] = fp["value"]
                self.assertNotEqual(kb(evaluate(s2, counterfactuals=False), layer), kb(out, layer), (i, layer, fp))
                cur = s["priorities"][fp["priority"]]
                for k in PRIO:  # nothing strictly nearer (smaller change) flips the layer
                    for v in range(1, 6):
                        if v == s["priorities"][k] or abs(v - s["priorities"][k]) >= abs(fp["value"] - cur):
                            continue
                        s3 = copy.deepcopy(s)
                        s3["priorities"][k] = v
                        self.assertEqual(kb(evaluate(s3, counterfactuals=False), layer), kb(out, layer), (i, layer, k, v))
        self.assertGreater(seen, 3)

    def test_deterministic_bytes(self):
        a = json.dumps(evaluate(copy.deepcopy(PUBLIC[3])), sort_keys=True)
        b = json.dumps(evaluate(copy.deepcopy(PUBLIC[3])), sort_keys=True)
        self.assertEqual(a, b)

    def test_invalid_input_has_no_stack_and_does_not_crash(self):
        bad = copy.deepcopy(PUBLIC[0])
        bad["priorities"]["cost"] = 9
        self.assertIsNone(evaluate(bad)["stack"])


if __name__ == "__main__":
    unittest.main()
