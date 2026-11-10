"""Knowledge-base lint, deprecated-product guard and interactive-mode smoke test."""
import copy
import io
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.kb import TECH, SOURCES, AS_OF  # noqa: E402
from engine.run import evaluate  # noqa: E402
import engine.services as services  # noqa: E402
import stacksense  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf-8") as f:
    PUBLIC = json.load(f)


def all_src_ids():
    for group in ("hosting", "frontend_web", "frontend_mobile", "backend", "database"):
        for item in TECH[group]:
            for s in item["src"]:
                yield group, item["id"], s
    for lc in TECH["lifecycle"]:
        yield "lifecycle", lc["pattern"], lc["src"]
    for pat in TECH["existing_patterns"]:
        for s in pat["src"]:
            yield "existing", pat["name"], s


class KnowledgeBase(unittest.TestCase):
    def test_every_source_id_resolves(self):
        missing = [(g, i, s) for g, i, s in all_src_ids() if s not in SOURCES]
        self.assertEqual(missing, [])

    def test_records_complete(self):
        for group in ("hosting", "frontend_web", "frontend_mobile", "backend", "database"):
            ids = [x["id"] for x in TECH[group]]
            self.assertEqual(len(ids), len(set(ids)), group)
            for item in TECH[group]:
                self.assertEqual(len(item["r"]), 6, item["id"])
                self.assertTrue(item["strengths"] and item["limits"], item["id"])
        for h in TECH["hosting"]:
            self.assertEqual(len(h["cost"]), 4, h["id"])
            self.assertTrue(all(lo <= hi for lo, hi in h["cost"]), h["id"])
            self.assertTrue(h["regions"], h["id"])
        # FAQ guidance: a credible engine knows 6-8 options per core layer
        self.assertGreaterEqual(len(TECH["hosting"]), 8)
        self.assertGreaterEqual(len(TECH["backend"]), 8)
        self.assertGreaterEqual(len(TECH["frontend_web"]) + len(TECH["frontend_mobile"]), 8)
        self.assertGreaterEqual(len(TECH["database"]), 5)

    def test_sources_have_status(self):
        for k, v in SOURCES.items():
            if k.startswith("_"):
                continue
            self.assertIn(v["status"], ("verified", "official-unverified", "source-reported"), k)


DEPRECATED = ("minio", "app runner", "azure cache for redis", "create react app", "vue 2", "angularjs",
              ".net 8", "node.js 20", "postgresql 13", "heroku free")


def mutations():
    for i, base in enumerate(PUBLIC):
        yield base
        for dep in ("managed_cloud", "self_hosted_cloud_vm", "on_premise", "air_gapped"):
            for cloud in ("any", "aws", "azure", "gcp"):
                s = copy.deepcopy(base)
                s["infrastructure"]["deployment_model"] = dep
                s["infrastructure"]["cloud_preference"] = cloud
                yield s


class NoDeprecatedChoices(unittest.TestCase):
    def test_choices_never_deprecated(self):
        n = 0
        for s in mutations():
            out = evaluate(s)
            if not out["stack"]:
                continue
            st = out["stack"]
            for c in [st[k] for k in ("frontend", "backend", "database", "hosting")] + st["supporting"]:
                low = c["choice"].lower()
                for d in DEPRECATED:
                    self.assertNotIn(d, low, f"{c['choice']} in {s.get('scenario_id')}")
            n += 1
        self.assertGreater(n, 60)

    def test_hard_constraints_on_all_mutations(self):
        for s in mutations():
            out = evaluate(s)
            if not out["stack"]:
                self.assertEqual(out["status"], "infeasible")
                continue
            h = out["stack"]["hosting"]
            cloud = s["infrastructure"]["cloud_preference"]
            if cloud in ("aws", "azure", "gcp"):
                self.assertEqual(h["provider"], cloud)
            dep = s["infrastructure"]["deployment_model"]
            if dep in ("on_premise", "air_gapped"):
                self.assertEqual(h["deployment"], "self_hosted")
            if dep == "self_hosted_cloud_vm":
                self.assertEqual(h["deployment"], "self_hosted")


class Interactive(unittest.TestCase):
    def test_wizard_reproduces_p5(self):
        p = PUBLIC[4]
        r = p["requirements"]
        yn = lambda b: "y" if b else "n"  # noqa: E731
        answers = [p["scenario_id"], p["project"]["name"], p["project"]["type"], p["project"]["description"],
                   ",".join(p["project"]["platforms"]),
                   str(p["scale"]["users_at_launch"]), str(p["scale"]["users_12_months"]), str(p["scale"]["peak_concurrent_users"]),
                   p["scale"]["traffic_pattern"], p["scale"]["workload"], str(p["scale"]["data_volume_gb_12_months"]),
                   str(p["team"]["size"]), p["team"]["experience"], ",".join(p["team"]["languages"]), yn(p["team"]["has_devops"]),
                   str(p["budget"]["monthly_infra_usd"]), str(p["timeline"]["mvp_weeks"]),
                   p["infrastructure"]["cloud_preference"], p["infrastructure"]["deployment_model"], p["infrastructure"]["data_residency"],
                   ",".join(p["infrastructure"]["existing_systems"])]
        answers += [yn(r[k]) for k in ("realtime", "offline_support", "full_text_search", "file_media_storage", "payments", "multi_tenant", "seo_critical")]
        answers += [r["auth"], r["ml_features"], r["availability"], str(r["p95_latency_ms"]), ",".join(p["compliance"])]
        answers += [str(p["priorities"][k]) for k in ("cost", "time_to_market", "scalability", "performance", "maintainability", "security")]
        answers += ["n"]  # no optional extra inputs (prompt added with the extra fields)
        import tempfile
        d = tempfile.mkdtemp()
        with mock.patch("builtins.input", side_effect=answers), mock.patch("sys.stdout", new=io.StringIO()):
            rc = stacksense.main(["interactive", "--out", d])
        self.assertEqual(rc, 0)
        with open(os.path.join(d, "P5_output.json"), encoding="utf-8") as f:
            got = json.load(f)
        self.assertEqual(got["stack"], evaluate(copy.deepcopy(p))["stack"])


if __name__ == "__main__":
    unittest.main()
