# Changelog - recommendation feature

Branch `feature/recommendation-system` (from `anjani` at `be07607`).

## Stage 0 - baseline

Created
- `recommendation/docs/CHANGELOG.md`
- `recommendation/CLAUDE.md`

Rewritten
- `recommendation/docs/00_codebase_findings.md` - replaced the earlier note, which named the
  wrong SQLite file and described RBAC dependencies as already enforced.

Existing files modified
- `backend/src/core/models.py` - adds `AudienceRating` enum and `ContentState.audience_rating`.
  This edit was already in the working tree before this work started; it is committed here
  because the feature depends on it. Additive; nothing existing reads it.

Committed as found (pre-existing untracked draft, reworked in Stage 1)
- `recommendation/src/{config,models,safety_gate,personalization,moderator_queue}.py`

Dependencies, migrations, config flags: none.

## Stage 1 - audience rating and safety gate

Created
- `recommendation/__init__.py`, `recommendation/src/__init__.py`
- `recommendation/src/rating.py` - rating derivation, agent agreement signals, pipeline hook target
- `recommendation/tests/conftest.py`, `test_rec_rating.py`, `test_rec_safety_gate.py`,
  `test_rec_gate_invariants.py`, `test_rec_pipeline_hook.py`
- `recommendation/docs/02_safety_policy.md`, `recommendation/docs/03_test_plan.md`
- `recommendation/results/RESULTS.md`

Rewritten in place (draft replaced)
- `recommendation/src/config.py` - flag now defaults to off; `DEFAULT_UNRATED_RATING` env
  knob removed; uncertainty threshold clamped; status allow-lists; escalation stems.
- `recommendation/src/models.py` - safety fields default to unknown; validators;
  `validate_assignment`; `GateReason`, `Strictness`; stronger `normalize_label`.
- `recommendation/src/safety_gate.py` - fail-closed rule sequence, final-output check.

Not yet reworked (Stage 2 and 3): `src/personalization.py`, `src/moderator_queue.py`. They
still import, but `personalization.py` concatenates topic tuples with `+` on lists and
will be replaced.

Existing files modified
- `backend/src/agents/workflow.py` - new private `_apply_audience_rating(state)` and one
  call to it in `process_content` after the graph finishes (covers `resume_from_hitl`,
  which calls `process_content`). No-op unless `RECOMMENDATION_ENABLED=true`; exceptions
  are caught and logged so the moderation result cannot change.
- `backend/src/core/models.py` - `ContentState.agent_disagreement: Optional[float]` added
  (TypedDict is `total=False`, so nothing else is affected).
- `backend/main.py` - one line appending the project root to `sys.path` so the optional
  `recommendation` package is importable. No routes registered yet.

Config flags
- `RECOMMENDATION_ENABLED` (default `false`) - when off the pipeline output is unchanged.
- `HIGH_UNCERTAINTY_THRESHOLD` (default and ceiling 0.45, floor 0.05) - can only tighten.

Dependencies: none added. Migrations: none.

## Stage 1 addendum - mock data and rejection-case verification

Requested ahead of Stage 2. Covers the rating and gate only; nothing from Stages 2 or 3 was built.

Created
- `recommendation/mock_data/generate_mock_data.py` and its output `items.json` (800),
  `profiles.json` (80), `engagement.json` (2,720), `resolved_cases.json` (200),
  `rejection_cases.json` (48). Fixed seed 20261008. Placeholder text and labels only.
- `recommendation/evaluation/gate_harness.py` - shared replay helpers and ground-truth leak check
- `recommendation/evaluation/run_gate_report.py` - catalogue plus 64,000-combination sweep
- `recommendation/evaluation/check_case.py` - try one case by hand from the command line
- `recommendation/tests/test_rec_mock_data.py`
- `recommendation/results/stage1_*.csv`, `stage1_gate_report.json`
- `recommendation/docs/EXPLAINABLE_TEST_GUIDE.md`

Modified (inside recommendation/)
- `src/rating.py` - `build_item_from_state`, the glue from pipeline state to gate item
- `src/config.py` - `BORDERLINE_TOXICITY_THRESHOLD` (0.25)

Existing files modified: none. Dependencies: none. Migrations: none.
