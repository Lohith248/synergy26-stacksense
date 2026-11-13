"""D13 right-sizing gates (engine/rightsize.py): synthetic scenarios only, no scenario ids or product-specific titles.
Each gate: positive, negative, boundary, and the note that explains a service that was not added."""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import context as cx  # noqa: E402
from engine import rightsize as rs  # noqa: E402
from engine.validate import validate  # noqa: E402
from test_round9 import S, codes, dump, run, sup  # noqa: E402


def ctx_of(**kw):
    req, errors, _ = validate(S(**kw))
    assert not errors, errors
    return cx.build(req)


def game(desc="", p95=None, realtime=True, **kw):
    kw.update({"project.type": "gaming", "requirements.realtime": realtime, "project.description": desc})
    if p95 is not None:
        kw["requirements.p95_latency_ms"] = p95
    return kw


def notes(out, text=""):
    return [w for w in out["warnings"] if w["code"] == "SERVICE_NOT_ADDED" and text in w["message"]]


class PredicateUnits(unittest.TestCase):
    def test_turn_based_and_fast_action_signals(self):
        for text, tb, fa in [("A turn-based card game", True, False), ("fast-paced arena shooter", False, True),
                             ("a word game where each player takes a turn", True, False),
                             ("This is not a turn-based game; it is a real-time shooter.", False, True),
                             ("", False, False), ("plain multiplayer lobby", False, False)]:
            c = ctx_of(**game(text))
            self.assertEqual((c["desc"]["turn_based"], c["desc"]["fast_action"]), (tb, fa), text)

    def test_game_servers_boundaries(self):
        self.assertTrue(rs.game_servers(ctx_of(**game(p95=60)))[0])
        self.assertTrue(rs.game_servers(ctx_of(**game(p95=100)))[0])      # boundary: at the threshold
        self.assertFalse(rs.game_servers(ctx_of(**game(p95=101)))[0])
        self.assertFalse(rs.game_servers(ctx_of(**game()))[0])             # no evidence at all
        self.assertFalse(rs.game_servers(ctx_of(**game("turn-based", p95=60)))[0])   # turn-based beats a number
        self.assertTrue(rs.game_servers(ctx_of(**game("fast-paced arena shooter")))[0])
        fact = rs.game_servers(ctx_of(**game(p95=150)))[1]
        self.assertIn("150", fact)
        self.assertIn("100 ms", fact)

    def test_warehouse_boundaries(self):
        def wh(gb, typ="data_analytics", **kw):
            kw = dict(kw, **{"project.type": typ})
            if gb is not None:
                kw["scale.data_volume_gb_12_months"] = gb
            return rs.warehouse(ctx_of(**kw))
        self.assertFalse(wh(99)[0])
        self.assertTrue(wh(100)[0])
        self.assertFalse(wh(None)[0])
        self.assertIn("not given", wh(None)[1])
        self.assertIn("99", wh(99)[1])
        d = {"project.description": "Dashboards and reports for analysts", "scale.workload": "read_heavy"}
        self.assertFalse(wh(199, "web_app", **d)[0])
        self.assertTrue(wh(200, "web_app", **d)[0])

    def test_public_facing(self):
        def pf(typ, **kw):
            return rs.public_facing(ctx_of(**dict(kw, **{"project.type": typ})))
        self.assertTrue(pf("web_app")[0])
        self.assertFalse(pf("internal_tool")[0])
        self.assertTrue(pf("internal_tool", **{"requirements.seo_critical": True})[0])
        self.assertTrue(pf("internal_tool", **{"scale.geo_spread": "global"})[0])
        self.assertFalse(pf("web_app", **{"project.description": "Used only by employees."})[0])

    def test_crdt(self):
        def cr(desc, typ="realtime_collab"):
            return rs.crdt(ctx_of(**{"project.type": typ, "project.description": desc}))[0]
        self.assertTrue(cr("Teams edit the same document at once"))
        self.assertTrue(cr("conflict-free merging of shared notes"))
        self.assertFalse(cr("Shared kanban boards with live card moves"))
        self.assertFalse(cr(""))
        self.assertFalse(cr("no co-editing; one author per page"))
        self.assertFalse(cr("multiplayer lobby", "gaming"))


def game_lines(out):
    return [s for s in sup(out, "realtime") if "game servers" in s["choice"]]


class G1GameServers(unittest.TestCase):
    def test_low_latency_gets_servers_on_each_cloud(self):
        for cloud, word in [("aws", "GameLift"), ("azure", "PlayFab"), ("gcp", "Agones")]:
            out = run(**game(p95=60, **{"infrastructure.cloud_preference": cloud}))
            self.assertTrue(any(word in s["choice"] for s in game_lines(out)), (cloud, dump(out)))
            self.assertFalse(notes(out, "game servers"))

    def test_fast_genre_without_p95_gets_servers(self):
        out = run(**game("A fast-paced arena shooter for friends"))
        self.assertEqual(len(game_lines(out)), 1)

    def test_turn_based_gets_native_realtime_alternative_and_note(self):
        out = run(**game("Turn-based card game, a move every few seconds", **{"scale.users_12_months": 8000}))
        self.assertEqual(game_lines(out), [])
        rt = sup(out, "realtime")
        self.assertEqual(len(rt), 1)
        self.assertIn("requirements.p95_latency_ms", rt[0]["driven_by"])
        self.assertTrue(any("server" in a["why_not"] and "turn-based" in a["why_not"] for a in rt[0]["alternatives"]))
        n = notes(out, "game servers")
        self.assertEqual(len(n), 1)
        self.assertIn("turn-based", n[0]["message"])
        self.assertEqual(n[0]["severity"], "info")
        self.assertNotIn("dedicated game servers", dump(out).lower())

    def test_latency_boundary_and_turn_based_beats_number(self):
        self.assertEqual(len(game_lines(run(**game(p95=100)))), 1)
        out = run(**game(p95=101))
        self.assertEqual(game_lines(out), [])
        self.assertIn("101", notes(out, "game servers")[0]["message"])
        self.assertEqual(game_lines(run(**game("A turn-based board game", p95=60))), [])

    def test_realtime_off_or_other_type_adds_nothing(self):
        out = run(**game("Turn-based card game", realtime=False))
        self.assertEqual(sup(out, "realtime"), [])
        self.assertFalse(notes(out))
        self.assertEqual(game_lines(run(**{"project.type": "web_app", "requirements.realtime": True, "requirements.p95_latency_ms": 60})), [])

    def test_negated_turn_based_is_a_shooter(self):
        out = run(**game("This is not a turn-based game; it is a real-time shooter."))
        self.assertEqual(len(game_lines(out)), 1)

    def test_core_layers_unchanged_by_the_gate(self):
        a, b = run(**game("Turn-based card game")), run(**game("Fast-paced shooter"))
        for layer in ("frontend", "backend", "database", "hosting"):
            self.assertEqual(a["stack"][layer]["choice"], b["stack"][layer]["choice"])

    def test_cost_drops_when_servers_are_not_needed(self):
        kw = {"infrastructure.cloud_preference": "azure", "budget.monthly_infra_usd": 40}
        slow, fast = run(**game("Turn-based card game", **kw)), run(**game(p95=60, **kw))
        self.assertLess(slow["estimated_monthly_cost_usd"]["min"], fast["estimated_monthly_cost_usd"]["min"])


def wh_lines(out):
    return [s for s in sup(out, "other") if s["choice"].startswith("Analytics warehouse")]


def bi_line(out):
    return next(s for s in sup(out, "other") if s["choice"].startswith("BI dashboards"))


def analytics(gb=None, **kw):
    kw["project.type"] = "data_analytics"
    if gb is not None:
        kw["scale.data_volume_gb_12_months"] = gb
    return run(**kw)


class G2Warehouse(unittest.TestCase):
    def test_100_gb_keeps_warehouse_and_bi(self):
        out = analytics(100)
        self.assertEqual(len(wh_lines(out)), 1)
        self.assertNotIn("application database", bi_line(out)["justification"])
        self.assertFalse(notes(out, "warehouse"))

    def test_99_gb_runs_reports_on_the_application_database(self):
        out = analytics(99)
        self.assertEqual(wh_lines(out), [])
        bi = bi_line(out)
        self.assertEqual(bi["choice"], "BI dashboards: Metabase (open-source edition, self-hosted container)")
        self.assertIn("application database", bi["justification"])
        self.assertIn("scale.data_volume_gb_12_months", bi["driven_by"])
        alt = next(a for a in bi["alternatives"] if a["choice"].startswith("Analytics warehouse"))
        self.assertIn("100 GB", alt["why_not"])
        n = notes(out, "warehouse")
        self.assertEqual(len(n), 1)
        self.assertIn("99", n[0]["message"])
        self.assertEqual(n[0]["fields"], ["project.type", "scale.data_volume_gb_12_months"])

    def test_missing_volume_says_not_given(self):
        out = analytics(None)
        self.assertEqual(wh_lines(out), [])
        self.assertIn("not given", notes(out, "warehouse")[0]["message"])

    def test_description_path_boundary_is_200(self):
        d = {"project.type": "web_app", "project.description": "Analysts run reports and dashboards", "scale.workload": "read_heavy"}
        self.assertEqual(wh_lines(run(**d, **{"scale.data_volume_gb_12_months": 199})), [])
        self.assertFalse(notes(run(**d, **{"scale.data_volume_gb_12_months": 199})))  # old precondition did not hold: no note
        self.assertEqual(len(wh_lines(run(**d, **{"scale.data_volume_gb_12_months": 200}))), 1)

    def test_azure_small_volume_drops_the_warehouse_floor(self):
        kw = {"infrastructure.cloud_preference": "azure"}
        small, big = analytics(10, **kw), analytics(100, **kw)
        drop = big["estimated_monthly_cost_usd"]["min"] - small["estimated_monthly_cost_usd"]["min"]
        self.assertGreaterEqual(drop, 263)


def rt(out):
    return sup(out, "realtime")


def collab_app(desc, **kw):
    return run(**{"project.type": "realtime_collab", "requirements.realtime": True, "project.description": desc,
                  "team.languages": ["php"], **kw})


class G4Crdt(unittest.TestCase):
    def test_co_editing_description_gets_crdt(self):
        out = collab_app("Teams edit the same document at once and see each other's cursors")
        self.assertEqual(len(rt(out)), 1)
        self.assertIn("Yjs", rt(out)[0]["choice"])
        self.assertFalse(notes(out, "CRDT"))

    def test_conflict_free_offline_notes_keep_crdt_everywhere(self):
        out = collab_app("Shared notes with conflict-free merging after reconnecting", **{"requirements.offline_support": True})
        self.assertIn("Yjs", rt(out)[0]["choice"])
        off = next(s for s in sup(out, "other") if s["choice"].startswith("Offline-first sync"))
        self.assertIn("CRDT", off["justification"])

    def test_discrete_events_use_native_realtime_with_note(self):
        out = collab_app("Shared kanban boards with live card moves")
        self.assertEqual(len(rt(out)), 1)
        self.assertEqual(rt(out)[0]["choice"], "Laravel Reverb")
        self.assertTrue(any(a["choice"].startswith("Yjs CRDT") for a in rt(out)[0]["alternatives"]))
        n = notes(out, "CRDT")
        self.assertEqual(len(n), 1)
        self.assertIn("realtime_collab", n[0]["message"])
        self.assertEqual(n[0]["severity"], "info")

    def test_empty_and_negated_descriptions_are_native(self):
        for desc in ("", "No co-editing: one author per page, readers see live updates"):
            out = collab_app(desc)
            self.assertNotIn("Yjs", rt(out)[0]["choice"], desc)
            self.assertEqual(len(notes(out, "CRDT")), 1, desc)

    def test_gaming_multiplayer_is_never_crdt(self):
        out = run(**game("Multiplayer shooter with live cursors", p95=60))
        self.assertFalse(any("Yjs" in s["choice"] for s in sup(out, "realtime")))
        self.assertFalse(notes(out, "CRDT"))

    def test_other_types_without_collab_words_are_unchanged(self):
        out = run(**{"project.type": "web_app", "requirements.realtime": True, "project.description": "Live order status"})
        self.assertFalse(notes(out, "CRDT"))


def cdn(out):
    return sup(out, "cdn")


def web(typ, **kw):
    return run(**{"project.type": typ, "scale.users_12_months": 20000, "scale.peak_concurrent_users": 1500, **kw})


class G3CdnAudience(unittest.TestCase):
    def test_tier_is_at_least_1(self):
        self.assertGreaterEqual(ctx_of(**{"scale.users_12_months": 20000, "scale.peak_concurrent_users": 1500})["tier"], 1)

    def test_public_app_gets_cdn(self):
        out = web("web_app")
        self.assertEqual(len(cdn(out)), 1)
        self.assertFalse(notes(out, "CDN"))

    def test_internal_tool_with_seo_or_global_users_gets_cdn(self):
        self.assertEqual(len(cdn(web("internal_tool", **{"requirements.seo_critical": True}))), 1)
        self.assertGreaterEqual(len(cdn(web("internal_tool", **{"scale.geo_spread": "global"}))), 1)

    def test_internal_tool_without_audience_evidence_has_no_cdn_and_a_note(self):
        for desc in ("", "Used only by employees."):
            out = web("internal_tool", **{"project.description": desc})
            self.assertEqual(cdn(out), [], desc)
            n = notes(out, "CDN")
            self.assertEqual(len(n), 1, desc)
            self.assertIn("internal_tool", n[0]["message"])
            self.assertEqual(n[0]["severity"], "info")
            if desc:
                self.assertIn("only by employees", n[0]["message"])

    def test_employees_only_blocks_cdn_for_any_type(self):
        out = web("web_app", **{"project.description": "Used only by employees."})
        self.assertEqual(cdn(out), [])
        self.assertEqual(len(notes(out, "CDN")), 1)

    def test_tier_0_internal_tool_has_no_cdn_and_no_note(self):
        out = run(**{"project.type": "internal_tool"})
        self.assertEqual(cdn(out), [])
        self.assertFalse(notes(out, "CDN"))

    def test_cdn_cost_line_removed_with_the_cdn(self):
        a, b = web("web_app"), web("internal_tool")
        self.assertLess(b["estimated_monthly_cost_usd"]["max"], a["estimated_monthly_cost_usd"]["max"])


def search_app(users):
    return run(**{"project.type": "marketplace", "project.description": "Students buy and sell used books, search by course code.",
                  "budget.monthly_infra_usd": 0, "team.experience": "beginner", "team.size": 3, "team.has_devops": False,
                  "team.languages": ["javascript", "python"], "requirements.full_text_search": True,
                  "scale.users_at_launch": 200, "scale.peak_concurrent_users": 100, "scale.users_12_months": users})


class G5NativeSearch(unittest.TestCase):
    def test_supabase_uses_postgresql_full_text_search(self):
        out = search_app(5000)
        self.assertIn("Supabase", out["stack"]["database"]["choice"])
        s = sup(out, "search")
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]["choice"].startswith("PostgreSQL full-text search"))
        self.assertTrue(any("Meilisearch" in a["choice"] for a in s[0]["alternatives"]))

    def test_tier_rule_boundary_is_unchanged(self):
        self.assertTrue(sup(search_app(50000), "search")[0]["choice"].startswith("PostgreSQL full-text search"))
        self.assertFalse(sup(search_app(50001), "search")[0]["choice"].startswith("PostgreSQL full-text search"))


if __name__ == "__main__":
    unittest.main()
