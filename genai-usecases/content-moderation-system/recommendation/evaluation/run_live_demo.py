"""
Live end-to-end demo: sample posts and images through the REAL moderation pipeline, with
the ML models and the recommendation feature switched on.

    backend/.venv/Scripts/python.exe recommendation/evaluation/run_live_demo.py
    backend/.venv/Scripts/python.exe recommendation/evaluation/run_live_demo.py --real-llm

With ``--real-llm`` the agents call the language model the backend is configured for
(Gemini today), using GOOGLE_API_KEY from the environment of this process. The key is
read from the environment only; this script never writes it anywhere. The sample posts
are sent to that provider. Output then goes to ``live_demo_real_llm_report.txt`` and
``live_demo_real_llm_results.json``.

What is real in this run
    - the LangGraph workflow and every agent in backend/src/agents
    - the ML toxicity models (USE_ML_MODELS=true)
    - the policy keyword checks, reputation scoring, media heuristics and image analysis
    - the audience rating, safety gate, feed, moderator queue, precedents and feedback

What is not
    - the language model. No provider is called; ``standin_llm.StandInLLM`` answers the
      agents' prompts from keyword lists. Topic extraction in particular comes from it.
    - the databases. Everything is written to a temporary folder; the project's own
      database files are not touched.

Writes recommendation/results/live_demo_report.txt and live_demo_results.json.
"""

import io
import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
RESULTS_DIR = PROJECT_ROOT / "recommendation" / "results"
WORK_DIR = Path(tempfile.mkdtemp(prefix="rec_live_demo_"))

os.environ["RECOMMENDATION_ENABLED"] = "true"
os.environ["USE_ML_MODELS"] = "true"
os.environ["ML_PRELOAD_MODELS"] = "true"
os.environ["ENABLE_FAST_MODE"] = "false"
os.environ["CHROMA_DB_PATH"] = str(WORK_DIR / "chroma")
os.environ["RECOMMENDATION_DB_PATH"] = str(WORK_DIR / "recommendation_data.db")
REAL_LLM = "--real-llm" in sys.argv
if REAL_LLM and not os.environ.get("GOOGLE_API_KEY"):
    sys.exit("--real-llm needs GOOGLE_API_KEY in the environment of this process")
os.environ.setdefault("GOOGLE_API_KEY", "not-used-standin-llm")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
# Use the toxicity model that is already in the local Hugging Face cache, so the demo
# needs no download. The project's default (distilbert_toxic) is not cached on this machine.
os.environ["ML_PRIMARY_MODEL"] = "toxic_bert"
os.environ["ML_USE_ENSEMBLE"] = "false"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(WORK_DIR)

import src.agents.agents as agents_module  # noqa: E402
from standin_llm import StandInLLM  # noqa: E402

REAL_LLM_MODEL = os.environ.get("DEMO_LLM_MODEL", "gemini-3.8-flash")
LLM_CALLS = {"count": 0, "failures": 0, "seconds": 0.0}


class RealLLMAdapter:
    """
    The backend's real Gemini chat model, with the two adjustments it needs to run today.

    1. ``backend/src/agents/agents.py`` asks for ``gemini-2.0-flash``, which the provider
       has retired (HTTP 404). The model named in DEMO_LLM_MODEL is used instead.
    2. Current Gemini models return ``content`` as a list of blocks; the agents treat it
       as a string (``.find``, ``.strip``, ``in``). The text blocks are joined here.

    Both are applied in this process only. No backend file is edited.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["model"] = REAL_LLM_MODEL
        kwargs.setdefault("max_retries", 2)
        self.inner = _RealChatModel(*args, **kwargs)

    def invoke(self, prompt: Any) -> Any:
        import time

        from standin_llm import StandInResponse

        started = time.perf_counter()
        for attempt in range(5):
            try:
                response = self.inner.invoke(prompt)
                break
            except Exception as failure:
                LLM_CALLS["failures"] += 1
                if attempt == 4 or "429" not in str(failure) and "quota" not in str(failure).lower():
                    raise
                time.sleep(15 * (attempt + 1))
        LLM_CALLS["count"] += 1
        LLM_CALLS["seconds"] += time.perf_counter() - started
        content = response.content
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content if not isinstance(block, dict) or block.get("type") == "text"
            )
        return StandInResponse(str(content))


if REAL_LLM:
    _RealChatModel = agents_module.ChatGoogleGenerativeAI
    agents_module.ChatGoogleGenerativeAI = RealLLMAdapter
else:
    agents_module.ChatGoogleGenerativeAI = StandInLLM

from src.agents.workflow import create_moderation_workflow, process_content  # noqa: E402
from src.core.models import ContentMetadata, ContentStatus, UserProfile  # noqa: E402
from src.ml.ml_classifier import get_ml_status, preload_ml_models  # noqa: E402
from src.utils.tools import analyze_uploaded_image  # noqa: E402

from recommendation.src import integration  # noqa: E402
from recommendation.src.api import build_container  # noqa: E402
from recommendation.src.models import AgeTier, AgeTrustLevel, FeedbackEvent, ParentalControls, ViewerProfileModel  # noqa: E402
from recommendation.src.rating import derive_audience_rating  # noqa: E402
from recommendation.src.safety_gate import SafetyGate  # noqa: E402

logging.getLogger().setLevel(logging.ERROR)
for noisy in ("src", "recommendation", "httpx", "chromadb", "transformers"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

# Mild, invented sample posts. The "bad" ones use only insults and spam phrases strong
# enough to trigger the detectors; none contains real harmful material.
SAMPLE_POSTS: List[Dict[str, Any]] = [
    {"id": "post-01", "text": "We built a baking soda volcano for the science fair and the experiment actually worked!"},
    {"id": "post-02", "text": "Our puppy met a kitten at the zoo today and they became best friends."},
    {"id": "post-03", "text": "Great football match last night, what a comeback in the second half."},
    {"id": "post-04", "text": "Finally fixed that bug in my Python script after three hours of debugging."},
    {"id": "post-05", "text": "New phone review: the camera is good but the battery on this laptop rival is better."},
    {"id": "post-06", "text": "Feeling stressed before exams, here is what helps my anxiety: sleep, walks and talking to friends."},
    {"id": "post-07", "text": "Stock tips: where to invest before the election results come in."},
    {"id": "post-08", "text": "Went to a nightclub opening downtown, the music was loud and the queue was endless."},
    {"id": "post-09", "text": "You are such an idiot, nobody wants to read your stupid posts. I hate you, loser."},
    {"id": "post-10", "text": "Click here and buy now! Limited offer, free money guaranteed, act now!"},
    {"id": "post-11", "text": "The secret truth they hide: this guaranteed cure works and mainstream media lies about it."},
    {"id": "post-12", "text": "Honestly that referee was stupid, what a terrible call in the match."},
    {"id": "post-13", "text": "Look at this drawing I made of a planet with rings!",
     "image_urls": ["https://example.com/uploads/planet_drawing.png"]},
    {"id": "post-14", "text": "Photos from the football match.",
     "image_urls": ["https://example.com/uploads/nsfw_explicit_photo.jpg"]},
    {"id": "post-15", "text": "A local charity talk on suicide prevention and where to find a helpline is on Friday."},
    {"id": "post-16", "text": "Solved a 1000 piece puzzle of a volcano this weekend."},
]

VIEWERS = [
    ("child-1", AgeTier.CHILD, AgeTrustLevel.VERIFIED, ["science", "animals"], {}),
    ("child-2", AgeTier.CHILD, AgeTrustLevel.PARENT_LINKED, ["sports", "puzzles"], {"blocked_categories": ["sports"]}),
    ("teen-1", AgeTier.TEEN, AgeTrustLevel.VERIFIED, ["coding", "sports"], {}),
    ("teen-2", AgeTier.TEEN, AgeTrustLevel.SELF_DECLARED, ["technology"], {"allowed_sensitive_topics": ["mental_health"]}),
    ("adult-1", AgeTier.ADULT, AgeTrustLevel.VERIFIED, ["finance", "news"], {}),
]

LINES: List[str] = []


def out(text: str = "") -> None:
    LINES.append(text)
    print(text)


def table(header: List[str], rows: List[List[Any]]) -> None:
    widths = [max(len(str(c)) for c in column) for column in zip(header, *rows)] if rows else [len(h) for h in header]
    out("  ".join(str(h).ljust(w) for h, w in zip(header, widths)))
    out("  ".join("-" * w for w in widths))
    for row in rows:
        out("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))


def initial_state(post: Dict[str, Any]) -> Dict[str, Any]:
    """The same initial state backend/main.py builds for POST /api/content/submit."""
    content_id = post["id"]
    now = datetime.now().isoformat()
    profile = UserProfile(
        user_id="demo-author", username="demo_author", account_age_days=400, total_posts=120,
        total_violations=0, previous_warnings=0, previous_suspensions=0, reputation_score=0.8,
        reputation_tier="new_user", verified=False, follower_count=50,
    )
    metadata = ContentMetadata(content_id=content_id, content_type="post", platform="demo", created_at=now, language="en")
    return {
        "content_id": content_id, "submission_id": f"sub-{content_id}", "submission_timestamp": now,
        "content_text": post["text"], "content_type": "post", "content_metadata": metadata,
        "image_urls": list(post.get("image_urls", [])), "video_urls": [], "audio_urls": [],
        "image_descriptions": [], "detected_objects": [], "detected_text_in_media": [],
        "media_risk_score": 0.0, "media_risk_level": "none", "media_signals": [],
        "user_profile": profile, "user_id": profile.user_id, "username": profile.username,
        "content_category": None, "content_sentiment": None, "content_topics": [],
        "contains_sensitive_content": False, "explicit_content_detected": False,
        "toxicity_score": None, "toxicity_level": None, "toxicity_categories": [],
        "hate_speech_detected": False, "harassment_detected": False,
        "policy_violations": [], "violation_severity": None, "policy_flags": [], "recommended_action": None,
        "user_reputation_score": None, "user_reputation_tier": None, "user_risk_score": None,
        "user_history_flags": [], "similar_violations_count": 0,
        "is_appeal": False, "appeal_reason": None, "original_decision": None, "appeal_timestamp": None,
        "moderation_action": None, "action_reason": "", "action_timestamp": None, "user_notified": False,
        "content_removed": False, "user_suspended": False, "suspension_duration_days": None,
        "agent_decisions": [], "current_agent": None,
        "status": ContentStatus.SUBMITTED.value, "requires_human_review": False, "human_review_reason": None,
        "overall_confidence": 0.0,
        "reviewer_name": None, "review_notes": None, "review_decision": None, "review_timestamp": None,
        "created_at": now, "processed_at": None, "similar_content": None, "historical_patterns": None,
        "react_think_output": None, "react_act_decision": None, "react_observe_result": None,
        "react_confidence": None, "react_reasoning": None,
        "hitl_required": False, "hitl_trigger_reasons": [], "hitl_checkpoint": None, "hitl_priority": None,
        "hitl_assigned_to": None, "hitl_queue_position": None, "hitl_waiting_since": None,
        "hitl_human_decision": None, "hitl_human_notes": None, "hitl_human_confidence_override": None,
        "hitl_resolution_timestamp": None,
    }


def make_test_image(kind: str) -> bytes:
    """A small generated PNG: no photographs are used."""
    from PIL import Image

    colours = {"blue_sky": (70, 130, 220), "skin_tone_block": (224, 172, 105), "dark_red": (120, 10, 10), "bright_green": (40, 220, 60)}
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), colours[kind]).save(buffer, format="PNG")
    return buffer.getvalue()


def short(value: Any, width: int) -> str:
    text = str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def main() -> int:
    results: Dict[str, Any] = {"run_at": datetime.now().isoformat(timespec="seconds")}

    out("=" * 100)
    out("LIVE DEMO - real moderation pipeline, ML models on, recommendation feature on, "
        + ("REAL language model (Gemini)" if REAL_LLM else "stand-in LLM"))
    out("=" * 100)

    # 1. Engines
    ml_preload = preload_ml_models()
    ml_status = get_ml_status()
    out("\n1. ENGINES")
    table(["engine", "state"], [
        ["Recommendation feature (RECOMMENDATION_ENABLED)", os.environ["RECOMMENDATION_ENABLED"]],
        ["ML models (USE_ML_MODELS)", os.environ["USE_ML_MODELS"]],
        ["ML preload status", ml_preload.get("status")],
        ["ML device", ml_preload.get("device", ml_status.get("device", "n/a"))],
        ["ML models available", ", ".join(ml_preload.get("models_available", []) or ["none"])],
        ["Language model", f"REAL: {REAL_LLM_MODEL} through the backend's own agent code and prompts" if REAL_LLM
         else "STAND-IN (keyword rules); no Gemini or Claude call is made"],
        ["Databases", f"temporary folder {WORK_DIR}"],
    ])
    results["engines"] = {"ml_preload": {k: v for k, v in ml_preload.items() if isinstance(v, (str, int, float, bool, list))}}

    # 2. Moderate the sample posts through the real workflow
    container = build_container(db_path=os.environ["RECOMMENDATION_DB_PATH"])
    integration.set_repository(container.repository)
    workflow = create_moderation_workflow(None, enable_fast_mode=False)

    out("\n2. MODERATION PIPELINE - one row per post")
    rows, post_results = [], []
    for post in SAMPLE_POSTS:
        try:
            final = process_content(workflow, initial_state(post))
            error = None
        except Exception as failure:  # report, do not hide
            final, error = None, f"{type(failure).__name__}: {failure}"
        if final is None:
            rows.append([post["id"], short(post["text"], 44), "PIPELINE ERROR", "", "", "", "", "", short(error, 30)])
            post_results.append({"id": post["id"], "error": error})
            continue
        rating = derive_audience_rating(final)
        verdicts = [
            f"{d.agent_name.replace(' Agent', '').replace(' Detection', '').replace(' Violation', '')}:"
            f"{getattr(d.decision, 'value', d.decision)}"
            for d in final.get("agent_decisions", [])
        ]
        toxicity = final.get("toxicity_score")
        rows.append([
            post["id"], short(post["text"], 44),
            f"{toxicity:.2f}" if isinstance(toxicity, (int, float)) else "n/a",
            ",".join(final.get("policy_violations") or []) or "-",
            final.get("violation_severity") or "-",
            f"{final.get('content_category')}",
            final.get("status"),
            final.get("audience_rating") or "unrated",
            short("; ".join(rating.reasons) or "no rule raised the rating", 60),
        ])
        post_results.append({
            "id": post["id"], "text": post["text"], "image_urls": post.get("image_urls", []),
            "toxicity_score": toxicity, "toxicity_level": final.get("toxicity_level"),
            "policy_violations": final.get("policy_violations"), "violation_severity": final.get("violation_severity"),
            "media_risk_level": final.get("media_risk_level"), "media_risk_score": final.get("media_risk_score"),
            "content_category": final.get("content_category"), "content_topics": final.get("content_topics"),
            "status": final.get("status"), "moderation_action": final.get("moderation_action"),
            "hitl_required": final.get("hitl_required"), "hitl_trigger_reasons": final.get("hitl_trigger_reasons"),
            "agent_verdicts": verdicts, "agent_disagreement": final.get("agent_disagreement"),
            "audience_rating": final.get("audience_rating"), "rating_reasons": list(rating.reasons),
            "escalation_categories": list(rating.escalation_categories),
        })
    table(["post", "text", "ML tox", "violations", "severity", "category", "status", "rating", "why this rating"], rows)
    results["posts"] = post_results

    out("\n   Agent verdicts per post")
    table(["post", "verdicts (agent:decision)", "disagreement", "human review needed"], [
        [p["id"], short(" ".join(p["agent_verdicts"]), 96), p["agent_disagreement"],
         ("yes: " + ",".join(p.get("hitl_trigger_reasons") or [])) if p.get("hitl_required") else "no"]
        for p in post_results if "error" not in p
    ])

    # 3. Image analysis
    out("\n3. IMAGE ANALYSIS - generated test images through analyze_uploaded_image (pixel heuristics)")
    image_rows, image_results = [], []
    for kind in ("blue_sky", "bright_green", "skin_tone_block", "dark_red"):
        analysis = analyze_uploaded_image(make_test_image(kind), f"{kind}.png")
        image_rows.append([kind, analysis["risk_score"], analysis["risk_level"], analysis["is_unsafe"],
                           analysis.get("skin_ratio"), analysis.get("dark_ratio"), analysis.get("saturated_ratio")])
        image_results.append({"image": kind, **analysis})
    table(["image", "risk score", "risk level", "unsafe", "skin ratio", "dark ratio", "saturated ratio"], image_rows)
    out("   Image URLs attached to posts are scored separately, from the file name only (score_media_urls):")
    table(["post", "image url", "media risk"], [
        [p["id"], p["image_urls"][0], f"{p['media_risk_level']} ({p['media_risk_score']})"]
        for p in post_results if p.get("image_urls")
    ])
    results["images"] = image_results

    # 4. What the recommender stored
    repository = container.repository
    stored = repository.list_items()
    out(f"\n4. RECOMMENDER STORE - {len(stored)} items stored by the workflow hook")
    table(["item", "rating", "status", "category", "topics", "disagreement", "confidence", "escalated"], [
        [i.item_id, i.audience_rating.value if i.audience_rating else "unrated", i.status, i.content_category,
         ",".join(i.content_topics) or "-", i.agent_disagreement, i.overall_confidence, i.escalated]
        for i in stored
    ])

    # 5. Feeds
    out("\n5. FEEDS - what each viewer is served, and why the rest was withheld")
    feed_rows, feed_results = [], []
    for profile_id, tier, trust, interests, controls in VIEWERS:
        repository.save_profile(ViewerProfileModel(
            profile_id=profile_id, user_id=profile_id, age_tier=tier, age_trust_level=trust,
            explicit_interests=interests, parental_controls=ParentalControls(**controls), tier_declared=True,
        ))
        feed = container.feed_service.get_feed(profile_id, limit=10)
        served = [item.item_id for item in feed.items]
        feed_rows.append([profile_id, tier.value, trust.value, ",".join(interests),
                          json.dumps(controls) if controls else "-", " ".join(served) or "(nothing)",
                          json.dumps(feed.rejection_summary, sort_keys=True)])
        feed_results.append({"profile": profile_id, "tier": tier.value, "trust": trust.value, "interests": interests,
                             "controls": controls, "served": served, "rejections": feed.rejection_summary})
    default_feed = container.feed_service.get_feed("brand-new-account", limit=10)
    feed_rows.append(["brand-new-account", "adult (default)", "self_declared", "-", "-",
                      " ".join(i.item_id for i in default_feed.items) or "(nothing)",
                      json.dumps(default_feed.rejection_summary, sort_keys=True)])
    table(["viewer", "tier", "trust", "interests", "parental controls", "served (ranked)", "withheld, by reason"], feed_rows)
    results["feeds"] = feed_results

    out("\n   Gate decision for every item, per viewer (S = served, otherwise the rejection reason)")
    matrix_header = ["item", "rating"] + [v[0] for v in VIEWERS]
    matrix = []
    for item in stored:
        row = [item.item_id, item.audience_rating.value if item.audience_rating else "unrated"]
        for profile_id, *_ in VIEWERS:
            decision = SafetyGate.evaluate_item(repository.get_profile(profile_id), item)
            row.append("S" if decision.passed else decision.rejection_reason.value)
        matrix.append(row)
    table(matrix_header, matrix)

    # 6. Moderator queue
    out("\n6. MODERATOR QUEUE - as a senior moderator sees it")
    queue = container.prioritizer.prioritize_queue(repository.list_items())
    table(["#", "item", "status", "escalated", "priority", "harm", "uncertainty", "exposure"], [
        [n + 1, q.content_id, q.status, q.is_escalated, q.priority_score, q.expected_harm, q.agent_disagreement, q.exposure_score]
        for n, q in enumerate(queue)
    ] or [["-", "(queue is empty)", "", "", "", "", "", ""]])
    results["queue"] = [q.model_dump(mode="json") for q in queue]

    # 7. Moderator decision and its effect
    if queue:
        target = queue[0]
        item = repository.get_item(target.content_id)
        precedents = container.precedents.get_similar_precedents(item, repository.list_precedents(), 3)
        action, confidence, source = container.precedents.suggest_action(item, precedents)
        out(f"\n7. FEEDBACK LOOP - moderator resolves {target.content_id}")
        out(f"   Suggested action before any precedent exists: {action} (confidence {confidence}, source: {source})")
        response = container.feedback_service.handle_override(
            FeedbackEvent(event_type="moderator_override", item_id=target.content_id, final_action="remove",
                          notes="Demo decision."), moderator_id="demo-senior")
        after = repository.get_item(target.content_id)
        out(f"   Moderator action: remove -> override of the agents: {response.override_occurred}")
        out(f"   Item now: status={after.status}, rating={after.audience_rating.value}, human_reviewed={after.human_reviewed}")
        out(f"   Precedents stored: {len(repository.list_precedents())}; "
            f"queue length now: {len(container.prioritizer.prioritize_queue(repository.list_items()))}")
        results["feedback"] = {"item": target.content_id, "suggested": action, "source": source,
                               "override": response.override_occurred, "status_after": after.status}
    else:
        out("\n7. FEEDBACK LOOP - skipped, nothing was queued for review")

    if REAL_LLM:
        out(f"\n8. LANGUAGE MODEL USAGE - {LLM_CALLS['count']} calls to {REAL_LLM_MODEL}, "
            f"{LLM_CALLS['seconds']:.0f} s in total, {LLM_CALLS['failures']} failed attempts")
        results["llm_usage"] = {"model": REAL_LLM_MODEL, **LLM_CALLS}

    integration.set_repository(None)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = "live_demo_real_llm" if REAL_LLM else "live_demo"
    (RESULTS_DIR / f"{stem}_results.json").write_text(
        json.dumps(results, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    out(f"\nSaved: {RESULTS_DIR / (stem + '_report.txt')} and {stem}_results.json")
    (RESULTS_DIR / f"{stem}_report.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
