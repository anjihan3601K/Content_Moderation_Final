# 02 - Safety policy

What the gate enforces, in the order it enforces it. Code: `src/rating.py`, `src/safety_gate.py`,
constants in `src/config.py`.

## Principle

The platform moderates conduct, not belief. Ratings and escalation react to violence,
incitement, harassment, grooming, self-harm promotion, sexual content, scams and spam. No
rule keys on a political or religious position, and no ideology is blocked as such. The
`politics_intro` topic is a sensitive teen topic (parent-allowed), not a blocked one.

## Ratings and tiers

| Rating | Rank | Meaning |
|---|---|---|
| `all_ages` | 1 | Approved, every agent allowed it, all signals clean, every topic on the child list |
| `teen` | 2 | As above but a topic is teen-only, toxicity 0.10-0.35, severity `low`, or a `spam`/`copyright` violation |
| `adult` | 3 | Anything else that is not blocked, including every case where a signal is missing or unrecognised |
| `blocked` | 4 | Removed, author sanctioned, toxicity >= 0.75, or an escalation category that no human moderator has approved (approval by the agents alone is not enough) |

Tiers: `child` (1), `teen` (2), `adult` (3). An item is served only if rating rank <= tier rank.
`blocked` is served to nobody.

## How a rating is derived

The item starts at `all_ages`; each rule can only raise it. Rating below `adult` requires all of:

- `status` is exactly `approved`; `moderation_action` is either absent (the pipeline does
  not write it for content approved on the normal path) or exactly `approved`;
  `content_removed` is `False`.
- Every judging agent's verdict is "allow", or the last decision is a human approval.
  Approvals from the Action Enforcement and HITL Checkpoint agents are not counted: they
  always report approve/1.0. The ReAct synthesis step's verdict is counted, but the score
  it reports is not treated as a confidence.
- `toxicity_score` is a number in [0, 1] below the threshold.
- `policy_violations` is a list containing nothing beyond `spam`/`copyright`; `policy_flags`
  is an empty list.
- `violation_severity` is `none` (or `low` for teen); the four detection booleans are
  exactly `False`; `media_risk_level` is `none`/`low`/`safe`.
- `content_category` is a non-empty string and every category and topic label is on the
  tier's allow-list.

Enumerated fields (status, action, severity, media risk, verdicts) are compared after
folding case and space/hyphen/underscore only, so `"!none"` or `"approved?"` do not match.

A field that is missing, `None`, of the wrong type or holding an unknown value raises the
rating to `adult`. It never counts as "nothing detected".

## Gate checks (first failure wins)

Inputs are re-validated first; an item or profile that fails validation, or any check that
raises, is a rejection (`invalid`).

| # | Check | Applies to | Reason code |
|---|---|---|---|
| 1 | Rating `blocked` or a removed/banned/suspended status | everyone | `blocked` |
| 2 | Status not `approved` or `warned` | everyone | `pending_review` (minors) / `not_servable_status` |
| 3 | No rating (legacy) | minors and self-declared adults withheld; trusted adults see it as `adult` | `unrated` |
| 4 | Parental blocked category (word-stem match in any order on category, topics, violations) or parental rating cap | everyone with controls | `parental_block` |
| 5 | Escalation category on any label, or `escalated` flag | child, teen | `escalation` |
| 6 | Rating above tier | everyone | `above_tier` |
| 7 | A topic not on the tier's allow-list, no topic at all, an empty label, a violation outside the tolerated set, or toxicity unknown or at/above the tier limit (child 0.10, teen 0.35) | child, teen | `unlisted_topic`, `policy_violation`, `toxicity` |
| 8 | Sensitive teen topic without a parental allowance | child, teen | `sensitive_topic` |
| 9 | Borderline item: flagged as such, or toxicity >= 0.25 (derived by the gate, not only read from the stored flag) | child; teen under `strict` | `borderline` |
| 10 | Status not exactly `approved`; disagreement or confidence missing; disagreement >= threshold or confidence < 1 - threshold | child, teen, self-declared adult | `pending_review`, `missing_signals`, `high_uncertainty` |

Checks 5 and 7 repeat, inside the gate, things the rating already accounts for. That is
deliberate: a wrong or stale rating alone cannot put an escalation label or an unlisted
topic in front of a minor.

### Uncertainty threshold

`0.45 x trust x strictness`. Trust: verified 1.0, parent_linked 0.85, self_declared 0.7.
Strictness: low 1.0 (default), medium 0.8, strict 0.6. `HIGH_UNCERTAINTY_THRESHOLD` may
lower the 0.45 base from the environment; it is clamped to [0.05, 0.45] and cannot raise it.

### Escalation categories

`violent_extremism`, `grooming`, `self_harm`. Each is matched by stems on the label with
separators removed (`extremis`, `terror`, `radicali`; `groom`, `childsafety`,
`childexploit`, `childsexual`, `csam`; `selfharm`, `selfinjur`, `suicid`, `eatingdisorder`).
Over-matching is accepted: "bridegroom" is hidden from minors.

### Where the gate runs

On the candidate pool, and again on the final ranked list immediately before it is returned.
The gate reads tier, trust level and parental controls from the profile and nothing else.

## Parental controls

`blocked_categories`, `max_rating` and `strictness_level` can only narrow. Labels must be
plain ASCII so a look-alike character cannot make a block match nothing.
`allowed_sensitive_topics` is the one field that widens, and only this far: it lets a teen
see teen-rated items on a sensitive topic. It does nothing for a child.

## Profiles and storage

- Raising an age tier is admin-only, always. The owner can lower it.
- A profile record that cannot be read is served as the most restrictive profile: child,
  strict, capped at `all_ages`, keeping any parental blocks that are still readable. It is
  not written back, and only an admin can repair it.
- A moderator's decision outranks a later machine rating. A re-run of the pipeline can make
  a human-reviewed item stricter, never more permissive, and cannot restore a removed item.
- A moderator approve or warn through the feedback endpoint rates the item `adult` at most.
- When a Firestore write fails, SQLite is the source of truth for that document until the
  write succeeds.

## Limitations - read these

- **Self-declared age can be false.** By product decision an account with no declared tier
  is `adult` / `self_declared`. A minor on such an account gets the adult feed, less the
  uncertainty margin. The gate cannot detect this.
- **The rating is only as good as the classifiers.** If the agents miss something and
  approve it with clean signals on a child-list topic, it is rated `all_ages`.
- **Coded language evolves.** Stem matching catches spelling variants, not new slang,
  images of text, or other languages.
- **Agent confidence is a weak signal here.** Most agents report a hard-coded constant
  (0.85, 0.80). Disagreement between verdicts carries the information; the confidence
  floor mostly catches unreadable decisions.
- **Topic allow-lists make minors' feeds sparse on real data.** `content_category` is LLM
  free text defaulting to `"general"`, which is not on any list, so such items rate `adult`.
  This fails closed, and it means the pipeline needs a controlled topic vocabulary before
  child and teen feeds are useful in production.
- **`violent_extremism` and `grooming` are not emitted by today's pipeline.** Those rules
  are exercised by mock data and tests only.
- **Fast-mode and early-exit items** often lack `moderation_action`, severity or detection
  flags. They rate `adult`.
- **Items moderated while the flag is off are unrated** and withheld from minors.
