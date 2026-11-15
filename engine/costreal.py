"""E8 cost realism (decision D17): named planning-heuristic tables and the small functions that turn them into cost lines.

Nothing here is a vendor quote. Every figure is either cited from kb/sources.json (the caller passes the source note) or labelled
'planning estimate' / 'planning heuristic' in the text the engine prints. The tables are policy, like engine/rightsize.py, and live in
this one file so a reader can see every number the cost realism rules use. Rules read input fields only, never a scenario name.
"""
import math
import re

# ---- (e) peak concurrency derived from a stated audience. Fractions are planning heuristics; only used when
# scale.peak_concurrent_users is absent. 0.10 is the long-standing default (kept so outputs without audience wording do not change).
PEAK_FRACTION = {"default": 0.10, "monthly_audience": 0.05, "monthly_audience_read_mostly": 0.02}
MONTHLY_AUDIENCE_RX = re.compile(r"\bmonthly\s+(?:active\s+)?(?:readers?|visitors?|viewers?|listeners?|users?|players?|customers?|subscribers?)\b"
                                 r"|\bmaus?\b|\b(?:readers?|visitors?|viewers?|listeners?)\s+(?:a|per|each|every)\s+month\b")

# ---- (a) share of a write-heavy IoT volume that is append-only rows (database storage rates) when file storage is also used
TS_ROWS_SHARE = 0.5  # planning heuristic: the rest is files or exports in object storage
DB_SSD_RATE = (0.10, 0.25)   # $/GB-month managed database SSD (Cloud SQL SSD $0.17 Iowa / $0.20 Mumbai, rendered 11 Nov 2026)
OBJ_RATE = (0.02, 0.035)     # $/GB-month object storage
# M1 phone OTP and Cognito, planning heuristics (every figure is printed in the cost line so it can be recomputed)
OTP_LOGINS_PER_USER = (0.3, 1.0)       # OTP logins per user per month: long-lived sessions keep them rare
INR_PER_USD = 90                       # planning exchange rate, not a quote
SMS_GST = 0.18                         # GST charged on top of Indian SMS prices (planning heuristic)
INDIA_SMS_RS = (0.20, 0.25)            # MSG91 OTP: Rs 0.20 per SMS at the 27k block + GST (msg91-otp); 0.25 is the upper planning figure
SMS_RETRY_FACTOR = (1.0, 1.5)          # lower bound: every code arrives first time; upper: 1.5 sends per code (retries, DLT rejections)
COGNITO_FREE_MAU, COGNITO_RATE = 10000, 0.0055   # aws-cognito-pricing (verified)
# p4: Cognito Lite volume tiers (aws-cognito-pricing worked example, rendered 15 Nov 2026): $0.0055 per MAU up to 100,000 MAU, then $0.0046
# up to 1,000,000 MAU. Rates above 1,000,000 MAU were not read: the $0.0046 rate is kept there, an upper bound if later tiers are cheaper.
COGNITO_TIERS = ((100_000, 0.0055), (float("inf"), 0.0046))
COGNITO_TIER_READ_TO = 1_000_000


def cognito_usd(mau):
    """USD a month for mau Cognito Lite MAUs: the free tier, then each slice at its tier's rate."""
    cost, prev = 0.0, COGNITO_FREE_MAU
    for cap, rate in COGNITO_TIERS:
        if mau <= prev:
            break
        cost += (min(mau, cap) - prev) * rate
        prev = cap
    return cost


MAU_SHARE = (0.3, 1.0)                 # monthly active users as a share of all users


def cognito_band(users):
    """(lo, hi) USD a month for Cognito Lite MAUs of `users` sign-in users (p5 item 6). Rates above COGNITO_TIER_READ_TO MAU were not
    read, so the lower bound counts MAUs only up to that point (a true floor) and the upper bound keeps the last read rate above it."""
    lo_mau, hi_mau = (users * x for x in MAU_SHARE)
    return round(cognito_usd(min(lo_mau, COGNITO_TIER_READ_TO))), round(cognito_usd(hi_mau))


def cognito_note(users, staff=False):
    (t1, r1), (_, r2) = COGNITO_TIERS
    mlo, mhi = (round(users * x) for x in MAU_SHARE)
    return (f" Cognito Lite: {COGNITO_FREE_MAU:,} MAU free, then ${r1} per MAU up to {t1:,} MAU and ${r2} per MAU up to {COGNITO_TIER_READ_TO:,} "
            f"(Amazon Cognito pricing); MAU taken as {MAU_SHARE[0]:.0%}-{MAU_SHARE[1]:.0%} of ~{users:,} {'staff who sign in' if staff else 'users'} = "
            f"{mlo:,}-{mhi:,} MAU (planning heuristic)"
            + (f"; rates above {COGNITO_TIER_READ_TO:,} MAU are not in the knowledge base, so the lower bound counts only the first "
               f"{COGNITO_TIER_READ_TO:,} MAU and the upper bound keeps ${r2} above it." if mhi > COGNITO_TIER_READ_TO else "."))


def india_sms_usd():
    return tuple(rs * (1 + SMS_GST) / INR_PER_USD for rs in INDIA_SMS_RS)


BLOCK_RATE = (0.08, 0.12)    # planning estimate: block disk under a database the team runs itself on a cloud VM
BROKER_NODE_MSGS_PER_S = 2000  # planning heuristic: one small self-run MQTT broker node
# A14: write-heavy or device-fed data at or above this volume is sized for ingest and for a database that holds it (planning heuristic)
INGEST_HEAVY_GB = 1000        # at 1 TB a write-heavy store needs an ingest buffer and no longer fits the smallest database tier
INGEST_DB_MIN_TIER = 2        # index into the tier names: 2 = 'medium'
# A13: managed WebSocket service (Azure Web PubSub / SignalR Service) billed per unit of concurrent connections; price NOT in the knowledge base
REALTIME_UNIT_CONNECTIONS = 1000        # planning heuristic: connections one unit carries
REALTIME_UNIT_USD_MONTH = (40, 60)      # planning estimate, official-unverified


def realtime_units(peak):
    return max(1, math.ceil(peak / REALTIME_UNIT_CONNECTIONS))


# Video egress (planning heuristic, shaped on the Google Cloud CDN cache egress tiers, source gcp-cdn-pricing): GB streamed per user per month
# (about 2-30 minutes of adaptive-bitrate video), the low-end rate, and the tiered rates for the high-end volume as (GB per month up to, USD per GB)
VIDEO_GB_PER_USER = (0.05, 0.5)
VIDEO_LOW_RATE = 0.02
VIDEO_EGRESS_TIERS = ((10_000, 0.09), (150_000, 0.06), (500_000, 0.04), (float("inf"), 0.03))


# p5 item 6: the chosen provider's own CDN transfer tiers (GB per month up to, USD per GB), official pages opened 15 Nov 2026.
# Amazon CloudFront pay-as-you-go (aws-cloudfront-payg): first 1 TB free. Azure Front Door edge-to-client (azure-frontdoor-pricing): bands
# above 150 TB are "Contact Us", so the 150 TB rate is kept there as an upper bound. Region: India rates under India residency, else the
# North America rates (a reference for other regions).
CDN_EGRESS_TIERS = {
    ("aws", "us"): ((1_024, 0.0), (10_240, 0.085), (51_200, 0.080), (153_600, 0.060), (512_000, 0.040), (1_048_576, 0.030),
                    (5_242_880, 0.025), (float("inf"), 0.020)),
    ("aws", "india"): ((1_024, 0.0), (10_240, 0.109), (51_200, 0.085), (153_600, 0.082), (512_000, 0.080), (1_048_576, 0.078),
                       (5_242_880, 0.075), (float("inf"), 0.072)),
    ("azure", "us"): ((10_240, 0.083), (51_200, 0.066), (float("inf"), 0.057)),
    ("azure", "india"): ((10_240, 0.109), (51_200, 0.085), (float("inf"), 0.083)),
}
CDN_EGRESS_NAME = {"aws": ("Amazon CloudFront pay-as-you-go transfer tiers, first 1 TB free", "aws-cloudfront-payg"),
                   "azure": ("Azure Front Door edge-to-client transfer tiers; bands above 150 TB are quoted on request, so the 150 TB rate is kept there",
                             "azure-frontdoor-pricing")}


def provider_tiers(provider, residency):
    """The provider's own CDN tier table, or None (another CDN: the caller keeps its reference rate)."""
    return CDN_EGRESS_TIERS.get((provider, "india" if residency == "india" else "us"))


def tiered_egress(gb, tiers=None):
    """USD for gb GB in a month, each slice at its tier's rate (default: the video reference tiers)."""
    cost, prev = 0.0, 0
    for cap, rate in tiers or VIDEO_EGRESS_TIERS:
        if gb <= prev:
            break
        cost += (min(gb, cap) - prev) * rate
        prev = cap
    return cost


ASSUMED_REPORT_SECONDS = 60    # planning assumption when the description gives a device count but no reporting interval
# Azure IoT Hub Standard tiers, list prices as published (NOT in the knowledge base, so printed as a planning estimate):
# (name, USD per unit-month, messages per unit-day)
IOT_HUB_TIERS = (("S1", 25, 400_000), ("S2", 250, 6_000_000), ("S3", 2500, 300_000_000))

# ---- (b) ML training: GPU-hours per stored GB per month. The managed table stays the lower bound.
TRAIN_GPU_HOURS_PER_GB = (0.02, 0.08)  # planning heuristic: 20-80 GPU-hours per TB of stored data per month
GPU_HOURS_PER_MONTH = 730  # planning heuristic (p5): one GPU running all month gives about 730 hours; more GPU-hours means several GPUs in parallel


def gpu_count_text(hours_lo, hours_hi, gpu_class):
    """p5: never price more than a month of hours on one GPU: '... on one T4-class GPU' or '... across 2-7 T4-class GPUs in parallel'."""
    lo, hi = (max(1, -(-int(round(h)) // GPU_HOURS_PER_MONTH)) for h in (hours_lo, hours_hi))
    if hi <= 1:
        return f"on one {gpu_class} GPU"
    return (f"across {lo if lo == hi else f'{lo}-{hi}'} {gpu_class} GPUs in parallel (one GPU gives about {GPU_HOURS_PER_MONTH} hours a month, "
            "planning heuristic), each GPU billed")
TRAIN_GPU_RATE = 0.736                 # $/h ml.g4dn.xlarge on-demand training, us-east-1 (kb source aws-sagemaker)
TRAIN_FLOOR_GB = 100                   # below this volume training stays on the tier table
# i2 (planning heuristic): a small, scheduled retrain of a classical model (tier 0-1, stored data under TRAIN_FLOOR_GB, no deep-learning or
# large-model words in the description) runs as a CPU job on the host or one small worker, not on a managed GPU training service.
TRAIN_CPU_MAX_TIER = 1
TRAIN_CPU_COST = [[0, 10], [5, 25]]    # per tier 0-1, USD/month: a few CPU-hours of a small worker or spare capacity on the existing host
TRAIN_HEAVY_RX = re.compile(r"\b(?:deep learning|neural|cnn|rnn|lstm|transformers?|gpus?|llms?|fine-?tun\w*|computer vision|image (?:model|classif\w*|recogni\w*)"
                            r"|speech|diffusion|embedding model|foundation model|large model|reinforcement learning"
                            r"|images?|photos?|imagery|scans?|x-?rays?|video|vision|object detection|face|ocr|transcri\w*|voice|audio|yolo|bert|gpt|chatbot|nlp"
                            r"|language model|segmentation)\b")


def training_on_cpu(ctx):
    """True when the training described is small and scheduled enough for a CPU job (see TRAIN_CPU_MAX_TIER)."""
    desc = (ctx["req"]["project.description"] or "").lower()
    return ctx["tier"] <= TRAIN_CPU_MAX_TIER and ctx["data_gb"] < TRAIN_FLOOR_GB and not TRAIN_HEAVY_RX.search(desc)

# ---- (c) on-premises hardware, one purchase amortised over 36 months. (servers, USD per server low, high); planning heuristic
ONPREM_AMORTISE_MONTHS = 36
ONPREM_SERVER = {0: (1, 1500, 3000), 1: (2, 2000, 4000), 2: (3, 3000, 6000), 3: (6, 5000, 10000)}
ONPREM_DISK_PER_TB = (150, 300)       # one-time USD per usable TB including RAID and a backup copy; counted above 500 GB
ONPREM_GPU_NODE = (4000, 12000)       # one GPU server when the stack trains or serves a model locally
ONPREM_TOOLING_NODE = (1000, 2000)    # CI, registry, metrics and logs for a team larger than TEAM_SHARES_APP_SERVER
TEAM_SHARES_APP_SERVER = 3
ONPREM_RUNNING_SHARE = 0.30           # power, cooling and spares on top of the amortised price (high end only)

# ---- (d) usage assumptions for per-message and per-unit services (planning estimates unless a source is named)
EMAIL_SENDS_PER_RECIPIENT_MONTH = (4, 8)
EMAIL_USD_PER_THOUSAND = (0.10, 0.60)
LLM_QUESTIONS_PER_USER_MONTH = (5, 20)
LLM_TOKENS_PER_QUESTION = (3000, 400)            # input (retrieved passages + question), output
LLM_USD_PER_MILLION_IN = (0.15, 0.60)
LLM_USD_PER_MILLION_OUT = (0.60, 2.40)
SINGLE_LINE_BUDGET_MULTIPLE = 10                 # a line above this multiple of the budget gets an explicit note

# what to cut, per cost-line family (explain-only: nothing is removed)
CUT_HINTS = (
    ("Phone OTP", "the stack keeps phone one-time codes because requirements.auth is phone_otp; each sign-in moved to an e-mail link, passkey or "
                  "social login removes its SMS fee, so changing that requirement or limiting OTP to first sign-in is the largest saving"),
    ("Email", "send fewer or digest e-mails, or cap the list size at launch"),
    ("Stored data", "shorten retention, archive cold partitions or old files to cheaper object storage, and compress or roll up raw rows"),
    ("Second app instance", "drop the second instance until the availability target is enforced"),
    ("Hosting", "start on the entry tier and scale on measured load"),
    ("Database", "start on the smallest instance tier that meets the load and scale on measured use; a standby doubles this line, so add it only when an availability target requires it"),
    ("ml", "cap questions per user, cache repeated answers or use a smaller model"),
    ("Video egress", "lower the bitrate ladder and cache aggressively at the CDN"),
    ("Indicative hardware", "reuse servers you already own; the line is new purchases only"),
)
DEFAULT_CUT_HINT = "defer it, or replace it with a free-tier or self-run option"


def desc_text(ctx):
    return (ctx["req"].get("project.description") or "").lower()


# ---------------------------------------------------------------- (e) peak concurrency
def derived_peak(users, req, typ):
    """Peak concurrent users when scale.peak_concurrent_users is absent: users x a documented fraction, never above users.
    Returns (peak, fraction, text). The default fraction keeps the earlier 10% rule; a stated monthly audience lowers it (a monthly
    audience is rarely online together): 5% for an interactive product, 2% for a read-mostly one."""
    text = (req.get("project.description") or "").lower()
    frac, why = PEAK_FRACTION["default"], "10% of users_12_months"
    if MONTHLY_AUDIENCE_RX.search(text):
        interactive = bool(req.get("requirements.realtime")) or req.get("scale.workload") == "write_heavy" or typ in ("gaming", "realtime_collab", "social")
        key = "monthly_audience" if interactive else "monthly_audience_read_mostly"
        frac = PEAK_FRACTION[key]
        why = (f"{frac:.0%} of users_12_months (planning heuristic: the description counts a monthly audience, and a monthly audience "
               f"is rarely online at once; {'interactive product' if interactive else 'read-mostly product'})")
    peak = min(users, max(1, int(users * frac + 1e-9)))
    return peak, frac, why


# ---------------------------------------------------------------- (a) stored data
def stored_data_split(ctx, obj, db_managed):
    """Rates for the 'Stored data' line as ([(gb, (lo_rate, hi_rate), label)], split). Without a storage layer the volume sits in
    the managed database at SSD rates. With one, the volume is files at object rates, except for a write-heavy IoT workload, where
    TS_ROWS_SHARE of it is append-only readings in the database. Other write-heavy types (analytics, time-series rule) that also
    use object storage keep object rates: the storage layer exists because files do, and the description does not say what share is rows."""
    gb = ctx["data_gb"]
    if not obj:
        return [(gb, DB_SSD_RATE, "database SSD")], False
    if ctx["req"]["scale.workload"] == "write_heavy" and ctx["type"] == "iot" and db_managed:
        r = gb * TS_ROWS_SHARE
        return [(r, DB_SSD_RATE, "append-only rows in the managed database"), (gb - r, OBJ_RATE, "files in object storage")], True
    return [(gb, OBJ_RATE, "object storage")], False


# ---------------------------------------------------------------- IoT ingestion
# i2 (planning heuristic): device nouns the description may count. Pass 1 holds the classic IoT nouns; pass 2 (vehicles and other
# ambiguous nouns such as cars, vans, cameras) is read only when pass 1 finds nothing, so "50,000 cars a day using 800 sensors" counts 800.
DEVICE_NOUNS_1 = r"sensors?|devices?|meters?|trackers?|gateways?|machines?|vehicles?|sites?|stations?|inverters?|pumps?|panels?|chargers?|lamps?"
DEVICE_NOUNS_2 = r"trucks?|vans?|cars?|buses|taxis|cabs|bikes?|scooters?|beacons?|cameras?|rigs?"
_PER_PERIOD = r"(?!\s+(?:a|per|each)\s+(?:day|hour|week|month))"


def device_match(d):
    """Regex match (group 1 number, group 2 unit) of the device count in a lower-cased description, or None."""
    for nouns in (DEVICE_NOUNS_1, DEVICE_NOUNS_2):
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakh|million|m)?\s+(?:\w+\s+){0,2}(?:" + nouns + r")\b" + _PER_PERIOD, d)
        if m:
            return m
    return None


def device_count(desc):
    d = (desc or "").lower()
    m = device_match(d)
    if not m:
        return None
    unit = {None: 1, "k": 1e3, "thousand": 1e3, "lakh": 1e5, "million": 1e6, "m": 1e6}[m.group(2)]
    n = float(m.group(1).replace(",", "")) * unit
    return int(n) if n >= 1 else None


def iot_hub_cost(msgs_per_month):
    """Cheapest Standard-tier combination of one tier for the daily message volume: (tier name, units, USD per month)."""
    per_day = msgs_per_month / 30
    best = None
    for name, usd, cap in IOT_HUB_TIERS:
        units = max(1, math.ceil(per_day / cap))
        if best is None or units * usd < best[2]:
            best = (name, units, units * usd)
    return best


def broker_nodes(per_sec):
    return max(1, math.ceil(per_sec / BROKER_NODE_MSGS_PER_S))


# ---------------------------------------------------------------- (b) ML training
def training_cost(ctx, table_cost, rate=None):
    """Per-tier [lo, hi] for managed training: the tier table, raised to a floor from the stored data volume when the volume is large.
    Returns (cost, floor or None)."""
    gb = ctx["data_gb"]
    if gb < TRAIN_FLOOR_GB:
        return table_cost, None
    rate = rate or TRAIN_GPU_RATE
    flo = round(gb * TRAIN_GPU_HOURS_PER_GB[0] * rate)
    fhi = round(gb * TRAIN_GPU_HOURS_PER_GB[1] * rate)
    return [[max(lo, flo), max(hi, fhi)] for lo, hi in table_cost], (flo, fhi)


def training_open_ended(ctx):
    """True when ML training runs on a data volume big enough that the training bill is not bounded by the app's size, so a
    'budget far above need' remark would contradict the volume."""
    return ctx["req"]["requirements.ml_features"] == "training" and ctx["data_gb"] >= TRAIN_FLOOR_GB


# ---------------------------------------------------------------- (c) on-premises hardware
def onprem_hardware(ctx, supporting, ha):
    """Indicative amortised hardware as (lo, hi, parts) USD per month; parts is the human list of what was counted."""
    n, ulo, uhi = ONPREM_SERVER[ctx["tier"]]
    parts = [f"{n} app/database server{'s' if n > 1 else ''} at ${ulo:,}-{uhi:,} each"]
    lo, hi = n * ulo, n * uhi
    if ha:
        lo, hi = lo + ulo, hi + uhi
        parts.append("one standby server for the availability target")
    if ctx["size"] > TEAM_SHARES_APP_SERVER:
        lo, hi = lo + ONPREM_TOOLING_NODE[0], hi + ONPREM_TOOLING_NODE[1]
        parts.append(f"one tooling server for CI and monitoring (team of {ctx['size']})")
    ml = ctx["req"]["requirements.ml_features"]
    if ml in ("training", "llm_rag") or any(s["layer"] == "ml" and "GPU" in s["choice"] for s in supporting):
        lo, hi = lo + ONPREM_GPU_NODE[0], hi + ONPREM_GPU_NODE[1]
        parts.append(f"one GPU server at ${ONPREM_GPU_NODE[0]:,}-{ONPREM_GPU_NODE[1]:,}")
    tb = ctx["data_gb"] / 1000
    if ctx["data_gb"] > 500:
        lo, hi = lo + tb * ONPREM_DISK_PER_TB[0], hi + tb * ONPREM_DISK_PER_TB[1]
        parts.append(f"~{tb:,.1f} TB of storage at ${ONPREM_DISK_PER_TB[0]}-{ONPREM_DISK_PER_TB[1]}/TB")
    return lo / ONPREM_AMORTISE_MONTHS, hi / ONPREM_AMORTISE_MONTHS * (1 + ONPREM_RUNNING_SHARE), parts


# ---------------------------------------------------------------- (d) per-message lines
def email_recipients(ctx):
    """List size from the description ('email list will be about 20,000', '5,000 subscribers'); else every user."""
    t = desc_text(ctx)
    for rx in (r"(?:e-?mail|mailing)\s+list[^.]{0,40}?(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|million|m)?\b",
               r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|million|m)?\s+(?:newsletter\s+)?(?:subscribers|recipients)\b"):
        m = re.search(rx, t)
        if m:
            n = float(m.group(1).replace(",", "")) * {None: 1, "k": 1e3, "thousand": 1e3, "million": 1e6, "m": 1e6}[m.group(2)]
            if n >= 1:
                return int(n), True
    return ctx["users"], False


def email_line(ctx):
    """(lo, hi, text) for managed e-mail sends: recipients x sends x price per thousand (planning estimate)."""
    n, stated = email_recipients(ctx)
    slo, shi = EMAIL_SENDS_PER_RECIPIENT_MONTH
    plo, phi = EMAIL_USD_PER_THOUSAND
    lo, hi = n * slo * plo / 1000, n * shi * phi / 1000
    who = f"{n:,} recipients (the list size in project.description)" if stated else f"{n:,} users (no list size stated, so every user)"
    return lo, hi, (f"E-mail delivery: {who} x {slo}-{shi} e-mails a month at ${plo:.2f}-{phi:.2f} per 1,000 sent = {{r}} "
                    "(planning estimate, not a vendor quote: no provider price is in the knowledge base).")


def llm_usage(ctx):
    """(lo, hi) USD per month for model tokens: users x questions x tokens x price. Planning estimate."""
    u = ctx["users"]
    qlo, qhi = LLM_QUESTIONS_PER_USER_MONTH
    tin, tout = LLM_TOKENS_PER_QUESTION
    lo = u * qlo * (tin * LLM_USD_PER_MILLION_IN[0] + tout * LLM_USD_PER_MILLION_OUT[0]) / 1e6
    hi = u * qhi * (tin * LLM_USD_PER_MILLION_IN[1] + tout * LLM_USD_PER_MILLION_OUT[1]) / 1e6
    return lo, hi


def llm_basis(ctx, rag=True):
    qlo, qhi = LLM_QUESTIONS_PER_USER_MONTH
    tin, tout = LLM_TOKENS_PER_QUESTION
    return (f" Token basis (planning estimate, not a vendor quote): {ctx['users']:,} users x {qlo}-{qhi} questions a month x about "
            f"{tin:,} input + {tout} output tokens at ${LLM_USD_PER_MILLION_IN[0]}-{LLM_USD_PER_MILLION_IN[1]} / "
            f"${LLM_USD_PER_MILLION_OUT[0]}-{LLM_USD_PER_MILLION_OUT[1]} per million input / output tokens; the line is the larger of this "
            "and the tier table" + (", which also covers the vector store." if rag else "."))


# ---------------------------------------------------------------- budget explanation (explain-only)
def cut_hint(label):
    for key, hint in CUT_HINTS:
        if label.startswith(key) or label.lower().startswith(key.lower()):
            return hint
    return DEFAULT_CUT_HINT


def dominant_text(items, budget, total_hi):
    """Which line dominates the band and what to cut. items: [(hi, lo, label)] sorted by hi descending. '' when there is nothing to say."""
    live = [i for i in items if i[0] > 0]
    if not live:
        return ""
    hi, lo, label = live[0]
    share = f", {hi / total_hi:.0%} of the upper bound" if total_hi else ""
    return (f" Dominant line: {label} (${lo:,}-{hi:,} a month{share}). What to cut: {cut_hint(label)}. Nothing was removed from the stack; "
            "this only says where the money goes.")


def over_multiple_note(items, budget, band_min=None):
    """Explicit note for each single line above SINGLE_LINE_BUDGET_MULTIPLE x budget (budget > 0), largest first; '' if none."""
    if budget <= 0:
        return ""
    cap = SINGLE_LINE_BUDGET_MULTIPLE * budget
    bits = []
    for hi, lo, label in sorted(items, key=lambda i: -i[0]):
        if lo > cap:
            bits.append(f"{label} alone (${lo:,}-{hi:,} a month) is above {SINGLE_LINE_BUDGET_MULTIPLE}x the budget even at its lower bound")
        elif hi > cap:
            bits.append(f"{label} alone (up to ${hi:,} a month) is above {SINGLE_LINE_BUDGET_MULTIPLE}x the budget at its upper bound")
    if not bits:
        return ""
    # p5 item 5: 'no scope cut fits' only when a flagged line's own lower bound is above the whole budget
    floor = max(lo for hi, lo, label in items if hi > cap)
    tail = ("no scope cut that keeps this line fits the budget." if floor > budget else
            "at its lower bound the line is within the budget, so the budget holds only while usage stays near the low end of the band."
            if band_min is None or band_min <= budget else
            "at its lower bound the line is within the budget, but the band minimum is not, so other lines must shrink as well.")
    return " Sanity check: " + "; ".join(bits[:2]) + ". The band keeps the figure as the estimate; " + tail
