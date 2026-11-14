"""H2: the description says a behaviour the boolean flags deny (live updates, search, an assistant, patchy connectivity, reminders
with no sender), and an existing identity provider that the description says staff sign in through.

The flags are hard inputs, so a mismatch never overrides them (uploads are the one old exception): it is a warning that quotes the
description phrase and names the flag. Every phrase goes through the shared negation guard (context.live_hit logic), so
"We do NOT need live updates" or "no search" never fires. Wording lists are planning heuristics: a test of each kind below shows what
fires and what must not."""
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
    """(phrase, clause) of the longest match of rx in desc that no negation reaches (the first on a tie), or None. The clause is quoted in warnings."""
    low = desc.lower().replace("’", "'")
    breaks = cx.clause_breaks(low)
    same = len(low) == len(desc)
    best = None
    for m in re.finditer(rx, low):
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
        hit = first_live(rx, desc, local_neg=True)
        if hit:
            code, text = _TEXT[key]
            out.append((code, sev, "project.description " + text.format(q=hit[1]), [path, "project.description"]))
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


def staff_sso_applies(ctx):
    """An existing IdP the description says staff sign in through, while the customer-facing auth does not already use it."""
    idp, auth = ctx.get("existing_idp"), ctx["req"]["requirements.auth"]
    if not idp or auth in ("enterprise_sso", "none"):
        return None
    if idp["pattern"].get("reuse") and ctx["idp_customer_login"] and auth in ("email_password", "social"):
        return None  # the provider is already the sign-in for everyone
    hit = staff_signin(ctx)
    if not hit:
        return None
    if ctx["no_internet"] and idp["pattern"].get("deployment") == "saas":
        return None  # an air gap cannot reach a SaaS identity provider
    return hit
