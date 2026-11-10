# StackSense — deterministic tech-stack recommendation engine

StackSense reads a project scenario in the official StackSense JSON format and recommends four core layers: frontend, backend, database and hosting. It adds supporting services such as auth, storage, search, realtime, cache, queue, payments, CDN, ML, CI/CD and observability where the inputs call for them. Each choice comes with:

- a scenario-specific justification;
- the input fields that drove it (`driven_by`);
- real alternatives and the reason each lost;
- trade-offs;
- an order-of-magnitude monthly cost band with its assumptions;
- severity-coded warnings for conflicts and risks.

Hard constraints (cloud preference, deployment model, data residency, compliance) filter candidates before any scoring, so they are never broken silently. Selection is done entirely by rules and weighted scoring over a cited knowledge base. **No LLM is used anywhere.** The engine is pure Python standard library, so there is nothing to install beyond Python.

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
 Section 4 JSON  ──►  outputs/<scenario_id>_output.json   (+ optional readable --explain view)

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
| `engine/kb.py` | Loads the knowledge base; an unknown source id fails loudly |
| `tools/check_contract.py` | Independent checker of the Section 4 output contract |
| `tests/` | 41 stdlib `unittest` tests: boundary set B01-B34, KB lint, deprecated-product guard, 96 hard-constraint mutations, interactive mode |

## Technology used

- Python 3.10+, standard library only: `json`, `argparse`, `re`, `unittest`. Tested on CPython 3.10.11 and 3.13.3 on Windows 11. Python 3.10 reached end of life on 2026-10-01, so **3.11 or newer is recommended**.
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
- Output is written to `outputs/<scenario_id>_output.json`, or `scenario_output.json` when there is no id.
- `--explain` also prints a readable explanation to the terminal.
- The exit code is 1 if any scenario is `invalid_input`, otherwise 0.
- Files are written atomically, so a crash never leaves a half-written output.

To enter a scenario by answering prompts for every standard field, use interactive mode. It saves the input file and then evaluates it:

```bash
python stacksense.py interactive --out outputs
```

Edge-case examples for every Section 6 category are in `scenarios/edge_cases/` (E1-E9):

```bash
python stacksense.py run scenarios/edge_cases/E7_air_gapped.json --explain
```

## Switching off LLM features

The engine contains no LLM calls, so the result is always the same with or without the switch. For the judges' LLM-off test, both of these are accepted and documented:

```bash
python stacksense.py run scenarios/stacksense_public_scenarios.json --out outputs --no-llm
```

You can also set the environment variable `STACKSENSE_LLM=off`. The test suite blocks sockets and verifies byte-identical outputs across processes and hash seeds.

## Verify

```bash
python -I -m unittest discover -s tests -v
```

```bash
python tools/check_contract.py outputs/P1_output.json outputs/P2_output.json outputs/P3_output.json outputs/P4_output.json outputs/P5_output.json outputs/P6_output.json
```

## Output conventions (documented interpretations)

- **`invalid_input`:** every detected problem is listed. `stack` is `null` and the cost band is `null/null`, so it cannot be mistaken for a free stack.
- **`infeasible`:** used only when hard constraints contradict each other, for example `cloud_preference: none` with a cloud deployment, an explicit cloud provider with on-premise, or `rbi_localisation` with EU/US residency. It comes with critical warnings naming both fields, and `stack` is `null`.
- **Soft conflicts:** budget, timeline and team conflicts give `ok_with_warnings` with a full stack and named warnings, never a silent violation.
- **`cloud_preference: none`** means no public cloud.
- **`on_premise` and `air_gapped`** both allow only self-hostable components, with no SaaS or CDN. Unavoidable external dependencies (a payment gateway, an existing cloud identity provider, an SMS carrier link) are kept only with an explicit warning.
- **Description rules:** fixed, deterministic keyword rules on `project.description` shape supporting services and warnings only, for example UPI, EMI, payouts, ledger, KYC, offline sync and Microsoft 365. Core layers come from structured fields.

## Project structure

```
source/
├── stacksense.py            CLI entry point
├── engine/                  validation, context, selection, services, orchestration
├── kb/technologies.json     knowledge base (as_of 2026-11-10)
├── kb/sources.json          cited sources with verification status
├── scenarios/               official public scenarios + edge_cases/E1-E9
├── outputs/                 P1-P6 outputs produced by this engine
├── tools/check_contract.py  output contract checker
├── tests/                   boundary, KB and interactive tests
├── DECISIONS.md             participant-owned design decisions
└── README.md
```

## Credits

- **Third-party libraries:** none. The engine uses only the Python standard library (PSF licence).
- **Datasets:** the organiser's `stacksense_public_scenarios.json`. No external datasets.
- **APIs:** none called at runtime.
- **Knowledge-base sources:** official vendor documentation, pricing and lifecycle pages and regulator pages. All are listed in `kb/sources.json` with URL, access date (2026-11-10) and verification status, and they are cited in the report.
- **AI assistance:** Claude Code (Anthropic) was used as a coding and research assistant. It is declared in the report's AI-assistance section. Design decisions are recorded in `DECISIONS.md`.
