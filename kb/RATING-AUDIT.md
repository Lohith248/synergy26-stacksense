# Rating audit against `RATING-RUBRIC.md`

Audit date 13 Nov 2026 (IST), KB as_of 2026-11-11, repository state main 552d36e. **Nothing was changed.** This file lists ratings that contradict a rubric rule. It does not say which side is right: either the rating or the record field the rule reads (`max_tier`, `learning`, `ops`, `host_os`, price band) may be the one to correct. Every change is the participant's decision (see rubric section 6) and moves outputs, so P1-P6 must be re-run after any edit.

## Method and coverage

- Scope: all 366 ratings (61 records x 6 criteria: hosting 21, frontend_web 10, frontend_mobile 9, backend 12, database 9).
- 191 ratings are checked by a mechanical rule (rubric section 3, rules C1, T1, S1, P1, P2, P3, M1, M2, M3, X1). The check is a script that reads `technologies.json` and the Stack Overflow 2025 shares in rubric 4.1; it is not part of the repository.
- 175 ratings are judgement-only (no KB field or verified public figure constrains them), so they cannot contradict the rubric by data. They are not endorsed either: they are author judgement.
- Result: **21 contradicting ratings in 15 records** (21 rating cells). 170 rule-checked cells passed.
- Direction: "implied" is the value or window the rule gives. Severity: **major** = off by 2 or more, or the same record contradicts itself on two rules; **minor** = off by 1.

## Contradictions, strongest first

| # | Record (layer) | Criterion | Current | Rubric-implied | Rule | Evidence |
|---|---|---|---|---|---|---|
| 1 | `onprem-k3s` (hosting) | scalability | 5 | 3 | S1 | `max_tier` 3, `scaling` instances, `provider` on_premise, no `multi_zone`; capacity is bought, not rented, so 3 + 1 (tier) - 1 (on-prem). Major (off by 2). |
| 2 | `vercel` (hosting) | cost | 3 | 4 | C1 | Small band 20-60 and medium 60-300 sit inside the bands of `render` (25-100 / 100-500), `railway` (20-80 / 80-400), `aws-elastic-beanstalk` (35-150 / 150-800), `azure-app-service` (25-150 / 150-800), `azure-container-apps` (20-120 / 120-700), `aws-ec2` (25-90 / 90-450), `azure-vm` (30-100 / 100-500), `gcp-compute-engine` (25-90 / 90-450), all rated 4. Eight cheaper-or-equal options rate higher. |
| 3 | `netlify` (hosting) | cost | 4 | 5 | C1 | Small band 0-19 and medium 19-99 sit inside the bands of `aws-lambda` (5-50 / 50-400), `gcp-cloud-run` (10-80 / 80-500), `digitalocean-droplet` (18-60 / 60-300), all rated 5. |
| 4 | `aws-elastic-beanstalk` (hosting) | maintainability and security | 4 and 4 | 3 and 3 | M1, X1 | Its own record has `host_os: customer` (you patch the server OS); the four other `host_os: customer` options (`aws-ec2`, `azure-vm`, `gcp-compute-engine`, `digitalocean-droplet`) are all rated 3 on both. Two cells, same cause. Major: the record contradicts itself on two criteria. |
| 5 | `nextjs` (frontend_web) | time_to_market | 5 | at most 4 | T1 | `learning` 3 in the same record. Other records with `learning` 3 (`aws-lambda`, `aws-ecs-fargate`, `azure-container-apps`, `go-chi`, `dotnet-aspnet`, `flutter`, `unity`, ...) are rated 4 or lower. |
| 6 | `onprem-k3s` (hosting) | maintainability | 3 | at most 2 | M2 | `ops` 5 (highest in the KB). Same record as #1. |
| 7 | `azure-container-apps` (hosting) | scalability | 5 | 4 | S1 | `max_tier` 3 but zone redundancy is opt-in: `azure-containerapps-reliability` (verified 12 Nov 2026) says it is set at environment creation and needs a virtual network and at least two replicas. Under S1 opt-in redundancy earns no +1. By contrast `azure-app-service` and `aws-elastic-beanstalk` (same kind of opt-in) are rated 4, and `gcp-cloud-run` (replicated across zones by default) is rated 5. |
| 8 | `azure-static-web-apps` (hosting) | scalability | 4 | 5 | S1 | Same relevant fields as `cloudflare-pages` and `aws-s3-cloudfront` (static, `max_tier` 3, global edge), which are rated 5. |
| 9 | `firebase-hosting` (hosting) | scalability | 4 | 5 | S1 | Same as #8. |
| 10 | `netlify` (hosting) | scalability | 4 | 3 | S1 | `max_tier` 2 and global edge, identical fields to `github-pages` (rated 3). The two static hosts with the same fields are rated 3 and 4. |
| 11 | `vercel` (hosting) | scalability | 4 | 3 | S1 | `max_tier` 2, `multi_zone` null (not established), so no +1; 3 would match the other `max_tier` 2 options (`render`, `aws-ec2`). |
| 12 | `railway` (hosting) | scalability | 3 | 2 | S1 | `max_tier` 1, the only hosting record at 1; rule implies `max_tier` + 1 = 2. |
| 13 | `python-django` (backend) | scalability | 3 | 4 to 5 | S1 | `max_tier` 3 but rated 3. Either `max_tier` should be 2 (as for `php-laravel`, `ruby-rails`) or the rating 4. The record is inconsistent with itself whichever the author intends (sync-first runtime would justify 3 only with `max_tier` 2). |
| 14 | `github-pages` (hosting) | performance | 4 | 5 | P1 | Static from a global edge (`regions: global`), like `cloudflare-pages`, `aws-s3-cloudfront`, `firebase-hosting` (all 5). |
| 15 | `azure-static-web-apps` (hosting) | performance | 4 | 5 | P1 | Same as #14. |
| 16 | `netlify` (hosting) | performance | 4 | 5 | P1 | Same as #14. |
| 17 | `server-templates` (frontend_web) | performance | 4 | 5 | P3 | `kind: templates`: no client JavaScript framework. `astro` and `hugo` (static) are rated 5. |
| 18 | `sveltekit` (frontend_web) | performance | 5 | 4 | P3 | `kind: ssr` with hydration; the other `ssr` records (`nextjs`, `nuxt`, `blazor`) are 4. Defensible as judgement (compiled, small runtime), but then rule P3 needs a written exception. |
| 19 | `node-nestjs` (backend) | maintainability | 5 | at most 4 | M3 | SO 2025 professional share 7.4% (<10%), <https://survey.stackoverflow.co/2025/technology>, read 13 Nov 2026. Single-source figure. |
| 20 | `blazor` (frontend_web) | maintainability | 5 | at most 4 | M3 | SO 2025 professional share 7.6% (<10%), same page. Single-source figure. |

Counting: 20 table rows, but row 4 covers two cells (maintainability and security), giving 21 cells. Several records appear more than once (`netlify` x3, `vercel` x2, `onprem-k3s` x2, `azure-static-web-apps` x2, `aws-elastic-beanstalk` x2 cells), which leaves 15 distinct records.

Top 5 (by size of the gap and strength of the evidence): #1 `onprem-k3s` scalability 5 vs 3; #2 `vercel` cost 3 vs 4 (dominated by eight options); #3 `netlify` cost 4 vs 5; #4 `aws-elastic-beanstalk` maintainability/security 4/4 vs 3/3; #5 `nextjs` time_to_market 5 vs at most 4.

### Notes the participant should weigh before changing anything

- Rules C1, P1, P3 and the +1 edge clause of S1 rest on the author's own rubric definitions (rubric section 3). If the participant disagrees with a rule, the fix is to change the rule, not the rating; the contradiction then disappears.
- #7 (Container Apps) is the one place where a verified vendor statement (zone redundancy needs a VNet and two replicas) works against the current rating. #2, #3 and #13 are contradictions inside the KB's own numbers, with no outside source needed.
- #1: on-prem k3s `max_tier` 3 may itself be the field to review.
- Ratings used by the scorer: scalability above `tier + 2` counts half (select.py `prio_terms`), so lowering a 5 only changes outputs where the scenario tier is large.

## Evidence gaps (not rating contradictions)

- `sla` strings with no SLA page cited in the record's `src`: `aws-s3-cloudfront` (99.9 CloudFront), `vercel` (99.99 Enterprise only), `aws-ecs-fargate`, `aws-lambda`, `azure-app-service`, `azure-container-apps`, `gcp-cloud-run`, `aws-ec2`, `azure-vm`, `gcp-compute-engine`, `digitalocean-droplet`. Three were verified on 13 Nov 2026 (Lambda 99.95, EC2 99.99 multi-AZ / 99.5 single instance, ECS/Fargate credits below 99.99; rubric 4.3). Eight are not verified; in particular `gcp-compute-engine` "99.9 (single instance)" conflicts with a recollection of 99.5% and must be read on <https://cloud.google.com/compute/sla> before it is quoted.
- No benchmark figure supports any backend `performance` rating (rubric 4.2: TechEmpower Round 23 per-framework results could not be read). Treat all backend performance ratings as judgement.
- Mobile frameworks have no hiring-pool figure (rubric 4.1). Do not claim one.
- `multi_zone` is null for `vercel`, `render`, `railway`, `onprem-*`, and absent for all static hosts. S1's +1 for databases that are managed and horizontally partitioned (`dynamodb`, `cosmosdb`, `mongodb`) has no recorded field, so their scalability 5 is judgement.

## Reproduce

The rules in rubric section 3 can be re-run by any script that loads `technologies.json`; the 21 cells above come from those rules and nothing else. Hand-check any row by reading the named fields in the record.
