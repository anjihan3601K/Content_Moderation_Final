# Results

Real output from real runs only. Sections for Stages 2 to 4 (personalization, queue,
evaluation tables, charts, ablations) are added when those stages run. Nothing below is
estimated.

## Status

| Stage | State |
|---|---|
| 0 - baseline and findings | done |
| 1 - audience rating and safety gate | done, reviewed twice, awaiting approval |
| 2 - profiles and personalization | not started |
| 3 - moderator queue, feedback, endpoints | not started |
| 4 - mock data, evaluation, final review | not started |

## Test outcomes (2026-10-08)

| Suite | Command | Result |
|---|---|---|
| Host suite, baseline (before any change) | `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q` | 3 passed |
| Host suite, after Stage 1 | same | 3 passed |
| Recommendation tests | `backend/.venv/Scripts/python.exe -m pytest recommendation/tests -q` | 870 passed, 1 skipped |

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

This run covers the gate in isolation. The same invariant through the full feed path
(ranker, bandit, drift guard) is a Stage 2 deliverable and has not been run.

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
- Firestore has not been touched yet. When it is (Stage 2), it will be tested against an
  in-memory fake, because the project has no emulator or mock.
