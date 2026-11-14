"""P2: wrong-choice and silent-rule fixes (service region availability, client platform fit, video detection,
skill mismatch, team warnings, every air-gap conflict, single-site availability)."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {
    "project": {"name": "Probe", "type": "api_platform", "description": "A public API that partners call from their systems.",
                "platforms": ["api_only"]},
    "scale": {"traffic_pattern": "steady", "workload": "balanced", "users_at_launch": 50, "users_12_months": 500,
              "peak_concurrent_users": 50, "data_volume_gb_12_months": 50},
    "team": {"has_devops": True, "size": 5, "experience": "senior", "languages": ["python", "typescript"]},
    "budget": {"monthly_infra_usd": 2000},
    "timeline": {"mvp_weeks": 12},
    "infrastructure": {"cloud_preference": "gcp", "deployment_model": "managed_cloud", "data_residency": "india",
                       "existing_systems": []},
    "requirements": {"realtime": False, "offline_support": False, "full_text_search": False, "file_media_storage": False,
                     "payments": False, "auth": "email_password", "multi_tenant": False, "ml_features": "none",
                     "seo_critical": False, "availability": "99.9", "p95_latency_ms": 500},
    "compliance": [],
    "priorities": {"cost": 3, "time_to_market": 3, "scalability": 3, "security": 3, "maintainability": 3, "learning_curve": 3},
}


def scen(**kw):
    s = copy.deepcopy(BASE)
    for path, v in kw.items():
        sec, key = path.split("__")
        s[sec][key] = v
    return s


def run(s):
    return evaluate(s, counterfactuals=False)


def codes(out):
    return [w["code"] for w in out["warnings"]]


def gateway(out):
    g = [x for x in out["stack"]["supporting"] if x["choice"].startswith("API gateway:")]
    return g[0] if g else None


class ServiceRegion(unittest.TestCase):
    def test_gcp_gateway_not_in_india_region(self):
        out = run(scen())
        g = gateway(out)
        self.assertNotIn("Google Cloud API Gateway", g["choice"])
        self.assertIn("asia-south1", g["choice"])
        self.assertIn("SERVICE_REGION_UNAVAILABLE", codes(out))
        self.assertIn("Google Cloud API Gateway", [a["choice"] for a in g["alternatives"]])

    def test_fintech_api_with_payments_switzerland(self):
        out = run(scen(project__type="fintech", requirements__payments=True, infrastructure__data_residency="other",
                       project__description="A payments API for Swiss banks; all data must stay in Switzerland."))
        g = gateway(out)
        self.assertIsNotNone(g)
        self.assertNotIn("Google Cloud API Gateway", g["choice"])
        self.assertIn("europe-west6", g["choice"])
        self.assertIn("SERVICE_REGION_UNAVAILABLE", codes(out))

    def test_healthtech_api_south_korea(self):
        out = run(scen(project__type="healthtech", requirements__payments=True, infrastructure__data_residency="other",
                       project__description="A clinic booking API for South Korea; patient data must stay in South Korea."))
        g = gateway(out)
        self.assertNotIn("Google Cloud API Gateway", g["choice"])
        self.assertIn("SERVICE_REGION_UNAVAILABLE", codes(out))

    def test_not_fired_where_offered_or_unconstrained(self):
        for kw in ({"infrastructure__data_residency": "eu"}, {"infrastructure__data_residency": "none"},
                   {"infrastructure__cloud_preference": "aws"}):
            out = run(scen(**kw))
            self.assertNotIn("SERVICE_REGION_UNAVAILABLE", codes(out), kw)
        g = gateway(run(scen(infrastructure__data_residency="eu")))
        self.assertIn("Google Cloud API Gateway", g["choice"])


if __name__ == "__main__":
    unittest.main()
