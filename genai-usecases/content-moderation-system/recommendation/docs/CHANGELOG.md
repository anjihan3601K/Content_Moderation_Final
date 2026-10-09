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

## Stage 2 - profiles, storage, personalization

Created
- `recommendation/src/store.py` - `DocumentStore` protocol, SQLite and Firestore backends,
  dual store in the host's write-SQLite-then-Firestore pattern, typed repository
- `recommendation/src/embeddings.py` - `EmbeddingProvider` protocol and TF-IDF implementation
- `recommendation/src/bandit.py` - Thompson sampling
- `recommendation/src/service.py` - feed assembly: gate, rank, gate
- `recommendation/src/telemetry.py` - OpenTelemetry spans and metrics
- `recommendation/tests/fakes.py` - in-memory Firestore stand-in
- `recommendation/tests/test_rec_store.py`, `test_rec_personalization.py`, `test_rec_feed_service.py`
- `recommendation/docs/01_design.md`, `recommendation/README.md`

Rewritten in place (draft replaced)
- `recommendation/src/personalization.py` - tier topic rules that reject instead of silently
  dropping, real drift guard (share cap plus trend penalty), diversity guard that uses
  `ADULT_DIVERSITY_MIN`. The draft's "TF-IDF" was Jaccard overlap; relevance now uses the
  embedding interface.

Modified (inside recommendation/)
- `src/models.py` - profile `tier_declared`, request/response models, `label_matches`,
  cached label normalisation
- `src/config.py` - personalization and queue settings, `recommendation_db_path()`
- `src/safety_gate.py` - profile validated once per pool instead of once per item (same result)

## Stage 3 - moderator queue, feedback loop, endpoints

Created
- `recommendation/src/feedback.py` - engagement learning and moderator overrides
- `recommendation/src/api.py` - router factory, service container, `register_recommendation_routes`
- `recommendation/src/integration.py` - `on_moderation_complete`, called by the workflow hook
- `recommendation/tests/test_rec_queue_feedback.py`, `test_rec_api.py`
- `recommendation/requirements-dev.txt`

Rewritten in place (draft replaced)
- `recommendation/src/moderator_queue.py` - escalation as a leading sort key instead of
  `+1000`; unknown signals count as maximum uncertainty; learned multiplier; precedent
  retrieval through the embedding interface; suggestion with its source. The draft promised
  a feedback loop it did not contain.

Existing files modified
- `backend/main.py` - a block of 6 lines after the auth dependencies: when
  `RECOMMENDATION_ENABLED=true`, import `register_recommendation_routes` and call it with
  the host's own `get_current_user` and `get_moderator`, and a provider for the existing
  Firestore client. With the flag off the block does not run and the route list is unchanged.
- `backend/src/agents/workflow.py` - the Stage 1 hook now calls
  `recommendation.src.integration.on_moderation_complete` (rates and stores the item)
  instead of `rating.apply_audience_rating` (rated only). Same guard, same try/except.
- `backend/requirements.txt` - `numpy==2.5.1` pinned. Already installed as a transitive
  dependency; now imported directly by `embeddings.py`.
- `backend/.env.example` - documents `RECOMMENDATION_ENABLED=false` and the optional
  settings, as comments. Appended without reading the file.

New dependencies
- Runtime: `numpy==2.5.1` (TF-IDF vectors, cosine similarity). No new package is downloaded.
- Development: `pytest==9.1.1`, `httpx==0.28.1` in `recommendation/requirements-dev.txt`.
  Both were already in the venv but listed nowhere. `httpx` is what FastAPI's `TestClient` needs.
- Not added: scikit-learn, sentence-transformers, hypothesis, matplotlib.

Migrations
- None. New tables are created with `CREATE TABLE IF NOT EXISTS` in a new file,
  `backend/databases/recommendation_data.db` (git-ignored by the root `*.db` rule), the
  first time an endpoint is used with the flag on. New Firestore collections `rec_items`,
  `rec_profiles`, `rec_events`, `rec_bandit_arms`, `rec_precedents` are created on first write.

Config flags added
- `BORDERLINE_DRIFT_CAP` (0.15), `ADULT_DIVERSITY_MIN` (0.20), `RECOMMENDATION_DB_PATH`.

## Stage 4 - evaluation, final review, profile page

Created
- `recommendation/evaluation/run_evaluation.py` - offline replay: leak rate, relevance
  against baselines, bandit simulation, diversity and drift, queue, precedents; ablations
  for gate, bandit, learning and precedents
- `recommendation/results/evaluation_metrics.json`, `evaluation_*.csv` (7), `chart_*.png` (6)
- `recommendation/tests/test_rec_final_review.py` - regression tests for the final review
- `frontend/src/components/Settings/ViewerProfile.jsx` - profile card: date of birth to age
  group (only the age group is sent or stored), interests, read-only parental controls

Modified (inside recommendation/)
- `mock_data/generate_mock_data.py`, `resolved_cases.json` - resolved cases now follow a
  per-category norm 80 % of the time, so precedent retrieval has something to recover.
  Items, profiles and engagement are byte-identical to before. Catalogue cases R16-R19 and
  C06 now carry an explicit human approval.
- `src/store.py` - restricted fallback for damaged profiles, never written back;
  `rec_pending_sync` table and SQLite-first reads for documents whose Firestore write failed
- `src/rating.py` - high-risk items need a human approval to leave `blocked`; text is never
  parsed as a score; escalation terms split across labels; `human_reviewed` on built items
- `src/safety_gate.py` - borderline derived from toxicity as well as the stored flag
- `src/moderator_queue.py` - status `escalated` counts as escalated; unreviewed high-risk
  items are queued whatever their status
- `src/feedback.py` - decisions mark the item human-reviewed; `escalate` sets the flag;
  approve and warn rate `adult` at most; precedents record escalation
- `src/integration.py` - a moderator's decision outranks a machine re-rating; items
  without a content id are not stored
- `src/api.py` - raising a tier is always admin-only; damaged profiles need an admin (409);
  escalated precedents hidden from non-senior roles; async moderator dependency refused
- `src/models.py` - `record_damaged`, `human_reviewed`, `PrecedentCase.is_escalated`;
  stricter number and parental-label validation
- `evaluation/gate_harness.py`, `evaluation/check_case.py` - `human_approved` support

Existing files modified
- `frontend/src/services/api.js` - new `recommendationAPI` export (three calls). Nothing
  existing changed.
- `frontend/src/components/Settings/UserSettings.jsx` - imports `ViewerProfile` and renders
  it as one more card on the Settings page. Two lines of import and one grid item added.
- No backend file was changed in Stage 4.

New dependencies
- Development only: `matplotlib==3.11.2` (charts in `run_evaluation.py`), with its
  dependencies `contourpy==1.4.0`, `cycler==0.12.1`, `fonttools==4.66.1`,
  `kiwisolver==1.5.1`, `pyparsing==3.3.3`. Installed into `backend/.venv` with `uv pip`
  and listed in `recommendation/requirements-dev.txt`. Not imported by any runtime code.

Migrations
- None for existing data. The feature's own SQLite file gains one table,
  `rec_pending_sync`, created with `CREATE TABLE IF NOT EXISTS`.

## Live run and the fixes it led to (2026-10-09)

Created
- `recommendation/evaluation/standin_llm.py` - rule-based stand-in for the language model,
  used only by the demo
- `recommendation/evaluation/run_live_demo.py` - sample posts and images through the real
  workflow with ML models and the feature on
- `recommendation/results/live_demo_report.txt`, `live_demo_results.json`

Modified (inside recommendation/)
- `src/rating.py` - an absent `moderation_action` is accepted for approved content; the
  ReAct synthesis step's score is not used as a confidence. Both found by the live run.
- `tests/test_rec_rating.py` - tests for both

Existing files modified: none. Dependencies: none. Migrations: none.
The demo patches the agents' model class in memory for its own process only; no backend
file is edited and no provider is called.
- `mock_data/generate_mock_data.py`, `items.json` - one mock item (`item-0799`) was labelled
  "malformed" for having no `moderation_action`. That is now known to be normal, so its
  defect was changed to a missing `policy_flags`. No other mock record changed, and the
  gate report and evaluation metrics are byte-identical to before.

## Firebase removed from the platform (2026-10-09, at the owner's request)

Existing files modified
- `backend/main.py` - the global `db` is now a `ModerationDatabase` (SQLite) instead of
  `FirebaseDatabaseManager`; the two Firebase user-sync blocks (registration and user
  update) are removed; the recommendation routes are registered without a Firestore client.
  Side effect: 18 methods `main.py` called that the Firebase manager never defined (for
  example `update_user_reputation`, `record_user_action`, `save_manual_review`) now resolve,
  because `ModerationDatabase` has them. Signatures of the shared methods were compared and
  are identical.
- `backend/requirements.txt` - `firebase-admin` removed.
- `frontend/package.json` - `firebase` removed.

Existing files deleted (all Firebase-only, none imported elsewhere; recoverable from git)
- `backend/src/database/firebase_db.py`
- `backend/scripts/initialize_firebase_users.py`, `migrate_sqlite_to_firebase.py`, `test_registration.py`
- `frontend/src/firebase.js`

Not changed
- The recommendation feature still contains its optional Firestore store
  (`src/store.py`) and the in-memory fake used by its tests. Nothing passes it a client
  any more, so it runs on SQLite only.
- `firebase-admin` is still installed in `backend/.venv`, and `firebase` in
  `frontend/node_modules`; they are just no longer required.

Also: `evaluation/run_live_demo.py` gained a `--real-llm` mode that uses the backend's
configured provider with a key taken from the process environment only.

## Gemini model update (2026-10-09, at the owner's request)

Existing files modified
- `backend/src/agents/agents.py` - the agents' model name now comes from `GEMINI_MODEL`
  (default `gemini-3.8-flash`) instead of the hard-coded, retired `gemini-2.0-flash`; both
  model objects are wrapped in a new `TextChatModel`, which returns the reply as plain
  text because current Gemini models return a list of content blocks.
- `backend/.env.example` - documents `GEMINI_MODEL`.
