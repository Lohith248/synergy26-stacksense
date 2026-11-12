"""Round 15 (12 Nov session): adversarial review of round 4 - description language claims, None in prose, negated
residency, low-priority leads, lifecycle facts, web offline, multi-region regions/routing, continent nouns, residency
enum suggestions, per-case residency leads, static availability, self-hosted tool cost, number format, skill-matched
alternative, wording. Each test written before the change."""
import copy
import glob
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from engine.run import evaluate  # noqa: E402
from engine import context as cx  # noqa: E402
from engine.context import primary_langs, residency_from_description  # noqa: E402
from test_round9 import PUBLIC, codes, dump, sup  # noqa: E402,F401


def P(sid, **kw):
    s = copy.deepcopy(PUBLIC[sid])
    for path, v in kw.items():
        node, parts = s, path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return evaluate(s, counterfactuals=False)


def warn(out, code):
    return next((w for w in out["warnings"] if w["code"] == code), None)


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def all_scenarios():
    out = list(PUBLIC.values())
    for f in sorted(glob.glob(os.path.join(ROOT, "scenarios", "**", "*.json"), recursive=True)):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        for s in d if isinstance(d, list) else d.get("scenarios", [d]):
            if isinstance(s, dict) and "project" in s and s not in out:
                out.append(s)
    return out


class Item1PrimaryLanguageClaims(unittest.TestCase):
    def test_unit_negated_past_hiring_contrast_compound(self):
        for desc in ("We are not a Java shop.", "The team works with go-live checklists.",
                     "We will hire two Python developers next year.", "Our previous Python team left.",
                     "Unlike a typical Rails shop, we sell furniture.", "The team works with Rust-coloured tiles.",
                     "The team uses Express shipping for parcels.", "We are hiring Go engineers."):
            self.assertEqual(primary_langs(desc), [], desc)

    def test_unit_lists_and_capitalised_go(self):
        self.assertEqual(primary_langs("Our team knows Node and Go."), ["go", "javascript"])
        self.assertEqual(primary_langs("The team writes Python, Go and Rust."), ["go", "python", "rust"])
        self.assertIn("ruby", primary_langs("Unlike a typical Rails shop, we write TypeScript; our team writes Ruby."))

    def test_description_only_promotes_a_listed_language(self):
        from engine.validate import validate
        base = copy.deepcopy(PUBLIC["P2"])
        base["project"]["description"] += " We are a Rails shop."
        req, _, _ = validate(base)
        self.assertEqual(cx.build(req)["primary_langs"], [])

    def test_p2_p3_unchanged_without_false_claim(self):
        b2 = P("P2")["stack"]["backend"]["choice"]
        for add in (" We will hire two Python developers next year.", " The team works with go-live checklists.",
                    " We are not a Java shop.", " Our team knows Node and Go."):
            out = P("P2", **{"project.description": PUBLIC["P2"]["project"]["description"] + add})
            self.assertEqual(out["stack"]["backend"]["choice"], b2, add)
            self.assertNotIn("project.description names", dump(out), add)
        b3 = P("P3")["stack"]["backend"]["choice"]
        for add in (" Our previous Python team left.", " Unlike a typical Rails shop, we write TypeScript."):
            out = P("P3", **{"project.description": PUBLIC["P3"]["project"]["description"] + add})
            self.assertEqual(out["stack"]["backend"]["choice"], b3, add)
            self.assertNotIn("project.description names", dump(out), add)

    def test_blind_rails_and_elixir_kept(self):
        for fn, want in (("B03_DuneCart.json", "ruby-rails"), ("B10_BidPulse.json", "elixir-phoenix")):
            with open(os.path.join(ROOT, "..", "research", "blind3", fn), encoding="utf-8") as f:
                s = json.load(f)
            self.assertEqual(evaluate(s, counterfactuals=False)["stack"]["backend"]["kb_id"], want, fn)


class Item2NoNoneInProse(unittest.TestCase):
    def test_cdn_why_not_has_no_none(self):
        for sid in ("P2", "P3", "P4"):
            self.assertNotIn("geo_spread=None", dump(P(sid)), sid)

    def test_no_none_value_rendered_anywhere(self):
        for s in all_scenarios():
            out = evaluate(copy.deepcopy(s), counterfactuals=False)
            for t in strings(out):
                self.assertIsNone(re.search(r"=None\b|\bNone [a-z]", t), (s.get("scenario_id"), t[:200]))


class Item3NegatedResidency(unittest.TestCase):
    def test_unit(self):
        for desc in ("Data does not need to stay in Japan; any region is fine.", "Data need not be stored in Brazil.",
                     "Customer data doesn't have to stay in Canada.", "There is no need to keep data in Australia.",
                     "Records may be stored anywhere, including Japan."):
            self.assertIsNone(residency_from_description(desc)["country"], desc)
        self.assertEqual(residency_from_description("Customer data must not leave Japan.")["country"], "japan")
        self.assertEqual(residency_from_description("Data must stay in Japan.")["country"], "japan")

    def test_p3_not_pinned(self):
        out = P("P3", **{"project.description": PUBLIC["P3"]["project"]["description"] + " Data does not need to stay in Japan; any region is fine.",
                         "infrastructure.data_residency": "other", "compliance": []})
        self.assertNotIn("RESIDENCY_FROM_DESCRIPTION", codes(out))
        self.assertNotIn("Japan East", out["stack"]["hosting"]["choice"])


LOW_LEAD = re.compile(r"^With priorities\.\w+=[12][, ]")


class Item4LowPriorityLead(unittest.TestCase):
    def test_no_why_not_led_by_low_priority(self):
        for s in all_scenarios():
            out = evaluate(copy.deepcopy(s))
            for layer in ("frontend", "backend", "database", "hosting"):
                c = out["stack"][layer] if out.get("stack") else None
                if not c:
                    continue
                for a in c["alternatives"]:
                    self.assertIsNone(LOW_LEAD.search(a["why_not"]), (s.get("scenario_id"), layer, a["why_not"]))
                self.assertNotRegex(c.get("contrast", ""), r"\. With priorities\.\w+=[12][, ]", (s.get("scenario_id"), layer))

    def test_p1_cloudflare(self):
        out = P("P1")
        for a in out["stack"]["hosting"]["alternatives"]:
            self.assertNotIn("priorities.scalability=1,", a["why_not"])


class Item5NoLifecycleFact(unittest.TestCase):
    def test_kb_fact_skips_version_strength(self):
        from engine.recommend import kb_fact
        from engine.kb import TECH
        from engine.validate import validate
        sc = copy.deepcopy(PUBLIC["P2"])
        sc["requirements"].update({"full_text_search": False, "multi_tenant": False, "realtime": False})
        req, _, _ = validate(sc)
        ctx = cx.build(req)
        for layer in ("database", "backend", "frontend_mobile"):
            for item in TECH[layer]:
                f = kb_fact(item, ctx) or ""
                self.assertNotRegex(f, r"(?i)\bLTS\b|supported (?:to|until)|\bEOL\b|support ends|supported majors", item["id"])


class Item6WebOffline(unittest.TestCase):
    def test_web_and_mobile_offline_names_web_mechanism(self):
        for sid in ("P2", "P4"):
            out = P(sid, **{"requirements.offline_support": True})
            off = [s for s in out["stack"]["supporting"] if s["choice"].startswith("Offline-first sync")]
            self.assertEqual(len(off), 1, sid)
            self.assertRegex(off[0]["choice"] + off[0]["justification"], r"(?i)service worker|indexeddb", sid)


EA = "We sell to teams in Europe and Asia."


class Item7MultiRegion(unittest.TestCase):
    def _mr(self, out):
        return next(s for s in out["stack"]["supporting"] if s["choice"].startswith("Multi-region"))

    def test_host_region_reused_and_located(self):
        out = P("P3", **{"project.description": PUBLIC["P3"]["project"]["description"] + " " + EA,
                         "requirements.p95_latency_ms": 50, "infrastructure.cloud_preference": "aws"})
        self.assertIn("eu-central-1", out["stack"]["hosting"]["choice"])
        mr = self._mr(out)
        self.assertIn("eu-central-1", mr["choice"])
        self.assertNotIn("eu-west-1", mr["choice"])
        self.assertTrue(mr["data_bearing"])
        self.assertTrue(mr["data_location"])
        line = next(l for l in out["estimated_monthly_cost_usd"]["assumptions"] if "Multi-region" in l)
        self.assertRegex(line, r"ap-southeast-1[^$]*\$\d+-\d+")  # the extra region is costed by name
        # CloudFront alone does not route between regions: a latency-routing entry is named and costed
        self.assertTrue(any("Route 53" in s["choice"] for s in out["stack"]["supporting"]))

    def test_cloudflare_free_cdn_gets_routing(self):
        out = P("P2", **{"infrastructure.data_residency": "none", "compliance": [], "scale.geo_spread": "global",
                         "requirements.p95_latency_ms": 50})
        names = [s["choice"] for s in out["stack"]["supporting"]]
        if any(n.startswith("Cloudflare (free plan)") for n in names):
            lb = [s for s in out["stack"]["supporting"] if "Load Balancing" in s["choice"]]
            self.assertEqual(len(lb), 1, names)
            self.assertGreater(lb[0]["_cost"][0][1] if "_cost" in lb[0] else 1, 0)
            self.assertTrue(any("Load Balancing" in l for l in out["estimated_monthly_cost_usd"]["assumptions"]))


class Item8Continents(unittest.TestCase):
    def test_unit(self):
        self.assertEqual(cx.continents_in("Boards feature Asian and European art styles."), [])
        self.assertEqual(cx.continents_in(EA), ["europe", "asia"])
        self.assertEqual(cx.continents_in("Customers across the Americas."), ["north_america", "south_america"])
        self.assertEqual(cx.continents_in("Our office is in Europe. We serve users in Asia."), ["asia"])


class Item9ResidencyEnum(unittest.TestCase):
    def _w(self, sent):
        out = P("P3", **{"project.description": PUBLIC["P3"]["project"]["description"] + " " + sent,
                         "infrastructure.data_residency": "other", "compliance": []})
        return warn(out, "RESIDENCY_UNSPECIFIED")["message"]

    def test_enum_values_suggested(self):
        self.assertIn("data_residency 'eu'", self._w("Data must stay in Germany."))
        self.assertIn("data_residency 'india'", self._w("Data must stay in India."))
        self.assertIn("data_residency 'us'", self._w("Customer data must be stored in the US."))

    def test_unknown_country_named_unsupported(self):
        m = self._w("Customer data must stay in Nigeria.")
        self.assertIn("Nigeria", m)
        self.assertRegex(m, r"not (?:a |one of the )?(?:supported|in the knowledge base)")


class Item10ConflictLead(unittest.TestCase):
    def test_field_conflict(self):
        out = P("P3", **{"infrastructure.data_residency": "other", "infrastructure.residency_country": "japan", "compliance": [],
                         "project.description": PUBLIC["P3"]["project"]["description"] + " Customer data must stay in Australia."})
        m = warn(out, "RESIDENCY_UNSPECIFIED")["message"]
        self.assertNotIn("does not name a jurisdiction", m)
        self.assertTrue(m.startswith("data_residency 'other': infrastructure.residency_country"), m)

    def test_description_conflict(self):
        out = P("P3", **{"infrastructure.data_residency": "other", "compliance": [],
                         "project.description": PUBLIC["P3"]["project"]["description"] + " Customer data must stay in Australia. Backups must stay in Japan."})
        m = warn(out, "RESIDENCY_UNSPECIFIED")["message"]
        self.assertNotIn("does not name a jurisdiction", m)
        self.assertIn("conflicting", m)


class Item11StaticAvailability(unittest.TestCase):
    def test_static_no_second_instance_or_region_warning(self):
        for av in ("99.95", "99.99"):
            out = P("P1", **{"requirements.availability": av})
            lines = out["estimated_monthly_cost_usd"]["assumptions"]
            self.assertFalse(any("second app instance" in l for l in lines), av)
            w = warn(out, "AVAILABILITY_SINGLE_REGION")
            if w:
                self.assertEqual(w["severity"], "info")
                self.assertNotIn("add a second region", w["message"])
                self.assertIn("CDN", w["message"])


class Item12SelfHostedToolCost(unittest.TestCase):
    def test_same_app_service_plan(self):
        out = P("P3")
        line = next(l for l in out["estimated_monthly_cost_usd"]["assumptions"] if l.startswith("auth: Keycloak"))
        self.assertNotIn("smallest size", line)
        self.assertIn("$0-0", line)


class Item13NumberFormat(unittest.TestCase):
    def test_no_exponent(self):
        out = P("P2", **{"scale.data_volume_gb_12_months": 1_000_000, "budget.monthly_infra_usd": 2_000_000})
        self.assertNotRegex(dump(out), r"\de\+\d")
        self.assertIn("1,000,000 GB", dump(out))


class Item14SkillMatchedAlternative(unittest.TestCase):
    def test_rails_offered(self):
        out = P("P3", **{"team.languages": ["ruby"]})
        self.assertIn("SKILL_MISMATCH", codes(out))
        alts = [a["choice"] for a in out["stack"]["backend"]["alternatives"]]
        self.assertTrue(any("Rails" in a for a in alts), alts)


class Item15Wording(unittest.TestCase):
    def test_scan(self):
        for s in all_scenarios():
            out = evaluate(copy.deepcopy(s), counterfactuals=False)
            if not out.get("stack"):
                continue
            t = dump(out)
            sid = s.get("scenario_id")
            self.assertNotRegex(t, r"fits better: [^\"]*; it fits better", sid)
            self.assertNotRegex(t, r"(?i)existing existing", sid)
            self.assertNotRegex(t, r"\.\)", sid)
            if out["stack"]["hosting"]["deployment"] in ("on_premise", "self_hosted") or s["infrastructure"].get("deployment_model") in ("on_premise", "air_gapped"):
                for layer in ("hosting", "database"):
                    self.assertNotIn("free plan", out["stack"][layer]["justification"], (sid, layer))

    def test_skill_mismatch_message(self):
        out = P("P3", **{"team.languages": ["ruby"]})
        m = warn(out, "SKILL_MISMATCH")["message"]
        self.assertNotIn(".)", m)


if __name__ == "__main__":
    unittest.main()
