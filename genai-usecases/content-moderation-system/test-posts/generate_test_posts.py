"""
Generates the manual test set in this folder: text posts, images, audio, URL lists and
edge-case files, plus RESULTS_FROM_LOCAL_CHECKS.md.

    backend/.venv/Scripts/python.exe test-posts/generate_test_posts.py

Everything is invented or drawn by this script. There are no photographs and no real
harmful material: the "bad" posts are short made-up sentences that contain the words the
platform's detectors look for, and the "risky" images are plain colours and shapes that
trip its pixel heuristics.

The script also runs each text and image through the platform's local checks (keyword
detector, ML toxicity model if it is cached, policy keyword check, image pixel analysis)
and writes what they returned. It does not call a language model.
"""

import json
import math
import os
import struct
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ["USE_ML_MODELS"] = "true"
os.environ["ML_PRIMARY_MODEL"] = "toxic_bert"
os.environ["ML_USE_ENSEMBLE"] = "false"

from PIL import Image, ImageDraw  # noqa: E402

# id, group, what you should see, text
TEXT_POSTS = [
    # Clean, child-friendly topics
    ("T01", "good", "approved", "We built a baking soda volcano for the science fair and the experiment actually worked!"),
    ("T02", "good", "approved", "Our puppy met a kitten at the zoo today and they became best friends."),
    ("T03", "good", "approved", "Great football match last night, what a comeback in the second half."),
    ("T04", "good", "approved", "Solved a 1000 piece puzzle of a mountain lake this weekend."),
    ("T05", "good", "approved", "Thank you to everyone who helped at the school garden clean-up today."),
    # Clean, older audiences
    ("T06", "good", "approved", "Finally fixed that bug in my Python script after three hours of debugging."),
    ("T07", "good", "approved", "New phone review: the camera is good but the battery could be better."),
    ("T08", "good", "approved", "Went to a nightclub opening downtown, the music was loud and the queue was endless."),
    ("T09", "good", "approved", "Mortgage rates went up again this month, here is how we adjusted our budget."),
    # Sensitive topics: the platform usually asks for a human review
    ("T10", "sensitive", "human review", "Feeling stressed before exams, here is what helps my anxiety: sleep, walks and talking to friends."),
    ("T11", "sensitive", "human review", "Stock tips: where to invest before the election results come in."),
    ("T12", "sensitive", "human review", "My doctor changed my diagnosis and I am trying a new treatment plan."),
    # Rude or insulting
    ("T13", "bad", "flagged", "Honestly that referee was stupid, what a terrible call in the match."),
    ("T14", "bad", "flagged or removed", "You are such an idiot, nobody wants to read your stupid posts. I hate you, loser."),
    ("T15", "bad", "flagged or removed", "Shut up, you worthless clown, everyone here thinks you are pathetic."),
    # Threats and violence keywords
    ("T16", "bad", "removed or human review", "I will attack you after school tomorrow, watch your back."),
    ("T17", "bad", "removed or human review", "Keep posting and I will threaten everyone in this group until you stop."),
    # Harassment and hate keywords
    ("T18", "bad", "removed or human review", "People who support that team are inferior and I hate every one of them."),
    ("T19", "bad", "removed or human review", "We should harass and stalk this user until they delete their account."),
    # Spam
    ("T20", "bad", "warned or human review", "Click here and buy now! Limited offer, free money guaranteed, act now!"),
    ("T21", "bad", "warned or human review", "Work from home, guaranteed income, click here, limited offer ends today!"),
    # Misinformation phrases
    ("T22", "bad", "warned or human review", "The secret truth they hide: this guaranteed cure works and mainstream media lies about it."),
    ("T23", "bad", "warned or human review", "Doctors don't want you to know this one trick that replaces all medicine."),
    # Adult-content keywords (an advert-style line, nothing graphic)
    ("T24", "bad", "removed or human review", "Adults only link inside: xxx videos and nude pics, click to see."),
    # Should be fine, but contain a trigger word (false-positive checks)
    ("T25", "false-positive check", "ideally approved", "The bomb scene in that action movie was the best part of the film."),
    ("T26", "false-positive check", "ideally approved", "A local charity talk on suicide prevention and where to find a helpline is on Friday."),
    ("T27", "false-positive check", "ideally approved", "I reported an account that keeps posting supremacist slogans, please remove it."),
    ("T28", "false-positive check", "ideally approved", "Our team will kill it at the quiz tonight, we have practised all week."),
    ("T29", "false-positive check", "ideally approved", "Someone is trying to harass my sister online, how do we report it?"),
    # Edge cases
    ("T30", "edge", "approved", "ok"),
    ("T31", "edge", "approved", "LOVED THE SCHOOL PLAY TONIGHT!!! BEST SHOW EVER!!!"),
    ("T32", "edge", "approved", "Good morning everyone ☀️\U0001F33B hope you all have a lovely day \U0001F60A"),
    ("T33", "edge", "approved", "आज हमने स्कूल में विज्ञान मेले में भाग लिया, बहुत मज़ा आया।"),
    ("T34", "edge", "approved", "ఈ రోజు మేము పాఠశాలలో క్రికెట్ ఆడాము, చాలా బాగుంది."),
    ("T35", "edge", "approved", "https://example.com/blog/how-to-grow-tomatoes"),
    ("T36", "edge", "flagged", "y0u are an 1d10t and a l0ser"),
    ("T37", "edge", "approved", "Sooooooo happyyyyyy todayyyyyy!!!!!!!!!!"),
    ("T38", "edge", "approved", "Here is my full trip report. " + "We walked, ate, rested and walked again. " * 60),
]

# Short comments: with fast mode on, these take the single-agent path
COMMENTS = [
    ("C01", "good", "approved", "Nice story, thanks for sharing!"),
    ("C02", "good", "approved", "I had the same experience last year."),
    ("C03", "bad", "flagged or removed", "This is a stupid story and you are an idiot."),
    ("C04", "bad", "warned or flagged", "Click here, buy now, free money!"),
    ("C05", "false-positive check", "ideally approved", "That ending killed me, so funny."),
]

IMAGE_URLS = [
    ("U01", "good", "https://example.com/uploads/planet_drawing.png"),
    ("U02", "good", "https://example.com/photos/school_trip_group.jpg"),
    ("U03", "bad", "https://example.com/uploads/nsfw_explicit_photo.jpg"),
    ("U04", "bad", "https://example.com/img/gore_blood_scene.png"),
    ("U05", "bad", "https://example.com/img/weapon_violent_poster.jpg"),
    ("U06", "false-positive check", "https://example.com/recipes/blood_orange_cake.jpg"),
]
VIDEO_URLS = [
    ("V01", "good", "https://example.com/videos/school_sports_day.mp4"),
    ("V02", "good", "https://example.com/videos/cooking_pasta_tutorial.mp4"),
    ("V03", "bad", "https://example.com/videos/street_fights_compilation.mp4"),
    ("V04", "bad", "https://example.com/videos/explicit_nsfw_clip.mp4"),
    ("V05", "bad", "https://example.com/videos/gore_attack_footage.mp4"),
    ("V06", "false-positive check", "https://example.com/videos/heart_attack_first_aid_training.mp4"),
]
AUDIO_URLS = [
    ("A01", "good", "https://example.com/audio/morning_birdsong.wav"),
    ("A02", "good", "https://example.com/audio/piano_practice.mp3"),
    ("A03", "bad", "https://example.com/audio/hate_threat_voicemail.mp3"),
    ("A04", "bad", "https://example.com/audio/violent_abuse_recording.wav"),
    ("A05", "false-positive check", "https://example.com/audio/anti_harassment_training_talk.mp3"),
]


# ─── images ─────────────────────────────────────────────────────────────────────

def landscape(size=(480, 320)):
    image = Image.new("RGB", size, (120, 180, 235))
    draw = ImageDraw.Draw(image)
    draw.ellipse((360, 30, 430, 100), fill=(250, 225, 90))
    draw.polygon([(0, 230), (140, 120), (280, 230)], fill=(90, 120, 110))
    draw.polygon([(180, 230), (330, 100), (480, 230)], fill=(80, 105, 100))
    draw.rectangle((0, 230, size[0], size[1]), fill=(70, 150, 80))
    return image


def cartoon_cat(size=(360, 360)):
    image = Image.new("RGB", size, (200, 225, 245))
    draw = ImageDraw.Draw(image)
    draw.polygon([(90, 130), (110, 50), (160, 110)], fill=(120, 120, 130))
    draw.polygon([(270, 130), (250, 50), (200, 110)], fill=(120, 120, 130))
    draw.ellipse((80, 90, 280, 290), fill=(120, 120, 130))
    for x in (140, 220):
        draw.ellipse((x - 16, 160, x + 16, 192), fill=(240, 240, 240))
        draw.ellipse((x - 6, 168, x + 6, 184), fill=(20, 20, 20))
    draw.polygon([(172, 215), (188, 215), (180, 228)], fill=(60, 60, 70))
    return image


def notice_card(size=(480, 270)):
    image = Image.new("RGB", size, (245, 245, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, size[0] - 20, size[1] - 20), outline=(40, 80, 150), width=6)
    draw.text((60, 90), "SCIENCE FAIR", fill=(40, 80, 150))
    draw.text((60, 130), "Friday 10 am, main hall", fill=(60, 60, 60))
    return image


def bar_chart(size=(480, 320)):
    image = Image.new("RGB", size, (250, 250, 250))
    draw = ImageDraw.Draw(image)
    for index, height in enumerate((90, 160, 120, 210, 180)):
        left = 50 + index * 85
        draw.rectangle((left, 290 - height, left + 55, 290), fill=(60, 110, 190))
    draw.line((40, 290, 460, 290), fill=(80, 80, 80), width=2)
    return image


def plain(colour, size=(320, 320)):
    return Image.new("RGB", size, colour)


def half_and_half(left, right, size=(320, 320)):
    image = Image.new("RGB", size, left)
    ImageDraw.Draw(image).rectangle((size[0] // 2, 0, size[0], size[1]), fill=right)
    return image


def night_sky(size=(480, 320)):
    image = Image.new("RGB", size, (8, 10, 30))
    draw = ImageDraw.Draw(image)
    for index in range(60):
        x, y = (index * 97) % size[0], (index * 53) % 220
        draw.point((x, y), fill=(230, 230, 240))
    draw.ellipse((380, 30, 430, 80), fill=(235, 235, 220))
    return image


def sunset(size=(480, 320)):
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        ratio = y / size[1]
        draw.line((0, y, size[0], y), fill=(int(250 - 40 * ratio), int(120 + 60 * ratio), int(70 + 40 * ratio)))
    return image


# file name, group, description, builder
IMAGES = [
    ("good_landscape.png", "good", "Sky, sun, mountains, grass", landscape),
    ("good_cartoon_cat.png", "good", "Simple cartoon cat on pale blue", cartoon_cat),
    ("good_notice_card.png", "good", "Text notice on a pale card", notice_card),
    ("good_bar_chart.png", "good", "Blue bar chart", bar_chart),
    ("good_plain_blue.jpg", "good", "Plain blue square", lambda: plain((70, 130, 220))),
    ("risky_skin_tone_block.png", "bad (heuristic)", "Plain tan square: 100% 'skin' pixels", lambda: plain((224, 172, 105))),
    ("risky_half_skin_tone.png", "bad (heuristic)", "Half tan, half blue", lambda: half_and_half((224, 172, 105), (70, 130, 220))),
    ("risky_saturated_red.png", "bad (heuristic)", "Plain bright red square", lambda: plain((230, 30, 30))),
    ("risky_dark_red.png", "bad (heuristic)", "Plain dark red square", lambda: plain((120, 10, 10))),
    ("fp_sunset_gradient.jpg", "false-positive check", "Orange sunset gradient, an ordinary scene", sunset),
    ("fp_beige_wall.jpg", "false-positive check", "A beige wall colour swatch", lambda: plain((205, 170, 125))),
    ("fp_night_sky.png", "false-positive check", "Dark night sky with stars", night_sky),
    ("named_nsfw_but_harmless.png", "file-name check", "The harmless landscape under a risky file name", landscape),
    ("edge_tiny_1x1.png", "edge", "1 x 1 pixel image", lambda: plain((255, 255, 255), (1, 1))),
    ("edge_very_wide.png", "edge", "2000 x 40 strip", lambda: plain((90, 160, 90), (2000, 40))),
]


def write_wav(path: Path, frequency: float, seconds: float = 1.5, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * frequency * n / rate))) for n in range(int(rate * seconds))
        )
        handle.writeframes(frames)


def animated_gif(path: Path) -> None:
    frames = []
    for step in range(12):
        frame = Image.new("RGB", (240, 160), (120, 180, 235))
        ImageDraw.Draw(frame).ellipse((10 + step * 16, 60, 50 + step * 16, 100), fill=(250, 225, 90))
        frames.append(frame)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=90, loop=0)


def local_text_checks(text: str):
    """Keyword toxicity, ML toxicity (None if the model is unavailable) and policy keywords."""
    from src.utils.tools import check_policy_violations, detect_toxicity

    keyword = detect_toxicity(text, use_ml=False)
    try:
        ml_score = round(float(detect_toxicity(text, use_ml=True)["toxicity_score"]), 2)
    except Exception:
        ml_score = None
    policy = check_policy_violations(text, "post", 0.7, keyword["toxicity_score"])
    return round(float(keyword["toxicity_score"]), 2), ml_score, policy["violations"], policy["severity"]


def main() -> int:
    for folder in ("text", "images", "videos", "audio", "other"):
        (HERE / folder).mkdir(exist_ok=True)

    # text
    (HERE / "text" / "posts.json").write_text(json.dumps(
        [{"id": i, "group": g, "expect": e, "text": t} for i, g, e, t in TEXT_POSTS], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (HERE / "text" / "comments.json").write_text(json.dumps(
        [{"id": i, "group": g, "expect": e, "text": t} for i, g, e, t in COMMENTS], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    lines = ["Copy one block at a time into the post box.", ""]
    for post_id, group, expect, text in TEXT_POSTS + COMMENTS:
        lines += [f"[{post_id}] {group} - expect: {expect}", text, ""]
    (HERE / "text" / "posts_to_copy.txt").write_text("\n".join(lines), encoding="utf-8")

    # images
    for name, _, _, builder in IMAGES:
        image = builder()
        image.save(HERE / "images" / name, quality=92) if name.endswith(".jpg") else image.save(HERE / "images" / name)
    animated_gif(HERE / "images" / "good_animated_sun.gif")
    (HERE / "images" / "image_urls.txt").write_text(
        "\n".join(f"[{i}] {g}\n{u}\n" for i, g, u in IMAGE_URLS), encoding="utf-8")

    # video and audio
    (HERE / "videos" / "video_urls.txt").write_text(
        "\n".join(f"[{i}] {g}\n{u}\n" for i, g, u in VIDEO_URLS), encoding="utf-8")
    write_wav(HERE / "audio" / "good_tone_440hz.wav", 440.0)
    write_wav(HERE / "audio" / "good_tone_880hz.wav", 880.0)
    (HERE / "audio" / "audio_urls.txt").write_text(
        "\n".join(f"[{i}] {g}\n{u}\n" for i, g, u in AUDIO_URLS), encoding="utf-8")

    # edge-case files
    (HERE / "other" / "not_an_image.jpg").write_text("This is a text file with a .jpg extension.\n", encoding="utf-8")
    (HERE / "other" / "empty_file.png").write_bytes(b"")
    (HERE / "other" / "plain_text_note.txt").write_text("A plain text file, to try in the image upload.\n", encoding="utf-8")
    landscape().save(HERE / "other" / "image_with_wrong_extension.txt", format="PNG")
    truncated = (HERE / "images" / "good_landscape.png").read_bytes()[:400]
    (HERE / "other" / "truncated_image.png").write_bytes(truncated)

    # local checks
    from src.utils.tools import analyze_uploaded_image, score_media_urls

    report = ["# What the platform's local checks return for this test set", "",
              "Produced by `generate_test_posts.py`. These are the parts of the pipeline that run",
              "without a language model. The final decision in the app also depends on the",
              "language model and on the routing between agents, so use this as a reference for",
              "what to expect, not as the expected final result.", "",
              "## Text", "",
              "| ID | Group | Keyword toxicity | ML toxicity (toxic-bert) | Policy keywords | Severity | Text |",
              "|---|---|---|---|---|---|---|"]
    for post_id, group, _, text in TEXT_POSTS + COMMENTS:
        keyword, ml_score, violations, severity = local_text_checks(text)
        shown = text if len(text) <= 70 else text[:67] + "..."
        report.append(f"| {post_id} | {group} | {keyword} | {'n/a' if ml_score is None else ml_score} | "
                      f"{', '.join(violations) or '-'} | {severity} | {shown} |")

    report += ["", "## Image files (pixel analysis of the uploaded file)", "",
               "| File | Group | Risk score | Risk level | Marked unsafe | Skin ratio | Dark ratio | Red ratio |", "|---|---|---|---|---|---|---|---|"]
    for name, group, _, _ in IMAGES + [("good_animated_sun.gif", "good", "", None)]:
        result = analyze_uploaded_image((HERE / "images" / name).read_bytes(), name)
        report.append(f"| {name} | {group} | {result['risk_score']} | {result['risk_level']} | {result['is_unsafe']} | "
                      f"{result.get('skin_ratio')} | {result.get('dark_ratio')} | {result.get('saturated_ratio')} |")
    report += ["", "## Edge-case files in the image upload", "", "| File | Accepted | Result |", "|---|---|---|"]
    for name in ("not_an_image.jpg", "empty_file.png", "plain_text_note.txt", "image_with_wrong_extension.txt", "truncated_image.png"):
        result = analyze_uploaded_image((HERE / "other" / name).read_bytes(), name)
        report.append(f"| {name} | {result['valid']} | {result.get('error') or result['risk_level']} |")

    for title, kind, urls in (("Image URLs", "image", IMAGE_URLS), ("Video URLs", "video", VIDEO_URLS), ("Audio URLs", "audio", AUDIO_URLS)):
        report += ["", f"## {title} (scored from the file name only)", "", "| ID | Group | Risk score | Risk level | Words matched | URL |", "|---|---|---|---|---|---|"]
        for url_id, group, url in urls:
            result = score_media_urls([url], media_type=kind)
            report.append(f"| {url_id} | {group} | {result['risk_score']} | {result['risk_level']} | {', '.join(result['signals']) or '-'} | {url} |")

    (HERE / "RESULTS_FROM_LOCAL_CHECKS.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"text posts: {len(TEXT_POSTS)}, comments: {len(COMMENTS)}, images: {len(IMAGES) + 1}, "
          f"urls: {len(IMAGE_URLS) + len(VIDEO_URLS) + len(AUDIO_URLS)}, audio files: 2, edge files: 5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
