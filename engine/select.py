"""Hard filtering and explained additive scoring for the four core layers (D10).

Every candidate gets a list of terms (key, points, input path, sentence). The winner is the highest total;
ties break by id. Excluded candidates carry the hard reason. Nothing here reads the clock or the network.
"""
from .kb import TECH

PRIO_LABEL = {"cost": "low running cost", "time_to_market": "fast delivery", "scalability": "scalability",
              "performance": "performance", "maintainability": "maintainability", "security": "security"}
PRIO_KEYS = list(PRIO_LABEL)


class Cand:
    def __init__(self, item):
        self.item = item
        self.id = item["id"]
        self.terms = []  # (key, points, path, text)
        self.excluded = None  # (reason, path): the first hard reason, shown to the user
        self.reasons = []  # every hard reason, used to pick informative alternatives

    def add(self, key, pts, path, text):
        if pts:
            self.terms.append((key, round(pts, 2), path, text))

    def exclude(self, reason, path):
        self.reasons.append((reason, path))
        if self.excluded is None:
            self.excluded = (reason, path)

    @property
    def score(self):
        return round(sum(t[1] for t in self.terms), 2)

    def term(self, key):
        return sum(t[1] for t in self.terms if t[0] == key)


def rank(cands):
    ok = sorted([c for c in cands if not c.excluded], key=lambda c: (-c.score, c.id))
    out = sorted([c for c in cands if c.excluded], key=lambda c: (-c.score, c.id))
    return ok, out


def prio_terms(c, ctx, r):
    for i, k in enumerate(PRIO_KEYS):
        w = ctx["prio"][k]
        rating = r[i]
        if k == "scalability":  # headroom beyond what the expected scale tier needs counts half
            need = ctx["tier"] + 2
            if rating > need:
                rating = need + (rating - need) / 2
        delta = rating - 3
        if delta:
            word = "good" if delta > 0 else "weaker"
            c.add(f"prio_{k}", w * delta * 0.8, f"priorities.{k}",
                  f"{word} {PRIO_LABEL[k]} (priority {w}/5)")


def lang_term(c, ctx, langs, weight, what):
    team = ctx["langs"]
    if not team:
        return
    hit = sorted(set(langs) & set(team))
    hire = sorted(set(langs) & set(ctx["hiring"]))
    if hit:
        c.add("lang", weight * ctx["lf"], "team.languages", f"team already writes {', '.join(hit)} for {what}")
    elif hire:
        c.add("lang", weight * ctx["lf"] * 0.5, "team.hiring_languages", f"the team plans to hire {', '.join(hire)} developers for {what}")
    else:
        c.add("lang", -weight * ctx["lf"], "team.languages",
              f"team lists {', '.join(team)} but this needs {'/'.join(langs[:2])}")


def learn_term(c, ctx, learning, new_lang=False):
    """new_lang: no team language fits any option in this layer, so the language itself is new too."""
    if learning > 2:
        c.add("learning", -(learning - 2) * ctx["xf"] * 1.2 * (2 if new_lang else 1), "team.experience",
              f"learning curve {learning}/5 for {'an' if ctx['exp'][0] in 'aeiou' else 'a'} {ctx['exp']} team"
              + ("; new language for the team: learning curve counts double" if new_lang else ""))


def tier_term(c, ctx, max_tier, what):
    if max_tier < ctx["tier"]:
        c.add("tier", -12, "scale.users_12_months",
              f"{what} is uncomfortable at the expected scale ({ctx['users']:,} users, ~{ctx['peak']:,} concurrent)")


# ---------------------------------------------------------------- hosting
def hosting_candidates(ctx):
    req = ctx["req"]
    cands = []
    for h in TECH["hosting"]:
        c = Cand(h)
        kind = h["kind"]
        # hard: deployment model
        dep = ctx["deploy"]
        if dep == "managed_cloud" and h["deploy"] not in ("saas", "managed"):
            c.exclude("self-managed infrastructure, but deployment_model is managed_cloud", "infrastructure.deployment_model")
        if dep == "self_hosted_cloud_vm" and kind != "vm":
            c.exclude("not a self-hosted cloud VM, which deployment_model requires", "infrastructure.deployment_model")
        if ctx["self_host_only"] and kind != "onprem":
            c.exclude(f"a cloud/SaaS service, but deployment_model is {dep} (only self-hostable components allowed)",
                      "infrastructure.deployment_model")
        if kind == "onprem" and not ctx["self_host_only"]:
            c.exclude("on-premises hardware was not requested", "infrastructure.deployment_model")
        # hard: explicit cloud preference
        if ctx["cloud"] in ("aws", "azure", "gcp") and h["provider"] != ctx["cloud"]:
            c.exclude(f"runs on {h['provider']}, but cloud_preference is {ctx['cloud']}", "infrastructure.cloud_preference")
        # hard: backend capability
        if ctx["needs_backend"] and kind in ("static", "web_ssr"):
            c.exclude("serves static/edge pages only; this project needs an application backend", "project.type")
        # hard: residency (any host that stores or processes personal data must sit in the region)
        if ctx["res_key"] and ctx["needs_backend"] and kind != "onprem" and ctx["res_key"] not in h["regions"]:
            c.exclude(f"no {h['name'].split(' (')[0]} region in {ctx['res_label']} (R15 region lists, 12 Nov 2026) for application data" if ctx["country"]
                      else f"no {ctx['residency'].upper()} region for application data", "infrastructure.data_residency")
        # hard: commercial terms
        if not h["commercial_ok"] and ctx["type"] not in ("content_site", "other"):
            c.exclude("free plan terms do not allow commercial products", "project.type")
        # soft
        prio_terms(c, ctx, h["r"])
        ops = h["ops"]
        if ops == 1 and not ctx["devops"]:
            c.add("ops", 1.5, "team.has_devops", "fully managed runtime (patching, TLS, scaling handled) for a team without a DevOps person")
        if ops > 1:
            if ctx["devops"]:
                c.add("ops", -(ops - 1) * 0.6, "team.has_devops", f"operations burden {ops}/5 (team has DevOps skills)")
            else:
                c.add("ops", -(ops - 1) * 2.2, "team.has_devops", f"operations burden {ops}/5 with no dedicated DevOps person")
        learn_term(c, ctx, h["learning"])
        tier_term(c, ctx, h["max_tier"], h["name"])
        lo = h["cost"][ctx["tier"]][0]
        if lo > ctx["budget"]:
            over = (lo - ctx["budget"]) / max(ctx["budget"], 10)
            c.add("budget", -(4 + min(8, over * 4)), "budget.monthly_infra_usd",
                  f"entry cost about ${lo}/month exceeds the ${ctx['budget']:g} budget")
        elif ctx["budget"] == 0 and lo == 0:
            c.add("budget", 3, "budget.monthly_infra_usd", "fits a zero budget on its free plan")
        elif lo > 0:  # inside budget, a cheaper entry point still matters in proportion to the cost priority
            c.add("budget_share", -min(3, 3 * lo / max(ctx["budget"], 20)) * ctx["prio"]["cost"] / 3, "budget.monthly_infra_usd",
                  f"entry cost about ${lo}/month uses {round(100 * lo / max(ctx['budget'], 1))}% of the budget")
        if ctx["weeks"] <= 6 and h["r"][1] >= 4:
            c.add("timeline", 1.5, "timeline.mvp_weeks", f"quick to set up for a {ctx['weeks']}-week MVP")
        avail = req["requirements.availability"]
        if avail in ("99.95", "99.99") and (h["sla"] is None or "single" in str(h["sla"])):
            c.add("availability", -6, "requirements.availability", f"no multi-zone SLA for a {avail}% target")
        elif avail in ("99.95", "99.99") and kind not in ("static", "onprem"):
            c.add("availability", 1, "requirements.availability", f"runs across availability zones for the {avail}% target")
        regulated = [x for x in ctx["compliance"] if x in ("pci_dss", "hipaa", "rbi_localisation", "iso27001", "soc2")]
        if regulated and h.get("host_os") == "customer":
            c.add("host_os", -2, "compliance",
                  f"the EC2/VM operating system stays in your patching and hardening scope for {', '.join(regulated)}")
        if req["requirements.realtime"] and kind == "serverless":
            c.add("realtime", -10, "requirements.realtime",
                  "functions cannot hold long-lived WebSocket connections; realtime would need a separate connection gateway")
        tp, sc = req["scale.traffic_pattern"], h.get("scaling")
        if tp in ("spiky", "seasonal") and sc:
            burst = "seasonal peaks" if tp == "seasonal" else "traffic bursts"
            if sc == "request":
                # persistent WebSocket connections keep instances busy, so pay-per-request elasticity helps less
                c.add("traffic", 1.0 if req["requirements.realtime"] else 2.5, "scale.traffic_pattern",
                      f"scales out with requests for {burst} and back down (to zero) afterwards, so idle periods cost little")
            elif sc == "fixed":
                c.add("traffic", -2, "scale.traffic_pattern", f"fixed capacity must be sized and paid for at the level of the {burst}")
        if ctx["lock"] == "low":
            if h.get("lock_in") == "high":
                c.add("lock_in", -4, "infrastructure.lock_in_tolerance", "code is written against a provider-specific runtime, costly to move")
            elif kind in ("containers", "vm", "onprem"):
                c.add("lock_in", 1, "infrastructure.lock_in_tolerance", "standard containers move to another cloud or on-prem unchanged")
        if req["requirements.realtime"] and h.get("ws_timeout") and ctx["type"] in ("realtime_collab", "gaming"):
            # ponytail: only long shared sessions pay this; short-lived realtime clients (feeds, notifications, mobile
            # sync) reconnect anyway, and the "traffic" term above already prices connections that keep instances busy
            c.add("realtime", -1.5, "project.type", "WebSocket connections end at the request timeout, so long shared sessions must reconnect")
        lat = req["requirements.p95_latency_ms"]
        if lat is not None and lat <= 150 and kind == "serverless":
            c.add("latency", -3, "requirements.p95_latency_ms", f"cold starts threaten a {lat} ms p95")
        if ctx["existing_db"] and ctx["existing_db"]["onprem"] and h["id"] == "azure-app-service":
            c.add("existing", 3, "infrastructure.existing_systems",
                  "Hybrid Connections reach the existing on-prem database without opening inbound ports")
        if ctx["existing_idp"] and h["provider"] == "azure" and "entra" in ctx["existing_idp"]["pattern"]["name"].lower():
            c.add("existing_idp", 1.5, "infrastructure.existing_systems", "built-in Entra ID sign-in (Easy Auth)")
        if kind == "static" and not ctx["needs_backend"]:
            c.add("fit", 4, "project.type", "a static site needs nothing more than a CDN host")
        if kind == "onprem" and h["id"] == "onprem-k3s" and not (ctx["tier"] >= 2 and ctx["devops"]):
            c.add("fit", -6, "team.size", "Kubernetes is unjustified for this team size/scale")
        cands.append(c)
    return cands


# ---------------------------------------------------------------- backend
def ui_needs_js(ctx, skill_band):
    """Lookahead for the one_new_language bonus. Without the bonus, take the backend that would be chosen (team language
    preferred within skill_band, as in recommend). The web UI needs JavaScript/TypeScript unless that backend is in the
    team's language, renders templates, and its templates are the best web option."""
    team = set(ctx["langs"])
    if not (ctx["web"] and team):
        return True
    ctx["ui_needs_js"] = False
    ok, _ = rank(backend_candidates(ctx, None))
    top = ok[0]
    fit = next((c for c in ok if set(c.item["langs"]) & team), None)
    if fit and top.score - fit.score <= skill_band:
        top = fit
    if not (top.item.get("templates") and set(top.item["langs"]) & team):
        return True
    w_ok, _ = rank(web_candidates(ctx, top.item))
    return w_ok[0].item["kind"] != "templates"


def backend_candidates(ctx, host):
    req = ctx["req"]
    cands = []
    known = set(ctx["langs"]) | set(ctx["hiring"])
    new_lang = not any(set(b["langs"]) & known for b in TECH["backend"])  # empty, or client-only languages (swift, dart)
    for b in TECH["backend"]:
        c = Cand(b)
        prio_terms(c, ctx, b["r"])
        lang_term(c, ctx, b["langs"], 7, "the API")
        learn_term(c, ctx, b["learning"], new_lang)
        tier_term(c, ctx, b["max_tier"], b["name"])
        if b.get("fullstack"):  # the UI app is the backend: only for small web-only apps
            if not ctx["web"] or ctx["mobile"]:
                c.exclude("route handlers inside a web app; mobile or API-only clients need a separate API", "project.platforms")
            elif req["requirements.realtime"]:
                c.exclude("no long-lived WebSocket connections on serverless hosts", "requirements.realtime")
            elif ctx["size"] > 4:
                c.exclude("one shared app for UI and API suits a team of up to 4", "team.size")
            else:
                c.add("one_app", 3, "team.size", f"UI and API in one Next.js app: one codebase and one deploy for a team of {ctx['size']}")
        if req["requirements.realtime"]:
            c.add("realtime", (b["realtime"] - 3) * 1.5, "requirements.realtime",
                  "native WebSocket support" if b["realtime"] >= 4 else "realtime needs extra libraries")
        if req["requirements.ml_features"] != "none":
            c.add("ml", (b["ml"] - 3) * 0.8, "requirements.ml_features",
                  "same language as the ML ecosystem" if b["ml"] >= 4 else "ML code would live in a separate Python service")
        heavy = [x for x in ctx["compliance"] if x in ("pci_dss", "rbi_localisation", "hipaa", "soc2", "iso27001")]
        if heavy or req["requirements.auth"] == "enterprise_sso":
            c.add("enterprise", (b["enterprise"] - 3) * 1.2,
                  "compliance" if heavy else "requirements.auth",
                  "mature security/audit tooling" if b["enterprise"] >= 4 else "fewer enterprise security integrations")
        if ctx["existing_db"] and ctx["existing_db"]["pattern"].get("engine") == "sqlserver":
            c.add("existing", (b["sqlserver"] - 3) * 2, "infrastructure.existing_systems",
                  "first-class SQL Server driver/ORM" if b["sqlserver"] >= 4 else "weaker SQL Server tooling")
        if (ctx["ui_needs_js"] and ctx["web"] and not set(ctx["langs"]) & {"javascript", "typescript"} and set(b["langs"]) & {"javascript", "typescript"}
                and not set(ctx["hiring"]) & {"javascript", "typescript"}):  # hiring already earns lang credit
            c.add("one_new_language", 7 * ctx["lf"], "team.languages",  # cancels the language-mismatch penalty above: JS must be learned for the web UI regardless
                  "the web UI needs JavaScript/TypeScript anyway, so the team learns one new language instead of two" if ctx["langs"] else
                  "no team language given: the web UI needs JavaScript/TypeScript anyway, so the backend should not add a second new language")
        js_team = set(ctx["langs"]) & {"javascript", "typescript"}
        if js_team and (ctx["web"] or ctx["mobile"]) and set(b["langs"]) & {"javascript", "typescript"}:
            c.add("one_language", 2, "team.languages", "one language (TypeScript/JavaScript) across clients and server")
        if ctx["existing_idp"] and b["id"] == "dotnet-aspnet":
            c.add("existing_idp", 2, "infrastructure.existing_systems", "Microsoft.Identity.Web for Entra ID")
        if ctx["desc"]["ledger"] or req["project.type"] == "fintech":
            c.add("ledger", (b["enterprise"] - 3) * 1.0, "project.type",
                  "strong transactional frameworks for money movement" if b["enterprise"] >= 4 else "less transaction tooling")
        cands.append(c)
    return cands


# ---------------------------------------------------------------- database
def db_variant(db, host):
    p, kind = host["provider"], host["kind"]
    if kind in ("vm", "onprem"):
        return db["variants"].get("self"), "self"
    if p in db["variants"]:
        return db["variants"][p], p
    if "any" in db["variants"] and p not in ("on_premise",):
        return db["variants"]["any"], "any"
    return None, None


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


def db_cost(item, vkey):
    """Monthly [low, high] per tier for a database offering; self-hosted runs on the app servers."""
    if vkey == "self":
        return [[0, 0]] * 4
    if "cost" in item:
        return item["cost"]
    if item["id"] == "mongodb":
        return DB_COST["atlas"]
    if item["id"] == "sqlserver":
        return DB_COST["azure_sql" if vkey == "azure" else "sqlserver"]
    return DB_COST.get(vkey, DB_COST["managed"])


def database_candidates(ctx, host, backend):
    req = ctx["req"]
    cands = []
    for d in TECH["database"]:
        c = Cand(d)
        name, vkey = db_variant(d, host.item)
        c.variant, c.vkey = name, vkey
        if d["id"] == "sqlite" and (host.item["kind"] not in ("vm", "onprem") or ctx["tier"] > 0):
            c.exclude("single-file database: only for one self-hosted server at tiny scale", "scale.users_12_months")
        if name is None:
            c.exclude(f"no managed offering on {host.item['name']}",
                      "infrastructure.cloud_preference" if ctx["cloud"] in ("aws", "azure", "gcp") else "stack.hosting")
        if vkey == "any" and ctx["cloud"] in ("aws", "azure", "gcp") and d["id"] != "mongodb":
            c.exclude(f"a separate vendor outside the explicit cloud_preference {ctx['cloud']}", "infrastructure.cloud_preference")
        if vkey == "any" and ctx["res_key"] and "regions" in d and ctx["res_key"] not in d["regions"]:
            c.exclude(f"no {d['name'].split(' (')[0]} region in {ctx['res_label']} (R15 region lists, 12 Nov 2026)" if ctx["country"]
                      else f"no {ctx['res_key'].upper()} region", "infrastructure.data_residency")
        if name is not None:
            lo = db_cost(d, vkey)[ctx["tier"]][0]
            left = max(0, ctx["budget"] - host.item["cost"][ctx["tier"]][0])
            if lo > left:
                over = (lo - left) / max(left, 10)
                c.add("budget", -(3 + min(6, over * 3)), "budget.monthly_infra_usd",
                      f"entry cost about ${lo}/month leaves no room in the ${ctx['budget']:g} budget after hosting")
            elif lo == 0 and ctx["budget"] < 25:
                c.add("budget", 2, "budget.monthly_infra_usd", f"has a free plan that fits the ${ctx['budget']:g} budget")
        prio_terms(c, ctx, d["r"])
        learn_term(c, ctx, d["learning"])
        tier_term(c, ctx, d["max_tier"], d["name"])
        if req["requirements.payments"] or ctx["desc"]["ledger"] or req["project.type"] in ("fintech", "ecommerce", "marketplace"):
            what = {"fintech": "money movement and ledger postings", "marketplace": "bookings and payments",
                    "ecommerce": "orders, stock and payments"}.get(req["project.type"], "payments and the records they change")
            if ctx["desc"]["ledger"]:
                what = "money movement and ledger postings"
            c.add("acid", (d["acid"] - 3) * 2.5, "requirements.payments",
                  f"strict ACID transactions for {what}" if d["acid"] >= 4 else f"weaker multi-record transactions for {what}")
        if req["scale.workload"] == "write_heavy":
            c.add("write", (d["write"] - 3) * 1.5, "scale.workload", "handles write-heavy load" if d["write"] >= 4 else "write throughput limits")
        if req["requirements.multi_tenant"]:
            c.add("rls", 3 if d["rls"] else -2, "requirements.multi_tenant",
                  "row-level security enforces tenant isolation in the database" if d["rls"] else "tenant isolation only in app code")
        if req["requirements.full_text_search"] and ctx["tier"] <= 1:
            c.add("fts", 1.5 if d["fts"] else -1, "requirements.full_text_search", "built-in full-text search avoids a separate search service")
        ed = ctx["existing_db"]
        if ed and ed["pattern"].get("engine") == d["id"]:
            c.add("existing", 9, "infrastructure.existing_systems", f"matches the existing {ed['raw']} the team already runs")
        if ctx["lock"] == "low" and d.get("lock_in") == "high":
            c.add("lock_in", -5, "infrastructure.lock_in_tolerance", "proprietary data model and API; leaving means rewriting data access")
        if "sql" in ctx["langs"] and d["family"] == "relational":
            c.add("sqlskill", 1.5, "team.languages", "team knows SQL")
        if backend["id"] == "dotnet-aspnet" and d["id"] == "sqlserver":
            c.add("synergy", 2.5, "team.languages", "EF Core + SQL Server is the default .NET pairing")
        if ctx["res_key"] and vkey == "any":
            c.add("vendor", -2, "infrastructure.data_residency", "adds a separate vendor whose region must also be pinned")
        cands.append(c)
    return cands


# ---------------------------------------------------------------- frontend
def web_candidates(ctx, backend):
    req = ctx["req"]
    cands = []
    for f in TECH["frontend_web"]:
        if f["kind"] == "templates":  # the backend framework renders the pages itself, in the backend's language
            if not (backend and backend.get("templates")):
                continue
            f = dict(f, langs=backend["langs"], name=backend["templates"])
        c = Cand(f)
        if backend and backend.get("fullstack") and f["id"] != "nextjs":
            c.exclude("the backend runs inside the Next.js app, so the UI is that same app", "stack.backend")
        if f["kind"] == "templates" and ctx["mobile"]:
            c.add("api_anyway", -3, "project.platforms", "the mobile app needs a JSON API anyway, so server-rendered pages add a second presentation layer")
        prio_terms(c, ctx, f["r"])
        lang_term(c, ctx, f["langs"], 5, "the UI")
        learn_term(c, ctx, f["learning"])
        if req["requirements.seo_critical"]:
            c.add("seo", (f["seo"] - 3) * 3, "requirements.seo_critical",
                  "server-rendered/static HTML that search engines index" if f["seo"] >= 4 else "client-rendered pages index poorly")
        if not ctx["needs_backend"]:
            c.add("static", 5 if f["kind"] == "static" else -3, "project.type",
                  "pre-built static pages, no server needed" if f["kind"] == "static" else "needs a server runtime for a site that does not")
        else:
            c.add("app", (f["app"] - 3) * 3.5, "project.type",
                  "rich interactive app screens" if f["app"] >= 4 else "suited to content pages, not app screens")
            if f["kind"] == "static":
                c.add("static", -2, "project.type", "a static-site generator for a dynamic application")
        if ctx["desc"]["markdown"] and f["kind"] == "static":
            c.add("markdown", 2, "project.description", "renders the owner's Markdown files directly")
        if backend and set(backend["langs"]) & set(f["langs"]) & set(ctx["langs"]):
            c.add("shared_lang", 1.5, "team.languages", "same language as the backend")
        if ctx["mobile"] and f["id"] in ("nextjs", "react-vite") and set(ctx["langs"]) & {"javascript", "typescript"}:
            c.add("react_mobile", 1.5, "project.platforms", "same React component model as a React Native mobile app")
        if ctx["desc"]["internal_only"] and f["kind"] == "spa":
            c.add("internal", 1, "project.description", "internal app behind login needs no SEO")
        cands.append(c)
    return cands


def mobile_candidates(ctx, web_choice):
    req = ctx["req"]
    targets = set(ctx["mobile"])
    cands = []
    for m in TECH["frontend_mobile"]:
        c = Cand(m)
        if not targets <= set(m["targets"]):
            c.exclude(f"does not target {', '.join(sorted(targets - set(m['targets'])))}", "project.platforms")
        game = m.get("kind") == "game"
        if game and ctx["type"] != "gaming":
            c.exclude("a game engine, and this is not a game", "project.type")
        if ctx["type"] == "gaming":
            c.add("game", 8 if game else -4, "project.type",
                  "game engine: rendering, physics, input, audio and asset pipeline built in" if game else "an app UI toolkit, not a game engine")
        prio_terms(c, ctx, m["r"])
        lang_term(c, ctx, m["langs"], 6, "the mobile app")
        learn_term(c, ctx, m["learning"])
        if ctx["desc"]["low_end"]:
            c.add("low_end", (m["low_end"] - 3) * 3, "project.description",
                  "light on memory for low-end phones" if m["low_end"] >= 4 else "heavier runtime on low-end phones")
        if req["requirements.offline_support"]:
            c.add("offline", (m["offline"] - 3) * 2, "requirements.offline_support",
                  "mature on-device storage and background sync" if m["offline"] >= 4 else "offline storage is weaker")
        if web_choice and set(web_choice["langs"]) & set(m["langs"]) & {"javascript", "typescript"}:
            c.add("shared_lang", 2, "project.platforms", "shares TypeScript code and skills with the web app")
        if len(targets) == 2 and len(m["targets"]) == 2:
            c.add("one_codebase", 2, "project.platforms", "one codebase for Android and iOS")
        if len(targets) == 1:
            only = next(iter(targets))
            if len(m["targets"]) == 1:
                c.add("native_single", 3, "project.platforms",
                      f"{'iOS' if only == 'ios' else only.capitalize()} is the only mobile target, so the native toolkit needs no cross-platform layer")
            elif not set(m["langs"]) & {"javascript", "typescript"}:
                c.add("native_single", -2, "project.platforms",
                      f"its multiplatform layer adds build complexity that a {only}-only app does not use")
        cands.append(c)
    return cands
