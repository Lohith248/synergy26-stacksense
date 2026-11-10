"""Independent checker for the StackSense output contract (PDF Section 4, pp7-8).

Written from the statement, not from the engine's serializer. Usage:
    python tools/check_contract.py outputs/P1_output.json [more files...]
Exit code 0 when every file passes.
"""
import json
import math
import sys

STATUS = {"ok", "ok_with_warnings", "infeasible", "invalid_input"}
STYLES = {"static", "monolith", "modular_monolith", "serverless", "service_oriented",
          "microservices", "hybrid", "other"}
SUPPORT_LAYERS = {"cache", "queue", "search", "auth", "storage", "cdn", "realtime", "payments",
                  "ml", "ci_cd", "observability", "other"}
SEVERITY = {"info", "warning", "critical"}
CORE = ("frontend", "backend", "database", "hosting")
INPUT_PATHS = {
    "project.name", "project.type", "project.description", "project.platforms",
    "scale.users_at_launch", "scale.users_12_months", "scale.peak_concurrent_users",
    "scale.traffic_pattern", "scale.workload", "scale.data_volume_gb_12_months",
    "team.size", "team.experience", "team.languages", "team.has_devops",
    "budget.monthly_infra_usd", "timeline.mvp_weeks",
    "infrastructure.cloud_preference", "infrastructure.deployment_model",
    "infrastructure.data_residency", "infrastructure.existing_systems",
    "requirements.realtime", "requirements.offline_support", "requirements.full_text_search",
    "requirements.file_media_storage", "requirements.payments", "requirements.auth",
    "requirements.multi_tenant", "requirements.ml_features", "requirements.seo_critical",
    "requirements.availability", "requirements.p95_latency_ms", "compliance",
    "priorities.cost", "priorities.time_to_market", "priorities.scalability",
    "priorities.performance", "priorities.maintainability", "priorities.security",
}


def _str(x):
    return isinstance(x, str) and x.strip() != ""


def check_component(c, where, core, errs):
    if not isinstance(c, dict):
        errs.append(f"{where}: not an object")
        return
    for k in ("choice", "justification"):
        if not _str(c.get(k)):
            errs.append(f"{where}.{k}: missing or empty")
    db = c.get("driven_by")
    if not isinstance(db, list) or not db or not all(_str(p) for p in db):
        errs.append(f"{where}.driven_by: must be a non-empty list of input paths")
    else:
        for p in db:
            if p not in INPUT_PATHS:
                errs.append(f"{where}.driven_by: '{p}' is not a Section 3 input path")
    alts = c.get("alternatives")
    if not isinstance(alts, list):
        errs.append(f"{where}.alternatives: must be a list")
    else:
        if core and len(alts) < 1:
            errs.append(f"{where}.alternatives: core layers need at least one")
        for i, a in enumerate(alts):
            if not (isinstance(a, dict) and _str(a.get("choice")) and _str(a.get("why_not"))):
                errs.append(f"{where}.alternatives[{i}]: needs choice and why_not")
    if "tradeoffs" in c and not (isinstance(c["tradeoffs"], list) and all(_str(t) for t in c["tradeoffs"])):
        errs.append(f"{where}.tradeoffs: must be a list of strings")


def check(doc):
    errs = []
    if not isinstance(doc, dict):
        return ["root: not an object"]
    for k in ("status", "summary", "architecture_style", "stack", "estimated_monthly_cost_usd",
              "warnings", "assumptions", "validation_errors"):
        if k not in doc:
            errs.append(f"missing required key '{k}'")
    if errs:
        return errs
    st = doc["status"]
    if st not in STATUS:
        errs.append(f"status '{st}' not allowed")
    if not _str(doc["summary"]):
        errs.append("summary: empty")
    if doc["architecture_style"] not in STYLES:
        errs.append(f"architecture_style '{doc['architecture_style']}' not allowed")
    stack = doc["stack"]
    if st in ("invalid_input", "infeasible"):
        if stack is not None:
            errs.append(f"stack must be null when status is {st}")
    else:
        if not isinstance(stack, dict):
            errs.append("stack must be an object")
        else:
            for layer in CORE:
                check_component(stack.get(layer), f"stack.{layer}", True, errs)
            sup = stack.get("supporting", [])
            if not isinstance(sup, list):
                errs.append("stack.supporting: must be a list")
            else:
                for i, s in enumerate(sup):
                    if not isinstance(s, dict) or s.get("layer") not in SUPPORT_LAYERS:
                        errs.append(f"stack.supporting[{i}].layer not in allowed list")
                    check_component(s, f"stack.supporting[{i}]", False, errs)
    cost = doc["estimated_monthly_cost_usd"]
    if not isinstance(cost, dict) or not isinstance(cost.get("assumptions"), list) or not cost.get("assumptions"):
        errs.append("estimated_monthly_cost_usd: needs min, max and non-empty assumptions")
    else:
        lo, hi = cost.get("min"), cost.get("max")
        if st in ("invalid_input", "infeasible") and lo is None and hi is None:
            pass
        elif not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
                     for v in (lo, hi)):
            errs.append("estimated_monthly_cost_usd: min/max must be finite non-negative numbers")
        elif lo > hi:
            errs.append("estimated_monthly_cost_usd: min > max")
    if not isinstance(doc["warnings"], list):
        errs.append("warnings: must be a list")
    else:
        for i, w in enumerate(doc["warnings"]):
            if not (isinstance(w, dict) and _str(w.get("code")) and w.get("severity") in SEVERITY
                    and _str(w.get("message")) and isinstance(w.get("fields"), list)):
                errs.append(f"warnings[{i}]: needs code, severity(info|warning|critical), message, fields[]")
    if not (isinstance(doc["assumptions"], list) and all(_str(a) for a in doc["assumptions"])):
        errs.append("assumptions: must be a list of strings")
    ve = doc["validation_errors"]
    if not isinstance(ve, list):
        errs.append("validation_errors: must be a list")
    else:
        for i, e in enumerate(ve):
            if not (isinstance(e, dict) and _str(e.get("field")) and _str(e.get("message"))):
                errs.append(f"validation_errors[{i}]: needs field and message")
        if (st == "invalid_input") != bool(ve):
            errs.append("validation_errors must be non-empty exactly when status is invalid_input")
    if st == "infeasible" and not any(isinstance(w, dict) and w.get("severity") == "critical"
                                      for w in doc["warnings"] if isinstance(doc["warnings"], list)):
        errs.append("infeasible needs at least one critical warning")
    if st == "ok" and any(isinstance(w, dict) and w.get("severity") in ("warning", "critical")
                          for w in doc["warnings"]):
        errs.append("status ok but warning/critical warnings present")
    return errs


def main(paths):
    bad = 0
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
            errs = check(doc)
        except (OSError, ValueError) as e:
            errs = [f"cannot read: {e}"]
        print(f"{'PASS' if not errs else 'FAIL'} {p}")
        for e in errs:
            print(f"   - {e}")
        bad += bool(errs)
    return 1 if bad or not paths else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
