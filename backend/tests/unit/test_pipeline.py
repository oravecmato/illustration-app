"""Unit tests for top-level orchestrator pipeline (§11.1).

The pipeline no longer authors the story; Agent 0b runs inside the session
finalize flow and pre-creates illustration rows. The pipeline only renders
those pre-existing illustrations.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import IllustrationState, RunStatus
from app.schemas.claude import StyleGuide

STYLE_GUIDE = StyleGuide(
    overall_style_positive="anime style",
    overall_style_negative="photorealistic",
    character_lora="",
    character_baseline_description="Warm lighting",
)


def make_run(run_id="run-1", n_illustrations=3):
    run = MagicMock()
    run.id = run_id
    run.session_id = "sess-1"
    run.status = RunStatus.RUNNING
    run.story_title = "Title"
    run.story_blocks_json = json.dumps(
        [{"type": "paragraph", "text": "P"}, {"type": "illustration", "scene_index": 0}]
    )
    run.style_guide_json = STYLE_GUIDE.model_dump_json()
    run.illustration_count = n_illustrations
    run.completed_count = 0
    run.failed_count = 0
    run.error_code = None
    run.error_message = None
    run.created_at = None
    run.updated_at = None
    return run


def make_illustration(run_id, scene_index):
    ill = MagicMock()
    ill.id = f"ill-{scene_index}"
    ill.run_id = run_id
    ill.scene_index = scene_index
    ill.scene_excerpt = f"Scene {scene_index}"
    ill.current_concept = f"Concept {scene_index}"
    ill.character_role = "male"
    ill.state = IllustrationState.PENDING
    ill.concept_attempt = 1
    ill.prompt_attempt = 1
    ill.image_path = None
    ill.error_message = None
    return ill


def _apply(obj, **kwargs):
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def make_repo(run, illustrations):
    repo = AsyncMock()
    repo.update_run = AsyncMock(side_effect=lambda r, **kwargs: _apply(r, **kwargs))
    repo.get_run = AsyncMock(return_value=run)
    repo.get_illustrations_for_run = AsyncMock(return_value=illustrations)
    return repo


@pytest.mark.asyncio
async def test_three_illustrations_spawn_three_branches():
    from app.orchestrator.pipeline import run_pipeline

    run = make_run(n_illustrations=3)
    illustrations = [make_illustration(run.id, i) for i in range(3)]
    repo = make_repo(run, illustrations)

    cancel_flag = asyncio.Event()
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    event_bus.set_snapshot = MagicMock()

    with patch("app.orchestrator.pipeline.run_branch", new_callable=AsyncMock) as mock_branch:

        async def fake_branch(illustration, **kwargs):
            illustration.state = IllustrationState.COMPLETED

        mock_branch.side_effect = fake_branch

        await run_pipeline(
            run=run,
            repo=repo,
            claude=AsyncMock(),
            runpod=AsyncMock(),
            event_bus=event_bus,
            workflow_template={},
            output_dir="/tmp",
            cancel_flag=cancel_flag,
        )

    assert mock_branch.call_count == 3


@pytest.mark.asyncio
async def test_all_branches_succeed_run_completed():
    from app.orchestrator.pipeline import run_pipeline

    n = 3
    run = make_run(n_illustrations=n)
    illustrations = [make_illustration(run.id, i) for i in range(n)]
    repo = make_repo(run, illustrations)

    cancel_flag = asyncio.Event()
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    event_bus.set_snapshot = MagicMock()

    with patch("app.orchestrator.pipeline.run_branch", new_callable=AsyncMock) as mock_branch:

        async def fake_branch(illustration, **kwargs):
            illustration.state = IllustrationState.COMPLETED

        mock_branch.side_effect = fake_branch

        await run_pipeline(
            run=run,
            repo=repo,
            claude=AsyncMock(),
            runpod=AsyncMock(),
            event_bus=event_bus,
            workflow_template={},
            output_dir="/tmp",
            cancel_flag=cancel_flag,
        )

    assert run.status == RunStatus.COMPLETED
    assert run.completed_count == n


@pytest.mark.asyncio
async def test_mixed_outcome_run_still_completed():
    from app.orchestrator.pipeline import run_pipeline

    n = 5
    run = make_run(n_illustrations=n)
    illustrations = [make_illustration(run.id, i) for i in range(n)]
    repo = make_repo(run, illustrations)

    cancel_flag = asyncio.Event()
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    event_bus.set_snapshot = MagicMock()
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
            claude=AsyncMock(),
            runpod=AsyncMock(),
            event_bus=event_bus,
            workflow_template={},
            output_dir="/tmp",
            cancel_flag=cancel_flag,
        )

    assert run.status == RunStatus.COMPLETED
    assert run.completed_count == 3
    assert run.failed_count == 2


@pytest.mark.asyncio
async def test_cancellation_marks_run_cancelled():
    from app.orchestrator.pipeline import run_pipeline

    n = 2
    run = make_run(n_illustrations=n)
    illustrations = [make_illustration(run.id, i) for i in range(n)]
    repo = make_repo(run, illustrations)

    cancel_flag = asyncio.Event()
    cancel_flag.set()
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    event_bus.set_snapshot = MagicMock()

    with patch("app.orchestrator.pipeline.run_branch", new_callable=AsyncMock) as mock_branch:

        async def fake_branch(illustration, **kwargs):
            illustration.state = IllustrationState.CANCELLED

        mock_branch.side_effect = fake_branch

        await run_pipeline(
            run=run,
            repo=repo,
            claude=AsyncMock(),
            runpod=AsyncMock(),
            event_bus=event_bus,
            workflow_template={},
            output_dir="/tmp",
            cancel_flag=cancel_flag,
        )

    assert run.status == RunStatus.CANCELLED
    published_types = [c.args[0] for c in event_bus.publish.call_args_list]
    assert "run_cancelled" in published_types


@pytest.mark.asyncio
async def test_unhandled_exception_gives_internal_error():
    from app.orchestrator.pipeline import run_pipeline

    run = make_run(n_illustrations=1)
    illustrations = [make_illustration(run.id, 0)]
    repo = make_repo(run, illustrations)

    cancel_flag = asyncio.Event()
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    event_bus.set_snapshot = MagicMock()

    with patch("app.orchestrator.pipeline.run_branch", new_callable=AsyncMock) as mock_branch:
        mock_branch.side_effect = RuntimeError("rendering exploded")

        await run_pipeline(
            run=run,
            repo=repo,
            claude=AsyncMock(),
            runpod=AsyncMock(),
            event_bus=event_bus,
            workflow_template={},
            output_dir="/tmp",
            cancel_flag=cancel_flag,
        )

    assert run.status == RunStatus.FAILED
    assert run.error_code == "INTERNAL_ERROR"
