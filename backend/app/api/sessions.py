"""API endpoints for chat sessions.

The previous explicit ``POST /sessions/{id}/finalize`` endpoint has been
removed. When ``POST /sessions/{id}/messages`` produces an assistant
reply with ``phase == "confirmed"``, this router:

1. Pre-allocates a run id and persists it on the session.
2. Registers an in-memory event bus + cancel flag for the future run.
3. Schedules a BackgroundTask that runs Agent 0b (build story), creates
   the run + illustration rows with that id, seeds the bus snapshot,
   and starts the pipeline.
4. Returns the run id to the frontend in the message response.

This lets the frontend navigate to ``/runs/:run_id`` immediately and
render its loading state while Agent 0b is still working, instead of
waiting for the slow build-story call to return synchronously.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import runs as runs_api
from app.api.auth import (
    QuotaExhausted,
    consume_run_quota,
    decrement_runs_used,
    require_access_key,
    stamp_run_access_key,
)
from app.constants import ERROR_CODE_QUOTA_EXHAUSTED
from app.db.models import AccessKey, SessionState
from app.db.repositories import RunRepository, SessionRepository
from app.db.session import get_session_factory
from app.orchestrator.events import EventBus
from app.orchestrator.pipeline import run_pipeline
from app.schemas.api import (
    PostMessageRequest,
    PostMessageResponse,
    SessionMessageResponse,
    SessionResponse,
)
from app.schemas.claude import CollectedBrief
from app.services.session import SessionError, SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# Strong references to detached pipeline tasks so the GC doesn't cancel
# them mid-run. Tasks remove themselves via the done_callback set in
# _schedule_finalize.
_background_tasks: set[asyncio.Task] = set()


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
        source_language=s.source_language,
        detected_language=s.detected_language,
        topic_short=s.topic_short,
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
    _key: AccessKey = Depends(require_access_key),  # noqa: B008
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


def _schedule_finalize(
    session_id: str,
    run_id: str,
    event_bus: EventBus,
    cancel_flag: asyncio.Event,
    access_key: str,
) -> None:
    """Schedule Agent 0b + pipeline as a detached asyncio.Task.

    Using ``asyncio.create_task`` (rather than FastAPI's BackgroundTasks)
    decouples the work from the response lifecycle so the messages
    endpoint can return immediately — the frontend navigates to
    /runs/:id without waiting for Agent 0b or the pipeline to finish.

    The task uses its own DB session (factory) because the request's
    AsyncSession is closed once the response is returned.
    """
    factory = get_session_factory()

    async def task() -> None:
        try:
            async with factory() as bg_session:
                svc = SessionService(SessionRepository(bg_session), runs_api._claude_client)
                run_repo = RunRepository(bg_session)
                result = await svc.finalize(session_id, run_repo, run_id=run_id)
                # Pin the access key onto the freshly created Run row so
                # the orchestrator/reaper refund path can locate it via
                # runs.access_key without joining through the session.
                await stamp_run_access_key(bg_session, result.run_id, access_key)

            # Seed the snapshot for SSE subscribers. From this point on, a
            # subscriber attaching to the bus immediately receives the full
            # initial state and the pipeline progress events that follow.
            event_bus.set_snapshot(
                {
                    "run": {
                        "id": result.run_id,
                        "session_id": session_id,
                        "status": "RUNNING",
                        "source_language": result.source_language,
                        "language": result.source_language,
                        "topic_short": result.topic_short,
                        "story_title": result.story_title,
                        "story_title_translation_state": "source",
                        "story_topic_description": result.story_topic_description,
                        "story_topic_description_translation_state": "source",
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
            # Wake any SSE subscriber that attached BEFORE the row existed.
            # `set_snapshot` alone doesn't unblock queue.get() — we need an
            # explicit publish.
            await event_bus.publish(
                "snapshot",
                {
                    "run": event_bus._snapshot["run"],
                    "illustrations": event_bus._snapshot["illustrations"],
                },
            )

            async with factory() as bg_session2:
                bg_repo = RunRepository(bg_session2)
                bg_run = await bg_repo.get_run(result.run_id)
                await run_pipeline(
                    run=bg_run,
                    repo=bg_repo,
                    claude=runs_api._claude_client,
                    runpod=runs_api._runpod_client,
                    event_bus=event_bus,
                    workflow_template=runs_api._workflow_template,
                    image_store=runs_api._image_store,
                    cancel_flag=cancel_flag,
                    character_config=runs_api._character_config,
                    session_factory=factory,
                )
        except SessionError as e:
            # Agent 0b failed (or the brief was invalid). The run row
            # was never created; emit a run_failed event so the SSE
            # subscriber on the (existing) bus learns the bad news and
            # the loading screen can flip into an error state. Also
            # unregister the bus so a refreshed page that hits SSE next
            # gets a clean 404 instead of a permanently-open empty
            # stream.
            await event_bus.publish(
                "run_failed",
                {"error_code": e.code, "error_message": e.message},
            )
            runs_api._run_buses.pop(run_id, None)
            runs_api._cancel_flags.pop(run_id, None)
            # Refund the quota slot directly via the access key: Agent
            # 0b failed before a Run row existed, so the Run-anchored
            # refund path has nothing to flip against. Decrement
            # ``runs_used`` in place. Safe because only this SessionError
            # branch reaches here per consumed slot — no idempotency
            # race to worry about.
            async with factory() as refund_session:
                try:
                    await decrement_runs_used(refund_session, access_key)
                except Exception:  # pragma: no cover — best effort
                    logger.exception("Refund after STORY_BUILD_FAILED failed for %s", run_id)
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("Unexpected error during background finalize")
            await event_bus.publish(
                "run_failed",
                {"error_code": "INTERNAL_ERROR", "error_message": str(exc)},
            )
            runs_api._run_buses.pop(run_id, None)
            runs_api._cancel_flags.pop(run_id, None)
            async with factory() as refund_session:
                try:
                    await decrement_runs_used(refund_session, access_key)
                except Exception:  # pragma: no cover — best effort
                    logger.exception("Refund after INTERNAL_ERROR failed for %s", run_id)

    # Detach from the request lifecycle so the response returns
    # immediately. Keep a strong reference so the task isn't GC'd while
    # running. (BackgroundTasks would block the response until the
    # pipeline finished, which can take minutes.)
    bg = asyncio.create_task(task())
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)


@router.post("/{session_id}/messages", response_model=PostMessageResponse)
async def post_message(
    session_id: str,
    body: PostMessageRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    key: AccessKey = Depends(require_access_key),  # noqa: B008
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
            "SESSION_USER_MESSAGE_LIMIT": 429,
            "CHAT_FAILED": 502,
        }.get(e.code, 500)
        # Service-level errors carry their own error_code; propagate it
        # in the response body so the frontend can branch on it (e.g. to
        # show the SESSION_USER_MESSAGE_LIMIT banner).
        raise HTTPException(
            status_code=status,
            detail={"error_code": e.code, "message": e.message},
        ) from e

    s, messages = await svc.get_session_with_messages(session_id)
    run_id: str | None = None

    if reply.phase == "confirmed" and s.run_id is None and s.collected_brief_json is not None:
        # Pre-allocate the run id, persist on the session, and schedule
        # Agent 0b + the pipeline as a background task. The frontend
        # uses the returned run_id to navigate immediately; the loader
        # in RunView stays on screen until SSE delivers the snapshot
        # once Agent 0b finishes.
        run_id = str(uuid.uuid4())
        await svc.repo.update_session(
            s,
            state=SessionState.FINALIZING,
            run_id=run_id,
        )

        # Consume one quota slot from the access key before any
        # background work spins up. We do this AFTER the run_id is
        # pinned to the session so a concurrent loser sees a clean
        # state if we lose the conditional UPDATE race.
        try:
            await consume_run_quota(session, key.key, run_id)
        except QuotaExhausted as e:
            # Roll the session back to CHATTING with no run_id so the
            # user can either grant more quota and retry, or start over.
            await svc.repo.update_session(s, state=SessionState.CHATTING, run_id=None)
            raise HTTPException(
                status_code=402,
                detail={
                    "error_code": ERROR_CODE_QUOTA_EXHAUSTED,
                    "message": "Run quota exhausted for this access key.",
                },
            ) from e

        # Register bus + cancel flag BEFORE returning so that an
        # immediately-subscribing SSE client finds them. The background
        # task will populate the snapshot once Agent 0b succeeds.
        event_bus = EventBus()
        cancel_flag = asyncio.Event()
        runs_api._run_buses[run_id] = event_bus
        runs_api._cancel_flags[run_id] = cancel_flag

        _schedule_finalize(session_id, run_id, event_bus, cancel_flag, key.key)

    return PostMessageResponse(
        session=_build_session_response(s, messages),
        phase=reply.phase,
        detected_language=reply.language if reply.language else s.detected_language,
        topic_short=reply.topic_short if reply.topic_short else s.topic_short,
        run_id=run_id,
    )
