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
    "decline_max_tier": 1,  # heuristic: up to this scale tier (<= 50,000 users, <= 2,000 concurrent) a requested cluster / microservices / blockchain / AI agent is declined
}

# types that may be static; web_app and internal_tool only when the description says the content is editorial
STATIC_TYPES = ("content_site", "other")
SOFT_TYPES = ("web_app", "internal_tool")
# description signals that mean stored user data, server-side work or integrations: any of them keeps the backend
DYNAMIC_FLAGS = ("payouts", "ledger", "kyc", "chat", "collab", "iot", "uploads", "otp", "sms", "web3", "digital_goods", "store_billing", "video_vod",
                 "video_call", "live_media", "jobs_dispatch", "approvals", "scoring_model", "scheduler", "user_data", "lending", "gps")
DYNAMIC_COMPLIANCE = ("hipaa", "rbi_localisation")  # regulated data is stored somewhere: not a pages-only site


def dynamic_fields(req, api_only, mobile):
    """Structured fields that ask for server-side behaviour (everything but payments)."""
    return (req["requirements.auth"] != "none" or req["requirements.realtime"] or req["requirements.file_media_storage"]
            or req["requirements.multi_tenant"] or req["requirements.ml_features"] != "none" or api_only or bool(mobile)
            or req["scale.workload"] == "write_heavy")


def dynamic_driver(c):
    """The input field that makes the app dynamic (first of: realtime, sign-in, multi-tenant, a description signal, regulated data)."""
    req, d = c["req"], c["desc"]
    if req["requirements.realtime"]:
        return "requirements.realtime"
    if req["requirements.auth"] != "none":
        return "requirements.auth"
    if req["requirements.multi_tenant"]:
        return "requirements.multi_tenant"
    if any(d[f] for f in DYNAMIC_FLAGS):
        return "project.description"
    return "compliance"


def dynamic_app(c):
    """True when a static-site generator cannot be the web frontend: the app needs live updates, sign-in, multi-tenant data or any description signal
    of server-side state (planning heuristic: a generator builds pages at deploy time, it holds no sessions and no live connection)."""
    req, d = c["req"], c["desc"]
    return bool(req["requirements.realtime"] or req["requirements.auth"] != "none" or req["requirements.multi_tenant"]
                or any(d[f] for f in DYNAMIC_FLAGS) or set(c["compliance"]) & set(DYNAMIC_COMPLIANCE))


def static_override(c):
    """'hosted_payments' (payments are a hosted button or link) or 'editorial' (a soft type with editorial content) when the input
    is static-eligible although the baseline rule would add a backend; otherwise None. c: the context under construction."""
    req, typ, d = c["req"], c["type"], c["desc"]
    if c["desktop"] and not c["web"]:
        return None  # A2: an installed desktop app is never a static site (localfirst.py decides its shape)
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


def quote(c, flag, keep_case=False):
    """The words of the description that set a signal (lower-case, as written), for output text. keep_case: the description's own capitals."""
    from .context import DESC_RX
    text = (c["req"]["project.description"] or "").replace("’", "'")
    m = re.search(DESC_RX[flag], text.lower())
    if m and keep_case and len(text.lower()) == len(text):
        return text[m.start():m.end()].strip()
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
    pct = f"{round(100 * floor / c['budget'])}% of" if c["budget"] >= 1 else "more than all of"
    return (f"{name} is estimated at about ${num(floor)}/month at the '{['tiny', 'small', 'medium', 'large'][c['tier']]}' tier, {pct} the "
            f"${num(c['budget'])}/month budget (budget.monthly_infra_usd; planning heuristic: an optional add-on above "
            f"{round(100 * THRESHOLDS['floor_share'])}% of the budget gives way to a cheaper option)")


def num(x):
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.2f}"


def small_team(c):
    return c["size"] <= THRESHOLDS["small_team"]


# ---- A1: requested or wished-for buzzwords (hype) are declined with a reason, not built
# A request is a sentence in which a stakeholder role asks / wants / suggests the thing, or which carries a hype word. Planning heuristics:
_ROLE = (r"(?:cto|cio|ceo|cfo|director|boss|board|investors?|executives?|management|managers?|stakeholders?|vp|head of \w+"
         r"|founders?|clients?|customers?|owners?)")
# request verbs only: a verb that merely reports ("read", "heard") or describes ("likes") is not a request
_ASK = (r"(?:ask(?:s|ed|ing)?|wants?|wanted|needs?|needed|requires?|required|wishes|wished|would like|must have|insists?|insisted|suggest\w*"
        r"|propos\w*|keen|demand\w*|expects?|expected|plans? to use|planned to use|pushing|pushes)")
# first person ("We want microservices"): only the direct form, so "we do not need" and "we run" never match
_FIRST = r"\b(?:we|i)\s+(?:(?:really|also|definitely|absolutely)\s+)?(?:want|need|require|insist|expect|would like|plan to use|must have)\b"
REQUEST_RX = r"\b" + _ROLE + r"\b(?:\W+\w+){0,6}?\W+" + _ASK + r"\b|" + _FIRST
# a hype term that is the object of one of these verbs ("migrate off Kubernetes", "avoid microservices") is being dropped, not asked for;
# up to four words may sit between verb and term, but not a word that starts a new object ("replace Heroku with Kubernetes")
DROP_RX = (r"\b(?:(?:migrat|mov)\w* (?:off|away from)|avoid\w*|rid of|drop\w*|replac\w*|stop(?:ped|ping)? using|leav\w*|abandon\w*"
           r"|retir\w*|sunset\w*|remov\w*)(?:\s+(?!(?:to|onto|into|with|by|for|and|or|in|instead|from|but)\b)[\w'-]+){0,4}\s+$")
HYPE_RX = (r"\b(?:buzz\w*|hype\w*|trendy|fashionable|modern look|cutting[- ]edge|state[- ]of[- ]the[- ]art|nice to have|to impress|for the wow)\b")
# project types for which a web3 term is usually the product itself: a role asking for it there is still a requirement
WEB3_NATIVE_TYPES = ("marketplace", "ecommerce", "gaming", "fintech", "social")
# (label, pattern, why it is declined at a small scale). The reasons are engineering judgement, not vendor facts.
HYPE_TERMS = (
    ("Kubernetes", r"\bkubernetes\b|\bk8s\b",
     "a cluster adds nodes to patch, upgrade and pay for, and its load-balancing is not needed by one deployable"),
    ("microservices", r"\bmicro-?services?\b|\bservice mesh\b",
     "separately deployed services multiply releases, monitoring and network failure modes without any scaling need"),
    ("blockchain", r"\bblockchain\b|\bnfts?\b|\bsmart contracts?\b|\bweb3\b|\bcryptocurrenc\w+",
     "a chain adds node or RPC costs and key handling for what a database with an append-only audit log already records"),
    ("an AI agent", r"\bai[- ]agents?\b|\bagentic\b|\bautonomous agents?\b",
     "an agent adds per-request model cost and unpredictable behaviour, and requirements.ml_features is none"),
    ("a 'future proof' architecture", r"\bfuture[- ]?proof\w*",
     "a simple design with portable data is what keeps change cheap; extra architecture now is cost without a trigger"),
    ("a Netflix-style architecture", r"\bnetflix\b",
     "architectures built for millions of simultaneous viewers solve a problem this load does not have"),
    ("event sourcing / CQRS", r"\bevent[- ]sourcing\b|\bcqrs\b",
     "two data models and a replay mechanism are extra moving parts when one relational schema covers the need"),
)


def _sentence(low, start, end):
    a = max((low.rfind(ch, 0, start) for ch in ".!?;\n"), default=-1) + 1
    nxt = [i for i in (low.find(ch, end) for ch in ".!?;\n") if i >= 0]
    return low[a:min(nxt) if nxt else len(low)]


def _live_hits(low, rx):
    from .context import clause_breaks, negated_at
    br = clause_breaks(low)
    return [m for m in re.finditer(rx, low) if not negated_at(low, br, m.start(), m.end())]


def dropped(low, m):
    """True when the hit m sits in a clause that moves away from it ("wants to migrate off Kubernetes")."""
    pre = low[:m.start()]
    pre = pre[max((pre.rfind(ch) for ch in ".!?;:,\n("), default=-1) + 1:]
    return bool(re.search(DROP_RX, pre + " "))


def requested(sentence, typ=None):
    """True when the sentence asks for / wishes for the thing rather than describing the product. `typ`: project.type; a role asking
    for a web3 term in a web3-native type is still a requirement (only hype words suppress there)."""
    if re.search(HYPE_RX, sentence):
        return True
    return bool(re.search(REQUEST_RX, sentence)) and typ not in WEB3_NATIVE_TYPES


def web3_only_requested(desc, typ):
    """True when every live web3 hit sits in a sentence that only asks for it (a stakeholder's wish or a hype word), so no on-chain
    component or crypto-payment caution is added for it. The caller applies it only where the decline also fires (small scale)."""
    from .context import DESC_RX
    low = (desc or "").lower().replace("’", "'")
    hits = _live_hits(low, DESC_RX["web3"])
    return bool(hits) and all(requested(_sentence(low, m.start(), m.end()), typ) and not dropped(low, m) for m in hits)


def declined_requests(c):
    """[(label, quoted words, reason)] for hype terms the description asks for although the scale tier is small. Terms the inputs
    justify (an existing cluster, a real web3 product, ml_features set) are not declined."""
    if c["tier"] > THRESHOLDS["decline_max_tier"]:
        return []
    req = c["req"]
    text = (req["project.description"] or "")
    low = text.lower().replace("’", "'")
    existing = " ".join(req["infrastructure.existing_systems"]).lower()
    out = []
    for label, rx, why in HYPE_TERMS:
        if label == "blockchain" and c["desc"]["web3"]:
            continue
        if label == "an AI agent" and req["requirements.ml_features"] != "none":
            continue
        if label in ("Kubernetes", "microservices") and re.search(rx, existing):
            continue
        for m in _live_hits(low, rx):
            if requested(_sentence(low, m.start(), m.end())) and not dropped(low, m):
                out.append((label, m.group(0).strip(), why))
                break
    return out


def decline_message(c, found, stack):
    """Text of OVERENGINEERING_REQUEST_DECLINED: what was asked, why it is not justified at these numbers, what is chosen instead."""
    names = [f[0] for f in found]
    lst = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    sent = next((s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n", c["req"]["project.description"] or "")
                 if any(re.search(rx, s, re.I) for lab, rx, _ in HYPE_TERMS if lab == found[0][0])), "")
    team = f" and a team of {c['size']}" if small_team(c) else ""
    msg = (f"project.description asks for {lst}" + (f" ('{sent if len(sent) <= 160 else sent[:157].rstrip() + '...'}')" if sent else "") + ". That is not adopted: at about "
           f"{c['users']:,} users (~{c['peak']:,} concurrent){team}, " + "; ".join(f"{f[0]}: {f[2]}" for f in found) + ". The stack chosen instead is "
           + stack + ", one deployable that the team can run and upgrade. Revisit the request when expected users pass about 50,000 or "
           "concurrent users pass about 2,000 (planning heuristic scale tiers), or when a measured bottleneck needs it.")
    if c["req"]["priorities.scalability"] == 5:
        msg += (" priorities.scalability is 5, but the expected load is far below the next tier; it is met by the growth path "
                "(larger instances and managed services first), not by adding architecture now.")
    return msg
