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
}
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
    if ctx["type"] == "data_analytics" and gb >= t_type:
        return True, f"project.type is data_analytics and {vol}, at or above the {t_type} GB planning heuristic", "", paths
    if ctx["desc"]["analytics"] and req["scale.workload"] == "read_heavy" and gb >= t_desc:
        return True, f"the description names reports and scale.workload is read_heavy over {gb:,.0f} GB", "", paths + ["scale.workload"]
    return False, f"project.type is {ctx['type']} and {vol}, under the {t_type} GB planning heuristic", \
        f"the data volume reaches about {t_type} GB (reports then compete with application traffic on the database)", paths


def public_facing(ctx):
    """Edge CDN needs a public audience: not 'employees only', and an internal tool only when SEO or multi-region users say otherwise."""
    d, req, typ, geo = ctx["desc"], ctx["req"], ctx["type"], ctx["geo"]
    paths = ["project.type", "project.description"]
    if d["internal_only"] and typ == "internal_tool":
        why = "project.type is internal_tool and the description says it is used only by employees"
    elif d["internal_only"]:
        why = "the description says it is used only by employees"
    elif typ == "internal_tool" and not req["requirements.seo_critical"] and geo not in _GEO_WIDE:
        why = ("project.type is internal_tool with requirements.seo_critical false and scale.geo_spread "
               + (f"{geo}" if geo else "not given"))
        paths = ["project.type", "requirements.seo_critical", "scale.geo_spread"]
    else:
        return True, "", "", []
    return False, why + ", so a known staff audience is served from one region", \
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
