# StackSense: input and output details

Reference for the details that the main [README](../README.md) leaves out.

## Input notation (D14)

values must have the types in the statement; enum values are lower-case strings exactly as written. Exactly two lossless notations are also read, each recorded as a line in `assumptions` and one `INPUT_COERCED` info warning (listing the fields): an integer-valued number for an integer field (`30000.0` is read as `30000`, `3e4` too), and a number equal to a listed `requirements.availability` value (`99.9` is read as `"99.9"`; likewise `99`, `99.95`, `99.99`). Nothing else is coerced: fractions (`2.5`), numbers as strings (`"150"`), other case (`"AWS"`), unknown enum values, booleans as strings (`"true"`) and lists of the wrong type stay `invalid_input`. A number that equals no availability value is rejected with a message naming the accepted values. No coercion note appears on `invalid_input`.

## Extra inputs (optional)

The engine accepts every standard field and works on files that contain only those. Seven optional extra fields can be added inside the usual groups; when absent they are ignored and nothing is assumed. Invalid values are reported in `validation_errors` like any other field. Interactive mode and the web UI ask for them as optional.

| Field | Values | What it changes |
|---|---|---|
| `scale.peak_rps` | integer ≥ 0 | Request rate is better sizing evidence than people counts. The scale tier becomes the higher of the people-based and rate-based tiers (≤20, ≤200, ≤2,000, more requests/s), which moves plans, caches and the cost band. |
| `scale.geo_spread` | `single_region`, `multi_region`, `global` | Distant users: adds a CDN even for small apps and a `GLOBAL_USERS_ONE_REGION` warning with the latency cost and what to do within the residency constraint. |
| `team.hiring_languages` | list of strings | Languages the team will hire for count at half the weight of languages it already writes (for example, hiring Kotlin developers moves P6's Android app to native Kotlin). |
| `infrastructure.lock_in_tolerance` | `low`, `medium`, `high` | `low` penalises provider-specific runtimes and data stores (Lambda, DynamoDB, Firestore, Cosmos DB, Cognito) and favours portable containers and open engines. |
| `requirements.rto_minutes` | integer ≥ 0 | Recovery time objective. Under 60 minutes adds a zone-redundant database standby with automatic failover and a second app instance (cost band rises); under 5 minutes adds `RTO_BELOW_FAILOVER`. |
| `infrastructure.residency_country` | `australia`, `singapore`, `japan`, `south_korea`, `indonesia`, `united_kingdom`, `canada`, `brazil`, `uae`, `saudi_arabia`, `qatar`, `israel`, `south_africa`, `switzerland`, `mexico` | Only with `data_residency: "other"` (ignored with a warning otherwise). Every data store uses that country's region from the provider region lists in `kb/technologies.json` (official AWS, Azure, Google Cloud and Vercel region pages, read 12 Nov 2026, listed in `kb/sources.json`); providers without one are excluded, and an explicit `cloud_preference` with no region there is `infeasible`. Without this field the engine reads the country from `project.description` (country names, demonyms, major cities; one jurisdiction only, `RESIDENCY_FROM_DESCRIPTION` warning). Regional words (Gulf, APAC, Europe...) or two countries keep the critical `RESIDENCY_UNSPECIFIED` and list the plausible countries (D12). |
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
| Dedicated search engine | scale tier above 1 (Supabase counts as PostgreSQL for the built-in full-text search) and, below the 'large' tier, an engine cheaper than 15% of the budget (D16) | database full-text search |

When the estimated minimum exceeds the budget, the `BUDGET_EXCEEDED` message also lists up to three services that could wait (managed cache, dedicated search, CDN without SEO/geo need, warehouse, game servers, the extra Node sync instance) and the minimum without them. Services the budget guard below already replaced or left out (D16) are not listed again; the listing itself is text only.

### Over-engineering guard (D16)

The statement asks for simple stacks (no microservices or Kubernetes without justification) for high traffic that is really static, small tools and tiny teams. Three input-driven rules, with thresholds in `engine/overeng.py` (`THRESHOLDS`, planning heuristics): (1) a site with no accounts, uploads, realtime, multi-tenancy, ML or stored-user-data wording, whose payments (if any) are a hosted button or link, is a static site with no backend or database, however much traffic it gets; the output quotes the inputs and says when to add a backend; (2) below the 'large' tier, an optional cache, dedicated search engine, managed queue or AWS/Google CDN whose cheapest tier is more than 15% of the budget is replaced by the cheaper option already in the knowledge base (or not added, with `SERVICE_NOT_ADDED`), and the budget warning still appears if the stack does not fit; (3) for a team of 5 or fewer, inference runs in-process where ONNX Runtime documents a binding for the API's language, and on-premises Kubernetes needs a larger team. Complex stacks whose input asks for them (enterprise scale, regulated lending, large teams) are unchanged. DECISIONS.md row D16 records the rule (accepted).

### Cost realism (D17)

The band is the sum of printed lines and every figure that is not in the knowledge base is labelled `planning estimate` or `planning heuristic`. Per-message services scale with users x a stated usage assumption (phone OTP logins, e-mail sends per recipient, LLM questions and tokens); managed ML training has a floor from `scale.data_volume_gb_12_months`; on-premise and air-gapped outputs add one `Hardware (indicative, not a quote)` line (servers per scale tier amortised over 36 months); a device count in the description sizes IoT ingestion; and a peak concurrency derived from a stated monthly audience uses a documented 5% or 2% fraction, never more than the users. When the budget is far below the minimum, `BUDGET_EXCEEDED` names the dominant line and what to cut (explain-only: nothing is removed); a single line above 10 times the budget gets a `Sanity check` sentence. All tables are in `engine/costreal.py`.

## Knowledge-base ratings and review notes

Knowledge-base ratings: the 1-5 values in `kb/technologies.json` are author judgement, not measurements. `kb/RATING-RUBRIC.md` defines what 1, 3 and 5 mean for each of the six criteria, the consistency rules that tie a rating to other fields of its record, the public data anchors (with URLs, access date and what could not be verified) and which ratings are rule-checked versus judgement-only. `kb/RATING-AUDIT.md` lists the ratings that currently contradict it; none has been changed.

Review limitations: numeric inputs must fit the finite floating-point range used by sizing calculations. Duplicate sanitized output filenames are rejected before any output is replaced. Unresolved residency and retained on-premises SaaS dependencies carry critical warnings. Source verification labels in `kb/sources.json` record the 11 November research pass; a later web review could not re-open every rendered vendor page, so read each label as of its access date.
