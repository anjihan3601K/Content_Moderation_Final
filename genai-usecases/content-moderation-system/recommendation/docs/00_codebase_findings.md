# 00 - Codebase findings (before building)

Recorded 2026-10-08 on branch `feature/recommendation-system`, created from `anjani` at `be07607`.
Paths are relative to `genai-usecases/content-moderation-system/` (PROJECT).

## Baseline test run

| | |
|---|---|
| Command | `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q` |
| Result | **3 passed, 0 failed**, 2 warnings, 12.93 s |
| Files | `tests/test_media_moderation.py` (2), `tests/test_uploaded_image_moderation.py` (1) |

The whole pre-existing suite is these 3 tests. There is no `conftest.py`, no fixtures and no
`TestClient` test, so the suite gives almost no regression coverage of the 58 existing
endpoints. "No regressions" in this project means "these 3 tests still pass" plus the route-list
check described in `03_test_plan.md`; it does not mean the existing API was exercised.

## Git state at the start

- Working tree was not clean: `backend/src/core/models.py` modified (adds `AudienceRating`
  and `ContentState.audience_rating`, used by nothing), two tracked database binaries modified
  (`moderation_auth.db`, `chroma.sqlite3`), `frontend.zip` and `recommendation/` untracked.
- The database binaries and `frontend.zip` are never staged by this work.
- `recommendation/` already held a 5-file draft (`src/config.py`, `models.py`,
  `safety_gate.py`, `personalization.py`, `moderator_queue.py`) with no tests. It is reworked
  in place; see "Draft gate defects" below.

## What the brief assumed versus what exists

| Brief | Actual |
|---|---|
| 40+ endpoints | 58 `@app.*` routes, all in `backend/main.py` (3322 lines). No `APIRouter`. Prefix `/api/<area>/`, no version segment. |
| 6-agent LangGraph pipeline | `StateGraph(ContentState)` built in `backend/src/agents/workflow.py:215`. Nodes: `entry_router`, `content_analysis`, `toxicity_detection`, `policy_check`, `react_loop`, `hitl_review`, `reputation_scoring`, `appeal_review`, `action_enforcement`, `fast_mode`. Several nodes can route straight to `END`. |
| Agent output models | `ContentState` is a `TypedDict(total=False)` in `backend/src/core/models.py:177`. Agents append `AgentDecision` dataclasses to `agent_decisions`. No Pydantic in this file. |
| Per-agent confidence and disagreement | `AgentDecision.confidence` is mostly a hard-coded constant (0.85, 0.80, 1.0). `overall_confidence` is initialised to 0.0 and never written. Consensus is computed in `agents.py:1590` but only stored inside a JSON string. |
| 5-tier RBAC | Six role strings: `user` plus `moderator`, `senior_moderator`, `content_analyst`, `policy_specialist`, `admin`. Dependencies `get_current_user`, `get_moderator`, `get_senior_moderator`, `get_admin` are in `backend/main.py:201-245`. `get_moderator` and `get_senior_moderator` are used on no route. Only 12 of 58 endpoints (all `/api/auth/*`) require auth; HITL, content and analytics endpoints are open. |
| SHA-256 auth | Unsalted SHA-256 (`auth_db.py:108`). Session tokens in `user_sessions`; `expires_at` is never set or checked. |
| Dual storage through an abstraction | No abstraction. `FirebaseDatabaseManager` (`backend/src/database/firebase_db.py:28`) owns a `ModerationDatabase` and an `AuthDatabase`, writes SQLite first and Firestore when credentials resolve, reads Firestore then falls back. Schemas are `CREATE TABLE IF NOT EXISTS` at construction; there is no migration mechanism. |
| Firestore emulator or mock | None in the repo. |
| OpenTelemetry instrumentation | `backend/src/utils/observability.py` defines a tracer wrapper and a custom in-memory metrics class, but no module imports it. No OTel meter exists. The running app emits no spans. |
| Config | `os.getenv` inline, string booleans compared with `.lower() == "true"`. No settings module. |
| Logging | `logging.getLogger(__name__)`, f-string messages. |
| Dependencies | `backend/requirements.txt` installed with `uv pip`; no lock file. Python 3.12.12. `numpy` 2.5.1, `httpx` 0.28.1 and `pytest` 9.1.1 are installed but not listed. `scikit-learn`, `sentence-transformers`, `matplotlib`, `hypothesis` are not installed. |

## Labels the pipeline can actually emit

- Final statuses: `approved`, `removed`, `warned`, `flagged`, `under_review`,
  `pending_human_review`, `escalated`, plus in-flight statuses (`submitted`, `analyzing`, ...).
- `moderation_action`: `approved`, `removed`, `warned`, `user_suspended`, `user_banned`, `flagged`.
- Policy violations from `check_policy_violations` (`backend/src/utils/tools.py:257`):
  `hate_speech`, `harassment`, `violence`, `spam`, `sexual_content`, `misinformation`, `self_harm`.
  Fast mode returns a free-form LLM list.
- `content_category` is LLM free-form text, default `"general"`.
- Nothing emits `violent_extremism` or `grooming`. Those escalation categories are reachable
  today only from mock data or a future detector.

## Draft gate defects found (fixed in Stage 1)

1. Status was a deny-list, so `submitted`, `analyzing`, `escalated`, `warned`,
   `user_suspended` and any unknown string passed for a child.
2. `derive_audience_rating` returned `all_ages` for any unknown category.
3. `overall_confidence` defaulted to 1.0 and `agent_disagreement` to 0.0, so a missing
   signal read as "certain".
4. Escalation and parental blocks matched category and topics only, never policy violations.
5. `strictness_level` was never read; a self-declared adult was treated like a verified one.
6. The gate ran once before ranking, not on the final output.
7. `DEFAULT_UNRATED_RATING` was an environment variable, so a config value could turn
   unrated items into `all_ages`.

## Existing problems noticed and deliberately not touched

- `main.py` calls 18 methods on `FirebaseDatabaseManager` that the class does not define
  (for example `get_story_by_id`, `save_manual_review`); those paths raise `AttributeError`.
- Paused HITL reviews live in a process-memory dict (`main.py:65`) and are lost on restart.
- `backend/databases/README.md` describes tables and collections that do not exist.
- Three database binaries are tracked in git although `.gitignore` lists `*.db` / `*.sqlite3`.
