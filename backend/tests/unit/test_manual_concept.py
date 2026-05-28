"""Schema-level tests for ManualConceptResponse (§ 7.1 Call 6) and
ManualRevisePromptsResponse (§ 7.1 Call 7)."""

import pytest
from pydantic import ValidationError

from app.schemas.claude import ManualConceptResponse, ManualRevisePromptsResponse


def test_gathering_allows_null_candidate():
    r = ManualConceptResponse(phase="gathering", reply="Tell me more.")
    assert r.concept_candidate is None


def test_awaiting_confirmation_requires_candidate():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="awaiting_concept_confirmation", reply="OK?")


def test_confirmed_requires_candidate():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="concept_confirmed", reply="Going for it.")


def test_accepted_forbids_candidate():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="accepted", reply="Glad you like it.", concept_candidate="x")


def test_gathering_forbids_candidate():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="gathering", reply="Tell me more.", concept_candidate="x")


def test_awaiting_confirmation_with_candidate_ok():
    r = ManualConceptResponse(
        phase="awaiting_concept_confirmation",
        reply="Shall I go with this?",
        concept_candidate="A girl on a stage, eyes closed.",
    )
    assert r.concept_candidate.startswith("A girl")


def test_empty_reply_rejected():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="gathering", reply="")


def test_unknown_phase_rejected():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="bogus", reply="hi")  # type: ignore[arg-type]


# ── New § 6A.4 phases ────────────────────────────────────────────────────────


def test_gathering_feedback_allows_null_candidate():
    r = ManualConceptResponse(phase="gathering_feedback", reply="What did you like?")
    assert r.concept_candidate is None


def test_gathering_feedback_forbids_candidate():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="gathering_feedback", reply="What now?", concept_candidate="x")


def test_awaiting_feedback_confirmation_allows_null_candidate():
    r = ManualConceptResponse(phase="awaiting_feedback_confirmation", reply="Shall I render again?")
    assert r.concept_candidate is None


def test_feedback_confirmed_allows_null_candidate():
    r = ManualConceptResponse(phase="feedback_confirmed", reply="On it.")
    assert r.concept_candidate is None


def test_feedback_confirmed_forbids_candidate():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="feedback_confirmed", reply="On it.", concept_candidate="x")


def test_restart_concept_allows_null_candidate():
    r = ManualConceptResponse(phase="restart_concept", reply="Sure, let's start over.")
    assert r.concept_candidate is None


def test_restart_concept_forbids_candidate():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="restart_concept", reply="Over.", concept_candidate="x")


def test_accepted_with_empty_reply_ok():
    """`accepted` is the only phase that may carry an empty reply (mirrors
    Agent 0a's `phase=confirmed`)."""
    r = ManualConceptResponse(phase="accepted", reply="")
    assert r.phase == "accepted"


# ── ManualRevisePromptsResponse (Agent 7) ────────────────────────────────────


def test_revise_prompts_minimal_ok():
    r = ManualRevisePromptsResponse(positive="brave girl, stage", negative="blurry")
    assert r.positive.startswith("brave")
    assert r.negative == "blurry"


def test_revise_prompts_empty_positive_rejected():
    with pytest.raises(ValidationError):
        ManualRevisePromptsResponse(positive="   ", negative="blurry")


def test_revise_prompts_empty_negative_rejected():
    with pytest.raises(ValidationError):
        ManualRevisePromptsResponse(positive="brave girl", negative="")


def test_revise_prompts_has_no_workflow_field():
    """Agent 7 cannot toggle workflow — § 6A.4 step 5.5 / § 7.1 Call 7."""
    assert "workflow" not in ManualRevisePromptsResponse.model_fields


# ── prompting_notes_update (§ 6A.2 rule #12, § 7.1 Call 6) ───────────────────


def test_prompting_notes_update_optional():
    """Field defaults to None and is therefore optional on every phase."""
    r = ManualConceptResponse(phase="gathering", reply="Tell me more.")
    assert r.prompting_notes_update is None


def test_prompting_notes_update_accepted_when_provided():
    r = ManualConceptResponse(
        phase="gathering_feedback",
        reply="What now?",
        prompting_notes_update="Robot renders as mist; add mecha, hard edges.",
    )
    assert r.prompting_notes_update.startswith("Robot")


def test_prompting_notes_update_allowed_on_restart_concept():
    """Notes may be updated on restart_concept (renderer blind spots transfer)."""
    r = ManualConceptResponse(
        phase="restart_concept",
        reply="OK, fresh idea.",
        prompting_notes_update="Companion drifts; anchor with on shoulder.",
    )
    assert r.prompting_notes_update.startswith("Companion")


def test_prompting_notes_update_empty_string_rejected():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="gathering", reply="…", prompting_notes_update="")


def test_prompting_notes_update_whitespace_only_rejected():
    with pytest.raises(ValidationError):
        ManualConceptResponse(phase="gathering", reply="…", prompting_notes_update="   \n  ")
