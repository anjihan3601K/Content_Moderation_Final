# 03 - Test plan

Run from `genai-usecases/content-moderation-system/`:

```
backend/.venv/Scripts/python.exe -m pytest recommendation/tests -q
```

No network, no real database, seeded randomness. The Stage 4 section (evaluation) is added when that stage lands.

## Stage 1

| File | What it checks | Why |
|---|---|---|
| `test_rec_rating.py` | Each rating rule; toxicity boundaries; every non-approved status rates at least `adult`; deleting or corrupting any one input field never rates below `adult`; escalation spelling variants; agent agreement signals including human review ordering | The rating is the gate's main input. Rule 9 (missing signal must not lower a rating) is the property most easily broken by a default value |
| `test_rec_safety_gate.py` | Full rating x tier x trust matrix; blocked never served; unrated handling; every backend `ContentStatus` value; uncertainty margin and its scaling by trust and strictness; parental controls; escalation; topic and violation allow-lists; items changed through `model_copy`; invalid profiles; final-output check | One test per rule, plus one per defect found in review |
| `test_rec_gate_invariants.py` | 12,000 seeded random profile/item pairs checked against an oracle that restates the safety rules without sharing code with the gate; gate decisions unchanged when interests, learned weights and history are stripped; final check is idempotent and never adds items | The main safety evidence. The oracle is deliberately simpler and weaker than the gate, so it can only fail when a rule is actually broken. The test asserts a minimum number of passes so it cannot succeed vacuously |
| `test_rec_pipeline_hook.py` | The hook in `backend/src/agents/workflow.py`: no change to state when the flag is off, rates when on, swallows a rating failure, tolerates a missing state | The hook is the only code path this stage adds to the existing pipeline |

## Mock data (Stage 1 addendum)

| File | What it checks | Why |
|---|---|---|
| `test_rec_mock_data.py` | Generator is reproducible and matches the files on disk; dataset sizes; placeholder text only; all 48 named cases; every gate reason code is exercised; every item gets its scenario's rating; no leak over 80 x 800 combinations; lower trust never sees more; parental controls never widen | Turns the mock data into evidence, and guards against the data and the code drifting apart |

## Stage 2

| File | What it checks | Why |
|---|---|---|
| `test_rec_store.py` | Items, profiles, events, bandit arms and precedents round-trip; unreadable records are skipped; a missing profile is the adult default while a damaged one is treated as child; unknown collection names are refused. Every test runs on SQLite, on Firestore and on the dual store; plus SQLite persistence, table list, dual-write order and behaviour during a Firestore outage | "Both databases" requirement, and the storage layer must not be a way to lose a profile's tier |
| `test_rec_personalization.py` | Explicit-interest validation per tier; child engagement cannot add a topic or exceed the baseline weight; learned drift is capped; hostile stored weights are ignored; TF-IDF ordering and determinism; bandit learning, seeding, persistence; ranker output is always a subset of its input; precision@10 against a random baseline on mock data; borderline share cap with and without history; risk-trend penalty; adult diversity guard | Each tier rule and each guard has a test that fails if the rule is removed |
| `test_rec_feed_service.py` | Tier-appropriate feeds on every backend; default profile; limit clamping; history recording; a ranker that injects or rewrites items is neutralised by the final gate; a damaged profile gets the child feed; **1,040 feeds over the full mock data with random interests, hostile learned signals, saturated history and random bandit state, checked against ground truth** | The most important test in the suite: the invariant through the whole path, not just the gate |

## Stage 3

| File | What it checks | Why |
|---|---|---|
| `test_rec_queue_feedback.py` | Queue membership; the priority formula; high-harm high-disagreement above easy items; escalation first even against an adversarially trained bandit; learned multiplier bounds; deterministic ties; precedent retrieval and exclusions; suggestion from precedents and from rules; overrides update the bandit, the precedent memory and the item; approving a blocked item never rates it below adult; engagement learning within tier rules; telemetry spans and metrics read back through the OpenTelemetry SDK | Queue, feedback-loop and telemetry requirements |
| `test_rec_api.py` | Every endpoint without a token and with an invalid token; feed per tier; own-profile enforcement; preferences read/write rules, tier-validation failures (422 with the rejected list), admin-only fields, tier raise/lower rules; queue RBAC and escalated-item visibility per role; item recommendation with precedents; engagement and override feedback with role checks; body validation; route registration; flag on/off; no path collision with existing routes; senior-role list matches the host's dependency | Uses the host's real `get_current_user` / `get_moderator` and a real `AuthDatabase`, on the dual store, so auth and both databases are exercised end to end |
| `test_rec_pipeline_hook.py` | As Stage 1, plus: the hook stores the rated item when a repository is registered, stores nothing with the flag off, and survives a storage failure | The only code path added to the existing pipeline |

## What is not tested

- Real Firestore. The Firestore store is tested against `tests/fakes.py`, an in-memory
  stand-in written for these tests. It proves the store's logic, not Firestore's behaviour
  (indexes, quotas, latency, permissions).
- A real moderation run. The Gemini-backed agents are never invoked.
- The running server with its lifespan. Endpoints are tested through FastAPI's
  `TestClient` on a fresh app carrying the same router and the host's auth dependencies.
- The frontend. No frontend file was changed.
- Concurrency. Bandit arms and profile history are read-modify-write without locking.

## Runtime

The suite takes several minutes. Almost all of it is the 1,040-feed invariant and the
64,000-combination sweep. To iterate quickly, run a single file.

## Regression

`cd backend && .venv/Scripts/python.exe -m pytest tests/ -q` before and after each stage.
Baseline 3 passed. This suite does not exercise the existing API; see
`00_codebase_findings.md`.
