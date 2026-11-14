"""L1 (blind10 re-grade): OFFLINE_REALTIME_MERGE fires only when offline_support and realtime are both on (input-driven), for different project types."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "L1", "project": {"type": "web_app", "platforms": ["web"], "description": "x"},
        "scale": {"users_at_launch": 800, "users_12_months": 6000, "peak_concurrent_users": 150},
        "team": {"size": 3, "experience": "intermediate", "languages": ["typescript"], "has_devops": False},
        "budget": {"monthly_infra_usd": 600}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password", "realtime": False, "full_text_search": False, "offline_support": False, "ml_features": "none",
                         "payments": False}}


def run(typ, plats, desc, req):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, platforms=list(plats), description=desc)
    s["requirements"].update(req)
    return evaluate(s, counterfactuals=False)


def merge(out):
    return next((w for w in out["warnings"] if w["code"] == "OFFLINE_REALTIME_MERGE"), None)


BOTH = {"offline_support": True, "realtime": True}


class OfflineRealtimeMerge(unittest.TestCase):
    def test_fires_for_different_project_types(self):
        cases = (("realtime_collab", ("web", "desktop"), "Collaborative notes editor for teams."),
                 ("social", ("android", "ios"), "Field technicians update job tickets in basements and see dispatch changes live."),
                 ("internal_tool", ("web",), "Warehouse stock counts entered on tablets, visible to the office live."),
                 ("marketplace", ("web", "android"), "Delivery riders accept orders offline-tolerant while the dashboard updates live."))
        for typ, plats, desc in cases:
            with self.subTest(typ=typ):
                out = run(typ, plats, desc, BOTH)
                w = merge(out)
                self.assertIsNotNone(w)
                self.assertEqual(w["severity"], "warning")
                self.assertEqual(w["fields"], ["requirements.offline_support", "requirements.realtime"])
                for word in ("last-write-wins", "server-authoritative", "CRDT", "tested"):
                    self.assertIn(word, w["message"])
                self.assertEqual(out["status"], "ok_with_warnings")

    def test_does_not_fire_with_only_one_flag(self):
        for req in ({"offline_support": True}, {"realtime": True}, {}):
            with self.subTest(req=req):
                self.assertIsNone(merge(run("web_app", ("web",), "Collaborative notes editor for teams.", req)))


if __name__ == "__main__":
    unittest.main()
