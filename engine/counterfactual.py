"""Per-layer counterfactuals: which single input edits would change each core choice.

The engine is re-run on a fixed, ordered list of one-field edits (nearest edits first: priority +-1,
toggling a soft requirement, halving/doubling a number, then enum swaps). For every core layer the
first edits that change its knowledge-base id are reported with the new choice. This is measured,
not guessed, and deterministic: the probe list and its order never depend on the clock or hashing.
"""
LAYERS = ("frontend", "backend", "database", "hosting")
MAX_PER_LAYER = 3
PRIO = ("cost", "time_to_market", "scalability", "performance", "maintainability", "security")
BOOLS = ("requirements.realtime", "requirements.offline_support", "requirements.full_text_search",
         "requirements.file_media_storage", "requirements.payments", "requirements.multi_tenant",
         "requirements.seo_critical", "team.has_devops")
ENUMS = {
    "team.experience": ["beginner", "intermediate", "senior", "mixed"],
    "requirements.availability": ["99", "99.9", "99.95", "99.99"],
    "requirements.auth": ["none", "email_password", "social", "phone_otp", "enterprise_sso"],
    "requirements.ml_features": ["none", "inference_api", "llm_rag", "training"],
    "scale.workload": ["read_heavy", "balanced", "write_heavy"],
    "infrastructure.cloud_preference": ["any", "aws", "gcp", "azure"],
    "infrastructure.data_residency": ["none", "india", "eu", "us"],
    "infrastructure.deployment_model": ["managed_cloud", "self_hosted_cloud_vm", "on_premise", "air_gapped"],
    "infrastructure.lock_in_tolerance": ["low", "medium", "high"],  # optional extra inputs
    "scale.geo_spread": ["single_region", "multi_region", "global"],
}


def probes(req):
    """Ordered (path, new_value) edits; each is one field, each value valid under the schema."""
    near, mid, far = [], [], []
    for k in PRIO:
        v = req[f"priorities.{k}"]
        near += [(f"priorities.{k}", x) for x in (v - 1, v + 1) if 1 <= x <= 5]
        mid += [(f"priorities.{k}", x) for x in (v - 2, v + 2) if 1 <= x <= 5]
    for b in BOOLS:
        near.append((b, not req[b]))
    b = req["budget.monthly_infra_usd"]
    mid += [("budget.monthly_infra_usd", x) for x in sorted({round(b / 2, 2), b * 2 if b else 50}) if x != b]
    u = req["scale.users_12_months"]
    mid += [("scale.users_12_months", x) for x in sorted({u // 2, u * 2 if u else 1000}) if x != u
            and x >= req["scale.users_at_launch"]]
    w = req["timeline.mvp_weeks"]
    mid += [("timeline.mvp_weeks", x) for x in sorted({max(1, w // 2), w * 2}) if x != w]
    for path, vals in ENUMS.items():
        far += [(path, x) for x in vals if x != req[path]]
    far += [("budget.monthly_infra_usd", x) for x in (0, b * 10) if x != b]
    far += [("scale.users_12_months", x) for x in (u * 10,) if x != u]
    return near + mid + far


def fmt(v):
    if v is None:
        return "unset"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def annotate(doc, req, run):
    """Add what_would_change to each core layer of an ok/ok_with_warnings document.

    run(req) -> document; it must not annotate (no recursion)."""
    base = {k: doc["stack"][k].get("kb_id") for k in LAYERS}
    found = {k: [] for k in LAYERS}
    for path, val in probes(req):
        r2 = dict(req)
        r2[path] = val
        out = run(r2)
        if not out.get("stack"):
            continue
        edit = f"{path}: {fmt(req[path])} -> {fmt(val)}"
        for k in LAYERS:
            new = out["stack"][k]
            if new.get("kb_id") == base[k]:
                continue
            same = next((e for e in found[k] if e["new_choice"] == new["choice"]), None)
            if same:  # one entry per distinct outcome; further edits that lead there are listed briefly
                if len(same["also_by"]) < 3:
                    same["also_by"].append(edit)
            elif len(found[k]) < MAX_PER_LAYER:
                found[k].append({"edit": edit, "path": path, "value": val, "new_choice": new["choice"], "also_by": []})
    for k in LAYERS:
        doc["stack"][k]["what_would_change"] = found[k] or [
            {"edit": "none in the probe set", "path": None, "value": None, "also_by": [],
             "new_choice": "No single-field edit among the probed priorities, requirements, numbers and constraints changes this choice"
                           + (" (the managed provider still follows the hosting choice)." if k == "database" else ".")}]
    return doc
