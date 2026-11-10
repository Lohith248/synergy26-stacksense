"""Write scenarios/hidden_like/H*.json: author-made scenarios in the official format covering project types
and inputs the public set does not exercise (gaming, IoT, analytics, AI/RAG, healthtech, API platform,
B2B SaaS, seasonal e-commerce, zero-budget students, social, desktop, seasonal content).

They are probes for the engine, not reference answers. Regenerate with: python tools/make_hidden_like.py
"""
import copy
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = {
    "project": {"name": "", "type": "web_app", "description": "", "platforms": ["web"]},
    "scale": {"traffic_pattern": "steady", "workload": "balanced", "users_at_launch": 1000, "users_12_months": 10000,
              "peak_concurrent_users": 300, "data_volume_gb_12_months": 20},
    "team": {"has_devops": False, "size": 3, "experience": "intermediate", "languages": ["typescript"]},
    "budget": {"monthly_infra_usd": 300},
    "timeline": {"mvp_weeks": 10},
    "infrastructure": {"cloud_preference": "any", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
    "requirements": {"realtime": False, "offline_support": False, "full_text_search": False, "file_media_storage": False,
                     "payments": False, "auth": "email_password", "multi_tenant": False, "ml_features": "none",
                     "seo_critical": False, "availability": "99.9", "p95_latency_ms": None},
    "compliance": [],
    "priorities": {"cost": 3, "time_to_market": 3, "scalability": 3, "performance": 3, "maintainability": 3, "security": 3},
}

H = {
    "H01": {"project": {"name": "ArenaClash", "type": "gaming", "platforms": ["android", "ios"],
                        "description": "Real-time 4-player mobile battle game with matchmaking, leaderboards and in-app purchases. Players expect under 60 ms latency."},
            "scale": {"traffic_pattern": "spiky", "workload": "write_heavy", "users_at_launch": 20000, "users_12_months": 300000,
                      "peak_concurrent_users": 20000, "data_volume_gb_12_months": 100},
            "team": {"size": 6, "experience": "senior", "languages": ["csharp"], "has_devops": True},
            "budget": {"monthly_infra_usd": 4000}, "timeline": {"mvp_weeks": 20},
            "requirements": {"realtime": True, "payments": True, "auth": "social", "p95_latency_ms": 60, "availability": "99.9"},
            "priorities": {"performance": 5, "scalability": 5, "cost": 3}},
    "H02": {"project": {"name": "FieldPulse", "type": "iot", "platforms": ["web"],
                        "description": "50,000 soil sensors send readings every 30 seconds; farmers see dashboards and get alerts when moisture drops."},
            "scale": {"traffic_pattern": "steady", "workload": "write_heavy", "users_at_launch": 500, "users_12_months": 5000,
                      "peak_concurrent_users": 400, "data_volume_gb_12_months": 2000},
            "team": {"size": 4, "experience": "intermediate", "languages": ["python", "typescript"], "has_devops": False},
            "budget": {"monthly_infra_usd": 1500}, "infrastructure": {"cloud_preference": "aws"},
            "requirements": {"realtime": True, "auth": "email_password"}},
    "H03": {"project": {"name": "SalesLens", "type": "data_analytics", "platforms": ["web"],
                        "description": "Internal BI dashboards over three years of sales and inventory data; analysts run ad-hoc SQL and scheduled reports."},
            "scale": {"workload": "read_heavy", "users_at_launch": 80, "users_12_months": 150, "peak_concurrent_users": 40,
                      "data_volume_gb_12_months": 800},
            "team": {"size": 2, "experience": "intermediate", "languages": ["python", "sql"]},
            "budget": {"monthly_infra_usd": 800}, "infrastructure": {"cloud_preference": "gcp"},
            "requirements": {"auth": "enterprise_sso"}},
    "H04": {"project": {"name": "DocAsk", "type": "ai_ml_product", "platforms": ["web"],
                        "description": "Teams upload PDFs and policies and ask questions in chat; answers cite the source passages."},
            "scale": {"users_at_launch": 500, "users_12_months": 20000, "peak_concurrent_users": 1000, "data_volume_gb_12_months": 300},
            "team": {"size": 4, "experience": "senior", "languages": ["python", "typescript"], "has_devops": True},
            "budget": {"monthly_infra_usd": 2000}, "infrastructure": {"data_residency": "eu"},
            "requirements": {"file_media_storage": True, "multi_tenant": True, "auth": "social", "ml_features": "llm_rag", "payments": True},
            "compliance": ["gdpr"]},
    "H05": {"project": {"name": "CareLink", "type": "healthtech", "platforms": ["web", "ios", "android"],
                        "description": "Telehealth app: patients book visits, chat with doctors and upload lab reports. US clinics only."},
            "scale": {"users_at_launch": 3000, "users_12_months": 60000, "peak_concurrent_users": 1500, "data_volume_gb_12_months": 400},
            "team": {"size": 6, "experience": "mixed", "languages": ["typescript", "java"], "has_devops": True},
            "budget": {"monthly_infra_usd": 3000}, "infrastructure": {"data_residency": "us"},
            "requirements": {"realtime": True, "file_media_storage": True, "payments": True, "auth": "email_password", "availability": "99.95"},
            "compliance": ["hipaa", "soc2"], "priorities": {"security": 5}},
    "H06": {"project": {"name": "GeoAPI", "type": "api_platform", "platforms": ["api_only"],
                        "description": "Public REST API for address geocoding with API keys, usage metering and rate limits."},
            "scale": {"traffic_pattern": "spiky", "workload": "read_heavy", "users_at_launch": 200, "users_12_months": 3000,
                      "peak_concurrent_users": 1000, "data_volume_gb_12_months": 150},
            "team": {"size": 3, "experience": "senior", "languages": ["go"], "has_devops": True},
            "budget": {"monthly_infra_usd": 700},
            "requirements": {"auth": "none", "payments": True, "p95_latency_ms": 100},
            "priorities": {"performance": 5, "cost": 4}},
    "H07": {"project": {"name": "OpsDesk", "type": "saas_b2b", "platforms": ["web"],
                        "description": "Helpdesk SaaS for mid-size companies; each customer org connects its own Okta or Entra login. Teams pay per seat."},
            "scale": {"users_at_launch": 2000, "users_12_months": 40000, "peak_concurrent_users": 2000, "data_volume_gb_12_months": 300},
            "team": {"size": 5, "experience": "senior", "languages": ["typescript"], "has_devops": True},
            "budget": {"monthly_infra_usd": 2500}, "infrastructure": {"data_residency": "us"},
            "requirements": {"full_text_search": True, "file_media_storage": True, "payments": True, "auth": "enterprise_sso",
                             "multi_tenant": True, "availability": "99.95"},
            "compliance": ["soc2"]},
    "H08": {"project": {"name": "Utsav Mart", "type": "ecommerce", "platforms": ["web", "android"],
                        "description": "Online store for festive clothing; most sales happen in the two weeks before Diwali."},
            "scale": {"traffic_pattern": "seasonal", "workload": "read_heavy", "users_at_launch": 5000, "users_12_months": 120000,
                      "peak_concurrent_users": 8000, "data_volume_gb_12_months": 60},
            "team": {"size": 3, "experience": "intermediate", "languages": ["php", "javascript"]},
            "budget": {"monthly_infra_usd": 400}, "infrastructure": {"data_residency": "india"},
            "requirements": {"full_text_search": True, "file_media_storage": True, "payments": True, "auth": "phone_otp", "seo_critical": True},
            "compliance": ["dpdp"], "priorities": {"cost": 4, "time_to_market": 5}},
    "H09": {"project": {"name": "CampusSwap", "type": "web_app", "platforms": ["web"],
                        "description": "Three students build a marketplace for second-hand textbooks within their college."},
            "scale": {"users_at_launch": 200, "users_12_months": 2000, "peak_concurrent_users": 50, "data_volume_gb_12_months": 2},
            "team": {"size": 3, "experience": "beginner", "languages": ["javascript", "python"]},
            "budget": {"monthly_infra_usd": 0}, "timeline": {"mvp_weeks": 4},
            "requirements": {"file_media_storage": True, "auth": "social"},
            "priorities": {"cost": 5, "time_to_market": 4}},
    "H10": {"project": {"name": "Snapverse", "type": "social", "platforms": ["android", "ios", "web"],
                        "description": "Photo-sharing social network with follows, feeds, likes, comments and push notifications."},
            "scale": {"traffic_pattern": "spiky", "workload": "read_heavy", "users_at_launch": 50000, "users_12_months": 1000000,
                      "peak_concurrent_users": 60000, "data_volume_gb_12_months": 20000},
            "team": {"size": 10, "experience": "senior", "languages": ["kotlin", "swift", "typescript"], "has_devops": True},
            "budget": {"monthly_infra_usd": 15000}, "timeline": {"mvp_weeks": 24},
            "requirements": {"realtime": True, "full_text_search": True, "file_media_storage": True, "auth": "social",
                             "availability": "99.95", "ml_features": "inference_api"},
            "priorities": {"scalability": 5, "performance": 4}},
    "H11": {"project": {"name": "LabBench", "type": "internal_tool", "platforms": ["desktop"],
                        "description": "Desktop tool for lab technicians to record sample results; used only by employees on the lab network."},
            "scale": {"users_at_launch": 40, "users_12_months": 60, "peak_concurrent_users": 30, "data_volume_gb_12_months": 5},
            "team": {"size": 1, "experience": "intermediate", "languages": ["csharp"]},
            "budget": {"monthly_infra_usd": 0}, "infrastructure": {"deployment_model": "on_premise", "cloud_preference": "none"},
            "requirements": {"auth": "enterprise_sso"}},
    "H12": {"project": {"name": "Kumbh Guide", "type": "content_site", "platforms": ["web"],
                        "description": "Multilingual visitor guide for a festival; traffic explodes for six weeks then nearly stops."},
            "scale": {"traffic_pattern": "seasonal", "workload": "read_heavy", "users_at_launch": 100000, "users_12_months": 5000000,
                      "peak_concurrent_users": 100000, "data_volume_gb_12_months": 5},
            "team": {"size": 2, "experience": "intermediate", "languages": ["javascript"]},
            "budget": {"monthly_infra_usd": 200}, "requirements": {"auth": "none", "seo_critical": True}},
}


def merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            merge(a[k], v)
        else:
            a[k] = v
    return a


def main():
    out = os.path.join(ROOT, "scenarios", "hidden_like")
    os.makedirs(out, exist_ok=True)
    for sid, over in H.items():
        s = merge(copy.deepcopy(BASE), copy.deepcopy(over))
        doc = {"scenario_id": sid, **s}
        with open(os.path.join(out, f"{sid}_{s['project']['name'].replace(' ', '')}.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
    print(f"wrote {len(H)} scenarios to {out}")


if __name__ == "__main__":
    main()
