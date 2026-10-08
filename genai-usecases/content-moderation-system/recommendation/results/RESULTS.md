# Results

Real output from real runs only. Nothing below is estimated. Stage 4 (offline evaluation
with baselines, ablations and charts, and the final independent review) has not been run;
the numbers here come from the test suite and the Stage 1 replay.

## Status

| Stage | State |
|---|---|
| 0 - baseline and findings | done |
| 1 - audience rating and safety gate | done, reviewed twice |
| 2 - profiles, storage, personalization | done, tested, **not independently reviewed** |
| 3 - moderator queue, feedback, endpoints | done, tested, **not independently reviewed** |
| 4 - evaluation, final review | mock data done; evaluation script, charts and final review not started |

## Test outcomes (2026-10-08)

| Suite | Command | Result |
|---|---|---|
| Host suite, baseline (before any change) | `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q` | 3 passed |
| Host suite, after Stage 1 | same | 3 passed |
| Host suite, after Stages 2 and 3 | same | 3 passed |
| Recommendation tests | `backend/.venv/Scripts/python.exe -m pytest recommendation/tests -q` | 1093 passed, 1 skipped (95 s) |

| Test file | Passed |
|---|---|
| `test_rec_rating.py` | 249 (+1 skipped) |
| `test_rec_safety_gate.py` | 537 |
| `test_rec_gate_invariants.py` | 4 |
| `test_rec_mock_data.py` | 76 |
| `test_rec_pipeline_hook.py` | 7 |
| `test_rec_store.py` | 64 |
| `test_rec_personalization.py` | 37 |
| `test_rec_feed_service.py` | 11 |
| `test_rec_queue_feedback.py` | 43 |
| `test_rec_api.py` | 65 |

The skip is deliberate: a parametrised case that would test `toxicity_score = 0` as a
malformed value, which it is not.

Regression status: no previously passing test fails. The host suite is 3 tests and does not
exercise the existing API, so this is weak evidence; see `docs/00_codebase_findings.md`.

### Gate invariant run

Seed 20261008, 300 random profiles x 40 random items.

| | |
|---|---|
| Profile/item combinations evaluated | 12,000 |
| Items the gate passed | 1,540 |
| Of those, passed to a child or teen | 434 |
| Passed items that broke a safety rule (independent oracle) | **0** |

Further seeded checks, all passing: 1,500 pairs where the gate decision is identical with
and without interests, learned weights and feed history; 200 pools where the final-output
check returns exactly the pool-filter survivors; 2,000 child profiles against teen, adult
and blocked items with zero passes.

This run covers the gate in isolation. The next section covers the full feed path.

## Stages 2 and 3

### Invariant through the whole feed path

`test_no_leak_through_the_full_feed_path_whatever_the_personalization_state`, seed 20261008.
Every one of the 80 mock profiles requests 13 feeds over all 800 mock items. Before each
feed the profile's explicit interests, learned weights and feed history are replaced with
random values that include escalation and adult topics, and the bandit is trained with
random rewards. Each served item is checked against the generator's ground-truth labels and
re-checked by the gate against the profile as stored.

| | |
|---|---|
| Feeds built | 1,040 |
| Items served | 23,150 |
| Of those, served to a child or teen | 15,495 |
| Served items that break a safety rule | **0** |

Also verified: a ranker that injects rejected or invented items, and a ranker that rewrites
an item's rating, both have their additions removed by the final gate; a profile record
that has lost its tier gets the child feed.

### Personalization versus a random baseline

Precision@10 on the mock data, where an item counts as relevant if one of its topics is in
the profile's explicit interests. Same gate survivors for both; 80 profiles.

| | Precision@10 |
|---|---|
| Ranker (TF-IDF relevance + bandit, seed 5) | 0.935 |
| Random 10 of the gate survivors (seed 11) | 0.349 |

Read this with care: the relevance label is defined from the same topic labels the ranker
uses, on synthetic data, so it shows the ranker does what it is built to do, not that
people would find the feed relevant. A comparison against an interest-only baseline, NDCG,
and the bandit-off and precedent-off ablations are Stage 4 and have not been run.

### Guards (unit-level, on constructed pools)

| Check | Result |
|---|---|
| Borderline items in a 10-item feed, pool 50 % borderline | teen 1 (cap 15 %), adult 3 (cap 30 %) |
| Same, with 20 borderline items already in recent history | 0 |
| Adult with one interest, 40 matching items and 10 others | 2 of 10 slots from outside the interest (20 % minimum) |
| Teen on the equivalent pool (no diversity guard) | 0 of 10 |
| Child engaging 50 times each with four non-explicit topics | 0 topics added |
| Learned topics outside the explicit set after engaging with every topic | teen 3, adult 8 (the limits) |

### Moderator queue and feedback

| Check | Result |
|---|---|
| High-harm high-disagreement item versus low-harm unanimous item | ranked first and last of four |
| Escalated item with the lowest possible score versus the worst ordinary item, bandit trained 200 times against it | escalated item first |
| Five overrides in one category, five agreements in another | overridden category's item moves ahead; precedent suggestion becomes the moderators' action |
| Approving a blocked escalation item | rating becomes `adult`; still absent from child and teen feeds |

Time-to-review against FIFO and a plain risk sort has not been measured; that is Stage 4.

### API and RBAC

65 API tests through FastAPI's `TestClient`, using the host's own `get_current_user` and
`get_moderator` with a real `AuthDatabase`, on the dual store.

| Check | Result |
|---|---|
| All 6 endpoints without a token | rejected (401) |
| All 6 endpoints with an invalid token | 401 |
| Queue and item recommendation as a plain user | 403 |
| Escalated items as `moderator` / `content_analyst` | withheld from the queue, 403 on the item and on resolving it |
| Escalated items as `senior_moderator`, `policy_specialist`, `admin` | visible, first in the queue |
| Child requesting disallowed interests | 422 with the rejected topics; nothing saved |
| Owner changing trust level or parental controls | 403 |
| Owner raising a declared tier | 403; lowering allowed |
| Reading or changing another user's profile | 403 (admin allowed) |
| Routes with the flag off / on (import of `backend/main.py`) | 62 / 68 |

### Both databases

Every storage test runs three times: SQLite, Firestore and the dual store. The API tests
run on the dual store.

**Firestore was tested against an in-memory fake (`tests/fakes.py`), not a real Firestore
or an emulator**, because the project has neither and tests must not use the network. This
verifies the store's logic and the fallback behaviour during a simulated outage. It does not
verify behaviour against the real service.

## Mock-data replay (rating and gate only)

Command: `backend/.venv/Scripts/python.exe recommendation/evaluation/run_gate_report.py`.
Raw tables: `stage1_case_results.csv`, `stage1_rating_accuracy.csv`,
`stage1_sweep_matrix.csv`, `stage1_rejection_reasons.csv`, `stage1_gate_report.json`.
The report is byte-identical across two runs.

| | |
|---|---|
| Named cases as expected | 48 / 48 (42 rejections, 6 controls served) |
| Items given the rating their scenario expects | 800 / 800 |
| Profile x item combinations evaluated | 64,000 (80 profiles x 800 items) |
| Combinations served | 33,030 |
| Child/teen combinations evaluated / served | 43,200 / 15,888 |
| Leaks against the generator's ground-truth labels | **0** |
| Clean child items served to child profiles | 5394 / 5720 (94.3 %); the rest are parental blocks and strict settings |
| Clean teen items served to teen profiles | 3757 / 3920 (95.8 %) |

Every scenario that must not reach a minor (adult, violation, high disagreement, pending,
removed, escalation, legacy, malformed) was served to child and teen profiles 0 times.
Pending, removed and escalation-pending items were served to nobody.

What this does not show: the data is synthetic and labelled by the same generator that
built it, so it tests that the gate reacts correctly to reported signals, not that real
harmful content would be detected. Ranking, the bandit, the queue and the API do not exist
yet and are not measured. Case-by-case explanations are in
`docs/EXPLAINABLE_TEST_GUIDE.md`.

## Independent review of the gate

A separate subagent with a fresh context was given the nine safety rules and the four
source files, not the tests, docs or design reasoning, and asked to get a withheld item to
a child or teen. It ran its own scripts. It reviewed twice.

### Pass 1 - on the first Stage 1 implementation

The reviewer found leaks. The tier ordering itself held: no above-tier, blocked, unrated
or non-approved item got past the gate with validated models.

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Leak | `policy_flags` was used only for exact escalation matching; a string, a dict, or flags such as `suicide`, `csam`, `sexual_content` rated `all_ages` | Any non-empty or malformed `policy_flags` rates `adult` |
| 2 | Leak | Missing or falsy `violation_severity`, `media_risk_level`, detection booleans, violations, `moderation_action` read as "nothing found" | Every one of these must be present and well-formed, else `adult` |
| 3 | Leak | Default strictness was `medium`, so setting `low` widened the gate | `low` is the default and the baseline; other levels only tighten |
| 4 | Leak | Parental block was an exact match: blocking `gaming` did not block `gaming_family`; look-alike characters matched nothing | Word-level matching; non-ASCII parental labels rejected at validation |
| 5 | Leak (gate alone) | Escalation check missed `selfharm`, `suicide`, `extremism`, `groomer` and Unicode variants when the rating came from elsewhere | Stem matching on separator-free labels; gate now requires allow-listed topics for minors regardless of rating |
| 6 | Weakness | Disagreement measured only the largest verdict group: unanimous "remove" scored 0.0; a human-review entry zeroed it whatever its verdict or position | Rating below `adult` requires every judging agent to allow, or a human approval as the last decision |
| 7 | Weakness | `moderation_action` values `flagged`, `warned`, `remove` were ignored | Must be exactly `approved` |
| 8 | Weakness | `model_copy`, `model_construct` and attribute assignment bypassed validation; an unknown trust level switched the margin off | Gate re-validates both inputs and rejects on failure; `validate_assignment`; margin is on unless trust is positively parent-linked or verified |
| 9 | Weakness | Sensitive-topic check was exact match | Covered by the topic allow-list and stronger normalisation |

### Pass 2 - same reviewer, on the fixed code

It re-ran every pass-1 reproducer: 1, 3, 5, 7, 8, 9 rejected; 2, 4, 6 partly closed. It
found three remaining end-to-end leaks and several weaknesses.

| # | Severity | Finding | Fix |
|---|---|---|---|
| A | Leak | A missing or non-string `content_category` was dropped instead of raising the rating | Category must be a non-empty string, else `adult` |
| B | Leak | Decisions from the two bookkeeping agents were skipped even when the verdict was `remove` or `needs_review` (the pipeline does emit those on error paths) | Only their approvals are skipped; names matched exactly |
| C | Leak | Parental block missed plurals and word order: `sport` vs `sports`, `games` vs `gaming_family`, `kids music` vs `music_kids` | Stem-based, order-independent word matching |
| D | Weakness | Normalisation stripped punctuation, so `!none`, `safe?`, `approve?` read as the safe value | Enumerated fields use a strict normaliser that keeps punctuation |
| E | Weakness | The gate never read `toxicity_score` | Minors need a known score under the tier's limit (child 0.10, teen 0.35) |
| G | Weakness | The gate dropped empty labels that the rating treats as malformed | Empty labels fail the allow-lists for minors |
| I | Note | Trusted adults were served loosely matched statuses such as `approved!` | Status matched exactly for everyone |
| J | Note | A violations list of `["none"]` was rejected for minors | "No violation" markers are recognised |

Each fix has a regression test in `tests/test_rec_rating.py` or `tests/test_rec_safety_gate.py`.

### What has not been verified

- **The pass-2 fixes have not been seen by the reviewer.** They are covered by my own
  regression tests built from its reproducers, which pass, but there was no third
  independent pass. The final review in Stage 4 will cover them.
- **Stages 2 and 3 have had no independent review at all.** Everything in the "Stages 2
  and 3" section is from tests I wrote for code I wrote.
- Reviewer finding F stands by design: an item supplied with disagreement 0.33 and
  confidence 0.9 passes a verified child, because that is under the 0.45 threshold. Through
  the rating derivation such an item is `adult` anyway.
- Reviewer note H stands: a profile whose tier is lost in storage re-validates to the adult
  default. This follows from the chosen default and is the storage layer's job to prevent
  (Stage 2).
- Reviewer note: escalation stems miss terms such as "child abuse", "sextortion", "pro-ana"
  and leetspeak. Minors are still protected by the topic allow-list; the effect is on
  blocked-versus-adult for unapproved items and on queue escalation.

## Known limitations

See `docs/02_safety_policy.md`. The two that matter most for reading these results:

- No real moderation run was made. The Gemini-backed pipeline was not invoked, so the
  rating has been tested on constructed states, not on actual agent output.
- Real Firestore has not been used; see "Both databases".
- The running server was not started. The endpoints were exercised through `TestClient`
  on a fresh app; registration on the real app was checked only by importing
  `backend/main.py` with the flag on and off and listing its routes.
- A moderator decision made through the new feedback endpoint updates the recommender's
  copy of the item, not the host moderation database.
- No frontend exists for any of this. There is no profile page; preferences can only be
  set through the API.
