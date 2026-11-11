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


def weight_grid(req):
    """Fixed, ordered grid of priority vectors (no randomness): every single priority at every other value 1-5, then
    every ordered pair 'favour one (5) over another (1)'. Vectors equal to the scenario's own weights are skipped."""
    cur = {k: req[f"priorities.{k}"] for k in PRIO}
    out = [{k: v} for k in PRIO for v in range(1, 6) if v != cur[k]]
    for i, a in enumerate(PRIO):
        for b in PRIO[i + 1:]:
            for hi, lo in ((a, b), (b, a)):
                if cur[hi] != 5 or cur[lo] != 1:
                    out.append({hi: 5, lo: 1})
    return out


def stability(doc, req, run):
    """Per core layer: share of grid vectors that keep the choice, the runner-up outcomes, and the nearest single-priority flip."""
    vectors = weight_grid(req)
    base = {k: doc["stack"][k].get("kb_id") for k in LAYERS}
    same = {k: 0 for k in LAYERS}
    alts = {k: {} for k in LAYERS}
    flip = {k: None for k in LAYERS}  # (distance, priority order, value order, record)
    for vec in vectors:
        r2 = dict(req)
        for k, v in vec.items():
            r2[f"priorities.{k}"] = v
        out = run(r2)
        for layer in LAYERS:
            new = out["stack"][layer] if out.get("stack") else None
            if new is None or new.get("kb_id") == base[layer]:
                same[layer] += 1
                continue
            alts[layer][new["choice"]] = alts[layer].get(new["choice"], 0) + 1
            if len(vec) == 1:
                (k, v), = vec.items()
                key = (abs(v - req[f"priorities.{k}"]), PRIO.index(k), v)
                if flip[layer] is None or key < flip[layer][0]:
                    flip[layer] = (key, {"priority": k, "from": req[f"priorities.{k}"], "value": v, "new_choice": new["choice"]})
    n = len(vectors)
    for layer in LAYERS:
        score = round(same[layer] / n, 2)
        doc["stack"][layer]["stability"] = {
            "score": score, "vectors_tested": n,
            "label": "robust" if score >= 0.9 else "moderate" if score >= 0.7 else "sensitive",
            "alternatives": [{"choice": c, "share": round(m / n, 2)} for c, m in sorted(alts[layer].items(), key=lambda x: (-x[1], x[0]))[:2]],
            "flip_point": flip[layer][1] if flip[layer] else None}


def confidence(doc):
    """One label per core layer: low if the choice is sensitive (stability < 0.7) or a near-tie (margin < 1.0),
    high if robust (>= 0.9) with a clear margin (>= 2.0, or no scored runner-up), else medium. Plus a contrastive
    sentence 'X rather than Y: reason. Trade-off accepted: limit.' built from the existing alternatives and tradeoffs."""
    for layer in LAYERS:
        c = doc["stack"][layer]
        st, m = c["stability"]["score"], c.get("score_margin")
        label = ("low" if st < 0.7 or (m is not None and m < 1.0) else
                 "high" if st >= 0.9 and (m is None or m >= 2.0) else "medium")
        basis = f"stability {st:.2f} ({c['stability']['label']}) over {c['stability']['vectors_tested']} priority vectors"
        if m is not None:
            basis += f"; score margin {m} over the runner-up" + (" (near-tie)" if m < 1.0 else "")
        c["confidence"] = {"label": label, "basis": basis + "."}
        if c["alternatives"]:
            alt = c["alternatives"][0]
            why = alt["why_not"].split(" Overall ")[0].split(" Known limit ")[0].rstrip(".")
            subject = f"No {layer}" if c.get("kb_id") in (None, "none") or c["choice"] == "None" else c["choice"].split(" — ")[0]
            s = f"{subject} rather than {alt['choice']}. {why[:1].upper() + why[1:]}."
            if c["tradeoffs"]:
                s += f" Trade-off accepted: {c['tradeoffs'][0].rstrip('.')}."
            c["contrast"] = s


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
    stability(doc, req, run)
    confidence(doc)
    for k in LAYERS:
        doc["stack"][k]["what_would_change"] = found[k] or [
            {"edit": "none in the probe set", "path": None, "value": None, "also_by": [],
             "new_choice": "No single-field edit among the probed priorities, requirements, numbers and constraints changes this choice"
                           + (" (the managed provider still follows the hosting choice)." if k == "database" else ".")}]
    return doc
