# Paper outline

## Working titles

- A Fail-Closed Age Gate for Personalized Content Feeds on a Multi-Agent Moderation Pipeline
- Keeping the Safety Decision Outside the Learner: A Deterministic Age Gate for Recommendation
- Age-Gated Recommendation with Uncertainty-Aware Safety Margins: Design and a Synthetic Evaluation

Avoid titles that promise a new algorithm or real-world safety. See "Positioning" below.

## Positioning (decide this first)

The honest contribution is an **architecture and an evaluation method**, not an algorithm:

1. A design in which the age-appropriateness decision is a deterministic, fail-closed rule
   set that runs before and after every learned component, so no learned signal can admit
   an item.
2. A way of deriving an audience rating from a multi-agent moderation pipeline's existing
   outputs, in which a missing or malformed signal can only raise the rating.
3. An evaluation approach for such a gate: invariant testing against an independent
   oracle, plus adversarial review, with the review's findings reported.
4. A negative-leaning empirical result worth stating: on synthetic data the learned
   ranking components added little over a simple interest sort, while the gate did all of
   the safety work.

Every technique used is established (see `05_related_work.md`). Say so in the introduction.

## Sections

### 1. Introduction (about 1 page)
- Problem: recommender systems optimise engagement; moderation decides only keep or
  remove; neither decides *who* may see an item. Minors share feeds with adults.
- Gap: age-appropriateness handled inside the ranking model is hard to verify.
- Approach in two sentences; contributions as the four points above.
- One sentence on scope: prototype, synthetic data.
- Material: `02_method.md` section 1; `04_claims_and_limitations.md`.

### 2. Background and related work (about 1 page)
- Automated content moderation and multi-agent / LLM pipelines.
- Content rating and age-appropriate design (regulatory context).
- Safe and constrained recommendation; filter bubbles and radicalization pathways.
- Bandits for recommendation; uncertainty from ensemble disagreement; case-based reasoning.
- Start from the five literature-survey papers: agent-based and human-in-the-loop
  moderation (WATCHED; Kotarcic et al.), recommenders for children (Ungruh), and
  beyond-accuracy evaluation (Wu et al.). Position against Ungruh most directly.
- Material: `05_related_work.md`, `references.bib`.

### 3. System design (2 to 3 pages)
- 3.1 Host pipeline: six agents, human-in-the-loop, what it outputs.
- 3.2 Audience rating derivation: the monotone "only raise" rule; table of rules.
- 3.3 The safety gate: ten ordered checks, trust and strictness scaling, where it runs.
- 3.4 Personalization inside the gate: tier topic rules, relevance, bandit, guards.
- 3.5 Moderator side: priority formula, escalation as a leading key, precedents, feedback.
- Figure 1: the data-flow diagram. Table: rating rules. Table: gate checks.
- Material: `02_method.md`.

### 4. Evaluation method (about 1 page)
- 4.1 Synthetic data: 800 items in 13 scenarios, 80 profiles, 200 resolved cases; why
  synthetic; placeholder text only.
- 4.2 Gate correctness: 48 named cases; 64,000-combination sweep against generator labels;
  12,000 random pairs against an independent oracle; 1,040 feeds through the full path
  with adversarial personalization state.
- 4.3 Adversarial review: three passes by reviewers given only the rules and the code.
- 4.4 Offline replay: baselines and ablations for ranking, bandit, queue, precedents.
- Material: `03_results.md` (the "how produced" notes), `06_reproducibility.md`.

### 5. Results (2 pages)
- 5.1 Gate: zero leaks in every run; what gate-off shows. Figure: leak rate.
- 5.2 What the gate cannot do: the later-flagged rate.
- 5.3 Ranking against baselines. Figure: relevance. State that interest-only wins precision.
- 5.4 Bandit under simulated feedback. Figure: learning curves. State the weak effect.
- 5.5 Drift and diversity guards. Figure.
- 5.6 Queue prioritization. Figure. State the role of the escalation rule.
- 5.7 Precedent retrieval. Figure. State the circularity.
- 5.8 Findings from adversarial review: the table of leaks found and fixed.
- 5.9 The live run: two defects the synthetic data could not reveal.
- Material: `03_results.md`.

### 6. Discussion (about 1 page)
- The safety value came from the deterministic layer; the learned layer was optional.
- Review found more than testing did: leaks were in the storage and integration code
  around the gate, not in the gate.
- Synthetic data encodes the author's assumptions; the live run broke two of them.
- Cost of fail-closed design: sparse feeds for minors without a controlled topic vocabulary.
- The manual approve-and-tag path: useful for a prototype, a single point of trust.

### 7. Limitations and threats to validity (half a page)
- Material: `04_claims_and_limitations.md`, nearly verbatim.

### 8. Ethics statement (short)
- No real user data. No harmful content generated: labels and placeholder text only.
- Self-declared age can be false; the system does not verify age.
- Moderation targets conduct, not belief; no ideology is blocked as such.
- A stored date of birth is avoided: only the age group is kept.

### 9. Conclusion and future work
- Future work: real-model evaluation; controlled topic vocabulary; real engagement data;
  versioned storage for concurrent updates; age assurance; user study with moderators.

## Length guide

A 6 to 8 page conference format fits this. If space is short, cut 5.5 and 5.7 to a
sentence each and keep 5.1, 5.2, 5.8 and 5.9: those carry the paper.
