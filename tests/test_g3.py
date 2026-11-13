"""G3: relaxed sizing (A10), llm_rag description constraints (A15 second half), small on-premises stack and backup warning (A20).
Each rule is stated over input fields, tested on several project types plus inputs where it must not fire. Inputs are inline."""
import copy
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "G3", "project": {"type": "web_app", "platforms": ["web"], "description": "A small web application."},
        "scale": {"users_at_launch": 800, "users_12_months": 3000, "peak_concurrent_users": 150},
        "team": {"size": 5, "experience": "intermediate", "languages": ["typescript"], "has_devops": True},
        "budget": {"monthly_infra_usd": 2000}, "timeline": {"mvp_weeks": 14},
        "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password"}}


def run(desc=None, **kw):
    s = copy.deepcopy(BASE)
    if desc is not None:
        s["project"]["description"] = desc
    for path, v in kw.items():
        node, parts = s, path.replace("__", ".").split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return evaluate(s, counterfactuals=False)


def sup(out, needle):
    return [s for s in out["stack"]["supporting"] if needle in s["choice"] or needle in s["layer"]]


def warns(out, code):
    return [w for w in out["warnings"] if w["code"] == code]


def sev(out, code):
    w = warns(out, code)
    return w[0]["severity"] if w else None


def lines(out):
    return out["estimated_monthly_cost_usd"]["assumptions"]


SOLO = dict(team__size=1, team__experience="beginner", team__has_devops=False)


class A10RelaxedAvailability(unittest.TestCase):
    """AVAILABILITY_VS_TEAM critical -> the stack is sized for 99.9%: no standby database, second instance or second region."""

    def check(self, out, asked_cheaper=True):
        self.assertEqual(sev(out, "AVAILABILITY_VS_TEAM"), "critical")
        self.assertFalse(sup(out, "Second-region"), "standby must not be in the stack")
        self.assertNotIn("zone-redundant HA", out["stack"]["database"]["choice"])
        self.assertFalse(any(l.startswith("Availability") for l in lines(out)), "no second app instance line")
        a = next(a for a in out["assumptions"] if a.startswith("Sized for 99.9% availability, not the requested 99.99%"))
        self.assertIn("leaves out", a)
        note = next(l for l in lines(out) if l.startswith("At full scale / full target"))
        self.assertIn("99.99% availability", note)
        self.assertNotRegex(note, r"\$[\d,]+-[\d,]+/month")  # the band stays the sum of its own lines
        self.assertTrue(out["summary"].startswith("Relaxed recommendation"))
        lo = hi = 0.0
        for l in lines(out):
            m = re.search(r"\$([\d,]+)-([\d,]+)/month", l)
            if m:
                lo += float(m.group(1).replace(",", ""))
                hi += float(m.group(2).replace(",", ""))
        self.assertLessEqual(abs(lo - out["estimated_monthly_cost_usd"]["min"]), 1)
        self.assertLessEqual(abs(hi - out["estimated_monthly_cost_usd"]["max"]), 1)
        full = [int(x.replace(",", "")) for x in re.findall(r"\$([\d,]+)", note)]
        self.assertGreater(full[1], out["estimated_monthly_cost_usd"]["max"])

    def test_hiking_app_on_gcp(self):
        out = run("Hiking route recorder with GPX export.", requirements__availability="99.99", infrastructure__cloud_preference="gcp",
                  project__platforms=["web", "android"], **SOLO)
        self.check(out)
        self.assertIn("second GCP region", " ".join(out["assumptions"]))

    def test_saas_on_aws(self):
        out = run("Invoicing tool for freelancers with a customer portal.", project__type="saas_b2b", requirements__availability="99.99",
                  infrastructure__cloud_preference="aws", requirements__multi_tenant=True, **SOLO)
        self.check(out)
        self.assertIn("AVAILABILITY_SINGLE_REGION", [w["code"] for w in out["warnings"]])
        self.assertEqual(sev(out, "AVAILABILITY_SINGLE_REGION"), "warning")

    def test_marketplace_on_azure(self):
        out = run("Local marketplace for second-hand tools.", project__type="marketplace", requirements__availability="99.99",
                  infrastructure__cloud_preference="azure", requirements__payments=True, **SOLO)
        self.check(out)

    def test_must_not_fire_for_milder_conflicts(self):
        # 99.95 for a solo beginner is a warning: the standby database stays
        o = run(requirements__availability="99.95", **SOLO)
        self.assertEqual(sev(o, "AVAILABILITY_VS_TEAM"), "warning")
        self.assertIn("zone-redundant HA", o["stack"]["database"]["choice"])
        self.assertFalse(any(a.startswith("Sized for 99.9%") for a in o["assumptions"]))
        # 99.99 with a senior team of five: the second region stays
        o = run(requirements__availability="99.99", infrastructure__cloud_preference="gcp", team__size=5, team__experience="senior")
        self.assertTrue(sup(o, "Second-region"))
        self.assertFalse(any("At full scale / full target" in l for l in lines(o)))

    def test_rto_still_keeps_database_standby(self):
        o = run(requirements__availability="99.99", requirements__rto_minutes=15, infrastructure__cloud_preference="gcp", **SOLO)
        self.assertIn("zone-redundant HA", o["stack"]["database"]["choice"])
        self.assertFalse(sup(o, "Second-region"))
        a = next(a for a in o["assumptions"] if a.startswith("Sized for 99.9% availability"))
        self.assertNotIn("zone-redundant standby database", a)


class A10RelaxedScale(unittest.TestCase):
    """SCALE_VS_BUDGET critical -> the band is priced for a pilot; the full-scale figure is a separate note."""

    def big(self, **kw):
        base = dict(scale__users_at_launch=300000, scale__users_12_months=2000000, scale__peak_concurrent_users=50000, budget__monthly_infra_usd=30,
                    scale__data_volume_gb_12_months=20000)
        base.update(kw)
        return run(**base)

    def test_social_app(self):
        o = self.big(project__type="social", infrastructure__cloud_preference="aws")
        self.assertEqual(sev(o, "SCALE_VS_BUDGET"), "critical")
        a = next(a for a in o["assumptions"] if a.startswith("Priced for a pilot"))
        self.assertIn("2,000,000", a)
        note = next(l for l in lines(o) if l.startswith("At full scale / full target"))
        self.assertIn("full scale (2,000,000 users", note)
        hi = [int(x.replace(",", "")) for x in re.findall(r"\$([\d,]+)", note)][1]
        self.assertGreater(hi, 100 * o["estimated_monthly_cost_usd"]["max"] // 10)
        self.assertLess(o["estimated_monthly_cost_usd"]["max"], hi)

    def test_marketplace_and_game(self):
        for typ in ("marketplace", "saas_b2b"):
            o = self.big(project__type=typ, infrastructure__cloud_preference="gcp")
            self.assertTrue(any(a.startswith("Priced for a pilot") for a in o["assumptions"]), typ)
            self.assertTrue(any(l.startswith("At full scale / full target") for l in lines(o)), typ)

    def test_core_choices_do_not_depend_on_pilot_pricing(self):
        a = self.big(infrastructure__cloud_preference="aws")
        b = self.big(infrastructure__cloud_preference="aws", budget__monthly_infra_usd=150)  # same scale, SCALE_VS_BUDGET silent
        for layer in ("frontend", "backend", "hosting"):
            self.assertEqual(a["stack"][layer]["choice"], b["stack"][layer]["choice"], layer)

    def test_must_not_fire(self):
        o = self.big(budget__monthly_infra_usd=150)
        self.assertIsNone(sev(o, "SCALE_VS_BUDGET"))
        self.assertFalse(any(a.startswith("Priced for a pilot") for a in o["assumptions"]))
        o = run(scale__users_12_months=3000, budget__monthly_infra_usd=20)  # small product, small budget
        self.assertFalse(any("At full scale / full target" in l for l in lines(o)))


class A10Latency(unittest.TestCase):
    def test_fires_for_realtime_with_unspecified_or_global_users(self):
        for typ in ("marketplace", "social", "realtime_collab"):
            o = run(project__type=typ, requirements__realtime=True, requirements__p95_latency_ms=30, infrastructure__cloud_preference="aws")
            self.assertEqual(sev(o, "LATENCY_TARGET_VS_REACH"), "warning", typ)
            self.assertIn("scale.geo_spread is not given", warns(o, "LATENCY_TARGET_VS_REACH")[0]["message"])

    def test_must_not_fire(self):
        for kw in (dict(requirements__p95_latency_ms=120),              # not strict
                   dict(requirements__realtime=False),                  # no live traffic
                   dict(scale__geo_spread="single_region")):            # users stated near the region
            o = run(**dict(dict(requirements__realtime=True, requirements__p95_latency_ms=30), **kw))
            self.assertIsNone(sev(o, "LATENCY_TARGET_VS_REACH"), kw)


def ml(out):
    return next(x for x in out["stack"]["supporting"] if x["layer"] == "ml")


class A15LlmDescriptionConstraints(unittest.TestCase):
    RAG = dict(requirements__ml_features="llm_rag", infrastructure__cloud_preference="aws")

    def test_legal_assistant(self):
        o = run("Chatbot that explains tenant rights, citing statutes. Letters must never be used to train a model.",
                requirements__multi_tenant=True, project__type="ai_ml_product", **self.RAG)
        j = ml(o)["justification"]
        self.assertIn("No-training requirement", j)
        self.assertIn("citations field", j)
        self.assertIn("tenant-scoped", j)
        self.assertEqual(sev(o, "LLM_NO_TRAINING_TERMS"), "warning")
        self.assertEqual(sev(o, "LLM_ADVICE_DISCLAIMER"), "warning")
        self.assertIn("'not legal advice'", warns(o, "LLM_ADVICE_DISCLAIMER")[0]["message"])

    def test_health_questions(self):
        o = run("Assistant answering patient questions about medication from the clinic leaflets, answers cite the leaflet.",
                project__type="ai_ml_product", **self.RAG)
        self.assertIn("'not medical advice'", warns(o, "LLM_ADVICE_DISCLAIMER")[0]["message"])
        self.assertIn("citations field", ml(o)["justification"])
        self.assertNotIn("tenant-scoped", ml(o)["justification"])

    def test_self_hosted_no_training_needs_no_vendor_terms(self):
        o = run("Internal HR policy assistant. Employee questions must not be used for training anyone's model.",
                project__type="internal_tool", requirements__ml_features="llm_rag", infrastructure__deployment_model="on_premise",
                infrastructure__cloud_preference="none")
        self.assertIn("runs on your own servers", ml(o)["justification"])
        self.assertIsNone(sev(o, "LLM_NO_TRAINING_TERMS"))
        self.assertIsNone(sev(o, "LLM_ADVICE_DISCLAIMER"))

    def test_must_not_fire(self):
        o = run("Search assistant over our product manuals.", project__type="ai_ml_product", **self.RAG)
        j = ml(o)["justification"]
        for needle in ("No-training", "citations field", "tenant-scoped", "advice"):
            self.assertNotIn(needle, j)
        for code in ("LLM_NO_TRAINING_TERMS", "LLM_ADVICE_DISCLAIMER"):
            self.assertIsNone(sev(o, code))
        o = run("Support bot over manuals; we do not need citations.", project__type="ai_ml_product", **self.RAG)
        self.assertNotIn("citations field", ml(o)["justification"])
        o = run("Legal documents must never be used to train a model.", requirements__ml_features="inference_api")  # not llm_rag
        self.assertIsNone(sev(o, "LLM_NO_TRAINING_TERMS"))


if __name__ == "__main__":
    unittest.main()
