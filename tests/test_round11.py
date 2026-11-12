"""Round 11 (12 Nov session, judge round 4 batch A): F1, F2, F3, F6, F8, F10, F17.
Each test written before the change. Blind inputs are read from ../research when present."""
import copy
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_round9 import PUBLIC, S, codes, dump, run, sup  # noqa: E402

RESEARCH = os.path.join(os.path.dirname(ROOT), "research")


def blind(name):
    """A blind scenario by id prefix (e.g. 'B03'), or skip when the research folder is absent."""
    for folder in ("blind3", "blind4"):
        d = os.path.join(RESEARCH, folder)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.startswith(name + "_") and f.endswith(".json"):
                    with open(os.path.join(d, f), encoding="utf-8") as fh:
                        return json.load(fh)
    raise unittest.SkipTest(f"blind scenario {name} not available")


def ev(s):
    return evaluate(copy.deepcopy(s), counterfactuals=False)


def kb(out, layer):
    return out["stack"][layer].get("kb_id", "")


class F1PrimaryServerLanguage(unittest.TestCase):
    def test_rails_shop_gets_rails(self):
        self.assertEqual(kb(ev(blind("B03")), "backend"), "ruby-rails")

    def test_elixir_team_gets_phoenix(self):
        self.assertEqual(kb(ev(blind("B10")), "backend"), "elixir-phoenix")

    def test_no_one_language_bonus_when_a_server_language_fits(self):
        # Ruby + JavaScript team that names Ruby as its own: JS must not be rewarded twice ("one language across clients
        # and server"). Narrowed from the judge's wording (any listed server language): that version flips P2 (js, ts,
        # python; NestJS 0.8 ahead of Django), which the batch brief forbids; see the round-11 report.
        out = run(**{"team.languages": ["ruby", "javascript"], "project.platforms": ["web", "android"],
                     "project.description": "Shop admin and storefront. We are a Rails shop."})
        self.assertNotIn("one language (TypeScript/JavaScript) across clients and server", dump(out))
        self.assertIn("Rails", out["stack"]["backend"]["choice"])

    def test_one_language_bonus_kept_for_js_only_team(self):
        from engine import context as cx, select as sl
        from engine.validate import validate
        req, _, _ = validate(S(**{"team.languages": ["typescript"]}))
        ctx = cx.build(req)
        ctx["ui_needs_js"] = True
        nest = next(c for c in sl.backend_candidates(ctx, None) if c.id == "node-nestjs")
        self.assertGreater(nest.term("one_language"), 0)

    def test_description_names_primary_language(self):
        for desc, want in (("Booking tool. Our Django team builds it.", "python"),
                           ("Shop for spare parts; the team writes Elixir.", "elixir"),
                           ("We are a Rails shop building a CRM.", "ruby")):
            from engine import context as cx
            from engine.validate import validate
            req, _, _ = validate(S(**{"project.description": desc, "team.languages": [want, "typescript"]}))
            self.assertIn(want, cx.build(req)["primary_langs"], desc)

    def test_primary_language_gets_small_bonus(self):
        out = run(**{"team.languages": ["python", "typescript"],
                     "project.description": "Internal booking system; our Django team builds and runs it."})
        be = out["stack"]["backend"]
        self.assertIn("python", " ".join(be["choice"].lower().split()))
        self.assertIn("project.description", be["driven_by"])

    def test_public_backends_unchanged(self):
        want = {"P2": "node-nestjs", "P3": "go-chi", "P4": "java-spring", "P5": "dotnet-aspnet", "P6": "python-django"}
        for sid, bid in want.items():
            self.assertEqual(kb(ev(PUBLIC[sid]), "backend"), bid, sid)


class F2VendorLocation(unittest.TestCase):
    def test_us_gateway_with_us_residency_has_no_location_warning(self):
        out = run(**{"requirements.payments": True, "infrastructure.data_residency": "us"})
        self.assertNotIn("PAYMENT_DATA_LOCATION", codes(out))
        pay = sup(out, "payments")[0]
        self.assertEqual(pay["data_location"], "us")
        self.assertFalse(any(w["code"] == "RESIDENCY_UNVERIFIED_SERVICE" and "Stripe" in w["message"] for w in out["warnings"]))

    def test_eu_residency_still_critical(self):
        out = run(**{"requirements.payments": True, "infrastructure.data_residency": "eu", "compliance": ["gdpr"]})
        self.assertEqual(next(w["severity"] for w in out["warnings"] if w["code"] == "PAYMENT_DATA_LOCATION"), "critical")

    def test_llm_region_in_kb_needs_no_check(self):
        out = ev(blind("C10"))
        self.assertNotIn("LLM_REGION_CHECK", codes(out))
        ml = sup(out, "ml")[0]
        self.assertIn("East US", ml["choice"])

    def test_llm_region_unknown_stays_critical(self):
        out = run(**{"requirements.ml_features": "llm_rag", "infrastructure.data_residency": "india",
                     "infrastructure.cloud_preference": "gcp"})
        self.assertEqual(next(w["severity"] for w in out["warnings"] if w["code"] == "LLM_REGION_CHECK"), "critical")


class F3OfflineAndCollabFollowStack(unittest.TestCase):
    def test_ios_native_offline_is_not_a_service_worker(self):
        out = run(**{"project.platforms": ["ios"], "team.languages": ["swift"], "requirements.offline_support": True})
        self.assertIn("swift", kb(out, "frontend"))
        other = " ".join(s["choice"] for s in sup(out, "other"))
        self.assertNotIn("Workbox", other)
        self.assertNotIn("Service worker", other)
        self.assertIn("SwiftData", other)

    def test_android_native_offline_is_room_workmanager(self):
        out = run(**{"project.platforms": ["android"], "team.languages": ["kotlin"], "requirements.offline_support": True})
        other = " ".join(s["choice"] for s in sup(out, "other"))
        self.assertIn("Room", other)
        self.assertIn("WorkManager", other)

    def test_web_offline_is_service_worker(self):
        out = run(**{"requirements.offline_support": True})
        self.assertIn("Service worker + IndexedDB", " ".join(s["choice"] for s in sup(out, "other")))

    def test_crdt_and_last_writer_wins_never_together(self):
        out = run(**{"project.type": "realtime_collab", "requirements.realtime": True, "requirements.offline_support": True,
                     "project.description": "Many users edit the same board at once."})
        self.assertIn("CRDT", " ".join(s["choice"] for s in sup(out, "realtime")))
        self.assertNotIn("last-writer-wins", dump(out).lower())

    def test_collab_server_in_backend_language(self):
        for langs, bid, want in ((["python"], "python", "pycrdt"), (["elixir"], "phoenix", "Phoenix Channels")):
            out = run(**{"project.type": "realtime_collab", "requirements.realtime": True, "team.languages": langs,
                         "team.experience": "senior", "project.description": "Many users edit the same board at once."})
            self.assertIn(bid, kb(out, "backend"))
            rt = sup(out, "realtime")[0]
            self.assertIn(want, rt["choice"])
            self.assertNotIn("Hocuspocus", rt["choice"])

    def test_hocuspocus_beside_non_node_backend_is_costed(self):
        out = ev(PUBLIC["P3"])
        self.assertEqual(kb(out, "backend"), "go-chi")
        rt = sup(out, "realtime")[0]
        self.assertIn("Hocuspocus", rt["choice"])
        self.assertTrue(any("Node" in t for t in rt["tradeoffs"]), rt["tradeoffs"])
        self.assertTrue(any("Hocuspocus" in a for a in out["estimated_monthly_cost_usd"]["assumptions"]))


class F6HostingFacts(unittest.TestCase):
    def test_kb_multi_zone_flag(self):
        from engine.kb import TECH
        rows = {h["id"]: h for h in TECH["hosting"]}
        for h in rows.values():
            if h["kind"] not in ("static", "onprem"):
                self.assertIn("multi_zone", h, h["id"])
        self.assertFalse(rows["digitalocean-droplet"]["multi_zone"])
        self.assertTrue(rows["aws-ecs-fargate"]["multi_zone"])

    def test_droplet_never_across_zones(self):
        out = ev(blind("B10"))
        self.assertNotIn("runs across availability zones", out["stack"]["hosting"]["justification"])
        s = S(**{"infrastructure.deployment_model": "self_hosted_cloud_vm", "requirements.availability": "99.95"})
        out = ev(s)
        self.assertNotIn("runs across availability zones", out["stack"]["hosting"]["justification"])

    def test_no_servers_to_patch_only_when_provider_patches_os(self):
        from engine.kb import TECH
        rows = {h["id"]: h for h in TECH["hosting"]}
        for name in ("B05", "C03", "C07"):
            out = ev(blind(name))
            hid = kb(out, "hosting")
            j = out["stack"]["hosting"]["justification"]
            if rows[hid].get("host_os") == "customer":
                self.assertNotIn("no servers to patch", j, name)
        out = ev(PUBLIC["P5"])
        self.assertIn("no servers to patch", out["stack"]["hosting"]["justification"])


class F8ReactNativeClaim(unittest.TestCase):
    def test_react_mobile_only_with_react_native(self):
        for s in (blind("B12"), PUBLIC["P4"]):
            out = ev(s)
            fe = out["stack"]["frontend"]
            if "React Native" not in fe["choice"]:
                self.assertNotIn("React Native mobile app", fe["justification"], fe["choice"])


def _all_inputs():
    items = [PUBLIC[k] for k in sorted(PUBLIC)]
    for folder in ("blind3", "blind4"):
        d = os.path.join(RESEARCH, folder)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".json"):
                    with open(os.path.join(d, f), encoding="utf-8") as fh:
                        items.append(json.load(fh))
    return items


class F10Justifications(unittest.TestCase):
    def test_low_priorities_never_cited_and_each_layer_has_a_fact(self):
        for s in _all_inputs():
            out = ev(s)
            if not out.get("stack"):
                continue
            for layer in ("frontend", "backend", "database", "hosting"):
                j = out["stack"][layer]["justification"]
                self.assertIsNone(re.search(r"\(priority [12]/5\)", j), (s["scenario_id"], layer, j))
                if out["stack"][layer]["choice"] == "None":
                    continue
                clauses = [c for c in re.split(r"[;.]\s+|\s—\s", j) if c.strip()]
                self.assertTrue(any("(priority" not in c for c in clauses), (s["scenario_id"], layer, j))


class F17TemplateSlips(unittest.TestCase):
    def test_runtime_named_correctly(self):
        out = run(**{"team.languages": ["csharp"], "infrastructure.cloud_preference": "aws"})
        self.assertNotIn("JVM/.NET", dump(out))

    def test_no_new_language_text_without_team_languages(self):
        out = run(**{"team.languages": []})
        self.assertNotIn("new language for the team", dump(out))
        from engine import context as cx, select as sl
        from engine.validate import validate
        req, _, _ = validate(S(**{"team.languages": []}))
        ctx = cx.build(req)
        ctx["ui_needs_js"] = True
        texts = [t[3] for c in sl.backend_candidates(ctx, None) for t in c.terms]
        self.assertFalse(any("new language for the team" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
