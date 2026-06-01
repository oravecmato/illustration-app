"""Unit tests for Claude IO Pydantic schemas (§11.1)."""

import pytest
from pydantic import ValidationError

from app.constants import MAX_ILLUSTRATIONS
from app.schemas.claude import (
    BuildStoryResponse,
    ChatResponse,
    CollectedBrief,
    Environment,
    EvaluateImageResponse,
    GeneratePromptsResponse,
    NarrativeEntity,
    NonHumanEntityHint,
    RethinkConceptResponse,
    RethinkEnvironmentResponse,
    RevisePromptsResponse,
    validate_illustration_distribution,
)

# ---- CollectedBrief ----


def _brief(roles: list[str]) -> dict:
    # Pick main_character_role deterministically from the cast: prefer male,
    # then female, then mother (mother-only is invalid anyway and exercised
    # by tests below). Tests that need a specific main can override the key
    # on the returned dict.
    if "male" in roles:
        main = "male"
    elif "female" in roles:
        main = "female"
    else:
        main = "mother"
    return {
        "characters": [
            {"role": r, "name_in_story": r.title(), "short_description": f"a {r}"} for r in roles
        ],
        "topic": "A short story about something.",
        "notes": "",
        "main_character_role": main,
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
            main_character_role="male",
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


def _default_environments(count: int = MAX_ILLUSTRATIONS) -> list[dict]:
    """5 distinct single-form indoor labels — satisfies disjointness rule."""
    labels = ["obývačka", "kuchyňa", "spálňa", "kúpeľňa", "predsieň"]
    return [
        {"label": labels[i % len(labels)], "kind": "indoor", "aspect": "single"}
        for i in range(count)
    ]


def _build_story_payload(
    *,
    blocks: list[dict],
    illustrations: list[dict],
    environments: list[dict] | None = None,
    narrative_entities: list[dict] | None = None,
) -> dict:
    # When the test only fixes ``illustrations`` count != MAX_ILLUSTRATIONS,
    # the environments must still be MAX_ILLUSTRATIONS for the outer
    # validator's structural check (we want the illustrations cardinality
    # rule — not the environments rule — to be the visible failure).
    envs = environments if environments is not None else _default_environments()
    return {
        "story_title": "Krátky príbeh",
        "story_topic_description": "Krátky príbeh o dobrodružstve",
        "story_blocks": blocks,
        "style_guide": VALID_STYLE_GUIDE,
        "illustrations": illustrations,
        "environments": envs,
        "narrative_entities": narrative_entities if narrative_entities is not None else [],
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
    "workflow": "single-lora",
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


VALID_REVISION_SUMMARY = {
    "kept": ["brave knight", "armor"],
    "removed": [],
    "added": ["enchanted forest", "magical"],
    "reweighted": [],
    "restructured": False,
    "restructure_reason": None,
}

VALID_REVISE_PROMPTS = {
    **VALID_GENERATE_PROMPTS,
    "revision_summary": VALID_REVISION_SUMMARY,
}


def test_revise_prompts_accepts_valid():
    resp = RevisePromptsResponse(**VALID_REVISE_PROMPTS)
    assert resp.negative == "blurry, deformed"
    assert resp.revision_summary.added == ["enchanted forest", "magical"]
    assert resp.revision_summary.restructured is False


def test_revise_prompts_rejects_missing():
    with pytest.raises(ValidationError):
        RevisePromptsResponse(positive="x")


def test_revise_prompts_rejects_missing_revision_summary():
    """revision_summary is required — it's the field that anchors the CoT plan."""
    data = {k: v for k, v in VALID_REVISE_PROMPTS.items() if k != "revision_summary"}
    with pytest.raises(ValidationError):
        RevisePromptsResponse(**data)


def test_revision_summary_restructured_requires_reason():
    data = {
        **VALID_REVISE_PROMPTS,
        "revision_summary": {**VALID_REVISION_SUMMARY, "restructured": True},
    }
    with pytest.raises(ValidationError, match="restructure_reason"):
        RevisePromptsResponse(**data)


def test_revision_summary_restructured_with_reason_accepts():
    data = {
        **VALID_REVISE_PROMPTS,
        "revision_summary": {
            **VALID_REVISION_SUMMARY,
            "restructured": True,
            "restructure_reason": "Head cluster reordered to put solo at position 3.",
        },
    }
    resp = RevisePromptsResponse(**data)
    assert resp.revision_summary.restructured is True


def test_revision_summary_reweighted_round_trips():
    data = {
        **VALID_REVISE_PROMPTS,
        "revision_summary": {
            **VALID_REVISION_SUMMARY,
            "reweighted": [
                {"tag": "looking down", "from_weight": 1.0, "to_weight": 1.2},
                {"tag": "serene", "from_weight": 1.4, "to_weight": 1.0},
            ],
        },
    }
    resp = RevisePromptsResponse(**data)
    assert len(resp.revision_summary.reweighted) == 2
    assert resp.revision_summary.reweighted[0].to_weight == 1.2


# ---- RethinkConceptResponse ----


def test_rethink_concept_accepts_valid():
    resp = RethinkConceptResponse(
        workflow="single-lora",
        concept="A completely new approach to the scene",
        concept_localized="A completely new approach to the scene",
        character_role="male",
        paragraph_text="Stál pri okne a hľadel von. Pršalo a on plakal.",
        scene_excerpt="Pršalo a on plakal.",
        narrative_continuity_check="Flows naturally between prior and next paragraphs.",
    )
    assert "new approach" in resp.concept
    assert resp.scene_excerpt in resp.paragraph_text
    # Default entity_action is "none" with null label.
    assert resp.entity_action == "none"
    assert resp.contains_entity_label is None


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
            workflow="single-lora",
            concept="A new concept",
            concept_localized="A new concept",
            character_role="male",
            paragraph_text="Pršalo a on plakal.",
            scene_excerpt="Slniečko svietilo.",
            narrative_continuity_check="ok",
        )


# ---- NonHumanEntityHint + CollectedBrief.non_human_entities ----


def _brief_with_hints(labels: list[str]) -> dict:
    payload = _brief(["male"])
    payload["non_human_entities"] = [{"label": label, "role_in_story": "ally"} for label in labels]
    return payload


def test_collected_brief_accepts_empty_non_human_entities():
    brief = CollectedBrief(**_brief(["male"]))
    assert brief.non_human_entities == []


def test_collected_brief_accepts_one_hint():
    brief = CollectedBrief(**_brief_with_hints(["a small black cat"]))
    assert len(brief.non_human_entities) == 1
    assert brief.non_human_entities[0].label == "a small black cat"


def test_collected_brief_accepts_two_hints():
    brief = CollectedBrief(**_brief_with_hints(["a small black cat", "a brass clockwork owl"]))
    assert len(brief.non_human_entities) == 2


def test_collected_brief_rejects_duplicate_hint_labels():
    with pytest.raises(ValidationError):
        CollectedBrief(**_brief_with_hints(["a small black cat", "A SMALL BLACK CAT"]))


def test_collected_brief_rejects_empty_hint_label():
    with pytest.raises(ValidationError):
        CollectedBrief(**_brief_with_hints(["   "]))


def test_non_human_entity_hint_requires_non_empty_fields():
    with pytest.raises(ValidationError):
        NonHumanEntityHint(label="", role_in_story="ally")
    with pytest.raises(ValidationError):
        NonHumanEntityHint(label="a cat", role_in_story="   ")


def test_non_human_entity_hint_accepts_valid():
    h = NonHumanEntityHint(label="a small black cat", role_in_story="ally")
    assert h.label == "a small black cat"


# ---- IllustrationConcept.contains_entity_label ----


def test_build_story_accepts_illustration_with_entity():
    blocks, illustrations = _valid_blocks_and_illustrations()
    illustrations[0]["contains_entity_label"] = "a small black cat"
    entities = [
        {
            "label": "a small black cat",
            "kind": "non_human_character",
            "importance": "primary",
            "reserved_for_scene_index": 0,
        }
    ]
    resp = BuildStoryResponse(
        **_build_story_payload(
            blocks=blocks, illustrations=illustrations, narrative_entities=entities
        )
    )
    assert resp.illustrations[0].contains_entity_label == "a small black cat"


def test_build_story_rejects_entity_label_not_in_register():
    blocks, illustrations = _valid_blocks_and_illustrations()
    illustrations[0]["contains_entity_label"] = "a ghost dog"
    with pytest.raises(ValidationError):
        BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))


def test_build_story_rejects_entity_placed_outside_reserved_slot():
    blocks, illustrations = _valid_blocks_and_illustrations()
    illustrations[0]["contains_entity_label"] = "a small black cat"
    entities = [
        {
            "label": "a small black cat",
            "kind": "non_human_character",
            "importance": "primary",
            "reserved_for_scene_index": 2,  # reserved for slot 2, placed in slot 0
        }
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(
                blocks=blocks, illustrations=illustrations, narrative_entities=entities
            )
        )


def test_build_story_accepts_all_illustrations_without_entity():
    blocks, illustrations = _valid_blocks_and_illustrations()
    resp = BuildStoryResponse(**_build_story_payload(blocks=blocks, illustrations=illustrations))
    assert all(i.contains_entity_label is None for i in resp.illustrations)


# ---- RethinkConceptResponse entity_action / contains_entity_label coherence ----


def test_rethink_concept_accepts_entity_action_none_with_null_label():
    resp = RethinkConceptResponse(
        workflow="single-lora",
        concept="A new concept",
        concept_localized="A new concept",
        character_role="male",
        paragraph_text="Pršalo a on plakal.",
        scene_excerpt="Pršalo a on plakal.",
        entity_action="none",
        contains_entity_label=None,
        narrative_continuity_check="ok",
    )
    assert resp.contains_entity_label is None


def test_rethink_concept_accepts_entity_action_keep_with_label():
    resp = RethinkConceptResponse(
        workflow="single-lora",
        concept="A new concept",
        concept_localized="A new concept",
        character_role="female",
        paragraph_text="Sedela pri okne. Mačka sa jej krčila na kolenách.",
        scene_excerpt="Sedela pri okne.",
        entity_action="keep",
        contains_entity_label="a small black cat",
        narrative_continuity_check="ok",
    )
    assert resp.contains_entity_label == "a small black cat"


def test_rethink_concept_accepts_entity_action_claim_floating_with_label():
    resp = RethinkConceptResponse(
        workflow="single-lora",
        concept="A new concept",
        concept_localized="A new concept",
        character_role="female",
        paragraph_text="Sedela pri okne. Mačka sa jej krčila na kolenách.",
        scene_excerpt="Sedela pri okne.",
        entity_action="claim_floating",
        contains_entity_label="a small black cat",
        narrative_continuity_check="ok",
    )
    assert resp.entity_action == "claim_floating"


def test_rethink_concept_rejects_keep_with_null_label():
    with pytest.raises(ValidationError):
        RethinkConceptResponse(
            workflow="single-lora",
            concept="A new concept",
            concept_localized="A new concept",
            character_role="male",
            paragraph_text="Pršalo.",
            scene_excerpt="Pršalo.",
            entity_action="keep",
            contains_entity_label=None,
            narrative_continuity_check="ok",
        )


def test_rethink_concept_rejects_drop_with_non_null_label():
    with pytest.raises(ValidationError):
        RethinkConceptResponse(
            workflow="single-lora",
            concept="A new concept",
            concept_localized="A new concept",
            character_role="male",
            paragraph_text="Pršalo.",
            scene_excerpt="Pršalo.",
            entity_action="drop",
            contains_entity_label="a small black cat",
            narrative_continuity_check="ok",
        )


def test_rethink_concept_rejects_none_with_non_null_label():
    with pytest.raises(ValidationError):
        RethinkConceptResponse(
            workflow="single-lora",
            concept="A new concept",
            concept_localized="A new concept",
            character_role="male",
            paragraph_text="Pršalo.",
            scene_excerpt="Pršalo.",
            entity_action="none",
            contains_entity_label="a small black cat",
            narrative_continuity_check="ok",
        )


# ---- main_character_role ----


def test_collected_brief_requires_main_character_role():
    payload = _brief(["male", "female"])
    del payload["main_character_role"]
    with pytest.raises(ValidationError):
        CollectedBrief(**payload)


def test_collected_brief_rejects_main_not_in_cast():
    payload = _brief(["male"])
    payload["main_character_role"] = "female"
    with pytest.raises(ValidationError):
        CollectedBrief(**payload)


def test_collected_brief_rejects_main_mother_with_companions():
    # 'mother' cannot be main when she's not the only human (cast rules
    # require male/female alongside her, which then forbids mother-as-main).
    payload = _brief(["male", "mother"])
    payload["main_character_role"] = "mother"
    with pytest.raises(ValidationError):
        CollectedBrief(**payload)


# ---- Environment ----


def test_environment_accepts_indoor_single():
    env = Environment(label="obývačka", kind="indoor", aspect="single")
    assert env.label == "obývačka"


def test_environment_accepts_outdoor_single():
    Environment(label="záhrada", kind="outdoor", aspect="single")


def test_environment_accepts_dual_inside():
    Environment(label="auto", kind="dual", aspect="inside")


def test_environment_accepts_dual_outside():
    Environment(label="auto", kind="dual", aspect="outside")


def test_environment_rejects_indoor_with_inside_aspect():
    with pytest.raises(ValidationError):
        Environment(label="obývačka", kind="indoor", aspect="inside")


def test_environment_rejects_outdoor_with_outside_aspect():
    with pytest.raises(ValidationError):
        Environment(label="záhrada", kind="outdoor", aspect="outside")


def test_environment_rejects_dual_with_single_aspect():
    with pytest.raises(ValidationError):
        Environment(label="auto", kind="dual", aspect="single")


def test_environment_rejects_empty_label():
    with pytest.raises(ValidationError):
        Environment(label="   ", kind="indoor", aspect="single")


def test_environment_rejects_invalid_kind():
    with pytest.raises(ValidationError):
        Environment(label="x", kind="undersea", aspect="single")


# ---- NarrativeEntity ----


def test_narrative_entity_accepts_non_human_primary_with_index():
    e = NarrativeEntity(
        label="malá čierna mačka",
        kind="non_human_character",
        importance="primary",
        reserved_for_scene_index=2,
    )
    assert e.reserved_for_scene_index == 2


def test_narrative_entity_accepts_supporting_object_unassigned():
    e = NarrativeEntity(
        label="stará fotografia",
        kind="object",
        importance="supporting",
        reserved_for_scene_index=None,
    )
    assert e.reserved_for_scene_index is None


def test_narrative_entity_rejects_object_with_primary_importance():
    # Primary/secondary are reserved for non_human_character.
    with pytest.raises(ValidationError):
        NarrativeEntity(
            label="stará fotografia",
            kind="object",
            importance="primary",
            reserved_for_scene_index=1,
        )


def test_narrative_entity_rejects_primary_unassigned():
    # Primary/secondary must be slot-reserved.
    with pytest.raises(ValidationError):
        NarrativeEntity(
            label="čierna mačka",
            kind="non_human_character",
            importance="primary",
            reserved_for_scene_index=None,
        )


def test_narrative_entity_rejects_secondary_unassigned():
    with pytest.raises(ValidationError):
        NarrativeEntity(
            label="hnedá sova",
            kind="non_human_character",
            importance="secondary",
            reserved_for_scene_index=None,
        )


def test_narrative_entity_rejects_empty_label():
    with pytest.raises(ValidationError):
        NarrativeEntity(
            label="",
            kind="object",
            importance="supporting",
        )


def test_narrative_entity_rejects_out_of_range_index():
    with pytest.raises(ValidationError):
        NarrativeEntity(
            label="x",
            kind="object",
            importance="supporting",
            reserved_for_scene_index=MAX_ILLUSTRATIONS,
        )


def test_narrative_entity_rejects_negative_index():
    with pytest.raises(ValidationError):
        NarrativeEntity(
            label="x",
            kind="object",
            importance="supporting",
            reserved_for_scene_index=-1,
        )


def test_narrative_entity_rejects_invalid_kind():
    with pytest.raises(ValidationError):
        NarrativeEntity(label="x", kind="weapon", importance="supporting")


def test_narrative_entity_rejects_invalid_importance():
    with pytest.raises(ValidationError):
        NarrativeEntity(
            label="x",
            kind="object",
            importance="critical",
            reserved_for_scene_index=0,
        )


# ---- BuildStoryResponse environments ----


def test_build_story_rejects_wrong_environments_count():
    blocks, illustrations = _valid_blocks_and_illustrations()
    envs = _default_environments(count=MAX_ILLUSTRATIONS - 1)
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(blocks=blocks, illustrations=illustrations, environments=envs)
        )


def test_build_story_rejects_duplicate_indoor_environment_labels():
    blocks, illustrations = _valid_blocks_and_illustrations()
    envs = _default_environments()
    # Force two slots to share the same indoor label.
    envs[1]["label"] = envs[0]["label"]
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(blocks=blocks, illustrations=illustrations, environments=envs)
        )


def test_build_story_rejects_duplicate_outdoor_environment_labels():
    blocks, illustrations = _valid_blocks_and_illustrations()
    envs = _default_environments()
    envs[0] = {"label": "záhrada", "kind": "outdoor", "aspect": "single"}
    envs[1] = {"label": "záhrada", "kind": "outdoor", "aspect": "single"}
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(blocks=blocks, illustrations=illustrations, environments=envs)
        )


def test_build_story_accepts_dual_environment_inside_outside():
    """Dual environments may occupy two slots — one inside, one outside."""
    blocks, illustrations = _valid_blocks_and_illustrations()
    envs = _default_environments()
    envs[0] = {"label": "auto", "kind": "dual", "aspect": "inside"}
    envs[1] = {"label": "auto", "kind": "dual", "aspect": "outside"}
    resp = BuildStoryResponse(
        **_build_story_payload(blocks=blocks, illustrations=illustrations, environments=envs)
    )
    assert resp.environments[0].label == "auto"
    assert resp.environments[1].label == "auto"


def test_build_story_rejects_dual_environment_with_same_aspect_twice():
    blocks, illustrations = _valid_blocks_and_illustrations()
    envs = _default_environments()
    envs[0] = {"label": "auto", "kind": "dual", "aspect": "inside"}
    envs[1] = {"label": "auto", "kind": "dual", "aspect": "inside"}
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(blocks=blocks, illustrations=illustrations, environments=envs)
        )


def test_build_story_rejects_dual_environment_in_three_slots():
    blocks, illustrations = _valid_blocks_and_illustrations()
    envs = _default_environments()
    envs[0] = {"label": "auto", "kind": "dual", "aspect": "inside"}
    envs[1] = {"label": "auto", "kind": "dual", "aspect": "outside"}
    envs[2] = {"label": "auto", "kind": "dual", "aspect": "inside"}
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(blocks=blocks, illustrations=illustrations, environments=envs)
        )


def test_build_story_rejects_same_label_with_inconsistent_kind():
    blocks, illustrations = _valid_blocks_and_illustrations()
    envs = _default_environments()
    envs[0] = {"label": "park", "kind": "outdoor", "aspect": "single"}
    envs[1] = {"label": "park", "kind": "dual", "aspect": "inside"}
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(blocks=blocks, illustrations=illustrations, environments=envs)
        )


def test_build_story_environment_label_uniqueness_is_case_insensitive():
    blocks, illustrations = _valid_blocks_and_illustrations()
    envs = _default_environments()
    envs[0]["label"] = "Obývačka"
    envs[1]["label"] = "obývačka"
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(blocks=blocks, illustrations=illustrations, environments=envs)
        )


# ---- BuildStoryResponse narrative_entities ----


def test_build_story_accepts_narrative_entities_register():
    blocks, illustrations = _valid_blocks_and_illustrations()
    entities = [
        {
            "label": "stará kniha",
            "kind": "object",
            "importance": "supporting",
            "reserved_for_scene_index": 2,
        },
        {
            "label": "čierna mačka",
            "kind": "non_human_character",
            "importance": "supporting",
            "reserved_for_scene_index": None,
        },
    ]
    resp = BuildStoryResponse(
        **_build_story_payload(
            blocks=blocks, illustrations=illustrations, narrative_entities=entities
        )
    )
    assert len(resp.narrative_entities) == 2


def test_build_story_rejects_two_primary_non_human_characters():
    blocks, illustrations = _valid_blocks_and_illustrations()
    entities = [
        {
            "label": "mačka",
            "kind": "non_human_character",
            "importance": "primary",
            "reserved_for_scene_index": 1,
        },
        {
            "label": "sova",
            "kind": "non_human_character",
            "importance": "primary",
            "reserved_for_scene_index": 2,
        },
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(
                blocks=blocks, illustrations=illustrations, narrative_entities=entities
            )
        )


def test_build_story_rejects_two_secondary_non_human_characters():
    blocks, illustrations = _valid_blocks_and_illustrations()
    entities = [
        {
            "label": "mačka",
            "kind": "non_human_character",
            "importance": "secondary",
            "reserved_for_scene_index": 1,
        },
        {
            "label": "sova",
            "kind": "non_human_character",
            "importance": "secondary",
            "reserved_for_scene_index": 2,
        },
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(
                blocks=blocks, illustrations=illustrations, narrative_entities=entities
            )
        )


def test_build_story_rejects_duplicate_entity_labels():
    blocks, illustrations = _valid_blocks_and_illustrations()
    entities = [
        {
            "label": "Stará Kniha",
            "kind": "object",
            "importance": "supporting",
            "reserved_for_scene_index": 0,
        },
        {
            "label": "stará kniha",
            "kind": "object",
            "importance": "supporting",
            "reserved_for_scene_index": 1,
        },
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(
                blocks=blocks, illustrations=illustrations, narrative_entities=entities
            )
        )


def test_build_story_rejects_entity_label_colliding_with_environment_label():
    blocks, illustrations = _valid_blocks_and_illustrations()
    envs = _default_environments()
    entities = [
        {
            # Same label as envs[0].
            "label": envs[0]["label"],
            "kind": "object",
            "importance": "supporting",
            "reserved_for_scene_index": 0,
        },
    ]
    with pytest.raises(ValidationError):
        BuildStoryResponse(
            **_build_story_payload(
                blocks=blocks,
                illustrations=illustrations,
                environments=envs,
                narrative_entities=entities,
            )
        )


# ---- validate_illustration_distribution ----


def _ill_concept(scene_index: int, role: str | None, entity_label: str | None = None) -> dict:
    return {
        "scene_index": scene_index,
        "scene_excerpt": f"excerpt {scene_index}",
        "concept": f"concept {scene_index}",
        "character_role": role,
        "contains_entity_label": entity_label,
    }


def _build_distribution_inputs(
    roles: list[str | None],
    cast: list[str],
    main: str,
    entity_labels: list[str | None] | None = None,
):
    """Construct (brief, illustrations) for distribution-validator tests."""
    from app.schemas.claude import IllustrationConcept

    brief_payload = _brief(cast)
    brief_payload["main_character_role"] = main
    brief = CollectedBrief(**brief_payload)
    labels = entity_labels if entity_labels is not None else [None] * len(roles)
    illustrations = [
        IllustrationConcept(**_ill_concept(i, r, lab))
        for i, (r, lab) in enumerate(zip(roles, labels, strict=True))
    ]
    return brief, illustrations


def test_distribution_accepts_balanced_run():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
    )
    validate_illustration_distribution(brief, illustrations, narrative_entities=[])


def test_distribution_accepts_one_no_human_slot():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", None],
        cast=["male", "female"],
        main="male",
    )
    validate_illustration_distribution(brief, illustrations, narrative_entities=[])


def test_distribution_rejects_cast_role_never_appearing():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "male", "male", "male", "male"],
        cast=["male", "female"],
        main="male",
    )
    with pytest.raises(ValueError, match="cast role 'female'"):
        validate_illustration_distribution(brief, illustrations, narrative_entities=[])


def test_distribution_rejects_main_appearing_only_once():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "female", "female", "female"],
        cast=["male", "female"],
        main="male",
    )
    with pytest.raises(ValueError, match="main_character_role='male'"):
        validate_illustration_distribution(brief, illustrations, narrative_entities=[])


def test_distribution_rejects_side_exceeding_main():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "male", "female", "female", "female"],
        cast=["male", "female"],
        main="male",
    )
    with pytest.raises(ValueError, match="side role 'female'"):
        validate_illustration_distribution(brief, illustrations, narrative_entities=[])


def test_distribution_rejects_two_no_human_slots():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", None, None],
        cast=["male", "female"],
        main="male",
    )
    with pytest.raises(ValueError, match="character_role=null"):
        validate_illustration_distribution(brief, illustrations, narrative_entities=[])


def test_distribution_rejects_entity_label_not_in_register():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
        entity_labels=["a ghost dog", None, None, None, None],
    )
    with pytest.raises(ValueError, match="not in the narrative_entities register"):
        validate_illustration_distribution(brief, illustrations, narrative_entities=[])


def test_distribution_accepts_primary_nh_with_main():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
        entity_labels=[None, None, "čierna mačka", None, None],
    )
    entities = [
        NarrativeEntity(
            label="čierna mačka",
            kind="non_human_character",
            importance="primary",
            reserved_for_scene_index=2,  # male slot
        )
    ]
    validate_illustration_distribution(brief, illustrations, entities)


def test_distribution_accepts_primary_nh_alone():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", None],
        cast=["male", "female"],
        main="male",
        entity_labels=[None, None, None, None, "čierna mačka"],
    )
    entities = [
        NarrativeEntity(
            label="čierna mačka",
            kind="non_human_character",
            importance="primary",
            reserved_for_scene_index=4,  # no-human slot
        )
    ]
    validate_illustration_distribution(brief, illustrations, entities)


def test_distribution_accepts_primary_nh_with_side_role():
    # Under the unified register, primary NH may sit with ANY cast role.
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
        entity_labels=[None, "čierna mačka", None, None, None],
    )
    entities = [
        NarrativeEntity(
            label="čierna mačka",
            kind="non_human_character",
            importance="primary",
            reserved_for_scene_index=1,  # female (side) slot
        )
    ]
    validate_illustration_distribution(brief, illustrations, entities)


def test_distribution_rejects_secondary_nh_alone():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", None],
        cast=["male", "female"],
        main="male",
        entity_labels=[None, None, None, None, "hnedá sova"],
    )
    entities = [
        NarrativeEntity(
            label="hnedá sova",
            kind="non_human_character",
            importance="secondary",
            reserved_for_scene_index=4,  # no-human slot — secondary may NOT appear alone
        )
    ]
    with pytest.raises(ValueError, match="secondary non_human_character"):
        validate_illustration_distribution(brief, illustrations, entities)


def test_distribution_accepts_secondary_nh_with_main():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
        entity_labels=[None, None, "hnedá sova", None, None],
    )
    entities = [
        NarrativeEntity(
            label="hnedá sova",
            kind="non_human_character",
            importance="secondary",
            reserved_for_scene_index=2,  # male (main) slot
        )
    ]
    validate_illustration_distribution(brief, illustrations, entities)


def test_distribution_accepts_secondary_nh_with_side():
    # Unified register allows secondary NH with any cast role (just not alone).
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
        entity_labels=[None, "hnedá sova", None, None, None],
    )
    entities = [
        NarrativeEntity(
            label="hnedá sova",
            kind="non_human_character",
            importance="secondary",
            reserved_for_scene_index=1,
        )
    ]
    validate_illustration_distribution(brief, illustrations, entities)


def test_distribution_rejects_entity_outside_reserved_slot():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
        entity_labels=[None, "kniha", None, None, None],  # placed at slot 1
    )
    entities = [
        NarrativeEntity(
            label="kniha",
            kind="object",
            importance="supporting",
            reserved_for_scene_index=3,  # reserved for slot 3, not 1
        )
    ]
    with pytest.raises(ValueError, match="scene-locked"):
        validate_illustration_distribution(brief, illustrations, entities)


def test_distribution_accepts_supporting_entity_at_reserved_slot():
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
        entity_labels=[None, None, None, "kniha", None],
    )
    entities = [
        NarrativeEntity(
            label="kniha",
            kind="object",
            importance="supporting",
            reserved_for_scene_index=3,
        )
    ]
    validate_illustration_distribution(brief, illustrations, entities)


def test_distribution_accepts_floating_supporting_entity_at_any_slot():
    # Floating supporting (reserved_for_scene_index=None) may appear at any slot.
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
        entity_labels=[None, "kniha", None, None, None],
    )
    entities = [
        NarrativeEntity(
            label="kniha",
            kind="object",
            importance="supporting",
            reserved_for_scene_index=None,  # floating
        )
    ]
    validate_illustration_distribution(brief, illustrations, entities)


def test_distribution_accepts_unused_entity():
    # An entity that no illustration claims is allowed (graceful drop).
    brief, illustrations = _build_distribution_inputs(
        roles=["male", "female", "male", "female", "male"],
        cast=["male", "female"],
        main="male",
    )
    entities = [
        NarrativeEntity(
            label="čierna mačka",
            kind="non_human_character",
            importance="primary",
            reserved_for_scene_index=2,
        )
    ]
    validate_illustration_distribution(brief, illustrations, entities)


# ---- EvaluateImageResponse environment problem ----


def test_evaluate_image_accepts_environment_problem():
    resp = EvaluateImageResponse(
        ok=False,
        problem="environment",
        reasoning="The locked environment is unrenderable.",
        suggestion="Swap to a more concrete locale.",
    )
    assert resp.problem == "environment"


# ---- RethinkEnvironmentResponse ----


def test_rethink_environment_accepts_valid():
    resp = RethinkEnvironmentResponse(
        workflow="single-lora",
        concept="character at a kitchen window",
        concept_localized="postava pri kuchynskom okne",
        character_role="female",
        paragraph_text="Stála pri kuchynskom okne a pozerala von.",
        scene_excerpt="Stála pri kuchynskom okne a pozerala von.",
        environment={"label": "kuchyňa", "kind": "indoor", "aspect": "single"},
        narrative_continuity_check="Flows naturally from prev to next.",
    )
    assert resp.environment.label == "kuchyňa"
    assert resp.contains_entity_label is None
    assert resp.entity_action == "none"


def test_rethink_environment_accepts_dual_environment():
    resp = RethinkEnvironmentResponse(
        workflow="no-lora",
        concept="empty cabin from the outside",
        concept_localized="prázdna chata zvonku",
        character_role=None,
        paragraph_text="Chata stála medzi smrekmi a ticho dymila.",
        scene_excerpt="Chata stála medzi smrekmi a ticho dymila.",
        environment={"label": "drevenica", "kind": "dual", "aspect": "outside"},
        narrative_continuity_check="ok",
    )
    assert resp.environment.aspect == "outside"


def test_rethink_environment_rejects_excerpt_not_in_paragraph():
    with pytest.raises(ValidationError):
        RethinkEnvironmentResponse(
            workflow="single-lora",
            concept="x",
            concept_localized="x",
            character_role="male",
            paragraph_text="Stál pri okne.",
            scene_excerpt="Sedel pri stole.",
            environment={"label": "obývačka", "kind": "indoor", "aspect": "single"},
            narrative_continuity_check="ok",
        )


def test_rethink_environment_rejects_empty_continuity_check():
    with pytest.raises(ValidationError):
        RethinkEnvironmentResponse(
            workflow="single-lora",
            concept="x",
            concept_localized="x",
            character_role="male",
            paragraph_text="Stál pri okne.",
            scene_excerpt="Stál pri okne.",
            environment={"label": "obývačka", "kind": "indoor", "aspect": "single"},
            narrative_continuity_check="   ",
        )


def test_rethink_environment_rejects_invalid_environment_aspect():
    with pytest.raises(ValidationError):
        RethinkEnvironmentResponse(
            workflow="single-lora",
            concept="x",
            concept_localized="x",
            character_role="male",
            paragraph_text="Stál pri okne.",
            scene_excerpt="Stál pri okne.",
            # indoor + aspect=inside is invalid (must be 'single')
            environment={"label": "obývačka", "kind": "indoor", "aspect": "inside"},
            narrative_continuity_check="ok",
        )


def test_rethink_environment_rejects_keep_with_null_label():
    with pytest.raises(ValidationError):
        RethinkEnvironmentResponse(
            workflow="single-lora",
            concept="x",
            concept_localized="x",
            character_role="male",
            paragraph_text="Stál pri okne.",
            scene_excerpt="Stál pri okne.",
            environment={"label": "obývačka", "kind": "indoor", "aspect": "single"},
            entity_action="keep",
            contains_entity_label=None,
            narrative_continuity_check="ok",
        )
