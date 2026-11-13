"""Local-first desktop archetype (A2): an app that runs on the user's own computer is neither a static site nor a server product.

When platforms contain desktop and no web, mobile or api_only client, and no input asks for accounts, payments, realtime, uploads,
tenants or ML, the data lives in an embedded database on the device and nothing needs hosting. An optional upload or sync step
described in the text is a small endpoint for later, not a backend for the MVP. The PWA-desktop path (web + desktop) is unchanged.

Rules touch the static/dynamic switch, the four core components' text and supporting services; they never rank candidates.
"""
from .kb import cite

# planning heuristic: description signals (context.DESC_RX flags) and compliance regimes that mean a server-side system of record,
# so the desktop app keeps the ordinary server stack instead of the local-first one
BLOCKER_FLAGS = ("payouts", "kyc", "chat", "collab", "iot", "otp", "sms", "web3", "digital_goods", "video_vod", "video_call",
                 "jobs_dispatch", "approvals", "scoring_model", "lending")
BLOCKER_COMPLIANCE = ("hipaa", "rbi_localisation", "pci_dss")
# project types that are dynamic server products by nature stay on the server path ('web_app' and 'internal_tool' are soft types)
SERVER_TYPES = {"saas_b2b", "ecommerce", "marketplace", "social", "realtime_collab", "fintech", "healthtech", "data_analytics", "iot",
                "ai_ml_product", "gaming", "api_platform"}

# a stand-in for a hosting item: the binary is the deliverable, so nothing runs in a data centre
HOST = {"id": "binary", "name": "None (distributed binary)", "provider": "none", "deploy": "client", "kind": "binary", "regions": {},
        "cost": [[0, 0]] * 4, "limits": [], "src": ["statement"]}


def applies(c, dynamic_need):
    """True when the structured fields and the text describe a desktop-only app with no need for a server."""
    d = c["desc"]
    if not c["desktop"] or c["web"] or c["mobile"] or c["api_only"] or dynamic_need:
        return False
    if c["type"] in SERVER_TYPES or any(d[f] for f in BLOCKER_FLAGS) or set(c["compliance"]) & set(BLOCKER_COMPLIANCE):
        return False
    # a recognised existing system (database, queue, identity provider) is a server the app must talk to
    return not any(e["pattern"] for e in c["existing"])


def optional_endpoint(c):
    """The description names an upload, sync or server step: an optional endpoint for later, never part of the MVP band."""
    return bool(c["desc"]["sync_server"])


def host_why(c):
    dep = c["req"]["infrastructure.deployment_model"]
    why = ("The app runs on each user's own computer, so there is nothing to host: it is shipped as an installer or portable binary for "
           "each desktop OS (platforms: desktop only). Application data stays on the device, so data_residency is not engaged by the app itself.")
    if optional_endpoint(c):
        why += (f" infrastructure.deployment_model '{dep}' applies to the optional upload endpoint only; it is not part of this MVP"
                " and is not costed.")
    return why


def hosting_component():
    return {"choice": HOST["name"], "justification": None, "driven_by": [], "alternatives": [], "tradeoffs": [],
            "deployment": "client", "provider": "neutral", "data_bearing": False, "data_location": None,
            "sources": cite(["statement"]), "kb_id": "none-binary"}


def hosting(c):
    out = hosting_component()
    out["justification"] = host_why(c)
    out["driven_by"] = ["project.platforms", "requirements.offline_support"] + (["infrastructure.deployment_model"] if optional_endpoint(c) else [])
    out["alternatives"] = [
        {"choice": "Cloud VM or managed platform", "why_not": "nothing runs server-side for the MVP, so a hosted service would be a bill with no feature behind it"},
        {"choice": "Static site host", "why_not": "this is an installed application, not pages a browser downloads"}]
    out["tradeoffs"] = ["Each desktop OS needs its own build; code-signing certificates and an update channel are costs outside the infrastructure band",
                        "With no server, nothing is collected centrally (crashes, usage) unless users send it"]
    return out


def backend(c, none_component, quote):
    d = c["desc"]
    why = ("No application server is needed: the app runs entirely on the user's computer and keeps its records in an embedded database, "
           "so there are no accounts, payments or shared live data to serve" + ("." if optional_endpoint(c) else " and no uploads.")
           )
    paths = ["project.platforms", "requirements.auth", "requirements.offline_support"]
    alts = [("Node.js + Express", "a server to run and pay for with no feature that needs it"),
            ("Firebase or another sync backend", "a vendor sync model for data that is written and read on one machine")]
    if optional_endpoint(c):
        q = quote(c, "sync_server")
        why += (f" The description mentions an upload or server step (\"{q}\"); it is optional and happens later, so it is out of the MVP: when added it "
                "should be a small HTTPS endpoint that accepts finished data as one append-only file per upload with an idempotency key, "
                "not a live-sync service.")
        paths.append("project.description")
        alts[1] = ("Live-sync service", "the description asks for an optional later upload, not continuous sync")
    return none_component("backend", why, paths, alts)


def database(c, none_component):
    req = c["req"]
    off = req["requirements.offline_support"]
    why = ("Records live in one embedded SQLite file on the device, so the app works with no network and needs no database server; "
           "one operator per machine fits SQLite's single-writer model, and the file format has long-term support from its maintainers.")
    paths = ["project.platforms", "requirements.offline_support"] if off else ["project.platforms"]
    if req["requirements.full_text_search"]:
        why += " Search uses SQLite's built-in full-text index, so there is no separate search service."
        paths.append("requirements.full_text_search")
    out = none_component("database", why, paths,
                         [("PostgreSQL (server)", "needs a server and a network connection, which a desktop app that must work offline cannot rely on"
                           if off else "needs a server and a network connection; no shared or remote access is requested"),
                          ("Plain files (JSON/CSV)", "no transactions or indexes; an interrupted write can corrupt the only copy")])
    out.update({"choice": "SQLite (embedded, on the device)", "deployment": "library", "provider": "neutral", "data_bearing": True,
                "data_location": "device", "kb_id": "sqlite", "sources": cite(["sqlite"]),
                "tradeoffs": ["No central copy: a lost or broken device loses its data unless backups or exports exist; schedule automatic local backups to a second location",
                              "Schema changes ship inside app updates, so every release needs a tested migration"]})
    return out


def offline_service(c, svc, Z):
    sync = optional_endpoint(c)
    why = ("Must work without connectivity: every write goes into the on-device SQLite database in a transaction, so the app has no network "
           "dependency; there is no service worker (this is an installed application, not a web page) and no sync API.")
    if sync:
        why += " The optional later upload sends finished data as an append-only file with an idempotency key, so a repeated upload does not duplicate records."
    return svc("other", "Embedded database for offline use (SQLite file on the device)", why,
               ["requirements.offline_support", "project.platforms"] + (["project.description"] if sync else []),
               [("Service worker + IndexedDB", "a browser mechanism; the stated platform is a desktop application"),
                ("Offline-first sync API", "nothing is shared live, so there is nothing to synchronise")],
               ["Automatic local backups are the team's job", "Upload (if added) needs its own retry and resume rules"],
               "client", "neutral", True, Z, ["sqlite"], "device")


def search_service(c, svc, Z):
    return svc("search", "SQLite full-text search (embedded)",
               "Search runs inside the same embedded database as the data, so there is no index service to run and it works offline.",
               ["requirements.full_text_search"], [("Algolia", "a paid hosted service for a search that must also work offline")],
               ["Ranking and typo tolerance are basic"], "library", "neutral", False, Z, ["sqlite"])
