# StackSense: a deterministic, explainable tech-stack recommendation engine

Entry for the **StackSense Challenge, Synergy '26**. StackSense reads a project scenario in the official JSON format. It recommends the four core layers (frontend, backend, database and hosting) plus the supporting services the inputs call for: auth, storage, search, realtime, cache, queue, payments, CDN, ML, CI/CD and observability.

- **Hard constraints are never broken.** Cloud preference, deployment model, data residency and compliance remove candidates *before* any scoring.
- **Every choice is explained.** Each component comes with:
  - a justification specific to the scenario;
  - the input fields that drove it (`driven_by`);
  - the real alternatives and why each lost;
  - its trade-offs;
  - a confidence label;
  - **what would change it**: single-field edits, found by re-running the engine.
- **Costs are honest.** Each recommendation gets an itemised monthly cost band with its assumptions printed, plus severity-coded warnings for conflicts and risks.
- **Deterministic, no LLM.** Selection uses rules and weighted scoring over a cited knowledge base. The same input always gives the same output.
- **Nothing to install.** Pure Python standard library: no packages, no network, no API keys.

## Quick start

```bash
git clone https://github.com/Lohith248/synergy26-stacksense.git stacksense && cd stacksense
python stacksense.py run scenarios/stacksense_public_scenarios.json --out outputs
```

This writes `outputs/P1_output.json` … `outputs/P6_output.json`. Requires Python 3.10 or newer; 3.11 or newer is recommended, since 3.10 reached end of life in October 2026. On macOS/Linux use `python3` if `python` is not Python 3. Works on Windows, macOS and Linux.

## Validation at a glance

| Check | Result |
|---|---|
| Unit and acceptance tests | 1,311 tests OK (18 skip when the optional `research/` folder is absent) |
| Public scenarios P1-P6 | `outputs/` reproduces byte-for-byte |
| Output contract (`tools/check_contract.py`) | PASS 6/6 |
| One-field perturbation sweep (`tools/perturb.py`) | 1,087 edits, 0 crashes, 0 violations |

These are development checks, not a measure of accuracy on unseen scenarios.

## Architecture

```
 scenario.json (object or array)
        │
        ▼
 engine/load.py       strict JSON (rejects NaN/Infinity/overflow, duplicate keys)
        ▼
 engine/validate.py   types, enums, ranges, required fields ──► invalid_input (every error, stack = null)
        │             documented defaults, each recorded in `assumptions`
        ▼
 engine/context.py    scale tier, team fit, residency, description rules, existing systems + lifecycle
        ▼
 engine/recommend.py  hard-vs-hard conflicts ──► infeasible (every conflict named, stack = null)
        │
        ├─ engine/select.py    per layer: hard filters → explained additive score
        │                      backend → hosting → database → frontend; ties broken by product id
        ├─ engine/services.py  supporting services inside the same constraint envelope
        ├─ cost band, warnings, architecture style, summary
        ▼
 engine/counterfactual.py  re-runs the engine on one-field edits → what_would_change
        ▼
 outputs/<scenario_id>_output.json   (+ --explain text, optional local web UI)

 kb/technologies.json   61 products: ratings, regions, cost bands, lifecycle table, existing-system patterns
 kb/sources.json        every cited source (official URL, access date, verification status)
```

| Module | Role |
|---|---|
| `stacksense.py` | CLI: `run`, `interactive`, `serve`, `fields`; flags `--explain`, `--adr`, `--no-llm` |
| `engine/validate.py` | Field-level errors (`{field, message}`); defaults recorded as assumptions |
| `engine/context.py` | Derived facts; users are people, never treated as requests per second |
| `engine/select.py` | Hard filtering and explained scoring for the core layers |
| `engine/services.py` | Supporting services, offline sync and integrations |
| `engine/recommend.py` | Orchestration, conflicts, warnings, cost band, summary |
| `engine/rightsize.py`, `engine/overeng.py` | Guards against over-engineering, each with its thresholds in one table |
| `engine/domains.py`, `engine/mlstack.py` | Domain rules for games, IoT and analytics, and for ML/LLM serving |
| `engine/costreal.py` | Itemised cost lines and their assumptions |
| `engine/counterfactual.py` | `what_would_change`, measured by re-running the engine |
| `engine/web.py`, `web/index.html` | Optional local web UI (127.0.0.1 only, no internet) |
| `tools/check_contract.py` | Independent checker for the output contract |

## Usage

```bash
python stacksense.py run path/to/scenario.json --out outputs --explain
```

- The input can be a single scenario object or an array of them. Each output goes to `outputs/<scenario_id>_output.json`.
- `--explain` prints a readable explanation to the terminal.
- `--adr` also writes an Architecture Decision Record for each core layer.
- The exit code is 1 if any scenario is `invalid_input`.

**Guided input:** `python stacksense.py interactive --out outputs` asks for every standard field, then evaluates the scenario.

**Web UI:** `python stacksense.py serve`, then open http://127.0.0.1:8765/. It has a form for every field, a JSON tab, the sample scenarios, a Recommend button and JSON export, and it calls the same engine as the CLI.

**Samples:**
- `scenarios/edge_cases/` holds E1-E9, one for each edge-case category in the statement.
- `scenarios/hidden_like/` holds extra probes for project types the public set does not cover.
- `scenarios/extras/X1_p6_with_extras.json` shows the optional extra inputs.

```bash
python stacksense.py run scenarios/edge_cases/E7_air_gapped.json --explain
```

## Switching off LLM features

The engine contains no LLM calls, so output is identical with or without the switch. Both forms are accepted for the LLM-off test:

```bash
python stacksense.py run scenarios/stacksense_public_scenarios.json --out outputs --no-llm
```

You can also set `STACKSENSE_LLM=off` (see `.env.example`). The tests block network sockets and check that outputs are byte-identical across processes.

## Verify

```bash
python -I -m unittest discover -s tests
python tools/check_contract.py outputs/P1_output.json outputs/P2_output.json outputs/P3_output.json outputs/P4_output.json outputs/P5_output.json outputs/P6_output.json
python tools/perturb.py          # optional robustness sweep, about 10 s
```

## Key output conventions

- **`invalid_input`** lists every problem. `stack` is `null` and the cost band is `null/null`, so it is never mistaken for a free stack.
- **`infeasible`** is used only when hard constraints contradict each other, for example `cloud_preference: none` with a managed cloud. Every conflict is named, with a resolution.
- **Soft conflicts** (budget, timeline, team) give `ok_with_warnings` with a full stack. If a critical conflict remains, the result is a labelled "Relaxed recommendation".
- **Extra output fields:** every core component has `what_would_change`, `stability`, `confidence` and `contrast`. For backend, database and hosting there are also `score_margin` and `pareto`.

Optional extra inputs (`peak_rps`, `geo_spread`, `hiring_languages`, `lock_in_tolerance`, RTO/RPO, `residency_country`) and the full conventions are in **[docs/DETAILS.md](docs/DETAILS.md)**. That covers input notation, right-sizing, the over-engineering guard and the cost method.

## Project structure

```
├── stacksense.py       CLI entry point
├── engine/             validation, context, selection, services, costs, counterfactuals, web UI
├── kb/                 knowledge base, cited sources, rating rubric and audit
├── scenarios/          public scenarios, edge_cases/ (E1-E9), hidden_like/, extras/
├── outputs/            P1-P6 outputs produced by this engine
├── web/index.html      local web UI page
├── tools/              contract checker, perturbation sweep
├── tests/              stdlib unittest suite
├── docs/DETAILS.md     input/output reference
└── DECISIONS.md        design decisions and their reasons
```

## Credits

- **Libraries:** none beyond the Python standard library (PSF licence).
- **Datasets:** the organiser's `stacksense_public_scenarios.json` only.
- **APIs:** none called at runtime.
- **Knowledge-base sources:** official vendor documentation, pricing, lifecycle and regulator pages. All are listed in `kb/sources.json` with URL, access date and verification status. Ratings are author judgement against `kb/RATING-RUBRIC.md`.
- **AI assistance:** Claude Code (Anthropic) and OpenAI Codex were used as coding and review assistants. A GPT-6.1 Terra research agent checked primary-source text. They are declared in the project report. Design decisions are recorded in `DECISIONS.md`, and no AI takes part in a recommendation.
