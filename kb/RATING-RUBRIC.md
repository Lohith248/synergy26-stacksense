# Knowledge-base rating rubric

Scope: the `r` array of every record in `technologies.json` (hosting, frontend_web, frontend_mobile, backend, database), as of the KB date 2026-11-11. Data checked on 13 Nov 2026 (IST). This file defines what a rating means. The companion `RATING-AUDIT.md` lists the ratings that contradict it. No rating value was changed to write either file.

## 1. Read this first: what a rating is and is not

- `r = [cost, time_to_market, scalability, performance, maintainability, security]`, each 1-5, higher is better for the user (cost 5 = cheapest). These are the six criteria the scorer uses (`PRIO_KEYS` in `engine/select.py`): score term = priority weight x (rating - 3) x 0.8, and for scalability, headroom above the tier's need (tier + 2) counts half.
- **No rating is a measurement.** None was computed by a formula or taken from a benchmark table. Every value was assigned by hand when the KB was curated (10 Nov 2026) and is an author judgement.
- What this rubric adds: a written meaning for 1, 3 and 5, a set of **consistency rules** that tie a rating to other facts in the same record (price band, `max_tier`, `learning`, `ops`, `host_os`, `multi_zone`, `low_end`), and public data anchors. Where a rule fixes the value or a window for it, the rating is called **rule-checked**. Where nothing in the KB or in a verified public source constrains it, the rating is called **judgement-only**. A rule-checked rating is still not measured: it is consistent or inconsistent with its own record.
- Coverage today: 366 ratings (61 records x 6). 191 are rule-checked by at least one rule below, 175 are judgement-only (details in section 5). A judge who asks "why 4, not 5?" for a judgement-only cell gets the definition in section 2 and the author's reasoning, not a number from a source.

## 2. Headline table: what 1, 3 and 5 mean

An anchor is a real KB product whose current rating equals the anchor value. Where no KB product is rated 1 on a criterion the cell says so: the definition is then a floor that no current option reaches.

| Criterion | 1 | 3 | 5 |
|---|---|---|---|
| **cost** (5 = cheapest) | More than about USD 500/month at the small tier, or a licence that dominates the bill. Anchor: none in the KB (lowest rating is 3). | About USD 50-150/month at the small tier, or a licence/consumption fee that matters at small scale. Anchor: `aws-ecs-fargate` (small band 50-150). Database anchor: `sqlserver` (licence). | Free or at most about USD 10/month at the small tier, open source with no licence fee. Anchor: `cloudflare-pages` (small band 0-0). |
| **time_to_market** | Months before a first production deploy, or needs specialists the team lacks. Anchor: none (lowest is 2: `rust-axum`, `onprem-k3s`). | About a week to a first deploy: several parts to assemble, or a steep learning curve (`learning` 3-4). Anchor: `go-chi`, `java-spring`. | Scaffold to deployed in a day: batteries included, one language, a managed or free deploy path, `learning` 1-2. Anchor: `python-django`. |
| **scalability** | Comfortable below the tiny tier only (`max_tier` 0). Anchor: `sqlite`. | One host or a fixed pool: comfortable to the medium tier (`max_tier` 2), no zone redundancy. Anchor: `aws-ec2` (single instance). | Large tier (`max_tier` 3) plus elastic scaling plus zone redundancy or a global edge that is on by default, not opt-in. Anchor: `aws-lambda`. |
| **performance** | Noticeably slow for end users or per request at normal load. Anchor: none (lowest is 2: `capacitor`). | Interpreted or sync-first runtime, or JavaScript bridge, adequate for most apps. Anchor: `python-django`; mobile anchor `react-native-expo`. | Compiled/native runtime or no client JavaScript; static content from a global edge. Anchor: `go-chi` (backend), `cloudflare-pages` (hosting), `kotlin-compose` (mobile). |
| **maintainability** | Fragile upgrades, no long-term support, or you patch and operate the whole platform with no help. Anchor: none (lowest is 3). | You patch the server OS yourself (`host_os: customer`) or the ecosystem offers few conventions. Anchor: `aws-ec2`; backend anchor `node-express`. | Opinionated structure or fully managed platform, stable upgrade path, large professional user base (at least 10% of professionals in SO 2025). Anchor: `postgresql`, `dotnet-aspnet`. |
| **security** | Insecure by default, or the user owns the whole security baseline. Anchor: none (lowest is 3). | The user patches the OS and wires auth, network rules and secrets. Anchor: `aws-ec2`; backend anchor `node-express` (minimal framework). | Provider owns runtime patching, strong default isolation, published compliance attestations; or a framework with secure defaults and a memory-safe language. Anchor: `aws-lambda` (see `aws-compliance` in `sources.json`); backend anchor `python-django`. |

Ratings 2 and 4 are interpolations: "between the 1/3 (or 3/5) definitions", never a separate definition.

### Layer-specific reading of the same scale

| Layer | cost | performance | scalability |
|---|---|---|---|
| hosting | small-tier price band in the record (rule C1) | 5 static from a global edge, 4 regional compute, 3 cold starts or small shared instances | `max_tier` + 1, +1 if zone redundancy or global edge is default (rule S1) |
| backend | free to run; 5 light footprint, 4 heavier baseline (JVM, Rails memory): judgement | runtime class: 5 native/AOT or async JIT (Go, Rust, ASP.NET Core), 4 V8/BEAM/Python async, 3 sync-first CPython, PHP, Ruby | `max_tier` + 1; +1 only for a very-high-concurrency runtime (judgement) |
| frontend_web | free; 5 static/templates | 5 static or near-zero client JS, 4 hydrated SPA/SSR | `max_tier` + 1 |
| frontend_mobile | free; licence and store fees ignored | 5 native or engine, 4 own renderer, 3 JS bridge, 2 WebView; must stay within 1 of `low_end` (rule P2) | judgement (no `max_tier` field) |
| database | 5 open source with no fee, 3 licence or paid tiers | judgement from `write` and the engine class | `max_tier` + 1; +1 for managed horizontally partitioned stores (judgement, no field records it) |

## 3. Consistency rules (the checks the audit runs)

A rule fires only when two facts in the KB disagree. The numeric offsets (for example `7 - learning`) are the author's coherence thresholds, not facts from a source.

| Rule | Criterion | Statement | KB fields used |
|---|---|---|---|
| C1 | cost | A hosting option whose small and medium price bands both sit inside another option's bands (no higher at either end, different on at least one) must not be rated lower on cost than that other option. Self-hosted on-prem (bands are 0 by construction: hardware, power and staff are outside the band) is exempt. | `cost` bands, tiers small and medium |
| T1 | time_to_market | rating <= 7 - `learning`. A stack that is hard to learn cannot be rated fastest to ship. | `learning` |
| S1 | scalability | hosting: implied = `max_tier` + 1; +1 when `max_tier` is 3 and zone redundancy is on by default or the host is a global edge; -1 for on-premises (capacity is bought, not rented). Zone redundancy that needs a plan, a network or a minimum instance count (Azure App Service, Azure Container Apps, Elastic Beanstalk) earns no +1. Backend, frontend and database: rating must lie in `max_tier` + 1 .. `max_tier` + 2. | `max_tier`, `multi_zone`, `regions`, `provider` |
| P1 | performance (hosting) | A static host served from a global edge rates 5. | `kind`, `regions` |
| P2 | performance (mobile) | within 1 of `low_end`. | `low_end` |
| P3 | performance (web) | static or template frontends rate 5; SSR with hydration at most 4. | `kind` |
| M1 / X1 | maintainability / security (hosting) | `host_os: customer` (you patch the server OS) caps both at 3. | `host_os` |
| M2 | maintainability (hosting) | rating <= 7 - `ops`. | `ops` |
| M3 | maintainability | A 5 needs at least 10% of professional developers using the technology in SO 2025 (section 4.1), or a written reason. Records with no SO row (hugo, flutter, go-chi, server-templates, ...) are "not verified", never failed. | SO 2025 share |

## 4. Public data anchors

All pages accessed 13 Nov 2026. "Read" means the page text was fetched with a web-fetch tool; the tool summarises the page, so each figure is single-source unless stated. The participant should re-read the page before quoting a number to a judge.

### 4.1 Hiring pool and ecosystem (supports maintainability and time_to_market)

Stack Overflow Developer Survey 2025, Technology section: <https://survey.stackoverflow.co/2025/technology>. Percentages are "all respondents / professional developers". Tables read: Databases (26,083 responses), Web frameworks and technologies (23,678), Cloud development (24,473).

| Group | Figures read (all / professional) |
|---|---|
| Databases | PostgreSQL 55.6 / 58.2, MySQL 40.5 / 39.6, SQLite 37.5 / 36.9, Microsoft SQL Server 30.1 / 30.9, MongoDB 24.0 / 24.3, DynamoDB 9.8 / 10.8, Supabase 6.0 / 6.1, Cloud Firestore 5.7 / 5.7, Cosmos DB 4.6 / 4.9 |
| Web frameworks | Node.js 48.7 / 49.1, React 44.7 / 46.9, Next.js 20.8 / 21.5, Express 19.9 / 20.3, ASP.NET Core 19.7 / 21.3, Angular 18.2 / 19.8, Vue.js 17.6 / 18.4, FastAPI 14.8 / 15.1, Spring Boot 14.7 / 15.6, Django 12.6 / 11.7, Laravel 8.9 / 9.3, Svelte 7.2 / 6.9, Blazor 7.0 / 7.6, NestJS 6.7 / 7.4, Ruby on Rails 5.9 / 6.2, Astro 4.5 / 4.3, Nuxt.js 4.0 / 4.1, Axum 2.8 / 2.7, Phoenix 2.4 / 2.5 |
| Cloud | AWS 43.3 / 45.9, Microsoft Azure 26.3 / 27.2, Google Cloud 24.6 / 24.3, Cloudflare 20.1 / 19.7, Firebase 13.1 / 13.3, DigitalOcean 10.7 / 11.1, Vercel 10.6 / 10.8, Netlify 5.9 / 5.7 |

Verification status: read from the official page on 13 Nov 2026. Independently cross-matched by a second source: only PostgreSQL (55.6 all / 58.2 professional). The other figures are single-source. **Not verified (not on the page or not readable):** Flutter, React Native, .NET MAUI, Unity, Capacitor, Godot, Kotlin Multiplatform, Gin/go-chi, Hugo, server-rendered templates, Elixir/Phoenix beyond the row above. Do not quote a hiring-pool figure for those.

How it is used: a popularity share does not make a stack better. It is used only as a support signal for maintainability (rule M3) and as the reason the team-language term in the scorer exists. The hiring/team-language effect itself is not a rating: it is `lang_term` in `engine/select.py`.

### 4.2 Performance

TechEmpower Framework Benchmarks Round 23, announced 17 Mar 2025: <https://www.techempower.com/blog/2025/03/17/framework-benchmarks-round-23/> (new Microsoft-provided hardware: ProLiant DL360 Gen10 Plus, Xeon Gold 6330, 64 GB, 40 Gbps). The project repository <https://github.com/TechEmpower/FrameworkBenchmarks> states it "was archived by the owner on Mar 24, 2026", so Round 23 is the last published round.

Verified: the round, its date and its hardware. **Not verified: any per-framework rank or requests-per-second figure.** The interactive results page (`https://www.techempower.com/benchmarks/#section=data-r23`) is script-rendered and could not be read by the tools used. No framework result is quoted in this rubric or in the KB. Backend performance ratings are therefore judgement by runtime class (section 2), which a reader can check against that public page themselves. A runtime-class tier is a directional statement, not a measured gap.

### 4.3 Scalability and availability (provider SLA and zone-redundancy documentation)

SLA percentages read on the official pages on 13 Nov 2026:

| Product | Figure | Page (as stated on the page) |
|---|---|---|
| AWS Lambda | 99.95% monthly uptime per Region | <https://aws.amazon.com/lambda/sla/> (page last updated 5 May 2022) |
| Amazon EC2 | 99.99% multi-AZ (Region-level), 99.5% single instance | <https://aws.amazon.com/compute/sla/> (last updated 25 May 2022) |
| Amazon ECS and Fargate | service credits begin below 99.99% (multi-AZ) | <https://aws.amazon.com/ecs/sla/> (last updated 25 May 2022) |

**Not verified in this work** (page did not render, redirected to a download, or returned 404): Cloud Run 99.95 (<https://cloud.google.com/run/sla>), Compute Engine "99.9 single instance" (<https://cloud.google.com/compute/sla>; the fetch tool recalled 99.5% for a single instance from older text, so the KB value is unresolved and must be read on the live page), Azure App Service 99.95, Azure Container Apps 99.95, Azure VM "99.9 single VM, premium SSD" (Microsoft SLA summary document, <https://www.microsoft.com/licensing/docs/view/Service-Level-Agreements-SLA-for-Online-Services>, download-only), DigitalOcean Droplet 99.99 (the SLA URL tried returned 404), CloudFront 99.9, Vercel 99.99 (Enterprise only). These strings are in `technologies.json` (`sla`) with no SLA page cited in `src`.

Zone-redundancy and availability documentation already recorded in `sources.json` with status `verified` (rendered 12 Nov 2026; not re-fetched on 13 Nov):

| Product | Statement | Source id |
|---|---|---|
| AWS Lambda | "Lambda runs your function in multiple Availability Zones" | `lambda-resilience` |
| Amazon ECS / Fargate | Fargate spreads tasks across accessible AZs on a best-effort basis; AZ rebalancing on by default for new services | `ecs-az-rebalancing` |
| Cloud Run | "replicated across multiple zones in the region" | `gcp-cloudrun-locations` |
| Azure App Service | zone redundancy only on Premium v2-v4 with at least two instances | `azure-appservice-reliability` |
| Azure Container Apps | zone redundancy set at environment creation, needs a virtual network and at least two replicas | `azure-containerapps-reliability` |
| Elastic Beanstalk | multi-AZ only in a load-balanced, scalable environment | `beanstalk-autoscaling` |
| DigitalOcean Droplet | one server in one datacenter, no availability-zone placement | `digitalocean-droplets` |

These statements are the reason S1 gives no +1 to opt-in zone redundancy (App Service, Container Apps, Elastic Beanstalk).

## 5. Which ratings are rule-checked and which are judgement

| Criterion | Rule-checked cells | Rules | Judgement-only cells |
|---|---|---|---|
| cost | 19 of 61 (hosting, excl. 2 on-prem) | C1 | 42: all non-hosting, on-prem hosting. Labelled judgement: no price band exists for frameworks or most databases |
| time_to_market | 61 of 61 | T1 (a cap, not a value) | the exact value below the cap is judgement |
| scalability | 52 of 61 (every record with `max_tier`) | S1 | 9: frontend_mobile; values above the S1 window for backends and databases (for example the 5 for `go-chi`, `dynamodb`) are judgement |
| performance | 25 of 61 (static hosts, mobile, web) | P1, P2, P3 | 36: other hosting, backend, database. Runtime-class judgement, anchored to TechEmpower only directionally (4.2) |
| maintainability | 29 of 61 (hosting 21 via M1/M2; 8 backend/database/web records rated 5 via M3) | M1, M2, M3 | 32 |
| security | 5 of 61 (hosting with `host_os: customer`) | X1 | 56: this criterion is mostly judgement |

Totals: 191 rule-checked, 175 judgement-only. Judgement ratings are never presented as measured. In particular every security rating other than the five capped hosting cells, every database performance rating and every backend security rating are author judgement.

## 6. Changing a rating

Ratings drive every output (P1-P6 and all probes). A change is a participant decision: record it as a new row in `DECISIONS.md` with the reason, change `technologies.json`, rerun the tests and the P1-P6 comparison against `outputs/`. This rubric and the audit do not change any rating.
