"""Strict validation of the standard input schema (PDF Section 3.1, pp4-5) with recorded defaults."""
import difflib
import math

PROJECT_TYPES = ["content_site", "web_app", "saas_b2b", "ecommerce", "marketplace", "social", "realtime_collab",
                 "fintech", "healthtech", "data_analytics", "iot", "ai_ml_product", "internal_tool", "gaming",
                 "api_platform", "other"]
PLATFORMS = ["web", "android", "ios", "desktop", "api_only"]
PRIORITY_KEYS = ["cost", "time_to_market", "scalability", "performance", "maintainability", "security"]

# path -> (kind, required, default, extra). default None with required False = "unspecified".
# kinds: str, enum, enum_list, int, num, bool, str_list, opt_int
FIELDS = [
    ("project.name", "str", False, None, None),
    ("project.type", "enum", True, None, PROJECT_TYPES),
    ("project.description", "str", False, None, None),
    ("project.platforms", "enum_list", True, None, PLATFORMS),
    ("scale.users_at_launch", "int", True, None, 0),
    ("scale.users_12_months", "int", True, None, 0),
    ("scale.peak_concurrent_users", "int", False, None, 0),
    ("scale.traffic_pattern", "enum", False, "steady", ["steady", "spiky", "seasonal"]),
    ("scale.workload", "enum", False, "balanced", ["read_heavy", "balanced", "write_heavy"]),
    ("scale.data_volume_gb_12_months", "num", False, None, 0),
    ("team.size", "int", True, None, 1),
    ("team.experience", "enum", True, None, ["beginner", "intermediate", "senior", "mixed"]),
    ("team.languages", "str_list", True, None, None),
    ("team.has_devops", "bool", False, False, None),
    ("budget.monthly_infra_usd", "num", True, None, 0),
    ("timeline.mvp_weeks", "int", True, None, 1),
    ("infrastructure.cloud_preference", "enum", False, "any", ["any", "aws", "gcp", "azure", "none"]),
    ("infrastructure.deployment_model", "enum", False, "managed_cloud",
     ["managed_cloud", "self_hosted_cloud_vm", "on_premise", "air_gapped"]),
    ("infrastructure.data_residency", "enum", False, "none", ["none", "india", "eu", "us", "other"]),
    ("infrastructure.existing_systems", "str_list", False, [], None),
    ("requirements.realtime", "bool", False, False, None),
    ("requirements.offline_support", "bool", False, False, None),
    ("requirements.full_text_search", "bool", False, False, None),
    ("requirements.file_media_storage", "bool", False, False, None),
    ("requirements.payments", "bool", False, False, None),
    ("requirements.auth", "enum", False, "none", ["none", "email_password", "social", "phone_otp", "enterprise_sso"]),
    ("requirements.multi_tenant", "bool", False, False, None),
    ("requirements.ml_features", "enum", False, "none", ["none", "inference_api", "llm_rag", "training"]),
    ("requirements.seo_critical", "bool", False, False, None),
    ("requirements.availability", "enum", False, "99.9", ["99", "99.9", "99.95", "99.99"]),
    ("requirements.p95_latency_ms", "opt_int", False, None, 1),
    ("compliance", "enum_list0", False, [], ["gdpr", "dpdp", "hipaa", "pci_dss", "rbi_localisation", "soc2", "iso27001"]),
] + [(f"priorities.{k}", "prio", False, 3, None) for k in PRIORITY_KEYS]

# Optional extra inputs (statement p5 encourages more than the standard fields). Absent = not used, no assumption
# recorded, so files with only the standard fields behave exactly as before. Each one changes a decision; see README.
EXTRA_FIELDS = [
    ("scale.peak_rps", "xint", False, None, 0),
    ("scale.geo_spread", "xenum", False, None, ["single_region", "multi_region", "global"]),
    ("team.hiring_languages", "xlist", False, [], None),
    ("infrastructure.lock_in_tolerance", "xenum", False, None, ["low", "medium", "high"]),
    ("requirements.rto_minutes", "xint", False, None, 0),
    ("requirements.rpo_minutes", "xint", False, None, 0),
]
EXTRA_PATHS = {f[0] for f in EXTRA_FIELDS}
FIELDS = FIELDS + EXTRA_FIELDS

GROUPS = {"project", "scale", "team", "budget", "timeline", "infrastructure", "requirements", "priorities"}
UNSPECIFIED_NOTE = {
    "project.name": "project.name absent: treated as unnamed; names never affect choices.",
    "project.description": "project.description absent: no description-derived signals applied.",
    "scale.peak_concurrent_users": "scale.peak_concurrent_users absent: estimated as 10% of users_12_months for sizing only.",
    "scale.data_volume_gb_12_months": "scale.data_volume_gb_12_months absent: assumed small (<10 GB) for the cost band.",
    "requirements.p95_latency_ms": "requirements.p95_latency_ms absent or null: no explicit latency target; typical web latency assumed.",
}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    try:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    except OverflowError:
        return False


def _fmt(v):
    return repr(v) if isinstance(v, str) else str(v).lower() if isinstance(v, bool) else str(v)


def _near(word, options):
    """Closest known name (case-insensitive) or None; stdlib difflib, deterministic."""
    m = difflib.get_close_matches(str(word).lower(), [o.lower() for o in options], n=1, cutoff=0.7)
    return next((o for o in options if o.lower() == m[0]), None) if m else None


def _did_you_mean(word, options):
    n = _near(word, options) if isinstance(word, str) else None
    return f" Did you mean {n!r}?" if n else ""


_KIDS = {}
for _p, *_ in FIELDS:
    _g, _, _k = _p.partition(".")
    if _k:
        _KIDS.setdefault(_g, []).append(_k)
_TOP = sorted(GROUPS | {"scenario_id", "compliance"})


def unknown_key_warnings(raw):
    """Info warnings for keys the schema does not define (they are ignored), with a near-miss hint."""
    out = []
    if not isinstance(raw, dict):
        return out

    def add(path, known):
        out.append({"code": "UNKNOWN_FIELD", "severity": "info", "fields": [path],
                    "message": f"Unknown key '{path}' is ignored; it does not affect any decision." + _did_you_mean(path.rsplit(".", 1)[-1], known)})
    for k in raw:
        if k not in _TOP:
            add(k, _TOP)
    for g in sorted(GROUPS):
        if isinstance(raw.get(g), dict):
            for k in raw[g]:
                if k not in _KIDS[g]:
                    add(f"{g}.{k}", _KIDS[g])
    return out


def _missing_hint(raw, parts):
    """Required field missing: point at an unknown sibling key that looks like it."""
    parent = raw.get(parts[0]) if len(parts) == 2 else None
    if len(parts) == 2 and not isinstance(parent, dict):  # the whole group may be misspelled
        for k in raw:
            if k not in _TOP and _near(k, [parts[0]]):
                return f" Found unknown key '{k}'. Did you mean '{parts[0]}'?"
        return ""
    for k in (parent or {}):
        if k not in _KIDS[parts[0]] and _near(k, [parts[1]]):
            return f" Found unknown key '{parts[0]}.{k}'. Did you mean '{parts[1]}'?"
    return ""


_REQ_GROUPS = {p.split(".")[0] for p, _k, r, *_ in FIELDS if r}


def null_paths(raw):
    """Optional fields (and optional-only groups) given as JSON null: generators emit null for 'not provided', so they
    are treated exactly as absent. Required fields and requirements.p95_latency_ms (null = no target) are excluded."""
    out = []
    if not isinstance(raw, dict):
        return out
    for path, kind, required, *_ in FIELDS:
        g, _, k = path.partition(".")
        if g in raw and raw[g] is None and g not in _REQ_GROUPS:
            if g not in out:
                out.append(g)
        elif k and isinstance(raw.get(g), dict) and k in raw[g] and raw[g][k] is None and not required and kind != "opt_int":
            out.append(path)
    return out


def null_warnings(raw):
    paths = null_paths(raw)
    return [{"code": "NULL_TREATED_AS_ABSENT", "severity": "info", "fields": paths,
             "message": "Optional field(s) given as null were treated as absent; the documented defaults apply (see assumptions)."}] if paths else []


def validate(raw):
    """-> (req dict keyed by dotted path, errors [{field,message}], assumptions [str])."""
    errors, assumptions, req = [], [], {}
    if not isinstance(raw, dict):
        return None, [{"field": "$", "message": "Scenario must be a JSON object."}], []
    for g in sorted(GROUPS):
        if g in raw and raw[g] is not None and not isinstance(raw[g], dict):  # null group = absent (null_paths)
            errors.append({"field": g, "message": f"'{g}' must be an object."})
    nulls = null_paths(raw)
    for g in nulls:
        if "." not in g and g != "compliance":
            assumptions.append(f"{g} null: treated as absent, so each of its optional fields takes its default below.")
    for path, kind, required, default, extra in FIELDS:
        parts = path.split(".")
        node, present, val = raw, True, None
        for p in parts:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                present = False
                break
        val = node if present else None
        was_null = path in nulls
        if was_null:
            present = False
        if not present and path in EXTRA_PATHS:
            req[path] = list(default) if isinstance(default, list) else default
            if was_null:
                assumptions.append(f"{path} null: treated as absent (optional extra input not used).")
            continue
        if not present:
            if required:
                errors.append({"field": path, "message": "Required field is missing." + _missing_hint(raw, parts)})
            else:
                req[path] = default
                how = f"{path} null: treated as absent;" if was_null else f"{path} absent:"
                if default is not None:
                    assumptions.append(f"{how} default {_fmt(default) if not isinstance(default, list) else default} applied.")
                elif path in UNSPECIFIED_NOTE:
                    assumptions.append(f"{how} {UNSPECIFIED_NOTE[path].split(': ', 1)[1]}" if was_null else UNSPECIFIED_NOTE[path])
            continue
        msg = None
        if kind == "str":
            if not isinstance(val, str):
                msg = "Must be a string."
        elif kind in ("enum", "xenum"):
            if not isinstance(val, str) or val not in extra:
                msg = f"Must be one of {', '.join(extra)} (got {_fmt(val)})." + _did_you_mean(val, extra)
        elif kind in ("enum_list", "enum_list0"):
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                msg = "Must be a list of strings."
            elif kind == "enum_list" and not val:
                msg = "Must contain at least one value."
            else:
                bad = [x for x in val if x not in extra]
                if bad:
                    msg = f"Unknown value(s) {bad}; allowed: {', '.join(extra)}." + "".join(_did_you_mean(x, extra) for x in bad)
                elif len(set(val)) != len(val):
                    assumptions.append(f"{path}: duplicate values ignored.")
                    val = sorted(set(val), key=val.index)
        elif kind in ("int", "xint"):
            if not _is_int(val):
                msg = "Must be an integer (JSON number without fraction)."
            elif not _is_num(val):
                msg = "Outside the finite numeric range used for sizing and cost calculations."
            elif val < extra:
                msg = f"Must be >= {extra} (got {val})."
        elif kind == "opt_int":
            if val is None:
                req[path] = None
                assumptions.append(UNSPECIFIED_NOTE[path])
                continue
            if not _is_int(val) or val < extra:
                msg = "Must be a positive integer or null."
            elif not _is_num(val):
                msg = "Outside the finite numeric range used for sizing and cost calculations."
        elif kind == "num":
            if not _is_num(val):
                msg = "Must be a finite number."
            elif val < extra:
                msg = f"Must be >= {extra} (got {val})."
        elif kind == "bool":
            if not isinstance(val, bool):
                msg = f"Must be true or false (got {_fmt(val)})."
        elif kind == "prio":
            if not _is_int(val) or not 1 <= val <= 5:
                msg = f"Must be an integer from 1 to 5 (got {_fmt(val)})."
        elif kind in ("str_list", "xlist"):
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                msg = "Must be a list of strings."
            elif path in ("team.languages", "team.hiring_languages"):
                norm = [x.strip().lower() for x in val if x.strip()]
                if norm != val:
                    assumptions.append(f"{path} normalised to lower-case trimmed names.")
                val = sorted(set(norm), key=norm.index)
        if msg:
            errors.append({"field": path, "message": msg})
        else:
            req[path] = val
    return (None if errors else req), errors, assumptions
