"""Derived signals from validated input. Every derived value records the input paths it came from."""
import re

from .kb import TECH

TIER_NAMES = ["tiny", "small", "medium", "large"]
EXP_FACTOR = {"beginner": 1.6, "intermediate": 1.2, "mixed": 1.2, "senior": 0.7}
# Language fit: switching language costs every team real time; seniors ramp faster but never for free.
LANG_FACTOR = {"beginner": 1.6, "intermediate": 1.3, "mixed": 1.3, "senior": 1.0}
DYNAMIC_TYPES = {"web_app", "saas_b2b", "ecommerce", "marketplace", "social", "realtime_collab", "fintech",
                 "healthtech", "data_analytics", "iot", "ai_ml_product", "internal_tool", "gaming", "api_platform"}
LANG_ALIASES = {"js": "javascript", "ts": "typescript", "c#": "csharp", "golang": "go", "py": "python",
                "node": "javascript", "nodejs": "javascript", "node.js": "javascript", "c sharp": "csharp"}

# Deterministic description rules (D7). Each: flag -> regex. They only shape supporting services/warnings.
DESC_RULES = [
    ("upi", r"\bupi\b"),
    ("recurring", r"\bemi\b|subscription|recurring|per[- ]seat|pay per seat|monthly plan"),
    ("payouts", r"get paid|payout|disburs|pay (?:out|providers|sellers|vendors)|split payment|commission"),
    ("ledger", r"ledger|double[- ]entry"),
    ("kyc", r"\bkyc\b|know your customer|identity verification"),
    ("chat", r"\bchat|messag"),
    ("collab", r"same board|collaborat|live cursor|multiplayer|co-edit|whiteboard"),
    ("markdown", r"markdown|\bmdx?\b"),
    ("gps_media", r"\bgps\b|photo|camera|geo-?tag"),
    ("low_bandwidth", r"\b2g\b|\b3g\b|intermittent|low bandwidth|poor (?:network|connectivity)|no signal|signal is available"),
    ("low_end", r"low-end|low end|2 ?gb ram|1 ?gb ram|budget phones?"),
    ("approvals", r"approv|leave request|workflow"),
    ("internal_only", r"only by employees|internal use|employees only|intranet"),
    ("jobs_dispatch", r"accept jobs|book |booking|dispatch|assign"),
    ("scoring_model", r"scoring model|credit scor|risk model|fraud model"),
    ("notifications", r"notif|alert|remind"),
    ("iot", r"\bsensors?\b|\biot\b|telemetry|\bdevices? (?:send|report|publish)|smart meters?|trackers? send"),
    ("digital_goods", r"in-app purchase|in-game|\bcoins\b|\bgems\b|unlock|premium (?:features|content|tier)|loot|battle pass"),
    ("analytics", r"dashboards?|\breports?\b|analysts?|\bbi\b|ad-hoc (?:sql|quer)|data warehouse"),
]


def lang_norm(langs):
    return sorted({LANG_ALIASES.get(x, x) for x in langs})


def build(req):
    c = {"req": req}
    plats = req["project.platforms"]
    c["platforms"] = plats
    c["web"] = "web" in plats
    c["mobile"] = [p for p in ("android", "ios") if p in plats]
    c["desktop"] = "desktop" in plats
    c["api_only"] = plats == ["api_only"] or (set(plats) == {"api_only"})
    users = max(req["scale.users_12_months"], req["scale.users_at_launch"])
    peak = req["scale.peak_concurrent_users"]
    if peak is None:
        peak = max(1, users // 10)
    c["users"], c["peak"] = users, peak
    if users <= 5000 and peak <= 200:
        tier = 0
    elif users <= 50000 and peak <= 2000:
        tier = 1
    elif users <= 500000 and peak <= 20000:
        tier = 2
    else:
        tier = 3
    c["tier"] = tier
    c["data_gb"] = req["scale.data_volume_gb_12_months"] if req["scale.data_volume_gb_12_months"] is not None else 5
    c["langs"] = lang_norm(req["team.languages"])
    c["exp"] = req["team.experience"]
    c["xf"] = EXP_FACTOR[c["exp"]]
    c["lf"] = LANG_FACTOR[c["exp"]]
    c["devops"] = req["team.has_devops"]
    c["size"] = req["team.size"]
    c["weeks"] = req["timeline.mvp_weeks"]
    c["budget"] = req["budget.monthly_infra_usd"]
    c["cloud"] = req["infrastructure.cloud_preference"]
    c["deploy"] = req["infrastructure.deployment_model"]
    comp = req["compliance"]
    c["compliance"] = comp
    res = req["infrastructure.data_residency"]
    c["residency_from_rbi"] = False
    if res == "none" and "rbi_localisation" in comp:
        res = "india"
        c["residency_from_rbi"] = True
    c["residency"] = res
    c["res_key"] = res if res in ("india", "eu", "us") else None
    c["self_host_only"] = c["deploy"] in ("on_premise", "air_gapped")
    c["no_internet"] = c["deploy"] == "air_gapped"
    c["prio"] = {k: req[f"priorities.{k}"] for k in ("cost", "time_to_market", "scalability", "performance",
                                                       "maintainability", "security")}
    desc = (req["project.description"] or "").lower()
    c["desc"] = {flag: bool(re.search(rx, desc)) for flag, rx in DESC_RULES}
    ex = []
    for raw in req["infrastructure.existing_systems"]:
        low = f" {raw.lower()} "
        hit = None
        for pat in TECH["existing_patterns"]:
            if any(m in low for m in pat["match"]):
                hit = pat
                break
        life = None
        for lc in TECH["lifecycle"]:
            if lc["pattern"] in low:
                life = lc
                break
        ex.append({"raw": raw, "pattern": hit, "life": life, "onprem": "on-prem" in low or "on prem" in low
                   or "onprem" in low or "on-premises" in low})
    c["existing"] = ex
    c["existing_db"] = next((e for e in ex if e["pattern"] and e["pattern"]["kind"] == "database"), None)
    c["existing_idp"] = next((e for e in ex if e["pattern"] and e["pattern"]["kind"] == "identity"), None)
    c["existing_m365"] = next((e for e in ex if e["pattern"] and e["pattern"]["kind"] == "collaboration"), None)
    r = req
    typ = r["project.type"]
    c["type"] = typ
    dynamic_need = (r["requirements.auth"] != "none" or r["requirements.payments"] or r["requirements.realtime"]
                    or r["requirements.file_media_storage"] or r["requirements.multi_tenant"]
                    or r["requirements.ml_features"] != "none" or r["requirements.offline_support"]
                    or c["api_only"] or bool(c["mobile"]))
    c["needs_backend"] = dynamic_need or typ in DYNAMIC_TYPES
    c["needs_db"] = c["needs_backend"]
    c["static_search"] = (not c["needs_backend"]) and r["requirements.full_text_search"]
    return c
