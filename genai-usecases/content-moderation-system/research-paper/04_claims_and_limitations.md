# Claims and limitations

Use the first table to check every sentence in the abstract, introduction and conclusion.

## What the evidence supports

| Claim | Supported? | Evidence | How to word it |
|---|---|---|---|
| The gate withholds above-tier, blocked, pending, unrated and high-risk items from child and teen feeds | Yes, on synthetic data | R3, R4, R5 | "In all 64,000 decisions and 1,040 generated feeds on synthetic data, no such item was served" |
| No learned signal can admit an item | Yes, by construction and by test | R4; method section 4 | State the design reason first, the tests second |
| A missing or malformed signal never lowers a rating | Yes, for the fields tested | Field deletion and corruption tests; review passes | "For every input field we tested" |
| The gate makes feeds safe for children | **No** | R5, later-flagged column | Do not claim. The gate enforces ratings; it does not validate them |
| Personalization beats random selection | Yes | R6 | Fine as stated |
| Personalization beats an interest-only sort | **No** | R6 | Report it as a negative result |
| The bandit improves engagement | Weak, adults only | R7 | "A small, noisy gain for adult profiles; none for teens" |
| The guards hold their limits | Yes | R8 | "Borderline share stayed under the caps" |
| The system minimises borderline exposure | **No** | R8 | The full system serves more than the baseline |
| The prioritizer surfaces high-harm items sooner than FIFO and a risk sort | Yes, with a caveat | R9 | Say that high-risk items go first by rule and are part of the high-harm definition |
| Precedents improve suggested actions | Only under an assumption built into the data | R10 | See below |
| The approach is novel | Partly | `05_related_work.md` | "A composition of established techniques"; the novelty is the arrangement and the evaluation |
| The system works on a real moderation pipeline | Partly | R12 | "Integrated with and run through the real pipeline, with the language model replaced by a stand-in" |

## Threats to validity

### Construct validity

- **Leak is defined on labels the generator assigned.** The gate is shown to respect
  ratings and signals, not to recognise harmful content.
- **Relevance is defined from the same topic labels the rankers use.** It measures
  consistency with the stated profile, not whether a person would find the feed relevant.
- **Time-to-review is queue position**, assuming one review per step and equal review time.
- **"Later flagged" is a modelling assumption** (a uniform 3 %), not an observed rate.

### Internal validity

- **The precedent result is circular.** The generator gives each category a "house norm"
  that the simulated moderator follows 80 % of the time; category-based retrieval recovers
  it. Rules-only scores 0 % on override cases by definition, since an override is a case
  where the human differed from the rules. The result shows the mechanism works when such
  structure exists, nothing more.
- **The queue result partly follows from definitions.** High-risk items are ordered first
  by rule and are included in the high-harm set.
- **Tests and code share an author.** Three independent adversarial reviews offset this
  and found defects the tests had not. The fixes from the last review were not
  independently re-checked.
- **Agent confidences are near-constant.** Most agents in the host pipeline report a fixed
  confidence, so the uncertainty margin is driven by disagreement between verdicts.

### External validity

- **Synthetic data throughout.** No real users, content or moderator decisions.
- **Small scale.** 800 items, 80 profiles, 36 simulated viewers for the bandit.
- **The language model is absent from every measured result.** A real model emits
  free-form categories; most would be on no allow-list and rate adult, so feeds for minors
  would be sparse without a controlled topic vocabulary. This was not measured.
- **Mock data encoded wrong assumptions twice.** The live run exposed two defects that
  every synthetic test had passed (R12). More should be expected with a real model.
- **One pipeline.** The rating rules are tied to this pipeline's output fields.

### Reliability

- Deterministic and seeded; metrics are byte-identical across runs.
- The bandit simulation uses one seed. No confidence intervals were computed; the
  per-round curves are visibly noisy. Do not describe differences of a few points as
  significant.

## Known limitations of the system itself

1. **Age is self-declared.** An account with no declared age group is treated as an adult
   by project decision. A minor on such an account sees the adult feed.
2. **The gate trusts the moderation signals.** Content the classifiers approve with clean
   signals on a child-list topic is rated all_ages.
3. **Fail-closed has a cost.** Any image URL raises media risk in the host's heuristic and
   so rates the post adult; unknown topics rate adult.
4. **Label matching is lexical.** It catches spelling variants of known terms, not new
   slang, leetspeak, look-alike characters, other languages or text in images.
5. **Concurrent updates can be lost.** Profiles and bandit state are read, modified and
   written whole, without versioning. Not fixed.
6. **A moderator's approval plus hand-set tags can rate an item for children**, with no
   second check. Added so the prototype works without a language model.
7. **Parental controls are set by an admin**, because the platform has no parent accounts.
8. **The frontend was built but not exercised in a browser** at the time of writing.
9. **The host's detectors over-block**: "suicide prevention", a movie's "bomb scene" and a
   plain skin-coloured image are all treated as violations. These are properties of the
   existing platform, inherited by the ratings.

## Ethics points to include

- No real personal data; no harmful content was generated. Harmful categories are
  represented by labels on placeholder text.
- The date of birth is used to derive an age group and is not sent to the server or stored.
- Moderation targets conduct (violence, harassment, grooming, self-harm promotion, scams),
  not political or religious belief.
- A gate like this can give false assurance. The paper should say that it enforces
  ratings and does not replace age assurance or human moderation.
