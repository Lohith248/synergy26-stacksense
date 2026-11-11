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
        cost, note, trade = Z, "", ["Per-device credentials and certificate rotation must be managed", "Offline devices need local buffering"]
        if dep == "self_hosted" and selfh:
            why += "; it runs on the same servers as the application, with TCP 8883 (MQTT over TLS) opened to the devices"
        elif dep == "self_hosted":
            # ponytail: rough VM band (e2-small-class VM + 10 GB disk, scaled by tier); vendor price not rendered on 11 Nov 2026
            name = f"Eclipse Mosquitto MQTT broker on {'a Compute Engine e2-small VM' + rtxt if p == 'gcp' else 'a small always-on VM'} (TCP 8883, persistent disk)"
            why += (f"; {host['name']} serves HTTP requests, so the broker, which holds long-lived device TCP connections, "
                    "runs on its own VM in the same region and forwards messages to the app over the private network")
            cost = [[8, 30], [25, 60], [60, 200], [200, 800]]
            note = " Rough VM estimate (small VM + disk); vendor price not verified on 11 Nov 2026."
            trade = trade + ["Open-source Mosquitto is a single node: patch and monitor the VM; a clustered broker is needed for failover"]
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
                       trade, dep, prov, True, cost, src, loc))
        out[-1]["_note"] = note
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

    # ---------------- video: transcoding pipeline for uploaded video, managed WebRTC for live calls
    if d["video_vod"] and ctx["needs_backend"]:
        if hyper and p == "aws":
            tr, tprov, tsrc, tdep = f"Video transcoding: AWS Elemental MediaConvert{rtxt}", "aws", ["aws-mediaconvert"], "managed"
        elif hyper and p == "gcp":
            tr, tprov, tsrc, tdep = f"Video transcoding: Google Cloud Transcoder API{rtxt}", "gcp", ["gcp-transcoder"], "managed"
        else:
            tr, tprov, tsrc, tdep = "Video transcoding: FFmpeg worker containers fed from the job queue", "neutral", ["ffmpeg"], "self_hosted"
        out.append(svc("other", tr,
                       "Uploaded video is re-encoded into several bitrates (adaptive streaming) by background workers, not by the web API, so playback works on slow phones "
                       "and uploads never block requests.",
                       ["project.description", "requirements.file_media_storage"],
                       [("Serving the original upload", "huge files, no adaptive bitrate, buffering on mobile networks"),
                        ("Third-party video API", "simplest to run, but video would be stored outside your chosen region/provider")],
                       ["Billed per output minute (managed) or per worker-hour (FFmpeg); budget it per hour of video uploaded"],
                       tdep, tprov, True, [[10, 60], [60, 400], [400, 3000], [3000, 20000]], tsrc, loc))
    if d["video_call"] and ctx["needs_backend"]:
        if selfh or not hyper:
            vc, vsrc, vdep, vprov = "Video calls: LiveKit (open-source WebRTC server, self-hosted)", ["livekit"], "self_hosted", "neutral"
        else:
            vc, vsrc, vdep, vprov = "Video calls: managed WebRTC video API (for example Daily); recordings off by default", ["daily-docs"], "managed", "neutral"
        out.append(svc("realtime", vc,
                       "Live video runs through a WebRTC media server (SFU), never through the application server: the API only issues short-lived room tokens.",
                       ["project.description"],
                       [("Relaying video through the application API", "media streams need a purpose-built server; the API would saturate"),
                        ("Peer-to-peer WebRTC only", "fails behind many mobile and corporate NATs and does not scale past a few participants")],
                       ["Bandwidth is the main cost: priced per participant-minute (managed) or per egress GB (self-hosted)"],
                       vdep, vprov, False, [[0, 25], [25, 150], [150, 1000], [1000, 6000]], vsrc))
        if "hipaa" in ctx["compliance"]:
            warn("VIDEO_PHI", "warning", "Video consultations carry PHI: the video provider must sign a BAA, and recordings must stay off unless stored in your HIPAA-eligible storage.",
                 ["compliance", "project.description"])

    # ---------------- scheduled work (reminders, nightly jobs)
    if d["scheduler"] and ctx["needs_backend"]:
        if selfh or not hyper:
            sc, ssrc, sdep, sprov = "Scheduler: cron / Celery beat or Graphile Worker schedule inside the app container", ["postgres-versioning"], "self_hosted", "neutral"
        else:
            sc, sprov, ssrc, sdep = {"aws": (f"Scheduler: Amazon EventBridge Scheduler{rtxt}", "aws", ["aws-eventbridge-scheduler"], "managed"),
                                     "azure": (f"Scheduler: Azure Container Apps jobs or Functions timer trigger{rtxt}", "azure", ["azure-container-apps-jobs"], "managed"),
                                     "gcp": (f"Scheduler: Google Cloud Scheduler{rtxt}", "gcp", ["gcp-cloud-scheduler"], "managed")}[p]
        out.append(svc("other", sc,
                       "Reminders and other timed work run from a scheduler that calls the app on a schedule, so no always-on process or hand-rolled timer loop is needed.",
                       ["project.description"],
                       [("In-process timers", "lost on every restart or deploy; duplicated across instances")],
                       ["Make scheduled jobs idempotent: a schedule can fire twice"], sdep, sprov, False, [[0, 1], [0, 3], [1, 10], [5, 30]], ssrc))

    # ---------------- web3: on-chain access and payment caution
    if d["web3"] and ctx["needs_backend"] and ctx["self_host_only"]:
        warn("BLOCKCHAIN_NEEDS_NETWORK", "critical",
             "Public-chain reads and writes need external peers or an RPC service. Relaxed: live on-chain access is omitted under this restricted deployment; use imported snapshots or a separately approved connected gateway.",
             ["project.description", "infrastructure.deployment_model"])
    elif d["web3"] and ctx["needs_backend"]:
        warn("WEB3_CAUTION", "warning", "Crypto/NFT products: card processors may restrict or refuse some crypto businesses, so check the processor's restricted-business list before building the checkout; "
             "wallets and private keys stay with the user (never custody them by default); regulation (consumer, tax, anti-money-laundering) varies by country and is not assessed here.",
             ["project.description", "requirements.payments"])
        out.append(svc("other", "On-chain access: managed blockchain RPC provider plus an event indexer (for example The Graph or a self-run indexer)",
                       "Wallet connections, ownership checks and mint/transfer events are read from the chain through an RPC provider; an indexer copies events into the database so listings and search stay fast.",
                       ["project.description"],
                       [("Running your own full node", "large disk, constant sync and upgrades for a small team"),
                        ("Querying the chain on every page load", "slow and rate-limited by RPC providers")],
                       ["RPC providers meter requests; chain reorganisations require the indexer to handle rollbacks"],
                       "managed", "neutral", False, [[0, 50], [50, 250], [250, 1500], [1500, 8000]], ["the-graph"]))

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
