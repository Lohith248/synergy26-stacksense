"""Project-type rules for domains with their own architecture: games, IoT, analytics and API platforms.

Each rule adds supporting services (never core layers) inside the same constraint envelope as services.py:
hyperscaler-specific products only on that hyperscaler, self-hostable products under on_premise/air_gapped.
Facts are cited from kb/sources.json (research R6/R7).
"""
import re

SECONDS_PER_MONTH = 30 * 24 * 3600
NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakh|million|m)?"
UNIT = {None: 1, "k": 1e3, "thousand": 1e3, "lakh": 1e5, "million": 1e6, "m": 1e6}


def _num(txt, unit):
    return float(txt.replace(",", "")) * UNIT[unit]


def ingest_rate(desc):
    """Device count and reporting interval stated in the description -> (devices, seconds) or None."""
    d = (desc or "").lower()
    m = re.search(NUM + r"\s+(?:\w+\s+){0,2}(?:sensors?|devices?|meters?|trackers?|gateways?|machines?|vehicles?)", d)
    t = re.search(r"every\s+(\d+(?:\.\d+)?)?\s*(seconds?|secs?|s|minutes?|mins?|hours?|hrs?)\b", d)
    if not (m and t):
        return None
    n = _num(m.group(1), m.group(2))
    k = float(t.group(1) or 1)
    sec = k * (60 if t.group(2).startswith("min") else 3600 if t.group(2).startswith("h") else 1)
    return (int(n), sec) if n >= 1 and sec > 0 else None


def build(ctx, host, backend, db, svc, warn, Z, out):
    req, d = ctx["req"], ctx["desc"]
    p, kind = host["provider"], host["kind"]
    selfh = ctx["self_host_only"] or kind in ("vm", "onprem")
    hyper = p in ("aws", "azure", "gcp") and not selfh
    loc = ctx["res_key"]
    region = host["regions"].get(loc) if loc else None
    rtxt = f" in {region}" if region else ""
    typ = ctx["type"]

    # ---------------- games: dedicated game servers for realtime multiplayer
    if typ == "gaming" and req["requirements.realtime"] and ctx["needs_backend"]:
        name, prov, src, dep = {
            "aws": (f"Amazon GameLift Servers{rtxt} (managed dedicated game servers)", "aws", ["gamelift"], "managed"),
            "azure": ("Azure PlayFab Multiplayer Servers (managed dedicated game servers)", "azure", ["playfab-mps"], "managed"),
            "gcp": (f"Agones on Google Kubernetes Engine{rtxt} (open-source dedicated game servers)", "gcp", ["agones"], "managed"),
        }.get(p if hyper else "", ("Agones (open-source dedicated game servers on Kubernetes)", "neutral", ["agones"], "self_hosted"))
        lat = req["requirements.p95_latency_ms"]
        out.append(svc("realtime", name,
                       "Multiplayer matches run on authoritative dedicated game servers (stateful UDP/WebSocket processes allocated per match), "
                       "kept separate from the stateless account/matchmaking API" + (f"; the {lat} ms target needs servers in the players' region" if lat else "") + ".",
                       ["project.type", "requirements.realtime"] + (["requirements.p95_latency_ms"] if lat else []),
                       [("Running matches inside the web API", "game loops are stateful and latency-bound; mixing them with the API breaks scaling and deploys"),
                        ("Peer-to-peer hosting", "cheat-prone and NAT-dependent for competitive play")],
                       ["Fleet sizing and region placement follow player geography", "Game-server builds and the API deploy separately"],
                       dep, prov, False, [[20, 80], [80, 400], [400, 2000], [2000, 10000]], src, loc))

    # ---------------- IoT: device ingestion, time-series storage, rate check
    iot = typ == "iot" or d["iot"]
    if iot and ctx["needs_backend"]:
        rate = ingest_rate(req["project.description"])
        if hyper and p == "aws":
            name, prov, src, dep = f"AWS IoT Core (MQTT){rtxt} → rules → SQS", "aws", ["aws-iot-core"], "managed"
        elif hyper and p == "azure":
            name, prov, src, dep = f"Azure IoT Hub (MQTT){rtxt}", "azure", ["azure-iot-hub"], "managed"
        else:
            name, prov, src, dep = "Eclipse Mosquitto MQTT broker (self-hosted container)", "neutral", ["mosquitto", "gcp-iot-core-retired"], "self_hosted"
        why = ("Devices publish over MQTT (small, persistent, TLS-authenticated connections with per-device credentials); the broker "
               "buffers bursts and hands messages to a worker that batches inserts")
        if p == "gcp" and not selfh:
            why += "; Google Cloud IoT Core was shut down in August 2023, so the broker is self-run"
        paths = ["project.type", "project.description"] if typ == "iot" else ["project.description"]
        cost = Z
        if rate:
            n, sec = rate
            per_month = n * SECONDS_PER_MONTH / sec
            per_sec = n / sec
            why += f". The description implies ~{n:,} devices every {sec:g} s ≈ {per_sec:,.0f} messages/s, ~{per_month / 1e6:,.0f} million/month"
            if prov == "aws":
                lo = round(per_month / 1e6 * 1.0)
                cost = [[lo, round(lo * 1.3)]] * 4  # ~$1 per million messages (AWS's published Europe example)
            warn("IOT_INGEST_RATE", "warning" if per_sec >= 1000 else "info",
                 f"Telemetry rate from the description: ~{per_sec:,.0f} messages/s (~{per_month / 1e6:,.0f} million/month). Size the ingestion "
                 "workers and database writes for this rate; batching several readings per message lowers both broker and write cost.",
                 ["project.description", "scale.workload"])
        out.append(svc("other", "Device ingestion: " + name, why + ".", paths,
                       [("Devices calling the HTTPS API directly", "a request per reading is heavier on battery, bandwidth and servers"),
                        ("Google Cloud IoT Core", "retired on 16 August 2023")],
                       ["Per-device credentials and certificate rotation must be managed", "Offline devices need local buffering"],
                       dep, prov, True, cost, src, loc))
    if (iot or (req["scale.workload"] == "write_heavy" and ctx["data_gb"] >= 500)) and db and db.get("family") == "relational":
        ts = "TimescaleDB hypertables (extension supported on Azure Database for PostgreSQL)" if (p == "azure" and db["id"] == "postgresql" and not selfh) else \
            "native monthly partitions + BRIN index on the timestamp"
        out.append(svc("other", f"Time-series storage: {ts}",
                       f"~{ctx['data_gb']:,.0f} GB of append-only readings: time partitions keep inserts fast, old partitions are dropped or archived "
                       "to object storage, and dashboards read pre-aggregated rollups instead of raw rows.",
                       ["scale.data_volume_gb_12_months", "scale.workload"] + (["project.type"] if typ == "iot" else []),
                       [("One unpartitioned table", "index bloat and slow deletes as data grows"),
                        ("Amazon Timestream for LiveAnalytics", "closed to new customers since June 2025")],
                       ["Retention and rollup jobs must be scheduled"], "library", "neutral", False, Z,
                       ["postgres-partitioning"] + (["azure-pg-timescale"] if "Timescale" in ts else []) + (["timestream-change"] if iot else [])))

    # ---------------- analytics: warehouse + BI
    if typ == "data_analytics" or (d["analytics"] and req["scale.workload"] == "read_heavy" and ctx["data_gb"] >= 200):
        if selfh or not hyper:
            wh, wprov, wsrc, wdep = "ClickHouse (self-hosted columnar warehouse)", "neutral", ["clickhouse"], "self_hosted"
        else:
            wh, wprov, wsrc, wdep = {"gcp": (f"BigQuery{rtxt}", "gcp", ["bigquery-locations"], "managed"),
                                     "aws": (f"Amazon Redshift Serverless{rtxt}", "aws", ["redshift-serverless"], "managed"),
                                     "azure": (f"Microsoft Fabric Warehouse{rtxt}", "azure", ["fabric-overview"], "managed")}[p]
        out.append(svc("other", "Analytics warehouse: " + wh,
                       f"Ad-hoc SQL and reports over ~{ctx['data_gb']:,.0f} GB run on a columnar warehouse, so analysts' heavy scans never slow the "
                       "application database; data is loaded on a schedule (ELT) from the operational store.",
                       ["project.type", "scale.data_volume_gb_12_months", "scale.workload"],
                       [("Reporting straight off the OLTP database", "large scans compete with application traffic"),
                        ("Self-managed Spark cluster", "far more operations than SQL dashboards need")],
                       ["Pricing is per data scanned or per compute-hour; partition and cluster tables"], wdep, wprov, True,
                       [[0, 25], [10, 100], [100, 600], [600, 4000]], wsrc, loc))
        out.append(svc("other", "BI dashboards: Metabase (open-source edition, self-hosted container)",
                       "Analysts build dashboards and scheduled reports with SQL or a query builder, signed in through the same identity provider.",
                       ["project.type", "requirements.auth"],
                       [("Looker Studio", "no-cost and simple, but Google-account based and weaker on governed internal access") if p == "gcp" else
                        ("Apache Superset", "comparable open-source tool; heavier to operate"),
                        ("Custom React dashboards", "every new report becomes a development task")],
                       ["The open-source edition is AGPL: keep it unmodified or comply with the licence"], "self_hosted", "neutral", False, Z,
                       ["metabase-license", "superset"] + (["looker-studio"] if p == "gcp" else [])))

    # ---------------- API platforms: gateway with keys, quotas, rate limits
    if typ == "api_platform" or (ctx["api_only"] and req["requirements.payments"]):
        if hyper:
            gw, gprov, gsrc = {"aws": (f"Amazon API Gateway usage plans + API keys{rtxt}", "aws", ["aws-apigw-usage-plans"]),
                               "azure": (f"Azure API Management (Consumption tier){rtxt}", "azure", ["azure-apim"]),
                               "gcp": (f"Google Cloud API Gateway (API keys, quotas){rtxt}", "gcp", ["gcp-api-gateway"])}[p]
            gdep = "managed"
        else:
            gw, gprov, gsrc, gdep = "Kong Gateway (open-source, self-hosted)", "neutral", ["kong"], "self_hosted"
        out.append(svc("other", "API gateway: " + gw,
                       "A public API needs per-customer API keys, rate limits and quotas enforced before requests reach the service, plus "
                       "usage records for metering and abuse detection.",
                       ["project.type", "project.platforms"] + (["requirements.payments"] if req["requirements.payments"] else []),
                       [("Rate limiting inside the application", "every instance must share counters, and abuse still reaches your servers"),
                        ("Third-party API marketplace", "takes a revenue share and owns the customer relationship")],
                       ["Gateway latency adds a few milliseconds per call"], gdep, gprov, False,
                       [[0, 5], [5, 40], [40, 300], [300, 2000]], gsrc, loc))
