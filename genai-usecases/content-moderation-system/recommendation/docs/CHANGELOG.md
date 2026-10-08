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
