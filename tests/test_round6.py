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

    def test_r13_rows(self):
        """research/R13: Django 4.2 ended 2026-04-07 (verified); Spring Boot 3.4/3.5 ended, 4.0 ends 2026-12-31 and
        Java 17 premier support ended 2026-09-30 (endoflife.date, secondary); Node 22/24, Python 3.11 still supported."""
        self.assertIn("END_OF_LIFE_SYSTEM", with_existing("Django 4.2 admin"))
        for raw in ("Spring Boot 3.4 service", "Spring Boot 3.5 API"):
            self.assertIn("END_OF_LIFE_SYSTEM", with_existing(raw), raw)
        self.assertIn("END_OF_LIFE_SOON", with_existing("Spring Boot 4.0 API"))
        self.assertIn("EXISTING_SYSTEM_EXTENDED_SUPPORT", with_existing("Java 17 batch jobs"))
        for raw in ("Node.js 22 API", "Node 24 worker", "Python 3.11 scripts", "Java 21 service", "Django 5.2 app", "Spring Boot 4.1 API"):
            self.assertFalse(with_existing(raw) & {"END_OF_LIFE_SYSTEM", "END_OF_LIFE_SOON"}, raw)

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


class Wording(unittest.TestCase):
    def test_known_limit_keeps_acronyms_and_camel_case(self):
        """Reproduced in P4: 'Known limit of React Native: jS runtime overhead', 'Ionic Capacitor: webView performance'."""
        text = json.dumps(pub(4), ensure_ascii=False)
        self.assertNotIn(": jS runtime", text)
        self.assertNotIn(": webView", text)
        self.assertIn("Known limit of React Native: JS runtime", text)


class AdrExport(unittest.TestCase):
    """Round 5 item 5: Architecture Decision Record per core layer (context, decision, options table, consequences)."""

    def test_record_per_layer_with_options_and_consequences(self):
        import stacksense
        doc = pub(4)
        md = stacksense.adr(doc)
        for n, layer in enumerate(CORE, 1):
            c = doc["stack"][layer]
            self.assertIn(f"## ADR-{n}: {layer}", md)
            self.assertIn(c["choice"], md)
            for a in c["alternatives"]:
                self.assertIn(f"| {a['choice']} |", md)
            for t in c["tradeoffs"]:
                self.assertIn(t, md)
            self.assertIn(c["confidence"]["basis"], md)
        self.assertEqual(md.count("| Option | Outcome | Why |"), 4)
        for w in doc["warnings"]:
            if w["severity"] != "info":
                self.assertIn(w["code"], md)
        self.assertIn(f"{doc['estimated_monthly_cost_usd']['min']}-{doc['estimated_monthly_cost_usd']['max']} USD/month", md)

    def test_cli_writes_adr_only_when_asked_and_only_for_a_stack(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for args in ([], ["--adr"]):
                subprocess.run([sys.executable, "-I", os.path.join(ROOT, "stacksense.py"), "run",
                                os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), "--out", d] + args,
                               check=True, capture_output=True)
                if not args:
                    self.assertFalse([f for f in os.listdir(d) if f.endswith(".md")])
            self.assertEqual(sorted(f for f in os.listdir(d) if f.endswith(".md")), [f"P{i}_adr.md" for i in range(1, 7)])
            subprocess.run([sys.executable, "-I", os.path.join(ROOT, "stacksense.py"), "run",
                            os.path.join(ROOT, "scenarios", "edge_cases", "E2_invalid_values.json"), "--out", d, "--adr"], capture_output=True)
            self.assertEqual(len([f for f in os.listdir(d) if f.endswith(".md")]), 6)


def p6(**req):
    s = copy.deepcopy(PUBLIC[5])
    s["requirements"].update(req)
    out = evaluate(s, counterfactuals=False)
    return out


class RecoveryObjectives(unittest.TestCase):
    """Round 5 item 6: optional requirements.rto_minutes / rpo_minutes, each with a decision effect and a fields row."""

    def test_validation(self):
        for bad in (-1, "15", 1.5, True):
            out = p6(rto_minutes=bad)
            self.assertEqual(out["status"], "invalid_input", bad)
            self.assertIn("requirements.rto_minutes", {e["field"] for e in out["validation_errors"]})
        self.assertEqual(p6(rpo_minutes=0)["status"] in ("ok", "ok_with_warnings"), True)

    def test_tight_rto_or_rpo_adds_a_zone_redundant_standby(self):
        base = p6()
        self.assertNotIn("zone-redundant HA", base["stack"]["database"]["choice"])
        for edit, path in (({"rto_minutes": 15}, "requirements.rto_minutes"), ({"rpo_minutes": 0}, "requirements.rpo_minutes")):
            out = p6(**edit)
            db = out["stack"]["database"]
            self.assertIn("zone-redundant HA", db["choice"], edit)
            self.assertIn(path, db["driven_by"], edit)
            self.assertIn(path.split(".")[1].split("_")[0].upper(), db["justification"], edit)
            self.assertGreater(out["estimated_monthly_cost_usd"]["max"], base["estimated_monthly_cost_usd"]["max"], edit)

    def test_relaxed_objectives_change_nothing(self):
        base, out = p6(), p6(rto_minutes=240, rpo_minutes=60)
        self.assertEqual({k: base["stack"][k]["choice"] for k in CORE}, {k: out["stack"][k]["choice"] for k in CORE})
        self.assertEqual(base["estimated_monthly_cost_usd"], out["estimated_monthly_cost_usd"])

    def test_warnings_for_self_hosted_and_unrealistic_targets(self):
        with open(os.path.join(ROOT, "scenarios", "edge_cases", "E7_air_gapped.json"), encoding="utf-8") as f:
            e7 = json.load(f)
        e7 = copy.deepcopy(e7[0] if isinstance(e7, list) else e7)
        e7["requirements"]["rpo_minutes"] = 1
        self.assertIn("RPO_NEEDS_REPLICATION", {w["code"] for w in evaluate(e7, counterfactuals=False)["warnings"]})
        self.assertIn("RTO_BELOW_FAILOVER", {w["code"] for w in p6(rto_minutes=2)["warnings"]})
        self.assertNotIn("RTO_BELOW_FAILOVER", {w["code"] for w in p6(rto_minutes=15)["warnings"]})

    def test_fields_rows(self):
        from engine.fields import AFFECTS, HOW
        for k in ("requirements.rto_minutes", "requirements.rpo_minutes"):
            self.assertIn("database", AFFECTS[k])
            self.assertIn("Optional", HOW[k])


class CostBands(unittest.TestCase):
    """Round 5 item 7 (R11, Azure Retail Prices API): Front Door Standard has a $35/month base fee; the old $1-15 band was too low."""

    def test_p2_front_door_band_includes_the_base_fee(self):
        out = pub(2)
        cdn = next(s for s in out["stack"]["supporting"] if s["layer"] == "cdn")
        self.assertIn("Azure Front Door", cdn["choice"])
        line = next(a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("cdn:"))
        self.assertIn("$35-60/month", line)
        self.assertTrue(any("$35" in t for t in cdn["tradeoffs"]), cdn["tradeoffs"])
        self.assertTrue(any("Cloudflare" in a["choice"] for a in cdn["alternatives"]))
        with open(os.path.join(ROOT, "kb", "sources.json"), encoding="utf-8") as f:
            src = json.load(f)
        self.assertEqual(src["azure-frontdoor-pricing"]["status"], "verified")
        self.assertTrue(any("frontdoor" in u or "front-door" in u for u in cdn["sources"]), cdn["sources"])

    def test_small_tier_database_line_names_the_instance_class_it_assumes(self):
        line = next(a for a in pub(2)["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("Database "))
        self.assertIn("Burstable B2s", line)
        self.assertIn("$183", line)  # General Purpose D2ds_v5 compute alone (R11)

    def test_other_providers_keep_their_bands(self):
        out = pub(4)  # AWS: CloudFront band unchanged
        line = next((a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("cdn:")), "")
        self.assertNotIn("$35", line)


if __name__ == "__main__":
    unittest.main()
