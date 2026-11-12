"""Derived signals from validated input. Every derived value records the input paths it came from."""
import functools
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
# STRONG: a negated removal ("cannot be migrated") is a keep even though it contains a removal verb.
# REMOVE: the system is going away ("replace", "migrate off", "must not remain", "retain no", "to be retired", "will not keep").
# KEEP_RX: plain keep wording; in a description it must have the system itself as subject or object (see keep_in_text).
STRONG_KEEP_RX = (r"(?:cannot|can't|can not|won't|will not|must not|may not|should not|is not to) (?:be )?"
                  r"(?:migrat|replac|decommission|retir|remov|switch|mov|chang)\w*")
REMOVE_RX = (r"\breplac(?:e|ed|es|ing|ement)\b|\bmigrat\w* (?:off|away|out|from)\b|\bmov(?:e|ing) (?:off|away from)\b|decommission"
             r"|\bretir(?:e|ed|es|ing)\b|\bsunset|\bphas(?:e|ed|ing) out\b|\bretain no\b|\brewrit|\bend[- ]of[- ]life\b"
             r"|\b(?:not|never|no longer|don't|won't|cannot|can't) (?:be )?(?:keep|kept|retain|reus|remain|stay|preserv)")
KEEP_RX = (r"must (?:stay|remain|be kept|be retained|be reused|be preserved)|\bstays?\b|\bremains?\b|system of record|source of truth"
           r"|\bkeep(?:s|ing)?\b|\bkept\b|\breus(?:e|ed|ing)\b|\bretain\w*|\bpreserv\w*|\bas[- ]is\b|" + STRONG_KEEP_RX)
# words that may sit between a system's name and the keep wording without naming a different thing
_DB_NOUN = r"(?:\s+(?:v?\d[\w.]*|database|db|server|cluster|instance|deployment|tenant|replica set|broker))*"
_DETS = r"(?:(?:the|our|its|their|existing|current|legacy|old|same|this|that)\s+)*"
_AFTER_OBJ = (r"(?=\s*$|\s*[,.;:)(]|\s+(?:for|as|in|and|to|with|on|at|from|unchanged|intact|running|alive|until|because|since|so|but|or"
              r"|while|where|which|that|behind|beside|alongside)\b)")
_KEEP_VERB = r"\b(?:keep(?:s|ing)?|reus(?:e|es|ed|ing)|retain(?:s|ed|ing)?|preserv(?:e|es|ed|ing))\s+"
_KEEP_PRED = (r"\s+(?:must (?:stay|remain|be kept|be retained|be reused|be preserved)|(?:will |must |should )?(?:stays?|remains?)"
              r"|(?:is|are|will be) (?:kept|retained|preserved|reused)|(?:is|remains|stays) (?:the |our )?(?:system of record|source of truth)"
              r"|" + STRONG_KEEP_RX + r")")


def word_rx(pats):
    """Knowledge-base match patterns are regexes matched as whole words, case-insensitive ('teams' never in 'Teamspeak')."""
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(pats) + r")(?![a-z0-9])", re.I)


def keep_in_entry(low):
    """An existing_systems entry speaks about one system: a removal phrase wins unless the keep is a negated removal."""
    if re.search(STRONG_KEEP_RX, low):
        return True
    return not re.search(REMOVE_RX, low) and bool(re.search(KEEP_RX, low))


def keep_in_text(name_rx, text):
    """A description sentence keeps the system only when, within one clause, the system's own name is the object of a keep
    verb ('keep the Oracle database') or the subject of a keep predicate ('the Oracle database cannot be migrated'). A clause
    that removes it ('replace Oracle', 'migrate off MongoDB') or keeps something else ('reuse our Postgres dashboards') does not."""
    for clause in re.split(r"[,;:]\s*|\s+(?:but|while|whereas)\s+", text):
        if not re.search(name_rx, clause):
            continue
        name = r"(?:" + name_rx + r")" + _DB_NOUN
        if re.search(name + r"\s+" + STRONG_KEEP_RX, clause):
            return True
        if re.search(REMOVE_RX, clause):
            continue
        if re.search(_KEEP_VERB + _DETS + name + _AFTER_OBJ, clause) or re.search(name + _KEEP_PRED, clause):
            return True
    return False


# Server-side language named by an existing system (frameworks and app servers included; front-end frameworks are not).
# Node needs a version or an app noun ('Kubernetes node pool' is not Node.js).
EXISTING_LANG = {"java": r"\bjava\b|\btomcat\b|\bspring\b|\bjboss\b|\bwildfly\b|\bweblogic\b|\bwebsphere\b",
                 "python": r"\bpython\b|\bdjango\b|\bflask\b", "csharp": r"\.net\b|\bc#|\basp\.net\b",
                 "php": r"\bphp\b|\blaravel\b|\bsymfony\b", "ruby": r"\bruby\b|\brails\b", "go": r"\bgolang\b|\bgo \d",
                 "javascript": r"\bnode\.?js\b|\bnode\s*v?\d|\bnode (?:api|app|application|service|backend|server)s?\b|\bexpress\.?js\b"}
# 'Flask-shaped': a hyphenated modifier names a look, not the application; '-based'/'-powered' still name the stack
_COMPOUND = re.compile(r"-(?!(?:based|powered|backed|built|driven)\b)[a-z]")


def existing_langs(raws):
    """Languages of applications that keep running: an entry being decommissioned or rewritten does not count, and
    neither does a word used as a modifier."""
    out = set()
    for r in raws:
        low = r.lower()
        if re.search(REMOVE_RX, low) and not re.search(STRONG_KEEP_RX, low):
            continue
        for lang, rx in EXISTING_LANG.items():
            if any(not _COMPOUND.match(low, m.end()) for m in re.finditer(rx, low)):
                out.add(lang)
    return out


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


# F13: continent words in the description (whole words; country names do not count as a continent)
CONTINENTS = [("north_america", r"\bnorth america(?:n)?\b"), ("south_america", r"\b(?:south|latin) america(?:n)?\b|\blatam\b"),
              ("europe", r"\beurope(?:an)?\b"), ("asia", r"\basia(?:n)?\b|\bapac\b|\basia[- ]pacific\b"),
              ("africa", r"\bafrica(?:n)?\b"), ("oceania", r"\boceania\b"), ("middle_east", r"\bmiddle east\b")]


# D12a: a sentence states a data-residency requirement when it has a data noun and a residency verb phrase.
RES_DATA = r"\b(?:data|records?|backups?|pii|databases?|information|files?|documents?)\b"
RES_VERB = (r"\b(?:must|shall|should|has to|have to|needs? to|required to|is to|are to|to|will|may only|can only)\s+(?:only\s+)?"
            r"(?:stay|remain|reside|be (?:stored|hosted|kept|held|located|localised|localized|processed)|not (?:leave|be (?:stored|hosted|kept) outside))\b"
            r"|\bnever leaves?\b|\b(?:stored|hosted|kept|held|localised|localized|resident)\s+(?:only\s+)?(?:in|within)\b")


def residency_from_description(text):
    """D12a: project.description -> {'country', 'sentence', 'hints', 'ambiguous', 'conflict'}. A country is pinned only
    when residency sentences (data noun + residency verb) name exactly one country between them; regional words or
    two countries keep it unresolved ('ambiguous' / 'conflict' list the candidates). Place names elsewhere are 'hints'."""
    text = text or ""
    found, ambiguous = [], []
    for sent in re.split(r"(?<=[.!?;])\s+|\n", text):
        if not (re.search(RES_DATA, sent, re.I) and re.search(RES_VERB, sent, re.I)):
            continue
        cid, _, plaus = detect_country(sent)
        if cid:
            found.append((cid, sent.strip()))
        else:
            ambiguous += [p for p in plaus if p not in ambiguous]
    countries = list(dict.fromkeys(c for c, _ in found))
    cid, _, plaus = detect_country(text)
    hints = [cid] if cid else plaus
    out = {"country": None, "sentence": None, "hints": hints, "ambiguous": ambiguous, "conflict": []}
    if len(countries) == 1 and not ambiguous:
        out["country"], out["sentence"] = countries[0], found[0][1]
    elif len(countries) > 1:
        out["conflict"] = countries
    elif countries:  # one country sentence plus a regional / multi-country one
        out["ambiguous"] = countries + [p for p in ambiguous if p not in countries]
    return out


# Where an existing system says it runs: provider region codes/names and cities. London/Zurich regions are named first so
# 'eu-west-2' is the UK, not the EU. Only an exact single location counts; several or none -> None (unverified).
EXISTING_LOCATIONS = [
    (r"eu-west-2|europe-west2|uk ?south|uk ?west", "united_kingdom"),
    (r"eu-central-2|europe-west6|switzerland ?(?:north|west)", "switzerland"),
    (r"ap-south-[12]|asia-south[12]|(?:central|south|west|jio) ?india(?: \w+)?|india|indian|mumbai|pune|hyderabad|chennai|delhi"
     r"|bengaluru|bangalore|noida|gurugram|gurgaon|kolkata", "india"),
    (r"eu-[a-z]+-\d|europe-[a-z]+\d+|(?:west|north) ?europe|germany ?(?:west ?central|north)|france ?(?:central|south)"
     r"|sweden ?central|italy ?north|poland ?central|spain ?central|eu|europe|european union|frankfurt|dublin|ireland|paris"
     r"|amsterdam|netherlands|germany|france|stockholm|milan|madrid|warsaw|belgium|finland|italy|spain|sweden|poland", "eu"),
    (r"us-(?:east|west|central|north|south)[a-z]*-?\d|(?:east|west|central|north ?central|south ?central|west ?central) ?us ?\d?"
     r"|usa|u\.s\.a?\.?|united states|virginia|ohio|oregon|california|iowa|texas|arizona|illinois", "us"),
]


def existing_location(raw):
    """existing_systems entry -> 'india' / 'eu' / 'us' / a D12 country id, or None when no single location is stated."""
    hits = {loc for rx, loc in EXISTING_LOCATIONS if re.search(r"(?<![a-z0-9])(?:" + rx + r")(?![a-z0-9])", raw, re.I)}
    if "united_kingdom" in hits or "switzerland" in hits:
        hits.discard("eu")
    cid, _, _ = detect_country(raw)
    if cid and not hits & {"united_kingdom", "switzerland"}:
        hits.add(cid)
    return next(iter(hits)) if len(hits) == 1 else None


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


# F1 (round 11): the team's own server language named in project.description ("Rails shop", "the team writes Elixir",
# "our Django team"). Language or framework word -> language id. Whole words only; a match marks a primary language.
PRIMARY_WORDS = {"ruby": r"ruby(?: on rails)?|rails", "elixir": r"elixir|phoenix", "python": r"python|django|fastapi|flask",
                 "java": r"java|spring(?: boot)?", "kotlin": r"kotlin", "csharp": r"c#|\.net|asp\.net(?: core)?|dotnet",
                 "php": r"php|laravel|symfony", "go": r"golang|go", "rust": r"rust",
                 "javascript": r"node(?:\.?js)?|javascript|express", "typescript": r"typescript|nestjs"}
_TEAM_NOUN = r"(?:shop|team|house|developers|engineers|devs|programmers)"
_TEAM_VERB = (r"(?:team|we|developers|engineers)\s+(?:mostly |mainly |only |already |all )?(?:writes?|codes?|works?|builds?|knows?|uses?|is fluent|are fluent)"
              r"(?:\s+(?:in|with))?\s+(?:mostly |mainly |only )?")


def primary_langs(text):
    """Languages project.description names as the team's own (sorted ids)."""
    low = (text or "").lower()
    out = set()
    for lang, w in PRIMARY_WORDS.items():
        word = r"(?<![\w.#])(?:" + w + r")(?![\w#])"
        if re.search(word + r"\s+" + _TEAM_NOUN + r"\b", low) or re.search(_TEAM_VERB + word, low):
            out.add(lang)
    return sorted(out)


@functools.lru_cache(maxsize=8)
def desc_signals(desc):
    """Description flags and primary languages, computed once per description: counterfactual reruns rebuild the
    context ~125 times with the same (up to 20,000-character) text."""
    return {flag: bool(re.search(rx, desc)) for flag, rx in DESC_RULES}, tuple(primary_langs(desc))


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
    # F13: continents the description says users are on; geo_spread 'global' or two or more -> users span continents
    c["continents"] = [k for k, rx in CONTINENTS if re.search(rx, req["project.description"] or "", re.I)]
    c["multi_continent"] = c["geo"] == "global" or len(c["continents"]) >= 2
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
    # D12a: 'other' resolved from the extra field, else from one explicit residency sentence in the description
    c["country"] = c["country_path"] = c["country_sentence"] = None
    c["country_res"] = {"country": None, "sentence": None, "hints": [], "ambiguous": [], "conflict": []}
    if res == "other":
        r = c["country_res"] = residency_from_description(req["project.description"])
        rc = req.get("infrastructure.residency_country")
        stated = r["conflict"] or ([r["country"]] if r["country"] else [])
        if rc and any(x != rc for x in stated):
            r["conflict"] = [rc] + [x for x in stated if x != rc]
            r["conflict_field"] = True
        elif rc:
            c["country"], c["country_path"] = rc, "infrastructure.residency_country"
        elif r["country"]:
            c["country"], c["country_path"], c["country_sentence"] = r["country"], "project.description", r["sentence"]
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
    flags, prim = desc_signals(desc)
    c["desc"], c["primary_langs"] = dict(flags), list(prim)
    ex = []
    sentences = re.split(r"(?<=[.!?;])\s+|\n", desc)
    for raw in req["infrastructure.existing_systems"]:
        low = f" {raw.lower()} "
        hit = next((pat for pat in TECH["existing_patterns"] if word_rx(pat["match"]).search(low)), None)
        life = None
        norm = lifecycle_text(low)
        for lc in TECH["lifecycle"]:
            lead = r"(?<![a-z0-9])" if lc["pattern"][0].isalnum() else ""
            if re.search(lead + re.escape(lc["pattern"]) + r"(?!\d)", norm):
                life = lc
                break
        # "must stay": in the entry itself, or in a description sentence that names the same system (its patterns, or the
        # product's first word: 'Keep the Oracle database' names 'Oracle 19c')
        name_rx = None
        if hit:
            name_rx = r"(?<![a-z0-9])(?:" + "|".join(hit["match"] + ([re.escape(hit["product"].split()[0].lower())] if hit.get("product") else [])) + r")(?![a-z0-9])"
        keep = "infrastructure.existing_systems" if keep_in_entry(low) else "project.description" if hit and any(
            keep_in_text(name_rx, s) for s in sentences) else None
        # a tenant described only as workforce/staff identity is not a customer login directory
        workforce = bool(re.search(r"\b(?:workforce|employees?|staff)\b", low)) and not re.search(
            r"\b(?:customers?|consumers?|ciam|b2c|external|partners?|public)\b", low)
        ex.append({"raw": raw, "pattern": hit, "life": life, "keep": keep, "onprem": "on-prem" in low or "on prem" in low
                   or "onprem" in low or "on-premises" in low, "workforce": workforce})
    # list-order invariance: knowledge-base pattern order (identity, databases, brokers, ...), then name; unrecognised last
    order = {id(p): i for i, p in enumerate(TECH["existing_patterns"])}
    ex.sort(key=lambda e: (order[id(e["pattern"])] if e["pattern"] else len(order), e["raw"]))
    c["existing"] = ex
    c["existing_langs"] = existing_langs(req["infrastructure.existing_systems"])

    def of_kind(kind):  # every recognised system of a kind, the ones the input says must stay first (then list order above)
        return sorted((e for e in ex if e["pattern"] and e["pattern"]["kind"] == kind), key=lambda e: not e["keep"])
    dbs = of_kind("database")
    c["existing_db"] = dbs[0] if dbs else None
    # a database the input says must stay (system of record) is reused as THE database, not integrated beside a new one
    c["kept_db"] = c["existing_db"] if c["existing_db"] and c["existing_db"]["keep"] else None
    c["other_kept_dbs"] = [e for e in dbs[1:] if e["keep"]]
    queues, idps = of_kind("queue"), of_kind("identity")
    c["existing_queue"] = queues[0] if queues else None
    c["existing_idp"] = idps[0] if idps else None
    c["unused_existing"] = {"identity provider": idps[1:], "message broker": queues[1:]}
    c["idp_customer_login"] = bool(c["existing_idp"] and c["existing_idp"]["pattern"].get("customer_login")
                                   and not c["existing_idp"]["workforce"])
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
