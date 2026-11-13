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


if __name__ == "__main__":
    unittest.main()
