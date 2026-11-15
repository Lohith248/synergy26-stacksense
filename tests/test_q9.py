"""q9: cloud_preference 'none' with NO deployment_model in the file. The documented default (managed_cloud) would contradict the
one thing the input states, so the default becomes on_premise and the assumption says so. An explicit contradiction is unchanged.
Synthetic inputs only."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.run import evaluate  # noqa: E402
from test_round9 import BASE, codes  # noqa: E402

NOTE = "cloud_preference 'none' rules out public cloud"


def scenario(typ, desc, cloud="none", deployment="ABSENT", **req):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, description=desc)
    s["infrastructure"]["cloud_preference"] = cloud
    if deployment == "ABSENT":
        del s["infrastructure"]["deployment_model"]
    else:
        s["infrastructure"]["deployment_model"] = deployment
    s["requirements"].update(req)
    return s


class NoCloudWithoutDeploymentModel(unittest.TestCase):
    CASES = (("internal_tool", "Leave requests and approvals for a 400-person factory."),
             ("ecommerce", "A regional grocery chain sells online and delivers from its own shops."),
             ("iot", "Sensors on 40 pumps report pressure every minute to the plant control room."),
             ("data_analytics", "Monthly sales dashboards for the finance team."))

    def test_stack_is_built_on_own_infrastructure(self):
        for typ, desc in self.CASES:
            out = evaluate(scenario(typ, desc), counterfactuals=False)
            self.assertIn(out["status"], ("ok", "ok_with_warnings"), (typ, codes(out)))
            self.assertIsNotNone(out["stack"], typ)
            self.assertNotIn("CLOUD_NONE_VS_CLOUD_DEPLOYMENT", codes(out), typ)
            self.assertIn("On-premises", out["stack"]["hosting"]["choice"], typ)
            notes = [a for a in out["assumptions"] if NOTE in a]
            self.assertEqual(len(notes), 1, (typ, out["assumptions"]))
            self.assertIn("infrastructure.deployment_model absent", notes[0])
            self.assertIn("'on_premise'", notes[0])
            self.assertFalse(any("default 'managed_cloud' applied" in a for a in out["assumptions"]), typ)

    def test_null_deployment_model_is_absent(self):
        s = scenario("web_app", "A members' directory for a housing society.")
        s["infrastructure"]["deployment_model"] = None
        out = evaluate(s, counterfactuals=False)
        self.assertIsNotNone(out["stack"])
        self.assertIn("On-premises", out["stack"]["hosting"]["choice"])
        self.assertTrue(any(NOTE in a and "null" in a for a in out["assumptions"]), out["assumptions"])

    def test_same_stack_as_an_explicit_on_premise_file(self):
        typ, desc = self.CASES[0]
        a = evaluate(scenario(typ, desc), counterfactuals=False)
        b = evaluate(scenario(typ, desc, deployment="on_premise"), counterfactuals=False)
        for layer in ("frontend", "backend", "database", "hosting"):
            self.assertEqual(a["stack"][layer]["choice"], b["stack"][layer]["choice"], layer)
        self.assertEqual(a["estimated_monthly_cost_usd"]["min"], b["estimated_monthly_cost_usd"]["min"])


class MustNotFire(unittest.TestCase):
    def test_explicit_contradiction_is_still_infeasible(self):
        for dep in ("managed_cloud", "self_hosted_cloud_vm"):
            out = evaluate(scenario("web_app", "A booking page.", deployment=dep), counterfactuals=False)
            self.assertEqual(out["status"], "infeasible", dep)
            self.assertIn("CLOUD_NONE_VS_CLOUD_DEPLOYMENT", codes(out), dep)
            self.assertFalse(any(NOTE in a for a in out["assumptions"]), dep)

    def test_other_cloud_preferences_keep_the_documented_default(self):
        for cloud in ("any", "aws", "gcp", "azure"):
            out = evaluate(scenario("web_app", "A booking page.", cloud=cloud), counterfactuals=False)
            self.assertIsNotNone(out["stack"], cloud)
            self.assertNotIn("On-premises", out["stack"]["hosting"]["choice"], cloud)
            self.assertTrue(any("infrastructure.deployment_model absent: default 'managed_cloud' applied" in a for a in out["assumptions"]),
                            (cloud, out["assumptions"]))
            self.assertFalse(any(NOTE in a for a in out["assumptions"]), cloud)

    def test_absent_cloud_preference_keeps_both_defaults(self):
        s = scenario("web_app", "A booking page.", cloud="any")
        del s["infrastructure"]["cloud_preference"]
        out = evaluate(s, counterfactuals=False)
        self.assertNotIn("On-premises", out["stack"]["hosting"]["choice"])
        self.assertFalse(any(NOTE in a for a in out["assumptions"]))

    def test_explicit_on_premise_and_air_gapped_have_no_note(self):
        for dep in ("on_premise", "air_gapped"):
            out = evaluate(scenario("internal_tool", "An asset register.", deployment=dep), counterfactuals=False)
            self.assertFalse(any(NOTE in a for a in out["assumptions"]), dep)


if __name__ == "__main__":
    unittest.main()
