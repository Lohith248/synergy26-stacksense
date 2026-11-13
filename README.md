# StackSense — deterministic tech-stack recommendation engine

StackSense reads a project scenario in the official StackSense JSON format and recommends four core layers: frontend, backend, database and hosting. It adds supporting services such as auth, storage, search, realtime, cache, queue, payments, CDN, ML, CI/CD and observability where the inputs call for them. Each choice comes with:

- a scenario-specific justification;
- the input fields that drove it (`driven_by`);
- real alternatives and the reason each lost;
- trade-offs;
- an order-of-magnitude monthly cost band with its assumptions;
- severity-coded warnings for conflicts and risks;
- for each core layer, **what would change the choice**: single-field edits, found by re-running the engine, that would flip that layer; for backend, database and hosting also the score margin over the runner-up.

Hard constraints (cloud preference, deployment model, data residency, compliance) filter candidates before any scoring, so they are never broken silently. Selection is done entirely by rules and weighted scoring over a cited knowledge base. **No LLM is used anywhere.** The engine is pure Python standard library, so there is nothing to install beyond Python.

## Validation at a glance

| Check | Result |
|---|---|
| Unit and acceptance tests (`python -I -m unittest discover -s tests`) | 481 tests OK (17 skip cleanly when the optional `research/` folder is absent) |
| Public scenarios P1-P6 | outputs in `outputs/` reproduce byte-for-byte |
| Output contract (`tools/check_contract.py`) | PASS 6/6 |
| One-field perturbation sweep (`tools/perturb.py`) | 1,087 edits, 0 crashes, 0 violations |

These are development checks, not a measure of accuracy on unseen scenarios.

## Architecture and data flow

```
 scenario.json (object or array)
        │
        ▼
 engine/load.py      strict JSON: rejects NaN/Infinity/overflow, duplicate keys; tolerates UTF-8 BOM
        │
        ▼
 engine/validate.py  Section 3.1 schema: types, enums, ranges, required fields; applies documented
        │            defaults and records each one in `assumptions`  ──► invalid_input (all errors, stack=null)
        ▼
 engine/context.py   derived signals: scale tier, team skill factor, effective residency,
        │            deterministic description rules, existing-system + lifecycle matching
        ▼
 engine/recommend.py hard-vs-hard conflicts ──► infeasible (critical warnings, stack=null)
        │
        ├─ engine/select.py   per layer: hard filters (exclusion reason kept) → additive explained
        │                     scoring (priority weights × KB ratings, team languages, experience,
        │                     ops burden, budget, timeline, availability, latency, existing systems)
        │                     order: backend → hosting → database (provider variant) → frontend (web/mobile)
        ├─ engine/services.py supporting services inside the same constraint envelope
        ├─ cost band, contradiction/compliance/lifecycle warnings, architecture style, summary
        ▼
 engine/counterfactual.py  re-runs the engine on a fixed list of one-field edits → what_would_change per layer
        ▼
 Section 4 JSON  ──►  outputs/<scenario_id>_output.json   (+ --explain view, or the optional web UI)

 kb/technologies.json  products, ratings, regions, cost bands, lifecycle table, existing-system patterns
 kb/sources.json       every cited source (official URL, status, research claim ids)
```

| Module | Responsibility |
|---|---|
| `stacksense.py` | Command line: `run` (file or array to output files), `interactive` (guided input of every standard field), `--explain`, `--no-llm` |
| `engine/load.py` | Safe JSON parsing; one output per scenario; bad array elements do not stop the others |
| `engine/validate.py` | Field-level validation (`{field, message}` for every problem); defaults recorded as assumptions |
| `engine/context.py` | Derived facts: scale tier from users and concurrency (people, never treated as RPS), description flags, existing systems |
| `engine/select.py` | Hard filtering and explained scoring for the core layers; ties broken by product id |
| `engine/services.py` | Supporting services (auth, storage, search, realtime, cache, queue, payments, CDN, ML, CI/CD, observability, offline sync, integrations) |
| `engine/recommend.py` | Orchestration, conflicts, warnings, cost band, architecture style, summary |
| `engine/rightsize.py` | Right-sizing gates (D13): thresholds, predicates for game servers, warehouse, CDN audience and CRDT, the `SERVICE_NOT_ADDED` text, the deferrable list |
| `engine/domains.py` | Project-type rules: dedicated game servers, IoT ingestion and time-series storage, analytics warehouse + BI, API gateways |
| `engine/counterfactual.py` | Per-layer `what_would_change`: ordered one-field probes (priorities, soft requirements, numbers, constraints), measured by re-running the engine |
| `engine/web.py`, `web/index.html` | Optional local web UI (`serve`): standard-library HTTP server on 127.0.0.1 and one self-contained page |
| `engine/kb.py` | Loads the knowledge base; an unknown source id fails loudly |
| `tools/check_contract.py` | Independent checker of the Section 4 output contract |
| `tools/perturb.py` | Robustness sweep: 997 one-field edits across P1-P6; reports crashes, contract/hard-constraint violations and which layers move |
| `tests/` | stdlib `unittest` tests: boundary set B01-B34, KB lint, deprecated-product guard, 96 hard-constraint mutations, interactive mode, improvement acceptance tests (language fit, serverless fit, static hosts, native mobile, low budget, relaxed labelling, explanations, KB breadth, counterfactuals, web UI, traffic shape, domain rules for games/IoT/analytics/API/B2B SSO, extra inputs) |

## Technology used

- Python 3.10+, standard library only: `json`, `argparse`, `re`, `http.server` (optional UI), `unittest`. Tested on CPython 3.10.11 and 3.13.3 on Windows 11. Python 3.10 reached end of life on 2026-10-01, so **3.11 or newer is recommended**.
- No third-party packages, no network access, no API keys.

## Prerequisites

- Python 3.10 or newer (`python --version`). On macOS/Linux use `python3` if `python` is not Python 3.
- Any OS: Windows, macOS or Linux. No Docker, Node or database needed.

## Setup and run (about 1 minute)

```bash
git clone <this repository> stacksense && cd stacksense
```

If you received a zip instead, unzip it and `cd` into `source/`. There is nothing to install.

```bash
python stacksense.py run scenarios/stacksense_public_scenarios.json --out outputs
```

This writes `outputs/P1_output.json` … `outputs/P6_output.json`, one per scenario in the array.

## Run a scenario file and find the output

```bash
python stacksense.py run path/to/scenario.json --out outputs --explain
```

- Input may be a single scenario object or an array of them.
- **Input notation (D14):** values must have the types in the statement; enum values are lower-case strings exactly as written. Exactly two lossless notations are also read, each recorded as a line in `assumptions` and one `INPUT_COERCED` info warning (listing the fields): an integer-valued number for an integer field (`30000.0` is read as `30000`, `3e4` too), and a number equal to a listed `requirements.availability` value (`99.9` is read as `"99.9"`; likewise `99`, `99.95`, `99.99`). Nothing else is coerced: fractions (`2.5`), numbers as strings (`"150"`), other case (`"AWS"`), unknown enum values, booleans as strings (`"true"`) and lists of the wrong type stay `invalid_input`. A number that equals no availability value is rejected with a message naming the accepted values. No coercion note appears on `invalid_input`.
- Output is written to `outputs/<scenario_id>_output.json`, or `scenario_output.json` when there is no id.
- `--explain` also prints a readable explanation to the terminal.
- `--adr` also writes `outputs/<scenario_id>_adr.md`: one Architecture Decision Record per core layer (context, decision, options table, consequences).
- The exit code is 1 if any scenario is `invalid_input`, otherwise 0.
- Files are written atomically, so a crash never leaves a half-written output.

To enter a scenario by answering prompts for every standard field, use interactive mode. It saves the input file and then evaluates it:

```bash
python stacksense.py interactive --out outputs
```

### Optional web UI

```bash
python stacksense.py serve
```

Open http://127.0.0.1:8765/ in a browser. The page has a form for every standard field (required ones marked), a JSON tab, a sample loader (P1-P6, E1-E9, X1 and the hidden-like probes), file import, a Recommend button and export of the input and output JSON. It calls the same engine as the CLI, binds to 127.0.0.1 only, loads nothing from the internet and uses no LLM. Use `--port` to change the port; stop it with Ctrl+C.

More probes for project types the public set does not cover are in `scenarios/hidden_like/`. H01-H12 are author-made (gaming, IoT, analytics, AI/RAG, healthtech, API platform, B2B SaaS, seasonal e-commerce, zero-budget students, social, desktop, seasonal content; regenerate with `python tools/make_hidden_like.py`). H13 onward are blind probes: their expected outcomes in `tests/test_oracle.py` were written before the engine was run on them.

Edge-case examples for every Section 6 category are in `scenarios/edge_cases/` (E1-E9):

```bash
python stacksense.py run scenarios/edge_cases/E7_air_gapped.json --explain
```

## Switching off LLM features

The engine contains no LLM calls, so the result is always the same with or without the switch. For the judges' LLM-off test, both of these are accepted and documented:

```bash
python stacksense.py run scenarios/stacksense_public_scenarios.json --out outputs --no-llm
```

You can also set the environment variable `STACKSENSE_LLM=off` (see `.env.example`). The engine reads no environment variables, so it has no effect. The test suite blocks sockets and verifies byte-identical outputs across processes and hash seeds.

## Verify

```bash
python -I -m unittest discover -s tests -v
```

```bash
python tools/check_contract.py outputs/P1_output.json outputs/P2_output.json outputs/P3_output.json outputs/P4_output.json outputs/P5_output.json outputs/P6_output.json
```

Optional robustness sweep (about 10 s):

```bash
python tools/perturb.py
```

## Extra inputs (optional)

The engine accepts every standard field and works on files that contain only those. Seven optional extra fields can be added inside the usual groups; when absent they are ignored and nothing is assumed. Invalid values are reported in `validation_errors` like any other field. Interactive mode and the web UI ask for them as optional.

| Field | Values | What it changes |
|---|---|---|
| `scale.peak_rps` | integer ≥ 0 | Request rate is better sizing evidence than people counts. The scale tier becomes the higher of the people-based and rate-based tiers (≤20, ≤200, ≤2,000, more requests/s), which moves plans, caches and the cost band. |
| `scale.geo_spread` | `single_region`, `multi_region`, `global` | Distant users: adds a CDN even for small apps and a `GLOBAL_USERS_ONE_REGION` warning with the latency cost and what to do within the residency constraint. |
| `team.hiring_languages` | list of strings | Languages the team will hire for count at half the weight of languages it already writes (for example, hiring Kotlin developers moves P6's Android app to native Kotlin). |
| `infrastructure.lock_in_tolerance` | `low`, `medium`, `high` | `low` penalises provider-specific runtimes and data stores (Lambda, DynamoDB, Firestore, Cosmos DB, Cognito) and favours portable containers and open engines. |
| `requirements.rto_minutes` | integer ≥ 0 | Recovery time objective. Under 60 minutes adds a zone-redundant database standby with automatic failover and a second app instance (cost band rises); under 5 minutes adds `RTO_BELOW_FAILOVER`. |
| `infrastructure.residency_country` | `australia`, `singapore`, `japan`, `south_korea`, `indonesia`, `united_kingdom`, `canada`, `brazil`, `uae`, `saudi_arabia`, `qatar`, `israel`, `south_africa`, `switzerland`, `mexico` | Only with `data_residency: "other"` (ignored with a warning otherwise). Every data store uses that country's region from `../research/R15-regions-other.md`; providers without one are excluded, and an explicit `cloud_preference` with no region there is `infeasible`. Without this field the engine reads the country from `project.description` (country names, demonyms, major cities; one jurisdiction only, `RESIDENCY_FROM_DESCRIPTION` warning). Regional words (Gulf, APAC, Europe...) or two countries keep the critical `RESIDENCY_UNSPECIFIED` and list the plausible countries (D12). |
| `requirements.rpo_minutes` | integer ≥ 0 | Recovery point objective. Under 5 minutes adds the same standby on a managed database, or `RPO_NEEDS_REPLICATION` on a self-hosted one. The 60/5-minute thresholds are planning heuristics, not provider guarantees. |

Example: `scenarios/extras/X1_p6_with_extras.json` (P6 plus the first four). The counterfactual probes include `lock_in_tolerance` and `geo_spread`, so `what_would_change` shows when they matter.

## Output conventions (documented interpretations)

- **`invalid_input`:** every detected problem is listed. `stack` is `null` and the cost band is `null/null`, so it cannot be mistaken for a free stack.
- **`infeasible`:** used only when hard constraints contradict each other, for example `cloud_preference: none` with a cloud deployment, an explicit cloud provider with on-premise, or `rbi_localisation` with EU/US residency. It comes with critical warnings naming both fields, and `stack` is `null`.
- **Soft conflicts:** budget, timeline and team conflicts give `ok_with_warnings` with a full stack and named warnings, never a silent violation.
- **`cloud_preference: none`** means no public cloud.
- **`on_premise` and `air_gapped`** both allow only self-hostable components, with no SaaS or CDN. Unavoidable external dependencies (a payment gateway, an existing cloud identity provider, an SMS carrier link) are kept only with an explicit warning.
- **Extra output fields** (Section 4 allows them): each core component has `kb_id` and `what_would_change` (up to three distinct outcomes, each with the first one-field edit that causes it and up to three other edits that lead there; falling back to the nearest single-priority flip from the stability grid, and empty when neither flips it), `stability` (share of a fixed grid of 45-54 priority-weight vectors that keeps the choice, with the nearest single-priority flip point), `confidence` (`low` if stability < 0.7 or margin < 1.0, `high` if stability ≥ 0.9 and margin ≥ 2.0, else `medium`, with the numbers in `basis`; the frontend has no margin, so its label uses stability alone) and `contrast` ("X rather than Y. Reason. Trade-off accepted: ..."). Backend, database and hosting also carry `score_margin` (gap to the runner-up; small means a near-tie) and `pareto` (whether another eligible option rates at least as well on all six priorities, and if so what the choice wins on, usually team fit or an existing system). The frontend can combine web, mobile and desktop picks, so it has neither. Components also carry `deployment`, `provider`, `data_bearing`, `data_location` and `sources`.
- **Relaxed recommendations:** when a critical conflict remains (for example a huge scale on a $0 budget), the summary starts with "Relaxed recommendation" and one `Relaxed:` assumption names each relaxed field.
- **Knowledge-base gaps are warnings (D15):** `PAYMENT_DATA_LOCATION` and `LLM_REGION_CHECK` are `warning`s that name the verified mechanism (for Stripe and EU residency: the EEA entity, the EU-US Data Privacy Framework and Standard Contractual Clauses) or say "not confirmed in the knowledge base", and give the next action. Only conflicts the engine can prove are `critical`, and only those produce `Relaxed:` assumptions.
- **Description rules (D7):** fixed, deterministic keyword rules on `project.description` shape supporting services and warnings, for example UPI, EMI, payouts, ledger, KYC, offline sync and Microsoft 365. Four signals also adjust core scores: ledger (database), Markdown (static frontend), internal-only (SPA frontend) and low-end devices (mobile frontend); each appears in `driven_by` as `project.description`.

### Right-sizing (D13)

A supporting service that is sized for scale or latency the input does not state is not added, and the output says so: the replacing component lists it as an alternative with the input values and the condition that would add it, and a `SERVICE_NOT_ADDED` info warning repeats that. Core layers are never affected. The thresholds live in `engine/rightsize.py` (`THRESHOLDS`) and are planning heuristics, not vendor limits.

| Service | Added when | Otherwise |
|---|---|---|
| Dedicated game servers | type `gaming`, `realtime`, a backend, no turn-based wording, and a fast-action genre word in the description or `requirements.p95_latency_ms` <= 100 | live updates over WebSockets from the backend |
| Analytics warehouse | type `data_analytics` with `scale.data_volume_gb_12_months` >= 100 (inferred from analytics words and `read_heavy`: >= 200) | BI dashboards read the application database |
| CDN | a public audience: not "used only by employees"; an `internal_tool` only with `seo_critical` or multi-region/global users | none (warning only) |
| CRDT sync server | the description names simultaneous editing of one document, note or canvas (the type `realtime_collab` alone is not enough; never for games) | native realtime of the backend |
| Dedicated search engine | scale tier above 1 (Supabase counts as PostgreSQL for the built-in full-text search) | database full-text search |

When the estimated minimum exceeds the budget, the `BUDGET_EXCEEDED` message also lists up to three services that could wait (managed cache, dedicated search, CDN without SEO/geo need, warehouse, game servers, the extra Node sync instance) and the minimum without them. This is text only; nothing is removed.

### Cost realism (D17)

The band is the sum of printed lines and every figure that is not in the knowledge base is labelled `planning estimate` or `planning heuristic`. Per-message services scale with users x a stated usage assumption (phone OTP logins, e-mail sends per recipient, LLM questions and tokens); managed ML training has a floor from `scale.data_volume_gb_12_months`; on-premise and air-gapped outputs add one `Hardware (indicative, not a quote)` line (servers per scale tier amortised over 36 months); a device count in the description sizes IoT ingestion; and a peak concurrency derived from a stated monthly audience uses a documented 5% or 2% fraction, never more than the users. When the budget is far below the minimum, `BUDGET_EXCEEDED` names the dominant line and what to cut (explain-only: nothing is removed); a single line above 10 times the budget gets a `Sanity check` sentence. All tables are in `engine/costreal.py`.

## Project structure

```
source/
├── stacksense.py            CLI entry point
├── engine/                  validation, context, selection, services, orchestration
├── kb/technologies.json     knowledge base (as_of 2026-11-11)
├── kb/sources.json          cited sources with verification status
├── scenarios/               official public scenarios, edge_cases/E1-E9, hidden_like/ probes, extras/X1
├── outputs/                 P1-P6 outputs produced by this engine
├── web/index.html           optional local UI page (served by `serve`)
├── tools/check_contract.py  output contract checker
├── tools/perturb.py         one-field robustness sweep
├── tests/                   boundary, KB, oracle, fields-sweep, no-LLM guard and round tests
├── DECISIONS.md             participant-owned design decisions
└── README.md
```

## Credits

- **Third-party libraries:** none. The engine uses only the Python standard library (PSF licence).
- **Datasets:** the organiser's `stacksense_public_scenarios.json`. No external datasets.
- **APIs:** none called at runtime.
- **Knowledge-base sources:** official vendor documentation, pricing and lifecycle pages and regulator pages. All are listed in `kb/sources.json` with URL, access date (2026-11-11) and verification status, and they are cited in the report.
- **AI assistance:** Claude Code (Anthropic) and OpenAI Codex were used as coding and review assistants; a GPT-6.1 Terra research agent checked primary-source text during the 11 November review. It is declared in the report's AI-assistance section. Design decisions are recorded in `DECISIONS.md`.

Knowledge-base ratings: the 1-5 values in `kb/technologies.json` are author judgement, not measurements. `kb/RATING-RUBRIC.md` defines what 1, 3 and 5 mean for each of the six criteria, the consistency rules that tie a rating to other fields of its record, the public data anchors (with URLs, access date and what could not be verified) and which ratings are rule-checked versus judgement-only. `kb/RATING-AUDIT.md` lists the ratings that currently contradict it; none has been changed.

Review limitations: numeric inputs must fit the finite floating-point range used by sizing calculations. Duplicate sanitized output filenames are rejected before any output is replaced. Unresolved residency and retained on-premises SaaS dependencies carry critical warnings. Source verification labels reflect earlier research; the 11 November Codex web review could not independently inspect rendered vendor pages.
