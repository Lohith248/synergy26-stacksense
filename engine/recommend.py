"""Orchestration: validated input -> Section 4 document. Deterministic; no clock, randomness or network."""
from . import ENGINE_VERSION
from . import context as cx
from . import select as sl
from . import services as sv
from .kb import AS_OF, TECH, cite

FIELD_ORDER = [f[0] for f in __import__("engine.validate", fromlist=["FIELDS"]).FIELDS]
HARD_PATHS = ("infrastructure.cloud_preference", "infrastructure.deployment_model", "infrastructure.data_residency")


class Warnings:
    def __init__(self):
        self.items = []

    def __call__(self, code, sev, msg, fields):
        if not any(w["code"] == code for w in self.items):
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
    pos = sorted([t for t in cand.terms if t[1] > 0], key=lambda t: (-t[1], t[0]))
    reasons = [t[3] for t in pos[:4]]
    why = base_why + ("; ".join(reasons[:1]).capitalize() + ("; " + "; ".join(reasons[1:]) if len(reasons) > 1 else "") + "." if reasons else "")
    alts = []
    for a in ranked_ok[1:3]:
        alts.append({"choice": a.item["name"], "why_not": why_not(cand, a)})
    for a in ranked_out[:2]:
        if len(alts) >= 3:
            break
        alts.append({"choice": a.item["name"], "why_not": f"Excluded: {a.excluded[0]} ({a.excluded[1]})."})
    driven = [t[2] for t in cand.terms if abs(t[1]) >= 1] + list(extra_paths)
    out = {"choice": name or item["name"], "justification": why.strip() or "Best overall fit for the stated inputs.",
           "driven_by": order_paths(driven) or ["project.type"], "alternatives": alts,
           "tradeoffs": list(item.get("limits", []))}
    out.update(extras)
    out["sources"] = cite(item.get("src", []))
    return out


def why_not(win, alt):
    keys = sorted({t[0] for t in win.terms} | {t[0] for t in alt.terms})
    gaps = []
    for k in keys:
        g = win.term(k) - alt.term(k)
        if g > 0.5:
            gaps.append((g, k))
    gaps.sort(key=lambda x: (-x[0], x[1]))
    texts = []
    for g, k in gaps[:2]:
        neg = [t for t in alt.terms if t[0] == k and t[1] < 0]
        pos = [t for t in win.terms if t[0] == k and t[1] > 0]
        if neg:
            texts.append(f"{neg[0][3]} ({neg[0][2]})")
        elif pos:
            texts.append(f"less {pos[0][3].split(' (')[0]} than {win.item['name']} ({pos[0][2]})")
    total = round(win.score - alt.score, 1)
    if not texts:
        return f"Close runner-up (score {alt.score} vs {win.score}); a stable id-based tie-break keeps the result deterministic."
    return "; ".join(texts).capitalize() + f". Overall {total} points behind."


def none_component(layer, why, paths, alts):
    return {"choice": "None", "justification": why, "driven_by": order_paths(paths),
            "alternatives": [{"choice": c, "why_not": w} for c, w in alts], "tradeoffs": [],
            "deployment": "none", "provider": None, "data_bearing": False, "data_location": None, "sources": []}


def recommend(req, assumptions, sid):
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
    if ctx["peak_assumed"]:
        pass
    if ctx["req"]["infrastructure.data_residency"] == "other":
        W("RESIDENCY_UNSPECIFIED", "warning", "data_residency 'other' does not name a jurisdiction; regions could not be verified. State the country so every data store can be pinned.",
          ["infrastructure.data_residency"])
        assumptions.append("data_residency 'other': no region pinning applied; choose regions in the required jurisdiction.")
    if not ctx["langs"]:
        assumptions.append("team.languages is empty: no language preference applied; mainstream options ranked on other factors.")
    assumptions.append(f"Scale tier '{cx.TIER_NAMES[ctx['tier']]}' from {ctx['users']:,} users and ~{ctx['peak']:,} peak concurrent users "
                       "(people, not requests per second; used only for sizing and cost).")

    # ---- backend
    backend_c = None
    if ctx["needs_backend"]:
        bs = sl.backend_candidates(ctx, None)
        b_ok, b_out = sl.rank(bs)
        backend_c = b_ok[0]
    backend = backend_c.item if backend_c else None

    # ---- hosting
    hs = sl.hosting_candidates(ctx)
    if backend and backend["id"] in ("java-spring", "dotnet-aspnet"):
        for c in hs:
            if c.item["kind"] == "serverless":
                c.add("runtime", -3, "team.languages", f"{backend['name']} cold starts on functions")
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
        if region is None:
            assumptions.append("No data_residency given: deploy in the provider region closest to most users (not specified in the input).")
    ctx["res_key"] = loc
    host_extra_paths = [p for p in HARD_PATHS if any(c.excluded and c.excluded[1] == p for c in h_out)]
    host_name = host["name"] + (f" — {region}" if region else "")
    hosting = component(host_c, h_ok, h_out, host_extra_paths,
                        {"deployment": host["deploy"], "provider": host["provider"], "data_bearing": ctx["needs_backend"],
                         "data_location": loc if ctx["needs_backend"] else None, "region": region}, name=host_name)

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
        ha = req["requirements.availability"] in ("99.95", "99.99")
        vname = db_c.variant + (f" — {region}" if region and db_c.vkey not in ("self",) else "") + (" (multi-AZ / zone-redundant HA)" if ha and db_c.vkey != "self" else "")
        for c in d_ok + d_out:
            c.item = dict(c.item, name=c.variant or c.item["name"])
        db_cmp = component(db_c, d_ok, d_out, [], {"deployment": "self_hosted" if db_c.vkey == "self" else "managed",
                                                   "provider": host["provider"] if db_c.vkey not in ("any", "self") else ("mongodb" if db_c.vkey == "any" else "neutral"),
                                                   "data_bearing": True, "data_location": loc}, name=vname)
        if ctx["existing_db"] and ctx["existing_db"]["pattern"].get("engine") == db_c.id:
            db_cmp["justification"] = (f"Same engine as the existing '{ctx['existing_db']['raw']}', so skills, tooling and queries carry over; "
                                       + db_cmp["justification"])
    else:
        db_cmp = none_component("database", "Content lives as Markdown/HTML files in the repository; there is no user data to store.",
                                ["project.type", "requirements.auth"],
                                [("SQLite", "no runtime data to persist"), ("Headless CMS database", "a single author edits files directly")])

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
    if ctx["desktop"]:
        if web:
            parts.append("installable PWA (desktop)")
            fe_why.append("Desktop: the web app is installable as a PWA, avoiding a separate desktop codebase.")
            fe_alts.append({"choice": "Tauri desktop app", "why_not": "a second codebase before desktop-specific features are needed"})
        else:
            parts.append("Tauri (desktop)")
            fe_why.append("Desktop: Tauri wraps a web UI in a small native shell.")
            fe_alts.append({"choice": "Electron", "why_not": "much larger memory footprint than Tauri"})
    if parts:
        fe_cmp = {"choice": " + ".join(parts), "justification": " ".join(fe_why), "driven_by": order_paths(fe_paths),
                  "alternatives": fe_alts[:4], "tradeoffs": fe_trade[:4], "deployment": "client", "provider": "neutral",
                  "data_bearing": bool(req["requirements.offline_support"]), "data_location": "device" if req["requirements.offline_support"] else None,
                  "sources": sorted(set(fe_src))}
        if web and not ctx["needs_backend"]:
            fe_cmp["deployment"] = "client"
    else:
        fe_cmp = none_component("frontend", "API-only product: consumers are other systems, so there is no end-user UI to build; an OpenAPI document serves as the developer interface.",
                                ["project.platforms"], [("Developer portal (Docusaurus)", "useful later for external API consumers"),
                                                        ("Admin web UI", "not requested by the platforms list")])

    # ---- supporting services
    supporting = sv.build(ctx, host, backend, db_item, mob.item if mob else None, W)

    # ---- warnings from contradictions and context
    contradictions(ctx, W, assumptions, host, backend)
    for s in supporting:
        explicit = ctx["req"]["infrastructure.data_residency"] in ("india", "eu", "us") or ctx["residency_from_rbi"]
        if s["data_bearing"] and explicit and s["data_location"] not in (ctx["res_key"], "device"):
            W("RESIDENCY_UNVERIFIED_SERVICE", "warning", f"{s['choice']} stores data but its location could not be pinned to {ctx['residency'].upper()}.",
              ["infrastructure.data_residency"])

    # ---- cost band
    cost = cost_band(ctx, host, db_item, db_c if ctx["needs_db"] else None, supporting, assumptions)
    if cost["min"] > ctx["budget"]:
        sev = "critical" if (ctx["budget"] == 0 or cost["min"] > 2 * ctx["budget"]) else "warning"
        W("BUDGET_EXCEEDED", sev,
          f"Estimated minimum ${cost['min']}/month exceeds the ${ctx['budget']:g}/month budget. The stack keeps the hard constraints; "
          "to fit the budget, reduce scope (fewer managed services, lower availability) or raise the budget.",
          ["budget.monthly_infra_usd"])
    elif cost["max"] > ctx["budget"] > 0:
        W("BUDGET_AT_RISK", "info", f"Upper estimate ${cost['max']}/month can exceed the ${ctx['budget']:g} budget at peak usage.",
          ["budget.monthly_infra_usd"])

    stack = {"frontend": fe_cmp, "backend": backend_cmp, "database": db_cmp, "hosting": hosting,
             "supporting": [{k: v for k, v in s.items() if not k.startswith("_")} for s in supporting]}
    style = architecture_style(ctx, host, backend, supporting)
    sev = {w["severity"] for w in W.items}
    status = "ok_with_warnings" if sev & {"warning", "critical"} else "ok"
    summary = make_summary(ctx, style, fe_cmp, backend_cmp, db_cmp, host_name, cost, status)
    return {"scenario_id": sid, "engine_version": ENGINE_VERSION, "status": status, "summary": summary,
            "architecture_style": style, "stack": stack, "estimated_monthly_cost_usd": cost,
            "warnings": W.items, "assumptions": assumptions, "validation_errors": []}


def contradictions(ctx, W, assumptions, host, backend):
    req = ctx["req"]
    avail = req["requirements.availability"]
    if avail in ("99.95", "99.99") and (ctx["size"] <= 2 and (ctx["exp"] == "beginner" or not ctx["devops"])):
        W("AVAILABILITY_VS_TEAM", "warning",
          f"A {avail}% availability target (≈{ {'99.95': '22', '99.99': '4.4'}[avail]} min downtime/month) needs on-call and redundancy that a {ctx['size']}-person {ctx['exp']} team without DevOps rarely sustains. Managed multi-zone services were preferred; plan on-call or relax the target.",
          ["requirements.availability", "team.size", "team.experience", "team.has_devops"])
    n_plat = len([p for p in ctx["platforms"] if p != "api_only"])
    if n_plat >= 3 and ctx["weeks"] <= 6:
        W("TIMELINE_VS_SCOPE", "warning",
          f"{n_plat} client platforms in {ctx['weeks']} weeks with a team of {ctx['size']} is aggressive; ship web first and add other platforms after the MVP.",
          ["project.platforms", "timeline.mvp_weeks", "team.size"])
    if "api_only" in ctx["platforms"] and len(ctx["platforms"]) > 1:
        W("API_ONLY_WITH_CLIENTS", "info", "api_only was listed together with client platforms; treated as 'also expose a public API'.", ["project.platforms"])
    if req["requirements.seo_critical"] and not ctx["web"]:
        W("SEO_WITHOUT_WEB", "warning", "seo_critical is true but no web platform is listed; search engines cannot index native apps. Add a web landing site.",
          ["requirements.seo_critical", "project.platforms"])
    peak = req["scale.peak_concurrent_users"]
    if peak is not None:
        top = max(req["scale.users_12_months"], req["scale.users_at_launch"])
        if peak > top:
            W("PEAK_EXCEEDS_USERS", "warning", f"peak_concurrent_users ({peak:,}) exceeds the total user count ({top:,}); check the numbers.",
              ["scale.peak_concurrent_users", "scale.users_12_months"])
        elif peak >= req["scale.users_at_launch"] > 0 and peak > 1000:
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
    lat = req["requirements.p95_latency_ms"]
    if lat is not None and lat <= 100:
        W("LATENCY_TARGET_UNMEASURED", "info", f"p95 {lat} ms is achievable only with users near the {host['name']} region and no cross-region calls; the engine cannot measure it — load-test before launch.",
          ["requirements.p95_latency_ms"])
    # compliance notes (never claims of certification)
    notes = {
        "dpdp": ("DPDP_OBLIGATIONS", "info", "DPDP Act 2023: collect consent with a clear notice, support access/correction/erasure requests, keep breach-notification runbooks (72 h to the Board under the 2025 Rules) and delete data when the purpose ends. Hosting in India simplifies transfers; legal review still required.", ["compliance"]),
        "gdpr": ("GDPR_OBLIGATIONS", "info", "GDPR: lawful basis and privacy notice, data-subject rights endpoints, DPAs with every processor (Art. 28), security of processing (Art. 32); transfers outside the EU need an adequacy decision or SCCs.", ["compliance"]),
        "pci_dss": ("PCI_SCOPE", "info", "PCI DSS v4.0.1: card data handled only by the gateway's hosted fields/checkout keeps scope small (SAQ A when fully outsourced); still secure the pages that embed checkout.", ["compliance"]),
        "rbi_localisation": ("RBI_LOCALISATION", "info", "RBI payment-data localisation: all payment data, backups and logs stay on systems in India; anything processed abroad must be deleted there and brought back within 24 hours.", ["compliance", "infrastructure.data_residency"]),
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
                W("END_OF_LIFE_SYSTEM", "warning",
                  f"'{e['raw']}' reached end of support on {life['eol']} ({life['name']}); integrate only through an isolated interface and plan an upgrade.",
                  ["infrastructure.existing_systems"])
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
    ha = ctx["req"]["requirements.availability"] in ("99.95", "99.99")
    if db_item and db_c and db_c.vkey != "self":
        dc = DB_COST.get(db_c.vkey, DB_COST["managed"]) if db_c.id != "sqlserver" else DB_COST["azure_sql" if db_c.vkey == "azure" else "sqlserver"]
        if db_c.id == "mongodb":
            dc = DB_COST["atlas"]
        dlo, dhi = dc[t]
        if ha:
            dlo, dhi = round(dlo * 1.8), round(dhi * 2)
        lo += dlo
        hi += dhi
        lines.append(f"Database {db_c.variant}: ${dlo}-{dhi}/month" + (" (HA doubles instances)" if ha else "") + ".")
    if ha:
        lo, hi = lo + host["cost"][t][0], hi + host["cost"][t][1]
        lines.append("Availability ≥99.95%: at least two app instances across zones.")
    for s in supporting:
        clo, chi = s["_cost"][t]
        if chi:
            lo += clo
            hi += chi
            lines.append(f"{s['layer']}: {s['choice'].split(' — ')[0]} ${clo}-{chi}/month.")
    gb = ctx["data_gb"]
    if any(s["layer"] == "storage" and s["deployment"] != "self_hosted" for s in supporting) or (db_item and gb > 20):
        slo, shi = round(gb * 0.02, 2), round(gb * 0.035 + 1, 2)
        lo += slo
        hi += shi
        lines.append(f"Stored data ~{gb:g} GB after 12 months at ~$0.02-0.035/GB-month (year-end volume used as an upper bound, not an average).")
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
        lo += round(logins * 0.5 * plo, 2)
        hi += round(logins * 1.5 * phi, 2)
        lines.append(f"Phone OTP: {logins:,} users x 0.5-1.5 OTP logins/month at {txt} per SMS.")
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


DB_COST = {
    "managed": [[15, 35], [30, 120], [150, 700], [700, 4000]],
    "aws": [[15, 35], [30, 120], [150, 700], [700, 4000]],
    "azure": [[13, 30], [30, 120], [150, 700], [700, 4000]],
    "gcp": [[10, 30], [30, 120], [150, 700], [700, 4000]],
    "vercel": [[0, 25], [25, 60], [100, 400], [400, 2000]],
    "render": [[6, 20], [20, 100], [100, 500], [500, 2000]],
    "railway": [[5, 20], [20, 100], [100, 500], [500, 2000]],
    "atlas": [[0, 60], [57, 150], [200, 800], [800, 4000]],
    "azure_sql": [[5, 15], [15, 80], [150, 700], [700, 4000]],
    "sqlserver": [[30, 80], [80, 250], [250, 1200], [1200, 6000]],
}


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
    s = " ".join(parts) + f", hosted on {host_name}. Estimated ${cost['min']}-{cost['max']}/month."
    if status == "ok_with_warnings":
        s += " Review the warnings: some inputs conflict or carry risk."
    return s
