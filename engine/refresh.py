"""Static site with periodically refreshed data (A18): a scheduled publisher, not Markdown in a repository.

A site whose structured fields ask for nothing dynamic can stay static even when its numbers change every few minutes, as long as the
changes come from one place on a schedule: a scheduled publisher fetches the latest figures, validates them, writes versioned static
files and switches one pointer atomically; the CDN caches the files for a short time. The audience then reads files, never a database.
CDN transfer, not compute, is the cost to watch, so it is estimated from users x pages x page weight and compared with the budget.

Every number below is a planning heuristic (policy, not a vendor limit); the reference transfer rate is the one already used for video
egress in recommend.py (Google Cloud CDN list price, source gcp-cdn-pricing).
"""
import math
import re

THRESHOLDS = {
    "pages_per_user": (2, 5),       # heuristic: pages a visitor opens in the busiest month
    "mb_per_page": (0.3, 1.0),      # heuristic: compressed HTML + data file + images per page view
    "usd_per_gb": (0.02, 0.09),     # reference CDN transfer list price range (gcp-cdn-pricing, 12 Nov 2026)
    "ttl_fraction": 0.2,            # heuristic: cache lifetime of the data files as a share of the refresh interval
    "ttl_min_s": 10,                # heuristic: never below this many seconds
    "report_usd": 1,                # heuristic: a transfer estimate below this upper bound is not worth a line
}
# hosts that do not bill transfer for static files (source cf-pages-pricing: requests to static assets are free and unlimited)
UNMETERED_HOSTS = ("cloudflare-pages",)
# unit -> seconds
_UNIT = {"s": 1, "m": 60, "h": 3600}
INTERVAL_RX = r"\b(?:every|each|per)\s+(\d+|a few|few|couple of|two|three|five|ten|fifteen|thirty)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b"
_WORDS = {"a few": 3, "few": 3, "couple of": 2, "two": 2, "three": 3, "five": 5, "ten": 10, "fifteen": 15, "thirty": 30}


def applies(c):
    """A static site (no backend, not a local desktop app) whose text says the data is refreshed on a schedule."""
    return bool(c["desc"]["periodic_refresh"] and not c["needs_backend"] and not c["local_first"])


def interval_seconds(c):
    """Refresh interval named in the description in seconds, or None when it only says 'latest numbers' / 'in batches'."""
    m = re.search(INTERVAL_RX, (c["req"]["project.description"] or "").lower())
    if not m:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _WORDS[m.group(1)]
    return n * _UNIT[m.group(2)[0]]


def interval_text(c):
    s = interval_seconds(c)
    if s is None:
        return "on a schedule"
    if s < 90:
        return f"about every {s} seconds"
    if s < 5400:
        return f"about every {round(s / 60)} minutes"
    return f"about every {round(s / 3600)} hours"


def ttl_seconds(c):
    s = interval_seconds(c)
    if s is None:
        return 60  # heuristic default when no interval is named
    return max(THRESHOLDS["ttl_min_s"], round(s * THRESHOLDS["ttl_fraction"]))


def egress(c):
    """(lo_gb, hi_gb, lo_usd, hi_usd) of CDN transfer in the busiest month: users x pages x page weight x reference rate."""
    users = c["users"]
    p0, p1 = THRESHOLDS["pages_per_user"]
    m0, m1 = THRESHOLDS["mb_per_page"]
    r0, r1 = THRESHOLDS["usd_per_gb"]
    lo, hi = users * p0 * m0 / 1024, users * p1 * m1 / 1024
    return lo, hi, lo * r0, hi * r1


def metered(host):
    return host["id"] not in UNMETERED_HOSTS


def fmt_gb(gb):
    return f"{gb / 1024:,.0f} TB" if gb >= 1024 else f"{gb:,.0f} GB"


def whole_usd(c):
    """(low, high) whole dollars as the cost band prints them: low floored, high ceiled."""
    _, _, ulo, uhi = egress(c)
    return int(ulo), int(math.ceil(uhi))


def egress_text(c):
    """The inputs and assumptions behind the transfer estimate, without the dollar result."""
    lo, hi, ulo, uhi = egress(c)
    p0, p1 = THRESHOLDS["pages_per_user"]
    m0, m1 = THRESHOLDS["mb_per_page"]
    r0, r1 = THRESHOLDS["usd_per_gb"]
    return (f"~{c['users']:,} users x {p0}-{p1} pages x {m0:g}-{m1:g} MB = about {fmt_gb(lo)}-{fmt_gb(hi)} of CDN transfer in the busiest month "
            f"(planning heuristic) at a reference rate of ${r0:g}-{r1:g}/GB (Google Cloud CDN list price, a stand-in for the chosen CDN)")


def publisher_name(host):
    """Product that runs the schedule, by the static host's provider (existing knowledge-base sources)."""
    p = host["provider"]
    return {"aws": ("Amazon EventBridge Scheduler (scheduled publisher)", ["aws-eventbridge-scheduler"]),
            "gcp": ("Google Cloud Scheduler (scheduled publisher)", ["gcp-cloud-scheduler"]),
            "azure": ("Azure Container Apps jobs (scheduled publisher)", ["azure-container-apps-jobs"])}.get(
        p, ("GitHub Actions scheduled workflow (scheduled publisher)", ["github-actions-schedule"]))


def backend_why(c, quote):
    iv = interval_text(c)
    return (f"No always-on application server is needed: the figures change {iv} (\"{quote}\") but from one source, so a scheduled publisher "
            "fetches the latest data, validates it and writes static files that the CDN serves; visitors never reach a server or a database.")


def database_why(c):
    return ("The published figures live as versioned static JSON/HTML snapshot files in object storage behind the CDN (written by the scheduled "
            "publisher), not as Markdown in a repository; the source feed is read by the publisher and nothing is queried at request time")


def publisher_why(c):
    ttl = ttl_seconds(c)
    return (f"Data refreshed {interval_text(c)} is published by a scheduled job instead of a live backend: it fetches the latest figures, rejects a "
            "batch that fails sanity checks (missing rows, totals that go backwards), writes the new snapshot under a new versioned key and then "
            "switches one small 'latest' pointer file in a single step (atomic publish), so a visitor sees the previous complete snapshot or the "
            f"new one, never half of each. The CDN caches the data files for a short time (about {ttl} seconds: a fifth of the refresh interval, "
            "planning heuristic), so bursts of readers hit the cache, not the origin; where the CDN can serve a stale copy on error, enable it so the "
            "last good snapshot keeps being served if the publisher is late.")


def quote(c):
    """The words of the description that say the data is refreshed on a schedule, with a little context (for output text)."""
    from .consistency import snippet
    from .context import DESC_RX
    return snippet(c["req"]["project.description"], DESC_RX["periodic_refresh"])


def database_alts(c):
    return [("Database behind an API", "the figures are written on one schedule from one source, so a request-time database adds cost and failure modes "
             "without making the data fresher; add one when visitors or editors start writing data"),
            ("SQLite", "no runtime data to persist: the publisher keeps the latest snapshot as files")]


def publisher_alts(c):
    return [("Application server with a database", "writes happen on one schedule from one source, so serving every visitor from a live server adds cost and "
                                                    "failure modes without making the data fresher"),
            ("Visitors' browsers polling the source directly", "puts the full audience on the source's servers and exposes its rate limits")]


PUBLISHER_TRADEOFFS = ["Data is only as fresh as the last successful publish: show the 'updated at' time on the page",
                       "The publisher is a single point of failure: alert when no new snapshot has appeared for two intervals",
                       "Check the platform's minimum schedule interval before promising a short refresh"]


def egress_warning(c, budget):
    """(code, severity, message, fields) when the estimated transfer can exceed the budget, else None. Same shape as the other budget warnings."""
    lo, hi, ulo, uhi = egress(c)
    if uhi < THRESHOLDS["report_usd"] or uhi <= budget:
        return None
    return ("CDN_EGRESS_AT_RISK", "warning",
            f"CDN transfer can exceed the ${budget:,.0f}/month budget: {egress_text(c)} is about ${whole_usd(c)[0]:,}-{whole_usd(c)[1]:,}/month. "
            "Launch near the lower figure and set billing alerts. Cut the "
            "page and data-file weight (compress, trim fields, tile or lazy-load the map), keep the cache lifetime of the data files short but not zero, "
            "and compare the CDN's flat-rate or committed-volume plans, or a host that does not bill static requests, before the audience arrives.",
            ["scale.users_12_months", "budget.monthly_infra_usd", "project.description"])
