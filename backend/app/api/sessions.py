"""API endpoints for chat sessions and finalize."""

import asyncio
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import runs as runs_api
from app.db.repositories import RunRepository, SessionRepository
from app.db.session import get_session_factory
from app.orchestrator.events import EventBus
from app.orchestrator.pipeline import run_pipeline
from app.schemas.api import (
    FinalizeResponse,
    PostMessageRequest,
    PostMessageResponse,
    SessionMessageResponse,
    SessionResponse,
)
from app.schemas.claude import CollectedBrief
from app.services.session import SessionError, SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _build_session_response(s, messages) -> SessionResponse:
    brief = None
    if s.collected_brief_json:
        brief = CollectedBrief.model_validate_json(s.collected_brief_json)
    return SessionResponse(
        id=s.id,
        state=s.state,
        collected_brief=brief,
        run_id=s.run_id,
        error_code=s.error_code,
        error_message=s.error_message,
        created_at=s.created_at,
        updated_at=s.updated_at,
        messages=[
            SessionMessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


def _service(session: AsyncSession) -> SessionService:
    if runs_api._claude_client is None:
        raise HTTPException(status_code=503, detail="Claude client not initialized")
    return SessionService(SessionRepository(session), runs_api._claude_client)


@router.post("", status_code=201, response_model=SessionResponse)
async def create_session(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SessionResponse:
    svc = _service(session)
    s = await svc.create_session()
    _, messages = await svc.get_session_with_messages(s.id)
    return _build_session_response(s, messages)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_detail(
    session_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SessionResponse:
    svc = _service(session)
    try:
        s, messages = await svc.get_session_with_messages(session_id)
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.message) from e
    return _build_session_response(s, messages)


@router.post("/{session_id}/messages", response_model=PostMessageResponse)
async def post_message(
    session_id: str,
    body: PostMessageRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PostMessageResponse:
    svc = _service(session)
    try:
        reply = await svc.post_message(session_id, body.content)
    except SessionError as e:
        status = {
            "SESSION_NOT_FOUND": 404,
            "EMPTY_MESSAGE": 400,
            "MESSAGE_TOO_LONG": 400,
            "SESSION_LOCKED": 409,
            "SESSION_TOO_LONG": 409,
            "CHAT_FAILED": 502,
        }.get(e.code, 500)
        raise HTTPException(status_code=status, detail=e.message) from e

    s, messages = await svc.get_session_with_messages(session_id)
    return PostMessageResponse(
        session=_build_session_response(s, messages),
        phase=reply.phase,
    )


@router.post("/{session_id}/finalize", status_code=201, response_model=FinalizeResponse)
async def finalize_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> FinalizeResponse:
    svc = _service(session)
    run_repo = RunRepository(session)
    try:
        result = await svc.finalize(session_id, run_repo)
    except SessionError as e:
        status = {
            "SESSION_NOT_FOUND": 404,
            "NOT_READY_TO_FINALIZE": 409,
            "NO_BRIEF": 409,
            "ALREADY_FINALIZED": 409,
            "STORY_BUILD_FAILED": 502,
        }.get(e.code, 500)
        raise HTTPException(status_code=status, detail=e.message) from e

    # Prepare event bus + cancel flag and seed the initial snapshot so the
    # frontend can SSE-subscribe immediately after the redirect.
    cancel_flag = asyncio.Event()
    event_bus = EventBus()
    event_bus.set_snapshot(
        {
            "run": {
                "id": result.run_id,
                "session_id": session_id,
                "status": "RUNNING",
                "story_title": result.story_title,
                "story_blocks": result.story_blocks,
                "style_guide": result.style_guide,
                "illustration_count": len(result.illustrations),
                "completed_count": 0,
                "failed_count": 0,
                "created_at": None,
                "updated_at": None,
                "error_code": None,
                "error_message": None,
            },
            "illustrations": result.illustrations,
        }
    )
    runs_api._run_buses[result.run_id] = event_bus
    runs_api._cancel_flags[result.run_id] = cancel_flag

    factory = get_session_factory()

    async def pipeline_task():
        async with factory() as bg_session:
            bg_repo = RunRepository(bg_session)
            bg_run = await bg_repo.get_run(result.run_id)
            await run_pipeline(
                run=bg_run,
                repo=bg_repo,
                claude=runs_api._claude_client,
                runpod=runs_api._runpod_client,
                event_bus=event_bus,
                workflow_template=runs_api._workflow_template,
                output_dir=runs_api._output_dir,
                cancel_flag=cancel_flag,
                character_config=runs_api._character_config,
                session_factory=factory,
                companions_pool=result.companions_pool,
            )

    background_tasks.add_task(pipeline_task)

    return FinalizeResponse(run_id=result.run_id)
