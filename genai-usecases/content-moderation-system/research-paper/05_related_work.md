# Related work: what to cite for each part

**Check every reference before you submit.** Two kinds of entry are in `references.bib`.
The four from the project's literature survey were looked up and are described first below.
The rest, for the individual techniques, were written from memory, without looking anything up. I am confident each work exists and is correctly
attributed, but details such as page numbers are omitted and years or venues may be off.
Look each one up (Google Scholar or the publisher's page), confirm it says what you cite
it for, and export the BibTeX from the source.

No literature search was done for this kit. This list covers the techniques the system
uses; it is not a survey. Before claiming a gap, search for closer prior work, in
particular: age-appropriate or child-safe recommendation, constrained or "safe"
recommender systems, and LLM-based content moderation.

## Papers from the project's literature survey

These five are the papers on the project's literature-survey slide. Four were looked up
on 2026-10-09 and their details below come from the publisher or archive page. The fourth
could not be found by title; see the note under it.

| # | Paper | Venue and status | What it does | What this project takes from it | Key |
|---|---|---|---|---|---|
| 1 | Piot, Sánchez and Parapar, *WATCHED: A Web AI Agent Tool for Combating Hate Speech by Expanding Data* (2025) | arXiv preprint 2509.01379 (cs.CL). No journal or conference version is listed on the arXiv page | A chatbot for moderators: an LLM agent that calls tools (a BERT classifier, retrieval of labelled examples, a slang lookup, platform guidelines) and explains why a post is harmful. Reports macro F1 0.91 | Agent-based moderation with tool use and explanations: the host pipeline's design. Their retrieval of similar labelled examples is close to this project's precedent retrieval | `piot2025watched` |
| 2 | Kotarcic, Hangartner, Gilardi, Kurer and Donnay, *Human-in-the-Loop Hate Speech Classification in a Multilingual Context* (2022) | Findings of EMNLP 2022, pages 7414-7442 | A BERT-based hate-speech pipeline for German and French with humans in the loop, documented from annotation to a 12-month post-deployment evaluation. F1 80.5. Finds that continuous human maintenance is needed to stay robust after deployment | Human-in-the-loop moderation; BERT-based toxicity classification; the feedback loop in which moderator decisions update the system. Also supports this paper's point that mock or pre-deployment evaluation is not enough | `kotarcic2022human` |
| 3 | Wu, Cao and Xu, *Fairness in Recommender Systems: Evaluation Approaches and Assurance Strategies* (2023) | ACM Transactions on Knowledge Discovery from Data 18(1), article 10 | A survey. Organises fairness metrics by whom fairness is for, demographic unit, time frame and quantification method, and reviews mitigation strategies | Background on evaluating recommenders beyond accuracy. **See the caution below** | `wu2023fairness` |
| 4 | *Enhancing Personalized Early Childhood Reading Recommendations* (2026) | **Not found.** Two searches on the exact title returned nothing | Per the slide: age, safety and personalization | Per the slide: age-aware filtering | none yet |
| 5 | Ungruh, *Are Recommender Systems Serving Children? Toward Child-Aware Design and Evaluation* (2025) | RecSys 2025 Doctoral Symposium, pages 1451-1457 | A PhD research plan. Argues recommender research targets adults and overlooks children, and proposes "child-aware" recommenders that account for children's needs, vulnerabilities and rights, starting with audits of current algorithms | The motivation for this project, and the closest prior work to position against: it identifies the gap, this project builds and tests one mechanism for it | `ungruh2025recommender` |

### Cautions when citing these

- **Paper 3, fairness.** The slide says the project uses "fairness-aware recommendation".
  The system as built does not measure or enforce fairness across user or item groups. It
  has an adult diversity guard and a drift guard, which are different things. Either cite
  this survey only as background on beyond-accuracy evaluation, or list fairness under
  future work. Do not say the system is fairness-aware.
- **Paper 1 is a preprint.** Cite it as an arXiv preprint and say so; check whether a
  reviewed version has appeared before you submit.
- **Paper 5 is a doctoral symposium paper**, a research plan with early audits, not a
  finished system. Cite it for the problem statement, not for results. I read only the
  abstract-level summary, which cut off before describing its second audit perspective.
- **Paper 4 needs the link from your slide.** Send me the URL or the authors and venue and
  I will add it. Until it is verified, leave it out of the reference list.
- For papers 1, 2 and 5 I worked from the abstract and listing pages, not the full text.
  Read each paper before describing its method in your own words.

### Where they go in the paper

- Introduction: 5 for the gap (recommenders are not designed for children); 2 for why
  human oversight matters after deployment.
- Related work, moderation: 1 and 2.
- Related work, recommendation for children: 5 (and 4 once verified).
- Related work, evaluation beyond accuracy: 3.
- Discussion: 2 again, next to the finding that the live run exposed defects the
  synthetic tests had passed.

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
