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

# Deterministic description rules (D7). Each: flag -> regex. They shape supporting services/warnings; ledger, markdown, internal_only and low_end also adjust core scores.
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
    ("video_vod", r"recorded video|video lectures?|short[- ]video|video (?:upload|sharing|library)|video-sharing|reels?\b|video[- ]on[- ]demand"),
    ("video_call", r"video (?:consult|calls?|chat|class|meeting)|live class|teleconsult|tele-consult|telehealth|live stream"),
    ("web3", r"\bnfts?\b|web3|blockchain|cryptocurrenc|wallet connect|smart contract"),
    ("scheduler", r"remind(?:er)?s?\b|\bcron\b|nightly|scheduled (?:jobs?|tasks?|emails?)|daily (?:email|digest|report)s?"),
    ("analytics", r"dashboards?|\breports?\b|analysts?|\bbi\b|ad-hoc (?:sql|quer)|data warehouse"),
]

# An existing system the input says must not be replaced (entry text or a description sentence naming it).
KEEP_RX = (r"must (?:stay|remain|be kept|be retained|be reused)|\bstays?\b|\bremains?\b|system of record|source of truth"
           r"|(?:cannot|can't|can not|won't|will not|must not) (?:be )?(?:migrat|replac)|\bkeep(?:s|ing)?\b|\bkept\b|\breus(?:e|ed|ing)\b|\bretain")

# Server-side language named by an existing system (frameworks and app servers included; front-end frameworks are not).
EXISTING_LANG = {"java": r"\bjava\b|\btomcat\b|\bspring\b|\bjboss\b|\bwildfly\b|\bweblogic\b|\bwebsphere\b",
                 "python": r"\bpython\b|\bdjango\b|\bflask\b", "csharp": r"\.net\b|\bc#|\basp\.net\b",
                 "php": r"\bphp\b|\blaravel\b|\bsymfony\b", "ruby": r"\bruby\b|\brails\b", "go": r"\bgolang\b|\bgo \d",
                 "javascript": r"\bnode(?:\.?js)?\b|\bexpress\.?js\b"}


def existing_langs(raws):
    return {lang for lang, rx in EXISTING_LANG.items() for r in raws if re.search(rx, r.lower())}


# D12: data_residency 'other' -> jurisdiction. Ids, display names and keywords from ../research/R15-regions-other.md.
# Whole-word, case-insensitive; acronyms in ACRONYMS match upper-case only (as written) so "mas", "sama" or "nia" in prose
# never pick a country. Lookbehinds keep "New Mexico", "North Korea", "New England" and "New South Wales" out.
COUNTRIES = {
    "australia": ("Australia", r"australian?|aussie|sydney|melbourne|canberra|brisbane|perth"),
    "singapore": ("Singapore", r"singaporean?|pdpa-sg"),
    "japan": ("Japan", r"japan(?:ese)?|tokyo|osaka"),
    "south_korea": ("South Korea", r"(?<!north )korean?|seoul|busan|k-isms"),
    "indonesia": ("Indonesia", r"indonesian?|jakarta|pdp law"),
    "united_kingdom": ("the United Kingdom", r"u\.k\.|united kingdom|british(?! columbia)|britain|(?<!new )england|scotland|(?<!new south )wales|london|uk gdpr"),
    "canada": ("Canada", r"canad(?:a|ian)|toronto|montr[eé]al|quebec|ottawa|vancouver|pipeda|law 25"),
    "brazil": ("Brazil", r"brazil(?:ian)?|brasil|s[aã]o paulo|rio|lgpd|bacen"),
    "uae": ("the UAE", r"united arab emirates|emirat(?:i|es)|dubai|abu dhabi"),
    "saudi_arabia": ("Saudi Arabia", r"saudi(?: arabia)?|riyadh|jeddah|dammam|vision 2030"),
    "qatar": ("Qatar", r"qatar[i]?|doha"),
    "israel": ("Israel", r"israeli?|tel aviv|jerusalem|haifa"),
    "south_africa": ("South Africa", r"south african?|johannesburg|cape town|pretoria|popia"),
    "switzerland": ("Switzerland", r"switzerland|swiss(?! army)|zurich|geneva|bern|ndsg|fadp"),
    "mexico": ("Mexico", r"(?<!new )mexic(?:o|an)|cdmx|quer[eé]taro|monterrey|lfpdppp"),
}
ACRONYMS = {"australia": "IRAP|APRA", "singapore": "MAS", "japan": "APPI|FISC", "south_korea": "PIPA",
            "indonesia": "OJK", "united_kingdom": "UK|NHS", "uae": "UAE|DIFC|ADGM|TDRA",
            "saudi_arabia": "KSA|NCA|SAMA", "qatar": "QCB|NIA", "south_africa": "SARB", "switzerland": "FINMA"}
# Regional words that name several jurisdictions (R15 "ambiguous" column): never pinned, only reported as plausible.
AMBIGUOUS = [
    (r"gulf|gcc", "i", ["uae", "saudi_arabia", "qatar"]),
    (r"middle east|mena", "i", ["uae", "saudi_arabia", "qatar", "israel"]),
    (r"MEA", "", ["uae", "saudi_arabia", "qatar", "israel", "south_africa"]),
    (r"apac|asia[- ]pacific|oceania|anz", "i", ["australia", "singapore", "japan", "south_korea", "indonesia"]),
    (r"south ?east asia|asean", "i", ["singapore", "indonesia"]),
    (r"SEA", "", ["singapore", "indonesia"]),
    (r"asia", "i", ["singapore", "japan", "south_korea", "indonesia"]),
    (r"(?:sub-saharan )?africa", "i", ["south_africa"]),
    (r"latam|latin america|south america", "i", ["brazil", "mexico"]),
    (r"north america", "i", ["canada", "mexico"]),
    (r"europe", "i", ["united_kingdom", "switzerland"]),
    (r"arabia", "i", ["saudi_arabia"]),
    (r"SA", "", ["saudi_arabia", "south_africa"]),
]


def detect_country(text):
    """project.description -> (country id or None, matched word, plausible ids). Exactly one jurisdiction named -> that
    one; several or only regional words -> None with the plausible list (D12)."""
    text = text or ""
    hits = {}
    for cid, (_, rx) in COUNTRIES.items():
        m = re.search(r"(?<!\w)(?:" + rx + r")(?!\w)", text, re.I)
        if not m and cid in ACRONYMS:
            m = re.search(r"(?<!\w)(?:" + ACRONYMS[cid] + r")(?!\w)", text)
        if m:
            hits[cid] = m.group(0)
    if len(hits) == 1:
        cid = next(iter(hits))
        return cid, hits[cid], []
    plaus = list(hits)
    for rx, flags, ids in AMBIGUOUS:
        if not hits and re.search(r"(?<!\w)(?:" + rx + r")(?!\w)", text, re.I if flags else 0):
            plaus += [i for i in ids if i not in plaus]
    return None, None, plaus


def lifecycle_text(low):
    """Normalise common product spellings so 'Node.js 18', 'node-18', 'ASP.NET Core 8', 'PostgreSQL14', 'Angular 1.x'
    meet the lifecycle patterns ('node 18', '.net 8', 'postgresql 14', 'angularjs'); a digit may not follow a pattern."""
    low = re.sub(r"node\s*\.?\s*js", "node", low)
    low = re.sub(r"\.net core", ".net", low)
    low = re.sub(r"angular\s*(?:\.?js\b|1(?:\.|x\b|\b))", "angularjs ", low)
    low = re.sub(r"\bmongo(?:\s*db)?\b", "mongodb", low)
    low = re.sub(r"\bcentos\s+linux\b", "centos", low)
    low = re.sub(r"\bruby\s+on\s+rails\b", "rails", low)
    low = re.sub(r"\boracle\s+database\b", "oracle", low)
    return re.sub(r"\b(node|python|postgresql|postgres|\.net|vue|mysql|angular|php|django|laravel|mongodb|centos|rails|ruby|oracle|elasticsearch|ubuntu)[\s\-_]*v?(?=\d)",
                  r"\1 ", low)


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
    rps = req["scale.peak_rps"]
    c["rps_tier"] = None
    if rps is not None:  # an explicit request rate is better evidence than people counts
        c["rps_tier"] = 0 if rps <= 20 else 1 if rps <= 200 else 2 if rps <= 2000 else 3
        tier = max(tier, c["rps_tier"])
    c["tier"] = tier
    c["data_gb"] = req["scale.data_volume_gb_12_months"] if req["scale.data_volume_gb_12_months"] is not None else 5
    c["langs"] = lang_norm(req["team.languages"])
    c["hiring"] = [x for x in lang_norm(req["team.hiring_languages"]) if x not in c["langs"]]
    c["geo"] = req["scale.geo_spread"]
    c["lock"] = req["infrastructure.lock_in_tolerance"]
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
    # users are in India when data must stay there or Indian data-protection/payment rules apply (DPDP covers data of
    # people in India even without a residency requirement); drives Indian SMS and payment providers
    c["india_users"] = res == "india" or "dpdp" in comp or "rbi_localisation" in comp
    c["res_key"] = res if res in ("india", "eu", "us") else None
    # D12: 'other' resolved to one jurisdiction from the extra field, else from the description
    c["country"] = c["country_path"] = c["country_word"] = None
    c["country_plausible"] = []
    if res == "other":
        if req.get("infrastructure.residency_country"):
            c["country"], c["country_path"] = req["infrastructure.residency_country"], "infrastructure.residency_country"
        else:
            cid, word, plaus = detect_country(req["project.description"])
            c["country_plausible"] = plaus
            if cid:
                c["country"], c["country_path"], c["country_word"] = cid, "project.description", word
    if c["country"]:
        c["residency"] = c["res_key"] = c["country"]
    c["res_label"] = COUNTRIES[c["country"]][0] if c["country"] else (c["residency"] or "").upper()
    # a named jurisdiction (india/eu/us or a resolved 'other'); rbi-derived India stays separate as before
    c["res_named"] = res in ("india", "eu", "us") or bool(c["country"])
    c["res_paths"] = ["infrastructure.data_residency"] + ([c["country_path"]] if c["country"] else [])
    c["self_host_only"] = c["deploy"] in ("on_premise", "air_gapped")
    c["no_internet"] = c["deploy"] == "air_gapped"
    c["prio"] = {k: req[f"priorities.{k}"] for k in ("cost", "time_to_market", "scalability", "performance",
                                                       "maintainability", "security")}
    desc = (req["project.description"] or "").lower()
    c["desc"] = {flag: bool(re.search(rx, desc)) for flag, rx in DESC_RULES}
    ex = []
    sentences = re.split(r"(?<=[.!?;])\s+|\n", desc)
    for raw in req["infrastructure.existing_systems"]:
        low = f" {raw.lower()} "
        hit = None
        for pat in TECH["existing_patterns"]:
            if any(m in low for m in pat["match"]):
                hit = pat
                break
        life = None
        norm = lifecycle_text(low)
        for lc in TECH["lifecycle"]:
            if re.search(re.escape(lc["pattern"]) + r"(?!\d)", norm):
                life = lc
                break
        # "must stay": in the entry itself, or in a description sentence that names the same system
        keep = "infrastructure.existing_systems" if re.search(KEEP_RX, low) else "project.description" if hit and any(
            re.search(KEEP_RX, s) and any(m.strip() in s for m in hit["match"]) for s in sentences) else None
        ex.append({"raw": raw, "pattern": hit, "life": life, "keep": keep, "onprem": "on-prem" in low or "on prem" in low
                   or "onprem" in low or "on-premises" in low})
    # list-order invariance: knowledge-base pattern order (identity, databases, brokers, ...), then name; unrecognised last
    order = {id(p): i for i, p in enumerate(TECH["existing_patterns"])}
    ex.sort(key=lambda e: (order[id(e["pattern"])] if e["pattern"] else len(order), e["raw"]))
    c["existing"] = ex
    c["existing_langs"] = existing_langs(req["infrastructure.existing_systems"])
    c["existing_db"] = next((e for e in ex if e["pattern"] and e["pattern"]["kind"] == "database"), None)
    # a database the input says must stay (system of record) is reused as THE database, not integrated beside a new one
    c["kept_db"] = c["existing_db"] if c["existing_db"] and c["existing_db"]["keep"] else None
    c["existing_queue"] = next((e for e in ex if e["pattern"] and e["pattern"]["kind"] == "queue"), None)
    c["existing_idp"] = next((e for e in ex if e["pattern"] and e["pattern"]["kind"] == "identity"), None)
    c["ms_idp"] = bool(c["existing_idp"] and c["existing_idp"]["pattern"].get("vendor") == "microsoft")
    c["existing_m365"] = next((e for e in ex if e["pattern"] and e["pattern"]["kind"] == "collaboration"), None)
    r = req
    typ = r["project.type"]
    c["type"] = typ
    dynamic_need = (r["requirements.auth"] != "none" or r["requirements.payments"] or r["requirements.realtime"]
                    or r["requirements.file_media_storage"] or r["requirements.multi_tenant"]
                    or r["requirements.ml_features"] != "none"  # offline alone: a static site precaches (services.py)
                    or c["api_only"] or bool(c["mobile"]))
    c["needs_backend"] = dynamic_need or typ in DYNAMIC_TYPES
    c["needs_db"] = c["needs_backend"]
    c["static_search"] = (not c["needs_backend"]) and r["requirements.full_text_search"]
    return c
