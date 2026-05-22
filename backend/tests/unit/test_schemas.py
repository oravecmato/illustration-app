"""Unit tests for Claude IO Pydantic schemas (§11.1)."""

import pytest
from pydantic import ValidationError

from app.constants import MAX_ILLUSTRATIONS
from app.schemas.claude import (
    AnalyzeStoryResponse,
    EvaluateImageResponse,
    GeneratePromptsResponse,
    RethinkConceptResponse,
    RevisePromptsResponse,
)

# ---- AnalyzeStoryResponse ----

VALID_ANALYZE_STORY = {
    "style_guide": {
        "overall_style_positive": "anime, mha style",
        "overall_style_negative": "photorealistic, dark",
        "character_lora": "",
        "character_baseline_description": "Warm afternoon lighting",
    },
    "illustrations": [
        {
            "scene_index": 0,
            "scene_excerpt": "Once upon a time...",
            "concept": "A boy crying with tears on cheeks",
            "character_role": "male",
        },
        {
            "scene_index": 1,
            "scene_excerpt": "She met a dragon.",
            "concept": "A girl looking determined",
            "character_role": "female",
        },
    ],
}


def test_analyze_story_accepts_valid():
    resp = AnalyzeStoryResponse(**VALID_ANALYZE_STORY)
    assert len(resp.illustrations) == 2
    assert resp.style_guide.character_lora == ""


def test_analyze_story_rejects_missing_style_guide():
    data = {**VALID_ANALYZE_STORY}
    del data["style_guide"]
    with pytest.raises(ValidationError):
        AnalyzeStoryResponse(**data)


def test_analyze_story_rejects_wrong_type():
    data = {**VALID_ANALYZE_STORY, "illustrations": "not a list"}
    with pytest.raises(ValidationError):
        AnalyzeStoryResponse(**data)


def test_analyze_story_truncates_to_max_illustrations():
    many_illustrations = [
        {
            "scene_index": i,
            "scene_excerpt": f"Scene {i}",
            "concept": f"Concept {i}",
            "character_role": "male",
        }
        for i in range(MAX_ILLUSTRATIONS + 3)
    ]
    data = {**VALID_ANALYZE_STORY, "illustrations": many_illustrations}
    resp = AnalyzeStoryResponse(**data)
    assert len(resp.illustrations) == MAX_ILLUSTRATIONS


def test_analyze_story_empty_illustrations_is_valid():
    """Empty illustrations array signals NO_SUITABLE_SCENES — must not be a schema error."""
    data = {**VALID_ANALYZE_STORY, "illustrations": []}
    resp = AnalyzeStoryResponse(**data)
    assert resp.illustrations == []


def test_analyze_story_character_role_valid_values():
    for role in ("male", "female", "mother"):
        data = {
            **VALID_ANALYZE_STORY,
            "illustrations": [
                {
                    "scene_index": 0,
                    "scene_excerpt": "...",
                    "concept": "Some concept",
                    "character_role": role,
                }
            ],
        }
        resp = AnalyzeStoryResponse(**data)
        assert resp.illustrations[0].character_role == role


def test_analyze_story_character_role_invalid_value():
    data = {
        **VALID_ANALYZE_STORY,
        "illustrations": [
            {
                "scene_index": 0,
                "scene_excerpt": "...",
                "concept": "Some concept",
                "character_role": "villain",
            }
        ],
    }
    with pytest.raises(ValidationError):
        AnalyzeStoryResponse(**data)


# ---- GeneratePromptsResponse ----

VALID_GENERATE_PROMPTS = {
    "character_positive": "brave knight, armor",
    "character_negative": "blurry, deformed",
    "environment": "enchanted forest, magical",
}


def test_generate_prompts_accepts_valid():
    resp = GeneratePromptsResponse(**VALID_GENERATE_PROMPTS)
    assert resp.character_positive == "brave knight, armor"


def test_generate_prompts_rejects_missing_field():
    data = {"character_positive": "x", "character_negative": "y"}
    with pytest.raises(ValidationError):
        GeneratePromptsResponse(**data)


def test_generate_prompts_rejects_wrong_type():
    data = {**VALID_GENERATE_PROMPTS, "environment": 123}
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
    assert resp.environment == "enchanted forest, magical"


def test_revise_prompts_rejects_missing():
    with pytest.raises(ValidationError):
        RevisePromptsResponse(character_positive="x")


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
