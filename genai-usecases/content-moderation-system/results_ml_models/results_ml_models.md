# Content moderation with the ML models on

Run at 2026-10-10T12:30:46 by `run_verification.py`. Settings are read from `backend/.env`.
The language model is the keyword stand-in from `recommendation/evaluation/standin_llm.py`;
no provider was called. Every text went through the full pipeline as a post.

## Engine

| Setting | Value |
|---|---|
| USE_ML_MODELS | true |
| ML_PRIMARY_MODEL | distilbert_toxic |
| ML_USE_ENSEMBLE | false |
| ML_PRELOAD_MODELS | true |
| ML_DEVICE | auto |
| Preload status | success |
| Device | cpu |
| Models loaded | distilbert_toxic |
| Model load time | 0.2 s |

## Checks

| Check | Result |
|---|---|
| backend/.env has USE_ML_MODELS=true | PASS |
| torch and transformers import | PASS |
| model preload succeeds | PASS |
| model named in .env is the one loaded | PASS |
| every text was scored by the model, not the keyword fallback | PASS |
| pipeline finished for every text | PASS |
| with ML off the same code falls back to keywords | PASS |

## Decisions against the expectation in the test set

ML on: 34 of 43 match. ML off (keywords only): 35 of 43.

| Group | Texts | Match, ML on | Match, ML off |
|---|---|---|---|
| good | 11 | 11 | 11 |
| sensitive | 3 | 3 | 3 |
| bad | 14 | 13 | 13 |
| false-positive check | 6 | 0 | 0 |
| edge | 9 | 7 | 8 |

## Decisions that ML changed

| ID | Group | Expect | ML off | ML on | Tox off | Tox on | Text |
|---|---|---|---|---|---|---|---|
| T37 | edge | approved | approved (ok) | removed (MISS) | 0.05 | 0.96 | Sooooooo happyyyyyy todayyyyyy!!!!!!!!!! |

## Every text, ML on

| ID | Group | Expect | Status | Result | Keyword tox | ML tox | Policy keywords | Severity | Human review | Text |
|---|---|---|---|---|---|---|---|---|---|---|
| T01 | good | approved | approved | ok | 0.00 | 0.00 | - | none | no | We built a baking soda volcano for the science fair and t... |
| T02 | good | approved | approved | ok | 0.00 | 0.00 | - | none | no | Our puppy met a kitten at the zoo today and they became b... |
| T03 | good | approved | approved | ok | 0.00 | 0.00 | - | none | no | Great football match last night, what a comeback in the s... |
| T04 | good | approved | approved | ok | 0.00 | 0.00 | - | none | no | Solved a 1000 piece puzzle of a mountain lake this weekend. |
| T05 | good | approved | approved | ok | 0.00 | 0.00 | - | none | no | Thank you to everyone who helped at the school garden cle... |
| T06 | good | approved | approved | ok | 0.00 | 0.00 | - | none | no | Finally fixed that bug in my Python script after three ho... |
| T07 | good | approved | approved | ok | 0.30 | 0.00 | - | none | no | New phone review: the camera is good but the battery coul... |
| T08 | good | approved | approved | ok | 0.00 | 0.00 | - | none | no | Went to a nightclub opening downtown, the music was loud ... |
| T09 | good | approved | approved | ok | 0.20 | 0.00 | - | none | no | Mortgage rates went up again this month, here is how we a... |
| T10 | sensitive | human review | pending_human_review | ok | 0.00 | 0.00 | - | none | yes | Feeling stressed before exams, here is what helps my anxi... |
| T11 | sensitive | human review | pending_human_review | ok | 0.00 | 0.00 | - | none | yes | Stock tips: where to invest before the election results c... |
| T12 | sensitive | human review | pending_human_review | ok | 0.00 | 0.00 | - | none | yes | My doctor changed my diagnosis and I am trying a new trea... |
| T13 | bad | flagged | flagged | ok | 0.20 | 0.96 | - | - | no | Honestly that referee was stupid, what a terrible call in... |
| T14 | bad | flagged or removed | flagged | ok | 0.55 | 0.01 | - | - | no | You are such an idiot, nobody wants to read your stupid p... |
| T15 | bad | flagged or removed | flagged | ok | 0.40 | 0.96 | - | - | no | Shut up, you worthless clown, everyone here thinks you ar... |
| T16 | bad | removed or human review | removed | ok | 0.30 | 0.01 | violence | high | no | I will attack you after school tomorrow, watch your back. |
| T17 | bad | removed or human review | removed | ok | 0.15 | 0.02 | harassment | high | no | Keep posting and I will threaten everyone in this group u... |
| T18 | bad | removed or human review | removed | ok | 0.00 | 0.11 | hate_speech | high | no | People who support that team are inferior and I hate ever... |
| T19 | bad | removed or human review | removed | ok | 0.15 | 0.03 | harassment | high | no | We should harass and stalk this user until they delete th... |
| T20 | bad | warned or human review | pending_human_review | ok | 0.30 | 0.00 | spam | medium | yes | Click here and buy now! Limited offer, free money guarant... |
| T21 | bad | warned or human review | pending_human_review | ok | 0.30 | 0.00 | spam | medium | yes | Work from home, guaranteed income, click here, limited of... |
| T22 | bad | warned or human review | pending_human_review | ok | 0.00 | 0.00 | misinformation | none | yes | The secret truth they hide: this guaranteed cure works an... |
| T23 | bad | warned or human review | pending_human_review | ok | 0.00 | 0.00 | misinformation | none | yes | Doctors don't want you to know this one trick that replac... |
| T24 | bad | removed or human review | pending_human_review | ok | 0.00 | 0.00 | sexual_content | medium | yes | Adults only link inside: xxx videos and nude pics, click ... |
| T25 | false-positive check | ideally approved | removed | MISS | 0.30 | 0.00 | violence | high | no | The bomb scene in that action movie was the best part of ... |
| T26 | false-positive check | ideally approved | removed | MISS | 0.00 | 0.00 | self_harm | critical | no | A local charity talk on suicide prevention and where to f... |
| T27 | false-positive check | ideally approved | removed | MISS | 0.15 | 0.00 | hate_speech | high | no | I reported an account that keeps posting supremacist slog... |
| T28 | false-positive check | ideally approved | removed | MISS | 0.30 | 0.00 | violence | high | no | Our team will kill it at the quiz tonight, we have practi... |
| T29 | false-positive check | ideally approved | removed | MISS | 0.15 | 0.00 | harassment | high | no | Someone is trying to harass my sister online, how do we r... |
| T30 | edge | approved | approved | ok | 0.00 | 0.01 | - | none | no | ok |
| T31 | edge | approved | approved | ok | 0.15 | 0.00 | - | none | no | LOVED THE SCHOOL PLAY TONIGHT!!! BEST SHOW EVER!!! |
| T32 | edge | approved | approved | ok | 0.00 | 0.00 | - | none | no | Good morning everyone ☀️🌻 hope you all have a lovely day 😊 |
| T33 | edge | approved | approved | ok | 0.00 | 0.19 | - | none | no | आज हमने स्कूल में विज्ञान मेले में भाग लिया, बहुत मज़ा आया। |
| T34 | edge | approved | approved | ok | 0.00 | 0.00 | - | none | no | ఈ రోజు మేము పాఠశాలలో క్రికెట్ ఆడాము, చాలా బాగుంది. |
| T35 | edge | approved | approved | ok | 0.00 | 0.00 | - | none | no | https://example.com/blog/how-to-grow-tomatoes |
| T36 | edge | flagged | approved | MISS | 0.00 | 0.00 | - | none | no | y0u are an 1d10t and a l0ser |
| T37 | edge | approved | removed | MISS | 0.05 | 0.96 | - | high | no | Sooooooo happyyyyyy todayyyyyy!!!!!!!!!! |
| T38 | edge | approved | approved | ok | 0.00 | 0.00 | - | none | no | Here is my full trip report. We walked, ate, rested and w... |
| C01 | good | approved | approved | ok | 0.00 | 0.00 | - | none | no | Nice story, thanks for sharing! |
| C02 | good | approved | approved | ok | 0.00 | 0.00 | - | none | no | I had the same experience last year. |
| C03 | bad | flagged or removed | flagged | ok | 0.40 | 0.96 | - | - | no | This is a stupid story and you are an idiot. |
| C04 | bad | warned or flagged | pending_human_review | MISS | 0.00 | 0.00 | spam | medium | yes | Click here, buy now, free money! |
| C05 | false-positive check | ideally approved | removed | MISS | 0.30 | 0.03 | violence | high | no | That ending killed me, so funny. |

## Timing, ML on

Model call per text: 30 ms on average (cpu). Full pipeline per text: 0.33 s on average, with the stand-in language model.
