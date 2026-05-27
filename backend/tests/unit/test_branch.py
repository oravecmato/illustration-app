"""Unit tests for per-illustration branch state machine (§11.1)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import IllustrationState
from app.schemas.claude import (
    EvaluateImageResponse,
    GeneratePromptsResponse,
    RethinkConceptResponse,
    StyleGuide,
)

STYLE_GUIDE = StyleGuide(
    overall_style_positive="watercolor",
    overall_style_negative="photorealistic",
    character_lora="",
    character_baseline_description="A young girl",
)

PROMPTS = GeneratePromptsResponse(
    workflow="single-lora",
    positive="brave knight, forest",
    negative="blurry",
)

VERDICT_OK = EvaluateImageResponse(
    ok=True,
    problem=None,
    reasoning="Looks great",
    suggestion="",
)

VERDICT_FAIL_PROMPT = EvaluateImageResponse(
    ok=False,
    problem="prompt",
    reasoning="Too blurry",
    suggestion="Make it sharper",
)

VERDICT_FAIL_CONCEPT = EvaluateImageResponse(
    ok=False,
    problem="concept",
    reasoning="Wrong scene",
    suggestion="Change concept",
)

RETHOUGHT_CONCEPT = RethinkConceptResponse(
    workflow="single-lora",
    concept="New concept for the scene",
    concept_localized="New concept for the scene",
    character_role="male",
    paragraph_text="Stál pri okne a hľadel von. Pršalo a on plakal.",
    scene_excerpt="Pršalo a on plakal.",
)

IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


CHARACTER_CONFIG = {
    "male": {
        "display_name": "Izuku Midoriya",
        "lora_filename": "midoriya_v1.safetensors",
        "trigger_tags": "midoriya izuku, green hair",
        "outfit_baseline": "school uniform",
    },
    "female": {
        "display_name": "Kyoka Jiro",
        "lora_filename": "jirou_v1.safetensors",
        "trigger_tags": "jirou kyouka, short hair",
        "outfit_baseline": "school uniform",
    },
    "mother": {
        "display_name": "Inko Midoriya",
        "lora_filename": "inko_v1.safetensors",
        "trigger_tags": "midoriya inko, green hair",
        "outfit_baseline": "casual clothes",
    },
}


def make_illustration(run_id="run-1", scene_index=0, character_role="male"):
    ill = MagicMock()
    ill.id = f"ill-{scene_index}"
    ill.run_id = run_id
    ill.scene_index = scene_index
    ill.scene_excerpt = "Once upon a time..."
    ill.paragraph_index = 0
    ill.character_role = character_role
    ill.initial_concept = "A boy crying in the rain"
    ill.current_concept = "A boy crying in the rain"
    ill.state = IllustrationState.PENDING
    ill.concept_attempt = 1
    ill.prompt_attempt = 1
    ill.image_path = None
    ill.error_message = None
    ill.companion_description = None
    ill.companion_interaction = None
    ill.current_workflow = None
    return ill


def make_services(
    generate_prompts_return=None,
    evaluate_image_return=None,
    revise_prompts_return=None,
    rethink_concept_return=None,
    run_workflow_return=None,
):
    claude = AsyncMock()
    claude.generate_prompts.return_value = generate_prompts_return or PROMPTS
    claude.evaluate_image.return_value = evaluate_image_return or VERDICT_OK
    claude.revise_prompts.return_value = revise_prompts_return or PROMPTS
    claude.rethink_concept.return_value = rethink_concept_return or RETHOUGHT_CONCEPT

    runpod = AsyncMock()
    runpod.run_workflow.return_value = run_workflow_return or IMAGE_BYTES

    return claude, runpod


async def run_branch(illustration, style_guide, claude, runpod, cancel_flag=None):
    """Helper to run a branch and return the final illustration state."""
    from app.orchestrator.branch import run_branch as _run_branch

    repo = AsyncMock()
    repo.update_illustration = AsyncMock(side_effect=lambda ill, **kwargs: _apply(ill, **kwargs))
    event_bus = AsyncMock()

    if cancel_flag is None:
        cancel_flag = asyncio.Event()

    workflow_template = {"node": {"inputs": {"text": "POSITIVE_PROMPT", "lora": "CHARACTER_LORA"}}}

    await _run_branch(
        illustration=illustration,
        style_guide=style_guide,
        workflow_template=workflow_template,
        output_dir="/tmp",
        claude=claude,
        runpod=runpod,
        repo=repo,
        event_bus=event_bus,
        cancel_flag=cancel_flag,
        character_config=CHARACTER_CONFIG,
        story_title="A short story",
        story_blocks=[
            {"type": "paragraph", "text": "Stál pri okne a hľadel von."},
            {"type": "illustration", "scene_index": 0},
        ],
    )
    return illustration


def _apply(ill, **kwargs):
    for k, v in kwargs.items():
        setattr(ill, k, v)
    return ill


@pytest.mark.asyncio
async def test_happy_path_first_attempt_succeeds():
    ill = make_illustration()
    claude, runpod = make_services(evaluate_image_return=VERDICT_OK)
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.COMPLETED
    claude.generate_prompts.assert_called_once()
    runpod.run_workflow.assert_called_once()
    claude.evaluate_image.assert_called_once()


@pytest.mark.asyncio
async def test_prompt_revision_path():
    """First attempt returns prompt-bad, second attempt succeeds."""
    ill = make_illustration()
    claude, runpod = make_services()
    claude.evaluate_image.side_effect = [VERDICT_FAIL_PROMPT, VERDICT_OK]
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.COMPLETED
    assert runpod.run_workflow.call_count == 2
    claude.revise_prompts.assert_called_once()


@pytest.mark.asyncio
async def test_concept_restart_path():
    """All 3 prompt attempts fail with problem=prompt on concept 1 -> concept 2 succeeds."""
    ill = make_illustration()
    claude, runpod = make_services()
    # 3 prompt failures on concept 1, then success on concept 2
    claude.evaluate_image.side_effect = [
        VERDICT_FAIL_PROMPT,
        VERDICT_FAIL_PROMPT,
        VERDICT_FAIL_PROMPT,
        VERDICT_OK,
    ]
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.COMPLETED
    claude.rethink_concept.assert_called_once()
    assert runpod.run_workflow.call_count == 4


@pytest.mark.asyncio
async def test_concept_rejection_immediate():
    """Verdict returns problem=concept on attempt 1 -> immediately move to next concept."""
    ill = make_illustration()
    claude, runpod = make_services()
    claude.evaluate_image.side_effect = [VERDICT_FAIL_CONCEPT, VERDICT_OK]
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.COMPLETED
    # Should not call revise_prompts on concept rejection
    claude.revise_prompts.assert_not_called()
    assert runpod.run_workflow.call_count == 2


@pytest.mark.asyncio
async def test_all_attempts_exhausted_leads_to_failed():
    """All 3 concepts, all 3 prompt attempts each -> FAILED."""
    ill = make_illustration()
    claude, runpod = make_services()
    claude.evaluate_image.return_value = VERDICT_FAIL_PROMPT
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.FAILED
    assert ill.error_message is not None


@pytest.mark.asyncio
async def test_cancellation_stops_branch():
    """Cancel flag set before start -> branch transitions to CANCELLED."""
    ill = make_illustration()
    claude, runpod = make_services()
    cancel_flag = asyncio.Event()
    cancel_flag.set()  # Set before running
    await run_branch(ill, STYLE_GUIDE, claude, runpod, cancel_flag=cancel_flag)
    assert ill.state == IllustrationState.CANCELLED
    # No external calls should be made
    claude.generate_prompts.assert_not_called()
    runpod.run_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_character_lora_from_character_config():
    """Branch uses the correct lora_filename from character_config based on character_role."""
    from app.orchestrator.branch import run_branch as _run_branch

    captured_workflow = []

    async def capture_workflow(workflow):
        captured_workflow.append(workflow)
        return IMAGE_BYTES

    ill = make_illustration(character_role="female")
    claude, runpod = make_services(evaluate_image_return=VERDICT_OK)
    runpod.run_workflow.side_effect = capture_workflow

    repo = AsyncMock()
    repo.update_illustration = AsyncMock(side_effect=lambda i, **kwargs: _apply(i, **kwargs))
    event_bus = AsyncMock()

    workflow_template = {
        "node": {
            "inputs": {
                "lora": "CHARACTER_LORA",
                "positive": "POSITIVE_PROMPT",
                "negative": "NEGATIVE_PROMPT",
                "style_pos": "STYLE_POSITIVE_PROMPT",
                "style_neg": "STYLE_NEGATIVE_PROMPT",
            }
        }
    }

    await _run_branch(
        illustration=ill,
        style_guide=STYLE_GUIDE,
        workflow_template=workflow_template,
        output_dir="/tmp",
        claude=claude,
        runpod=runpod,
        repo=repo,
        event_bus=event_bus,
        cancel_flag=asyncio.Event(),
        character_config=CHARACTER_CONFIG,
        story_title="Test Story",
        source_language="sk",
        story_blocks=[
            {"type": "paragraph", "text": "Test paragraph."},
            {"type": "illustration", "scene_index": 0},
        ],
    )

    assert ill.state == IllustrationState.COMPLETED
    # The lora value in the submitted workflow must be the female lora_filename
    # Check that workflow was captured and contains the expected lora
    assert len(captured_workflow) > 0, "No workflow was captured"
    wf = captured_workflow[0]
    # Navigate the workflow structure - it may vary based on template
    if "node" in wf:
        assert wf["node"]["inputs"]["lora"] == "jirou_v1.safetensors"
    else:
        # If structure is different, just verify lora value exists somewhere
        import json

        wf_str = json.dumps(wf)
        assert "jirou_v1.safetensors" in wf_str, f"Expected lora not found in workflow: {wf}"
