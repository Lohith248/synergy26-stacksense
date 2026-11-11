"""Orchestration: validated input -> Section 4 document. Deterministic; no clock, randomness or network."""
import re
from datetime import date  # fromisoformat only: dates are compared with the KB date, never the clock
from . import ENGINE_VERSION
from . import context as cx
from . import select as sl
from . import services as sv
from .kb import AS_OF, TECH, cite

FIELD_ORDER = [f[0] for f in __import__("engine.validate", fromlist=["FIELDS"]).FIELDS]
SKILL_BAND = 5  # a mismatched backend must beat the best skill-matched one by more than this to be chosen
HARD_PATHS = ("infrastructure.cloud_preference", "infrastructure.deployment_model", "infrastructure.data_residency")


class Warnings:
    def __init__(self):
        self.items = []

    def __call__(self, code, sev, msg, fields):
        if not any(w["code"] == code and w["message"] == msg for w in self.items):
            self.items.append({"code": code, "severity": sev, "message": msg, "fields": list(fields)})


def order_paths(paths):
    seen = []
    for p in paths:
        if p not in seen:
            seen.append(p)
    return sorted(seen, key=lambda p: FIELD_ORDER.index(p) if p in FIELD_ORDER else 999)


def hard_conflicts(ctx):
    out = []
    cloud, dep = ctx["cloud"], ctx["deploy"]
    if cloud == "none" and dep in ("managed_cloud", "self_hosted_cloud_vm"):
        out.append(("CLOUD_NONE_VS_CLOUD_DEPLOYMENT",
                    f"cloud_preference 'none' (no public cloud) contradicts deployment_model '{dep}', which runs on a public cloud. "
                    "Change one: choose on_premise/air_gapped, or allow a cloud provider.",
                    ["infrastructure.cloud_preference", "infrastructure.deployment_model"]))
    if cloud in ("aws", "azure", "gcp") and dep in ("on_premise", "air_gapped"):
        out.append(("CLOUD_PROVIDER_VS_ONPREM",
                    f"cloud_preference '{cloud}' requires {cloud.upper()} services, but deployment_model '{dep}' allows only self-hosted components on your premises. "
                    "Change one of them (provider-run on-prem hardware is out of scope for this budget class).",
                    ["infrastructure.cloud_preference", "infrastructure.deployment_model"]))
    res = ctx["req"]["infrastructure.data_residency"]
    if "rbi_localisation" in ctx["compliance"] and res in ("eu", "us"):
        out.append(("RBI_LOCALISATION_VS_RESIDENCY",
                    f"rbi_localisation requires payment data to be stored only in India, but data_residency is '{res}'.",
                    ["compliance", "infrastructure.data_residency"]))
    return out


def component(cand, ranked_ok, ranked_out, extra_paths, extras, name=None, base_why=""):
    """Build the official component object from a winning candidate and its competitors."""
    item = cand.item
    pos = sorted([t for t in cand.terms if t[1] > 0], key=lambda t: (t[0].startswith("prio_"), -t[1], t[0]))
    domain = [t for t in pos if not t[0].startswith("prio_")][:3]
    prios = [t for t in pos if t[0].startswith("prio_") and "(priority 3/5)" not in t[3]][:2]
    reasons = [t[3] for t in domain + prios] or [t[3] for t in pos if t[0].startswith("prio_")][:2]  # balanced (3/5) priorities still decide
    why = base_why + (cap("; ".join(reasons)) + "." if reasons else "")
    alts = []
    for a in ranked_ok[1:3]:
        alts.append({"choice": a.item["name"], "why_not": why_not(cand, a)})
    # excluded options are shown when a hard constraint removed them (that teaches the reader something);
    # options excluded only for not fitting the project shape are used just to reach the required minimum
    hard = [a for a in ranked_out if all(r[1] in HARD_PATHS + ("compliance",) for r in a.reasons)]
    shape = [a for a in ranked_out if a not in hard]
    for a in hard + (shape if len(alts) < 2 else []):
        if len(alts) >= 3 or (a in shape and len(alts) >= 2):
            break
        alts.append({"choice": a.item["name"], "why_not": f"Excluded: {a.excluded[0]} ({a.excluded[1]})."})
    driven = [t[2] for t in cand.terms if abs(t[1]) >= (2.5 if t[0].startswith("prio_") else 1)] + list(extra_paths)
    out = {"choice": name or item["name"], "justification": why.strip() or "Best overall fit for the stated inputs.",
           "driven_by": order_paths(driven) or ["project.type"], "alternatives": alts,
           "tradeoffs": list(item.get("limits", []))}
    out["kb_id"] = item["id"]
    if len(ranked_ok) > 1:  # score gap to the runner-up: small margins are near-ties (see what_would_change)
        out["score_margin"] = round(cand.score - ranked_ok[1].score, 1)
    out["pareto"] = pareto(cand, ranked_ok)
    out.update(extras)
    out["sources"] = cite(item.get("src", []))
    return out


PRIO_NAMES = ("cost", "time_to_market", "scalability", "performance", "maintainability", "security")


def pareto(cand, ranked_ok):
    """Dominance on the six priority ratings only (a check on the score terms could never fail: the winner maximises
    their sum). If an eligible option rates at least as well on all six and better on one, say what the choice wins on."""
    r = cand.item["r"]
    dom = [a for a in ranked_ok[1:] if a.item["r"] != r and all(x >= y for x, y in zip(a.item["r"], r))]
    if not dom:
        return {"optimal": True, "dominated_by": [],
                "note": "No eligible option rates at least as well on all six priorities (cost, delivery, scalability, performance, maintainability, security)."}
    a = dom[0]
    better = [PRIO_NAMES[i] for i, (x, y) in enumerate(zip(a.item["r"], r)) if x > y]
    wins = sorted(((cand.term(k) - a.term(k), k) for k in {t[0] for t in cand.terms} if not k.startswith("prio_")
                   and cand.term(k) - a.term(k) > 0.5), key=lambda x: (-x[0], x[1]))
    texts = [next(t[3] for t in cand.terms if t[0] == k) for _, k in wins[:2]]
    return {"optimal": False, "dominated_by": [x.item["name"] for x in dom[:2]],
            "note": f"{a.item['name']} rates at least as well on every priority and better on {', '.join(better)}; "
                    + (f"this choice wins on project fit: {'; '.join(texts)}." if texts else "this choice still scores higher overall.")}


def why_not(win, alt):
    keys = sorted({t[0] for t in win.terms} | {t[0] for t in alt.terms})
    gaps = []
    for k in keys:
        g = win.term(k) - alt.term(k)
        if g > 0.5:
            gaps.append((g, k))
    gaps.sort(key=lambda x: (-x[0], x[1]))
    weak, strong = [], []
    for g, k in gaps[:2]:
        neg = [t for t in alt.terms if t[0] == k and t[1] < 0]
        pos = [t for t in win.terms if t[0] == k and t[1] > 0]
        if neg:
            weak.append(f"{neg[0][3]} ({neg[0][2]})")
        elif pos:
            strong.append(f"{pos[0][3]} ({pos[0][2]})")
    total = round(win.score - alt.score, 1)
    lim = alt.item.get("limits") or []
    tail = f" Known limit of {alt.item['name'].split(' (')[0]}: {lim[0] if any(ch.isupper() for ch in lim[0].split(' ')[0][1:]) else lim[0][:1].lower() + lim[0][1:]}." if lim else ""
    if total < 0:
        return (f"Scores {-total} points higher ({alt.score} vs {win.score}), but the team-language preference keeps "
                f"{win.item['name']} within the {SKILL_BAND}-point switching-cost band." + tail)
    if total < 0.1:
        return (f"Tied on score ({alt.score}) with {win.item['name'].split(' (')[0]}; the stable id-based tie-break keeps the result "
                "deterministic, so either is a defensible choice." + tail)
    if not weak and not strong:
        return (f"Close runner-up (score {alt.score} vs {win.score}): many small differences, none above half a point, add up to "
                f"the {total}-point gap, so either is defensible." + tail)
    parts = []
    if weak:
        parts.append(cap("; ".join(weak)))
    if strong:
        parts.append(f"{win.item['name'].split(' — ')[0]} is stronger on: " + "; ".join(strong))
    return ". ".join(parts) + f". Overall {total} points behind." + tail


def ha_paths(req):
    """Inputs that call for zone redundancy: availability >= 99.95, or the optional RTO < 60 min / RPO < 5 min
    (planning thresholds: a restore from backup is slower than an hour for most databases, and backups are not continuous)."""
    rto, rpo = req["requirements.rto_minutes"], req["requirements.rpo_minutes"]
    return ([p for p, on in (("requirements.availability", req["requirements.availability"] in ("99.95", "99.99")),
                             ("requirements.rto_minutes", rto is not None and rto < 60),
                             ("requirements.rpo_minutes", rpo is not None and rpo < 5)) if on])


def ha_targets(req):
    names = {"requirements.availability": f"the {req['requirements.availability']}% availability target",
             "requirements.rto_minutes": f"RTO {req['requirements.rto_minutes']} min",
             "requirements.rpo_minutes": f"RPO {req['requirements.rpo_minutes']} min"}
    return [names[p] for p in ha_paths(req)]


def cap(s):
    return s[:1].upper() + s[1:] if s else s


def envelope_text(ctx, region):
    if ctx["residency"] == "other":
        return "Deployment/provider filters are met, but residency is unresolved until a jurisdiction is supplied. "
    bits = []
    if ctx["cloud"] in ("aws", "azure", "gcp"):
        bits.append(f"cloud_preference {ctx['cloud']}")
    if ctx["deploy"] != "managed_cloud":
        bits.append(f"deployment_model {ctx['deploy']}")
    else:
        bits.append("managed_cloud (no servers to patch)")
    if ctx["req"]["infrastructure.data_residency"] in ("india", "eu", "us") or ctx["residency_from_rbi"]:
        bits.append(f"data_residency {ctx['residency']}" + (f" -> {region}" if region else ""))
    return "Satisfies the hard constraints (" + ", ".join(bits) + "). " if bits else ""


def none_component(layer, why, paths, alts):
    return {"choice": "None", "justification": why, "driven_by": order_paths(paths),
            "alternatives": [{"choice": c, "why_not": w} for c, w in alts], "tradeoffs": [],
            "deployment": "none", "provider": None, "data_bearing": False, "data_location": None, "sources": [], "kb_id": "none"}


def recommend(req, assumptions, sid, probe=False):
    doc = _recommend(req, assumptions, sid)
    if not probe and doc["stack"]:
        from .counterfactual import annotate
        annotate(doc, req, lambda r: _recommend(r, [], sid))
    return doc


def _recommend(req, assumptions, sid):
    ctx = cx.build(req)
    W = Warnings()
    assumptions = list(assumptions)
    assumptions.append(f"Knowledge base as of {AS_OF}; lifecycle and pricing judgements use that date, not the run date.")
    conflicts = hard_conflicts(ctx)
    if conflicts:
        for code, msg, fields in conflicts:
            W(code, "critical", msg, fields)
        return {"scenario_id": sid, "engine_version": ENGINE_VERSION, "status": "infeasible",
                "summary": "No stack can satisfy these hard constraints together: " + " ".join(c[1].split('. ')[0] + "." for c in conflicts),
                "architecture_style": "other", "stack": None,
                "estimated_monthly_cost_usd": {"min": None, "max": None, "assumptions": ["Not estimated: hard constraints conflict, so no stack was chosen."]},
                "warnings": W.items, "assumptions": assumptions, "validation_errors": []}

    if ctx["residency_from_rbi"]:
        assumptions.append("rbi_localisation present with data_residency 'none': payment and personal data are kept in India.")
    if ctx["req"]["infrastructure.data_residency"] == "other":
        W("RESIDENCY_UNSPECIFIED", "critical", "data_residency 'other' does not name a jurisdiction; regions could not be verified. State the country so every data store can be pinned.",
          ["infrastructure.data_residency"])
        assumptions.append("data_residency 'other': no region pinning applied; choose regions in the required jurisdiction.")
    if not ctx["langs"]:
        assumptions.append("team.languages is empty: no language preference applied; mainstream options ranked on other factors.")
    assumptions.append(f"Scale tier '{cx.TIER_NAMES[ctx['tier']]}' from {ctx['users']:,} users and ~{ctx['peak']:,} peak concurrent users "
                       + (f"and scale.peak_rps {req['scale.peak_rps']:,} requests/s (the higher of the two tiers is used)."
                          if ctx["rps_tier"] is not None else "(people, not requests per second; used only for sizing and cost)."))
    if ctx["hiring"]:
        assumptions.append(f"team.hiring_languages {', '.join(ctx['hiring'])}: counted at half the weight of languages the team already writes.")
    if ctx["lock"]:
        assumptions.append(f"infrastructure.lock_in_tolerance '{ctx['lock']}'" + (
            ": provider-specific runtimes and data stores are penalised; portable containers and open engines preferred." if ctx["lock"] == "low"
            else ": no portability penalty applied."))

    # ---- backend
    backend_c = None
    if ctx["needs_backend"]:
        ctx["ui_needs_js"] = sl.ui_needs_js(ctx, SKILL_BAND)
        bs = sl.backend_candidates(ctx, None)
        b_ok, b_out = sl.rank(bs)
        backend_c = b_ok[0]
        team = set(ctx["langs"])
        if team and not set(backend_c.item["langs"]) & team:
            fit = next((c for c in b_ok if set(c.item["langs"]) & team), None)
            if fit and backend_c.score - fit.score <= SKILL_BAND:
                # switching language has costs the scores do not capture (ramp-up, hiring, review quality)
                assumptions.append(f"{fit.item['name']} uses the team's language and is within {SKILL_BAND:g} points of "
                                   f"{backend_c.item['name']} ({fit.score} vs {backend_c.score}); team skill is preferred inside that band.")
                b_ok.remove(fit)
                b_ok.insert(0, fit)
                backend_c = fit
    backend = backend_c.item if backend_c else None

    if backend and ctx["langs"] and not set(backend["langs"]) & set(ctx["langs"]):
        fit = next((c for c in b_ok if set(c.item["langs"]) & set(ctx["langs"])), None)
        W("SKILL_MISMATCH", "warning",
          f"{backend['name']} is not in the team's languages ({', '.join(ctx['langs'])}); it was chosen for the stated priorities and requirements. "
          + (f"The best skill-matched option, {fit.item['name']}, scored {round(backend_c.score - fit.score, 1)} points lower ({why_not(backend_c, fit)}) — "
             "choose it if ramp-up time matters more." if fit else "No option in the knowledge base uses the team's languages.")
          + " Budget training time into the timeline.",
          ["team.languages", "team.experience"])

    # ---- hosting
    hs = sl.hosting_candidates(ctx)
    for c in hs:
        if c.item["kind"] != "serverless" or not backend:
            continue
        if backend["id"] in ("java-spring", "dotnet-aspnet"):
            c.add("runtime", -7, "team.languages",
                  f"{backend['name'].split(' + ')[-1]} is a long-running JVM/.NET server: slow cold starts and per-invocation connection pools on functions")
        elif backend["id"] in ("python-django", "ruby-rails", "php-laravel", "node-nestjs"):
            c.add("runtime", -3, "team.languages",
                  f"{backend['name'].split(' + ')[-1]} is a full-stack framework built to run as a long-lived server, not per-invocation functions")
        if ctx["needs_db"] and ctx["tier"] >= 2:
            c.add("db_conn", -4, "scale.peak_concurrent_users",
                  f"~{ctx['peak']:,} concurrent users would open relational connections per function instance; needs a connection proxy")
    h_ok, h_out = sl.rank(hs)
    if not h_ok:  # should be prevented by hard_conflicts; keep a safe answer
        W("NO_COMPLIANT_HOSTING", "critical", "No hosting option in the knowledge base satisfies the hard constraints.", list(HARD_PATHS))
        return {"scenario_id": sid, "engine_version": ENGINE_VERSION, "status": "infeasible",
                "summary": "No hosting option satisfies the hard constraints.", "architecture_style": "other", "stack": None,
                "estimated_monthly_cost_usd": {"min": None, "max": None, "assumptions": ["Not estimated: no stack recommended."]},
                "warnings": W.items, "assumptions": assumptions, "validation_errors": []}
    host_c = h_ok[0]
    host = host_c.item
    loc = ctx["res_key"]
    if loc:
        region = host["regions"].get(loc) or next(iter(host["regions"].values()))
    elif "gdpr" in ctx["compliance"] and "eu" in host["regions"]:
        region = host["regions"]["eu"]
        loc = "eu"
        assumptions.append(f"gdpr with no data_residency: EU region ({region}) chosen to avoid international transfers.")
    else:
        region = next(iter(host["regions"].values())) if "global" in host["regions"] or "any" in host["regions"] else None
        if region is None and req["infrastructure.data_residency"] == "none":
            assumptions.append("No data_residency given: deploy in the provider region closest to most users (not specified in the input).")
    ctx["res_key"] = loc
    host_extra_paths = [p for p in HARD_PATHS if any(c.excluded and c.excluded[1] == p for c in h_out)]
    if any(c.term("lock_in") for c in h_ok if c is not host_c) or host_c.term("lock_in"):
        host_extra_paths.append("infrastructure.lock_in_tolerance")
    plan = ""
    if host.get("plans"):
        ha_need = req["requirements.availability"] in ("99.95", "99.99")
        plan = host["plan_ha"] if ha_need and ctx["tier"] <= 1 else host["plans"][ctx["tier"]]
        host_c.item = host = dict(host, name=f"{host['name'][:-1]}, {plan})")
    host_name = host["name"] + (f" — {region}" if region else "")
    if not any(e["onprem"] for e in ctx["existing"]):
        host_c.item = host = dict(host, limits=[x for x in host.get("limits", []) if "Hybrid Connection" not in x])
    hosting = component(host_c, h_ok, h_out, host_extra_paths,
                        {"deployment": host["deploy"], "provider": host["provider"], "data_bearing": ctx["needs_backend"],
                         "data_location": loc if ctx["needs_backend"] else None, "region": region}, name=host_name,
                        base_why=envelope_text(ctx, region) if ctx["needs_backend"] else "")

    # ---- backend component
    if backend_c:
        backend_cmp = component(backend_c, b_ok, b_out, [], {"deployment": "self_hosted" if host["kind"] in ("vm", "onprem") else "library",
                                                              "provider": "neutral", "data_bearing": False, "data_location": None})
    else:
        backend_cmp = none_component("backend", "No application server is needed: there are no accounts, payments, uploads or dynamic data; pages are pre-built at deploy time.",
                                     ["project.type", "requirements.auth", "requirements.payments"],
                                     [("Netlify/Cloudflare serverless functions", "nothing to compute at request time for this site"),
                                      ("Node.js + Express", "a server to run and pay for with no feature that needs it")])

    # ---- database
    db_item = None
    if ctx["needs_db"]:
        ds = sl.database_candidates(ctx, host_c, backend)
        d_ok, d_out = sl.rank(ds)
        db_c = d_ok[0]
        db_item = dict(db_c.item, _variant=db_c.variant)
        ha = bool(ha_paths(req))
        db_region = db_c.item.get("regions", {}).get(loc) if db_c.vkey == "any" else region
        vname = db_c.variant + (f" — {db_region}" if db_region and db_c.vkey not in ("self",) else "") + (" (multi-AZ / zone-redundant HA)" if ha and db_c.vkey != "self" else "")
        for c in d_ok + d_out:
            c.item = dict(c.item, name=c.variant or c.item["name"])
        db_cmp = component(db_c, d_ok, d_out, [], {"deployment": "self_hosted" if db_c.vkey == "self" else "managed",
                                                   "provider": host["provider"] if db_c.vkey not in ("any", "self") else (db_c.id if db_c.vkey == "any" else "neutral"),
                                                   "data_bearing": True, "data_location": loc}, name=vname)
        if ha and db_c.vkey != "self":
            hp = ha_paths(req)
            if hp == ["requirements.availability"]:
                db_cmp["justification"] += (f" The {req['requirements.availability']}% target uses a standby in a second zone with automatic failover "
                                            "and point-in-time recovery.")
            else:
                db_cmp["justification"] += (f" {cap(' and '.join(ha_targets(req)))} need a standby in a second zone with automatic failover "
                                            "(restoring from backup takes too long for the RTO; nightly backups lose too much data for the RPO) "
                                            "and point-in-time recovery.")
            db_cmp["driven_by"] = order_paths(db_cmp["driven_by"] + hp)
        rto, rpo = req["requirements.rto_minutes"], req["requirements.rpo_minutes"]
        if rpo is not None and rpo < 5 and db_c.vkey == "self":
            W("RPO_NEEDS_REPLICATION", "warning", f"RPO {rpo} min on a self-hosted database: configure streaming replication to a standby server and "
              "continuous WAL/log archiving; nightly backups alone can lose up to a day of data.", ["requirements.rpo_minutes"])
        if rto is not None and rto < 5:
            W("RTO_BELOW_FAILOVER", "warning", f"RTO {rto} min leaves almost no time for failover, DNS and connection-pool recovery; "
              "rehearse a failover and measure it before promising this, or relax the target.", ["requirements.rto_minutes"])
        if "rbi_localisation" in ctx["compliance"] and db_c.vkey != "self":
            db_cmp["justification"] += f" Automated backups and snapshots stay in {db_region or 'the Indian region'} (no cross-region copies), as RBI localisation requires."
            db_cmp["driven_by"] = order_paths(db_cmp["driven_by"] + ["compliance"])
        if ctx["desc"]["gps_media"] and db_c.id in ("postgresql", "supabase"):
            db_cmp["justification"] += " GPS coordinates are stored as PostGIS geography points, so area and distance queries run in the database."
            db_cmp["driven_by"] = order_paths(db_cmp["driven_by"] + ["project.description"])
            db_cmp["sources"] = db_cmp["sources"] + cite(["postgis"])
        if ctx["data_gb"] >= 1000 and db_c.item.get("family") == "relational":
            db_cmp["justification"] += (f" At ~{ctx['data_gb']:,.0f} GB in year one, partition the largest tables by time and move cold rows or blobs "
                                        "to object storage so backups and index maintenance stay manageable.")
            db_cmp["driven_by"] = order_paths(db_cmp["driven_by"] + ["scale.data_volume_gb_12_months"])
        if ctx["existing_db"] and ctx["existing_db"]["pattern"].get("engine") == db_c.id and ctx["existing_db"]["onprem"] and not ctx["self_host_only"]:
            db_cmp["justification"] += " New application data lives in the cloud database; the on-prem server is integrated, not migrated (see supporting 'other')."
    else:
        db_cmp = none_component("database", "Content lives as Markdown/HTML files in the repository; there is no user data to store.",
                                ["project.type", "requirements.auth"],
                                [("SQLite", "no runtime data to persist"), ("Headless CMS database", "a single author edits files directly")])
    if host["kind"] == "serverless" and backend_c:  # a web framework on Lambda needs an adapter and connection limits
        hosting["justification"] += (f" {backend_c.item['name']} runs unchanged behind AWS Lambda Web Adapter, which forwards "
                                     "API Gateway events to the framework's normal HTTP server.")
        if ctx["needs_db"] and db_c.item.get("family") == "relational" and db_c.vkey != "self":
            hosting["tradeoffs"].append("Each concurrent invocation holds its own database connection: "
                                        + ("keep Django's CONN_MAX_AGE at 0, " if "django" in backend_c.id else "use a pool of one connection, ")
                                        + "cap reserved concurrency and add RDS Proxy (about $0.015 per database vCPU-hour in us-east-1, outside this band) as traffic grows")

    # ---- frontend
    parts, f_terms_c, mob = [], None, None
    fe_alts, fe_paths, fe_trade, fe_src, fe_why = [], ["project.platforms"], [], [], []
    web = None
    if ctx["web"]:
        wc = sl.web_candidates(ctx, backend)
        w_ok, w_out = sl.rank(wc)
        web = w_ok[0]
        wcmp = component(web, w_ok, w_out, [], {})
        parts.append(f"{web.item['name']} (web)")
        fe_alts += wcmp["alternatives"][:2]
        fe_paths += wcmp["driven_by"]
        fe_trade += wcmp["tradeoffs"]
        fe_src += wcmp["sources"]
        fe_why.append(f"Web: {web.item['name']} — {wcmp['justification']}")
        f_terms_c = web
    if ctx["mobile"]:
        mc = sl.mobile_candidates(ctx, web.item if web else None)
        m_ok, m_out = sl.rank(mc)
        mob = m_ok[0]
        mcmp = component(mob, m_ok, m_out, [], {})
        parts.append(f"{mob.item['name']} ({' + '.join(p.capitalize() if p != 'ios' else 'iOS' for p in ctx['mobile'])})")
        fe_alts += mcmp["alternatives"][:2]
        fe_paths += mcmp["driven_by"]
        fe_trade += mcmp["tradeoffs"]
        fe_src += mcmp["sources"]
        fe_why.append(f"Mobile: {mob.item['name']} — {mcmp['justification']}")
        if ctx["desc"]["low_end"] and mob.item["low_end"] <= 3:
            light = next((c for c in m_ok[1:] if c.item["low_end"] >= 5), None)
            fe_why.append(f"Low-end devices: {mob.item['name']} adds a JavaScript runtime, so keep the bundle small, use the default Hermes engine, "
                          "lazy-load screens and profile memory on a 2 GB phone"
                          + (f"; {light.item['name']} ({round(mob.score - light.score, 1)} points behind) is the fallback if memory is tight." if light else "."))
            fe_src.append(cite(["rn-hermes"])[0])
    if ctx["desktop"]:
        if web:
            parts.append("installable PWA (desktop)")
            fe_why.append("Desktop: the web app is installable as a PWA, avoiding a separate desktop codebase.")
            fe_alts.append({"choice": "Tauri desktop app", "why_not": "a second codebase before desktop-specific features are needed"})
        else:
            langs = set(ctx["langs"])
            if "csharp" in langs:
                dname, dwhy, dalts, dsrc = ("WPF on .NET 10", "Desktop for a C# team: WPF is the mature Windows desktop framework on supported .NET 10, with direct access to Windows authentication and devices.",
                                            [("Avalonia UI", "MIT-licensed and cross-platform (Windows/macOS/Linux); choose it if non-Windows desktops matter"),
                                             (".NET MAUI", "also targets mobile, which this project does not need")], ["wpf", "avalonia", "dotnet-maui"])
            elif langs & {"kotlin", "java"}:
                dname, dwhy, dalts, dsrc = ("Compose Multiplatform (desktop)", "Desktop for a Kotlin/Java team: Compose Multiplatform runs on the JVM on Windows, macOS and Linux.",
                                            [("Electron", "would add a JavaScript stack the team does not use")], ["kotlin"])
            elif langs & {"javascript", "typescript"}:
                dname, dwhy, dalts, dsrc = ("Electron", "Desktop for a JavaScript/TypeScript team: Electron runs the same web UI and Node APIs everywhere.",
                                            [("Tauri 2", "smaller and lighter, but native code is written in Rust")], ["electron-tauri"])
            else:
                dname, dwhy, dalts, dsrc = ("Tauri 2", "Desktop: Tauri wraps a web UI in a small native shell with a low memory footprint.",
                                            [("Electron", "much larger memory footprint than Tauri")], ["electron-tauri"])
            parts.append(f"{dname} (desktop)")
            fe_why.append(dwhy)
            fe_paths.append("team.languages")
            fe_src += cite(dsrc)
            fe_alts += [{"choice": c, "why_not": w} for c, w in dalts]
    if parts:
        fe_cmp = {"choice": " + ".join(parts), "justification": " ".join(fe_why), "driven_by": order_paths(fe_paths),
                  "alternatives": fe_alts[:4], "tradeoffs": fe_trade[:4], "deployment": "client", "provider": "neutral",
                  "data_bearing": bool(req["requirements.offline_support"]), "data_location": "device" if req["requirements.offline_support"] else None,
                  "sources": sorted(set(fe_src)),
                  "kb_id": "+".join([web.item["id"]] if web else []) + ("+" if web and mob else "") + (mob.item["id"] if mob else "")
                  + ("+desktop" if ctx["desktop"] else "")}
        if web and not ctx["needs_backend"]:
            fe_cmp["deployment"] = "client"
    else:
        fe_cmp = none_component("frontend", "API-only product: consumers are other systems, so there is no end-user UI to build; an OpenAPI document serves as the developer interface.",
                                ["project.platforms"], [("Developer portal (Docusaurus)", "useful later for external API consumers"),
                                                        ("Admin web UI", "not requested by the platforms list")])

    # ---- supporting services
    supporting = sv.build(ctx, host, backend, db_item, mob.item if mob else None, W)
    second = second_region(ctx, host, db_c if ctx["needs_db"] else None)
    if second:
        supporting.append(second)

    # ---- warnings from contradictions and context
    contradictions(ctx, W, assumptions, host, backend)
    for s in supporting:
        explicit = ctx["req"]["infrastructure.data_residency"] in ("india", "eu", "us") or ctx["residency_from_rbi"]
        if s["layer"] == "payments" and any(w["code"] == "PAYMENT_DATA_LOCATION" for w in W.items):
            continue
        if s["data_bearing"] and explicit and s["data_location"] not in (ctx["res_key"], "device"):
            W("RESIDENCY_UNVERIFIED_SERVICE", "critical", f"{s['choice']} stores data but its location could not be pinned to {ctx['residency'].upper()}.",
              ["infrastructure.data_residency"])

    # ---- cost band
    cost = cost_band(ctx, host, db_item, db_c if ctx["needs_db"] else None, supporting, assumptions)
    if cost["min"] > ctx["budget"]:
        sev = "critical" if (ctx["budget"] == 0 or cost["min"] > 2 * ctx["budget"]) else "warning"
        W("BUDGET_EXCEEDED", sev,
          f"Estimated minimum ${cost['min']}/month exceeds the ${ctx['budget']:g}/month budget. The stack keeps the hard constraints; "
          "to fit the budget, reduce scope (fewer managed services, lower availability) or raise the budget.",
          ["budget.monthly_infra_usd"])
    elif host["kind"] != "onprem" and ctx["budget"] >= 500 and cost["max"] * 8 < ctx["budget"]:
        W("BUDGET_FAR_ABOVE_NEED", "info", f"The ${ctx['budget']:g}/month budget is far above the estimated ${cost['min']}-{cost['max']}/month need. The stack was not inflated to use it; spare budget could buy redundancy, support plans or monitoring.",
          ["budget.monthly_infra_usd"])
    elif cost["max"] > ctx["budget"] > 0:
        # ponytail: drivers read back from the band's own "label ... $lo-hi/month" lines; a structured item list would be cleaner
        items = []
        for line in cost["assumptions"]:
            m = re.findall(r"\$([\d,]+(?:\.\d+)?)-([\d,]+(?:\.\d+)?)/month", line)
            if m:
                items.append((float(m[-1][1].replace(",", "")), line.split(":")[0].split(" — ")[0]))
        top = sorted(items, key=lambda x: (-x[0], x[1]))[:2]
        far = cost["max"] > 2 * ctx["budget"]
        W("BUDGET_AT_RISK", "warning" if far else "info",
          f"Upper estimate ${cost['max']}/month is {cost['max'] / ctx['budget']:.1f}x the ${ctx['budget']:g} budget at peak usage"
          + (f"; the largest upper-bound items are {' and '.join(f'{n} (up to ${v:,.0f})' for v, n in top)}" if top else "")
          + f". Launch near the ${cost['min']} lower bound and set billing alerts at the budget.",
          ["budget.monthly_infra_usd"])

    stack = {"frontend": fe_cmp, "backend": backend_cmp, "database": db_cmp, "hosting": hosting,
             "supporting": [{k: v for k, v in s.items() if not k.startswith("_")} for s in supporting]}
    style = architecture_style(ctx, host, backend, supporting)
    sev = {w["severity"] for w in W.items}
    status = "ok_with_warnings" if sev & {"warning", "critical"} else "ok"
    summary = make_summary(ctx, style, fe_cmp, backend_cmp, db_cmp, host_name, cost, status)
    crit = [w for w in W.items if w["severity"] == "critical"]
    if crit:  # statement p8: a reduced/relaxed stack must say exactly which constraints were relaxed
        for w in crit:
            assumptions.append(f"Relaxed: {', '.join(w['fields'])} — {w['message'].split('. ')[0].rstrip('.')}. "
                               "The stack above does not satisfy this as stated; see the matching critical warning.")
        summary = (f"Relaxed recommendation ({len(crit)} critical conflict{'s' if len(crit) > 1 else ''}: "
                   + ", ".join(w["code"] for w in crit) + ") — " + summary)
    return {"scenario_id": sid, "engine_version": ENGINE_VERSION, "status": status, "summary": summary,
            "architecture_style": style, "stack": stack, "estimated_monthly_cost_usd": cost,
            "warnings": W.items, "assumptions": assumptions, "validation_errors": []}


# Second region inside the same residency area (all are public provider regions; India pairs keep RBI data in India).
SECOND_REGION = {"aws": {"india": "ap-south-2 (Hyderabad)", "eu": "eu-west-1 (Ireland)", "us": "us-east-2 (Ohio)"},
                 "azure": {"india": "South India (Chennai)", "eu": "North Europe (Ireland)", "us": "West US 2 (Washington)"},
                 "gcp": {"india": "asia-south2 (Delhi)", "eu": "europe-west4 (Netherlands)", "us": "us-east1 (South Carolina)"}}
FAILOVER = {"aws": "Route 53 health-checked failover records", "azure": "Azure Front Door priority routing",
            "gcp": "a global external Application Load Balancer with backends in both regions"}


def second_region(ctx, host, db_c):
    """99.99% on hyperscaler managed hosting: warm standby (smaller app footprint + cross-region DB replica) in a second
    region of the same residency area, with health-checked failover. Cost: half to all of the hosting band plus one
    database replica. Self-hosted, on-premise and static hosting get only the warning."""
    p, req, t = host["provider"], ctx["req"], ctx["tier"]
    if req["requirements.availability"] != "99.99" or p not in SECOND_REGION or host["kind"] in ("vm", "onprem", "static") \
            or not ctx["needs_backend"]:
        return None
    loc = ctx["res_key"] if ctx["res_key"] in ("india", "eu", "us") else None
    where = SECOND_REGION[p][loc] if loc else f"a second {p.upper()} region"
    ctx["second_region"] = where
    dbc = sl.db_cost(db_c.item, db_c.vkey) if db_c and db_c.vkey != "self" else [[0, 0]] * 4
    cost = [[round(host["cost"][i][0] / 2) + dbc[i][0], host["cost"][i][1] + dbc[i][1]] for i in range(4)]
    explicit = req["infrastructure.data_residency"] in ("india", "eu", "us") or ctx["residency_from_rbi"]
    return sv.svc("other", f"Second-region warm standby in {where}: cross-region database replica + {FAILOVER[p]}",
                  f"The 99.99% target allows about 4.4 minutes of downtime a month, which one region cannot promise. A scaled-down copy of the "
                  f"application runs in {where}, the database streams to a cross-region read replica that is promoted on failover, and "
                  f"{FAILOVER[p]} move traffic when health checks fail" + (", without leaving the required residency area." if loc else "."),
                  ["requirements.availability"] + (["infrastructure.data_residency"] if explicit else []),
                  [("Active-active in two regions", "multi-region writes need a globally distributed database: far more cost and complexity at this scale"),
                   ("Single region, multiple zones", "designed for about 99.95%; one regional outage breaks a 99.99% target")],
                  ["Replica lag: a failover can lose the last few seconds of writes (RPO in seconds, not zero)",
                   "Failover must be rehearsed regularly; an untested runbook fails when it is needed"],
                  "managed", p, True, cost, ["aws-regional"] if p == "aws" else ["azure-regions"] if p == "azure" else ["gcp-locations"],
                  loc)


def contradictions(ctx, W, assumptions, host, backend):
    req = ctx["req"]
    avail = req["requirements.availability"]
    if avail in ("99.95", "99.99") and (ctx["size"] <= 2 and (ctx["exp"] == "beginner" or not ctx["devops"])):
        # statement 6 example (enterprise availability, solo beginner): critical when servers must be run; static sites need no on-call
        extreme = avail == "99.99" and ctx["size"] == 1 and ctx["exp"] == "beginner" and ctx["needs_backend"]
        W("AVAILABILITY_VS_TEAM", "critical" if extreme else "warning",
          f"A {avail}% availability target (≈{ {'99.95': '22', '99.99': '4.4'}[avail]} min downtime/month) needs on-call and redundancy that a {ctx['size']}-person {ctx['exp']} team without DevOps rarely sustains. Managed multi-zone services were preferred; plan on-call or relax the target."
          + (" Relaxed: the stack is built for the target, but a solo beginner cannot staff 24/7 on-call or failover drills, so treat 99.99% as best effort (about 99.9%) until on-call cover exists." if extreme else ""),
          ["requirements.availability", "team.size", "team.experience", "team.has_devops"])
    if avail == "99.99":
        why = ("A 99.99% target (about 4.4 minutes of downtime a month) is beyond what one region of managed services is designed to deliver, "
               "and service SLAs compose to a lower number. ")
        if ctx.get("second_region"):
            W("AVAILABILITY_SINGLE_REGION", "info", why + f"Addressed: a warm standby in {ctx['second_region']} with a cross-region database "
              "replica and health-checked failover (see supporting). Rehearse the failover; replica lag means a few seconds of writes can be lost.",
              ["requirements.availability"])
        else:
            W("AVAILABILITY_SINGLE_REGION", "warning", why +
              "This stack runs multi-zone in one region; add a second region with tested failover, or plan on 99.95%.",
              ["requirements.availability"])
    n_plat = len([p for p in ctx["platforms"] if p != "api_only"])
    if n_plat >= 3 and ctx["weeks"] <= 6:
        # statement 6 example (short timeline, many platforms): critical at 8 person-weeks or less
        extreme = ctx["size"] * ctx["weeks"] <= 8
        W("TIMELINE_VS_SCOPE", "critical" if extreme else "warning",
          f"{n_plat} client platforms in {ctx['weeks']} weeks with a team of {ctx['size']} is "
          + (f"not achievable. Relaxed: the MVP ships {'web' if ctx['web'] else 'one platform'} first; the stack covers every platform, but the others follow after the MVP." if extreme
             else "aggressive; ship web first and add other platforms after the MVP."),
          ["project.platforms", "timeline.mvp_weeks", "team.size"])
    if "api_only" in ctx["platforms"] and len(ctx["platforms"]) > 1:
        W("API_ONLY_WITH_CLIENTS", "info", "api_only was listed together with client platforms; treated as 'also expose a public API'.", ["project.platforms"])
    if req["requirements.offline_support"] and ctx["platforms"] == ["api_only"]:
        W("OFFLINE_WITHOUT_CLIENT", "warning", "offline_support is true but the only platform is api_only; offline behaviour lives in a client app. Add a web, mobile or desktop client or drop offline_support.",
          ["requirements.offline_support", "project.platforms"])
    if req["requirements.seo_critical"] and req["project.type"] == "internal_tool":
        W("SEO_ON_INTERNAL_TOOL", "warning", "seo_critical is true for an internal tool; pages behind a login are not indexed by search engines. Confirm whether a public site is meant, otherwise set it to false.",
          ["requirements.seo_critical", "project.type"])
    if "hipaa" in req["compliance"] and req["infrastructure.data_residency"] in ("india", "eu", "other"):
        W("HIPAA_RESIDENCY", "warning", f"HIPAA covers US patient data, but data_residency is '{req['infrastructure.data_residency']}'. HIPAA does not require US storage, but it still needs a BAA with the cloud provider; confirm which law governs which data and whether any US patients' data must stay in the US.",
          ["compliance", "infrastructure.data_residency"])
    if req["requirements.seo_critical"] and not ctx["web"]:
        W("SEO_WITHOUT_WEB", "warning", "seo_critical is true but no web platform is listed; search engines cannot index native apps. Add a web landing site.",
          ["requirements.seo_critical", "project.platforms"])
    peak = req["scale.peak_concurrent_users"]
    if peak is not None:
        top = max(req["scale.users_12_months"], req["scale.users_at_launch"])
        if peak > top:
            W("PEAK_EXCEEDS_USERS", "warning", f"peak_concurrent_users ({peak:,}) exceeds the total user count ({top:,}); check the numbers.",
              ["scale.peak_concurrent_users", "scale.users_12_months"])
        elif peak == req["scale.users_at_launch"] and peak > 1000:
            W("PEAK_EQUALS_LAUNCH_USERS", "info", f"Every launch user ({req['scale.users_at_launch']:,}) is assumed online at once at peak; sizing uses this conservative figure.",
              ["scale.peak_concurrent_users", "scale.users_at_launch"])
    if req["scale.users_12_months"] < req["scale.users_at_launch"]:
        W("USERS_SHRINK", "info", "users_12_months is lower than users_at_launch; sizing uses the larger number.", ["scale.users_12_months"])
    big = ctx["users"] >= 500000 or ctx["peak"] >= 20000
    if big and ctx["budget"] < 100 and ctx["needs_backend"]:
        W("SCALE_VS_BUDGET", "critical", f"{ctx['users']:,} users with a ${ctx['budget']:g}/month budget cannot run a dynamic application reliably.",
          ["scale.users_12_months", "budget.monthly_infra_usd"])
    if ctx["exp"] == "beginner" and ctx["size"] == 1 and (req["requirements.payments"] or req["requirements.multi_tenant"] or req["requirements.realtime"]) and ctx["weeks"] <= 4:
        W("SCOPE_VS_TEAM", "warning", "A solo beginner building payments/realtime/multi-tenancy in a few weeks is high risk; managed services were preferred, but consider cutting scope.",
          ["team.experience", "team.size", "timeline.mvp_weeks"])
    if req["requirements.offline_support"] and not ctx["mobile"] and ctx["web"]:
        assumptions.append("offline_support on web: implemented as a PWA with service worker + IndexedDB; capability is narrower than native apps.")
    if req["requirements.offline_support"] and req["requirements.auth"] == "phone_otp":
        W("OFFLINE_LOGIN", "info", "Phone OTP needs signal at first login; sessions are long-lived refresh tokens so the app keeps working offline afterwards.",
          ["requirements.offline_support", "requirements.auth"])
    if ctx["no_internet"] and req["requirements.auth"] == "social":
        W("SOCIAL_LOGIN_NEEDS_NETWORK", "critical", "Social login depends on external identity providers, impossible in an air-gapped network. Relaxed: local accounts in Keycloak.",
          ["requirements.auth", "infrastructure.deployment_model"])
    if ctx["no_internet"] and req["requirements.ml_features"] in ("llm_rag", "inference_api"):
        assumptions.append("air_gapped: models and package mirrors must be imported into the network manually.")
    if ctx["geo"] in ("multi_region", "global") and ctx["needs_backend"]:
        res = ctx["req"]["infrastructure.data_residency"]
        W("GLOBAL_USERS_ONE_REGION", "info",
          f"scale.geo_spread '{ctx['geo']}': the API and database run in one region ({host['name']}), so distant users add roughly 100-250 ms per round trip. "
          "Static assets go through the CDN; " + ("data stays in the residency region, so keep APIs chatty-free and cache public responses at the edge."
                                                 if res in ("india", "eu", "us") else "add a read replica or a second region when distant traffic grows."),
          ["scale.geo_spread"] + (["infrastructure.data_residency"] if res in ("india", "eu", "us") else []))
    lat = req["requirements.p95_latency_ms"]
    if lat is not None and lat <= 100:
        W("LATENCY_TARGET_UNMEASURED", "info", f"p95 {lat} ms is achievable only with users near the {host['name']} region and no cross-region calls; the engine cannot measure it — load-test before launch.",
          ["requirements.p95_latency_ms"])
    # compliance notes (never claims of certification)
    notes = {
        "dpdp": ("DPDP_OBLIGATIONS", "info", "DPDP Act 2023: collect consent with a clear notice, support access/correction/erasure requests, keep a breach runbook (the DPDP Rules 2025 require prompt intimation to the Board and affected people, then a detailed report within 72 hours; the Rules commence in phases, so confirm which apply on your launch date) and delete data when the purpose ends. Hosting in India simplifies transfers; legal review still required.", ["compliance"]),
        "gdpr": ("GDPR_OBLIGATIONS", "info", "GDPR: lawful basis and privacy notice, data-subject rights endpoints, DPAs with every processor (Art. 28), security of processing (Art. 32); transfers outside the EU need an adequacy decision or SCCs.", ["compliance"]),
        "pci_dss": ("PCI_SCOPE", "info", "PCI DSS v4.0.1: card data handled only by the gateway's hosted checkout or embedded payment form keeps scope small and can qualify for SAQ A; with an embedded form the page must also be protected from script attacks (Requirements 6.4.3/11.6.1, or the processor's confirmation), and your acquirer confirms which SAQ applies.", ["compliance"]),
        "rbi_localisation": ("RBI_LOCALISATION", "info", "RBI storage of payment system data: payment system operators and the gateways and vendors in their chain store the end-to-end payment data only in India; data processed abroad must be deleted there and brought back within one business day or 24 hours, whichever is earlier.", ["compliance", "infrastructure.data_residency"]),
        "iso27001": ("ISO27001_CONTROLS", "info", "ISO/IEC 27001:2022 certifies your organisation's ISMS, not a cloud provider's badge: keep asset inventory, access reviews, logging and change management for this system.", ["compliance"]),
        "soc2": ("SOC2_CONTROLS", "info", "SOC 2 requires evidence of your own controls (access, change management, monitoring) over a review period; provider reports only cover their part.", ["compliance"]),
        "hipaa": ("HIPAA_BAA_REQUIRED", "warning", "HIPAA: sign a Business Associate Agreement with the cloud provider and use only HIPAA-eligible services for PHI; SaaS add-ons without a BAA (analytics, chat widgets) must not receive PHI.", ["compliance"]),
    }
    for c in ctx["compliance"]:
        if c in notes:
            W(*notes[c])
    if "hipaa" in ctx["compliance"] and host["provider"] not in ("aws", "azure", "gcp", "on_premise") and host["kind"] not in ("vm", "onprem"):
        W("HIPAA_HOST_NO_BAA", "critical", f"{host['name']} has no BAA in the knowledge base; PHI must not be stored there.", ["compliance"])
    for e in ctx["existing"]:
        life = e["life"]
        if life:
            if life["eol"] <= AS_OF:
                what = {"unmaintained": f"is no longer maintained (repository archived {life['eol']})",
                        "closed": f"is closed to new customers (since {life['eol']})", "deprecated": f"was deprecated on {life['eol']}"}.get(
                    life.get("kind"), f"reached end of support on {life['eol']}")
                W("END_OF_LIFE_SYSTEM", "warning",
                  f"'{e['raw']}' {what} ({life['name']}); keep it behind an isolated interface, do not build new features on it, and plan a migration.",
                  ["infrastructure.existing_systems"])
            elif (date.fromisoformat(life["eol"]) - date.fromisoformat(AS_OF)).days <= 90:
                W("END_OF_LIFE_SOON", "warning",
                  f"'{e['raw']}' ({life['name']}) reaches end of support on {life['eol']}, within 90 days of the knowledge-base date {AS_OF}; "
                  "schedule the upgrade now and avoid building new features on it.", ["infrastructure.existing_systems"])
            elif life.get("mainstream_end") and life["mainstream_end"] <= AS_OF:
                W("EXISTING_SYSTEM_EXTENDED_SUPPORT", "info",
                  f"'{e['raw']}' is in extended (security-only) support until {life['eol']}; supported, but plan the upgrade path.",
                  ["infrastructure.existing_systems"])
        if not e["pattern"] and not life:
            W("EXISTING_SYSTEM_UNRECOGNISED", "info", f"'{e['raw']}' is not in the knowledge base; integration must be designed manually.",
              ["infrastructure.existing_systems"])
    if ctx["existing_idp"] and req["requirements.auth"] not in ("enterprise_sso", "none") and "entra" in ctx["existing_idp"]["pattern"]["name"].lower():
        W("EXISTING_IDP_NOT_USED", "info", "An Entra tenant exists but auth is not enterprise_sso; consider SSO for staff users.",
          ["infrastructure.existing_systems", "requirements.auth"])
    if not ctx["needs_backend"] and ctx["res_key"]:
        assumptions.append("Static public site: content is public and contains no personal data, so a global CDN host does not breach data residency.")


def cost_band(ctx, host, db_item, db_c, supporting, assumptions):
    t = ctx["tier"]
    lo = host["cost"][t][0]
    hi = host["cost"][t][1]
    lines = [f"Hosting {host['name']}: ${host['cost'][t][0]}-{host['cost'][t][1]}/month at the '{cx.TIER_NAMES[t]}' tier."]
    ha = bool(ha_paths(ctx["req"]))
    if db_item and db_c and db_c.vkey != "self":
        dc = sl.db_cost(db_c.item, db_c.vkey)
        dlo, dhi = dc[t]
        if ha:
            dlo, dhi = round(dlo * 1.8), round(dhi * 2)
        lo += dlo
        hi += dhi
        # R11 (Azure Retail Prices API / AWS Price List, India regions, compute only): the small-tier band fits a burstable instance
        size = {"azure": " Sized for a Burstable B2s instance (about $72 compute); a General Purpose D2ds_v5 alone is about $183.",
                "aws": " Sized for a burstable db.t4g.medium (about $61 compute); a db.m6g.large alone is about $165."}.get(db_c.vkey, "") \
            if t == 1 and db_c.item["id"] == "postgresql" else ""
        if t <= 1 and db_c.item["id"] == "sqlserver" and db_c.vkey == "azure":  # review 11 Nov: Azure Retail Prices API, Central India
            size += (f" Assumes serverless auto-pause outside working hours: about {dc[t][0] / 0.574:.0f}-{dc[t][1] / 0.574:.0f} active vCore-hours "
                     "a month at ~$0.57/vCore-hour (Central India rate, 11 Nov 2026); a 0.5-vCore minimum that never pauses is about $210/month "
                     "compute, and DTU Standard S0 (~$17/month) is the fixed-price alternative.")
        if t == 0 and db_c.vkey == "gcp" and db_c.item["id"] in ("postgresql", "mysql"):  # Cloud SQL SLA page, 11 Nov 2026
            size += (" Assumes a shared-core instance (db-f1-micro to db-g1-small: $0.0126-0.042/hour in Mumbai, $0.0105-0.035 in Iowa, about "
                     "$8-31/month, Google pricing page 11 Nov 2026). Google excludes shared-core instances from the Cloud SQL SLA and advises "
                     "against production use; a dedicated-core instance costs more.")
        lines.append(f"Database {db_c.variant}: ${dlo}-{dhi}/month" + (" (HA doubles instances)" if ha else "") + "." + size)
    if ha:
        lo, hi = lo + host["cost"][t][0], hi + host["cost"][t][1]
        lines.append(("Availability ≥99.95%" if ha_paths(ctx["req"])[0] == "requirements.availability" else cap(" and ".join(ha_targets(ctx["req"]))))
                     + ": at least two app instances across zones.")
    for s in supporting:
        clo, chi = s["_cost"][t]
        if chi:
            lo += clo
            hi += chi
            lines.append(f"{s['layer']}: {s['choice'].split(' — ')[0]} ${clo}-{chi}/month." + s.get("_note", ""))
    gb = ctx["data_gb"]
    obj = any(s["layer"] == "storage" and s["deployment"] != "self_hosted" for s in supporting)
    if obj or (db_item and db_c.vkey != "self" and gb > 20):
        # object storage ~$0.02-0.035/GB-month; managed database SSD ~$0.10-0.25 (Cloud SQL SSD $0.17 Iowa / $0.20 Mumbai, rendered 11 Nov 2026)
        r_lo, r_hi = (0.02, 0.035) if obj else (0.10, 0.25)
        slo, shi = round(gb * r_lo, 2), round(gb * r_hi + 1, 2)
        lo += slo
        hi += shi
        lines.append(f"Stored data ~{gb:g} GB after 12 months at ~${r_lo:.2f}-{r_hi:g}/GB-month (year-end volume used as an upper bound, not an average); "
                     + ("bulk files and media are assumed to sit in object storage, while database rows stay small." if obj
                        else "it lives in the managed database's SSD storage, which costs several times object storage."))
    if ctx["req"]["requirements.auth"] == "phone_otp" and not ctx["no_internet"]:
        logins = ctx["users"]
        if any("MSG91" in s["choice"] for s in supporting):
            plo, phi = 0.0024, 0.0045
            txt = "India SMS ~Rs 0.20-0.25 + GST"
        elif any("SNS" in s["choice"] for s in supporting):
            plo, phi = 0.003, 0.006
            txt = "SNS India SMS rate band"
        else:
            plo, phi = 0.05, 0.06
            txt = "Twilio Verify ~$0.05 + SMS"
        olo, ohi = round(logins * 0.3 * plo, 2), round(logins * 1.0 * phi, 2)
        lo += olo
        hi += ohi
        lines.append(f"Phone OTP: {logins:,} users x 0.3-1.0 OTP logins/month at {txt} per SMS = ${olo:,.0f}-{ohi:,.0f}/month (long-lived sessions keep OTPs rare).")
    tp = ctx["req"]["scale.traffic_pattern"]
    if tp in ("spiky", "seasonal") and host.get("scaling") in ("request", "instances"):
        lines.append(f"{'Seasonal' if tp == 'seasonal' else 'Spiky'} traffic: the upper bound is a peak month; with autoscaling, "
                     "quiet months run near the lower bound.")
    elif tp in ("spiky", "seasonal") and host.get("scaling") == "fixed":
        lines.append("Fixed-capacity servers are sized for the peak, so quiet months cost the same as peak months.")
    if ctx["req"]["requirements.payments"]:
        lines.append("Excluded: payment gateway fees (~2% per transaction) are a share of revenue, not infrastructure.")
    if host["kind"] == "onprem":
        lines.append("Excluded: on-premises hardware, power, licences and staff time (capital/operational costs outside a cloud bill).")
    lines.append("Excluded: taxes, domain names, paid support plans and data-egress spikes. Order-of-magnitude band, not a quote.")
    lo, hi = int(lo), int(round(hi + 0.49))
    hi = max(hi, lo)
    if hi > 0 and hi < 5:
        hi = 5
    return {"min": lo, "max": hi, "currency": "USD", "assumptions": lines}




def architecture_style(ctx, host, backend, supporting):
    if not ctx["needs_backend"]:
        return "static"
    if host["kind"] == "serverless":
        return "serverless"
    if any(e["onprem"] for e in ctx["existing"]) and host["kind"] not in ("onprem",):
        return "hybrid"
    if any(s["layer"] == "ml" and s["choice"].startswith("Separate") for s in supporting):
        return "service_oriented"
    caps = sum(bool(ctx["req"][k]) for k in ("requirements.realtime", "requirements.full_text_search", "requirements.file_media_storage",
                                             "requirements.payments", "requirements.multi_tenant")) + (ctx["req"]["requirements.auth"] != "none")
    if ctx["size"] >= 4 or ctx["tier"] >= 2 or caps >= 4:
        return "modular_monolith"
    return "monolith"


def make_summary(ctx, style, fe, be, db, host_name, cost, status):
    style_txt = {"static": "Static site", "monolith": "Single deployable monolith", "modular_monolith": "Modular monolith",
                 "serverless": "Serverless application", "hybrid": "Hybrid cloud + on-premises integration",
                 "service_oriented": "Small set of services", "microservices": "Microservices", "other": "Architecture"}[style]
    parts = [f"{style_txt}: {fe['choice']}"]
    if be["choice"] != "None":
        parts.append(f"on {be['choice']}")
    if db["choice"] != "None":
        parts.append(f"with {db['choice']}")
    s = " ".join(parts) + f", hosted on {host_name}, at an estimated ${cost['min']}-{cost['max']}/month."  # statement 4: one or two sentences
    if status == "ok_with_warnings":
        s += " Review the warnings: some inputs conflict or carry risk."
    return s
