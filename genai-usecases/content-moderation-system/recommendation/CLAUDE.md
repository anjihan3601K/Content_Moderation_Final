# recommendation/ - working notes

Age-gated recommendation feed plus moderator review-queue prioritizer, added to the content
moderation platform. Additive, behind `RECOMMENDATION_ENABLED` (default `true`).

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
backend/.venv/Scripts/python.exe recommendation/mock_data/generate_mock_data.py
backend/.venv/Scripts/python.exe recommendation/evaluation/run_gate_report.py      # Stage 1 replay
backend/.venv/Scripts/python.exe recommendation/evaluation/check_case.py --help
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

## State of the work

All four stages are built, and the frontend has a profile card on the Settings page.
Open items, all listed in `results/RESULTS.md`: the final-review fixes have not been
independently re-checked; lost updates under concurrent requests (W4) are not fixed; the
profile page has not been run in a browser; real Firestore and a real moderation run have
never been exercised.

## Things that are easy to get wrong here

- `backend/src` and `recommendation/src` are both packages called `src`. Backend code is
  imported as `src.*` with `backend/` on the path; this feature as `recommendation.src.*`
  with the project root on the path. Tests set both up.
- The gate re-validates its inputs. Change an item with attribute assignment, not
  `model_copy(update=...)`, unless you mean to hand it an unchecked value.
- Do not write shell heredocs containing apostrophes in this environment; write the file
  with the editor tools and run it.
- `mock_repository` (tests) is session-scoped and shared. Pass `record_history=False`.

## Host-project rules

- Do not read `.env` or credential files. Do not stage `backend/databases/*` or `frontend.zip`.
- Stage explicit paths; never `git add .`.
- Log every edit to a file outside `recommendation/` in `docs/CHANGELOG.md` with the reason.
