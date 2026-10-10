"""
Verifies content moderation with the ML toxicity models switched on (USE_ML_MODELS=true).

    backend/.venv/Scripts/python.exe results_ml_models/run_verification.py
    backend/.venv/Scripts/python.exe results_ml_models/run_verification.py --model toxic_bert

The settings come from backend/.env, the same file the server reads. The test set in
test-posts/text (38 posts, 5 comments) is run twice through the real LangGraph workflow,
once with ML on and once with ML forced off, each in its own process because the ML
module decides at import time whether to load torch.

What is real in this run
    - backend/.env, the ML model it names, the workflow and every agent
    - the keyword detector, the policy checks and the routing between agents

What is not
    - the language model: ``recommendation/evaluation/standin_llm.py`` answers the agents'
      prompts from keyword lists, so no provider is called and the run is repeatable.
    - the databases: everything is written to a temporary folder.
    - fast mode: every text, comments included, takes the full pipeline as a post.

Writes results_ml_models.json and results_ml_models.md next to this file.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
TEXT_DIR = PROJECT_ROOT / "test-posts" / "text"

REVIEW_STATUSES = {"pending_human_review", "under_review", "escalated"}
EXPECTED_STATUSES = {
    "approved": {"approved"}, "ideally approved": {"approved"}, "flagged": {"flagged"},
    "removed": {"removed"}, "warned": {"warned"}, "human review": REVIEW_STATUSES,
}


def load_cases() -> List[Dict[str, Any]]:
    cases = []
    for name in ("posts.json", "comments.json"):
        cases += json.loads((TEXT_DIR / name).read_text(encoding="utf-8"))
    return cases


def allowed_statuses(expect: str) -> set:
    allowed = set()
    for part in expect.split(" or "):
        allowed |= EXPECTED_STATUSES[part.strip()]
    return allowed


# ─── worker: one pass over the test set, in its own process ─────────────────────

def initial_state(case: Dict[str, Any]) -> Dict[str, Any]:
    """The same initial state backend/main.py builds for POST /api/content/submit."""
    from src.core.models import ContentMetadata, ContentStatus, UserProfile

    content_id = case["id"]
    now = datetime.now().isoformat()
    profile = UserProfile(
        user_id="verify-author", username="verify_author", account_age_days=400, total_posts=120,
        total_violations=0, previous_warnings=0, previous_suspensions=0, reputation_score=0.8,
        reputation_tier="new_user", verified=False, follower_count=50,
    )
    metadata = ContentMetadata(content_id=content_id, content_type="post", platform="verify", created_at=now, language="en")
    return {
        "content_id": content_id, "submission_id": f"sub-{content_id}", "submission_timestamp": now,
        "content_text": case["text"], "content_type": "post", "content_metadata": metadata,
        "image_urls": [], "video_urls": [], "audio_urls": [],
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


def worker(mode: str, out_path: str) -> int:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
    env_setting = os.environ.get("USE_ML_MODELS")
    if mode == "off":
        os.environ["USE_ML_MODELS"] = "false"
    work_dir = Path(tempfile.mkdtemp(prefix=f"verify_ml_{mode}_"))
    os.environ["CHROMA_DB_PATH"] = str(work_dir / "chroma")
    os.environ["RECOMMENDATION_DB_PATH"] = str(work_dir / "recommendation_data.db")
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    sys.path.insert(0, str(PROJECT_ROOT / "recommendation" / "evaluation"))
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(BACKEND_ROOT))
    os.chdir(work_dir)

    import logging

    import src.agents.agents as agents_module
    from standin_llm import StandInLLM

    agents_module.ChatGoogleGenerativeAI = StandInLLM

    from src.agents.workflow import create_moderation_workflow, process_content
    from src.ml.ml_classifier import get_ml_status, preload_ml_models
    from src.utils.tools import detect_toxicity

    logging.getLogger().setLevel(logging.ERROR)
    for noisy in ("src", "recommendation", "httpx", "chromadb", "transformers"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    started = time.perf_counter()
    preload = preload_ml_models()
    load_seconds = round(time.perf_counter() - started, 1)
    workflow = create_moderation_workflow(None, enable_fast_mode=False)

    rows = []
    for case in load_cases():
        text = case["text"]
        keyword = detect_toxicity(text, use_ml=False)
        tool_started = time.perf_counter()
        tool = detect_toxicity(text)
        tool_ms = round((time.perf_counter() - tool_started) * 1000, 1)
        row = {
            **case,
            "keyword_toxicity": round(float(keyword["toxicity_score"]), 4),
            "tool_toxicity": round(float(tool["toxicity_score"]), 4),
            "tool_method": tool.get("detection_method", "keyword"),
            "tool_models": tool.get("models_used", []),
            "tool_ms": tool_ms,
        }
        pipeline_started = time.perf_counter()
        try:
            final = process_content(workflow, initial_state(case))
        except Exception as failure:  # report, do not hide
            row["error"] = f"{type(failure).__name__}: {failure}"
            rows.append(row)
            continue
        row.update({
            "pipeline_seconds": round(time.perf_counter() - pipeline_started, 2),
            "toxicity_score": final.get("toxicity_score"), "toxicity_level": final.get("toxicity_level"),
            "toxicity_categories": final.get("toxicity_categories"),
            "hate_speech_detected": final.get("hate_speech_detected"),
            "policy_violations": final.get("policy_violations"), "violation_severity": final.get("violation_severity"),
            "status": final.get("status"), "moderation_action": final.get("moderation_action"),
            "hitl_required": final.get("hitl_required"), "hitl_trigger_reasons": final.get("hitl_trigger_reasons"),
            "overall_confidence": final.get("overall_confidence"),
            "agent_verdicts": [f"{d.agent_name}:{getattr(d.decision, 'value', d.decision)}"
                               for d in final.get("agent_decisions", [])],
        })
        rows.append(row)

    result = {
        "mode": mode, "use_ml_models_in_env_file": env_setting,
        "settings": {k: os.environ.get(k) for k in ("USE_ML_MODELS", "ML_PRIMARY_MODEL", "ML_USE_ENSEMBLE",
                                                    "ML_PRELOAD_MODELS", "ML_DEVICE")},
        "preload": preload, "ml_status": get_ml_status(), "model_load_seconds": load_seconds, "cases": rows,
    }
    Path(out_path).write_text(json.dumps(result, indent=1, default=str, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


# ─── report ─────────────────────────────────────────────────────────────────────

def cell(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "-"
    return "-" if value in (None, "") else str(value)


def short(text: str, width: int = 60) -> str:
    text = text.replace("|", "/")
    return text if len(text) <= width else text[: width - 3] + "..."


def outcome(row: Dict[str, Any]) -> str:
    if "error" in row:
        return "ERROR"
    return "ok" if row["status"] in allowed_statuses(row["expect"]) else "MISS"


def build_report(on: Dict[str, Any], off: Dict[str, Any], stem: str = "results_ml_models") -> Dict[str, Any]:
    status = on["ml_status"]
    checks = [
        ("backend/.env has USE_ML_MODELS=true", str(on["use_ml_models_in_env_file"]).lower() == "true"),
        ("torch and transformers import", bool(status["ml_available"])),
        ("model preload succeeds", on["preload"].get("status") == "success"),
        ("model named in .env is the one loaded", status["loaded_models"] == [on["settings"]["ML_PRIMARY_MODEL"]]),
        ("every text was scored by the model, not the keyword fallback",
         all(r["tool_method"].startswith("ml_") for r in on["cases"])),
        ("pipeline finished for every text", not any("error" in r for r in on["cases"])),
        ("with ML off the same code falls back to keywords", all(r["tool_method"] == "keyword" for r in off["cases"])),
    ]
    off_by_id = {r["id"]: r for r in off["cases"]}
    groups: Dict[str, Dict[str, int]] = {}
    changed = []
    for row in on["cases"]:
        before = off_by_id[row["id"]]
        tally = groups.setdefault(row["group"], {"total": 0, "ml_on_ok": 0, "ml_off_ok": 0})
        tally["total"] += 1
        tally["ml_on_ok"] += outcome(row) == "ok"
        tally["ml_off_ok"] += outcome(before) == "ok"
        if row.get("status") != before.get("status"):
            changed.append({"id": row["id"], "group": row["group"], "expect": row["expect"],
                            "ml_off_status": before.get("status"), "ml_on_status": row.get("status"),
                            "ml_off_toxicity": before.get("toxicity_score"), "ml_on_toxicity": row.get("toxicity_score"),
                            "ml_off": outcome(before), "ml_on": outcome(row), "text": row["text"]})
    misses = [r for r in on["cases"] if outcome(r) != "ok"]
    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "language_model": "stand-in (keyword rules), no provider called",
        "checks": [{"check": name, "passed": passed} for name, passed in checks],
        "all_checks_passed": all(passed for _, passed in checks),
        "by_group": groups,
        "matches_expectation": {"ml_on": sum(g["ml_on_ok"] for g in groups.values()),
                                "ml_off": sum(g["ml_off_ok"] for g in groups.values()),
                                "total": len(on["cases"])},
        "decisions_changed_by_ml": changed,
        "ml_on_misses": [{k: r.get(k) for k in ("id", "group", "expect", "status", "toxicity_score",
                                               "policy_violations", "error", "text")} for r in misses],
        "ml_on": on, "ml_off": off,
    }

    total = summary["matches_expectation"]
    lines = [
        "# Content moderation with the ML models on", "",
        f"Run at {summary['run_at']} by `run_verification.py`. Settings are read from `backend/.env`.",
        "The language model is the keyword stand-in from `recommendation/evaluation/standin_llm.py`;",
        "no provider was called. Every text went through the full pipeline as a post.", "",
        "## Engine", "", "| Setting | Value |", "|---|---|",
    ]
    lines += [f"| {key} | {value} |" for key, value in on["settings"].items()]
    lines += [f"| Preload status | {on['preload'].get('status')} |", f"| Device | {status['device']} |",
              f"| Models loaded | {cell(status['loaded_models'])} |",
              f"| Model load time | {on['model_load_seconds']} s |", "",
              "## Checks", "", "| Check | Result |", "|---|---|"]
    lines += [f"| {name} | {'PASS' if passed else 'FAIL'} |" for name, passed in checks]
    lines += ["", "## Decisions against the expectation in the test set", "",
              f"ML on: {total['ml_on']} of {total['total']} match. ML off (keywords only): {total['ml_off']} of {total['total']}.", "",
              "| Group | Texts | Match, ML on | Match, ML off |", "|---|---|---|---|"]
    lines += [f"| {group} | {t['total']} | {t['ml_on_ok']} | {t['ml_off_ok']} |" for group, t in groups.items()]
    lines += ["", "## Decisions that ML changed", ""]
    if changed:
        lines += ["| ID | Group | Expect | ML off | ML on | Tox off | Tox on | Text |", "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {c['id']} | {c['group']} | {c['expect']} | {c['ml_off_status']} ({c['ml_off']}) | "
                  f"{c['ml_on_status']} ({c['ml_on']}) | {cell(c['ml_off_toxicity'])} | {cell(c['ml_on_toxicity'])} | "
                  f"{short(c['text'])} |" for c in changed]
    else:
        lines.append("None.")
    lines += ["", "## Every text, ML on", "",
              "| ID | Group | Expect | Status | Result | Keyword tox | ML tox | Policy keywords | Severity | Human review | Text |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in on["cases"]:
        lines.append(
            f"| {row['id']} | {row['group']} | {row['expect']} | {row.get('status') or row.get('error')} | {outcome(row)} | "
            f"{cell(row['keyword_toxicity'])} | {cell(row['tool_toxicity'])} | {cell(row.get('policy_violations'))} | "
            f"{cell(row.get('violation_severity'))} | {'yes' if row.get('hitl_required') else 'no'} | {short(row['text'])} |")
    timed = [r for r in on["cases"] if "pipeline_seconds" in r]
    if timed:
        lines += ["", "## Timing, ML on", "",
                  f"Model call per text: {sum(r['tool_ms'] for r in on['cases']) / len(on['cases']):.0f} ms on average "
                  f"({status['device']}). Full pipeline per text: {sum(r['pipeline_seconds'] for r in timed) / len(timed):.2f} s "
                  "on average, with the stand-in language model."]
    (HERE / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (HERE / f"{stem}.json").write_text(
        json.dumps(summary, indent=1, default=str, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return summary


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        return worker(sys.argv[2], sys.argv[3])

    # --model NAME checks another model from ContentMLClassifier.MODELS in place of the one in .env
    stem = "results_ml_models"
    if len(sys.argv) == 3 and sys.argv[1] == "--model":
        os.environ["ML_PRIMARY_MODEL"] = sys.argv[2]
        stem = f"results_ml_models_{sys.argv[2]}"

    scratch = Path(tempfile.mkdtemp(prefix="verify_ml_"))
    passes = {}
    for mode in ("on", "off"):
        out_path = scratch / f"{mode}.json"
        print(f"Running the test set with ML {mode}...", flush=True)
        log = (scratch / f"{mode}.log").open("w", encoding="utf-8")
        code = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", mode, str(out_path)],
                              stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}).returncode
        log.close()
        if code != 0 or not out_path.exists():
            print(f"The ML {mode} pass failed (exit {code}). Log: {scratch / (mode + '.log')}")
            return 1
        passes[mode] = json.loads(out_path.read_text(encoding="utf-8"))

    summary = build_report(passes["on"], passes["off"], stem)
    for check in summary["checks"]:
        print(f"  {'PASS' if check['passed'] else 'FAIL'}  {check['check']}")
    total = summary["matches_expectation"]
    print(f"Decisions matching the test set: ML on {total['ml_on']}/{total['total']}, ML off {total['ml_off']}/{total['total']}")
    print(f"Decisions changed by ML: {len(summary['decisions_changed_by_ml'])}")
    print(f"Saved: {HERE / (stem + '.md')} and {stem}.json")
    return 0 if summary["all_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
