# Related work: what to cite for each part

**Check every reference before you submit.** The entries in `references.bib` were written
from memory, without looking anything up. I am confident each work exists and is correctly
attributed, but details such as page numbers are omitted and years or venues may be off.
Look each one up (Google Scholar or the publisher's page), confirm it says what you cite
it for, and export the BibTeX from the source.

No literature search was done for this kit. This list covers the techniques the system
uses; it is not a survey. Before claiming a gap, search for closer prior work, in
particular: age-appropriate or child-safe recommendation, constrained or "safe"
recommender systems, and LLM-based content moderation.

## Techniques used, and a citation for each

| Part of the system | Established technique | Key in `references.bib` |
|---|---|---|
| Relevance scoring | TF-IDF term weighting, cosine similarity | `salton1988term` |
| Explore/exploit | Thompson sampling | `thompson1933likelihood`, `chapelle2011empirical` |
| Bandits for recommendation | Contextual bandits for news recommendation | `li2010contextual` |
| Relevance metrics | NDCG | `jarvelin2002cumulated` |
| Diversity guard | Diversity-aware re-ranking (MMR) | `carbonell1998use` |
| Uncertainty margin | Ensemble disagreement as uncertainty | `lakshminarayanan2017simple` |
| Withholding when uncertain | Selective classification / abstention | `geifman2017selective` |
| Precedent retrieval | Case-based reasoning | `aamodt1994case` |
| Drift guard, motivation | Filter bubbles; radicalization pathways | `pariser2011filter`, `ribeiro2020auditing` |
| Moderation context | Algorithmic content moderation; platform governance | `gorwa2020algorithmic`, `gillespie2018custodians` |
| Toxicity model | BERT; the Detoxify models (`unitary/toxic-bert`) | `devlin2019bert`, `hanu2020detoxify` |
| Agent orchestration | ReAct-style reasoning and acting | `yao2023react` |

## Regulatory and policy context (for the introduction)

Cite the primary documents, not summaries:

- **COPPA**, the US Children's Online Privacy Protection Act (1998), and the FTC rule.
- **UK Age Appropriate Design Code** ("Children's Code"), Information Commissioner's
  Office, in force from 2020.
- **EU Digital Services Act** (Regulation (EU) 2022/2065), in particular the provisions on
  protection of minors and on recommender-system transparency.
- If you are writing for an Indian venue: the **Digital Personal Data Protection Act,
  2023**, which has provisions on children's data. I have not checked its details; read
  the relevant section before citing it.

These are not in `references.bib`; cite them in your venue's format for legislation.

## Software to acknowledge

LangGraph and LangChain (agent orchestration), FastAPI, Pydantic, Hugging Face
Transformers, PyTorch, NumPy, Matplotlib, pytest. Versions are in `06_reproducibility.md`.
Most venues want software cited by its paper where one exists, otherwise by URL and version.

## How to frame novelty

A fair statement: *"Each component is a known technique. What we contribute is an
arrangement in which the age-appropriateness decision is deterministic, fail-closed and
applied both before and after every learned component, together with an evaluation
approach for it and the results of adversarially reviewing the implementation."*

Do not write "novel algorithm", "first", or "guarantees safety". A reviewer will check
the first two against the literature, and the results section contradicts the third.
