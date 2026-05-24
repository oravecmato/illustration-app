"""Unit tests for Claude IO Pydantic schemas (§11.1)."""

import pytest
from pydantic import ValidationError

from app.constants import MAX_ILLUSTRATIONS
from app.schemas.claude import (
    BuildStoryResponse,
    ChatResponse,
    CollectedBrief,
    EvaluateImageResponse,
    GeneratePromptsResponse,
    RethinkConceptResponse,
    RevisePromptsResponse,
)

# ---- CollectedBrief ----


def _brief(roles: list[str]) -> dict:
    return {
        "characters": [
            {"role": r, "name_in_story": r.title(), "short_description": f"a {r}"} for r in roles
        ],
        "topic": "A short story about something.",
        "notes": "",
    }


def test_collected_brief_accepts_single_male():
    CollectedBrief(**_brief(["male"]))


def test_collected_brief_accepts_male_and_female():
    CollectedBrief(**_brief(["male", "female"]))


def test_collected_brief_accepts_full_cast():
    CollectedBrief(**_brief(["male", "female", "mother"]))


def test_collected_brief_rejects_mother_only():
    with pytest.raises(ValidationError):
        CollectedBrief(**_brief(["mother"]))


def test_collected_brief_rejects_empty_cast():
    with pytest.raises(ValidationError):
        CollectedBrief(**_brief([]))


def test_collected_brief_rejects_duplicate_role():
    with pytest.raises(ValidationError):
        CollectedBrief(**_brief(["male", "male"]))


def test_collected_brief_rejects_too_many():
    with pytest.raises(ValidationError):
        CollectedBrief(
            characters=[
                {"role": "male", "name_in_story": "M", "short_description": "x"},
                {"role": "female", "name_in_story": "F", "short_description": "x"},
                {"role": "mother", "name_in_story": "Mo", "short_description": "x"},
                {"role": "male", "name_in_story": "M2", "short_description": "x"},
            ],
            topic="t",
            notes="",
        )


# ---- ChatResponse ----


def test_chat_response_gathering_with_null_brief():
    resp = ChatResponse(reply="Aha, povedz mi viac.", phase="gathering", collected_brief=None)
    assert resp.phase == "gathering"


def test_chat_response_gathering_rejects_brief():
    with pytest.raises(ValidationError):
        ChatResponse(
            reply="x",
            phase="gathering",
            collected_brief=_brief(["male"]),  # type: ignore[arg-type]
        )


def test_chat_response_awaiting_confirmation_requires_brief():
    with pytest.raises(ValidationError):
        ChatResponse(reply="Súhlasíš?", phase="awaiting_confirmation", collected_brief=None)


def test_chat_response_confirmed_requires_brief():
    with pytest.raises(ValidationError):
        ChatResponse(reply="Ide na to.", phase="confirmed", collected_brief=None)


def test_chat_response_awaiting_confirmation_with_brief():
    resp = ChatResponse(
        reply="Súhlasíš?",
        phase="awaiting_confirmation",
        collected_brief=_brief(["male"]),  # type: ignore[arg-type]
    )
    assert resp.collected_brief is not None


# ---- BuildStoryResponse ----

VALID_STYLE_GUIDE = {
    "overall_style_positive": "anime, mha style",
    "overall_style_negative": "photorealistic",
    "character_lora": "",
    "character_baseline_description": "Warm light.",
}


def _build_story_payload(
    *,
    blocks: list[dict],
    illustrations: list[dict],
) -> dict:
    return {
        "story_title": "Krátky príbeh",
        "story_blocks": blocks,
        "style_guide": VALID_STYLE_GUIDE,
        "illustrations": illustrations,
    }


def test_build_story_accepts_valid_minimal():
    blocks = [
        {"type": "paragraph", "text": "Začiatok. Stojí pri okne a pozerá sa von."},
        {"type": "illustration", "scene_index": 0},
        {"type": "paragraph", "text": "Koniec príbehu."},
    ]
    illustrations = [
        {
            "scene_index": 0,
            "scene_excerpt": "Stojí pri okne a pozerá sa von.",
            "concept": "boy at window, contemplative",
            "character_role": "male",
        }
    ]
    resp = BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))
    assert len(resp.story_blocks) == 3
    assert len(resp.illustrations) == 1


def test_build_story_rejects_starting_with_illustration():
    blocks = [
        {"type": "illustration", "scene_index": 0},
        {"type": "paragraph", "text": "Koniec."},
    ]
    illustrations = [
        {
            "scene_index": 0,
            "scene_excerpt": "Koniec.",
            "concept": "x",
            "character_role": "male",
        }
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_ending_with_illustration():
    blocks = [
        {"type": "paragraph", "text": "Začiatok textu."},
        {"type": "illustration", "scene_index": 0},
    ]
    illustrations = [
        {
            "scene_index": 0,
            "scene_excerpt": "Začiatok textu.",
            "concept": "x",
            "character_role": "male",
        }
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_adjacent_illustrations():
    blocks = [
        {"type": "paragraph", "text": "P1 obsah."},
        {"type": "illustration", "scene_index": 0},
        {"type": "illustration", "scene_index": 1},
        {"type": "paragraph", "text": "P2 obsah."},
    ]
    illustrations = [
        {
            "scene_index": 0,
            "scene_excerpt": "P1 obsah.",
            "concept": "x",
            "character_role": "male",
        },
        {
            "scene_index": 1,
            "scene_excerpt": "P2 obsah.",
            "concept": "y",
            "character_role": "female",
        },
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_out_of_order_block_indices():
    blocks = [
        {"type": "paragraph", "text": "P1 obsah."},
        {"type": "illustration", "scene_index": 1},
        {"type": "paragraph", "text": "P2 obsah."},
    ]
    illustrations = [
        {
            "scene_index": 1,
            "scene_excerpt": "P1 obsah.",
            "concept": "x",
            "character_role": "male",
        }
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_excerpt_not_in_paragraph():
    blocks = [
        {"type": "paragraph", "text": "P1 obsah."},
        {"type": "illustration", "scene_index": 0},
        {"type": "paragraph", "text": "P2 obsah."},
    ]
    illustrations = [
        {
            "scene_index": 0,
            "scene_excerpt": "Tento text v žiadnom odseku nie je.",
            "concept": "x",
            "character_role": "male",
        }
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_more_than_max_illustrations():
    # Build (MAX + 2) illustration blocks. The illustrations array gets
    # truncated to MAX by the field validator, which then mismatches the
    # block list and raises. This verifies the cap is enforced end-to-end.
    n = MAX_ILLUSTRATIONS + 2
    blocks: list[dict] = []
    for i in range(n):
        blocks.append({"type": "paragraph", "text": f"Para {i}."})
        blocks.append({"type": "illustration", "scene_index": i})
    blocks.append({"type": "paragraph", "text": "End."})
    illustrations = [
        {
            "scene_index": i,
            "scene_excerpt": f"Para {i}.",
            "concept": f"c{i}",
            "character_role": "male",
        }
        for i in range(n)
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


# ---- GeneratePromptsResponse ----

VALID_GENERATE_PROMPTS = {
    "positive": "brave knight, armor, enchanted forest, magical",
    "negative": "blurry, deformed",
}


def test_generate_prompts_accepts_valid():
    resp = GeneratePromptsResponse(**VALID_GENERATE_PROMPTS)
    assert resp.positive == "brave knight, armor, enchanted forest, magical"


def test_generate_prompts_rejects_missing_field():
    data = {"positive": "x"}
    with pytest.raises(ValidationError):
        GeneratePromptsResponse(**data)


def test_generate_prompts_rejects_wrong_type():
    data = {**VALID_GENERATE_PROMPTS, "negative": 123}
    with pytest.raises(ValidationError):
        GeneratePromptsResponse(**data)


# ---- EvaluateImageResponse ----

VALID_EVALUATE_OK = {
    "ok": True,
    "problem": None,
    "reasoning": "The image looks great.",
    "suggestion": "",
}

VALID_EVALUATE_FAIL_PROMPT = {
    "ok": False,
    "problem": "prompt",
    "reasoning": "The image is blurry.",
    "suggestion": "Use sharper prompt.",
}

VALID_EVALUATE_FAIL_CONCEPT = {
    "ok": False,
    "problem": "concept",
    "reasoning": "The concept is wrong.",
    "suggestion": "Change the scene concept.",
}


def test_evaluate_image_accepts_ok():
    resp = EvaluateImageResponse(**VALID_EVALUATE_OK)
    assert resp.ok is True
    assert resp.problem is None


def test_evaluate_image_accepts_fail_prompt():
    resp = EvaluateImageResponse(**VALID_EVALUATE_FAIL_PROMPT)
    assert resp.ok is False
    assert resp.problem == "prompt"


def test_evaluate_image_accepts_fail_concept():
    resp = EvaluateImageResponse(**VALID_EVALUATE_FAIL_CONCEPT)
    assert resp.problem == "concept"


def test_evaluate_image_rejects_invalid_problem():
    data = {**VALID_EVALUATE_FAIL_PROMPT, "problem": "unknown_problem"}
    with pytest.raises(ValidationError):
        EvaluateImageResponse(**data)


def test_evaluate_image_rejects_missing_reasoning():
    data = {"ok": True, "problem": None, "suggestion": ""}
    with pytest.raises(ValidationError):
        EvaluateImageResponse(**data)


# ---- RevisePromptsResponse ----


def test_revise_prompts_accepts_valid():
    resp = RevisePromptsResponse(**VALID_GENERATE_PROMPTS)
    assert resp.negative == "blurry, deformed"


def test_revise_prompts_rejects_missing():
    with pytest.raises(ValidationError):
        RevisePromptsResponse(positive="x")


# ---- RethinkConceptResponse ----


def test_rethink_concept_accepts_valid():
    resp = RethinkConceptResponse(concept="A completely new approach to the scene")
    assert "new approach" in resp.concept


def test_rethink_concept_rejects_missing_concept():
    with pytest.raises(ValidationError):
        RethinkConceptResponse()


def test_rethink_concept_rejects_wrong_type():
    with pytest.raises(ValidationError):
        RethinkConceptResponse(concept=123)
