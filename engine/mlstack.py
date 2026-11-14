"""p1: ML / LLM knowledge rules. Reads kb/ml.json (serving engines, vector stores, tracking, GPU instance rows).

Tells a self-hosted LLM from classical tabular ML and from edge computer vision, sizes a GPU class from the model size the
description gives, and prices a GPU that serves all month at HOURS_PER_MONTH x the KB rate. Engine-only: no network, stdlib only.
"""
import math
import re
from . import descflags as dfl
from .kb import ML

# ---------------------------------------------------------------- planning heuristics (p1), one place
# Wording that the product runs a large language model (read outside negated clauses).
LLM_RX = (r"\bllms?\b|\blarge language models?\b|\blanguage models?\b|\bopen[- ]?weights?\b|\bopen[- ]weight models?\b|\bhugging ?face\b"
          r"|\bllama\b|\bmistral\b|\bmixtral\b|\bqwen\w*|\bgemma\b|\bdeepseek\b|\bopenai[- ]compatible\b|\bvllm\b|\bollama\b")
# Wording that the model runs on the team's own machines: an open-weight model family, a self-hosting verb, a serving engine.
SELF_HOST_RX = (r"\bopen[- ]?weights?\b|\bopen[- ]weight\b|\bhugging ?face\b|\bllama\b|\bmistral\b|\bmixtral\b|\bqwen\w*|\bgemma\b|\bdeepseek\b"
                r"|\bvllm\b|\bollama\b|\bself[- ]host\w*\s+(?:\w+\s+){0,2}(?:llms?|models?)\b|\b(?:our|its|their) own (?:gpus?|gpu servers?)\b")
# Data must stay on the team's machines (read with re.search: the phrase carries its own negation, so first_live would skip it).
NO_LEAVE_RX = (r"\b(?:prompts?|data|queries|questions|documents?|text)\b(?:\W+\w+){0,4}?\W+(?:must|may|can|should|will|shall)\s+(?:not|never)\s+leave\b"
               r"|\bno\s+(?:prompts?|data|queries|questions|documents?|text)\s+(?:may|must|can|should|will|shall)\s+leave\b|\bnever\s+leaves?\b")
# A no-leave phrase followed by a place ("never leaves the EU", "must not leave India") is data residency, not a self-host signal.
RESIDENCY_PLACE_RX = (r"\s+(?:the\s+)?(?:eu|eea|european union|europe|india|us|usa|united states|uk|united kingdom|germany|france|canada|australia"
                      r"|japan|singapore|brazil|country|region|jurisdiction|continent)")
# A no-leave phrase that names the team's own machines ("our servers", "the premises", "our AWS account") is a self-host signal even
# when a hosted API is also named; a bare no-leave phrase ("data never leaves") counts only when no hosted API is named.
OWN_PREMISES_RX = (r"\s+(?:the\s+|our\s+|its\s+|their\s+|your\s+)?(?:own\s+)?(?:\w+\s+)?(?:servers?|premises|network|infrastructure|machines?"
                   r"|vms?|data ?cent(?:er|re)s?|building|firewall|environment|account|vpc|hardware|walls)")
# A hosted model API named outright: the hosted route stays unless the description also says data must not leave.
HOSTED_LLM_RX = (r"\bopenai api\b|\bchatgpt\b|\bgpt-?\d\w*|\bclaude\b|\bgemini\b|\bbedrock\b|\bazure openai\b|\bvertex ai\b|\bhosted (?:llm|model|api)s?\b")
# Model size in billions of parameters ("Llama 3.1 8B", "a 70b model", "13 billion parameters").
MODEL_SIZE_RX = r"(?<![\w.$])(\d{1,3}(?:\.\d)?)\s?b\b(?![-/]\w)|(?<![\w.])(\d{1,3}(?:\.\d)?)\s*billion[- ]param\w*"
BYTES_PER_PARAM = 2         # FP16/BF16 weights
VRAM_OVERHEAD = 1.2         # KV cache and runtime memory on top of the weights
DEFAULT_PARAMS_B = 8        # assumed model size when the description names none (a 7-8B instruct model)
SERVING_REPLICAS = (1, 2)   # GPU instances serving all month: one, up to two for peak throughput or a standby
HOURS_PER_MONTH = 730
FINE_TUNE_GPU_HOURS = (40, 200)  # GPU-hours a month of LoRA fine-tuning runs on one GPU of the sized class
FULL_FINE_TUNE_VRAM_FACTOR = 4   # full fine-tuning (weights + gradients + optimizer state) needs about 4x the serving memory
FINE_TUNE_RX = r"\bfine[- ]?tun\w*|\blora\b|\bqlora\b|\badapters?\b"
LORA_RX = r"\blora\b|\bqlora\b|\badapters?\b|\bpeft\b"
TRACKING_RX = (r"\btrack\w*\s+(?:\w+\s+){0,2}experiments?\b|\bexperiment[- ]tracking\b|\bexperiments?\b|\bversion\w*\s+(?:\w+\s+){0,3}(?:datasets?|data|models?)\b"
               r"|\b(?:model|dataset|data)\s+(?:versioning|lineage|registry)\b|\bmodel registry\b|\breproducib\w*")
# Computer vision at the edge: a vision word and an edge-device word (both read outside negated clauses).
VISION_RX = (r"\bcomputer vision\b|\bcameras?\b|\bvideo analytics\b|\bvideo streams?\b|\bobject detection\b|\bdefect detection\b"
             r"|\bdetect\w*\s+(?:\w+\s+){0,2}defects?\b|\bimage (?:classification|recognition|model)s?\b|\bvision models?\b")
EDGE_RX = (r"\bjetson\b|\bedge (?:devices?|boxes|nodes?|gateways?|computers?|inference|ai|gpus?)\b|\bat the edge\b|\bon[- ]device\b"
           r"|\bnext to the (?:line|cameras?|machines?)\b|\bon the (?:line|shop floor|factory floor)\b")
CAMERAS_PER_EDGE_DEVICE = (4, 8)  # cameras one edge GPU device analyses in real time (sizes the device count only)


def _desc(ctx):
    return ctx["req"]["project.description"] or ""


def _live(rx, ctx):
    return dfl.first_live(rx, _desc(ctx))


def self_hosted_llm(ctx, selfh):
    """(True, evidence) when the ml service must be a self-hosted LLM, else (False, None). selfh: the host is a VM or on-premises."""
    ml = ctx["req"]["requirements.ml_features"]
    if ml not in ("inference_api", "llm_rag"):
        return False, None
    desc = _desc(ctx)
    llm = _live(LLM_RX, ctx)
    sh = _live(SELF_HOST_RX, ctx)
    nl = re.search(NO_LEAVE_RX, desc.lower())
    hosted = _live(HOSTED_LLM_RX, ctx)
    if ml == "inference_api" and not llm:
        return False, None  # classical model serving: no LLM wording
    if ctx["self_host_only"]:
        return True, "deployment_model " + ctx["deploy"]
    after = desc.lower()[nl.end():] if nl else ""
    if nl and re.match(RESIDENCY_PLACE_RX, after):
        nl = None  # data residency ("never leaves the EU"): the region rule handles it, the model may still be hosted
    if nl and (re.match(OWN_PREMISES_RX, after) or not hosted):
        return True, dfl._clause(desc, nl.start(), nl.end())
    if hosted:
        return False, None  # an explicitly named hosted model API wins over model-family and bare self-host wording
    if sh:
        return True, sh[1]
    if ml == "llm_rag" and selfh:
        return True, "a self-run VM host"
    return False, None


def model_params_b(ctx):
    """Largest model size (billions of parameters) named in the description, or None."""
    sizes = []
    for m in re.finditer(MODEL_SIZE_RX, _desc(ctx).lower()):
        v = float(m.group(1) or m.group(2))
        if 0.5 <= v <= 1000:
            sizes.append(v)
    return max(sizes) if sizes else None


def vram_need_gb(params_b, full_fine_tune=False):
    need = params_b * BYTES_PER_PARAM * VRAM_OVERHEAD
    return need * (FULL_FINE_TUNE_VRAM_FACTOR if full_fine_tune else 1)


def gpu_pick(provider, need_gb, res_key):
    """The smallest KB GPU instance of the provider with at least need_gb of GPU memory. A provider without rows uses the AWS rows as a
    labelled reference. Returns a dict with the row, its rate, the region the rate is for, and flags for reference rates."""
    table = ML["gpu_instances"]
    ref_provider = provider not in table or provider.startswith("_")
    rows = table["aws" if ref_provider else provider]
    row = next((r for r in rows if r["vram_gb"] >= need_gb), rows[-1])
    key = res_key if res_key in row["usd_per_hour"] else "us"
    return {"row": row, "rate": row["usd_per_hour"][key], "region": row["region"][key], "ref_provider": ref_provider,
            "ref_region": bool(res_key) and key != res_key, "too_big": need_gb > rows[-1]["vram_gb"], "provider": "aws" if ref_provider else provider}


def gpu_label(pick):
    r = pick["row"]
    return f"{r['id']} ({r['gpus']}, {r['vram_gb']} GB GPU memory)"


def rate_text(pick):
    r = pick["row"]
    where = {"aws": "AWS EC2 on-demand", "azure": "Azure Retail Prices API, Linux pay-as-you-go", "gcp": "Google pricing page"}[pick["provider"]]
    txt = f"${pick['rate']:g}/hour for {r['id']} in {pick['region']} ({where}, read 14 Nov 2026" + (f"; {r['rate_basis']})" if r.get("rate_basis") else ")")
    if pick["ref_provider"]:
        txt += "; this hosting provider's GPU price is not in the knowledge base, so the AWS rate is a reference only"
    elif pick["ref_region"]:
        txt += "; the knowledge base has no rate for the residency region, so this rate is a reference"
    return txt


def size_basis(params, need):
    if params:
        return (f"the description names a ~{params:g}B-parameter model: {params:g}B x {BYTES_PER_PARAM} bytes (FP16) x {VRAM_OVERHEAD} for the KV cache "
                f"≈ {need:,.0f} GB of GPU memory (planning heuristic)")
    return (f"no model size is given, so a ~{DEFAULT_PARAMS_B}B model is assumed: {DEFAULT_PARAMS_B}B x {BYTES_PER_PARAM} bytes (FP16) x {VRAM_OVERHEAD} "
            f"for the KV cache ≈ {need:,.0f} GB of GPU memory (planning heuristic)")


def serving_plan(ctx, provider, cloud_bill):
    """GPU sizing for an LLM that serves all month. Returns (label, cost per tier, note, params, need, pick)."""
    params = model_params_b(ctx)
    need = vram_need_gb(params or DEFAULT_PARAMS_B)
    pick = gpu_pick(provider, need, ctx["res_key"])
    basis = size_basis(params, need)
    if not cloud_bill:
        lab = f"an on-premises GPU server with at least {math.ceil(need / 8) * 8} GB of GPU memory"
        return lab, None, basis, params, need, pick
    lo = round(SERVING_REPLICAS[0] * HOURS_PER_MONTH * pick["rate"])
    hi = round(SERVING_REPLICAS[1] * HOURS_PER_MONTH * pick["rate"])
    note = (f" Basis: {basis}; {SERVING_REPLICAS[0]}-{SERVING_REPLICAS[1]} GPU instances x {HOURS_PER_MONTH} hours a month (it serves all month) x "
            f"{rate_text(pick)}. The second instance covers peak throughput or a standby; measure tokens per second on one GPU before buying more.")
    if pick["too_big"]:
        note += " The model is larger than the biggest instance in the knowledge base: plan multi-node serving or a quantised model."
    return gpu_label(pick), [[lo, hi]] * 4, note, params, need, pick


def llm_fine_tune(ctx):
    """Phrase when the training described is LLM fine-tuning (an LLM word and a fine-tuning word), else None."""
    if ctx["req"]["requirements.ml_features"] != "training":
        return None
    ft = _live(FINE_TUNE_RX, ctx)
    return ft[1] if ft and _live(LLM_RX + r"|\b\d{1,3}\s?b\b(?:\W+\w+){0,2}?\W+models?\b", ctx) else None


def fine_tune_plan(ctx, provider, cloud_bill):
    """GPU-hours priced fine-tuning: (label, cost per tier, note, pick)."""
    params = model_params_b(ctx) or DEFAULT_PARAMS_B
    lora = bool(_live(LORA_RX, ctx))
    need = vram_need_gb(params, full_fine_tune=not lora)
    pick = gpu_pick(provider, need, ctx["res_key"])
    method = "LoRA adapters" if lora else "full fine-tuning (about 4x the serving memory)"
    note = (f" Basis: {method} on a ~{params:g}B model needs ≈ {need:,.0f} GB of GPU memory (planning heuristic), so one {gpu_label(pick)}; "
            f"{FINE_TUNE_GPU_HOURS[0]}-{FINE_TUNE_GPU_HOURS[1]} GPU-hours a month of runs (planning heuristic) x {rate_text(pick)}. "
            "A managed training service adds its own fee on top of the machine rate, which the knowledge base does not hold; more runs or bigger "
            "datasets scale this linearly.")
    if not cloud_bill:
        return gpu_label(pick), None, note, pick
    cost = [[round(FINE_TUNE_GPU_HOURS[0] * pick["rate"]), round(FINE_TUNE_GPU_HOURS[1] * pick["rate"])]] * 4
    return gpu_label(pick), cost, note, pick


def wants_tracking(ctx):
    t = _live(TRACKING_RX, ctx)
    return t[1] if t else None


def tracking_row(provider, managed):
    return ML["tracking"][provider] if managed and provider in ML["tracking"] else ML["tracking"]["mlflow"]


def vision_edge(ctx):
    """(vision phrase, edge phrase) when the description puts computer vision on edge devices, else None."""
    v, e = _live(VISION_RX, ctx), _live(EDGE_RX, ctx)
    return (v[0], e[0]) if v and e else None


def edge_devices(cameras):
    """Edge GPU devices for a camera count (planning heuristic range), or None."""
    if not cameras:
        return None
    return math.ceil(cameras / CAMERAS_PER_EDGE_DEVICE[1]), math.ceil(cameras / CAMERAS_PER_EDGE_DEVICE[0])


def src(*ids_lists):
    out = []
    for ids in ids_lists:
        for i in ids:
            if i not in out:
                out.append(i)
    return out
