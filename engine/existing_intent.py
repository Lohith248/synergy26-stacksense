"""q7: what the input means to do with an existing system, beyond the keep / retire words engine/context.py reads.

rebuilt: the new application is that system's rebuild. The description lists what the system does as one of the new application's
         own functions ('admissions, fees, attendance ...') and, in another sentence, says that function currently runs on it. The
         entry is then marked retire (one-time data migration, read-only during the transition, cut-over with rollback), never
         integrated for good. Only custom applications and APIs: a vendor product (ERP, CRM) is integrated unless the text replaces it.
no_touch: the description forbids changes to what exists ('without touching the core', 'must not be modified', 'read-only replica'):
         every existing database / record system / legacy application it covers is read only (replica, CDC or read API).
Planning heuristics; deterministic regexes over the input text only."""
import re

from . import context as cx

APP_NOUN = (r"(?:web ?sites?|sites?|portals?|apps?|applications?|systems?|software|tools?|storefronts?|stores?|apis?|backends?"
            r"|front-?ends?|platforms?|modules?|services?|programs?|suite)")
# entry words that never name a business function
_STOP = set("custom code legacy old older existing current in-house inhouse house built written based version the our and with for from using "
            "running server database written by freelancer agency vendor team internal external monolith classic new".split())
_NOW_RX = (r"\bcurrently\b|\btoday\b|\bat (?:the )?present\b|\bpresently\b|\bright now\b|\bfor now\b|\bstill (?:runs?|running|lives?|sits?)\b"
           r"|\b(?:the|our) current\b")
# the text integrates with it instead of taking over its job
_INTEG_RX = (r"\bintegrat\w*|\bsync\w*|\bconnect\w* (?:to|with)\b|\btalks? to\b|\b(?:reads?|pulls?|fetch(?:es)?|imports?|gets?) (?:[\w-]+ ){0,4}?from\b"
             r"|\b(?:push(?:es)?|posts?|sends?|writes?|exports?) (?:[\w-]+ ){0,4}?(?:to|into)\b|\bcalls?\b|\bbeside\b|\balongside\b")
_STAYS_RX = (r"\bstays?\b|\bremains?\b|\bwill (?:still )?(?:run|keep running)\b|\bkeep(?:s|ing)? (?:it|them|using|running)\b|\bas[- ]is\b"
             r"|" + cx.STRONG_KEEP_RX)
_REBUILD_KINDS =("legacy_app", "api")

NO_TOUCH_RX = (cx.NO_TOUCH_RX
               + r"|\b(?:must|may|can|should|will|is to|are to)(?: not|n't| never) be (?:touched|modified|changed|altered|written to|written)\b"
               + r"|\bread[- ]only\b|\bno writes?\b|\b(?:stays?|remains?|left|leave)\s+(?:[\w-]+\s+){0,3}?untouched\b")


def _sentences(desc):
    return [s for s in re.split(r"(?<=[.!?;])\s+|\n", (desc or "").lower().replace("’", "'")) if s.strip()]


def _name_rx(e):
    pat, life = e["pattern"], e["life"]
    parts = []
    if pat and not pat.get("synthetic") and pat.get("match"):
        parts.append(cx.name_rx_plain(pat))
    if life:
        parts.append(cx.life_rx(life))
    return "|".join(parts) or None


def _stem(w):
    return w[:-1] if len(w) > 4 and w.endswith("s") else w


def _functions(e):
    """Business-function words of the entry ('PHP 5.6 admissions website (custom code)' -> ['admission'])."""
    low = e["raw"].lower()
    named = " ".join(filter(None, [(e["life"] or {}).get("name", ""), (e["pattern"] or {}).get("product", "")])).lower()
    out = []
    for w in re.findall(r"[a-z][a-z-]{3,}", low):
        if w in _STOP or re.fullmatch(APP_NOUN, w) or w in named or re.search(_name_rx(e) or r"(?!x)x", w):
            continue
        out.append(w)
    return out


def rebuilt_function(e, desc):
    """The function word through which the description makes the new application this system's rebuild, else None."""
    pat = e["pattern"]
    if e["keep"] or e["retire"] or not re.search(r"\b" + APP_NOUN + r"\b", e["raw"].lower()):
        return None
    if not ((pat and pat["kind"] in _REBUILD_KINDS) or (not pat and e["life"])):
        return None
    name, sents = _name_rx(e), _sentences(desc)
    for fw in _functions(e):
        frx = r"\b" + re.escape(_stem(fw)) + r"s?\b"
        # the sentences about it, each with the one after it ('... runs on the X site, which stays; the portal syncs with it')
        about = [s + " " + (sents[i + 1] if i + 1 < len(sents) else "") for i, s in enumerate(sents)
                 if re.search(frx, s) or (name and re.search(name, s))]
        if any(re.search(_INTEG_RX, s) or re.search(_STAYS_RX, s) for s in about):
            return None
        scope = any(re.search(frx, s) and not (name and re.search(name, s)) and not re.search(_NOW_RX, s) for s in sents)
        now = any(re.search(frx, s) and re.search(_NOW_RX, s) for s in sents)
        if scope and now:
            return fw
    return None


# a no-touch clause must be about the existing estate: it names an existing system or one of these nouns ('without changing the
# menu', 'a read-only dashboard for managers' are not about it)
ESTATE_RX = (r"\b(?:core|core banking|systems?|existing|legacy|databases?|db|mainframe|servers?|erp|crm|ledger|records?|source data"
             r"|replicas?|tables?|schemas?)\b")


def no_touch(desc, name_rxs):
    """(quoted sentence, [lower-case clauses]) for the description clauses that forbid changes to the existing estate."""
    quote, clauses = None, []
    prev = ""
    for s in re.split(r"(?<=[.!?;])\s+|\n", (desc or "").replace("’", "'")):
        for cl in re.split(r"[,;:]\s*|\s+(?:but|while|whereas)\s+", s.lower()):
            said = s
            if re.search(NO_TOUCH_RX, cl) and re.match(r"\s*(?:it|they|this|that|which)\b", cl):
                # 'keep the Oracle database; it must not be modified': the clause before the pronoun says what it is
                said = (prev + " " + s).strip()
                cl = said.lower()
            if re.search(NO_TOUCH_RX, cl) and (re.search(ESTATE_RX, cl) or any(rx and re.search(rx, cl) for rx in name_rxs)):
                clauses.append(cl)
                if quote is None:
                    q = said.strip().rstrip(".")
                    quote = q if len(q) <= 160 else q[:157].rsplit(" ", 1)[0] + " ..."
        prev = s
    return quote, clauses


def mark(ctx, req):
    """Adds e['rebuilt'] (function word or None) and e['read_only'] (quoted description words or None) to each existing system;
    a rebuilt system is also marked retire."""
    desc = req["project.description"] or ""
    names = {id(e): _name_rx(e) for e in ctx["existing"]}
    sents = _sentences(desc)
    quote, hits = no_touch(desc, list(names.values()))
    # a no-touch clause that names some existing systems covers only those; one that names none covers all of them
    named = {i for i, rx in names.items() if rx and any(re.search(rx, s) for s in hits)}
    for e in ctx["existing"]:
        fw = rebuilt_function(e, desc)
        e["rebuilt"] = fw
        if fw:
            e["retire"] = True
        kind = (e["pattern"] or {}).get("kind")
        covered = (id(e) in named) if named else True
        rx = names[id(e)]
        writes = bool(rx and any(cx.write_in_text(rx, s) for s in sents)) or e.get("keep_write")
        e["read_only"] = (quote if quote and covered and not e["retire"] and not writes
                          and kind in ("database", "record", "legacy_app", "erp", "crm") else None)
