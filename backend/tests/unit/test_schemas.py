"""Unit tests for Claude IO Pydantic schemas (§11.1)."""

import pytest
from pydantic import ValidationError

from app.constants import MAX_ILLUSTRATIONS
from app.schemas.claude import (
    BuildStoryResponse,
    ChatResponse,
    CollectedBrief,
    Companion,
    EvaluateImageResponse,
    GeneratePromptsResponse,
    RethinkConceptResponse,
    RevisePromptsResponse,
    companion_in_pool,
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


def _valid_blocks_and_illustrations(
    count: int = MAX_ILLUSTRATIONS,
) -> tuple[list[dict], list[dict]]:
    """Build a well-formed (blocks, illustrations) pair with `count` scenes.

    Layout: P I P I P I P I P I P — paragraphs and illustrations alternate
    with paragraph bookends. Each scene_excerpt is verbatim in its
    preceding paragraph.
    """
    blocks: list[dict] = [{"type": "paragraph", "text": "Začiatok príbehu."}]
    illustrations: list[dict] = []
    for i in range(count):
        para_text = f"Odsek {i}. Stojí pri okne {i} a pozerá sa von."
        excerpt = f"Stojí pri okne {i} a pozerá sa von."
        blocks.append({"type": "paragraph", "text": para_text}) if i > 0 else None
        blocks.append({"type": "illustration", "scene_index": i})
        illustrations.append(
            {
                "scene_index": i,
                "scene_excerpt": excerpt,
                "concept": f"character at window {i}, contemplative",
                "character_role": "male",
            }
        )
        # ensure first illustration's excerpt is in opening paragraph
        if i == 0:
            blocks[0] = {"type": "paragraph", "text": "Začiatok. " + excerpt}
    blocks.append({"type": "paragraph", "text": "Koniec príbehu."})
    return blocks, illustrations


def test_build_story_accepts_valid_full_count():
    blocks, illustrations = _valid_blocks_and_illustrations()
    resp = BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))
    assert len(resp.illustrations) == MAX_ILLUSTRATIONS


def test_build_story_rejects_fewer_than_max():
    # Any count below MAX_ILLUSTRATIONS must be rejected.
    blocks, illustrations = _valid_blocks_and_illustrations(count=MAX_ILLUSTRATIONS - 1)
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_single_illustration():
    blocks, illustrations = _valid_blocks_and_illustrations(count=1)
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_more_than_max_illustrations():
    blocks, illustrations = _valid_blocks_and_illustrations(count=MAX_ILLUSTRATIONS + 1)
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_starting_with_illustration():
    blocks, illustrations = _valid_blocks_and_illustrations()
    blocks = blocks[1:]  # drop opening paragraph
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_ending_with_illustration():
    blocks, illustrations = _valid_blocks_and_illustrations()
    blocks = blocks[:-1]  # drop closing paragraph
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_adjacent_illustrations():
    blocks, illustrations = _valid_blocks_and_illustrations()
    # Find the first paragraph-between-two-illustrations and remove it.
    for i, b in enumerate(blocks):
        if (
            b["type"] == "paragraph"
            and i > 0
            and i < len(blocks) - 1
            and blocks[i - 1]["type"] == "illustration"
            and blocks[i + 1]["type"] == "illustration"
        ):
            del blocks[i]
            break
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_out_of_order_block_indices():
    blocks, illustrations = _valid_blocks_and_illustrations()
    # Swap scene_index of the first two illustration blocks → no longer 0,1,...
    illus_block_positions = [i for i, b in enumerate(blocks) if b["type"] == "illustration"]
    a, b = illus_block_positions[0], illus_block_positions[1]
    blocks[a]["scene_index"], blocks[b]["scene_index"] = (
        blocks[b]["scene_index"],
        blocks[a]["scene_index"],
    )
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_excerpt_not_in_paragraph():
    blocks, illustrations = _valid_blocks_and_illustrations()
    illustrations[0]["scene_excerpt"] = "Tento text v žiadnom odseku určite nie je."
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
    resp = RethinkConceptResponse(
        concept="A completely new approach to the scene",
        paragraph_text="Stál pri okne a hľadel von. Pršalo a on plakal.",
        scene_excerpt="Pršalo a on plakal.",
    )
    assert "new approach" in resp.concept
    assert resp.scene_excerpt in resp.paragraph_text


def test_rethink_concept_rejects_missing_concept():
    with pytest.raises(ValidationError):
        RethinkConceptResponse()


def test_rethink_concept_rejects_wrong_type():
    with pytest.raises(ValidationError):
        RethinkConceptResponse(
            concept=123,
            paragraph_text="x",
            scene_excerpt="x",
        )


def test_rethink_concept_rejects_excerpt_not_in_paragraph():
    with pytest.raises(ValidationError):
        RethinkConceptResponse(
            concept="A new concept",
            paragraph_text="Pršalo a on plakal.",
            scene_excerpt="Slniečko svietilo.",
        )


# ---- Companion + CollectedBrief.companions ----


def _brief_with_companions(companion_descriptions: list[str]) -> dict:
    payload = _brief(["male"])
    payload["companions"] = [{"description": d} for d in companion_descriptions]
    return payload


def test_collected_brief_accepts_empty_companions():
    brief = CollectedBrief(**_brief(["male"]))
    assert brief.companions == []


def test_collected_brief_accepts_one_companion():
    brief = CollectedBrief(**_brief_with_companions(["a small black cat"]))
    assert len(brief.companions) == 1
    assert brief.companions[0].description == "a small black cat"


def test_collected_brief_accepts_two_companions():
    brief = CollectedBrief(**_brief_with_companions(["a small black cat", "a brass clockwork owl"]))
    assert len(brief.companions) == 2


def test_collected_brief_rejects_three_companions():
    with pytest.raises(ValidationError):
        CollectedBrief(**_brief_with_companions(["a", "b", "c"]))


def test_collected_brief_rejects_empty_companion_description():
    with pytest.raises(ValidationError):
        CollectedBrief(**_brief_with_companions(["   "]))


def test_companion_requires_non_empty_fields():
    with pytest.raises(ValidationError):
        Companion(description="", interaction="curled on her lap")
    with pytest.raises(ValidationError):
        Companion(description="a small black cat", interaction="")


def test_companion_accepts_valid():
    c = Companion(description="a small black cat", interaction="curled on her lap")
    assert c.description == "a small black cat"


def test_build_story_accepts_illustration_with_companion():
    blocks, illustrations = _valid_blocks_and_illustrations()
    illustrations[0]["companion"] = {
        "description": "a small black cat",
        "interaction": "curled on her lap",
    }
    resp = BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))
    assert resp.illustrations[0].companion is not None
    assert resp.illustrations[0].companion.description == "a small black cat"


def test_build_story_accepts_all_illustrations_without_companion():
    blocks, illustrations = _valid_blocks_and_illustrations()
    resp = BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))
    assert all(i.companion is None for i in resp.illustrations)


def test_rethink_concept_accepts_companion_null():
    resp = RethinkConceptResponse(
        concept="A new concept",
        paragraph_text="Pršalo a on plakal.",
        scene_excerpt="Pršalo a on plakal.",
        companion=None,
    )
    assert resp.companion is None


def test_rethink_concept_accepts_companion_populated():
    resp = RethinkConceptResponse(
        concept="A new concept",
        paragraph_text="Sedela pri okne. Mačka sa jej krčila na kolenách.",
        scene_excerpt="Sedela pri okne.",
        companion={
            "description": "a small black cat",
            "interaction": "curled on her lap",
        },
    )
    assert resp.companion is not None
    assert resp.companion.description == "a small black cat"


def test_rethink_concept_rejects_companion_with_empty_field():
    with pytest.raises(ValidationError):
        RethinkConceptResponse(
            concept="A new concept",
            paragraph_text="Pršalo.",
            scene_excerpt="Pršalo.",
            companion={"description": "a cat", "interaction": ""},
        )


# ---- companion_in_pool ----


def test_companion_in_pool_exact_match():
    assert companion_in_pool("a small black cat", ["a small black cat"])


def test_companion_in_pool_case_insensitive():
    assert companion_in_pool("A Small Black Cat", ["a small black cat"])


def test_companion_in_pool_whitespace_tolerant():
    assert companion_in_pool("a  small   black cat", ["a small black cat"])


def test_companion_in_pool_substring_in_either_direction():
    # description is substring of pool entry
    assert companion_in_pool("small black cat", ["a small black cat"])
    # pool entry is substring of description
    assert companion_in_pool("a small black cat sitting", ["small black cat"])


def test_companion_in_pool_rejects_unrelated():
    assert not companion_in_pool("a red dragon", ["a small black cat"])


def test_companion_in_pool_rejects_empty_description():
    assert not companion_in_pool("", ["a small black cat"])


def test_companion_in_pool_rejects_empty_pool():
    assert not companion_in_pool("a small black cat", [])
