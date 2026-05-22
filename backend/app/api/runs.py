"""API endpoints: POST/GET runs, SSE, cancel."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import STORY_MAX_CHARS
from app.db.models import Run, RunStatus
from app.db.repositories import RunRepository
from app.db.session import get_session_factory
from app.orchestrator.events import EventBus
from app.orchestrator.pipeline import run_pipeline
from app.schemas.api import (
    CreateRunRequest,
    CreateRunResponse,
    IllustrationResponse,
    RunDetailResponse,
    RunResponse,
)
from app.schemas.claude import StyleGuide
from app.services.claude import ClaudeClient
from app.services.runpod import RunPodClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

# In-memory registry of active run buses and cancel flags
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
    style_guide = None
    if run.style_guide_json:
        data = json.loads(run.style_guide_json)
        style_guide = StyleGuide(**data)
    return RunResponse(
        id=run.id,
        status=run.status,
        story_text=run.story_text,
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
        character_role=ill.character_role,
        current_concept=ill.current_concept,
        state=ill.state,
        concept_attempt=ill.concept_attempt,
        prompt_attempt=ill.prompt_attempt,
        image_url=image_url,
    )


@router.post("", status_code=201, response_model=CreateRunResponse)
async def create_run(
    body: CreateRunRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> CreateRunResponse:
    if not body.story_text.strip():
        raise HTTPException(status_code=400, detail="story_text must not be empty")
    if len(body.story_text) > STORY_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"story_text exceeds {STORY_MAX_CHARS} characters",
        )

    repo = RunRepository(session)
    run = await repo.create_run(body.story_text)

    cancel_flag = asyncio.Event()
    event_bus = EventBus()
    # Set an initial empty snapshot so SSE can connect before pipeline starts
    event_bus.set_snapshot(
        {
            "run": {
                "id": run.id,
                "status": run.status,
                "story_text": run.story_text,
                "style_guide": None,
                "illustration_count": 0,
                "completed_count": 0,
                "failed_count": 0,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "error_code": None,
                "error_message": None,
            },
            "illustrations": [],
        }
    )

    _run_buses[run.id] = event_bus
    _cancel_flags[run.id] = cancel_flag

    factory = get_session_factory()

    async def pipeline_task():
        async with factory() as bg_session:
            bg_repo = RunRepository(bg_session)
            bg_run = await bg_repo.get_run(run.id)
            await run_pipeline(
                run=bg_run,
                repo=bg_repo,
                claude=_claude_client,
                runpod=_runpod_client,
                event_bus=event_bus,
                workflow_template=_workflow_template,
                output_dir=_output_dir,
                cancel_flag=cancel_flag,
                character_config=_character_config,
                session_factory=factory,
            )

    background_tasks.add_task(pipeline_task)

    return CreateRunResponse(run_id=run.id)


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
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    event_bus = _run_buses.get(run_id)
    if event_bus is None:
        raise HTTPException(status_code=404, detail="Run not found or not active")

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
