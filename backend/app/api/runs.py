"""API endpoints: GET runs, SSE, cancel.

Runs are no longer created directly by this router — they are created by the
session-finalize endpoint in ``app.api.sessions`` once Agent 0b has produced
the story and scenes.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, RunStatus
from app.db.repositories import RunRepository
from app.db.session import get_session_factory
from app.orchestrator.events import EventBus
from app.schemas.api import (
    IllustrationResponse,
    RunDetailResponse,
    RunResponse,
)
from app.schemas.claude import StyleGuide
from app.services.claude import ClaudeClient
from app.services.runpod import RunPodClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

# In-memory registry of active run buses and cancel flags. Shared with the
# sessions router so that finalize() can register the bus/flag for the
# spawned pipeline before this router serves SSE for that run id.
_run_buses: dict[str, EventBus] = {}
_cancel_flags: dict[str, asyncio.Event] = {}

# Set by main.py during startup
_claude_client: ClaudeClient | None = None
_runpod_client: RunPodClient | None = None
_workflow_template: dict | None = None
_output_dir: str | None = None
_character_config: dict | None = None


def set_clients(
    claude: ClaudeClient,
    runpod: RunPodClient,
    workflow: dict,
    output_dir: str,
    character_config: dict | None = None,
) -> None:
    global _claude_client, _runpod_client, _workflow_template, _output_dir, _character_config
    _claude_client = claude
    _runpod_client = runpod
    _workflow_template = workflow
    _output_dir = output_dir
    _character_config = character_config


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _build_run_response(run: Run) -> RunResponse:
    style_guide = StyleGuide(**json.loads(run.style_guide_json))
    story_blocks = json.loads(run.story_blocks_json)
    return RunResponse(
        id=run.id,
        session_id=run.session_id,
        status=run.status,
        story_title=run.story_title,
        story_blocks=story_blocks,
        style_guide=style_guide,
        illustration_count=run.illustration_count,
        completed_count=run.completed_count,
        failed_count=run.failed_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
        error_code=run.error_code,
        error_message=run.error_message,
    )


def _build_illustration_response(ill) -> IllustrationResponse:
    image_url = None
    if ill.image_path:
        image_url = f"/static/{ill.image_path}"
    return IllustrationResponse(
        id=ill.id,
        scene_index=ill.scene_index,
        scene_excerpt=ill.scene_excerpt,
        paragraph_index=ill.paragraph_index,
        character_role=ill.character_role,
        current_concept=ill.current_concept,
        state=ill.state,
        concept_attempt=ill.concept_attempt,
        prompt_attempt=ill.prompt_attempt,
        image_url=image_url,
    )


def _build_snapshot(run: Run, illustrations: list) -> dict:
    """Build an SSE snapshot from current DB state (matches RunDetailResponse shape)."""
    return {
        "run": _build_run_response(run).model_dump(mode="json"),
        "illustrations": [
            _build_illustration_response(ill).model_dump(mode="json") for ill in illustrations
        ],
    }


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RunDetailResponse:
    repo = RunRepository(session)
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    illustrations = await repo.get_illustrations_for_run(run_id)
    return RunDetailResponse(
        run=_build_run_response(run),
        illustrations=[_build_illustration_response(ill) for ill in illustrations],
    )


@router.get("/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> StreamingResponse:
    # Load fresh state from DB — used both for the initial snapshot and to
    # handle terminal runs whose bus is no longer active (e.g., after server
    # restart).
    repo = RunRepository(session)
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    illustrations = await repo.get_illustrations_for_run(run_id)
    snapshot = _build_snapshot(run, illustrations)

    event_bus = _run_buses.get(run_id)
    terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}

    if event_bus is None:
        # No active bus. If the run is terminal we can still serve a complete
        # snapshot followed by the appropriate terminal event so the frontend
        # closes the stream cleanly.
        if run.status not in terminal:
            raise HTTPException(status_code=404, detail="Run not found or not active")

        async def generate_terminal():
            yield f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"
            if run.status == RunStatus.COMPLETED:
                payload = {"completed": run.completed_count, "failed": run.failed_count}
                event_type = "run_completed"
            elif run.status == RunStatus.FAILED:
                payload = {"error_code": run.error_code, "error_message": run.error_message}
                event_type = "run_failed"
            else:
                payload = {}
                event_type = "run_cancelled"
            yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            generate_terminal(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Active run: refresh the snapshot so subscribers see current state, not
    # the stale snapshot left over from earlier in the pipeline.
    event_bus.set_snapshot(snapshot)
    queue = event_bus.subscribe()

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
                    if event["type"] in ("run_completed", "run_failed", "run_cancelled"):
                        break
                except TimeoutError:
                    # Heartbeat
                    yield "event: heartbeat\ndata: {}\n\n"
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    repo = RunRepository(session)
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    if run.status in terminal:
        raise HTTPException(status_code=409, detail="Run is already in a terminal state")

    cancel_flag = _cancel_flags.get(run_id)
    if cancel_flag:
        cancel_flag.set()

    return {"status": "CANCELLED"}
