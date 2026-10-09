"""
A rule-based stand-in for the language model, for running the real moderation pipeline
without calling an LLM provider.

It is NOT a model. It answers each of the pipeline's prompts from small keyword lists, in
the shape that prompt expects, so that everything around the LLM can be exercised: the
LangGraph workflow, the ML toxicity models, the policy checks, the audience rating, the
safety gate, the feed and the moderator queue. Topic extraction, the toxicity "second
opinion" and the written explanations are where a real model (Gemini today, Claude once it
is wired in) would do much better; results that depend on them are only as good as these
keyword lists.

Used only by ``run_live_demo.py``. Nothing in the application imports it.
"""

import json
import re
from typing import Any, Dict, List

# keyword -> (category, topic). Categories and topics are from the recommender's lists.
TOPIC_KEYWORDS: Dict[str, tuple] = {
    "volcano": ("science", "science"), "planet": ("science", "science"), "experiment": ("science", "science"),
    "space": ("science", "science"), "puppy": ("animals", "animals"), "kitten": ("animals", "animals"),
    "zoo": ("animals", "animals"), "football": ("sports", "sports"), "cricket": ("sports", "sports"),
    "match": ("sports", "sports"), "puzzle": ("puzzles", "puzzles"), "drawing": ("crafts", "crafts"),
    "python": ("coding", "coding"), "javascript": ("coding", "coding"), "bug": ("coding", "coding"),
    "phone": ("technology", "technology"), "laptop": ("technology", "technology"),
    "movie": ("movies", "movies"), "novel": ("books", "books"), "workout": ("fitness", "fitness"),
    "anxiety": ("mental_health", "mental_health"), "stressed": ("mental_health", "mental_health"),
    "election": ("politics", "politics"), "stock": ("finance", "finance"), "invest": ("finance", "finance"),
    "nightclub": ("nightlife", "nightlife"), "court": ("news", "news"),
}
SENSITIVE_KEYWORDS = {"election": "politics", "vote": "politics", "stock": "finance", "invest": "finance",
                      "anxiety": "health", "diagnos": "health"}
HOSTILE_WORDS = ("idiot", "stupid", "hate you", "loser", "shut up", "worthless")
SPAM_PHRASES = ("click here", "buy now", "free money", "limited offer", "act now", "guaranteed")
MISINFORMATION_PHRASES = ("secret truth", "guaranteed cure", "mainstream media lies", "doctors don't want you to know")


class StandInResponse:
    """Mimics the ``.content`` attribute of a LangChain chat response."""

    def __init__(self, content: str):
        self.content = content


def extract_content(prompt: str) -> str:
    """The submitted text, which every pipeline prompt quotes after ``Content:``."""
    match = re.search(r'Content:\s*"(.*?)"\s*(?:\n|$)', prompt, flags=re.DOTALL)
    if match:
        return match.group(1)
    match = re.search(r'"(.*?)"', prompt, flags=re.DOTALL)
    return match.group(1) if match else ""


def assess(text: str) -> Dict[str, Any]:
    """Keyword assessment of the submitted text."""
    lower = text.lower()
    hostile = [word for word in HOSTILE_WORDS if word in lower]
    spam = [phrase for phrase in SPAM_PHRASES if phrase in lower]
    misinformation = [phrase for phrase in MISINFORMATION_PHRASES if phrase in lower]
    if len(hostile) >= 2:
        verdict, toxicity = "remove", 0.85
    elif hostile:
        verdict, toxicity = "flag", 0.55
    elif len(spam) >= 2 or misinformation:
        verdict, toxicity = "warn", 0.15
    else:
        verdict, toxicity = "approve", 0.02
    return {"verdict": verdict, "toxicity": toxicity, "hostile": hostile, "spam": spam, "misinformation": misinformation}


def topic_extraction(text: str) -> Dict[str, Any]:
    lower = text.lower()
    found = [value for keyword, value in TOPIC_KEYWORDS.items() if keyword in lower]
    topics: List[str] = list(dict.fromkeys(topic for _, topic in found))
    return {
        "topics": topics,
        "category": found[0][0] if found else "general",
        "entities": [],
        "sensitive_topics": sorted({label for keyword, label in SENSITIVE_KEYWORDS.items() if keyword in lower}),
        "explicit_content": False,
        "language": "en",
    }


class StandInLLM:
    """Drop-in for the chat model the agents construct. Accepts and ignores its arguments."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls = 0

    def invoke(self, prompt: Any) -> StandInResponse:
        self.calls += 1
        prompt = str(prompt)
        text = extract_content(prompt)
        result = assess(text)
        verdict = result["verdict"]

        if "Main topics (up to 5)" in prompt:
            return StandInResponse(json.dumps(topic_extraction(text)))

        if "Is this content toxic or harmful?" in prompt:
            level = "high" if result["toxicity"] >= 0.6 else "medium" if result["toxicity"] >= 0.4 else "none"
            return StandInResponse(json.dumps({
                "decision": "approve" if verdict == "warn" else verdict,
                "confidence": 0.9 if verdict in ("approve", "remove") else 0.65,
                "toxicity_score": result["toxicity"],
                "toxicity_level": level,
                "categories": [{"category": "insult", "score": result["toxicity"], "evidence": result["hostile"]}]
                if result["hostile"] else [],
                "is_satire": False,
                "is_quote": False,
                "is_educational": False,
                "context_notes": "",
                "reasoning": "Stand-in assessment from keyword lists; no language model was called.",
            }))

        if '"toxicity_score": <float>' in prompt:
            violations = (["harassment"] if result["hostile"] else []) + (["spam"] if len(result["spam"]) >= 2 else [])
            return StandInResponse(json.dumps({
                "toxicity_score": result["toxicity"], "policy_violations": violations, "decision": verdict,
                "reason": "Stand-in fast-mode assessment from keyword lists.", "confidence": 0.8,
            }))

        if "Community Guidelines:" in prompt:
            action = {"approve": "APPROVE", "warn": "WARN", "flag": "WARN", "remove": "REMOVE"}[verdict]
            return StandInResponse(f"Stand-in policy assessment. Recommended action: {action}.")

        if "Should this proceed to toxicity detection" in prompt:
            label = "FLAG" if verdict in ("flag", "remove") else "APPROVE"
            return StandInResponse(f"Stand-in initial assessment: {label}.")

        # Reputation, synthesis and user-notification prompts: free text the pipeline
        # stores but only scans for explicit sanction keywords, which are avoided here.
        return StandInResponse("Stand-in summary: decision follows the agents' recorded signals.")
