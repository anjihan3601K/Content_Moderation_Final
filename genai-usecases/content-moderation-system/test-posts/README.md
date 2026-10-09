# Test posts for manual moderation checks

A set of posts, images, URLs and odd files to submit by hand and watch how the platform
moderates them. Everything here is invented or drawn by `generate_test_posts.py`: there
are no photographs and no real harmful material. The "bad" posts are short made-up
sentences containing the words the detectors look for; the "risky" images are plain
colours and shapes that trip the pixel checks.

## What is in each folder

| Folder | Contents | How to use it |
|---|---|---|
| `text/posts_to_copy.txt` | 38 posts and 5 short comments, each with an ID and what to expect | Copy one block into the post or story box and submit |
| `text/posts.json`, `comments.json` | The same, as data | For scripts |
| `images/` | 16 image files (PNG, JPG, one animated GIF) | Attach with the image upload on the story form |
| `images/image_urls.txt` | 6 image URLs | Paste into the image URL field |
| `videos/video_urls.txt` | 6 video URLs | Paste into the video URL field |
| `audio/audio_urls.txt` | 5 audio URLs | Only through the API (`audio_urls`); the forms have no audio field |
| `audio/*.wav` | Two harmless tone files | For when audio upload exists; nothing accepts them today |
| `other/` | 5 broken or mislabelled files | Try them in the image upload; most should be refused |

**There are no video files.** The platform has no video upload: it only takes a video URL
and scores it from the words in the file name. The URLs point at `example.com` and do not
need to exist.

## The groups

| Group | Meaning |
|---|---|
| good | Should be approved |
| sensitive | Harmless, but on a topic (health, politics, money) where the platform usually asks for human review |
| bad | Should be flagged, warned, sent to human review or removed |
| false-positive check | Harmless, but contains a word a detector reacts to. Shows where the platform over-blocks |
| edge | Unusual input: very short, very long, all capitals, emoji, Hindi, Telugu, a bare link, letters swapped for digits |
| file-name check | A harmless image saved under a risky file name |

## What to expect

`RESULTS_FROM_LOCAL_CHECKS.md` lists what the platform's own checks return for every item
here: keyword toxicity, the ML toxicity model, policy keywords, image pixel analysis and
URL scoring. It was produced by running those checks, not written by hand.

It is a reference, not the final answer. In the app the outcome also depends on the
language model and on the routing between agents, so a post can end up approved, held for
human review, warned or removed in ways the local checks alone do not decide.

Things the local checks already show, so they do not surprise you:

- **Ordinary scenes can be marked unsafe.** The orange sunset and the beige wall are scored
  "severe", because the pixel check counts warm colours as skin. The night sky is "medium".
- **Any image, video or audio URL scores at least "medium"**, even the harmless ones. The
  score comes from the URL alone.
- **The file name of an uploaded image is ignored.** `named_nsfw_but_harmless.png` scores
  the same as the landscape it copies.
- **Harmless sentences with a trigger word are treated as violations**: the movie "bomb
  scene" and "kill it at the quiz" count as violence, the suicide-prevention talk as
  critical self-harm, and asking how to report harassment as harassment.
- **Swapping letters for digits fools the keyword check but not the ML model**: T36 scores
  0.0 on keywords and 0.73 on the model.
- **The ML model reads no Hindi or Telugu toxicity**; those two posts are harmless anyway.
- A file with the wrong extension is accepted if its contents are a real image.

## Recording results

For each item note: the ID, the status the app shows (approved, flagged, under review,
pending human review, warned, removed), and what the review page shows under
"Recommendation" (audience rating, tags, suggested for). Compare with the group above.

Each full post uses about 5 language-model calls. On the Gemini free tier (20 requests a
day) that is 3 or 4 posts before every later post gets stuck as "under review".

## Regenerating

```
backend/.venv/Scripts/python.exe test-posts/generate_test_posts.py
```
