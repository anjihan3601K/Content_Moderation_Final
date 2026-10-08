# 03 - Test plan

Run from `genai-usecases/content-moderation-system/`:

```
backend/.venv/Scripts/python.exe -m pytest recommendation/tests -q
```

No network, no real database, seeded randomness. Sections for Stages 2 to 4 are added as
those stages land.

## Stage 1

| File | What it checks | Why |
|---|---|---|
| `test_rec_rating.py` | Each rating rule; toxicity boundaries; every non-approved status rates at least `adult`; deleting or corrupting any one input field never rates below `adult`; escalation spelling variants; agent agreement signals including human review ordering | The rating is the gate's main input. Rule 9 (missing signal must not lower a rating) is the property most easily broken by a default value |
| `test_rec_safety_gate.py` | Full rating x tier x trust matrix; blocked never served; unrated handling; every backend `ContentStatus` value; uncertainty margin and its scaling by trust and strictness; parental controls; escalation; topic and violation allow-lists; items changed through `model_copy`; invalid profiles; final-output check | One test per rule, plus one per defect found in review |
| `test_rec_gate_invariants.py` | 12,000 seeded random profile/item pairs checked against an oracle that restates the safety rules without sharing code with the gate; gate decisions unchanged when interests, learned weights and history are stripped; final check is idempotent and never adds items | The main safety evidence. The oracle is deliberately simpler and weaker than the gate, so it can only fail when a rule is actually broken. The test asserts a minimum number of passes so it cannot succeed vacuously |
| `test_rec_pipeline_hook.py` | The hook in `backend/src/agents/workflow.py`: no change to state when the flag is off, rates when on, swallows a rating failure, tolerates a missing state | The hook is the only code path this stage adds to the existing pipeline |

Not covered in Stage 1: the gate as called through the feed service (Stage 2 repeats the
invariant test end to end), storage, API, and a real moderation run through LangGraph
(needs the Gemini API; out of scope for offline tests).

## Regression

`cd backend && .venv/Scripts/python.exe -m pytest tests/ -q` before and after each stage.
Baseline 3 passed. This suite does not exercise the existing API; see
`00_codebase_findings.md`.
