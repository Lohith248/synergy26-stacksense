"""Perturbation sweep: change one input field at a time on every public scenario and report what moves.

Usage: python tools/perturb.py [scenarios.json] [--json out.json]
Flags: crashes, hard-constraint violations (via the contract checker's envelope rules), and the number of
core layers that change per single-field edit. A field edit that is unrelated to a layer (for example a
priority not touching the database) yet flips it is listed as a candidate non-local flip for human review.
Deterministic; stdlib only.
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from engine.run import evaluate  # noqa: E402
from engine.validate import FIELDS  # noqa: E402
import check_contract  # noqa: E402

CORE = ("frontend", "backend", "database", "hosting")


def get(d, path):
    for p in path.split("."):
        if not isinstance(d, dict) or p not in d:
            return None
        d = d[p]
    return d


def put(d, path, v):
    parts = path.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = v


def base_name(choice):
    return choice.split(" — ")[0] if choice else choice


def core(doc):
    st = doc.get("stack") or {}
    return {k: base_name((st.get(k) or {}).get("choice")) for k in CORE}


def supp(doc):
    st = doc.get("stack") or {}
    return sorted(f"{s['layer']}:{base_name(s['choice'])}" for s in st.get("supporting", []))


HYPER = ("aws", "azure", "gcp")


def hard_violations(doc, sc):
    """Hard-constraint envelope (PDF 5.3) checked independently of the engine's own filters."""
    st = doc.get("stack")
    if not st:
        return []
    inf = sc.get("infrastructure", {})
    cloud, dep = inf.get("cloud_preference", "any"), inf.get("deployment_model", "managed_cloud")
    res = inf.get("data_residency", "none")
    if res == "none" and "rbi_localisation" in sc.get("compliance", []):
        res = "india"
    codes = {w["code"] for w in doc["warnings"]}
    out = []
    comps = [st[k] for k in CORE] + st.get("supporting", [])
    for c in comps:
        if c["choice"] == "None":
            continue
        name = f"{c.get('layer', '?')}:{c['choice']}"
        reuse = c.get("layer") in ("auth", "other") and "EXISTING_CROSS_CLOUD_SERVICE" in codes
        if cloud in HYPER and c.get("provider") in HYPER and c["provider"] != cloud and not reuse:
            out.append(f"{name} on {c['provider']} breaks cloud_preference {cloud}")
        if dep in ("on_premise", "air_gapped") and c.get("deployment") not in ("self_hosted", "client", "none", "library"):
            ok = (c.get("layer") == "payments" and "EXTERNAL_PAYMENT_GATEWAY" in codes) or (
                c.get("layer") == "auth" and "EXTERNAL_IDENTITY_PROVIDER" in codes) or (
                c.get("layer") == "other" and "EXTERNAL_EXISTING_SERVICE" in codes)
            if not ok:
                out.append(f"{name} is {c.get('deployment')} under {dep}")
        if res in ("india", "eu", "us") and c.get("data_bearing") and c.get("data_location") not in (res, "device"):
            if not (c.get("layer") == "payments" and "PAYMENT_DATA_LOCATION" in codes) and "RESIDENCY_UNVERIFIED_SERVICE" not in codes:
                out.append(f"{name} stores data in {c.get('data_location')} but residency is {res}")
    if dep in ("on_premise", "air_gapped") and any(s["layer"] == "cdn" for s in st.get("supporting", [])):
        out.append(f"CDN under {dep}")
    if cloud == "none" and dep in ("managed_cloud", "self_hosted_cloud_vm"):
        out.append("stack produced for cloud none + cloud deployment")
    return out


def variants(path, kind, cur, extra):
    if kind == "enum":
        return [v for v in extra if v != cur]
    if kind == "bool":
        return [not cur]
    if kind == "prio":
        return [v for v in (1, 2, 3, 4, 5) if v != cur]
    if kind in ("int", "num", "opt_int"):
        c = cur or 0
        vals = {0, 1, max(0, int(c * 0.5)), int(c * 2), int(c * 10), int(c * 1.2) + 1}
        if kind == "opt_int":
            vals |= {50, 100, 150, 300, 1000}
            vals.discard(0)
        if path in ("team.size", "timeline.mvp_weeks"):
            vals.discard(0)
        return sorted(v for v in vals if v != c)
    if kind == "enum_list":
        return [[p] for p in extra if [p] != cur] + [sorted(set(cur) | {"ios"}), sorted(set(cur) | {"desktop"})]
    if kind == "enum_list0":
        return [[]] + [sorted(set(cur) | {v}) for v in extra if v not in cur]
    if kind == "str_list" and path == "team.languages":
        return [[], ["python"], ["java"], ["csharp"], ["go"], ["php"], ["typescript"], ["kotlin"], ["ruby"]]
    if kind == "str_list":
        return [[], ["PostgreSQL 16"], ["Okta"], ["Node 18 API"]]
    return []


def main(argv):
    path = "scenarios/stacksense_public_scenarios.json"
    out_json = None
    args = list(argv)
    if "--json" in args:
        i = args.index("--json")
        out_json = args[i + 1]
        del args[i:i + 2]
    if args:
        path = args[0]
    with open(path, encoding="utf-8") as f:
        scenarios = json.load(f)
    rows, crashes, violations = [], [], []
    for sc in scenarios:
        sid = sc["scenario_id"]
        base = evaluate(copy.deepcopy(sc))
        bcore, bsupp = core(base), supp(base)
        for fpath, kind, _req, _default, extra in FIELDS:
            cur = get(sc, fpath)
            for v in variants(fpath, kind, cur, extra):
                s2 = copy.deepcopy(sc)
                put(s2, fpath, v)
                try:
                    doc = evaluate(s2)
                except Exception as e:  # noqa: BLE001
                    crashes.append((sid, fpath, v, repr(e)))
                    continue
                errs = check_contract.check(doc) + hard_violations(doc, s2)
                if errs:
                    violations.append((sid, fpath, v, errs[:3]))
                if doc["status"] in ("invalid_input", "infeasible"):
                    rows.append({"sid": sid, "field": fpath, "value": v, "status": doc["status"], "changed": ["*stack*"]})
                    continue
                c2 = core(doc)
                changed = [k for k in CORE if c2[k] != bcore[k]]
                s_add = sorted(set(supp(doc)) - set(bsupp))
                s_del = sorted(set(bsupp) - set(supp(doc)))
                rows.append({"sid": sid, "field": fpath, "value": v, "status": doc["status"], "changed": changed,
                             "core": {k: c2[k] for k in changed}, "supp_add": s_add, "supp_del": s_del,
                             "cost": [doc["estimated_monthly_cost_usd"]["min"], doc["estimated_monthly_cost_usd"]["max"]]})
    flips = [r for r in rows if r["changed"] and r["changed"] != ["*stack*"]]
    multi = [r for r in flips if len(r["changed"]) >= 3]
    print(f"perturbations: {len(rows) + len(crashes)}  crashes: {len(crashes)}  contract violations: {len(violations)}")
    print(f"core changes: {len(flips)}  three-or-more-layer changes: {len(multi)}")
    for r in flips:
        print(f"  {r['sid']} {r['field']}={json.dumps(r['value'])}: " + "; ".join(f"{k}->{r['core'][k]}" for k in r["changed"]))
    for c in crashes:
        print("  CRASH", c)
    for v in violations:
        print("  VIOLATION", v)
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "crashes": crashes, "violations": violations}, f, indent=1, default=str)
    return 1 if crashes or violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
