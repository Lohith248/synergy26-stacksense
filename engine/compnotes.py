"""H2 (blind9 A4): compliance notes that follow the input instead of one sentence per regime.

All text is cautious: it names what a rule requires in outline, never claims a certification, and says to confirm with counsel or the
assessor. Wording lists are planning heuristics."""
import re
from . import descflags as dfl

# minors: wording that says the users are children ("under 18", "students 12 to 18", "classes 6 to 10", "children", "K-12")
MINORS_RX = (r"\bunder[- ]?(?:18|17|16|15|14|13|eighteen|sixteen|thirteen)\b|\bminors?\b|\bchildren\b|\bkids?\b|\bk-?12\b|\bteen(?:ager)?s?\b"
             r"|\b(?:students?|learners?|pupils?|users?|players?|members?)\b(?:\W+\w+){0,4}?\W+(?:aged?|ages)\s*\d{1,2}\b"
             r"|\b(?:students?|learners?|pupils?)\b(?:\W+\w+){0,3}?\W+(?:are |is )?(?:1[0-7]|[5-9])\s*(?:to|-|and)\s*(?:1[0-8]|[6-9])\b(?:\s*years?)?"
             r"|\b(?:players?|users?|members?|customers?|audience)\b(?:\W+\w+){0,3}?\W+(?:are |is |between )?(?:1[0-7]|[5-9])\s*(?:to|-|and)\s*(?:1[0-8]|[6-9])\s*(?:years?|yrs?)\b"
             r"|\bclass(?:es)? \d{1,2}\s*(?:to|-)\s*\d{1,2}\b|\bgrades? \d{1,2}\s*(?:to|-)\s*\d{1,2}\b")
# weaker evidence: a school level that is usually minors, with no age stated
MINORS_WEAK_RX = r"\bpupils?\b|\bprimary schools?\b|\bsecondary schools?\b"
# a payment service provider shape: the project itself routes, authorises or vaults card payments for merchants
PSP_RX = (r"\bpayment orchestrat\w*|\broutes? to acquirers?\b|\b(?:we are|we.re|become|becoming|building) an? (?:\w+ )?(?:payment service provider|psp|acquirer)\b|\bvault(?:s|ing)? cards?\b|\bpayment facilitators?\b|\bpayment aggregators?\b"
          r"|\bcard (?:vault|tokeni[sz]ation)\b|\bcardholder data (?:environment|vault)\b|\bmerchant acquiring\b"
          r"|\b(?:accepts?|processes?|routes?|authori[sz]es?|settles?)\b(?:\W+\w+){0,3}?\W+card (?:payments?|transactions?)\b(?:\W+\w+){0,4}?\W+(?:for|on behalf of) (?:\w+ )?merchants?\b"
          r"|\bfor merchants\b(?:\W+\w+){0,6}?\W+(?:accepts?|processes?|routes?|authori[sz]es?)\b(?:\W+\w+){0,3}?\W+card"
          # p5: the product itself is the gateway, processor or switch (named first, or connecting to the card schemes / NPCI), not a shop that uses one
          r"|^\W*(?:an? |the |our )?(?:\w+[- ]){0,3}?(?:payment gateway|card processor|payment processor|payments? switch|card switch)\b(?! (?:integration|checkout|plugin))"
          r"|\b(?:upi|imps|neft|rtgs|atm|card|interbank) switch(?:es|ing)?\b"
          r"|\bconnects?\b(?:\W+\w+){0,5}?\W+(?:to|with) (?:the )?(?:npci|card networks?|card schemes?|visa|mastercard|rupay)\b"
          r"|\b(?:stores?|storing|process(?:es)?|processing) (?:and (?:process(?:es)?|stores?) )?(?:raw )?card(?:holder)? data\b"
          r"|\broutes?\b(?:\W+\w+){0,3}?\W+(?:payments?|transactions?) to (?:\w+ ){0,2}(?:acquir\w*|card networks?|card schemes?|npci)\b")
# p5: mobile-money wallets (paid from a phone wallet, not a card): need a mobile-money provider API or aggregator, not a card gateway
MOBILE_MONEY_RX = r"\bmobile[- ]money\b|\bm-?pesa\b|\bmtn (?:mobile money|momo)\b|\bmomo\b|\bairtel money\b|\borange money\b|\btigo pesa\b|\bwave (?:mobile )?money\b"
# p5: an existing system that is the scheme / network link a payment provider operates itself
SCHEME_RX = r"\bnpci\b|\bvisa\b|\bmastercard\b|\brupay\b|\bcard (?:network|scheme)s?\b|\bacquir\w+|\bupi\b|\bimps\b|\bswitch\b"
# services whose end-user personal data passes through the vendor although the vendor holds no database for the project
DATA_PATH_LAYERS = ("auth", "realtime", "email")
# planning heuristic: a provider the engine picks because it is the in-region route for the stated residency (an Indian SMS route under India residency) is not flagged
IN_REGION_PROVIDERS = ("msg91",)


def minors(ctx):
    """(phrase, sentence, stated): stated is False when only a school level (no age) suggests minors."""
    desc = ctx["req"]["project.description"] or ""
    hit = dfl.first_live(MINORS_RX, desc)
    if hit:
        return hit + (True,)
    hit = dfl.first_live(MINORS_WEAK_RX, desc)
    return hit + (False,) if hit else None


def psp(ctx):
    return dfl.first_live(PSP_RX, ctx["req"]["project.description"] or "")


def refine(ctx, notes, managed_cloud_hipaa):
    """Extend the static notes dict {regime: (code, severity, message, fields)} in place for this input."""
    m = minors(ctx)
    if m and "gdpr" in notes:
        code, sev, msg, fields = notes["gdpr"]
        notes["gdpr"] = (code, sev, msg + f" Children: project.description {'says' if m[2] else 'suggests'} the users include minors ('{m[1]}'). Recital 38 says children merit specific protection; "
                         "under Art. 8, where you rely on consent as the lawful basis, consent for an online service offered directly to a child is valid only from age 16 (a Member State may lower it, to no less than 13); "
                         "below that age the holder of parental responsibility must give or authorise it, and you must make reasonable efforts to verify this. "
                         "Write notices in plain language, switch off profiling and marketing aimed at children, and confirm the age threshold for each country with counsel (this is not legal advice).",
                         fields + ["project.description"])
    if m and "dpdp" in notes:
        code, sev, msg, fields = notes["dpdp"]
        notes["dpdp"] = (code, sev, msg + f" Children: project.description {'says' if m[2] else 'suggests'} the users include minors ('{m[1]}'). Section 9 of the Act requires verifiable consent of a parent or lawful guardian "
                         "before a child's (under 18) personal data is processed, and bars processing that is likely to harm a child's well-being, tracking or behavioural monitoring "
                         "of children, and targeted advertising directed at them (exemptions can be notified, and the DPDP Rules set how age and parent are verified: confirm what applies on your launch date; "
                         "this is not legal advice).", fields + ["project.description"])
    if managed_cloud_hipaa and "hipaa" in notes:
        code, sev, msg, fields = notes["hipaa"]
        notes["hipaa"] = (code, sev, msg + " A BAA does not configure the safeguards for you: on the managed services encrypt PHI in transit and at rest (an 'addressable' Security Rule "
                          "specification, expected in practice), give every user a unique id with role-based access, keep audit logs of who accessed PHI, test backups and restores, and "
                          "check for each service you use that its region and BAA coverage hold. This is not legal advice.", fields)
    if "soc2" in notes:
        code, sev, msg, fields = notes["soc2"]
        notes["soc2"] = (code, sev, msg + " The report comes from an independent auditor: a Type I report looks at one date, a Type II at how controls operated over a review period "
                         "(usually several months), and the audit fee plus the work to prepare evidence can cost as much as or more than the infrastructure for a small product (planning heuristic). Buy from vendors that publish their own SOC 2 reports "
                         "where you can, and plan your audit separately.", fields)
    p = psp(ctx) if "pci_dss" in notes else None
    if p:
        code, sev, msg, fields = notes["pci_dss"]
        notes["pci_dss"] = (code, "warning",
                            f"PCI DSS v4.0.1: project.description says this system itself accepts or routes card payments for merchants ('{p[1]}'), so it stores, processes or transmits "
                            "cardholder data as a service provider and the hosted-checkout shortcut (SAQ A) does not apply. Scope is what you design: keep raw card numbers inside one small, "
                            "segmented cardholder-data environment, tokenise them there and give everything else tokens only, hold keys in an HSM or a managed key service, "
                            "log and monitor every access to that environment, and keep an audit trail that cannot be edited. "
                            "Card brands place service providers handling over 300,000 card transactions a year, and Mastercard any payment gateway or processor, at Level 1 "
                            "(an annual Report on Compliance by a Qualified Security Assessor) under the card-scheme rules (Mastercard Site Data Protection programme), "
                            "so confirm your level with your acquirer early: the assessment and its remediation can cost more than the infrastructure (planning heuristic).", fields + ["project.description"])
    return notes


def data_path_warnings(ctx, supporting, host):
    """[(code, severity, message, fields)]: a vendor service that handles end users' data, with no data location in the knowledge base, under a named residency."""
    if not ctx["res_named"]:
        return []
    out = []
    for s in supporting:
        ch = s["choice"]
        layer = "email" if ch.startswith("Email delivery") else s["layer"]
        if (layer not in DATA_PATH_LAYERS or s["data_bearing"] or s["data_location"] or s["deployment"] not in ("saas", "managed")
                or s.get("provider") in (host["provider"], None) or s.get("provider") in IN_REGION_PROVIDERS
                or "(existing" in ch or ch.startswith("Staff sign-in")):  # an identity provider the company already runs is its decision, not a new vendor
            continue
        if layer == "realtime" and "managed WebRTC" not in ch:
            continue  # a self-hosted media server or a realtime layer inside the chosen cloud keeps data in the chosen region
        what = {"auth": "phone numbers and sign-in data", "realtime": "call audio and video", "email": "recipient addresses and message content"}[layer]
        area = {"EU": "the EU", "US": "the US", "INDIA": "India"}.get(ctx["res_label"], ctx["res_label"])
        out.append(("DATA_PATH_RESIDENCY", "warning",
                    f"{ch.split(';')[0]}: {what} pass through this vendor, and the knowledge base does not state where it processes them, so it is not confirmed to stay in {area} "
                    f"(data_residency is {ctx['req']['infrastructure.data_residency']}). A gap, not a proven conflict: check its data-processing terms and regions, "
                    + ("pick a provider that states processing in the region, "
                       if layer == "auth" else "self-host a media server (LiveKit) or pick a provider that states a regional deployment, "
                       if layer == "realtime" else "pick a sending region that matches, ")
                    + "or record the transfer mechanism you rely on.",
                    ctx["res_paths"] + ["project.description"]))
    return out
