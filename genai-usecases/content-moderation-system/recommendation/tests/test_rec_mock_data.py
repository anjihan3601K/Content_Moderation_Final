"""Mock data: reproducible, harmless, and handled correctly by the rating and the gate."""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mock_data"))

import generate_mock_data as generator  # noqa: E402
from gate_harness import (  # noqa: E402
    MOCK_DATA_DIR,
    item_from_record,
    leak_reason,
    load_dataset,
    profile_from_record,
    run_case,
)
from recommendation.src.models import GateReason  # noqa: E402
from recommendation.src.safety_gate import SafetyGate  # noqa: E402

DATASETS = generator.generate()
ITEM_RECORDS = DATASETS["items"]
PROFILE_RECORDS = DATASETS["profiles"]
CASES = DATASETS["rejection_cases"]
ITEMS = [item_from_record(record) for record in ITEM_RECORDS]

PLACEHOLDER_TEXT = re.compile(r"^Placeholder item item-\d{4} (about|labelled) [a-z_ ]+\.$")


def passed_ids(profile_record):
    profile = profile_from_record(profile_record)
    return {item.item_id for item in ITEMS if SafetyGate.evaluate_item(profile, item).passed}


# ─── the data itself ────────────────────────────────────────────────────────────

def test_generation_is_reproducible():
    assert generator.generate() == DATASETS
    assert generator.generate(seed=1) != DATASETS


@pytest.mark.parametrize("name", list(DATASETS))
def test_files_on_disk_match_the_generator(name):
    on_disk = json.loads((MOCK_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(DATASETS[name]))
    assert load_dataset(name) == on_disk


def test_dataset_sizes_match_the_specification():
    assert 500 <= len(ITEM_RECORDS) <= 1000
    assert 60 <= len(PROFILE_RECORDS) <= 100
    assert 150 <= len(DATASETS["resolved_cases"]) <= 300
    assert len(DATASETS["engagement"]) > 1000
    assert {p["age_tier"] for p in PROFILE_RECORDS} == {"child", "teen", "adult"}
    assert {p["age_trust_level"] for p in PROFILE_RECORDS} == {"self_declared", "parent_linked", "verified"}
    assert any(c["override_occurred"] for c in DATASETS["resolved_cases"])
    assert any(not c["override_occurred"] for c in DATASETS["resolved_cases"])


def test_adversarial_scenarios_are_present():
    item_scenarios = {record["scenario"] for record in ITEM_RECORDS}
    assert {"high_disagreement", "legacy_unrated", "removed", "escalation_pending", "malformed"} <= item_scenarios
    profile_scenarios = {record["scenario"] for record in PROFILE_RECORDS}
    assert {"risky_engagement", "disallowed_interest_request", "parental_block", "strict_controls"} <= profile_scenarios


def test_item_text_is_placeholder_only():
    for record in ITEM_RECORDS:
        assert PLACEHOLDER_TEXT.match(record["pipeline_state"]["content_text"]), record["item_id"]
    for case in DATASETS["resolved_cases"]:
        assert re.match(r"^Placeholder note for case \d{3}\.$", case["moderator_notes"])


# ─── catalogue of named cases ───────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES, ids=[case["case_id"] for case in CASES])
def test_catalogue_case(case):
    outcome = run_case(case)
    assert outcome["actual_rating"] == case["expected_rating"]
    assert outcome["actual_served"] is case["expected_served"]
    assert outcome["actual_reason"] == case["expected_reason"]


def test_catalogue_exercises_every_gate_reason():
    covered = {case["expected_reason"] for case in CASES if case["expected_reason"]}
    assert covered == {reason.value for reason in GateReason}


def test_catalogue_has_rejections_and_controls():
    assert sum(1 for case in CASES if not case["expected_served"]) >= 40
    assert sum(1 for case in CASES if case["expected_served"]) >= 5


# ─── bulk items ─────────────────────────────────────────────────────────────────

def test_every_item_gets_the_rating_its_scenario_expects():
    for record, item in zip(ITEM_RECORDS, ITEMS):
        actual = item.audience_rating.value if item.audience_rating else None
        assert actual == record["expected_rating"], (record["item_id"], record["scenario"])


def test_no_leak_across_every_profile_and_item():
    served = minor_served = 0
    for profile_record in PROFILE_RECORDS:
        profile = profile_from_record(profile_record)
        for record, item in zip(ITEM_RECORDS, ITEMS):
            if SafetyGate.evaluate_item(profile, item).passed:
                problem = leak_reason(profile_record, record)
                assert problem is None, (problem, profile_record["profile_id"], record["item_id"])
                served += 1
                minor_served += profile_record["age_tier"] != "adult"
    assert served > 10000 and minor_served > 5000  # not vacuous


@pytest.mark.parametrize(
    "scenario",
    ["removed", "escalation_pending", "pending_review"],
)
def test_scenarios_that_reach_nobody(scenario):
    targets = {record["item_id"] for record in ITEM_RECORDS if record["scenario"] == scenario}
    for profile_record in PROFILE_RECORDS:
        assert not targets & passed_ids(profile_record)


@pytest.mark.parametrize(
    "scenario",
    ["adult_general", "adult_violation", "high_disagreement", "escalation_approved", "legacy_unrated", "malformed"],
)
def test_scenarios_that_never_reach_a_minor(scenario):
    targets = {record["item_id"] for record in ITEM_RECORDS if record["scenario"] == scenario}
    for profile_record in PROFILE_RECORDS:
        if profile_record["age_tier"] != "adult":
            assert not targets & passed_ids(profile_record)


def test_clean_content_does_reach_its_audience():
    by_scenario = {}
    for record in ITEM_RECORDS:
        by_scenario.setdefault(record["scenario"], set()).add(record["item_id"])
    plain = {"age_trust_level": "verified", "parental_controls": {}}
    assert by_scenario["clean_child"] <= passed_ids({**plain, "age_tier": "child"})
    assert by_scenario["clean_teen"] <= passed_ids({**plain, "age_tier": "teen"})
    assert not by_scenario["clean_teen"] & passed_ids({**plain, "age_tier": "child"})
    assert by_scenario["adult_general"] <= passed_ids({**plain, "age_tier": "adult"})


@pytest.mark.parametrize("tier", ["child", "teen", "adult"])
def test_lower_trust_never_sees_more(tier):
    def seen(trust):
        return passed_ids({"age_tier": tier, "age_trust_level": trust, "parental_controls": {}})

    assert seen("self_declared") <= seen("parent_linked") <= seen("verified")


def test_parental_controls_never_widen_except_the_sensitive_allowance():
    for profile_record in PROFILE_RECORDS:
        controls = dict(profile_record["parental_controls"])
        if not controls:
            continue
        controls.pop("allowed_sensitive_topics", None)
        with_controls = passed_ids({**profile_record, "parental_controls": controls})
        without = passed_ids({**profile_record, "parental_controls": {}})
        assert with_controls <= without, profile_record["profile_id"]


def test_risky_engagement_and_requested_interests_do_not_change_what_a_child_sees():
    risky = [p for p in PROFILE_RECORDS if p["scenario"] in ("risky_engagement", "disallowed_interest_request")]
    assert risky
    for profile_record in risky:
        hostile = {
            **profile_record,
            "explicit_interests": profile_record["requested_explicit_interests"] + ["violent_extremism"],
            "learned_interests": {"violent_extremism": 1.0, "nightlife": 1.0},
        }
        neutral = {**profile_record, "explicit_interests": [], "learned_interests": {}}
        assert passed_ids(hostile) == passed_ids(neutral)
