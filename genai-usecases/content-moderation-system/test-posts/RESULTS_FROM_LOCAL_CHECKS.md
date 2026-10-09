# What the platform's local checks return for this test set

Produced by `generate_test_posts.py`. These are the parts of the pipeline that run
without a language model. The final decision in the app also depends on the
language model and on the routing between agents, so use this as a reference for
what to expect, not as the expected final result.

## Text

| ID | Group | Keyword toxicity | ML toxicity (toxic-bert) | Policy keywords | Severity | Text |
|---|---|---|---|---|---|---|
| T01 | good | 0.0 | 0.0 | - | none | We built a baking soda volcano for the science fair and the experim... |
| T02 | good | 0.0 | 0.0 | - | none | Our puppy met a kitten at the zoo today and they became best friends. |
| T03 | good | 0.0 | 0.0 | - | none | Great football match last night, what a comeback in the second half. |
| T04 | good | 0.0 | 0.0 | - | none | Solved a 1000 piece puzzle of a mountain lake this weekend. |
| T05 | good | 0.0 | 0.0 | - | none | Thank you to everyone who helped at the school garden clean-up today. |
| T06 | good | 0.0 | 0.0 | - | none | Finally fixed that bug in my Python script after three hours of deb... |
| T07 | good | 0.3 | 0.0 | - | none | New phone review: the camera is good but the battery could be better. |
| T08 | good | 0.0 | 0.0 | - | none | Went to a nightclub opening downtown, the music was loud and the qu... |
| T09 | good | 0.2 | 0.0 | - | none | Mortgage rates went up again this month, here is how we adjusted ou... |
| T10 | sensitive | 0.0 | 0.0 | - | none | Feeling stressed before exams, here is what helps my anxiety: sleep... |
| T11 | sensitive | 0.0 | 0.0 | - | none | Stock tips: where to invest before the election results come in. |
| T12 | sensitive | 0.0 | 0.0 | - | none | My doctor changed my diagnosis and I am trying a new treatment plan. |
| T13 | bad | 0.2 | 0.87 | - | none | Honestly that referee was stupid, what a terrible call in the match. |
| T14 | bad | 0.55 | 0.99 | hate_speech | high | You are such an idiot, nobody wants to read your stupid posts. I ha... |
| T15 | bad | 0.4 | 0.99 | - | low | Shut up, you worthless clown, everyone here thinks you are pathetic. |
| T16 | bad | 0.3 | 0.84 | violence | high | I will attack you after school tomorrow, watch your back. |
| T17 | bad | 0.15 | 0.32 | harassment | high | Keep posting and I will threaten everyone in this group until you s... |
| T18 | bad | 0.0 | 0.5 | hate_speech | high | People who support that team are inferior and I hate every one of t... |
| T19 | bad | 0.15 | 0.25 | harassment | high | We should harass and stalk this user until they delete their account. |
| T20 | bad | 0.3 | 0.0 | spam | medium | Click here and buy now! Limited offer, free money guaranteed, act now! |
| T21 | bad | 0.3 | 0.0 | spam | medium | Work from home, guaranteed income, click here, limited offer ends t... |
| T22 | bad | 0.0 | 0.0 | misinformation | none | The secret truth they hide: this guaranteed cure works and mainstre... |
| T23 | bad | 0.0 | 0.01 | misinformation | none | Doctors don't want you to know this one trick that replaces all med... |
| T24 | bad | 0.0 | 0.01 | sexual_content | medium | Adults only link inside: xxx videos and nude pics, click to see. |
| T25 | false-positive check | 0.3 | 0.0 | violence | high | The bomb scene in that action movie was the best part of the film. |
| T26 | false-positive check | 0.0 | 0.0 | self_harm | critical | A local charity talk on suicide prevention and where to find a help... |
| T27 | false-positive check | 0.15 | 0.0 | hate_speech | high | I reported an account that keeps posting supremacist slogans, pleas... |
| T28 | false-positive check | 0.3 | 0.01 | violence | high | Our team will kill it at the quiz tonight, we have practised all week. |
| T29 | false-positive check | 0.15 | 0.04 | harassment | high | Someone is trying to harass my sister online, how do we report it? |
| T30 | edge | 0.0 | 0.0 | - | none | ok |
| T31 | edge | 0.15 | 0.0 | - | none | LOVED THE SCHOOL PLAY TONIGHT!!! BEST SHOW EVER!!! |
| T32 | edge | 0.0 | 0.0 | - | none | Good morning everyone ☀️🌻 hope you all have a lovely day 😊 |
| T33 | edge | 0.0 | 0.0 | - | none | आज हमने स्कूल में विज्ञान मेले में भाग लिया, बहुत मज़ा आया। |
| T34 | edge | 0.0 | 0.02 | - | none | ఈ రోజు మేము పాఠశాలలో క్రికెట్ ఆడాము, చాలా బాగుంది. |
| T35 | edge | 0.0 | 0.0 | - | none | https://example.com/blog/how-to-grow-tomatoes |
| T36 | edge | 0.0 | 0.73 | - | none | y0u are an 1d10t and a l0ser |
| T37 | edge | 0.05 | 0.04 | - | none | Sooooooo happyyyyyy todayyyyyy!!!!!!!!!! |
| T38 | edge | 0.0 | 0.0 | - | none | Here is my full trip report. We walked, ate, rested and walked agai... |
| C01 | good | 0.0 | 0.0 | - | none | Nice story, thanks for sharing! |
| C02 | good | 0.0 | 0.0 | - | none | I had the same experience last year. |
| C03 | bad | 0.4 | 0.99 | - | low | This is a stupid story and you are an idiot. |
| C04 | bad | 0.0 | 0.0 | spam | medium | Click here, buy now, free money! |
| C05 | false-positive check | 0.3 | 0.07 | violence | high | That ending killed me, so funny. |

## Image files (pixel analysis of the uploaded file)

| File | Group | Risk score | Risk level | Marked unsafe | Skin ratio | Dark ratio | Red ratio |
|---|---|---|---|---|---|---|---|
| good_landscape.png | good | 0.288 | low | False | 0.0257 | 0.0 | 0.0 |
| good_cartoon_cat.png | good | 0.324 | low | False | 0.0 | 0.0027 | 0.0 |
| good_notice_card.png | good | 0.344 | low | False | 0.0 | 0.0 | 0.0 |
| good_bar_chart.png | good | 0.322 | low | False | 0.0 | 0.0 | 0.0 |
| good_plain_blue.jpg | good | 0.25 | low | False | 0.0 | 0.0 | 0.0 |
| risky_skin_tone_block.png | bad (heuristic) | 1.0 | severe | True | 1.0 | 0.0 | 0.0 |
| risky_half_skin_tone.png | bad (heuristic) | 1.0 | severe | True | 0.5 | 0.0 | 0.0 |
| risky_saturated_red.png | bad (heuristic) | 1.0 | severe | True | 0.0 | 0.0 | 1.0 |
| risky_dark_red.png | bad (heuristic) | 0.45 | medium | False | 0.0 | 1.0 | 0.0 |
| fp_sunset_gradient.jpg | false-positive check | 1.0 | severe | True | 1.0 | 0.0 | 0.0 |
| fp_beige_wall.jpg | false-positive check | 1.0 | severe | True | 1.0 | 0.0 | 0.0 |
| fp_night_sky.png | false-positive check | 0.449 | medium | False | 0.0 | 0.9864 | 0.0 |
| named_nsfw_but_harmless.png | file-name check | 0.288 | low | False | 0.0257 | 0.0 | 0.0 |
| edge_tiny_1x1.png | edge | 0.35 | medium | False | 0.0 | 0.0 | 0.0 |
| edge_very_wide.png | edge | 0.25 | low | False | 0.0 | 0.0 | 0.0 |
| good_animated_sun.gif | good | 0.301 | low | False | 0.0342 | 0.0 | 0.0 |

## Edge-case files in the image upload

| File | Accepted | Result |
|---|---|---|
| not_an_image.jpg | False | Invalid image file |
| empty_file.png | False | Invalid image file |
| plain_text_note.txt | False | Invalid image file |
| image_with_wrong_extension.txt | True | low |
| truncated_image.png | False | Invalid image file |

## Image URLs (scored from the file name only)

| ID | Group | Risk score | Risk level | Words matched | URL |
|---|---|---|---|---|---|
| U01 | good | 0.4 | medium | - | https://example.com/uploads/planet_drawing.png |
| U02 | good | 0.4 | medium | - | https://example.com/photos/school_trip_group.jpg |
| U03 | bad | 0.65 | high | explicit, nsfw | https://example.com/uploads/nsfw_explicit_photo.jpg |
| U04 | bad | 0.65 | high | blood, gore | https://example.com/img/gore_blood_scene.png |
| U05 | bad | 0.65 | high | violent, weapon | https://example.com/img/weapon_violent_poster.jpg |
| U06 | false-positive check | 0.4 | medium | blood | https://example.com/recipes/blood_orange_cake.jpg |

## Video URLs (scored from the file name only)

| ID | Group | Risk score | Risk level | Words matched | URL |
|---|---|---|---|---|---|
| V01 | good | 0.4 | medium | - | https://example.com/videos/school_sports_day.mp4 |
| V02 | good | 0.4 | medium | - | https://example.com/videos/cooking_pasta_tutorial.mp4 |
| V03 | bad | 0.4 | medium | fights | https://example.com/videos/street_fights_compilation.mp4 |
| V04 | bad | 0.65 | high | explicit, nsfw | https://example.com/videos/explicit_nsfw_clip.mp4 |
| V05 | bad | 0.65 | high | attack, gore | https://example.com/videos/gore_attack_footage.mp4 |
| V06 | false-positive check | 0.4 | medium | attack | https://example.com/videos/heart_attack_first_aid_training.mp4 |

## Audio URLs (scored from the file name only)

| ID | Group | Risk score | Risk level | Words matched | URL |
|---|---|---|---|---|---|
| A01 | good | 0.4 | medium | - | https://example.com/audio/morning_birdsong.wav |
| A02 | good | 0.4 | medium | - | https://example.com/audio/piano_practice.mp3 |
| A03 | bad | 0.65 | high | hate, threat | https://example.com/audio/hate_threat_voicemail.mp3 |
| A04 | bad | 0.65 | high | abuse, violent | https://example.com/audio/violent_abuse_recording.wav |
| A05 | false-positive check | 0.4 | medium | harassment | https://example.com/audio/anti_harassment_training_talk.mp3 |
