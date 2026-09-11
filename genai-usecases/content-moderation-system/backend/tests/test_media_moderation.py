from pydantic import BaseModel

from src.utils.tools import score_media_urls
from main import ContentSubmission


def test_score_media_urls_detects_risky_media():
    result = score_media_urls(
        [
            "https://cdn.example.com/images/explicit-nsfw-scene.jpg",
            "https://cdn.example.com/videos/gore-violence.mp4",
        ],
        media_type="image",
    )

    assert result["risk_score"] > 0.3
    assert result["risk_level"] in {"low", "medium", "high", "severe"}
    assert len(result["signals"]) > 0


def test_content_submission_accepts_media_urls():
    payload = ContentSubmission(
        content_text="",
        content_type="video",
        image_urls=["https://cdn.example.com/img1.jpg"],
        video_urls=["https://cdn.example.com/clip.mp4"],
        audio_urls=["https://cdn.example.com/audio.wav"],
    )

    assert payload.image_urls[0].endswith(".jpg")
    assert payload.video_urls[0].endswith(".mp4")
    assert payload.audio_urls[0].endswith(".wav")
