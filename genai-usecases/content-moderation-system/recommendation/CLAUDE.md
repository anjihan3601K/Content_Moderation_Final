# recommendation/ - working notes

Age-gated recommendation feed plus moderator review-queue prioritizer, added to the content
moderation platform. Additive, behind `RECOMMENDATION_ENABLED` (default `false`).

Read `docs/` first: `00_codebase_findings.md` (what the host project really looks like),
`CHANGELOG.md` (every file touched, current stage). Update both at the end of each stage.

## Folder map

- `src/` - feature code. Imported as `recommendation.src.*` with the project root on `sys.path`.
- `tests/` - pytest, no network. Files are named `test_rec_*.py`.
- `mock_data/` - seeded generator and its output.
- `evaluation/` - offline replay; writes to `results/`.
- `docs/` - findings, design, safety policy, test plan, changelog.

## Commands (from `genai-usecases/content-moderation-system/`)

```
backend/.venv/Scripts/python.exe -m pytest recommendation/tests -q
backend/.venv/Scripts/python.exe recommendation/evaluation/run_evaluation.py
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q      # host suite, baseline 3 passed
```

## Safety invariants - do not weaken

1. The gate (`src/safety_gate.py`) is deterministic and rule-based. Nothing learned, no
   environment variable and no profile field may let an item through that the rules reject.
2. `blocked` is served to nobody. An item rated above the viewer's tier is never served.
3. Unknown means unsafe: unrated items, unknown statuses, unknown categories and missing
   confidence signals are withheld from child and teen viewers.
4. Child and teen viewers only get items whose status is exactly `approved`.
5. The gate runs on the candidate pool and again on the final list just before it is returned.
   The ranker can reorder or drop survivors; it has no way to add an item.
6. Parental controls override interests, learned signals and the bandit.

## Host-project rules

- Do not read `.env` or credential files. Do not stage `backend/databases/*` or `frontend.zip`.
- Stage explicit paths; never `git add .`.
- Log every edit to a file outside `recommendation/` in `docs/CHANGELOG.md` with the reason.
