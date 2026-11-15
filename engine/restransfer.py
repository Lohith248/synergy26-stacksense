"""q3 item 1: a stated transfer of regulated data out of the residency area is a hard-constraint break.

When a residency area is in force (infrastructure.data_residency, an 'other' country, or rbi_localisation -> India), the input can
still plan to move the data elsewhere: a description sentence that sends / streams / exports / replicates / syncs / mirrors / backs
up data to a named place outside the area, or an existing system the stack integrates with that is stated to live outside it.
Either one is a critical warning, and the matching integration component says what is allowed instead (raw records stay in the
area; only aggregated or anonymised data leaves, or an in-region instance of that system is used).

A place counts only when it is named (provider region codes, countries, cities, regions); a place inside the area, a sentence with
no transfer verb ("customers in the US"), and a negated sentence ("never leaves India", "nothing is exported") never fire.
Only place names and verbs are listed here; no scenario, project or vendor behaviour appears.
"""
import re

from . import context as cx
from . import integrations as ig

# provider region codes and place words the context table does not hold (place -> area id, as context.COUNTRIES / RES_ENUM)
EXTRA_PLACES = [
    (r"ap-southeast-1|asia-southeast1|south ?east ?asia|singapore", "singapore"),
    (r"ap-southeast-[234]|australia-southeast[12]|australia ?(?:east|southeast|central)", "australia"),
    (r"ap-northeast-[13]|asia-northeast[12]|japan ?(?:east|west)", "japan"),
    (r"ap-northeast-2|asia-northeast3|korea ?(?:central|south)", "south_korea"),
    (r"me-central-1|uae ?(?:north|central)|me-central1", "uae"),
    (r"sa-east-1|southamerica-east1|brazil ?south", "brazil"),
    (r"ca-central-1|northamerica-northeast[12]|canada ?(?:central|east)", "canada"),
]
UPPER_US = r"(?<![A-Za-z])US(?![A-Za-z])"
# a place word directly followed by one of these names people, not a system's location ("the US investors' team", "EU customers")
AUDIENCE_AFTER = (r"\s*(?:'s\s+|-based\s+)?(?:customers?|users?|clients?|investors?|teams?|players?|patients?|students?|people|visitors?|"
                  r"buyers?|sellers?|merchants?|partners?|subscribers?|market|audiences?|staff|employees?|offices?)\b")
TRANSFER_RX = (r"\b(?:send|sends|sent|sending|stream(?:s|ed|ing)?|export(?:s|ed|ing)?|replicat\w+|sync(?:s|ed|ing|hroni[sz]\w+)?|"
               r"mirror(?:s|ed|ing)?|back(?:s|ed|ing)? up|backed-up|backups?\s+(?:to|in)|cop(?:y|ies|ied|ying)\s+(?:\w+\s+){0,4}?(?:to|into)|"
               r"push(?:es|ed|ing)?\s+(?:\w+\s+){0,4}?(?:to|into)|forward(?:s|ed|ing)?|upload(?:s|ed|ing)?\s+(?:\w+\s+){0,4}?(?:to|into)|"
               r"ship(?:s|ped|ping)?\s+(?:\w+\s+){0,4}?(?:to|into)|transferr?(?:s|ed|ing)?|load(?:s|ed|ing)?\s+(?:\w+\s+){0,4}?into|"
               r"feed(?:s|ing)?\s+(?:\w+\s+){0,4}?into|pip(?:e|es|ed|ing)\s+(?:\w+\s+){0,4}?(?:to|into))")
NEGATION_RX = r"\b(?:not|never|no|nothing|none|without|instead of|rather than)\b|n't\b"
DATA_RX = (r"\b(?:data|records?|logs?|transactions?|events?|payments?|backups?|snapshots?|cop(?:y|ies)|tables?|rows?|readings?|"
           r"telemetry|files?|documents?|messages?|orders?|profiles?|details|information|pii|phi|datasets?|everything|all of it)\b")


def area_label(area):
    """Display name of an area id."""
    return {"india": "India", "eu": "the EU", "us": "the United States"}.get(area) or (cx.COUNTRIES[area][0] if area in cx.COUNTRIES else area.upper())


def _place_patterns():
    pats = [(rx, loc) for rx, loc in EXTRA_PLACES] + list(cx.EXISTING_LOCATIONS)
    pats += [(rx, cid) for cid, (_, rx) in cx.COUNTRIES.items() if cid != "singapore"]
    return [(re.compile(r"(?<![a-z0-9])(?:" + rx + r")(?![a-z0-9])", re.I), loc) for rx, loc in pats]


PLACES = _place_patterns()


def places(text):
    """[(start, matched text, area id)] for every named place in text; a longer match at the same start wins, earlier tables first."""
    found = {}
    for rx, loc in PLACES:
        for m in rx.finditer(text):
            if re.match(AUDIENCE_AFTER, text[m.end():], re.I):
                continue
            if m.start() not in found or len(m.group(0)) > len(found[m.start()][0]):
                found[m.start()] = (m.group(0), loc)
    for m in re.finditer(UPPER_US, text):
        if not re.match(AUDIENCE_AFTER, text[m.end():], re.I) and m.start() not in found:
            found[m.start()] = (m.group(0), "us")
    # a match inside a longer one at an earlier start ("Europe" inside "west europe") is dropped
    out, end = [], -1
    for s in sorted(found):
        txt, loc = found[s]
        if s >= end:
            out.append((s, txt, loc))
            end = s + len(txt)
    return out


def _outside(area, loc):
    return loc != area


def quote(text, n=160):
    """A description fragment cut at a word boundary, with an ellipsis when shortened."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;:-–—")
    return cut + "..."


def _sentences(desc):
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n", desc or "") if s.strip()]


def transfer_in_sentence(sent, area):
    """(verb, place text, place area) for the first named place outside the area that follows an un-negated transfer verb, else None."""
    if not re.search(DATA_RX, sent, re.I):
        return None
    for v in re.finditer(TRANSFER_RX, sent, re.I):
        if re.search(NEGATION_RX, sent[:v.start()], re.I):
            continue
        for s, txt, loc in places(sent):
            if s > v.start() and _outside(area, loc):
                return v.group(0), txt, loc
    return None


def _constraint(ctx):
    rbi = "rbi_localisation" in ctx["compliance"]
    parts = []
    if rbi:
        parts.append("RBI payment-data localisation")
    if not ctx["residency_from_rbi"]:
        parts.append(f"data residency in {area_label(ctx['res_key'])}")
    if "gdpr" in ctx["compliance"] and ctx["res_key"] == "eu":
        parts.append("GDPR rules on transfers out of the EU")
    return " and ".join(parts)


def findings(ctx):
    """[(source, quoted evidence, place text, place area, entry or None)] for each stated transfer out of the residency area."""
    area = ctx.get("res_key")
    if not area or not (ctx.get("res_named") or ctx.get("residency_from_rbi")) or ctx.get("local_first"):
        return []
    out = []
    for sent in _sentences(ctx["req"]["project.description"]):
        hit = transfer_in_sentence(sent, area)
        if hit:
            words = set(re.findall(r"[a-z0-9]+", sent.lower()))
            entry = next((e for e in ctx["existing"] if ig._tokens(e["raw"]) & words), None)
            out.append(("description", sent, hit[1], hit[2], entry))
    named = {id(f[4]) for f in out if f[4] is not None}
    for e in ctx["existing"]:
        if id(e) in named or e is ctx.get("kept_db") or e.get("retire") or (e.get("adapter") or {}).get("kind") == "retire":
            continue
        if not (e.get("pattern") or e.get("adapter")) or ig._retiring(e["raw"].lower()):
            continue  # nothing is integrated with an entry the stack does not use
        ps = [(t, loc) for _, t, loc in places(e["raw"]) if _outside(area, loc)]
        inside = [loc for _, _, loc in places(e["raw"]) if loc == area]
        if ps and not inside:
            out.append(("entry", e["raw"], ps[0][0], ps[0][1], e))
    return out


def apply(ctx, supporting):
    """Warnings (code, severity, message, fields) for each stated transfer; the matching integration components are rewritten to agree."""
    warns = []
    for src, evidence, place, loc, entry in findings(ctx):
        res = area_label(ctx["res_key"])
        label = area_label(loc)
        where = place if label.lower().replace("the ", "") in place.lower() else f"{place} ({label})"
        if src == "description":
            what = f"project.description sends data out of {res}: '{quote(evidence)}' names {where}"
        else:
            what = f"infrastructure.existing_systems lists '{entry['raw']}', which the stack integrates with and which is stated to run in {where}"
        payment = "rbi_localisation" in ctx["compliance"]
        msg = (f"{what}, outside {res}. That breaks {_constraint(ctx)}"
               + (": payment data must be stored only in India, and data processed abroad must be deleted there and brought back within one business day or 24 hours, whichever is earlier" if payment else "")
               + f". Allowed instead: keep the raw records in {res} and send only aggregated or anonymised data to that system, "
               f"or use an instance of it that runs in {res}. Confirm the data flow with whoever owns the compliance sign-off before building it.")
        fields = list(ctx["res_paths"]) + (["compliance"] if payment and "compliance" not in ctx["res_paths"] else [])
        fields += ["project.description"] if src == "description" else []
        fields += ["infrastructure.existing_systems"] if entry is not None else []
        warns.append(("RESIDENCY_TRANSFER_OUT", "critical", msg, list(dict.fromkeys(fields))))
        if entry is not None:
            name = re.sub(r"(?i)^(?:the |our )?existing ", "", re.sub(r"\s+", " ", entry["raw"]).strip())[:40].lower()
            note = (f"Residency limits this integration: raw records stay in {res} ({_constraint(ctx)}). Only aggregated or anonymised "
                    f"data may be sent to the system in {place}, or an instance of it that runs in {res} replaces it; a full export of the records is not part of this plan. ")
            for s in supporting:
                if s["layer"] == "other" and name and name in s["choice"].lower() and not s["justification"].startswith("Residency limits"):
                    s["justification"] = note + s["justification"]
                    if "infrastructure.data_residency" not in s["driven_by"] and ctx["res_paths"]:
                        s["driven_by"] = s["driven_by"] + [p for p in ctx["res_paths"] if p not in s["driven_by"]]
    return warns
