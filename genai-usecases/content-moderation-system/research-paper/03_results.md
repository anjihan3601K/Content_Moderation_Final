# Results, ready to copy

Every number here was produced by running the code; none is estimated. Raw files are in
`data/`. Charts are in `figures/`. Commands are in `06_reproducibility.md`.

All data is synthetic (seed 20261008): 800 items in 13 scenarios, 80 viewer profiles
(26 child, 28 teen, 26 adult), 200 resolved moderation cases.

---

## R1. Gate correctness on named cases

48 hand-written cases, one per rule the gate enforces: 42 that must be rejected and 6
controls that must be served. Each starts from one clean item and changes one thing.

| | Result |
|---|---|
| Rejection cases correctly rejected, with the expected reason | 42 / 42 |
| Control cases correctly served | 6 / 6 |
| Gate reason codes exercised | all |

Per-case table: `data/stage1_case_results.csv`. The controls matter: a gate that rejected
everything would pass the 42 rejection cases too.

## R2. Rating derivation

| Scenario | Items | Expected rating | Rated as expected |
|---|---|---|---|
| Clean, child topic | 220 | all_ages | 220 |
| Clean, teen topic | 140 | teen | 140 |
| Sensitive teen topic | 30 | teen | 30 |
| Adult topic | 120 | adult | 120 |
| Violation or toxicity 0.35 to 0.74 | 50 | adult | 50 |
| Borderline (toxicity 0.25 to 0.34) | 40 | teen | 40 |
| An agent dissented | 50 | adult | 50 |
| Pending review | 40 | adult | 40 |
| Removed | 40 | blocked | 40 |
| High-risk category, awaiting review | 24 | blocked | 24 |
| High-risk category, human-approved | 6 | adult | 6 |
| Legacy, no rating | 30 | unrated | 30 |
| Malformed pipeline output | 10 | adult | 10 |
| **Total** | **800** | | **800** |

Expected ratings were assigned by the data generator from the scenario, independently of
the rating code.

## R3. Exhaustive sweep: every profile against every item

64,000 gate decisions (80 x 800). "Leak" = an item served that the generator's ground-truth
labels say must be withheld from that viewer.

| Metric | Value |
|---|---|
| Decisions | 64,000 |
| Items served | 33,030 |
| Decisions for child or teen profiles | 43,200 |
| Items served to child or teen profiles | 15,888 |
| Leaks | **0** |

Served / evaluated, by scenario and viewer tier:

| Scenario | Child | Teen | Adult |
|---|---|---|---|
| Clean, child topic | 5394 / 5720 | 5835 / 6160 | 5720 / 5720 |
| Clean, teen topic | 0 / 3640 | 3757 / 3920 | 3640 / 3640 |
| Sensitive teen topic | 0 / 780 | 60 / 840 | 780 / 780 |
| Adult topic | 0 / 3120 | 0 / 3360 | 3120 / 3120 |
| Violation or moderate toxicity | 0 / 1300 | 0 / 1400 | 1075 / 1300 |
| Borderline | 0 / 1040 | 842 / 1120 | 1040 / 1040 |
| An agent dissented | 0 / 1300 | 0 / 1400 | 850 / 1300 |
| Pending review | 0 / 1040 | 0 / 1120 | 0 / 1040 |
| Removed | 0 / 1040 | 0 / 1120 | 0 / 1040 |
| High-risk, awaiting review | 0 / 624 | 0 / 672 | 0 / 624 |
| High-risk, human-approved | 0 / 156 | 0 / 168 | 156 / 156 |
| Legacy, unrated | 0 / 780 | 0 / 840 | 510 / 780 |
| Malformed | 0 / 260 | 0 / 280 | 251 / 260 |

Utility retained: clean child items reach child profiles 94.3 % of the time (5394/5720)
and clean teen items reach teen profiles 95.8 % (3757/3920). The shortfall is parental
blocks and strict settings on individual profiles.

Rejections by first failing check:

| Reason | Child | Teen | Adult | Total |
|---|---|---|---|---|
| Rating above tier | 8909 | 4867 | 0 | 13776 |
| Blocked | 1664 | 1792 | 1664 | 5120 |
| Parental control | 2849 | 2073 | 0 | 4922 |
| Pending review | 1040 | 1120 | 225 | 2385 |
| Unrated | 780 | 840 | 270 | 1890 |
| Not a servable status | 0 | 0 | 1040 | 1040 |
| Sensitive topic | 0 | 780 | 0 | 780 |
| High uncertainty | 38 | 62 | 450 | 550 |
| High-risk category | 126 | 132 | 0 | 258 |
| Borderline | 0 | 240 | 0 | 240 |
| Missing signals | 0 | 0 | 9 | 9 |

Only the first failing check is counted, so late checks look rarer than their reach.

## R4. Randomised invariant tests

| Test | Size | Violations |
|---|---|---|
| Gate alone, random profile/item pairs against an independent oracle | 12,000 pairs; 1,540 passed, 434 to minors | 0 |
| Gate decision unchanged when interests, learned weights and history are removed | 1,500 pairs | 0 |
| Full feed path with randomised interests, hostile learned weights, saturated history and randomly trained bandit | 1,040 feeds; 23,150 items served, 15,495 to minors | 0 |
| A ranker that injects rejected items, and one that rewrites ratings | 2 constructed attacks | additions removed by the final gate |

## R5. Leak rate with and without the gate (ablation)

5 feeds of 10 items per child and teen profile. Gate off = the ranker applied to all items.

| System | Tier | Feeds | Feeds with a forbidden item | Forbidden items served | Feeds with a later-flagged item |
|---|---|---|---|---|---|
| Gate on | child | 130 | 0 (0.0 %) | 0 | 24 (18.5 %) |
| Gate on | teen | 140 | 0 (0.0 %) | 0 | 19 (13.6 %) |
| Gate off | child | 130 | 126 (96.9 %) | 424 | 18 (13.8 %) |
| Gate off | teen | 140 | 93 (66.4 %) | 229 | 16 (11.4 %) |

Figure: `figures/chart_leak_rate.png`. Caption: *Share of child and teen feeds containing
at least one item the viewer must not see, with the gate and with the gate removed.*

"Later flagged" is a seeded 3 % of clean-looking items assumed to be flagged by a later
review. The gate cannot detect them. **3 % is an assumption, not a measurement.**

## R6. Ranking against baselines (single feed, k = 10)

| System | Precision@10 | NDCG@10 | Hit rate@10 |
|---|---|---|---|
| Full system (TF-IDF relevance + bandit + guards) | 0.935 | 0.863 | 1.000 |
| Bandit off | 0.935 | 0.892 | 1.000 |
| Interest-only sort (baseline) | 1.000 | 0.870 | 1.000 |
| Random among gate survivors | 0.348 | 0.261 | 0.963 |

Figure: `figures/chart_relevance.png`. Caption: *Relevance of one feed measured against
each profile's stated interests and weights (80 synthetic profiles).*

The full system's precision is below the baseline because the adult diversity guard
reserves 2 of 10 slots for topics outside the interests: (26 x 0.8 + 54 x 1.0) / 80 = 0.935.

## R7. Learning from simulated feedback (bandit ablation)

36 simulated viewers, 10 rounds of 10 items. Click probability 0.8 for two undeclared
topics, 0.5 for declared interests, 0.05 otherwise.

| Variant | Child | Teen | Adult |
|---|---|---|---|
| Full system | 0.554 | 0.552 | 0.454 |
| Bandit off, learned interests on | 0.555 | 0.553 | 0.435 |
| No learning | 0.548 | 0.553 | 0.408 |
| Random | 0.541 | 0.343 | 0.237 |

Figure: `figures/chart_bandit_learning.png`. Caption: *Simulated click rate per feedback
round. Viewers have undeclared tastes that only exploration can discover.*

Per-round values: `data/evaluation_bandit_by_round.csv`.

## R8. Diversity and drift

| System | Tier | Distinct topics per feed | Share outside stated interests | Borderline share |
|---|---|---|---|---|
| Full system | teen | 4.04 | 0.00 | 0.057 |
| Full system | adult | 5.04 | 0.20 | 0.104 |
| Interest-only | teen | 4.71 | 0.00 | 0.014 |
| Interest-only | adult | 5.00 | 0.00 | 0.035 |
| Random | teen | 7.96 | 0.70 | 0.064 |
| Random | adult | 8.65 | 0.79 | 0.139 |

Figure: `figures/chart_diversity_drift.png`. Caps: borderline share 15 % (teen), 30 %
(adult); diversity minimum 20 % (adult).

## R9. Review queue

64 queued items; one reviewed per step; time-to-review = position. High harm = high-risk
category awaiting review, or toxicity >= 0.5 (35 items).

| Policy | High-harm items | High-risk items | All items | High-harm among the first 35 | Exposure-weighted wait |
|---|---|---|---|---|---|
| Prioritizer | 20.0 | 12.5 | 32.5 | 88.6 % | 1466.9 |
| Risk-score sort | 22.6 | 27.0 | 32.5 | 74.3 % | 1680.8 |
| First in, first out | 42.6 | 52.5 | 32.5 | 28.6 % | 2289.2 |

Figure: `figures/chart_queue.png`. Caption: *Mean queue position at which items are
reviewed, under three ordering policies (lower is sooner).*

## R10. Precedent retrieval (ablation)

Leave-one-out over 200 resolved cases, k = 5.

| System | All cases | Cases where the moderator overrode the agents (120) | Cases of agreement (80) |
|---|---|---|---|
| With precedents | 66.0 % | 58.3 % | 77.5 % |
| Rules only | 40.0 % | 0.0 % | 100.0 % |

Figure: `figures/chart_precedents.png`. **Read `04_claims_and_limitations.md` before using
this table**: the data was constructed so that precedents can help.

## R11. Adversarial review findings

Three review passes by independent reviewers given only the safety rules and the source.

| Pass | Scope | Leaks found | Weaknesses found | Outcome |
|---|---|---|---|---|
| 1 | Rating and gate | 5 | 4 | all fixed |
| 2 | Rating and gate, after fixes | 3 | 4 and 2 notes | all fixed |
| 3 | Whole feature, new reviewer | 4 | 8 | all fixed except lost updates under concurrency |

Where the leaks were:

| Layer | Examples |
|---|---|
| Rating derivation (passes 1, 2) | Missing signals read as "nothing found"; policy flags ignored unless spelled exactly; missing category dropped; a "remove" vote from a bookkeeping agent skipped |
| Label matching (passes 1, 2) | Spelling variants of high-risk labels; plural and word-order variants in parental blocks |
| Parental controls (pass 1) | A "low" strictness setting was looser than having no controls |
| Storage (pass 3) | One unreadable profile field dropped all parental controls; a failed mirror write left a stale copy that overrode a removal |
| Integration (pass 3) | A pipeline re-run undid a moderator's removal |
| Access control (pass 3) | Resolved high-risk cases shown to ordinary moderators as precedents |

In pass 3 the reviewer's 40,000-item fuzz of the gate itself found no violation; every
leak was in the code around it.

## R12. Live run through the real pipeline

16 invented posts through the real workflow with the ML toxicity model on and a
rule-based stand-in for the language model. Full output: `data/live_demo_report.txt`.

| Outcome | Posts |
|---|---|
| Approved, rated all_ages | 4 |
| Approved, rated teen | 2 |
| Approved, rated adult (adult topic, or any attached media URL) | 3 |
| Held for human review (sensitive topic or agent disagreement) | 4 |
| Flagged, rated blocked (ML toxicity 0.87 and 0.99) | 2 |
| Removed (keyword match) | 1 |

Feeds: 4 items for the verified child, 3 for the child with one topic blocked, 6 for each
teen, 9 for each adult. Nothing flagged, held or removed was served.

Two defects found only by this run, both fixed:

1. Approved content carries no enforcement action, because the enforcement agent is not
   run for it. The rating required that field and rated every clean post adult.
2. The synthesis step reports a weighted score of about 0.1 as its confidence. The rating
   took the minimum confidence, so every item failed the uncertainty margin.

On the first live run, before these fixes, feeds for minors were empty.

## R13. Test suite

| | |
|---|---|
| Automated tests | 1,182 passed, 1 deliberately skipped |
| Host project's original tests, before and after | 3 passed |
| Evaluation metrics identical across two runs | yes |
