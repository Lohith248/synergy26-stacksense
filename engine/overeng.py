"""Over-engineering guard (D16): simple stacks for inputs that do not need complexity.

The statement's edge-case table asks for "simple stacks; no microservices or Kubernetes without justification" for "high traffic that
is actually static, small internal tools, tiny teams". Three input-driven rules live here:

  1. static_override: a site whose structured fields ask for nothing dynamic, and whose payments (if any) are a hosted button or link,
     is a static site. High traffic alone never needs a backend or database: the CDN absorbs read traffic.
  2. over_floor: an optional managed add-on whose entry price is a large share of a small budget is replaced by the cheaper option the
     knowledge base already holds, or not added (and the output says so), instead of silently exceeding the budget.
  3. small_team: one deployable and no Kubernetes for a small team unless an input says otherwise.

Every number below is a planning heuristic (policy, not a vendor limit); a vendor fact is cited from kb/sources.json where it is used.
Rules touch supporting services, explanations and the static/dynamic switch; they never rank the four core layers against each other.
"""
import re

THRESHOLDS = {
    "small_team": 5,        # heuristic: up to this many people run one deployable and no cluster
    "floor_share": 0.15,    # heuristic: an optional add-on whose cheapest tier costs more than this share of the budget is replaced or deferred
                            # (same 15% as the Azure Front Door rule in services.py, which was derived from its verified $35 base fee)
    "guard_max_tier": 2,    # heuristic: at the 'large' scale tier (>500,000 users) the add-ons carry load; BUDGET_EXCEEDED explains the gap instead
}

# types that may be static; web_app and internal_tool only when the description says the content is editorial
STATIC_TYPES = ("content_site", "other")
SOFT_TYPES = ("web_app", "internal_tool")
# description signals that mean stored user data, server-side work or integrations: any of them keeps the backend
DYNAMIC_FLAGS = ("payouts", "ledger", "kyc", "chat", "collab", "iot", "uploads", "otp", "sms", "web3", "digital_goods", "video_vod",
                 "video_call", "jobs_dispatch", "approvals", "scoring_model", "scheduler", "user_data", "lending", "gps")
DYNAMIC_COMPLIANCE = ("hipaa", "rbi_localisation")  # regulated data is stored somewhere: not a pages-only site


def dynamic_fields(req, api_only, mobile):
    """Structured fields that ask for server-side behaviour (everything but payments)."""
    return (req["requirements.auth"] != "none" or req["requirements.realtime"] or req["requirements.file_media_storage"]
            or req["requirements.multi_tenant"] or req["requirements.ml_features"] != "none" or api_only or bool(mobile)
            or req["scale.workload"] == "write_heavy")


def static_override(c):
    """'hosted_payments' (payments are a hosted button or link) or 'editorial' (a soft type with editorial content) when the input
    is static-eligible although the baseline rule would add a backend; otherwise None. c: the context under construction."""
    req, typ, d = c["req"], c["type"], c["desc"]
    paying = bool(req["requirements.payments"])
    if typ not in STATIC_TYPES + SOFT_TYPES or not (paying or typ in SOFT_TYPES):
        return None  # nothing to override: the baseline already says static, or the type is dynamic by nature
    if dynamic_fields(req, c["api_only"], c["mobile"]) or c["deploy"] != "managed_cloud" or c["existing"]:
        return None
    if any(d[f] for f in DYNAMIC_FLAGS) or set(c["compliance"]) & set(DYNAMIC_COMPLIANCE):
        return None
    if paying and not d["hosted_pay"]:
        return None
    if typ in SOFT_TYPES and not d["editorial"]:
        return None
    return "hosted_payments" if paying else "editorial"


def quote(c, flag):
    """The words of the description that set a signal (lower-case, as written), for output text."""
    from .context import DESC_RX
    m = re.search(DESC_RX[flag], (c["req"]["project.description"] or "").lower().replace("’", "'"))
    return m.group(0).strip() if m else ""


def static_facts(c):
    """Sentence fragment quoting the inputs behind a static stack, shared by the backend and database explanations."""
    req = c["req"]
    bits = ["requirements.auth is none", "no realtime, uploads, multi-tenancy or ML features are requested"]
    if req["requirements.payments"]:
        q = quote(c, "hosted_pay")
        bits.append(f"requirements.payments is true but the description names a hosted payment button or link (\"{q}\"), "
                    "so card data and payment records stay with the payment provider")
    else:
        bits.append("requirements.payments is false")
    return "; ".join(bits)


def traffic_clause(c):
    """Why traffic does not change a static verdict; empty below the 'medium' scale tier."""
    if c["tier"] < 2:
        return ""
    return (f" Traffic does not change this: ~{c['users']:,} expected users (~{c['peak']:,} concurrent) read pre-built pages that the CDN "
            "serves from its edge cache, so the load falls on the CDN and the origin count stays at zero.")


def over_floor(c, floor):
    """True when an optional add-on whose cheapest tier costs `floor` USD/month should give way to a cheaper option: the budget is
    small relative to it and the scale is below the 'large' tier. A budget of 0 treats any paid floor as too large."""
    if floor <= 0 or c["tier"] > THRESHOLDS["guard_max_tier"]:
        return False
    return floor > THRESHOLDS["floor_share"] * c["budget"]


def floor_fact(c, name, floor):
    """The numbers behind an over_floor verdict, in prose."""
    pct = f"{round(100 * floor / c['budget'])}% of" if c["budget"] > 0 else "more than all of"
    return (f"{name} costs from about ${floor}/month at the '{['tiny', 'small', 'medium', 'large'][c['tier']]}' tier, {pct} the "
            f"${num(c['budget'])}/month budget (budget.monthly_infra_usd; planning heuristic: an optional add-on above "
            f"{round(100 * THRESHOLDS['floor_share'])}% of the budget gives way to a cheaper option)")


def num(x):
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.2f}"


def small_team(c):
    return c["size"] <= THRESHOLDS["small_team"]
