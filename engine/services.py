"""Supporting services derived from requirements, hard constraints and description rules (FR4).

Each entry is a complete component object plus extra fields (deployment, provider, data_bearing, data_location,
cost per tier, sources). Choices respect the same envelope as the core layers.
"""
import re
from . import domains
from .kb import cite

Z = [[0, 0], [0, 0], [0, 0], [0, 0]]
# cloudflare.com/plans rendered 11 Nov 2026
CF_FREE = ("Cloudflare positions the Free plan for projects that are not business-critical and gives it no uptime SLA (the 100% SLA starts at Business); move to a paid plan when the site becomes business-critical")


def svc(layer, choice, why, driven, alts, trade, deploy, provider, data_bearing, cost, src, location=None):
    return {"layer": layer, "choice": choice, "justification": why, "driven_by": driven,
            "alternatives": [{"choice": a, "why_not": w} for a, w in alts], "tradeoffs": trade,
            "deployment": deploy, "provider": provider, "data_bearing": data_bearing,
            "data_location": location if data_bearing else None, "_cost": cost, "sources": cite(src)}


def build(ctx, host, backend, db, mobile, warn):
    """host/backend/db/mobile: chosen KB items (db may be None). warn(code, sev, msg, fields)."""
    req = ctx["req"]
    p, kind = host["provider"], host["kind"]
    hyper = p in ("aws", "azure", "gcp")
    selfh = kind in ("vm", "onprem")
    loc = ctx["res_key"]
    region = host["regions"].get(loc) if loc else None
    rtxt = f" in {region}" if region else ""
    out = []
    d = ctx["desc"]
    res_path = ["infrastructure.data_residency"] if loc else []

    # ---------------- auth
    auth = req["requirements.auth"]
    if auth != "none":
        dp = ["requirements.auth"]
        if auth == "social" and ctx["no_internet"]:
            out.append(svc("auth", "Keycloak 26 (local accounts; social login deferred)",
                           "An air-gapped network cannot reach social providers: use local accounts in Keycloak as the explicitly relaxed fallback.",
                           dp + ["infrastructure.deployment_model"],
                           [("Google/GitHub/Microsoft OAuth", "requires an external identity provider across the air gap")],
                           ["Users need a separate local account until the network restriction changes"],
                           "self_hosted", "neutral", True, Z, ["keycloak"], loc))
        elif auth == "enterprise_sso":
            idp = ctx["existing_idp"]
            if idp and "entra" in idp["pattern"]["name"].lower() and not ctx["no_internet"]:
                if ctx["self_host_only"]:
                    warn("EXTERNAL_IDENTITY_PROVIDER", "critical",
                         "The company's existing identity provider (Microsoft Entra ID) is a cloud service; reusing it is kept as the one external dependency of an otherwise on-premises stack. Use Keycloak federated to on-prem AD if no cloud dependency is acceptable.",
                         ["infrastructure.existing_systems", "infrastructure.deployment_model"])
                if p in ("aws", "gcp"):
                    warn("EXISTING_CROSS_CLOUD_SERVICE", "info",
                         f"The existing Microsoft Entra ID tenant (and Microsoft 365 if used) stays in Microsoft's cloud while the application runs on {p.upper()}: this reuses an existing system rather than adding a second cloud. Only sign-in tokens and notifications cross over; application data stays on {p.upper()}.",
                         ["infrastructure.existing_systems", "infrastructure.cloud_preference"])
                out.append(svc("auth", "Microsoft Entra ID (existing tenant) via OpenID Connect",
                               f"enterprise_sso is required and '{idp['raw']}' already exists: reuse it so employees keep one login; "
                               "app roles/groups in the token drive approvals and admin rights.",
                               dp + ["infrastructure.existing_systems"],
                               [("Keycloak (self-hosted)", "duplicates an identity provider the company already operates"),
                                ("Amazon Cognito federation", "extra hop and a second directory to administer")],
                               ["Depends on the customer's Entra tenant admins for app registration and consent"],
                               "saas", "azure", False, Z, ["entra-sso"]))
            elif (req["requirements.multi_tenant"] or ctx["type"] == "saas_b2b") and not selfh:
                name, prov, src = {"aws": (f"Amazon Cognito user pool{rtxt} with per-customer SAML/OIDC federation", "aws", ["cognito-federation"]),
                                   "gcp": ("Google Cloud Identity Platform multi-tenancy (per-tenant SAML/OIDC providers)", "gcp", ["gcp-identity-multitenancy"])
                                   }.get(p, ("Keycloak 26 identity brokering (one SAML/OIDC provider per customer org)", "neutral", ["keycloak-brokering"]))
                out.append(svc("auth", name,
                               "B2B SaaS with enterprise_sso: each customer organisation signs in through its own IdP (Okta, Entra ID, Google Workspace…), "
                               "so the app federates one SAML/OIDC connection per tenant and maps the IdP to the tenant id; no passwords are stored.",
                               dp + ["requirements.multi_tenant", "project.type"],
                               [("A single corporate identity tenant", "fits one company's staff, not many customer organisations with their own IdPs"),
                                ("WorkOS / Auth0 (SaaS)", "fastest per-customer SSO setup, but per-connection pricing and another processor")],
                               ["Each customer connection needs metadata exchange and claim mapping", "Just-in-time provisioning or SCIM must be decided"],
                               "managed" if prov in ("aws", "gcp") else "self_hosted", prov, True,
                               [[0, 0], [0, 20], [20, 150], [150, 800]], src, loc))
            elif selfh:
                out.append(svc("auth", "Keycloak 26 (self-hosted, OIDC/SAML)",
                               "enterprise_sso on self-hosted infrastructure: Keycloak federates with the corporate directory (LDAP/AD or SAML) and runs on the same servers.",
                               dp + ["infrastructure.deployment_model"],
                               [("Microsoft Entra ID", "a cloud service, not allowed under this deployment model")],
                               ["You operate and upgrade Keycloak"], "self_hosted", "neutral", True, Z, ["keycloak"], loc))
            else:
                name = {"aws": "Amazon Cognito (SAML/OIDC federation to the corporate IdP)",
                        "azure": "Microsoft Entra ID (OIDC)",
                        "gcp": "Google Cloud Identity Platform (SAML/OIDC)"}.get(p, "Keycloak 26 (container next to the API)")
                out.append(svc("auth", name, "enterprise_sso is required: federate with the customer's identity provider instead of storing passwords.",
                               dp + ["infrastructure.cloud_preference"],
                               [("Keycloak (self-hosted)", "more to operate than the provider's managed identity service")],
                               ["Each customer IdP must be configured (metadata, claims mapping)"],
                               "managed" if hyper else "self_hosted", p if hyper else "neutral", True,
                               [[0, 0], [0, 20], [20, 150], [150, 800]], ["keycloak", "entra-sso"], loc))
        elif auth == "phone_otp":
            if ctx["no_internet"]:
                out.append(svc("auth", "Keycloak 26 with an on-premises SMS gateway (reduced scope)",
                               "phone_otp needs an SMS carrier link that an air-gapped network does not have; the stack keeps OTP only if a dedicated telecom gateway is installed on-site.",
                               dp + ["infrastructure.deployment_model"],
                               [("MSG91 / Twilio Verify", "internet SaaS, forbidden in an air-gapped deployment")],
                               ["Relaxed: OTP availability depends on an on-site gateway"], "self_hosted", "neutral", True, Z, ["keycloak"], loc))
                warn("PHONE_OTP_NEEDS_NETWORK", "critical",
                     "Phone OTP needs a telecom/SMS link, which contradicts an air-gapped deployment. Relaxed: OTP only via an on-site SMS gateway; otherwise use username/password + hardware tokens.",
                     ["requirements.auth", "infrastructure.deployment_model"])
            elif ctx["self_host_only"]:
                out.append(svc("auth", "Keycloak 26 (self-hosted) with OTP over an SMPP link to a licensed SMS aggregator",
                               f"phone_otp on {ctx['deploy']}: identity stays on your servers; only the OTP text leaves through a telecom SMPP connection, not a SaaS identity product.",
                               dp + ["infrastructure.deployment_model"],
                               [("MSG91 / Twilio Verify APIs", "SaaS identity services, excluded by the on-premise rule")],
                               ["Needs a contract with an SMS aggregator and DLT-registered templates in India"], "self_hosted", "neutral", True, Z, ["keycloak", "trai-dlt"], loc))
                warn("EXTERNAL_TELECOM_LINK", "warning", "Phone OTP on-premises still needs an outbound telecom (SMPP) link to an SMS aggregator; this is the only external dependency of the auth layer.",
                     ["requirements.auth", "infrastructure.deployment_model"])
            elif p == "aws":
                out.append(svc("auth", f"Amazon Cognito user pool + Amazon SNS SMS OTP{rtxt}",
                               f"phone_otp with cloud_preference aws: Cognito custom-auth issues OTP via SNS SMS inside AWS{rtxt}, keeping identity data in the chosen region.",
                               dp + ["infrastructure.cloud_preference"] + res_path,
                               [("MSG91 OTP", "cheaper Indian SMS, but a second vendor outside the requested AWS footprint"),
                                ("Firebase Authentication (phone)", "Google service outside the AWS preference")],
                               ["India SMS needs DLT-registered sender ID and templates", "SMS cost scales with logins"],
                               "managed", "aws", True, [[0, 5], [5, 40], [30, 250], [250, 1500]],
                               ["aws-cognito-pricing", "aws-sns-sms", "trai-dlt"], loc))
            elif loc == "india" or ctx["residency"] == "india" or ctx["india_users"]:
                in_res = loc == "india" or ctx["residency"] == "india"
                out.append(svc("auth", "Backend-issued sessions + MSG91 OTP API (India)",
                               "phone_otp for Indian users: an Indian SMS provider with DLT-registered templates is the cheapest reliable OTP route (about Rs 0.20 per SMS); "
                               "the backend stores users and refresh tokens in the in-region database.",
                               dp + res_path + ([] if in_res else ["compliance"]),
                               [("Firebase Authentication (phone)", "stores identity data in Google's global auth service" + (", conflicting with India residency" if in_res else "; acceptable, but costlier per SMS at scale")),
                                ("Twilio Verify", "about $0.05 per verification plus SMS, far above Indian SMS rates")],
                               ["DLT registration of sender ID/template before launch", "OTP needs network at login; sessions must stay valid offline"],
                               "saas", "msg91", False, Z, ["msg91-otp", "trai-dlt", "firebase-pricing", "twilio-verify"]))
            else:
                out.append(svc("auth", "Twilio Verify (SMS OTP) + backend-issued sessions",
                               "phone_otp without a residency constraint: a managed verification API handles carrier routing and fraud checks.",
                               dp, [("Firebase Authentication (phone)", "ties identity to Firebase; fine alternative if the team prefers Google")],
                               ["Per-verification fee (~$0.05) plus SMS"], "saas", "twilio", False, Z, ["twilio-verify", "firebase-pricing"]))
        else:  # email_password / social
            social = auth == "social"
            if db and db["id"] == "supabase":
                out.append(svc("auth", "Supabase Auth" + (" with Google/GitHub/Apple social sign-in" if social else ""),
                               f"{auth} login from the same Supabase project as the database: users sit next to the data and row-level security policies can use the signed-in user id; free plan covers this scale.",
                               dp + ["budget.monthly_infra_usd"],
                               [("Framework built-in auth", "you would own password storage, reset e-mails and MFA"),
                                ("Auth0 / Clerk (SaaS)", "another vendor and per-user pricing on a near-zero budget")],
                               ["Ties identity to the Supabase project; migrating users later needs a password-hash export"],
                               "saas", "supabase", True, Z, ["supabase-pricing"], loc))
            elif p == "aws" and not selfh and ctx["lock"] != "low":
                choice = f"Amazon Cognito user pool{rtxt}" + (" with Google/Apple/Microsoft social sign-in" if social else "")
                out.append(svc("auth", choice, f"{auth} login on AWS: managed user pool with MFA and hosted UI{rtxt}.",
                               dp + ["infrastructure.cloud_preference"],
                               [("Framework built-in auth", "you would own password storage, reset flows and MFA")],
                               ["Cognito customisation limits"], "managed", "aws", True,
                               [[0, 0], [0, 30], [50, 300], [300, 2000]], ["aws-cognito-pricing"], loc))
            else:
                lib = {"python-django": "Django auth + django-allauth", "dotnet-aspnet": "ASP.NET Core Identity",
                       "java-spring": "Spring Security (+ OAuth2 client)", "php-laravel": "Laravel Fortify/Socialite",
                       "ruby-rails": "Rails authentication generator + OmniAuth",
                       "python-fastapi": "FastAPI Users (+ Authlib OAuth)", "go-chi": "Keycloak 26 (container next to the API)"}.get(backend["id"] if backend else "", "Auth.js / Passport (Node)")
                if social:
                    lib += " with Google/GitHub/Microsoft OAuth"
                kc = lib.startswith("Keycloak")
                out.append(svc("auth", lib,
                               (f"{auth} login on a self-hosted identity server: Go has no batteries-included auth framework, so Keycloak handles passwords, MFA and social providers{' and keeps identities in-region' if loc else ''}."
                                if kc else f"{auth} login kept inside the application: users live in your own database{' (in-region)' if loc else ''}, so no extra vendor or data transfer."),
                               dp + (["team.languages"] if backend else []),
                               [("Auth0 / Clerk (SaaS)", "extra monthly cost per active user and identity data outside your region"),
                                ("Hand-written auth in Go", "security-sensitive code the team would have to maintain") if kc else ("Keycloak", "a separate service to run for a single application")],
                               ["You run and upgrade Keycloak"] if kc else ["You own password hashing, reset e-mails and MFA setup"],
                               "self_hosted" if kc else "library", "neutral", kc, Z, ["keycloak"], loc))

    # ---------------- storage
    if req["requirements.file_media_storage"] or d["gps_media"] or d["kyc"]:
        dp = ["requirements.file_media_storage"] + res_path
        extra = " Private bucket, server-generated signed URLs, encryption with managed keys." if (d["kyc"] or ctx["compliance"]) else " Private bucket with signed upload/download URLs."
        if selfh:
            out.append(svc("storage", "SeaweedFS (self-hosted S3-compatible object store)",
                           "User files must stay on your own servers; SeaweedFS exposes the S3 API so the app code stays portable." + extra,
                           dp + ["infrastructure.deployment_model"],
                           [("MinIO", "its open-source repository was archived in April 2026 and is no longer maintained"),
                            ("Local disk / NFS volume", "no S3 API; harder backups and scaling")],
                           ["You run replication and backups for the object store"], "self_hosted", "neutral", True, Z, ["seaweedfs", "minio-archived"], loc))
        else:
            name = {"aws": "Amazon S3", "azure": "Azure Blob Storage", "gcp": "Google Cloud Storage"}.get(p, "Cloudflare R2" if not loc else "Amazon S3")
            prov = p if hyper else ("cloudflare" if not loc else "aws")
            alt = [("Storing files in the database", "bloats backups and costs more per GB")]
            if hyper:
                alt.append(("Cloudflare R2", f"zero egress fees, but a second vendor outside {p.upper()}"))
            reg = region or (host["regions"].get("india") if loc == "india" else None)
            out.append(svc("storage", f"{name}{(' (' + reg + ')') if reg else ''}",
                           f"Uploads ({'GPS-tagged photos' if d['gps_media'] else 'images, documents'}) go straight from clients to object storage via signed URLs.{extra}",
                           dp, alt, ["Egress charges for heavy downloads"], "managed", prov, True,
                           [[0, 2], [1, 10], [10, 80], [80, 600]], ["aws-india-data", "gcp-storage-locations", "azure-regions"], loc))

    # ---------------- search
    if req["requirements.full_text_search"]:
        dp = ["requirements.full_text_search"]
        if not ctx["needs_backend"]:
            out.append(svc("search", "Pagefind (static search index built at deploy time)",
                           "Search over a static site without any server: the index is generated with the pages.", dp,
                           [("Algolia", "paid SaaS for a small static site")], ["Index size grows with content"], "library", "neutral", False, Z, ["statement"]))
        elif db and db["id"] in ("postgresql", "mysql", "sqlserver") and ctx["tier"] <= 1:
            native = {"postgresql": "PostgreSQL full-text search (tsvector + GIN index)", "mysql": "MySQL FULLTEXT indexes",
                      "sqlserver": "SQL Server Full-Text Search"}[db["id"]]
            out.append(svc("search", native,
                           f"At ~{ctx['users']:,} users the primary database's built-in full-text search is enough; no extra service to run or pay for.",
                           dp + ["scale.users_12_months"],
                           [("Meilisearch / OpenSearch", "a separate cluster to operate before the data size needs it")],
                           ["Typo tolerance and ranking are basic; move to a search engine if relevance becomes a product feature"],
                           "library", "neutral", False, Z, ["postgres-fts"]))
        else:
            if p == "aws" and not selfh:
                c, prov, cost, src = f"Amazon OpenSearch Service{rtxt}", "aws", [[25, 60], [60, 200], [200, 800], [800, 4000]], ["aws-opensearch", "opensearch-license"]
            elif p == "azure" and not selfh:
                c, prov, cost, src = f"Azure AI Search{rtxt}", "azure", [[0, 75], [75, 250], [250, 1000], [1000, 4000]], ["azure-ai-search"]
            else:
                c, prov, cost, src = "Meilisearch (self-hosted container, MIT core)", "neutral", [[0, 10], [10, 40], [40, 200], [200, 800]], ["meilisearch-license"]
            alts = [("Database full-text search", "relevance and load isolation weaker at this scale")]
            if p == "gcp" and not selfh:  # Google Cloud has no managed engine comparable to OpenSearch / Azure AI Search
                src = src + ["gcp-vertex-search"]
                alts.append(("Vertex AI Search", "Google positions it as generative-AI search for websites, enterprise data and media, not a general "
                             "application search engine; a managed Elasticsearch-compatible service (for example Elastic Cloud on the Google Cloud Marketplace) can be priced if self-hosting is unwanted"))
            out.append(svc("search", c, f"Search at {ctx['users']:,} users / {ctx['data_gb']:g} GB benefits from a dedicated engine with relevance tuning, kept in the same region as the data.",
                           dp + ["scale.users_12_months"] + res_path,
                           alts,
                           ["Index must be kept in sync with the database (outbox/CDC)"],
                           "managed" if prov != "neutral" else "self_hosted", prov, True, cost, src, loc))

    # ---------------- realtime
    collab = ctx["type"] == "realtime_collab" or d["collab"]
    if req["requirements.realtime"] and ctx["type"] != "gaming":  # games: dedicated game servers (domains.py)
        dp = ["requirements.realtime"]
        if collab:
            out.append(svc("realtime", "Yjs CRDT documents + Hocuspocus WebSocket server",
                           "Many people edit the same board at once: CRDTs merge concurrent edits without conflicts and broadcast cursors/presence (awareness); Hocuspocus persists document updates to the database.",
                           dp + ["project.type", "project.description"],
                           [("Liveblocks (managed)", "fastest to start but per-room pricing and board data held by a third party"),
                            ("Plain WebSocket broadcast", "last-write-wins loses concurrent edits")],
                           ["Stateful socket servers need sticky routing or a Redis pub/sub backplane when scaled out"],
                           "self_hosted" if not hyper else "library", "neutral", False, Z, ["yjs", "hocuspocus", "liveblocks-pricing"]))
        else:
            bid = backend["id"] if backend else ""
            native = {"dotnet-aspnet": "ASP.NET Core SignalR", "java-spring": "Spring WebSocket (STOMP)",
                      "python-django": "Django Channels", "python-fastapi": "FastAPI WebSockets",
                      "go-chi": "WebSockets in Go (coder/websocket)", "php-laravel": "Laravel Reverb",
                      "ruby-rails": "Rails Action Cable"}.get(bid, "Socket.IO on the Node API")
            if p == "azure" and ctx["tier"] >= 2:
                native = "Azure SignalR Service (managed)"
            if kind == "serverless" and p == "aws":
                native = f"Amazon API Gateway WebSocket APIs{rtxt} (gateway holds connections; Lambda handles messages)"
            out.append(svc("realtime", native,
                           f"Live updates{' and chat' if d['chat'] else ''} over WebSockets from the same backend, so authorisation and data stay in one place.",
                           dp + (["project.description"] if d["chat"] else []),
                           [("Ably / Pusher", "managed fan-out, but an extra vendor and per-connection cost"),
                            ("Polling", "wastes requests and adds latency")],
                           ["Scale-out needs a pub/sub backplane (Redis/Valkey)"], "library", "neutral", False, Z, ["ably-pricing"]))

    # ---------------- cache
    read_hot = req["scale.workload"] == "read_heavy" and ctx["peak"] >= 1000
    need_cache = ctx["tier"] >= 2 or read_hot or (req["requirements.realtime"] and ctx["tier"] >= 1 and collab) or (
        ctx["prio"]["performance"] >= 5 and ctx["tier"] >= 1)
    if need_cache and ctx["needs_backend"]:
        if selfh:
            c, prov, cost, src = "Valkey 8 (self-hosted container)", "neutral", Z, ["valkey"]
        elif p == "aws":
            c, prov, cost, src = f"Amazon ElastiCache for Valkey{rtxt}", "aws", [[13, 25], [15, 50], [50, 300], [300, 1500]], ["aws-elasticache", "valkey"]
        elif p == "azure":
            c, prov, cost, src = f"Azure Managed Redis{rtxt}", "azure", [[15, 30], [30, 60], [60, 350], [350, 1500]], ["azure-redis-retirement"]
        elif p == "gcp":
            c, prov, cost, src = f"Memorystore for Valkey{rtxt}", "gcp", [[15, 40], [40, 80], [80, 350], [350, 1500]], ["valkey"]
        else:
            c, prov, cost, src = "Valkey (platform-managed key-value)", p, [[0, 10], [10, 30], [30, 150], [150, 600]], ["valkey"]
        why = []
        if ctx["tier"] >= 2:
            why.append(f"~{ctx['peak']:,} concurrent users")
        if req["requirements.realtime"]:
            why.append("pub/sub backplane so WebSocket messages reach users on every instance")
        if ctx["prio"]["performance"] >= 5:
            why.append("performance priority 5")
        if read_hot:
            why.append("read-heavy workload: hot pages and lookups served from memory instead of the database")
        if ctx["type"] == "gaming":
            why.append("leaderboards and matchmaking queues on sorted sets")
        out.append(svc("cache", c, "Cache and pub/sub layer: " + "; ".join(why) + ".",
                       ["scale.peak_concurrent_users"] + (["scale.workload"] if read_hot else []) + (["requirements.realtime"] if req["requirements.realtime"] else []) + (["priorities.performance"] if ctx["prio"]["performance"] >= 5 else []),
                       [("Redis (7.4+)", "7.4-7.8 are source-available (RSALv2/SSPLv1) and Redis 8+ adds an AGPLv3 option (copyleft for network use); Valkey keeps the BSD licence"),
                        ("Azure Cache for Redis", "being retired (Sept 2028); Azure Managed Redis is the replacement") if p == "azure" else ("No cache", "database absorbs every hot read and no cross-instance pub/sub")],
                       ["Another stateful component to size and monitor"], "managed" if prov in ("aws", "azure", "gcp") else "self_hosted", prov, False, cost, src))

    # ---------------- queue
    need_queue = (req["requirements.payments"] and ctx["tier"] >= 2) or req["requirements.ml_features"] == "training" or (
        req["scale.workload"] == "write_heavy" and ctx["tier"] >= 2) or (req["requirements.offline_support"] and d["gps_media"]) or d["video_vod"]
    if need_queue and ctx["needs_backend"]:
        why = []
        if req["requirements.payments"] and ctx["tier"] >= 2:
            why.append("payment webhooks and ledger postings processed idempotently with retries")
        if d["video_vod"]:
            why.append("video transcoding jobs queued after each upload")
        if req["requirements.offline_support"] and d["gps_media"]:
            why.append("photo post-processing (thumbnails, EXIF/GPS extraction) after bursts of offline syncs")
        if req["scale.workload"] == "write_heavy" and ctx["tier"] >= 2:
            why.append("absorbs write bursts")
        if req["requirements.ml_features"] == "training":
            why.append("schedules training jobs")
        if selfh or not hyper:
            c, prov, cost, src = "Database-backed job queue in the app (e.g. Graphile Worker / Hangfire / Celery)", "neutral", Z, ["postgres-versioning"]
        else:
            c, prov, src = {"aws": (f"Amazon SQS{rtxt}", "aws", ["aws-regional"]), "azure": (f"Azure Service Bus{rtxt}", "azure", ["azure-products-by-region"]),
                            "gcp": (f"Google Cloud Pub/Sub / Cloud Tasks{rtxt}", "gcp", ["gcp-locations"])}[p]
            cost = [[0, 1], [0, 5], [5, 30], [30, 200]]
        out.append(svc("queue", c, "Background work: " + "; ".join(why) + ".",
                       [x for x in ("requirements.payments", "requirements.offline_support", "scale.workload", "requirements.ml_features")
                        if (x == "requirements.payments" and req[x] and ctx["tier"] >= 2) or (x == "requirements.offline_support" and req[x])
                        or (x == "scale.workload" and req[x] == "write_heavy" and ctx["tier"] >= 2) or (x == "requirements.ml_features" and req[x] == "training")] or ["project.description" if d["video_vod"] else "scale.workload"],
                       [("Synchronous processing in the request", "slow responses and lost work when a call fails")],
                       ["Consumers must be idempotent"], "managed" if prov in ("aws", "azure", "gcp") else "library", prov, True, cost, src, loc))

    # ---------------- payments
    if req["requirements.payments"]:
        dp = ["requirements.payments"]
        if ctx["no_internet"]:
            warn("PAYMENTS_NEED_NETWORK", "critical",
                 "Taking payments requires reaching a payment network, which contradicts an air-gapped deployment. Relaxed: payments excluded from the stack; record payments offline or via a separately connected system.",
                 ["requirements.payments", "infrastructure.deployment_model"])
        else:
            india = ctx["india_users"] or d["upi"]
            via_compliance = india and ctx["residency"] != "india" and not d["upi"]
            pci = "pci_dss" in ctx["compliance"]
            feats, extra_src = [], []
            store = bool(ctx["mobile"]) and (ctx["type"] == "gaming" or d["digital_goods"]) and ctx["type"] not in ("marketplace", "ecommerce", "fintech")
            if store:
                stores = [x for x in ("Google Play Billing" if "android" in ctx["mobile"] else None,
                                      "Apple In-App Purchase (StoreKit)" if "ios" in ctx["mobile"] else None) if x]
                web_gw = ("Razorpay" if india else "Stripe") if ctx["web"] else None
                out.append(svc("payments", " + ".join(stores) + (f" (+ {web_gw} for web purchases)" if web_gw else ""),
                               "In-app digital goods (items, currency, premium content, subscriptions) sold inside a mobile app must use the store's "
                               "billing: Google Play's payments policy and App Store guideline 3.1.1. Purchases are confirmed by server-side receipt "
                               "validation before items are granted." + (f" Web purchases outside the apps can use {web_gw}." if web_gw else ""),
                               dp + ["project.type", "project.platforms"] + (["project.description"] if d["digital_goods"] else []),
                               [("Stripe/Razorpay checkout inside the app", "violates store policy for digital goods and risks removal from the stores"),
                                ("RevenueCat (SaaS wrapper)", "simplifies receipts across stores, but adds a vendor and a revenue-based fee")],
                               ["Store commission on digital sales", "Refunds and chargebacks arrive as store notifications, not gateway webhooks"],
                               "saas", "google" if "android" in ctx["mobile"] else "apple", True, Z, ["play-billing", "apple-iap"]))
            if store:
                name, prov, src, alts = out[-1]["choice"], out[-1]["provider"], [], []
            elif india:
                name = "Razorpay (UPI, cards, netbanking)"
                if d["payouts"] or ctx["type"] == "marketplace":
                    lend = ctx["type"] == "fintech" or bool(re.search(r"loan|disburs|lend", (req["project.description"] or "").lower()))
                    feats.append("RazorpayX Payouts for UPI loan disbursals to borrowers" if lend else "Route/RazorpayX Payouts to pay service providers")
                    extra_src += ["razorpay-route", "razorpayx-payouts"]
                if d["recurring"]:
                    feats.append("Subscriptions with UPI AutoPay / e-mandate for recurring collections")
                    extra_src.append("razorpay-subscriptions")
                alts = [("Cashfree Payments", "comparable Indian gateway; Razorpay chosen for combined UPI + payouts + subscriptions documentation"),
                        ("Stripe", "India accounts are invite-based and UPI coverage is narrower")]
                src = ["razorpay-upi", "razorpay-pricing", "razorpay-security", "stripe-india"] + extra_src
                prov = "razorpay"
            else:
                name = "Stripe (Checkout)"
                if d["recurring"]:
                    feats.append("Stripe Billing with per-seat subscription quantities")
                    extra_src += ["stripe-quantities", "stripe-billing-pricing"]
                if d["payouts"] or ctx["type"] == "marketplace":
                    feats.append("Stripe Connect for marketplace payouts")
                alts = [("Paddle (merchant of record)", "handles global tax but higher fees and less control"),
                        ("Adyen", "enterprise pricing/onboarding for this size")]
                src = ["stripe-billing-pricing"] + extra_src
                prov = "stripe"
            why = ("Hosted checkout keeps card data off your servers, which can qualify for PCI DSS SAQ A (your acquirer confirms; protect the checkout page from script attacks). "
                   "Payment confirmation is trusted only from signed server-side webhooks.")
            if d["upi"]:
                why = "The description requires UPI. " + why
            if ctx["type"] == "fintech" and d["ledger"]:
                why += (" For lending, disburse straight to the borrower's bank account and collect repayments directly into the "
                        "lender's (regulated entity's) account — no pooled pass-through accounts (RBI Digital Lending Directions 2025).")
                src += ["rbi-digital-lending"]
            if pci:
                why += " pci_dss: the gateway is PCI DSS Level 1; your scope still covers the pages that embed checkout."
                src += ["pci-saq-a", "pci-v4"]
            if ctx["self_host_only"]:
                warn("EXTERNAL_PAYMENT_GATEWAY", "critical",
                     f"Payments cannot be self-hosted: {name.split(' (')[0]} is the single external SaaS dependency kept on {ctx['deploy']} "
                     + ("(app-store billing and receipt validation run on Google/Apple servers)." if store
                        else "(card/UPI networks are external by nature). Card data never touches your servers."),
                     ["requirements.payments", "infrastructure.deployment_model"])
            if not store and not india and ctx["res_key"] in ("eu", "us") and ctx["req"]["infrastructure.data_residency"] in ("eu", "us"):
                warn("PAYMENT_DATA_LOCATION", "critical",
                     f"{name.split(' (')[0]} processes payer data; its storage location for {ctx['residency'].upper()} residency is not verified in the knowledge base — confirm the data-processing terms.",
                     ["requirements.payments", "infrastructure.data_residency"])
            if not store and ctx["type"] == "api_platform" and not india:
                feats.append("usage-based (metered) billing from API-gateway usage records")
                src = src + ["stripe-usage-billing"]
            if not store:
                out.append(svc("payments", name + (" — " + "; ".join(feats) if feats else ""), why,
                               dp + (["project.description"] if (feats or d["upi"]) else []) + (["compliance"] if pci or via_compliance else []) + res_path,
                               alts, ["Per-transaction fees (~2% domestic cards) are charged on revenue, not in the infrastructure band",
                                      "Webhook handling must be idempotent"],
                               "saas", prov, True, Z, src, "india" if india else None))

    # ---------------- cdn
    public_media = ctx["mobile"] and not ctx["web"] and req["requirements.file_media_storage"] and (d["video_vod"] or ctx["type"] == "social")
    if ((ctx["web"] or public_media) and ctx["needs_backend"] and not selfh and not d["internal_only"]
            and (req["requirements.seo_critical"] or ctx["tier"] >= 1 or ctx["geo"] in ("multi_region", "global"))):
        name = {"aws": "Amazon CloudFront", "azure": "Azure Front Door", "gcp": "Cloud CDN"}.get(p, "Cloudflare (free plan)")
        paths = (["project.platforms"] + (["requirements.seo_critical"] if req["requirements.seo_critical"] else ["scale.users_12_months"])
                 + (["scale.geo_spread"] if ctx["geo"] in ("multi_region", "global") else []))
        why = "Caches public pages and static assets near users; only public, non-personal content is cached at the edge."
        # Front Door's $35 base fee (verified, R11) is more than 15% of a budget under ~$233; unless Azure was requested
        # explicitly (a hard constraint), the free Cloudflare plan in front of Azure does the same job for a small site
        if p == "azure" and req["infrastructure.cloud_preference"] != "azure" and ctx["budget"] < 35 / 0.15:
            out.append(svc("cdn", "Cloudflare (free plan) in front of Azure", why + f" Azure Front Door's $35/month base fee would take "
                           + (f"{3500 / ctx['budget']:.0f}% of" if ctx["budget"] >= 35 else "more than all of")
                           + f" the ${ctx['budget']:g} budget, so the free plan is used.",
                           paths + ["budget.monthly_infra_usd"],
                           [("Azure Front Door", "the $35/month Standard base fee is too large a share of this budget; switch when the budget grows"),
                            ("No CDN", "every asset request hits the origin; slower for distant users")],
                           ["Cache invalidation on deploys", "A second vendor for DNS/TLS, outside the Azure contract", CF_FREE],
                           "saas", "cloudflare", False, [[0, 1], [0, 5], [0, 20], [20, 200]], ["cloudflare-plans"]))
        else:
            out.append(svc("cdn", name, why, paths,
                       [("No CDN", "every asset request hits the origin; slower for distant users")]
                       + ([("Cloudflare (free plan) in front of Azure", "cheaper for a small site, but a second vendor for DNS/TLS and outside the Azure contract")] if p == "azure" else []),
                       ["Cache invalidation on deploys"] + (["Front Door Standard has a $35/month base fee before requests and egress"] if p == "azure" else [])
                       + ([CF_FREE] if name.startswith("Cloudflare (free plan)") else []),
                       "managed", p if hyper else "cloudflare", False,
                       # Azure: the $35 base fee is verified (R11); request/egress growth in the larger tiers is an estimate
                       [[35, 40], [35, 60], [50, 200], [150, 900]] if p == "azure" else [[0, 1], [1, 15], [15, 120], [120, 800]],
                       ["azure-frontdoor-pricing"] if p == "azure" else ["aws-regional"]))

    # ---------------- ml
    ml = req["requirements.ml_features"]
    if ml != "none":
        dp = ["requirements.ml_features"]
        py = backend and "python" in backend["langs"]
        if ml == "inference_api":
            if py:
                c, why = "In-process model inference (scikit-learn/XGBoost exported to ONNX Runtime)", "The backend is Python, so the trained model loads inside the API: no extra network hop, versioned model files."
            else:
                c, why = ("Separate Python inference service (FastAPI + ONNX Runtime) in the same private network",
                          f"The core API is {backend['name'] if backend else 'not Python'}; a small Python service serves the model behind an internal endpoint so data scientists keep their tooling.")
            if d["scoring_model"]:
                why += " Credit-scoring outputs and their inputs are logged for audit and explainability."
            alt = {"aws": ("Amazon SageMaker AI real-time endpoint", "managed MLOps, but always-on endpoint cost before volume justifies it"),
                   "azure": ("Azure Machine Learning online endpoint", "managed MLOps, but extra always-on cost now"),
                   "gcp": ("Vertex AI online prediction", "managed MLOps, but extra always-on cost now")}.get(p, ("Hosted inference API (third party)", "sends personal data to another vendor"))
            out.append(svc("ml", c, why, dp + (["project.description"] if d["scoring_model"] else []) + res_path,
                           [alt], ["Model versioning, drift monitoring and fairness review are your responsibility"],
                           "self_hosted" if selfh else "library", "neutral", True,
                           [[0, 10], [10, 40], [40, 200], [200, 1000]], ["aws-sagemaker"], loc))
        elif ml == "llm_rag":
            if selfh:
                c, prov, src = "Self-hosted open-weight LLM (vLLM/Ollama on a GPU node) + pgvector", "neutral", ["postgres-versioning"]
                warn("LLM_SELF_HOSTED_CAPACITY", "warning", "Self-hosted LLM needs GPU hardware; quality and latency depend on the model you can run locally.",
                     ["requirements.ml_features", "infrastructure.deployment_model"])
            else:
                c, prov, src = {"aws": (f"Amazon Bedrock{rtxt} + pgvector", "aws", ["aws-bedrock"]),
                                "azure": ("Azure OpenAI (Foundry) + Azure AI Search vectors", "azure", ["azure-ai-search"]),
                                "gcp": ("Vertex AI Gemini + pgvector", "gcp", ["gcp-locations"])}.get(p, ("Hosted LLM API + pgvector", "neutral", ["postgres-versioning"]))
                if loc:
                    warn("LLM_REGION_CHECK", "critical", f"Confirm the chosen LLM model is served in {ctx['residency'].upper()} before sending personal data to it.",
                         ["requirements.ml_features", "infrastructure.data_residency"])
            out.append(svc("ml", c, "Retrieval-augmented generation: embeddings stored next to the data, "
                           + ("a local model" if selfh else "a managed model") + " generates answers from retrieved passages.",
                           dp, [("Fine-tuning a model", "costlier and slower to update than retrieval")],
                           ["GPU hardware, power and operations must be sized separately; evaluate answer quality"] if selfh else ["Per-token cost; evaluate answer quality"],
                           "managed" if prov != "neutral" else "self_hosted", prov, True,
                           Z if selfh else [[5, 30], [30, 200], [200, 1500], [1500, 8000]], src, loc))
        else:
            managed = hyper and not ctx["self_host_only"]  # on_premise/air_gapped: own GPU hardware, outside the cloud bill
            c = {"aws": "Amazon SageMaker AI training jobs", "azure": "Azure Machine Learning training jobs", "gcp": "Vertex AI custom training"}.get(p) if managed                 else "Scheduled training job on a GPU/CPU worker (PyTorch / scikit-learn)"
            out.append(svc("ml", c, "Model training runs as scheduled batch jobs separate from the serving path.", dp,
                           [("Training inside the web API", "starves user requests of CPU/memory")],
                           ["Training data governance and cost control"] + (["GPU hardware, power and operations must be sized separately"] if ctx["self_host_only"] else []),
                           "managed" if managed else "self_hosted", p if managed else "neutral", True,
                           Z if ctx["self_host_only"] else [[10, 50], [50, 200], [200, 1500], [1500, 8000]], ["aws-sagemaker"], loc))
            lo, hi = out[-1]["_cost"][ctx["tier"]]  # ml.g4dn.xlarge Training $0.736/h us-east-1, AWS price data 11 Nov 2026
            out[-1]["_note"] = (f" Basis: about {lo / 0.736:,.0f}-{hi / 0.736:,.0f} GPU-hours a month on one T4-class GPU at $0.736/hour ("
                                + ("ml.g4dn.xlarge on-demand training, us-east-1, AWS price data 11 Nov 2026" if p == "aws"
                                   else "AWS ml.g4dn.xlarge reference rate; this provider's T4 rate was not checked")
                                + "). Larger models or more frequent retraining scale this linearly.") if managed else ""

    # ---------------- ci/cd + observability
    if ctx["self_host_only"]:
        out.append(svc("ci_cd", "Gitea + Gitea Actions (self-hosted)",
                       f"deployment_model {ctx['deploy']}: source, builds and container images stay inside your network (no SaaS CI).",
                       ["infrastructure.deployment_model"], [("GitHub Actions", "SaaS, not allowed under this deployment model")],
                       ["Mirror base images and packages into a local registry"], "self_hosted", "neutral", False, Z, ["gitea"]))
        out.append(svc("observability", "Prometheus + Grafana + Loki (self-hosted)",
                       "Metrics, dashboards and logs without any external service.", ["infrastructure.deployment_model"],
                       [("Sentry / Datadog", "SaaS services, not allowed here")], ["Retention and alerting are yours to run"],
                       "self_hosted", "neutral", True, Z, ["grafana-stack"], loc))
    else:
        ci_cost = [0, 4] if ctx["size"] <= 3 else ([0, 20] if ctx["size"] <= 8 else [20, 100])  # minutes scale with engineers, not users
        out.append(svc("ci_cd", "GitHub Actions", f"Automated tests and deploys on every push{' to ' + host['name'] if host else ''}; free minutes cover a team of {ctx['size']}.",
                       ["team.size", "team.has_devops"], [("GitLab CI", "equivalent; GitHub chosen for its marketplace of deploy actions")],
                       ["Secrets must be stored as encrypted environment secrets"], "saas", "github", False,
                       [ci_cost] * 4, ["gha-billing"]))
        ob = {"aws": (f"Amazon CloudWatch{rtxt} (logs, metrics, alarms)", "aws"),
              "azure": (f"Azure Monitor + Application Insights{rtxt}", "azure"),
              "gcp": (f"Cloud Logging + Cloud Monitoring{rtxt}", "gcp")}.get(p, ("Platform logs/metrics + Prometheus/Grafana on the VM" if kind == "vm" else "Platform logs and metrics + uptime checks", p))
        if ctx["needs_backend"]:
            out.append(svc("observability", ob[0], f"Logs and metrics stay with the host provider{rtxt}; alerts on error rate and latency{(' against the ' + str(req['requirements.p95_latency_ms']) + ' ms p95 target') if req['requirements.p95_latency_ms'] else ''}.",
                           ["requirements.availability"] + (["requirements.p95_latency_ms"] if req["requirements.p95_latency_ms"] else []) + res_path,
                           [("Sentry (SaaS)", "stores data only in the US or EU" if loc == "india" else "extra vendor; add later for richer error grouping")],
                           ["Log retention costs grow with traffic"], "managed" if hyper else "self_hosted", ob[1], True,
                           [[0, 5], [5, 30], [30, 200], [200, 1200]], ["sentry-regions"], loc))

    # ---------------- other (domain-specific)
    if req["requirements.offline_support"] and not ctx["needs_backend"]:
        out.append(svc("other", "Service worker precache (Workbox) for offline reading",
                       "Must work without connectivity: the pre-built pages and assets are cached on first visit, so the site reads offline with no server or sync API.",
                       ["requirements.offline_support", "project.type"],
                       [("Offline-first sync API", "nothing is written by visitors, so there is nothing to sync")],
                       ["Cached pages update on the next visit online", "Browser storage quotas limit very large sites"],
                       "client", "neutral", False, Z, ["workbox"], None))
    elif req["requirements.offline_support"]:
        mid = mobile["id"] if mobile else ""
        local = {"kotlin-compose": "Room (SQLite) + WorkManager", "kmp-compose": "SQLDelight + WorkManager",
                 "react-native-expo": "expo-sqlite + background task", "flutter": "drift (SQLite) + workmanager plugin",
                 "capacitor": "SQLite plugin + background runner"}.get(mid, "Service worker + IndexedDB (Workbox)")
        bits = ["writes go to an on-device database first", "an outbox queue retries uploads when signal returns",
                "each record carries a client-generated UUID so retries are idempotent", "server applies last-writer-wins per field with an edit log"]
        if d["gps_media"]:
            bits.append("photos are compressed on-device and uploaded with resumable chunks")
        if d["low_bandwidth"]:
            bits.append("sync batches are small and compressed for 2G/3G")
        out.append(svc("other", f"Offline-first sync: {local}, outbox + idempotent sync API",
                       "Must work without connectivity: " + "; ".join(bits) + ".",
                       ["requirements.offline_support"] + (["project.description"] if (d["gps_media"] or d["low_bandwidth"]) else []),
                       [("Firebase Firestore offline cache", "convenient but ties data to Google's global service and its pricing"),
                        ("Online-only app", "fails the stated offline requirement")],
                       ["Conflict resolution rules must be agreed with field teams", "Device storage limits on low-end phones"],
                       "client", "neutral", True, Z, ["android-offline-first", "workmanager"], "device"))
    if ctx["mobile"] and (d["jobs_dispatch"] or d["notifications"] or d["chat"]) and not ctx["self_host_only"] and "hipaa" in ctx["compliance"]:
        warn("PHI_IN_PUSH", "warning",
             "Firebase Cloud Messaging is not on Google Cloud's HIPAA covered-products list: push payloads must carry no PHI (send an opaque id; "
             "the app fetches details after sign-in).", ["compliance", "project.platforms"])
    if ctx["mobile"] and (d["jobs_dispatch"] or d["notifications"] or d["chat"]) and not ctx["self_host_only"]:
        out.append(svc("other", "Firebase Cloud Messaging (push notifications)",
                       "Mobile users must hear about new jobs/messages immediately; FCM is no-cost and also relays to iOS via APNs. Payloads carry only an ID, never personal data.",
                       ["project.platforms", "project.description"],
                       [("Polling from the app", "drains battery and misses events when the app is closed")],
                       ["Delivery is best-effort; critical updates also appear in-app"], "saas", "google", False, Z,
                       ["firebase-pricing"] + (["gcp-hipaa-products"] if "hipaa" in ctx["compliance"] else [])))
    if (ctx["existing_m365"] or (d["approvals"] and ctx["existing_idp"])) and ctx["no_internet"]:
        out.append(svc("other", "Approval notifications through the on-premises SMTP relay",
                       "Approvals must notify managers, but an air-gapped network cannot reach Microsoft 365; the internal mail relay carries notifications.",
                       ["infrastructure.existing_systems", "infrastructure.deployment_model"],
                       [("Microsoft Graph", "cloud API unreachable from an air-gapped network")], ["Depends on an internal mail server"],
                       "self_hosted", "neutral", False, Z, ["statement"]))
    elif ctx["existing_m365"] or (d["approvals"] and ctx["existing_idp"]):
        if ctx["self_host_only"]:
            warn("EXTERNAL_EXISTING_SERVICE", "critical",
                 "Microsoft 365 is an existing cloud service; calling Microsoft Graph for notifications is kept as an integration with an existing system, not a new SaaS dependency.",
                 ["infrastructure.existing_systems", "infrastructure.deployment_model"])
        out.append(svc("other", "Microsoft Graph notifications (Outlook mail / Teams) for approvals",
                       "Approval requests and decisions reach managers in the Microsoft 365 tools they already use, authorised through the existing Entra tenant.",
                       ["infrastructure.existing_systems", "project.description"],
                       [("Separate e-mail service (SES/SendGrid)", "duplicates mail infrastructure the company already has")],
                       ["Needs admin consent for Graph application permissions"], "saas", "azure", False, Z, ["ms-graph"]))
    if req["requirements.multi_tenant"]:
        rls = db and db.get("rls")
        out.append(svc("other", "Tenant isolation: tenant_id on every row" + (" + database row-level security" if rls else " enforced in a repository layer"),
                       "Several customer organisations share the system: every query is scoped by tenant, enforced in the database so one bug cannot leak another team's boards.",
                       ["requirements.multi_tenant"], [("Database per tenant", "strong isolation but heavy operations for thousands of small teams")],
                       ["Every new table needs a policy"], "library", "neutral", False, Z, ["postgres-rls"]))
    if d["ledger"]:
        out.append(svc("other", "Double-entry ledger module (append-only journal, SERIALIZABLE transactions, idempotency keys)",
                       "Loan disbursals and EMI collections post balanced debit/credit entries that are never updated in place; reconciliation compares the ledger with gateway settlement reports.",
                       ["project.description", "requirements.payments"], [("Balance columns updated in place", "no audit trail and race conditions")],
                       ["Corrections are reversing entries, not edits"], "library", "neutral", True, Z, ["postgres-versioning"], loc))
    if d["kyc"]:
        out.append(svc("other", "KYC document vault (private encrypted bucket) + regulated KYC verification partner",
                       "KYC uploads are stored encrypted with access logging and retention rules; identity checks go through a licensed verification partner chosen by the business.",
                       ["project.description", "compliance"] + res_path, [("Storing KYC files in the app database", "large blobs and broader access")],
                       ["Verification partner contract and API not selected here"], "managed" if hyper else "self_hosted", p if hyper else "neutral", True, Z, ["rbi-digital-lending"], loc))
    if ctx["desc"]["markdown"] and not ctx["needs_backend"]:
        out.append(svc("other", "Git-based Markdown content (no CMS)",
                       "The owner writes posts in Markdown in the repository; every push rebuilds and publishes the site.",
                       ["project.description"], [("Headless CMS (Contentful/Sanity)", "adds accounts and cost for a single author")],
                       ["Non-technical editors would need a CMS later"], "library", "neutral", False, Z, ["astro"]))
    for e in ctx["existing"]:
        pat = e["pattern"]
        if pat and pat["kind"] == "database" and db:
            via = "App Service Hybrid Connection (outbound 443 relay, no inbound ports)" if p == "azure" else (
                "site-to-site VPN / private link" if not selfh else "the local network")
            out.append(svc("other", f"Integration with existing {e['raw']} via {via}",
                           f"{pat['how']} The new application keeps its own tables in {db['_variant']} and reads the existing data through {via}.",
                           ["infrastructure.existing_systems"],
                           [("Migrate everything into the new database now", "risky in the MVP timeline and breaks existing consumers"),
                            ("Use the on-prem server as the only database", "ties availability of the new app to the on-prem server and the relay")],
                           ["Cross-network latency on queries to the on-prem server", "Credentials for the on-prem database must live in a secret store"],
                           "library", "neutral", False, Z, pat["src"] + (["azure-hybrid-connections"] if p == "azure" else [])))
        elif pat and pat["kind"] in ("erp", "crm", "legacy_app", "payments"):
            out.append(svc("other", f"Integration with existing {e['raw']}", pat["how"], ["infrastructure.existing_systems"],
                           [("Replacing it", "outside MVP scope")], ["Depends on the existing system's API limits"], "library", "neutral", False, Z, pat["src"]))
    domains.build(ctx, host, backend, db, svc, warn, Z, out)
    return out
