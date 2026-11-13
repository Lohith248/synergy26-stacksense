"""Right-sizing gates for supporting services (D13).

A supporting service that is sized for scale or latency the input does not state is not added; the decision is explained
(an alternative on the replacing component plus a SERVICE_NOT_ADDED info warning), never silent. The numbers below are
planning heuristics, not vendor limits; they are policy and live here, not in the knowledge base (which holds cited product data).
Each predicate returns (needed, fact, add_when, paths): fact quotes the input values behind the verdict and add_when says what
would change it. Gates only touch supporting services and warnings, never a core layer.
"""

THRESHOLDS = {
    "game_p95_ms": 100,           # heuristic: a server-side game loop is justified at or below this p95 latency target
    "warehouse_gb_type": 100,     # heuristic: data_analytics type; at 10x the managed-DB storage price the app DB still serves reports
    "warehouse_gb_inferred": 200,  # heuristic: warehouse inferred only from description words needs stronger evidence
    "warehouse_users": 2000,      # heuristic (A17): below this many users_12_months AND this peak the application database serves the reports
    "warehouse_peak": 50,         # heuristic (A17): concurrent users at which report scans start to compete with application traffic
    "warehouse_gb_any": 500,      # heuristic (A17): from this volume a columnar engine pays off whatever the audience
    "warehouse_gb_airgap": 1000,  # heuristic (A17): an air-gapped site adds no second database engine below this volume (every engine is patched by hand)
}
# A8: project types whose pages are meant for the public. Anything else with sign-in on every route and no SEO need is an
# authenticated app: its static files gain little from an edge cache (planning heuristic, not a vendor fact).
PUBLIC_TYPES = ("content_site", "ecommerce", "marketplace", "social", "gaming", "web_app", "realtime_collab")
TIER_CDN_EXEMPT = 2           # heuristic: from tier 2 (over 50,000 users in 12 months or 2,000 concurrent) a signed-in app keeps its CDN: static-file traffic is large enough to cache
_GEO_WIDE = ("multi_region", "global")


def note(service, fact, add_when):
    """Text of a SERVICE_NOT_ADDED warning."""
    return f"{service} not added: {fact}. Add it when {add_when}."


def game_servers(ctx):
    """Dedicated game servers only for a server-side real-time loop: fast-action genre, or a stated p95 target at or under the threshold.
    A turn-based description wins over a latency number (moves arrive seconds apart)."""
    d, lat, limit = ctx["desc"], ctx["req"]["requirements.p95_latency_ms"], THRESHOLDS["game_p95_ms"]
    paths = ["requirements.p95_latency_ms", "project.description"]
    add_when = (f"the match runs a server-side loop that needs p95 latency of {limit} ms or less "
                "(fast-action play such as a shooter, racing or battle-royale mode)")
    lat_txt = f"requirements.p95_latency_ms is {lat}" if lat is not None else "requirements.p95_latency_ms is not given"
    if d["turn_based"]:
        return False, (f"project.description describes a turn-based game ({lat_txt}); moves arrive seconds apart, so a per-match "
                       "server fleet is not needed"), add_when, paths
    if d["fast_action"]:
        return True, "project.description names a fast-action game", add_when, paths
    if lat is not None and lat <= limit:
        return True, f"requirements.p95_latency_ms is {lat}, at or under the {limit} ms planning heuristic", add_when, paths
    over = f", above the {limit} ms planning heuristic" if lat is not None else ""
    return False, f"{lat_txt}{over}; project.description names no fast-action game", add_when, paths


def warehouse(ctx):
    """Analytics warehouse by data volume. Type path (data_analytics): from the type threshold; description path (analytics
    words + read-heavy): from the stricter inferred threshold. A missing volume uses the engine's 5 GB default."""
    req, gb = ctx["req"], ctx["data_gb"]
    t_type, t_desc = THRESHOLDS["warehouse_gb_type"], THRESHOLDS["warehouse_gb_inferred"]
    paths = ["project.type", "scale.data_volume_gb_12_months"]
    given = req["scale.data_volume_gb_12_months"] is not None
    vol = f"scale.data_volume_gb_12_months is {gb:,.0f}" if given else "scale.data_volume_gb_12_months is not given (5 GB assumed)"
    users, peak = ctx["users"], ctx["peak"]
    small = users < THRESHOLDS["warehouse_users"] and peak < THRESHOLDS["warehouse_peak"] and gb < THRESHOLDS["warehouse_gb_any"]
    if small and (ctx["type"] == "data_analytics" and gb >= t_type or ctx["desc"]["analytics"] and gb >= t_desc):
        # A17: few readers over a modest volume: the application database (read-only role) serves the reports
        return False, (f"project.type is {ctx['type']} with {users:,} users in 12 months, ~{peak:,} concurrent and {vol}, under the "
                       f"{THRESHOLDS['warehouse_users']:,} users, {THRESHOLDS['warehouse_peak']} concurrent and {THRESHOLDS['warehouse_gb_any']:,} GB planning heuristics"), \
            (f"readers reach about {THRESHOLDS['warehouse_users']:,} users or {THRESHOLDS['warehouse_peak']} concurrent, or the data reaches "
             f"{THRESHOLDS['warehouse_gb_any']:,} GB (reports then compete with application traffic on the database)"), paths + ["scale.users_12_months", "scale.peak_concurrent_users"]
    if ctx["no_internet"] and gb < THRESHOLDS["warehouse_gb_airgap"]:
        # A17: an air-gapped site runs and patches every engine itself: no second database engine below 1 TB
        return False, (f"hosting is air-gapped, so every extra database engine is one more thing to install, patch and back up by hand, and {vol}, "
                       f"under the {THRESHOLDS['warehouse_gb_airgap']:,} GB planning heuristic"), \
            f"the data reaches about {THRESHOLDS['warehouse_gb_airgap']:,} GB", paths
    if ctx["type"] == "data_analytics" and gb >= t_type:
        return True, f"project.type is data_analytics and {vol}, at or above the {t_type} GB planning heuristic", "", paths
    if ctx["desc"]["analytics"] and req["scale.workload"] == "read_heavy" and gb >= t_desc:
        return True, f"the description names reports and scale.workload is read_heavy over {gb:,.0f} GB", "", paths + ["scale.workload"]
    return False, f"project.type is {ctx['type']} and {vol}, under the {t_type} GB planning heuristic", \
        f"the data volume reaches about {t_type} GB (reports then compete with application traffic on the database)", paths


def public_pages(ctx):
    """True when the input says public pages exist (SEO, a public project type, or editorial/public-page wording)."""
    return bool(ctx["req"]["requirements.seo_critical"] or ctx["type"] in PUBLIC_TYPES or ctx["desc"]["editorial"] or ctx["desc"]["public_pages"])


def media_delivery(ctx):
    """True when the description says video, audio or large files are delivered to users: a CDN pays off for media whatever the sign-in."""
    return bool(ctx["desc"]["media_delivery"] or ctx["desc"]["video_vod"] or ctx["desc"]["large_downloads"])


def public_facing(ctx):
    """Edge CDN needs a public audience: not 'employees only', not an app that is signed-in on every route (A8), and an internal
    tool only when SEO or multi-region users say otherwise."""
    d, req, typ, geo = ctx["desc"], ctx["req"], ctx["type"], ctx["geo"]
    paths, aud = ["project.type", "project.description"], "a known staff audience"
    if d["internal_only"] and typ == "internal_tool":
        why = "project.type is internal_tool and the description says it is used only by employees"
    elif d["internal_only"]:
        why = "the description says it is used only by employees"
    elif typ == "internal_tool" and not req["requirements.seo_critical"] and geo not in _GEO_WIDE:
        why = ("project.type is internal_tool with requirements.seo_critical false and scale.geo_spread "
               + (f"{geo}" if geo else "not given"))
        paths = ["project.type", "requirements.seo_critical", "scale.geo_spread"]
    elif req["requirements.auth"] != "none" and not public_pages(ctx) and not media_delivery(ctx) and ctx["tier"] < TIER_CDN_EXEMPT and geo not in _GEO_WIDE:
        why = (f"requirements.auth is {req['requirements.auth']}, requirements.seo_critical is false, project.type is {typ}, the description has no public-page "
               f"or media-delivery wording (public pages, listings, catalogue, directory, profiles, blog, video, audio, large files) "
               f"and scale.geo_spread is " + (f"{geo}" if geo else "not given") + ", which this planning heuristic reads as an app that is signed in on every route")
        paths, aud = ["requirements.auth", "requirements.seo_critical", "project.type", "scale.geo_spread"], "a signed-in audience"
    else:
        return True, "", "", []
    # tier 2+ with no scale.geo_spread: the input does not say one region, so the text does not either
    where = "served from one region" if geo or ctx["tier"] < TIER_CDN_EXEMPT else "served from wherever the application runs (scale.geo_spread is not given)"
    return False, why + f", so {aud} is {where}", \
        "public pages, public media or users on several continents appear", paths


def crdt(ctx):
    """CRDT sync only on description evidence of simultaneous editing of one item; the type alone no longer counts, and games never."""
    if ctx["desc"]["collab"] and ctx["type"] != "gaming":
        return True, "the description names simultaneous editing of one shared item", "", ["project.description"]
    return False, (f"project.type is {ctx['type']} but the description names no simultaneous editing of one document, note or canvas; "
                   "live updates are discrete events the server orders"), \
        "two people can edit the same document or canvas at once and edits must merge without conflicts", ["project.type", "project.description"]


def deferrable(supporting, ctx):
    """E3b: lines of the cost band that are sized for scale rather than a hard constraint, as [(name, low $)], at most 3
    (largest first, then name). Text only; nothing is removed."""
    t, req, out = ctx["tier"], ctx["req"], []
    for s in supporting:
        lo, layer, ch = s["_cost"][t][0], s["layer"], s["choice"]
        if lo <= 0:
            continue
        if (layer == "cache" or (layer == "search" and s["deployment"] != "library") or ch.startswith("Analytics warehouse")
                or (layer == "realtime" and ("game servers" in ch or "Hocuspocus" in ch))
                or (layer == "cdn" and not req["requirements.seo_critical"] and ctx["geo"] not in _GEO_WIDE)):
            out.append((ch.split(" (")[0].split(" — ")[0], lo))
    return sorted(out, key=lambda x: (-x[1], x[0]))[:3]
