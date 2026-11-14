"""N1: one cost rule for extra self-run processes (Keycloak, Hocuspocus); driven_by never lists a neutral field; Entra data-location note."""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

with open(os.path.join(ROOT, "scenarios", "stacksense_public_scenarios.json"), encoding="utf8") as _f:
    _SC = json.load(_f)
_SC = _SC if isinstance(_SC, list) else _SC["scenarios"]
P3 = next(s for s in _SC if "P3" in s["scenario_id"])
P5 = next(s for s in _SC if "P5" in s["scenario_id"])
ENTRA_URL = "https://learn.microsoft.com/en-us/entra/fundamentals/data-residency"


def run(base, cloud=None, res=None, comp=None, desc=None, **req):
    s = copy.deepcopy(base)
    if cloud:
        s["infrastructure"]["cloud_preference"] = cloud
    if res:
        s["infrastructure"]["data_residency"] = res
    if comp is not None:
        s["compliance"] = comp
    if desc:
        s["project"]["description"] += " " + desc
    s["requirements"].update(req)
    return evaluate(s, counterfactuals=False)


def sup(out, layer):
    return [x for x in out["stack"]["supporting"] if x["layer"] == layer]


def cost_lines(out):
    return out["estimated_monthly_cost_usd"]["assumptions"]


class ExtraProcessCost(unittest.TestCase):
    def test_plan_host_both_on_the_plan(self):
        for cloud in ("azure", "any"):
            ls = [a for a in cost_lines(run(P3, cloud)) if a.startswith(("auth:", "realtime:"))]
            self.assertEqual(len(ls), 2, ls)
            for a in ls:
                self.assertIn("same Azure App Service", a)
                self.assertIn("$0/month extra", a)

    def test_planless_host_both_one_entry_instance(self):
        out = run(P3, "gcp")
        ls = [a for a in cost_lines(out) if a.startswith(("auth:", "realtime:"))]
        self.assertEqual(len(ls), 2, ls)
        self.assertTrue(all("entry" in a for a in ls), ls)
        self.assertTrue(all("$0-10/month" in a for a in ls), ls)  # one figure for both (Cloud Run entry tier)

    def test_rule_stated_once(self):
        for cloud in ("azure", "gcp"):
            rule = [a for a in cost_lines(run(P3, cloud)) if a.startswith("Extra self-run processes")]
            self.assertEqual(len(rule), 1)
            self.assertIn("Hocuspocus", rule[0])
            self.assertIn("Keycloak", rule[0])

    def test_must_not_fire_without_extra_processes(self):
        out = run(P3, "azure", realtime=False)  # Keycloak remains, Hocuspocus is gone
        rule = [a for a in cost_lines(out) if a.startswith("Extra self-run")]
        self.assertTrue(rule and "Hocuspocus" not in rule[0] and "Keycloak" in rule[0])
        out = run(P5)  # managed identity, no extra process
        self.assertFalse([a for a in cost_lines(out) if a.startswith("Extra self-run")])


class DrivenByNeutral(unittest.TestCase):
    def all_driven(self, out):
        return [(x["layer"], f) for x in out["stack"]["supporting"] for f in x["driven_by"]]

    def test_none_residency_not_cited_for_description_pin(self):
        for desc in ("Customer data must stay in Germany.", "Data residency: all customer data must be stored in India."):
            out = run(P3, comp=[], desc=desc)
            self.assertNotIn(("payments", "infrastructure.data_residency"), self.all_driven(out))
            self.assertNotIn(("storage", "infrastructure.data_residency"), self.all_driven(out))
            self.assertIn("project.description", sup(out, "payments")[0]["driven_by"])

    def test_none_residency_not_cited_with_gdpr_or_no_constraint(self):
        for comp in (["gdpr"], []):
            out = run(P3, comp=comp)
            self.assertFalse([d for d in self.all_driven(out) if d[1] == "infrastructure.data_residency"], comp)
            pay = sup(out, "payments")[0]["driven_by"]
            self.assertEqual(len(pay), len(set(pay)))

    def test_cloud_any_never_cited(self):
        out = run(P3, "any")
        self.assertFalse([d for d in self.all_driven(out) if d[1] == "infrastructure.cloud_preference"])

    def test_must_not_drop_a_real_residency(self):
        out = run(P3, res="eu", comp=[])
        self.assertIn("infrastructure.data_residency", sup(out, "payments")[0]["driven_by"])
        self.assertIn("infrastructure.data_residency", sup(out, "storage")[0]["driven_by"])
        out = run(P5)  # india
        self.assertIn("infrastructure.data_residency", sup(out, "storage")[0]["driven_by"])


class EntraDataLocation(unittest.TestCase):
    def note(self, out):
        a = sup(out, "auth")[0]
        return a, "geo-location chosen when the tenant was created" in a["justification"]

    def test_fires_with_residency_or_compliance(self):
        for res, comp in (("india", []), ("eu", []), ("none", ["gdpr"]), ("none", ["iso27001"])):
            a, hit = self.note(run(P5, res=res, comp=comp))
            self.assertIn("Entra", a["choice"])
            self.assertTrue(hit, (res, comp))
            self.assertIn("not this application's data", a["justification"])
            self.assertIn(ENTRA_URL, a["sources"])

    def test_must_not_fire_without_residency_or_compliance(self):
        a, hit = self.note(run(P5, res="none", comp=[]))
        self.assertFalse(hit)
        self.assertNotIn(ENTRA_URL, a["sources"])

    def test_must_not_fire_for_non_entra_auth(self):
        out = run(P3, res="eu")
        self.assertNotIn("Entra", sup(out, "auth")[0]["choice"])
        self.assertNotIn("geo-location chosen when the tenant", sup(out, "auth")[0]["justification"])


if __name__ == "__main__":
    unittest.main()
