"""`stacksense.py fields`: every input with its type, default, validation rule and the decisions it affects.

Types, defaults and rules are read from validate.FIELDS (single source of truth). AFFECTS lists what a
one-field change moved in a sweep over 18+ scenarios (tests/test_fields.py re-runs that sweep and fails if an
observed effect is missing here): a layer name = the chosen product flipped; supporting = the supporting
services changed; cost / warnings = the cost band / warning codes changed; ranking = only scores,
margins or justifications moved.
"""
import json

from .validate import FIELDS, EXTRA_PATHS

KIND = {"str": "string", "enum": "enum", "xenum": "enum", "enum_list": "list of enum", "enum_list0": "list of enum",
        "int": "integer", "xint": "integer", "num": "number", "bool": "boolean", "str_list": "list of strings",
        "xlist": "list of strings", "opt_int": "integer or null", "prio": "integer"}

AFFECTS = {
    "project.name": "",
    "project.type": "frontend backend database hosting supporting cost warnings ranking",
    "project.description": "frontend backend supporting cost warnings ranking",
    "project.platforms": "frontend backend database hosting supporting cost warnings",
    "scale.users_at_launch": "cost warnings ranking",
    "scale.users_12_months": "frontend backend database hosting supporting cost warnings ranking",
    "scale.peak_concurrent_users": "frontend backend database hosting supporting cost warnings ranking",
    "scale.traffic_pattern": "database hosting supporting cost warnings ranking",
    "scale.workload": "supporting cost ranking",
    "scale.data_volume_gb_12_months": "supporting cost warnings ranking",
    "team.size": "frontend backend supporting cost warnings ranking",
    "team.experience": "frontend backend warnings ranking",
    "team.languages": "frontend backend hosting supporting cost warnings ranking",
    "team.has_devops": "ranking",
    "budget.monthly_infra_usd": "database hosting supporting cost warnings ranking",
    "timeline.mvp_weeks": "warnings ranking",
    "infrastructure.cloud_preference": "database hosting supporting cost warnings ranking",
    "infrastructure.deployment_model": "database hosting supporting cost warnings ranking",
    "infrastructure.data_residency": "database supporting cost warnings ranking",
    "infrastructure.existing_systems": "backend database supporting cost warnings ranking",
    "requirements.realtime": "frontend backend database hosting supporting cost warnings ranking",
    "requirements.offline_support": "frontend backend database hosting supporting cost warnings ranking",
    "requirements.full_text_search": "supporting cost warnings ranking",
    "requirements.file_media_storage": "frontend backend database hosting supporting cost warnings",
    "requirements.payments": "frontend backend database hosting supporting cost warnings ranking",
    "requirements.auth": "frontend backend database hosting supporting cost warnings ranking",
    "requirements.multi_tenant": "frontend backend database hosting supporting cost warnings ranking",
    "requirements.ml_features": "frontend backend database hosting supporting cost warnings ranking",
    "requirements.seo_critical": "frontend supporting cost warnings ranking",
    "requirements.availability": "database hosting supporting cost warnings ranking",
    "requirements.p95_latency_ms": "supporting cost warnings ranking",
    "compliance": "frontend backend database hosting supporting cost warnings ranking",
    "priorities.cost": "frontend backend database hosting supporting cost warnings ranking",
    "priorities.time_to_market": "frontend backend database hosting supporting cost warnings ranking",
    "priorities.scalability": "frontend backend database hosting supporting cost warnings ranking",
    "priorities.performance": "frontend backend supporting cost warnings ranking",
    "priorities.maintainability": "frontend backend database hosting supporting cost warnings ranking",
    "priorities.security": "frontend backend hosting supporting cost warnings ranking",
    "scale.peak_rps": "frontend backend database hosting supporting cost warnings ranking",
    "scale.geo_spread": "supporting cost warnings",
    "team.hiring_languages": "frontend backend supporting cost warnings ranking",
    "infrastructure.lock_in_tolerance": "database hosting supporting cost warnings ranking",
    "requirements.rto_minutes": "database cost warnings ranking",
    "requirements.rpo_minutes": "database cost warnings ranking",
    "infrastructure.residency_country": "database hosting supporting warnings ranking",
}

HOW = {
    "project.name": "Label only; names never affect choices.",
    "project.type": "Selects domain rules: static site vs app, game/IoT/analytics/API/B2B/desktop handling, domain services.",
    "project.description": "Keyword signals (loans/ledger, employees-only, device message rates, game genre such as turn-based or fast-action, simultaneous editing) add services and warnings; employees-only, turn-based play and no co-editing also keep a CDN, game servers or a CRDT sync server out, with a note (D13).",
    "project.platforms": "Picks web/native/cross-platform clients; web adds SEO and CDN reasoning; api_only drops the client.",
    "scale.users_at_launch": "Sets the launch sizing tier and the peak-equals-launch assumption used for cost.",
    "scale.users_12_months": "Sets the scale tier that sizes hosting, database plan, cache/queue needs and cost bands.",
    "scale.peak_concurrent_users": "Sizes concurrency (people, not requests/s): hosting plan, database tier, backend scale ceiling.",
    "scale.traffic_pattern": "Spiky/seasonal favour request-based autoscaling and scale-to-zero over always-on plans.",
    "scale.workload": "read_heavy adds caching/read replicas at medium+ scale; write_heavy raises database and queue needs.",
    "scale.data_volume_gb_12_months": "Drives storage cost, partitioning/lifecycle notes and the analytics warehouse: for a data_analytics project, 100 GB or more (planning heuristic) adds one; below that reports run on the application database, with a note.",
    "team.size": "Scales CI/CD cost with team size; feeds scope-versus-team warnings; a team of up to 4 may get one Next.js app as UI and API.",
    "team.experience": "Raises learning-curve penalty for complex frameworks; managed services for beginners; scope warnings.",
    "team.languages": "Language fit for backend and client frameworks; a mismatch is penalised and warned.",
    "team.has_devops": "Operations-burden term in hosting scores (managed PaaS for teams without DevOps); availability warning.",
    "budget.monthly_infra_usd": "Budget terms for hosting and database; BUDGET_EXCEEDED / AT_RISK / FAR_ABOVE_NEED warnings.",
    "timeline.mvp_weeks": "Favours fast-to-ship stacks; TIMELINE_VS_SCOPE and scope warnings.",
    "infrastructure.cloud_preference": "Restricts hosting, database and services to that provider (or none for self-run).",
    "infrastructure.deployment_model": "managed_cloud vs VM vs on-premise vs air-gapped: filters hosting and every managed service.",
    "infrastructure.data_residency": "Pins regions for database, hosting and data-bearing services; warns when it cannot.",
    "infrastructure.existing_systems": "Reuses recognised systems (identity providers, brokers; a database that must stay becomes the database); credits the existing app's language; warns on end-of-life ones. A name it does not know is read by keyword (database, broker, identity, API, system of record, health interchange) and handled by that category.",
    "requirements.realtime": "Adds WebSocket/managed realtime service; penalises functions; favours realtime-capable backends.",
    "requirements.offline_support": "Local-first clients (PWA/SQLite sync); affects frontend and sync service.",
    "requirements.full_text_search": "Database full-text search or a dedicated engine, by scale and provider.",
    "requirements.file_media_storage": "Adds object storage and CDN in the data region; affects upload and hosting limits.",
    "requirements.payments": "Chooses a gateway by region/goods type (Razorpay, Stripe, store billing); PCI warnings.",
    "requirements.auth": "Chooses identity service (OTP, social, SSO, per-customer federation) and backend fit.",
    "requirements.multi_tenant": "Adds tenant isolation; changes database/auth choices for B2B SaaS.",
    "requirements.ml_features": "Adds model-serving or RAG services and vector storage; favours Python ecosystems.",
    "requirements.seo_critical": "Favours server-rendered or static frameworks; warns when no web platform exists.",
    "requirements.availability": "Higher targets force multi-zone hosting and database HA, which raises cost; 99.99 on AWS/Azure/GCP adds a second-region warm standby in the same residency area.",
    "requirements.p95_latency_ms": "Latency target check against the stack and region; warns when it cannot be measured. For a game, 100 ms or less (planning heuristic) adds dedicated game servers; above that, or turn-based play, keeps live updates in the backend with a note.",
    "compliance": "Adds controls, regional pins and warnings (HIPAA BAA, PCI scope, RBI, DPDP, GDPR, SOC 2, ISO 27001).",
    "priorities.cost": "Score weight (1-5) for low running cost across hosting, database and frontend.",
    "priorities.time_to_market": "Score weight for fast delivery and low learning curve.",
    "priorities.scalability": "Score weight for scale ceilings of backend, database and hosting.",
    "priorities.performance": "Score weight for runtime speed of backend and frontend.",
    "priorities.maintainability": "Score weight for long-term upkeep and ecosystem maturity.",
    "priorities.security": "Score weight for security tooling and managed hardening.",
    "scale.peak_rps": "Optional: requests/s tier; the higher of this and the user-count tier is used for sizing.",
    "scale.geo_spread": "Optional: multi-region/global users add a latency note and CDN/replica advice.",
    "team.hiring_languages": "Optional: languages the team will hire for count at half the weight of languages already written.",
    "infrastructure.lock_in_tolerance": "Optional: low penalises provider-specific runtimes and data stores.",
    "requirements.rto_minutes": "Optional: recovery time objective; under 60 min adds a zone-redundant database standby and a second app instance; under 5 min warns.",
    "requirements.rpo_minutes": "Optional: recovery point objective; under 5 min adds a zone-redundant standby (managed) or a replication warning (self-hosted).",
    "infrastructure.residency_country": "Optional: with data_residency other, names the country whose regions every data store must use; ignored otherwise.",
}


def _rule(kind, extra):
    if kind in ("enum", "xenum"):
        return "one of " + ", ".join(extra)
    if kind in ("enum_list", "enum_list0"):
        return ("list, at least one; " if kind == "enum_list" else "list, may be empty; ") + "each one of " + ", ".join(extra)
    if kind in ("int", "xint"):
        return f"whole number >= {extra}"
    if kind == "num":
        return f"finite number >= {extra}"
    if kind == "opt_int":
        return f"whole number >= {extra}, or null for no target"
    if kind == "bool":
        return "true or false"
    if kind == "prio":
        return "whole number 1 to 5"
    if kind in ("str_list", "xlist"):
        return "list of strings (names are trimmed and lower-cased)"
    return "any text"


def rows():
    out = []
    for path, kind, required, default, extra in FIELDS:
        out.append({"field": path, "type": KIND[kind], "required": required, "default": default,
                    "rule": _rule(kind, extra), "affects": AFFECTS[path].split(), "how": HOW[path],
                    "optional_extra": path in EXTRA_PATHS})
    return out


def render(as_json=False):
    rs = rows()
    if as_json:
        return json.dumps(rs, indent=1)
    lines = ["StackSense input fields (%d; %d are optional extras beyond the standard schema)" % (
        len(rs), sum(r["optional_extra"] for r in rs)), ""]
    for r in rs:
        if r["required"]:
            dflt = "none (required)"
        elif r["default"] is None:
            dflt = "not set" + (": engine does not use it" if r["optional_extra"] else ": recorded as an assumption")
        else:
            dflt = repr(r["default"])
        lines += [f"{r['field']}  [{r['type']}{', optional extra' if r['optional_extra'] else ''}]",
                  f"    required: {'yes' if r['required'] else 'no'}   default: {dflt}",
                  f"    rule: {r['rule']}",
                  f"    affects: {', '.join(r['affects']) or 'nothing'}",
                  f"    how: {r['how']}", ""]
    return "\n".join(lines)
