"""H2: the description says a behaviour the boolean flags deny (live updates, search, an assistant, patchy connectivity, reminders
with no sender), and an existing identity provider that the description says staff sign in through.

The flags are hard inputs, so a mismatch never overrides them (uploads are the one old exception): it is a warning that quotes the
description phrase and names the flag. Every phrase goes through the shared negation guard (context.live_hit logic), so
"We do NOT need live updates" or "no search" never fires. Wording lists are planning heuristics: a test of each kind below shows what
fires and what must not."""
import functools
import re
from . import context as cx

# (key, flag path, flag value that conflicts, severity, regex). Planning heuristic: wording that states the behaviour as something the
# product must do (an update that happens instantly, a search over named things, a chat assistant), not a bare topic word.
_N = r"(?:\W+\w+)"
NEEDS = [
    ("realtime", "requirements.realtime", False, "warning",
     r"\b(?:updat\w*|refresh\w*|appear\w*|chang\w*|show\w*|sync\w*|reflect\w*|push\w*)\b" + _N + r"{0,4}?\W+"
     r"(?:instantly|immediately|in real[- ]?time|as (?:it|they|things) happens?|without (?:a )?(?:page )?(?:reload|refresh)\w*)"
     r"|\binstant(?:ly)? (?:updates?|notifications?|alerts?|bids?)\b|\bcountdown timers?\b"
     r"|\blive (?:updates?|bids?|bidding|auctions?|scores?|dashboards?|tracking|chat|feeds?|prices|leaderboards?|odds|quotes|location|notifications?)\b"
     r"|\breal[- ]?time (?:updates?|bids?|bidding|chat|messag\w*|notifications?|tracking|dashboards?|collaborat\w*|sync\w*|location|leaderboards?|multiplayer|alerts?)\b"),
    ("search", "requirements.full_text_search", False, "warning",
     r"\bkeyword search\b|\bfull[- ]text (?:search|index)\w*|\bsearch(?:es|ing)? (?:the |our |their |through |across |all )?(?:\w+ ){0,2}"
     r"(?:archives?|catalogu?es?|listings?|lots|products?|documents?|articles?|messages?|records?|inventory|library|knowledge base|items|posts|jobs|courses|files|notes|tickets|recipes)\b"
     r"|\b(?:search|find|filter)\w* (?:\w+ ){0,3}by (?:\w+ ){0,3}(?:keywords?|name|title|text|model|brand|tags?|content)\b"
     r"|\bsearch(?:able)? (?:box|bar|function|feature|results)\b|\bautocomplete\b|\btypeahead\b"),
    ("assistant", "requirements.ml_features", "none", "warning",
     r"\bchat ?bots?\b|\b(?:chat|ai|virtual|llm|smart|voice) assistants?\b|\bgrounded (?:in|on)\b|\banswers? (?:questions?|queries) (?:from|about|using|based on|over)\b"
     r"|\bquestion[- ]answering\b|\bretrieval[- ]augmented\b|\blarge language models?\b|\bllms?\b|\bgpt[- ]?\d?\b|\bcited answers\b"
     r"|\bnatural[- ]language (?:questions?|queries|search|interface)\b|\bsummari[sz]\w* (?:\w+ ){0,3}(?:with|using|by) (?:an? )?(?:ai|llm|language model)\b"),
    ("connectivity", "requirements.offline_support", False, "info",
     r"\b(?:patchy|spotty|flaky|unreliable|intermittent|poor|weak|unstable|slow)\b" + _N + r"{0,2}?\W+(?:wi-?fi|network|connection|connectivity|internet|signal|coverage)"
     r"|\b(?:wi-?fi|network|connection|connectivity|internet|signal)\b" + _N + r"{0,3}?\W+(?:drops?|dropped|cuts? out|goes down|is down|is patchy|is unreliable|is spotty|fails)"
     r"|\bdropped (?:connection|signal)s?\b|\bwork(?:s|ing)? (?:fully )?offline\b|\bwithout (?:a |any )?(?:network|connection|internet|signal|connectivity)\b"
     r"|\b(?:keep|continue|carry on|still)\s+work\w*\s+(?:\w+\s+){0,2}(?:if|when|while|without)\s+(?:\w+\s+){0,6}?(?:down|offline|disconnected|unavailable|connection|internet|network|wan|link)\b"),
    # q4: people sign in or hold accounts while requirements.auth is none
    ("signin", "requirements.auth", "none", "warning",
     r"\b(?:log|sign)(?:s|ged|ned)?[- ]?(?:in|on)\b(?:\W+\w+){0,3}?\W+(?:with|using|via|through)\W+(?:\w+\W+){0,3}?(?:google|apple|facebook|microsoft|github|linkedin|e-?mail|phone|passwords?|accounts?)\b"
     r"|\b(?:google|apple|facebook|github|microsoft|social) (?:log-?ins?|sign[- ]?ins?)\b"
     r"|\b(?:create|open|register)(?:s|d|ing)? (?:an? |their |his |her )?(?:own )?(?:accounts?|profiles?)\b"
     r"|\b(?:members?|users?|students?|customers?|players?|volunteers?|parents?|teachers?)\b(?:\W+\w+){0,2}?\W+(?:log|sign)(?:s|ged|ned)?[- ]?in\b"
     r"|\b(?:user|member|customer|student|player) (?:accounts?|log-?ins?)\b|(?<!wi-fi )(?<!wifi )(?<!router )(?<!network )(?<!door )\bpasswords?\b"),
    # q4: a trained model or machine-learning feature while requirements.ml_features is none (an assistant / LLM is the 'assistant' row)
    ("model", "requirements.ml_features", "none", "warning",
     r"\b(?:train(?:s|ed|ing)?|fine[- ]?tun\w+|retrain\w*)\b(?:\W+\w+){0,5}?\W+(?:classifiers?|models?|neural networks?|recommenders?)\b"
     r"|\b(?:trained|ml|machine[- ]learning|deep[- ]learning|predictive|forecasting) (?:classifiers?|models?|engines?)\b|\brecommendation models?\b"
     r"|(?<!rule-based )(?<!rules-based )\bmachine[- ]learning\b|\b(?:image|speech|face|facial|object) (?:recognition|classification|detection)\b|\bcomputer vision\b"
     r"|\bautomatically classif(?:y|ies|ied)\b|\bclassif(?:y|ies|ied|ying)\b(?:\W+\w+){0,4}?\W+(?:automatically|with (?:a|an|our) (?:\w+ )?model)\b"),
]

# q4: the reverse case. The flag is set and the description plainly says the product does not do it. Matched as written (the negation is
# the point), quoted, and the flag still wins. (key, flag path, flag-is-set test, severity, regex). Planning heuristic wording lists.
DENIES = [
    ("payments", "requirements.payments", lambda v: bool(v), "warning",
     r"\b(?:do not|don't|does not|doesn't|will not|won't|never|cannot|can't)\s+(?:take|accept|process|handle|collect|charge|do)\s+(?:any\s+|online\s+|in-app\s+)*payments?\b"
     r"|\bno\s+(?:online\s+|in-app\s+)?payments?\b(?!\s+(?:gateway|provider|method))"
     r"|\bpayments?\s+(?:are|is)\s+(?:not (?:needed|required|taken|handled|part\b)|out of scope|settled (?:offline|outside|in person|in cash)|handled (?:offline|outside|in person|in cash))"
     r"|\bwithout\s+(?:any\s+)?(?:online\s+)?payments?\b|\bno money changes hands\b"),
    ("signin", "requirements.auth", lambda v: v != "none", "warning",
     r"\bno (?:log-?ins?|sign[- ]?ins?|accounts?|registration)\b(?: (?:is|are) (?:needed|required))?"
     r"|\bwithout (?:any )?(?:log-?in|sign[- ]?in|signing in|logging in|an account|accounts|registration|registering)\b"
     r"|\b(?:do|does) not (?:need|have) to (?:log|sign) in\b|\b(?:nobody|no one) (?:logs|signs) in\b"),
]

_TEXT = {
    "realtime": ("DESC_VS_FLAG_REALTIME",
                 "says the screen must change live ('{q}') but requirements.realtime is false. The flag is a hard input, so no realtime layer was added: "
                 "the stack serves normal requests and the screen refreshes by polling. Set requirements.realtime to true to add a WebSocket/managed realtime "
                 "layer, or take the live wording out of the description."),
    "search": ("DESC_VS_FLAG_SEARCH",
               "has users searching ('{q}') but requirements.full_text_search is false. The flag is a hard input, so no search service was added: lookups use the "
               "database's own filters and indexes. Set requirements.full_text_search to true to add text search (ranking, typo tolerance), or take the search "
               "wording out of the description."),
    "assistant": ("DESC_VS_FLAG_ASSISTANT",
                  "describes an assistant or question-answering feature ('{q}') but requirements.ml_features is 'none'. The flag is a hard input, so no language-model "
                  "or retrieval layer was added. Set requirements.ml_features to llm_rag (answers grounded in your own documents, with the sources shown) or "
                  "inference_api to add it, or take the assistant wording out of the description."),
    "connectivity": ("DESC_VS_FLAG_OFFLINE",
                     "says the connection can drop ('{q}') but requirements.offline_support is false. The flag is a hard input, so no offline layer was added. Without "
                     "one a dropped connection loses whatever the user was doing: set offline_support to true for a local queue that keeps each action (a scan, a form) "
                     "on the device and sends it when the network returns, or make every action idempotent and retry it from the client."),
    "signin": ("DESC_VS_FLAG_AUTH",
               "has people signing in or holding accounts ('{q}') but requirements.auth is 'none'. The flag is a hard input, so no sign-in component and no user "
               "store were added: nothing in this stack knows who a visitor is. Set requirements.auth (email_password, social, phone_otp or enterprise_sso) to add "
               "sign-in, or take the account wording out of the description."),
    "model": ("DESC_VS_FLAG_ML",
              "describes a trained model or machine-learning feature ('{q}') but requirements.ml_features is 'none'. The flag is a hard input, so no model "
              "training, model serving or ML cost was added. Set requirements.ml_features to training (you train and serve your own model) or inference_api "
              "(you call a hosted model) to add it, or take the model wording out of the description."),
}
_DENY_TEXT = {
    "payments": ("DESC_DENIES_FLAG_PAYMENTS",
                 "says the product takes no payments ('{q}') but requirements.payments is true. The flag is a hard input, so a payments component was added and "
                 "sized. If the description is right, set requirements.payments to false: the payments component, its card-data notes and its fees then leave the "
                 "stack and the cost band."),
    "signin": ("DESC_DENIES_FLAG_AUTH",
               "says people use the product without signing in ('{q}') but requirements.auth is '{v}'. The flag is a hard input, so sign-in was added. If the "
               "description is right, set requirements.auth to none: the sign-in component and the user store then leave the stack."),
}


QUOTE_MAX = 110  # planning heuristic: longest quote of the description put into a warning


# a clause that hands the thing to someone else or rules it out ("decided against any AI features", "handled by the existing LinkedIn integration")
LOCAL_NEG_RX = r"(?<!\w)(?:decided against|ruled out|instead of|rather than|handled by|taken care of by)(?!\w)"


def _sentence(text, start, end):
    brk = (".", ";", "!", "?", chr(10))
    a = max(text.rfind(c, 0, start) for c in brk) + 1
    cuts = [k for k in (text.find(c, end) for c in brk) if k >= 0]
    return text[a:min(cuts) if cuts else len(text)]


def _clause(desc, start, end):
    """The clause of desc around [start, end): between the nearest sentence or comma breaks, cut at a word when long."""
    breaks = (".", ";", "!", "?", ",", chr(10))
    a = max(desc.rfind(c, 0, start) for c in breaks) + 1
    cuts = [k for k in (desc.find(c, end) for c in breaks) if k >= 0]
    b = min(cuts) if cuts else len(desc)
    q = desc[a:b].strip()
    if len(q) > QUOTE_MAX:
        q = q[:QUOTE_MAX].rsplit(" ", 1)[0] + " ..."
    return q


def first_live(rx, desc, local_neg=False):
    """(phrase, clause) of the longest match of rx in desc that no negation reaches (the first on a tie), or None. The clause is quoted in warnings.
    Pure in its arguments, and the counterfactual runs re-read the same description many times, so the result is cached."""
    return _first_live(rx, desc, local_neg)


@functools.lru_cache(maxsize=512)
def _first_live(rx, desc, local_neg):
    low = desc.lower().replace("’", "'")
    breaks = None  # computed on the first match: clause_breaks scans the whole text, which is slow on a long description with no match
    same = len(low) == len(desc)
    best = None
    for m in re.finditer(rx, low):
        if breaks is None:
            breaks = cx.clause_breaks(low)
        if same and cx.negated_at(low, breaks, m.start(), m.end()):
            continue
        if re.search(r"(?<!\w)(?:not|never|no|nor)(?!\w)|n't", m.group(0)):
            continue  # the phrase itself carries the negation ("do not sign in through ...")
        if local_neg and re.search(LOCAL_NEG_RX, _sentence(low, m.start(), m.end())):
            continue
        if best is None or len(m.group(0)) > len(best.group(0)):
            best = m
    return (best.group(0), _clause(desc, best.start(), best.end())) if best else None


def mismatches(ctx):
    """[(code, severity, message, fields)]: a behaviour the description needs that its flag denies."""
    req = ctx["req"]
    desc = req["project.description"] or ""
    out = []
    if not desc:
        return out
    for key, path, bad, sev, rx in NEEDS:
        if req[path] != bad:
            continue
        if key == "realtime" and (ctx["local_first"] or not ctx["needs_backend"]):
            continue  # a static site's refreshed figures (A18) and a local app have no server to push from
        if key == "connectivity" and ctx["local_first"]:
            continue  # a local-first desktop app is offline by design
        if key == "model" and first_live(dict((k, r) for k, _, _, _, r in NEEDS)["assistant"], desc, local_neg=True):
            continue  # the assistant row already says it
        hit = first_live(rx, desc, local_neg=True)
        if hit:
            code, text = _TEXT[key]
            out.append((code, sev, "project.description " + text.format(q=hit[1]), [path, "project.description"]))
    low = desc.lower().replace("\u2019", "'")
    for key, path, is_set, sev, rx in DENIES:  # q4: the flag is set, the description says the product does not do it
        m = re.search(rx, low) if is_set(req[path]) else None
        if m and key == "payments" and re.search(r"ourselves|directly|\bstor\w*|\bkept\b|\bsaved?\b|\bhandle[sd]?\b|stripe|razorpay|paypal|checkout|gateway|"
                                                 r"provider|third[- ]party|hosted", _clause(low, m.start(), m.end())):
            m = None  # "we never process payments ourselves; Stripe Checkout handles it" still takes payments
        if m and key == "signin" and re.search(r"\b(?:sign|log)(?:s|ged|ned)?[- ]?(?:in|on|up)\b|\bat checkout\b|\bcreate an account\b", low[m.end():]):
            m = None  # "browse without an account and sign in only at checkout" still signs people in
        if m and len(low) == len(desc):
            code, text = _DENY_TEXT[key]
            out.append((code, sev, "project.description " + text.format(q=_clause(desc, m.start(), m.end()), v=req[path]), [path, "project.description"]))
    return out


# ---- reminders with no sender
REMINDER_RX = r"\bremind(?:er|ers|s)?\b(?!\s+(?:me|you|them|us)\b)"
CHANNEL_RX = r"\b(?:e-?mails?|sms|text messages?|texts|whatsapp|push|notifications?)\b"


def reminder_without_sender(ctx):
    """The description schedules reminders and names no channel, and nothing in the stack delivers one: a reminder needs a sender."""
    d, desc = ctx["desc"], ctx["req"]["project.description"] or ""
    if not (d["scheduler"] and ctx["needs_backend"]) or d["email_out"] or d["sms"] or ctx["mobile"]:
        return None
    if first_live(CHANNEL_RX, desc):
        return None  # the description names a channel ("reminder notifications in the browser"): nothing to assume
    hit = first_live(REMINDER_RX, desc)
    return None if hit and "snooz" in hit[1].lower() else hit


def reminder_warning(ctx):
    hit = reminder_without_sender(ctx)
    if not hit:
        return None
    return ("REMINDER_SENDER_NOT_SELECTED", "info",
            f"project.description schedules reminders ('{hit[1]}') and a scheduler is in the stack, but nothing says how a reminder reaches a person: "
            "no e-mail, SMS or push channel is named, and no requirement flag covers one. A scheduler only decides when. E-mail is assumed and a transactional e-mail "
            "API with an authenticated sending domain was added; if reminders must go by SMS (per-message fees"
            + (", and registered sender IDs and templates for Indian numbers" if ctx["india_users"] or ctx["residency"] == "india" else "")
            + ") or push, name that in the description so it is designed and priced.",
            ["project.description"])


# ---- an existing identity provider that staff sign in through
STAFF_WHO = (r"(?:staff|employees?|workforce|clinicians?|doctors?|nurses?|physicians?|teachers?|faculty|administrators?|admins?|agents?|officers?|analysts?"
             r"|caseworkers?|operators?|technicians?|team members|personnel|back[- ]office users?|internal users?|moderators?|managers?)")
_IDP_NAMES = (r"(?:identity provider|idp|sso|single sign[- ]on|domain|directory|active directory|okta|entra|azure ad|keycloak|google workspace|ad ?fs|ldap"
              r"|ping(?: identity)?|auth0|onelogin|jumpcloud|authentik)")
_LOGIN_NOUN = r"(?:log-?ins?|accounts?|credentials?|identit(?:y|ies)|sso)"
_SIGN_VERB = r"(?:sign(?:s|ed)?[- ]?(?:in|on)|log(?:s|ged)?[- ]?(?:in|on)|authenticat\w*)"
STAFF_SIGNIN = (
    # staff + a sign-in verb + a named login system (or a company/hospital/school login noun)
    r"\b" + STAFF_WHO + r"\b(?:\W+\w+){0,4}?\W+" + _SIGN_VERB + r"\b(?:\W+\w+){0,6}?\W+(?:" + _IDP_NAMES
    + r"|(?:corporate|company|hospital|school|university|existing|work|network|windows) " + _LOGIN_NOUN + r")\b"
    # staff + "use their/the/our" + a login noun ("use their domain logins"); "use the company car booking page" has none
    r"|\b" + STAFF_WHO + r"\b(?:\W+\w+){0,4}?\W+use (?:their|the|our)\b(?:\W+\w+){0,3}?\W+" + _LOGIN_NOUN + r"\b"
    # a sign-in verb + through/via/with + a named login system, staff named in the same clause (checked in staff_signin)
    r"|\b" + _SIGN_VERB + r"\b(?:\W+\w+){0,4}?\W+(?:through|via|with|using|by|from)\W+(?:\w+\W+){0,4}?"
    r"(?:identity provider|idp|sso|single sign[- ]on|domain (?:log-?ins?|accounts?|credentials?)|directory|active directory|okta|entra|azure ad|keycloak"
    r"|google workspace|ad ?fs|ldap|ping(?: identity)?|auth0|onelogin|jumpcloud|authentik)\b"
    # a phrase that names the login itself
    r"|\b(?:domain log-?ins?|domain accounts?|domain credentials?|single sign[- ]on|corporate (?:log-?ins?|credentials?|accounts?|identity)|work (?:accounts?|log-?ins?))\b")


def staff_signin(ctx):
    """The first live sentence in which staff sign in through an existing login system, or None. Needs an existing identity provider."""
    if not ctx.get("existing_idp"):
        return None
    desc = ctx["req"]["project.description"] or ""
    hit = first_live(STAFF_SIGNIN, desc)
    # the sentence must also say who (staff) unless the phrase itself is a domain/corporate login
    if hit and not re.search(r"\b" + STAFF_WHO + r"\b|\bdomain\b|\bcorporate\b", hit[1].lower()):
        return None
    return hit


# narrow roles that are the organisation's own people (planning heuristic): an "agent", "manager" or "admin" may be a customer of the product
INTERNAL_ROLE_RX = (r"\b(?:staff|employees?|workforce|personnel|clinicians?|doctors?|nurses?|physicians?|teachers?|faculty|caseworkers?"
                    r"|back[- ]office users?|internal users?)\b")
# Planning heuristics: wording lists that keep the "staff sign in through the directory" inference to projects whose users are the organisation's own people.
# Staff of another party ("customers' purchasing staff") are not covered; on a portal for customers, citizens or the public only a specific internal role
# (clinician, teacher, caseworker ...) counts, not the bare word "staff"/"employees", which usually names who already holds a directory login.
_OTHER_PARTY = r"(?:customers?|clients?|citizens?|consumers?|buyers?|suppliers?|vendors?|partners?|dealers?|distributors?|resellers?|tenants?|residents?|members)"
OTHER_PARTY_STAFF_RX = r"\b" + _OTHER_PARTY + r"(?:['\u2019]s|s['\u2019])\s+(?:\w+\s+){0,2}?(?:staff|employees?|workforce|personnel|team members)\b"
PUBLIC_AUDIENCE_RX = (r"\b(?:citizen|customer|client|public|consumer|resident|supplier|dealer|distributor|reseller)s?\s+(?:self[- ]service\s+)?(?:portal|app|site|website|platform)\b"
                      r"|\bportal\s+(?:for|to serve)\s+(?:its |our |the |their )?(?:\w+\s+){0,2}?(?:customers?|clients?|citizens?|consumers?|residents?|suppliers?|dealers?|the public|members of the public)\b"
                      r"|\b(?:app|site|website|platform|service)\s+(?:built\s+)?for\s+(?:its |our |the |their )?(?:customers|citizens|clients|consumers|residents|the public)\b")
GENERIC_ROLE_RX = r"\b(?:clinicians?|doctors?|nurses?|physicians?|teachers?|faculty|caseworkers?|back[- ]office users?|internal users?)\b"
INFERRED_STAFF_TYPES = ("internal_tool", "healthtech")  # on-premises stacks of these types are run for the organisation's own staff (planning heuristic)


def inferred_staff_directory(ctx):
    """(phrase, None) when an on-premises directory (Active Directory, LDAP) is an existing system and the people who work with the system
    are staff of the organisation that runs it: the description names an internal role (staff, employees, clinicians, teachers ...), or the
    stack is an on-premises / air-gapped internal tool or healthcare system (planning heuristic). The directory is where those staff already have
    logins, so they sign in through it even if the description does not say so."""
    idp = ctx.get("existing_idp")
    if not idp or not idp["pattern"]["name"].startswith("On-premises"):
        return None
    desc = ctx["req"]["project.description"] or ""
    desc = re.sub(OTHER_PARTY_STAFF_RX, " ", desc, flags=re.I)  # "customers' purchasing staff" are not the organisation's staff
    role = first_live(GENERIC_ROLE_RX if re.search(PUBLIC_AUDIENCE_RX, desc, re.I) else INTERNAL_ROLE_RX, desc)
    if role:
        return (role[0], None)
    if ctx["self_host_only"] and ctx["type"] in INFERRED_STAFF_TYPES:
        return ("an on-premises deployment run by the organisation's staff", None)
    return None


def staff_sso_applies(ctx):
    """An existing IdP the description says staff sign in through, while the customer-facing auth does not already use it."""
    idp, auth = ctx.get("existing_idp"), ctx["req"]["requirements.auth"]
    if not idp or auth in ("enterprise_sso", "none"):
        return None
    if idp["pattern"].get("reuse") and ctx["idp_customer_login"] and auth in ("email_password", "social"):
        return None  # the provider is already the sign-in for everyone
    hit = staff_signin(ctx) or inferred_staff_directory(ctx)
    if not hit:
        return None
    if ctx["no_internet"] and idp["pattern"].get("deployment") == "saas":
        return None  # an air gap cannot reach a SaaS identity provider
    return hit


# ---- deliverables the description names that no hard flag or layer covers (CMS, image-heavy pages, offline video, a site that survives a WAN outage)
# Planning heuristics: wording lists. Each deliverable becomes a quoted note (info warning, or an assumption for the site-survives-WAN-outage case);
# no product is added to the stack, so the layer choices never move.
CMS_RX = (r"\bcms\b(?!\s+colou?r)|\bcontent management(?: system)?s?\b"
          r"|\b(?:editors?|journalists?|writers?|authors?|reporters?|content team)\b(?:\W+\w+){0,3}?\W+(?:publish|post|write|edit|update)\w*\b(?:\W+\w+){0,3}?\W+(?:through|via|in|with|using|from)\b(?:\W+\w+){0,2}?\W+(?:cms|admin(?:istration)? (?:panel|section|interface|area)|backend)")
EXISTING_CMS_RX = r"cms|wordpress|drupal|contentful|strapi|sanity|ghost|wagtail|joomla|sitecore|aem"
IMAGE_HEAVY_RX = (r"\b(?:photo|image|picture|pictures|photos|images)[- ]?(?:galler(?:y|ies)|librar(?:y|ies)|heavy|grids?|catalogu?es?|portfolios?)\b"
                  r"|\bimage[- ]heavy\b|\bphoto[- ]heavy\b|\bhigh[- ]res(?:olution)? (?:photos?|images?)\b"
                  r"|\b(?:product|property|listing|vehicle|recipe|artwork|portfolio) (?:photos|images|pictures)\b")
OFFLINE_VIDEO_RX = (r"\b(?:video|videos|lessons?|lectures?|films?|episodes?|movies?|courses?|recordings?)\b[^.;!?]{0,60}?\bdownload\w*\b[^.;!?]{0,50}?\boffline\b"
                    r"|\bdownload\w*\b[^.;!?]{0,50}?\b(?:video|videos|lessons?|lectures?|films?|episodes?|movies?)\b[^.;!?]{0,50}?\boffline\b")
WAN_DOWN_RX = (r"\b(?:keep|continue|carry on|still|stay)\w*\s+(?:\w+\s+){0,4}?(?:if|when|while)\s+(?:\w+\s+){0,4}?(?:wan|uplink|internet|head[- ]office|leased)\b(?:\W+\w+){0,4}?\W+(?:link|connection|connectivity|line)?\W*(?:is|goes|gets|are|drops?|fails?)\W+(?:down|offline|lost|unavailable|cut)\b"
               r"|\b(?:wan|uplink|internet|head[- ]office|leased)\b(?:\W+\w+){0,4}?\W+(?:link|connection|connectivity|line)?\W*(?:is|goes|gets|are|drops?|fails?)\W+(?:down|offline|lost|unavailable|cut)\b"
               r"|\b(?:wan|uplink|internet) (?:link |connection )?(?:outages?|failures?|drops?)\b"
               r"|\b(?:keep|continue|carry on|still)\s+work\w*\s+(?:\w+\s+){0,3}(?:if|when|while|without)\s+(?:the |a |our )?(?:\w+\s+){0,3}?(?:wan|uplink|internet|head[- ]office)\b")
ONSITE_NAMES_MAX = 8  # planning heuristic: components named in the WAN-outage assumption
# q4: capabilities a description names that no hard flag or layer carries. Each becomes a quoted note with a plan (no product is selected or
# priced, so the layer choices never move); an external channel on a self-hosted or air-gapped stack is a warning or a critical.
# only messages the APPLICATION sends: "a WhatsApp link" or "orders come by WhatsApp" is a person using the WhatsApp app, not the Business Platform
WHATSAPP_RX = (r"\bwhats ?app (?:reminders?|alerts?|notifications?|messages?|updates?|confirmations?|receipts?|otps?|codes?|bots?|chatbots?|business|api)\b"
               # q10: one or two words between the channel and what is sent ("WhatsApp appointment reminders"); never across a link, group or number
               r"|\bwhats ?app (?:(?!(?:links?|buttons?|groups?|numbers?|and|or|with|but|then|today|is|are|was|to|in|on)\b)[a-z-]+ ){1,2}"
               r"(?:reminders?|alerts?|notifications?|confirmations?|otps?)\b"
               r"|\b(?:send|sends|sent|sending|notif\w+|remind\w*|alert\w*|messag\w+|confirm\w*|deliver\w*|push\w*)\b(?!\s+us\b)[^.;!?]{0,50}?"
               r"\b(?:via|by|on|over|through|to|in)\s+(?:their |a |the |our )?whats ?app\b(?! (?:link|button|group|number))")
CRASH_RX = (r"\bcrash(?:es)?[- ](?:reports?|reporting|dumps?|logs?|analytics|telemetry)\b|\berror[- ](?:tracking|reporting|monitoring)\b|\bexception[- ](?:tracking|monitoring)\b"
            r"|\b(?:collect|gather|upload|send|receiv)\w*\b(?:\W+\w+){0,3}?\W+crash(?:es)?\b")
DRM_RX = (r"\bdrm\b|\bwidevine\b|\bfairplay\b|\bplayready\b|\banti[- ]piracy\b|\b(?:against|prevent\w*|stop\w*|deter\w*) (?:\w+ )?piracy\b"
          r"|\badaptive[- ]bitrate\b|\bhls\b|\bmpeg[- ]dash\b")
OTA_RX = (r"\bota (?:updates?|upgrades?|firmware|rollouts?|releases?)\b|\b(?:firmware|software|device) ota\b|\bover[- ]the[- ]air\b|\bfirmware (?:updates?|upgrades?|rollouts?|releases?|images?)\b|\b(?:updat|upgrad|flash|push)\w* (?:the |new |device )?firmware\b")
INBOUND_MAIL_RX = (r"\b(?:read|reads|reading|ingest\w*|pars\w+|process\w*|import\w*|poll\w*|monitor\w*|triag\w+)\W+"
                   r"(?:(?:the|our|their|incoming|inbound|support|customer[- ]support|customer|shared)\W+)*(?:e-?mails?|mailbox(?:es)?|inbox(?:es)?)\b"
                   r"(?!\W+(?:deliverability|receipts?|confirmations?|campaigns?|newsletters?|templates?|bounces?|open rates?|addresses))"
                   r"|\b(?:incoming|inbound) (?:\w+ )?e-?mails?\b|\bshared (?:mailbox|inbox)\b")


def _short(choice):
    n = choice.split(": ", 1)[-1]
    for cut in (" (", " —", " via ", " + ", ",", ";"):
        n = n.split(cut)[0]
    return " ".join(n.split()[:5])


def component_notes(ctx, supporting, core):
    """([(code, severity, message, fields)], [assumption text]) for deliverables the description names and the layers do not carry."""
    req = ctx["req"]
    desc = req["project.description"] or ""
    notes, assumptions = [], []
    if not desc:
        return notes, assumptions
    existing = " ".join(str(e) for e in (req["infrastructure.existing_systems"] or [])).lower()
    low = desc.lower()  # cheap substring pre-checks before the regexes: they are slow on a long description
    hit = first_live(CMS_RX, desc) if ("cms" in low or "content management" in low or "editor" in low or "journalist" in low or "writer" in low
                                       or "author" in low or "reporter" in low or "content team" in low) else None
    if hit and not re.search(EXISTING_CMS_RX, existing):
        notes.append(("DESC_CMS_NOT_SELECTED", "info",
                      f"project.description says content is published through a CMS ('{hit[1]}'). No CMS product is selected by the engine (none is in the knowledge base). "
                      "Plan one of two shapes: a headless CMS (editors work in its admin interface and the site reads the content from its API, so public pages can still be "
                      "cached at the edge and rebuilt or purged on publish), or an editor admin section inside the backend. Either way give editors roles, a draft and publish "
                      "step and image upload, and keep them out of the public request path.", ["project.description"]))
    hit = first_live(IMAGE_HEAVY_RX, desc) if ("photo" in low or "image" in low or "picture" in low or "galler" in low) else None
    if hit and ctx["web"] and not ctx["local_first"] and ctx["type"] != "internal_tool":  # a public-facing site, not an internal tool
        notes.append(("DESC_IMAGE_OPTIMISATION", "info",
                      f"project.description describes image-heavy pages ('{hit[1]}'). Serving each original photo is the main bandwidth cost and slows pages: keep originals in object "
                      "storage, generate resized and compressed copies (WebP or AVIF at several widths, chosen with srcset), lazy-load images below the fold, and serve them "
                      "through a CDN or an image-resizing service with long cache lifetimes (planning heuristic).", ["project.description"]))
    hit = first_live(OFFLINE_VIDEO_RX, desc) if "download" in low and "offline" in low else None  # cheap pre-check: the spans below are slow on long text
    if hit and (ctx["web"] or ctx["mobile"] or ctx["desktop"]) and not ctx["local_first"]:
        gb = req["scale.data_volume_gb_12_months"]
        notes.append(("DESC_OFFLINE_DOWNLOADS", "info",
                      f"project.description has users download media for offline use ('{hit[1]}')"
                      + (f" and ~{cx.num(gb)} GB of files are expected in 12 months" if gb else "")
                      + ". Keep the files in object storage and put a CDN in front of the download path: egress per downloaded copy, not storage, becomes the bill, and "
                      "a CDN cuts it and the latency. The client needs a download manager (resumable, chunked downloads in the background, for example WorkManager on Android), "
                      "an integrity check, a storage-space check and a way to delete or expire downloaded packs; paid content should be encrypted on the device or served by "
                      "short-lived signed URLs (planning heuristic; no CDN product is priced into the band unless a CDN layer is listed).", ["project.description"]))
    hit = first_live(WHATSAPP_RX, desc) if "whats" in low else None
    if hit and not ctx["local_first"]:
        base = (f"project.description sends or receives WhatsApp messages ('{hit[1]}'). No WhatsApp provider is selected or priced by the engine (none is in the "
                "knowledge base). WhatsApp business messaging runs through Meta's WhatsApp Business Platform, an external service reached over the internet, directly "
                "or through a messaging provider: plan a registered business number, message templates approved in advance for reminders and alerts, a stored opt-in "
                "per recipient, a delivery-status webhook, and per-message or per-conversation fees (check the current price list).")
        if ctx["no_internet"]:
            notes.append(("WHATSAPP_NEEDS_NETWORK", "critical", base + " deployment_model air_gapped has no route to the internet, so this channel cannot work from "
                          "inside the air gap: use a channel that stays on site (on-screen notices, printed slips, an internal mail server, or an on-site SMS modem if "
                          "one is allowed), or run the messaging from a separate system outside the gap.", ["project.description", "infrastructure.deployment_model"]))
        elif ctx["self_host_only"]:
            notes.append(("WHATSAPP_EXTERNAL_SERVICE", "warning", base + " deployment_model on_premise keeps every component on your own servers; this channel is the "
                          "exception: it needs an outbound-only HTTPS path from the application server to the provider, and message content (names, appointment times) "
                          "leaves the site. If that is not permitted, send reminders by SMS through an on-site gateway or by e-mail through the internal mail server.",
                          ["project.description", "infrastructure.deployment_model"]))
        else:
            notes.append(("DESC_WHATSAPP_CHANNEL", "info", base, ["project.description"]))
    hit = first_live(CRASH_RX, desc) if ("crash" in low or "error" in low or "exception" in low) else None
    if hit and not re.search(r"sentry|glitchtip|crashlytics|bugsnag|rollbar", " ".join(s["choice"].lower() for s in supporting)):
        notes.append(("DESC_CRASH_REPORTING", "info",
                      f"project.description collects crash or error reports ('{hit[1]}'). No error-tracking product is selected or priced by the engine (none is in the "
                      "knowledge base). Plan a crash and error collector that receives stack traces or crash dumps from the client and the server, groups duplicates, "
                      "keeps the release version with each report and alerts on new ones; upload debug symbols or source maps at build time and strip personal data "
                      "before sending. " + ("With this deployment model pick one you can host yourself (open-source collectors exist)."
                                             if ctx["self_host_only"] else "Hosted services and self-hostable open-source collectors both exist."), ["project.description"]))
    hit = first_live(DRM_RX, desc) if ("drm" in low or "piracy" in low or "bitrate" in low or "hls" in low or "dash" in low or "widevine" in low
                                       or "fairplay" in low or "playready" in low) else None
    if hit:
        notes.append(("DESC_STREAMING_PROTECTION", "warning",
                      f"project.description asks for adaptive-bitrate or protected video playback ('{hit[1]}'). No packaging or DRM licence service is selected or priced by "
                      "the engine (none is in the knowledge base), so this part is NOT covered by the stack above. Plan: transcode each title into a ladder of bitrates, "
                      "package it as HLS and DASH with encrypted segments, issue playback licences from a multi-DRM licence service (Widevine for Android and Chrome, "
                      "FairPlay for Apple devices, PlayReady for Windows), use a player that supports them on each platform, and expire downloaded licences for offline "
                      "viewing. Video delivery (egress) and the licence service will be the largest lines of the real bill.", ["project.description"]))
    hit = first_live(OTA_RX, desc) if ("ota" in low or "over-the-air" in low or "over the air" in low or "firmware" in low) else None
    if hit:
        notes.append(("DESC_FIRMWARE_UPDATES", "info",
                      f"project.description updates device firmware remotely ('{hit[1]}'). No firmware-update service is selected or priced by the engine (none is in the "
                      "knowledge base). Plan: signed firmware images in object storage, a manifest of the target version per device group, a staged rollout (a few devices, "
                      "then the fleet) announced over the device channel, a device that verifies the signature and can roll back (two firmware slots), and a status report "
                      "from each device so a failed rollout is stopped (planning heuristic).", ["project.description"]))
    hit = first_live(INBOUND_MAIL_RX, desc) if ("mail" in low or "inbox" in low) else None
    if hit and ctx["needs_backend"]:
        notes.append(("DESC_INBOUND_EMAIL", "info",
                      f"project.description reads incoming e-mail ('{hit[1]}'). The stack's e-mail service, where one is listed, only sends; nothing above receives mail. "
                      "Plan an ingestion step: poll the mailbox over IMAP (or the mail provider's API) or take the provider's inbound webhook, put each message on the "
                      "job queue, de-duplicate on the Message-ID header, keep the original message and its attachments in object storage, and scan attachments before "
                      "anyone opens them (planning heuristic).", ["project.description"]))
    hit = first_live(WAN_DOWN_RX, desc) if ctx["self_host_only"] and ("wan" in low or "uplink" in low or "internet" in low or "head office" in low
                                                                        or "head-office" in low or "leased" in low) else None
    if hit:
        names = []
        for n in [_short(c["choice"]) for c in core if c.get("choice")] + [_short(s["choice"]) for s in supporting if s["deployment"] == "self_hosted" and s["data_bearing"]]:
            if n and n not in names:
                names.append(n)
        assumptions.append(
            f"Local-first operation: project.description says the site must keep working when the WAN link is down ('{hit[1]}'). The application, its database and the services that hold its data run on the "
            f"site's own servers ({', '.join(names[:ONSITE_NAMES_MAX])}), so a WAN outage does not stop it. Data is buffered locally and sent to the remote side "
            "(head office or cloud) when the link returns (store-and-forward with idempotent, retried transfers); anything hosted outside the site would stop working during an outage "
            "(planning heuristic).")
    return notes, assumptions
