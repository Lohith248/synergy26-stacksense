# Design decisions

The participant owns these decisions (FAQ p15: "The design decisions, knowledge base and reasoning must be your own"). Claude proposed each one in the 10 November review. On 10 November the user told Claude to start Phase B and to "make those changes". **Each row still needs the participant to confirm it, in their own words, before submission.**

| id | Decision | Why | Participant confirmation |
|---|---|---|---|
| D1 | Route A: a new engine written inside the challenge window, starting 10 Nov 2026 after 10:00 IST. | The rules disqualify pre-existing projects (p15-16). | pending |
| D2 | Source root is `SYNERGY/StackSense26/source`, with a local git repository. Pushing to a public repo happens only on the user's instruction. | Commit history is the organiser's originality evidence (p13). | pending |
| D3 | A missing required field gives `invalid_input`, listing every missing or invalid field. A missing optional field gets its documented default, recorded in `assumptions`. | Section 6 (p9) allows this. A recommendation built on invented required values would mislead. | pending |
| D4 | On `invalid_input` the cost band is `min=null, max=null`, with an assumption saying no estimate was made. | A 0/0 band could be misread as a free stack. | pending |
| D5 | `infeasible` (with `stack=null`) only when hard constraints contradict each other. Soft conflicts (budget, timeline, team) give `ok_with_warnings` with a full stack and named warnings. | Follows p8 and p16. Hard constraints are never silently broken, and soft trade-offs stay useful. | pending |
| D6 | `cloud_preference=none` means "no public cloud". Combined with `managed_cloud` or `self_hosted_cloud_vm`, it is a hard contradiction. | The enum is undefined. "none" duplicating "any" is implausible. | pending |
| D7 | Fixed keyword rules on `project.description` may shape **supporting** services and warnings only. Each effect is recorded in `driven_by` and `assumptions`. Core layers come from structured fields. | p4 says the description "may be parsed by your engine". This keeps results deterministic and explainable. | pending |
| D8 | No LLM at runtime. `--no-llm` and `STACKSENSE_LLM=off` exist and are documented as no-ops. | An LLM choosing the stack scores zero (p9). A judge can verify there is no network use. | pending |
| D9 | The UI is a CLI: `run` for files, `interactive` for guided input with the same validator. | FR1 allows web or CLI. The CLI needs no dependencies. | pending |
| D10 | Scoring is a sum of explained terms: priority weight times knowledge-base rating, plus team-language fit, operations burden, budget fit and timeline. Ties are broken by product id. | Deterministic, and every term maps to an input path for `driven_by`. | pending |
