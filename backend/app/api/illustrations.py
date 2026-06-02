"""API endpoints for the § 6A manual illustration chat fallback."""

import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import runs as runs_api
from app.constants import MAX_MANUAL_ATTEMPTS
from app.db.models import IllustrationState, RunStatus
from app.db.repositories import ManualRepository, RunRepository
from app.db.session import get_session_factory
from app.schemas.api import (
    AcceptAttemptRequest,
    ManualMessageRequest,
    ManualMessageResponse,
    ManualSessionResponse,
)
from app.services.manual import ManualService, ManualServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/illustrations", tags=["illustrations"])


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def _build_manual_response(
    illustration, manual_repo: ManualRepository
) -> ManualSessionResponse:
    rows = await manual_repo.get_messages(illustration.id)
    ms = await manual_repo.get_manual_session(illustration.id)
    last_image_url = None
    sub_phase = "concept_design"
    if ms is not None:
        if ms.last_manual_image_path:
            assert runs_api._image_store is not None, "image_store not initialized"
            last_image_url = runs_api._image_store.url_for(ms.last_manual_image_path)
        sub_phase = ms.sub_phase or "concept_design"
    return ManualSessionResponse(
        illustration_id=illustration.id,
        state=illustration.state,
        manual_attempts=illustration.manual_attempts,
        messages=[
            ManualMessageResponse(
                id=row.id,
                role=row.role,
                content=row.content,
                image_url=row.image_url,
                manual_attempt_index=row.manual_attempt_index,
                concept_used=row.concept_used,
                positive_prompt=row.positive_prompt,
                negative_prompt=row.negative_prompt,
                created_at=row.created_at,
            )
            for row in rows
        ],
        last_image_url=last_image_url,
        sub_phase=sub_phase,
    )


@router.get("/{illustration_id}/manual", response_model=ManualSessionResponse)
async def get_manual_chat(
    illustration_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ManualSessionResponse:
    """Return the full § 6A manual chat for one illustration.

    If the illustration is FAILED but still has budget left (e.g. legacy
    rows from before the § 6A feature, or any FAILED illustration the user
    re-opens), bootstrap the manual flow on the fly: seed the session,
    write the welcome bubble, and transition to MANUAL_CHATTING. This is
    the entry point that makes the chat panel show up on existing stories.
    """
    run_repo = RunRepository(session)
    manual_repo = ManualRepository(session)
    illustration = await run_repo.get_illustration(illustration_id)
    if illustration is None:
        raise HTTPException(status_code=404, detail="Illustration not found")

    if (
        illustration.state == IllustrationState.FAILED
        and illustration.manual_attempts < MAX_MANUAL_ATTEMPTS
    ):
        run = await run_repo.get_run(illustration.run_id)
        if run is not None and run.status != RunStatus.CANCELLED:
            if runs_api._claude_client is not None and runs_api._runpod_client is not None:
                service = ManualService(
                    run_repo=run_repo,
                    manual_repo=manual_repo,
                    claude=runs_api._claude_client,
                    runpod=runs_api._runpod_client,
                    event_bus=runs_api._run_buses.get(illustration.run_id),
                    cancel_flag=runs_api._cancel_flags.get(illustration.run_id),
                    workflow_template=runs_api._workflow_template or {},
                    image_store=runs_api._image_store,
                    character_config=runs_api._character_config,
                )
                await service.open_manual_flow(illustration, source_language=run.source_language)

    return await _build_manual_response(illustration, manual_repo)


@router.post("/{illustration_id}/manual/messages", response_model=ManualSessionResponse)
async def post_manual_message(
    illustration_id: str,
    body: ManualMessageRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ManualSessionResponse:
    """Append a user message and let Agent 6 (and possibly the renderer) respond."""
    if runs_api._claude_client is None or runs_api._runpod_client is None:
        raise HTTPException(status_code=500, detail="Clients not initialized")

    run_repo = RunRepository(session)
    manual_repo = ManualRepository(session)
    illustration = await run_repo.get_illustration(illustration_id)
    if illustration is None:
        raise HTTPException(status_code=404, detail="Illustration not found")

    event_bus = runs_api._run_buses.get(illustration.run_id)
    cancel_flag = runs_api._cancel_flags.get(illustration.run_id)

    service = ManualService(
        run_repo=run_repo,
        manual_repo=manual_repo,
        claude=runs_api._claude_client,
        runpod=runs_api._runpod_client,
        event_bus=event_bus,
        cancel_flag=cancel_flag,
        workflow_template=runs_api._workflow_template or {},
        image_store=runs_api._image_store,
        character_config=runs_api._character_config,
    )

    try:
        illustration = await service.post_message(illustration, body.content)
    except ManualServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    return await _build_manual_response(illustration, manual_repo)


@router.post("/{illustration_id}/accept", response_model=ManualSessionResponse)
async def accept_manual_attempt(
    illustration_id: str,
    body: AcceptAttemptRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ManualSessionResponse:
    """Promote a specific manual attempt's image to canonical (§ 6A.10).

    Bypasses Agent 6 entirely — deterministic server-side promotion. The
    caller is the UI's Accept/Use button on a ``ManualImageCard``.
    """
    if runs_api._claude_client is None or runs_api._runpod_client is None:
        raise HTTPException(status_code=500, detail="Clients not initialized")

    run_repo = RunRepository(session)
    manual_repo = ManualRepository(session)
    illustration = await run_repo.get_illustration(illustration_id)
    if illustration is None:
        raise HTTPException(status_code=404, detail="Illustration not found")

    event_bus = runs_api._run_buses.get(illustration.run_id)
    cancel_flag = runs_api._cancel_flags.get(illustration.run_id)

    service = ManualService(
        run_repo=run_repo,
        manual_repo=manual_repo,
        claude=runs_api._claude_client,
        runpod=runs_api._runpod_client,
        event_bus=event_bus,
        cancel_flag=cancel_flag,
        workflow_template=runs_api._workflow_template or {},
        image_store=runs_api._image_store,
        character_config=runs_api._character_config,
    )

    try:
        await service.accept_attempt(illustration, body.manual_attempt_index)
    except ManualServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    return await _build_manual_response(illustration, manual_repo)


@router.post("/{illustration_id}/manual/iterate", response_model=ManualSessionResponse)
async def iterate_manual_image(
    illustration_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ManualSessionResponse:
    """Append the localized iterate-prompt bubble (§ 6A.10).

    Called when the user clicks the "Iterate" button on a freshly rendered
    manual image.
    """
    if runs_api._claude_client is None or runs_api._runpod_client is None:
        raise HTTPException(status_code=500, detail="Clients not initialized")

    run_repo = RunRepository(session)
    manual_repo = ManualRepository(session)
    illustration = await run_repo.get_illustration(illustration_id)
    if illustration is None:
        raise HTTPException(status_code=404, detail="Illustration not found")

    run = await run_repo.get_run(illustration.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    event_bus = runs_api._run_buses.get(illustration.run_id)
    cancel_flag = runs_api._cancel_flags.get(illustration.run_id)

    service = ManualService(
        run_repo=run_repo,
        manual_repo=manual_repo,
        claude=runs_api._claude_client,
        runpod=runs_api._runpod_client,
        event_bus=event_bus,
        cancel_flag=cancel_flag,
        workflow_template=runs_api._workflow_template or {},
        image_store=runs_api._image_store,
        character_config=runs_api._character_config,
    )

    try:
        await service.append_iterate_prompt(illustration, source_language=run.source_language)
    except ManualServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    return await _build_manual_response(illustration, manual_repo)


@router.post("/{illustration_id}/regenerate", response_model=ManualSessionResponse)
async def regenerate_illustration(
    illustration_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ManualSessionResponse:
    """Begin a manual regeneration on a COMPLETED illustration (§ 6A.9)."""
    if runs_api._claude_client is None or runs_api._runpod_client is None:
        raise HTTPException(status_code=500, detail="Clients not initialized")

    run_repo = RunRepository(session)
    manual_repo = ManualRepository(session)
    illustration = await run_repo.get_illustration(illustration_id)
    if illustration is None:
        raise HTTPException(status_code=404, detail="Illustration not found")

    run = await run_repo.get_run(illustration.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    event_bus = runs_api._run_buses.get(illustration.run_id)
    cancel_flag = runs_api._cancel_flags.get(illustration.run_id)

    service = ManualService(
        run_repo=run_repo,
        manual_repo=manual_repo,
        claude=runs_api._claude_client,
        runpod=runs_api._runpod_client,
        event_bus=event_bus,
        cancel_flag=cancel_flag,
        workflow_template=runs_api._workflow_template or {},
        image_store=runs_api._image_store,
        character_config=runs_api._character_config,
    )

    try:
        await service.start_regeneration(illustration, source_language=run.source_language)
    except ManualServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    return await _build_manual_response(illustration, manual_repo)
