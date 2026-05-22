"""Unit tests for top-level orchestrator pipeline (§11.1)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants import MAX_ILLUSTRATIONS
from app.db.models import IllustrationState, RunStatus
from app.schemas.claude import (
    AnalyzeStoryResponse,
    IllustrationConcept,
    StyleGuide,
)


def make_analyze_story_response(n: int) -> AnalyzeStoryResponse:
    return AnalyzeStoryResponse(
        style_guide=StyleGuide(
            overall_style_positive="anime style",
            overall_style_negative="photorealistic",
            character_lora="",
            character_baseline_description="Warm lighting",
        ),
        illustrations=[
            IllustrationConcept(
                scene_index=i,
                scene_excerpt=f"Scene {i} excerpt",
                concept=f"Concept for scene {i}",
                character_role="male",
            )
            for i in range(n)
        ],
    )


def make_run(run_id="run-1", story="Once upon a time..."):
    run = MagicMock()
    run.id = run_id
    run.story_text = story
    run.status = RunStatus.RUNNING
    run.style_guide_json = None
    run.illustration_count = 0
    run.completed_count = 0
    run.failed_count = 0
    run.error_code = None
    run.error_message = None
    return run


def make_illustration(run_id, scene_index):
    ill = MagicMock()
    ill.id = f"ill-{scene_index}"
    ill.run_id = run_id
    ill.scene_index = scene_index
    ill.character_role = "male"
    ill.state = IllustrationState.PENDING
    ill.concept_attempt = 1
    ill.prompt_attempt = 1
    ill.image_path = None
    ill.error_message = None
    return ill


@pytest.mark.asyncio
async def test_step0_produces_3_illustrations():
    """Step 0 produces N=3 illustrations -> 3 branches spawned."""
    from app.orchestrator.pipeline import run_pipeline

    run = make_run()
    analyze_response = make_analyze_story_response(3)

    repo = AsyncMock()
    illustrations = [make_illustration(run.id, i) for i in range(3)]
    repo.create_illustration = AsyncMock(side_effect=illustrations)
    repo.update_run = AsyncMock(side_effect=lambda r, **kwargs: _apply(r, **kwargs))
    repo.get_run = AsyncMock(return_value=run)

    claude = AsyncMock()
    claude.analyze_story.return_value = analyze_response
    claude.generate_prompts.return_value = MagicMock(
        character_positive="x", character_negative="y", environment="z"
    )
    claude.evaluate_image.return_value = MagicMock(
        ok=True, problem=None, reasoning="", suggestion=""
    )

    runpod = AsyncMock()
    runpod.run_workflow.return_value = b"\x89PNG\r\n" + b"\x00" * 100

    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    event_bus.snapshot_getter = MagicMock(return_value=AsyncMock())

    workflow_template = {}
    cancel_flag = asyncio.Event()

    with patch("app.orchestrator.pipeline.run_branch", new_callable=AsyncMock) as mock_branch:
        # Simulate branches completing successfully
        async def fake_branch(illustration, **kwargs):
            illustration.state = IllustrationState.COMPLETED

        mock_branch.side_effect = fake_branch

        await run_pipeline(
            run=run,
            repo=repo,
            claude=claude,
            runpod=runpod,
            event_bus=event_bus,
            workflow_template=workflow_template,
            output_dir="/tmp",
            cancel_flag=cancel_flag,
        )

    assert mock_branch.call_count == 3


@pytest.mark.asyncio
async def test_step0_produces_8_truncated_to_5():
    """Step 0 produces N=8 -> truncated to MAX_ILLUSTRATIONS (5)."""
    from app.orchestrator.pipeline import run_pipeline

    run = make_run()
    analyze_response = make_analyze_story_response(8)

    repo = AsyncMock()
    illustrations = [make_illustration(run.id, i) for i in range(8)]
    repo.create_illustration = AsyncMock(side_effect=illustrations)
    repo.update_run = AsyncMock(side_effect=lambda r, **kwargs: _apply(r, **kwargs))
    repo.get_run = AsyncMock(return_value=run)

    claude = AsyncMock()
    claude.analyze_story.return_value = analyze_response

    runpod = AsyncMock()
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()

    cancel_flag = asyncio.Event()

    with patch("app.orchestrator.pipeline.run_branch", new_callable=AsyncMock) as mock_branch:

        async def fake_branch(illustration, **kwargs):
            illustration.state = IllustrationState.COMPLETED

        mock_branch.side_effect = fake_branch

        await run_pipeline(
            run=run,
            repo=repo,
            claude=claude,
            runpod=runpod,
            event_bus=event_bus,
            workflow_template={},
            output_dir="/tmp",
            cancel_flag=cancel_flag,
        )

    # Truncated to MAX_ILLUSTRATIONS
    assert mock_branch.call_count == MAX_ILLUSTRATIONS


@pytest.mark.asyncio
async def test_all_branches_succeed_run_completed():
    """All branches succeed -> run COMPLETED with completed_count = N."""
    from app.orchestrator.pipeline import run_pipeline

    run = make_run()
    n = 3
    analyze_response = make_analyze_story_response(n)

    illustrations = [make_illustration(run.id, i) for i in range(n)]
    repo = AsyncMock()
    repo.create_illustration = AsyncMock(side_effect=illustrations)
    repo.update_run = AsyncMock(side_effect=lambda r, **kwargs: _apply(r, **kwargs))
    repo.get_run = AsyncMock(return_value=run)

    claude = AsyncMock()
    claude.analyze_story.return_value = analyze_response

    cancel_flag = asyncio.Event()

    with patch("app.orchestrator.pipeline.run_branch", new_callable=AsyncMock) as mock_branch:

        async def fake_branch(illustration, **kwargs):
            illustration.state = IllustrationState.COMPLETED

        mock_branch.side_effect = fake_branch

        await run_pipeline(
            run=run,
            repo=repo,
            claude=claude,
            runpod=AsyncMock(),
            event_bus=AsyncMock(),
            workflow_template={},
            output_dir="/tmp",
            cancel_flag=cancel_flag,
        )

    assert run.status == RunStatus.COMPLETED
    assert run.completed_count == n


@pytest.mark.asyncio
async def test_mixed_outcome_run_still_completed():
    """3 ok, 2 failed -> run COMPLETED (run is not FAILED just because some branches failed)."""
    from app.orchestrator.pipeline import run_pipeline

    run = make_run()
    n = 5
    analyze_response = make_analyze_story_response(n)

    illustrations = [make_illustration(run.id, i) for i in range(n)]
    repo = AsyncMock()
    repo.create_illustration = AsyncMock(side_effect=illustrations)
    repo.update_run = AsyncMock(side_effect=lambda r, **kwargs: _apply(r, **kwargs))
    repo.get_run = AsyncMock(return_value=run)

    claude = AsyncMock()
    claude.analyze_story.return_value = analyze_response

    cancel_flag = asyncio.Event()
    call_count = [0]

    with patch("app.orchestrator.pipeline.run_branch", new_callable=AsyncMock) as mock_branch:

        async def fake_branch(illustration, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 3:
                illustration.state = IllustrationState.COMPLETED
            else:
                illustration.state = IllustrationState.FAILED

        mock_branch.side_effect = fake_branch

        await run_pipeline(
            run=run,
            repo=repo,
            claude=claude,
            runpod=AsyncMock(),
            event_bus=AsyncMock(),
            workflow_template={},
            output_dir="/tmp",
            cancel_flag=cancel_flag,
        )

    assert run.status == RunStatus.COMPLETED
    assert run.completed_count == 3
    assert run.failed_count == 2


@pytest.mark.asyncio
async def test_step0_empty_illustrations_no_suitable_scenes():
    """Step 0 returns empty illustrations -> run FAILED with NO_SUITABLE_SCENES."""
    from app.orchestrator.pipeline import run_pipeline

    run = make_run()

    repo = AsyncMock()
    repo.update_run = AsyncMock(side_effect=lambda r, **kwargs: _apply(r, **kwargs))
    repo.get_run = AsyncMock(return_value=run)

    empty_response = AnalyzeStoryResponse(
        style_guide=StyleGuide(
            overall_style_positive="anime",
            overall_style_negative="realistic",
            character_lora="",
            character_baseline_description="...",
        ),
        illustrations=[],
    )
    claude = AsyncMock()
    claude.analyze_story.return_value = empty_response

    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    cancel_flag = asyncio.Event()

    await run_pipeline(
        run=run,
        repo=repo,
        claude=claude,
        runpod=AsyncMock(),
        event_bus=event_bus,
        workflow_template={},
        output_dir="/tmp",
        cancel_flag=cancel_flag,
    )

    assert run.status == RunStatus.FAILED
    assert run.error_code == "NO_SUITABLE_SCENES"
    # Verify run_failed SSE was emitted with error_code
    published_types = [call.args[0] for call in event_bus.publish.call_args_list]
    assert "run_failed" in published_types
    run_failed_payloads = [
        call.args[1] for call in event_bus.publish.call_args_list if call.args[0] == "run_failed"
    ]
    assert run_failed_payloads[0]["error_code"] == "NO_SUITABLE_SCENES"


@pytest.mark.asyncio
async def test_step0_claude_error_sets_step0_failed():
    """Step 0 raises ClaudeError -> run FAILED with STEP0_FAILED error_code."""
    from app.orchestrator.pipeline import run_pipeline
    from app.services.claude import ClaudeError

    run = make_run()

    repo = AsyncMock()
    repo.update_run = AsyncMock(side_effect=lambda r, **kwargs: _apply(r, **kwargs))
    repo.get_run = AsyncMock(return_value=run)

    claude = AsyncMock()
    claude.analyze_story.side_effect = ClaudeError("JSON parse failure after 3 attempts")

    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    cancel_flag = asyncio.Event()

    await run_pipeline(
        run=run,
        repo=repo,
        claude=claude,
        runpod=AsyncMock(),
        event_bus=event_bus,
        workflow_template={},
        output_dir="/tmp",
        cancel_flag=cancel_flag,
    )

    assert run.status == RunStatus.FAILED
    assert run.error_code == "STEP0_FAILED"
    run_failed_payloads = [
        call.args[1] for call in event_bus.publish.call_args_list if call.args[0] == "run_failed"
    ]
    assert run_failed_payloads[0]["error_code"] == "STEP0_FAILED"


@pytest.mark.asyncio
async def test_step0_fails_run_failed():
    """Unhandled exception in pipeline -> run FAILED with INTERNAL_ERROR."""
    from app.orchestrator.pipeline import run_pipeline

    run = make_run()

    repo = AsyncMock()
    repo.update_run = AsyncMock(side_effect=lambda r, **kwargs: _apply(r, **kwargs))
    repo.get_run = AsyncMock(return_value=run)

    claude = AsyncMock()
    # Non-ClaudeError exception triggers INTERNAL_ERROR path
    claude.analyze_story.side_effect = RuntimeError("unexpected failure")

    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    cancel_flag = asyncio.Event()

    await run_pipeline(
        run=run,
        repo=repo,
        claude=claude,
        runpod=AsyncMock(),
        event_bus=event_bus,
        workflow_template={},
        output_dir="/tmp",
        cancel_flag=cancel_flag,
    )

    assert run.status == RunStatus.FAILED
    assert run.error_code == "INTERNAL_ERROR"
    assert run.error_message is not None


def _apply(obj, **kwargs):
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj
