"""Derived signals from validated input. Every derived value records the input paths it came from."""
import bisect
import copy
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
# things a user uploads (a bare "devices upload readings" is not a file upload)
UPLOAD_OBJ = (r"(?:files?|documents?|docs?|pdfs?|photos?|images?|pictures?|videos?|scans?|bills?|receipts?|invoices?|attachments?"
              r"|certificates?|resumes?|cvs?|recordings?|audio|spreadsheets?|csv|forms?)")
DESC_RULES = [
    ("upi", r"\bupi\b"),
    ("recurring", r"\bemi\b|subscription|recurring|per[- ]seat|pay per seat|monthly plan"),
    ("payouts", r"get paid|payout|disburs|pay (?:out|providers|sellers|vendors)|split payment|commission"),
    ("ledger", r"ledger|double[- ]entry"),
    ("kyc", r"\bkyc\b|know your customer|identity verification"),
    ("chat", r"\bchat|messag"),
    ("collab", r"same board|collaborat|live cursor|multiplayer|co-edit|whiteboard|conflict-free|\bcrdts?\b"
               r"|edit(?:s|ing)? (?:the same|a shared) (?:document|doc|note|canvas|sheet|spreadsheet|diagram|text)"
               r"|(?:shared|collaborative) (?:notes?|canvas|spreadsheets?|text editor)|edit(?:ing)? together|simultaneous(?:ly)? edit"),
    # D13 right-sizing signals, read only for type gaming (engine/rightsize.py): genre vocabulary, no titles or product names
    ("turn_based", r"turn-based|turn based|\basynchronous\b|take (?:a|their) turn|card games?|board games?|\bpuzzles?\b|\btrivia\b|\bquiz"
                   r"|word games?|a move every"),
    ("fast_action", r"\bshooters?\b|\bfps\b|battle royale|\bmoba\b|\bracing\b|fighting game|action game|battle (?:game|arena)"
                    r"|real-?time (?:multiplayer|battles?|combat|pvp|matches)|\bpvp\b|tick[- ]rate|fast-paced"),
    ("markdown", r"markdown|\bmdx?\b"),
    # "GPs" (doctors) is not GPS: lower-case gps needs a location word; upper-case GPS is added in desc_signals.
    # gps = a location is recorded; media = photos or cameras. A photo is not a position (and the reverse).
    ("gps", r"\bgps[- ](?:track\w*|coordinates?|locations?|positions?|fix(?:es)?|pings?|tag\w*|enabled|data|traces?)\b"
            r"|\bgeo-?tag|\blat(?:itude)?\s*(?:/|,|and|&)\s*long(?:itude)?\b|\b(?:gps|geo\w*|map|location)[- ]coordinates?\b"),
    ("media", r"\bphotos?\b|\bphotograph\w*|\bcameras?\b"),
    # words that let a signal's text name lending only when the input does
    ("lending", r"\bloans?\b|\blend(?:ing|er|ers)?\b|\bborrowers?\b"),
    ("emi", r"\bemi\b"),
    ("low_bandwidth", r"\b2g\b|\b3g\b|intermittent|low bandwidth|poor (?:network|connectivity)|no signal|signal is available"),
    ("low_end", r"low-end|low end|2 ?gb ram|1 ?gb ram|budget phones?"),
    ("approvals", r"approv|leave request|workflow"),
    ("internal_only", r"only by employees|internal use|employees only|intranet"),
    ("jobs_dispatch", r"accept jobs|book |booking|dispatch|assign"),
    ("scoring_model", r"scoring model|credit scor|risk model|fraud model"),
    ("notifications", r"notif|alert|remind"),
    ("iot", r"\bsensors?\b|\biot\b|telemetry|\bdevices? (?:send|report|publish)|smart meters?|trackers? send"),
    ("digital_goods", r"in-app purchase|in-game|\bcoins\b|\bgems\b|unlock|premium (?:features|content|tier)|loot|battle pass"
                      # E11-3: wording that sells through the app stores (store billing is mandatory for digital goods there)
                      r"|(?:sold|billed|purchased|bought|charged|paid)\s+(?:\w+\s+){0,3}(?:through|via|in|on|with|using)\s+(?:the\s+)?(?:app stores?|apple app store|google play(?: store)?|play store)"
                      r"|\bapp[- ]store (?:billing|subscriptions?|purchases?)|\bstore (?:subscriptions?|billing)|in-app subscriptions?"),
    # E11-3: facts the description states that no enum field carries (each reads as a service or a named assumption)
    ("sms", r"\bsms\b|\btext[- ]messages? (?:reminders?|alerts?|notifications?|codes?)|\btexts? reminders?|\bwhatsapp (?:reminders?|alerts?|notifications?)"),
    ("otp", r"\botps?\b|one[- ]time (?:pass(?:word|code)s?|codes?)"),
    ("email_out", r"newsletters?|mailing lists?|\be-?mail (?:lists?|campaigns?|receipts?|confirmations?|digests?|reminders?|notifications?)"
                  r"|transactional e-?mails?|\b(?:confirmation|receipt|welcome|reminder|invoice|booking) e-?mails?"
                  r"|\b(?:go|goes|sent|send|sends|delivered|delivery)\s+(?:out\s+)?(?:by|via|through|over)\s+e-?mail"),
    ("uploads", r"\buploads?\b(?:\W+\w+){0,5}?\W+" + UPLOAD_OBJ + r"\b|\b" + UPLOAD_OBJ + r"\b(?:\W+\w+){0,3}?\W+uploaded\b"),
    ("video_vod", r"recorded video|video lectures?|short[- ]video|video (?:upload|sharing|library)|video-sharing|reels?\b|video[- ]on[- ]demand"),
    ("video_call", r"video (?:consult|calls?|chat|class|meeting)|live class|teleconsult|tele-consult|telehealth|live stream"),
    ("web3", r"\bnfts?\b|web3|blockchain|cryptocurrenc|wallet connect|smart contract"),
    ("scheduler", r"remind(?:er)?s?\b|\bcron\b|nightly|scheduled (?:jobs?|tasks?|emails?)|daily (?:email|digest|report)s?"),
    ("analytics", r"dashboards?|\breports?\b|analysts?|\bbi\b|ad-hoc (?:sql|quer)|data warehouse"),
]
DESC_RX = dict(DESC_RULES)

# Negation guard shared by every description signal (one helper, not one per signal). A hit counts unless a negation reaches it
# inside its own clause: before it ("no chat", "do not need a ledger", "without KYC") or right after it ("cameras are out of
# scope", "chat: not needed"). Clauses end at punctuation, at "but/however/yet/so/because/since/who/which/that" and at
# "..., and we/now/need ...". A short list ("no in-app chat or messaging", "not adding payments, UPI or cards") shares one cue.
# A negation does not apply when
#   (a) it is a double negation ("cannot ... without KYC", "nothing ships without approval"); "without" negates only when a word
#       comes before it in its sentence ("an app without chat"), so "Without KYC, no account opens" is a requirement,
#   (b) a loss or omission verb sits between the cue and the hit or follows it ("must not lose a ledger entry", "no messages are lost"),
#   (c) the negation is a prohibition or a complaint, not a scope decision: an imperative ("Do not send alerts", "Never assign two
#       jobs"), the rest of the clause says without/unless/until, the negation is about the past ("never used one before") or about
#       today ("Today, staff cannot chat"). Scope verbs ("do not need/plan/build/add ...") and "not needed" stay negations.
# Known limit: a negator more than one word before the hit (or 5 after a scope verb) is not seen, so the signal fires (a missed
# negation adds one supporting service; a false negation would drop a stated requirement). Only a window of _SCAN characters
# around each hit is examined, so cost is linear in the text length.
_SCAN = 120
_CLAUSE_BREAK = re.compile(r"[.!?;:,\n()\[\]]|\s[-\u2013\u2014]+\s"
                           r"|\b(?:but|however|although|though|yet|whereas|while|instead|so|because|since|who|which|that)\b"
                           r"|\band\s+(?:we|they|you|it|i|now|then|also|need|want|require)\b")
# a modal verb ends a relative clause ("users who don't have phones can still chat"): a negation does not reach past it;
# a hyphenated compound ("in-app") is one word
_W = r"(?:\W+(?!(?:can|could|will|would|should|may|might|must|shall)\b)\w+(?:-\w+)*)"
# kind "plain": reaches at most one word ("not chat", "no in-app chat"); "scope": a scope verb reaches further
_STRONG = (
    ("plain", re.compile(r"(?P<cue>\b(?:not|never|neither|nor|cannot)\b(?!\W+(?:only|just|merely|even)\b)|n't\b|\bno need(?: for| of)?\b"
                         r"|\bout of scope\b|\bno longer\b|\bdecided against\b|\brul(?:e|ed) out\b"
                         r"|(?<!can )(?<!may )(?<!could )(?<!might )\bskip(?:ping)?\b)" + _W + r"{0,1}\W*$")),
    ("scope", re.compile(r"(?P<cue>\b(?:not|never)\b|n't\b)\W+(?:plan|want|intend|build|need|use|include|require|support|add|offer"
                         r"|provide|allow|implement)\w*" + _W + r"{0,5}\W*$")),
    ("scope", re.compile(r"(?P<cue>\b(?:will|shall|would) not|\bwon't|\bwouldn't)\W+be\W+(?:any|an?|the)" + _W + r"{0,1}\W*$")),
    ("plain", re.compile(r"(?P<cue>\bnobody\b|\bno one\b|\bnone of\b)" + _W + r"{0,3}\W*$")),
    ("plain", re.compile(r"(?P<cue>\bno\b(?![- ]?code))" + _W + r"{0,2}(?:\W+(?:or|and|nor))?\W*$")),
)
_WEAK = re.compile(r"(?P<cue>\b(?:without|excluding|except)\b)" + _W + r"{0,4}\W*$")
_ANY_NEGATOR = re.compile(r"\b(?:not|never|no|neither|nor|cannot|nobody|nothing|none|no one)\b|n't\b")
_IMPERATIVE = re.compile(r"\W*(?:do\W*)?$")
_LOSS = re.compile(r"\b(?:lose|loses|losing|lost|miss|misses|missed|missing|skip(?:s|ped|ping)?|bypass(?:es|ed|ing)?"
                   r"|delete[sd]?|deleting|drop(?:s|ped|ping)?|leak(?:s|ed|ing|age)?|alter(?:s|ed|ing)?|edit(?:s|ed|ing)?"
                   r"|wait(?:s|ed|ing)?|forget(?:s|ting)?|forgot(?:ten)?|omit(?:s|ted|ting)?)\b")
_LATER_COND = re.compile(r"\b(?:without|unless|until)\b")
_PAST_AFTER = re.compile(r"\W*(?:before|previously|so far|until now|in the past)\b")
_NOW = re.compile(r"\b(?:today|currently|right now|at the moment|at present|as it stands|yet)\b")
_LABEL = re.compile(r"\s*(?::|[-\u2013\u2014]+\s)")
_LIST_NEXT = re.compile(r"\s*(?:or|and|nor)\b")
_LIST_LAST = re.compile(r"\W*(?:or|and|nor)\W*$")
_CONJ_OPEN = re.compile(r"(?:but|yet|while|whereas|although|though|however|instead|and\b.*)$")
_NEG_AFTER = re.compile(r"\W*(?:\w+\W+){0,2}?(?:(?:is|are|was|were|will be|would be|stays?|remains?)\s+)?"
                        r"(?:out of scope|ruled out|excluded|decided against|not a (?:requirement|priority|goal)"
                        r"|(?:not|no longer)\s+(?:needed|required|necessary|in scope|supported|used|planned|wanted|part)"
                        r"|(?:isn't|aren't|wasn't|weren't)\s+(?:needed|required|necessary|in scope|supported|used|planned|wanted))")


def clause_breaks(low):
    spans = [m.span() for m in _CLAUSE_BREAK.finditer(low)]
    return [b[0] for b in spans], [b[1] for b in spans]


def _cue(pre, opening):
    """The negation cue reaching the end of pre: (match, kind) with kind plain/scope/weak, or (None, None)."""
    found = []
    for kind, rx in _STRONG:
        m = rx.search(pre)
        if not m:
            continue
        before = pre[:m.start("cue")]
        word = m.group("cue")
        # an imperative prohibition ("Do not send alerts", "Never assign two jobs") states a rule, not a scope decision
        if kind == "plain" and _IMPERATIVE.match(before) and (
                word == "never" or (before.strip() and word in ("not", "n't") and re.search(r"\w", pre[m.end("cue"):]))):
            continue
        found.append((m, kind))
    strong = min(found, key=lambda t: (t[0].start(), t[1] != "scope")) if found else None
    weak = _WEAK.search(pre)
    if weak and weak.group("cue") != "excluding":
        # "without"/"except" negate only after a word ("an app without chat"); "Without KYC, no account opens" is a requirement
        if not re.search(r"\w", pre[:weak.start("cue")]) and not _CONJ_OPEN.match(opening):
            weak = None
    if weak and not strong and _ANY_NEGATOR.search(pre, 0, weak.start("cue")):
        weak = None  # double negation
    if strong and not weak:
        return strong
    if weak and not strong:
        return weak, "weak"
    return None, None


def negated_at(low, breaks, start, end):
    """True when low[start:end] sits in a clause that negates it (see the rules above)."""
    starts, ends = breaks
    i = bisect.bisect_right(ends, start)
    j = bisect.bisect_left(starts, end)
    ce = starts[j] if j < len(starts) else len(low)
    post = low[end:min(ce, end + _SCAN)]
    for _ in range(3):
        cs = ends[i - 1] if i else 0
        pre = low[max(cs, start - _SCAN):start]
        opening = low[starts[i - 1]:ends[i - 1]].strip() if i else ""
        cue, kind = _cue(pre, opening)
        # a comma list shares one cue: "not adding payments, UPI or cards"
        if cue or not i or opening != "," or not (_LIST_NEXT.match(post) or _LIST_LAST.match(pre)):
            break
        i -= 1
    if cue:
        neg = not _LOSS.search(pre, cue.end("cue"))
    else:
        kind = "after"
        label = post if post.strip() else low[end:end + _SCAN] if _LABEL.match(low, end) else ""
        neg = bool(_NEG_AFTER.match(label.split(".")[0] if label else post))
    if not neg or _LOSS.search(post) or _PAST_AFTER.match(post):
        return False
    if kind != "weak" and _LATER_COND.search(post):
        return False
    if kind == "plain":  # today's problem is a requirement ("Today, staff cannot chat")
        sp = low[max(0, start - 2 * _SCAN):start]
        sp = sp[max(map(sp.rfind, ".!?;\n")) + 1:]
        sq = low[end:end + 2 * _SCAN]
        m = re.search(r"[.!?;\n]", sq)
        if _NOW.search(sp + " " + (sq[:m.start()] if m else sq)):
            return False
    return True


def live_hit(rx, text, low, breaks, flags=0):
    """rx matches text outside every negated clause (low = lower-cased text of the same length, breaks = clause_breaks(low))."""
    same = len(text) == len(low)
    return any(not (same and negated_at(low, breaks, m.start(), m.end())) for m in re.finditer(rx, text, flags))


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


_CLOUD_WORDS = re.compile(r"\b(?:cloud|saas|managed|aws|azure|gcp|google|amazon|atlas|hosted by)\b")


def fallback_pattern(raw, low):
    """An existing system the knowledge base does not know by name, read by keyword (first matching category in knowledge-base
    order) into a stand-in pattern that the by-name handling (reused database / broker / identity provider, integration
    component) treats like a recognised one; None when no keyword names a kind of system."""
    for fb in TECH["existing_fallback"]:
        m = word_rx(fb["match"]).search(low)
        if not m:
            continue
        head = re.split(r"\s*[(,;]|\s+[-–—]\s", raw.strip(), maxsplit=1)[0].strip().rstrip(" .:") or fb["label"]
        name = head[:60].rstrip()
        pat = {"match": [re.escape(m.group(0))], "kind": fb["kind"], "name": name, "how": fb["how"], "src": fb["src"],
               "synthetic": True, "category": fb["category"], "label": fb["label"], "handled": fb["handled"],
               "keyword": m.group(0)}
        if fb["kind"] == "database":
            pat.update(engine="other", product=name)
        elif fb["kind"] == "identity":
            pat.update(reuse=True, provider="neutral", deployment="self_hosted")
        return pat
    return None


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
# "the Americas" names both American continents
_AMERICAS = r"\bamericas\b"
# a continent counts only in a sentence about who uses the product ("teams in Europe and Asia", not "Asian art styles")
_AUDIENCE = (r"\b(?:users?|customers?|clients?|traffic|teams?|visitors?|buyers?|players?|audiences?|subscribers?"
             r"|partners?|merchants?|sellers?|shoppers?|members?|consumers?|students?|patients?|tenants?|people"
             r"|used by|sell(?:s|ing)?|sold|serv(?:e|es|ed|ing))\b")


def continents_in(text):
    """F13: continents named in project.description sentences that also name the product's users or market."""
    found = set()
    for clause in re.split(r"(?<=[.!?;])\s+|\n", text or ""):
        if not re.search(_AUDIENCE, clause, re.I):
            continue
        found |= {k for k, rx in CONTINENTS if re.search(rx, clause, re.I)}
        if re.search(_AMERICAS, clause, re.I):
            found |= {"north_america", "south_america"}
    return [k for k, _ in CONTINENTS if k in found]


# D12a: a sentence states a data-residency requirement when it has a data noun and a residency verb phrase.
RES_DATA = r"\b(?:data|records?|backups?|pii|databases?|information|files?|documents?)\b"
RES_VERB = (r"\b(?:must|shall|should|has to|have to|needs? to|required to|is to|are to|to|will|may only|can only)\s+(?:only\s+)?"
            r"(?:stay|remain|reside|be (?:stored|hosted|kept|held|located|localised|localized|processed)|not (?:leave|be (?:stored|hosted|kept) outside))\b"
            r"|\bnever leaves?\b|\b(?:stored|hosted|kept|held|localised|localized|resident)\s+(?:only\s+)?(?:in|within)\b")


# a residency verb preceded by a negation in its sentence ("does not need to stay", "need not be stored") or a sentence that
# allows any location states no requirement
RES_NEGATED = r"\bnot\b|n't\b|\bno need\b|\bnever (?:need|has|have)\b"
RES_ANYWHERE = r"\bany (?:region|country|location|jurisdiction)\b|\banywhere\b"
# data_residency enum values the knowledge base covers directly (a country inside them, e.g. Germany -> eu)
RES_ENUM = ("india", "eu", "us")  # patterns: EXISTING_LOCATIONS below
_RES_PLACE = r"\b(?:in|within|inside)\s+(?:the\s+)?((?-i:[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?))"


def _residency_stated(sent):
    """A sentence states residency when a data noun and an un-negated residency verb appear and it allows no 'anywhere'."""
    if not re.search(RES_DATA, sent, re.I) or re.search(RES_ANYWHERE, sent, re.I):
        return False
    return any(not re.search(RES_NEGATED, sent[:m.start()], re.I) for m in re.finditer(RES_VERB, sent, re.I))


def residency_from_description(text):
    """D12a: project.description -> {'country', 'sentence', 'hints', 'ambiguous', 'conflict'}. A country is pinned only
    when residency sentences (data noun + residency verb) name exactly one country between them; regional words or
    two countries keep it unresolved ('ambiguous' / 'conflict' list the candidates). Place names elsewhere are 'hints'.
    Cached per text (counterfactual reruns rebuild the context ~125 times); callers get a copy they may change."""
    return copy.deepcopy(_residency_from_description(text or ""))


@functools.lru_cache(maxsize=8)
def _residency_from_description(text):
    found, ambiguous, enum, unsupported, stated = [], [], [], [], []
    for sent in re.split(r"(?<=[.!?;])\s+|\n", text):
        if not _residency_stated(sent):
            continue
        stated.append(sent.strip())
        cid, _, plaus = detect_country(sent)
        if cid:
            found.append((cid, sent.strip()))
        elif plaus:
            ambiguous += [p for p in plaus if p not in ambiguous]
        else:  # D12a: an enum-covered place (India, Germany -> eu, the US) or a country the knowledge base does not cover
            hits = [loc for rx, loc in EXISTING_LOCATIONS if loc in RES_ENUM and re.search(r"(?<![a-z0-9])(?:" + rx + r")(?![a-z0-9])", sent, re.I)]
            if re.search(r"(?<![A-Za-z])US(?![A-Za-z])", sent) and "us" not in hits:
                hits.append("us")
            if hits:
                enum += [(h, sent.strip()) for h in hits if h not in [e[0] for e in enum]]
            else:
                m = re.search(_RES_PLACE, sent)
                if m and m.group(1) not in unsupported:
                    unsupported.append(m.group(1))
    countries = list(dict.fromkeys(c for c, _ in found))
    cid, _, plaus = detect_country(text)
    hints = [cid] if cid else plaus
    out = {"country": None, "sentence": None, "hints": hints, "ambiguous": ambiguous, "conflict": [],
           "enum": enum, "unsupported": unsupported, "stated": stated}
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
    low = re.sub(r"\b(?:vb|visual\s+basic)[\s\-_]*6(?:\.0)?(?![\d.]*\d)", "visual basic 6", low)
    low = re.sub(r"\bwin(?:dows)?[\s\-_]*server[\s\-_]*(?=\d)", "windows server ", low)
    return re.sub(r"\b(node|python|postgresql|postgres|\.net|vue|mysql|angular|php|django|laravel|mongodb|centos|rails|ruby|oracle|elasticsearch|ubuntu)[\s\-_]*v?(?=\d)",
                  r"\1 ", low)


# F1 (round 11): the team's own server language named in project.description ("Rails shop", "the team writes Elixir",
# "our Django team"). Language or framework word -> language id. Whole words only; a match marks a primary language.
# Common English words count only in their language spelling: "Go"/"Golang" (never "go"), "Rust" (never "rust"), Express
# only as Express.js or "Express framework".
PRIMARY_WORDS = {"ruby": r"ruby(?: on rails)?|rails", "elixir": r"elixir|phoenix", "python": r"python|django|fastapi|flask",
                 "java": r"java|spring(?: boot)?", "kotlin": r"kotlin", "csharp": r"c#|\.net|asp\.net(?: core)?|dotnet",
                 "php": r"php|laravel|symfony", "go": r"golang|(?-i:Go|GO)", "rust": r"(?-i:Rust)",
                 "javascript": r"node(?:\.?js)?|javascript|express(?:\.?js| framework)", "typescript": r"typescript|nestjs"}
_PRIMARY_RX = {lang: re.compile(r"(?<![\w.#])(?:" + w + r")(?![\w#])", re.I) for lang, w in PRIMARY_WORDS.items()}
_TEAM_NOUN = re.compile(r"\s+(?:shop|team|house|developers|engineers|devs|programmers)\b", re.I)
_TEAM_VERB = re.compile(r"(?:team|we|developers|engineers)\s+(?:mostly |mainly |only |already |all )?(?:writes?|codes?|works?|builds?"
                        r"|knows?|uses?|is fluent|are fluent)(?:\s+(?:in|with))?\s+(?:mostly |mainly |only )?", re.I)
# a clause that negates, contrasts, looks back or plans hiring does not state the team's current language
_NOT_OWN = re.compile(r"\bnot\b|n't\b|\bnever\b|\bno longer\b|\bunlike\b|\bprevious(?:ly)?\b|\bformer(?:ly)?\b|\bleft\b"
                      r"|\bused to\b|\bhir(?:e|es|ed|ing)\b|\brecruit\w*|\bavoid\w*|\bmov(?:e|ed|ing) away\b|\bmigrat\w* away\b"
                      r"|\binstead of\b|\brather than\b", re.I)
_LIST_SEP = re.compile(r"\s*(?:,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+|&\s*|/\s*)", re.I)
# Round 16: experience phrasing. A team subject (we/team/developers/engineers...) earlier in the clause, then "have built
# [and maintained] <X> apps", "have been writing <X>", "years of <X>" or "experience(d) in/with <X>". After "have built" each
# listed language/framework must be followed by a product noun or the clause end ("We have run Spring sales" is not Java).
_EXP_SUBJ = re.compile(r"\b(?:we|i|team|developers|engineers|devs|programmers|founders)\b", re.I)
_EXP_VERB = r"(?:built|maintained|shipped|run|written|developed|delivered|operated)"
_EXP_BUILT = re.compile(r"(?:\bhave|\bhas|'ve)\s+(?:all\s+|both\s+|long\s+)?" + _EXP_VERB + r"(?:(?:\s*,\s*|\s+and\s+)" + _EXP_VERB
                        + r")*\s+(?:(?:with|in|on)\s+)?", re.I)
_EXP_OTHER = re.compile(r"(?:\bhave|\bhas|'ve)\s+been\s+(?:writing|coding|using|building|shipping|running|maintaining|working)(?:\s+(?:with|in|on))?\s+"
                        r"|\byears of\s+(?:(?:professional|production|hands-on|commercial)\s+)?(?:experience\s+(?:in|with)\s+)?"
                        r"|\b(?:experienced|experience|expertise|skilled|proficient)\s+(?:in|with)\s+", re.I)
_EXP_NOUN = re.compile(r"\s+(?:apps?|applications?|services?|sites?|websites?|backends?|apis?|projects?|systems?|platforms?|products?"
                       r"|code(?:bases?)?|monoliths?|microservices?|stacks?|servers?)\b", re.I)
_EXP_END = re.compile(r"\s+(?:for|since|professionally|in production)\b|\s*(?:[.,;:)]|$)", re.I)


def _lang_at(clause, pos):
    """(language id, end) of a language word starting exactly at pos, or None; hyphen compounds ('go-live') do not count."""
    for lang, rx in _PRIMARY_RX.items():
        m = rx.match(clause, pos)
        if m and not _COMPOUND.match(clause.lower(), m.end()):
            return lang, m.end()
    return None


def primary_langs(text):
    """Languages project.description names as the team's own (sorted ids): '<lang> shop/team/developers' or 'the team
    writes <lang>[, <lang> and <lang>]' or experience phrasing ('our developers have built Laravel apps for years', 'years
    of Django'), only in a clause without negation, contrast, past or hiring words."""
    out = set()
    for clause in re.split(r"(?<=[.!?;])\s+|\n|\s+but\s+|,\s+(?=(?:and |so |while |whereas )?(?:we|our|the|they|their|it|its|this|i)\b)",
                           text or "", flags=re.I):
        if _NOT_OWN.search(clause):
            continue
        for lang, rx in _PRIMARY_RX.items():
            if any(not _COMPOUND.match(clause.lower(), m.end()) and _TEAM_NOUN.match(clause, m.end()) for m in rx.finditer(clause)):
                out.add(lang)
        for v in _TEAM_VERB.finditer(clause):
            _walk_langs(clause, v.end(), out, False)
        for rx, need_noun in ((_EXP_BUILT, True), (_EXP_OTHER, False)):
            for v in rx.finditer(clause):
                if _EXP_SUBJ.search(clause[:v.start()]):
                    _walk_langs(clause, v.end(), out, need_noun)
    return sorted(out)


def _walk_langs(clause, pos, out, need_noun):
    """Add each language in a list starting at pos ('Python, Go and Rust'; 'Laravel apps and Django services'). With
    need_noun every item must be followed by a product noun or the clause end."""
    while True:
        hit = _lang_at(clause, pos)
        if not hit:
            return
        end = hit[1]
        noun = _EXP_NOUN.match(clause, end)
        if need_noun and not noun and not _EXP_END.match(clause, end):
            return
        out.add(hit[0])
        sep = _LIST_SEP.match(clause, noun.end() if noun else end)
        if not sep:
            return
        pos = sep.end()


@functools.lru_cache(maxsize=8)
def desc_signals(desc):
    """Description flags (lower-cased text) and primary languages (original case: 'Go' vs 'go'), computed once per
    description: counterfactual reruns rebuild the context ~125 times with the same (up to 20,000-character) text."""
    low = desc.lower().replace("\u2019", "'")
    breaks = clause_breaks(low)
    flags = {flag: live_hit(rx, low, low, breaks) for flag, rx in DESC_RULES}
    flags["gps"] = flags["gps"] or live_hit(r"\bGPS\b", desc, low, breaks)
    return flags, tuple(primary_langs(desc))


def num(x):
    """Plain number for prose: never an exponent; thousands separators from 10,000 (as the cost lines)."""
    if float(x).is_integer():
        n = int(x)
        return f"{n:,}" if abs(n) >= 10000 else str(n)
    return f"{x:,.2f}".rstrip("0").rstrip(".")


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
    c["continents"] = continents_in(req["project.description"])
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
    # Round 16: data_residency 'none' (or absent) while a D12a residency sentence in project.description states a
    # requirement. The stricter reading wins when the sentences name one supported jurisdiction (an enum-covered place such
    # as Germany -> eu, or one D12 country); a regional word ("Europe"), several places or an unsupported country keep
    # the field, and recommend.py only warns.
    c["res_stated"] = None
    if res == "none":
        r = residency_from_description(req["project.description"])
        if r["stated"]:
            vals = list(dict.fromkeys(v for v, _ in r["enum"]))
            pin, sent = None, r["stated"][0]
            if r["country"] and not vals and not r["unsupported"]:
                pin, sent = r["country"], r["sentence"]
                c["country"], c["country_path"], c["country_sentence"] = pin, "project.description", sent
            elif len(vals) == 1 and not (r["country"] or r["conflict"] or r["ambiguous"] or r["unsupported"]):
                pin, sent = vals[0], r["enum"][0][1]
                res = c["residency"] = c["res_key"] = pin
                c["india_users"] = c["india_users"] or pin == "india"
            c["res_stated"] = {"sentence": sent, "pin": pin, "ambiguous": r["ambiguous"] or r["conflict"],
                               "enum": vals, "unsupported": r["unsupported"]}
    if c["country"]:
        c["residency"] = c["res_key"] = c["country"]
    c["res_label"] = COUNTRIES[c["country"]][0] if c["country"] else (c["residency"] or "").upper()
    # a named jurisdiction (india/eu/us or a resolved 'other'); rbi-derived India stays separate as before
    c["res_named"] = res in ("india", "eu", "us") or bool(c["country"])
    c["res_paths"] = ["infrastructure.data_residency"] + ([c["country_path"]] if c["country"] else [])
    if c["res_stated"] and c["res_stated"]["pin"] and not c["country"]:
        c["res_paths"].append("project.description")
    c["self_host_only"] = c["deploy"] in ("on_premise", "air_gapped")
    c["no_internet"] = c["deploy"] == "air_gapped"
    c["prio"] = {k: req[f"priorities.{k}"] for k in ("cost", "time_to_market", "scalability", "performance",
                                                       "maintainability", "security")}
    flags, prim = desc_signals(req["project.description"] or "")
    desc = (req["project.description"] or "").lower()
    # the description only promotes a language team.languages already lists; it never adds one
    c["desc"], c["primary_langs"] = dict(flags), [x for x in prim if x in c["langs"]]
    ex = []
    sentences = re.split(r"(?<=[.!?;])\s+|\n", desc)
    for raw in req["infrastructure.existing_systems"]:
        low = f" {raw.lower()} "
        hit = next((pat for pat in TECH["existing_patterns"] if word_rx(pat["match"]).search(low)), None)
        hit = hit or fallback_pattern(raw, low)
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
            name_rx = r"(?<![a-z0-9])(?:" + "|".join(hit["match"] + ([re.escape(hit["product"].split()[0].lower())] if hit.get("product") and not hit.get("synthetic") else [])) + r")(?![a-z0-9])"
        keep = "infrastructure.existing_systems" if keep_in_entry(low) else "project.description" if hit and any(
            keep_in_text(name_rx, s) for s in sentences) else None
        # a tenant described only as workforce/staff identity is not a customer login directory
        workforce = bool(re.search(r"\b(?:workforce|employees?|staff)\b", low)) and not re.search(
            r"\b(?:customers?|consumers?|ciam|b2c|external|partners?|public)\b", low)
        onprem = "on-prem" in low or "on prem" in low or "onprem" in low or "on-premises" in low
        if hit and hit.get("synthetic"):  # read by keyword: a mainframe, or a system that must stay and is not said to be a cloud service, is estate to bridge to
            onprem = onprem or "mainframe" in low or bool(keep and not _CLOUD_WORDS.search(low))
        ex.append({"raw": raw, "pattern": hit, "life": life, "keep": keep, "onprem": onprem, "workforce": workforce})
    # list-order invariance: knowledge-base pattern order (identity, databases, brokers, ...), then keyword categories
    # (knowledge-base order), then name; unrecognised last
    order = {id(p): i for i, p in enumerate(TECH["existing_patterns"])}
    cats = {fb["category"]: len(order) + i for i, fb in enumerate(TECH["existing_fallback"])}
    ex.sort(key=lambda e: (order[id(e["pattern"])] if e["pattern"] and id(e["pattern"]) in order
                           else cats[e["pattern"]["category"]] if e["pattern"] else len(order) + len(cats), e["raw"]))
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
