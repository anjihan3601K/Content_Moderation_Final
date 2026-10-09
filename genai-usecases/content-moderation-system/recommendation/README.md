# Age-Gated Profile Recommender

An addition to the Content Moderation Platform:

- **Viewer feed** - recommendations filtered by a deterministic age gate before and after
  personalization.
- **Moderator queue** - review items ordered by expected harm, agent disagreement and
  exposure, with similar past cases shown for each.

It is off by default. With the flag off the platform behaves exactly as before.

## Turn it on

In `backend/.env`:

```
RECOMMENDATION_ENABLED=true
```

Then start the backend as usual (`cd backend && python main.py`). On startup the six
endpoints below are registered, and every item that goes through moderation is rated and
stored for the feed and the queue.

## Endpoints

| Method and path | Who |
|---|---|
| `GET /api/recommendations/feed` | any logged-in user |
| `GET /api/profiles/{id}/preferences` | owner or admin |
| `PUT /api/profiles/{id}/preferences` | owner or admin |
| `GET /api/moderation/queue/next` | moderator roles |
| `GET /api/items/{id}/recommendation` | moderator roles |
| `POST /api/recommendations/feedback` | any user (engagement), moderator roles (overrides) |

Details and access rules: `docs/01_design.md`.

## Profile page

With the flag on, the existing Settings page in the frontend shows a "Viewer Profile" card
(`frontend/src/components/Settings/ViewerProfile.jsx`). The viewer enters a date of birth;
the page works out the age group and sends only the age group. The date of birth is never
sent to the server or stored. Interests are chosen from the topics allowed for that age
group. Parental controls are shown read-only; an admin sets them through the API.

## Config flags

| Variable | Default | Effect |
|---|---|---|
| `RECOMMENDATION_ENABLED` | `false` | Master switch for the rating hook and the endpoints |
| `HIGH_UNCERTAINTY_THRESHOLD` | `0.45` | Agent-disagreement limit for minors. Can only be lowered; clamped to 0.05-0.45 |
| `BORDERLINE_DRIFT_CAP` | `0.15` | Max borderline share of a teen's recent feed (adult: twice this) |
| `ADULT_DIVERSITY_MIN` | `0.20` | Share of adult feed slots reserved for topics outside the interests |
| `RECOMMENDATION_DB_PATH` | `backend/databases/recommendation_data.db` | SQLite file for the feature's own tables |

## Run the checks

From `genai-usecases/content-moderation-system/`:

```
backend/.venv/Scripts/python.exe -m pytest recommendation/tests -q        # several minutes
backend/.venv/Scripts/python.exe recommendation/mock_data/generate_mock_data.py
backend/.venv/Scripts/python.exe recommendation/evaluation/run_gate_report.py
backend/.venv/Scripts/python.exe recommendation/evaluation/check_case.py --help
backend/.venv/Scripts/python.exe recommendation/evaluation/run_evaluation.py   # about 4 minutes; needs matplotlib
backend/.venv/Scripts/python.exe recommendation/evaluation/run_live_demo.py    # real pipeline, ML on, stand-in LLM
```

No network, API key or database server is needed.

## Folder map

```
recommendation/
  src/
    config.py           flags, thresholds, topic lists
    models.py           Pydantic schemas
    rating.py           Stage 1: audience rating from pipeline output
    safety_gate.py      Stage 1: the deterministic gate
    embeddings.py       Stage 2: TF-IDF behind an interface
    bandit.py           Stage 2: Thompson sampling
    personalization.py  Stage 2: tier topic rules, ranker, drift and diversity guards
    service.py          feed assembly: gate -> rank -> gate
    moderator_queue.py  Stage 3: queue priority and precedent retrieval
    feedback.py         Stage 3: engagement and moderator overrides
    store.py            SQLite and Firestore storage
    telemetry.py        OpenTelemetry spans and metrics
    api.py              the endpoints
    integration.py      hook called by the moderation workflow
  tests/                pytest suite
  mock_data/            seeded generator and generated JSON
  evaluation/           replay scripts
  results/              RESULTS.md and raw tables
  docs/                 findings, design, safety policy, test plan, test guide, changelog
```

## Read next

- `docs/02_safety_policy.md` - what the gate enforces and its limitations
- `docs/EXPLAINABLE_TEST_GUIDE.md` - step-by-step verification with every case explained
- `results/RESULTS.md` - measured results and what has not been verified
- `docs/CHANGELOG.md` - every file created or changed, including the existing ones
