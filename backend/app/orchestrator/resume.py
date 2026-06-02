"""Startup orphan-run resumer.

When uvicorn restarts mid-pipeline, in-flight RunPod jobs survive
(RunPod is external GPU infra) but the in-process orchestrator that
was polling them does not. Without intervention we would waste the
paid render and reap the illustration as ``OOM_REAPED``.

This module re-polls every persisted ``Illustration.runpod_job_id`` on
startup. For auto-pipeline branches we apply Scope B: skip the
evaluator, write the recovered bytes as the canonical scene image, and
transition straight to ``COMPLETED``. The branch task that would
normally evaluate is dead — we cannot resume the prompt-revision loop —
so the recovered render is accepted as-is.

For manual-flow branches we mirror ``manual.py``'s post-render side
effects: save the ``manual_K`` image, append the image row to the
chat transcript, flip ``sub_phase`` to ``feedback_gathering``, and
return to ``MANUAL_CHATTING`` so the user can resume iterating.

Non-resumable orphan illustrations (mid-Agent calls, no persisted
job id) are reaped as ``OOM_REAPED`` exactly like the previous
``_reap_orphan_runs`` did.
"""

import asyncio
import json
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth import refund_run_quota
from app.constants import (
    ERROR_CODE_OOM_REAPED,
    ERROR_CODE_RENDER_FAILED,
    ERROR_CODE_RENDER_QUEUE_TIMEOUT,
    ERROR_CODE_RENDER_TIMEOUT,
)
from app.db.models import (
    Illustration,
    IllustrationState,
    ManualMessageRole,
    Run,
    RunStatus,
)
from app.db.repositories import ManualRepository, RunRepository
from app.orchestrator.events import EventBus
from app.services.images import save_image, save_manual_image
from app.services.runpod import (
    RunPodClient,
    RunPodError,
    RunPodQueueTimeoutError,
    RunPodTimeoutError,
)
from app.services.storage import ImageStore

logger = logging.getLogger(__name__)

# Illustration states that own an in-flight RunPod job — only these are
# resumable, and only when ``runpod_job_id`` is populated.
_RESUMABLE_STATES = (IllustrationState.RENDERING, IllustrationState.MANUAL_RENDERING)

# Non-terminal state that legitimately survives a restart untouched:
# the user is mid-chat in the manual fallback.
_USER_RESUMABLE_STATES = (IllustrationState.MANUAL_CHATTING,)

_TERMINAL_ILL = {
    IllustrationState.COMPLETED,
    IllustrationState.FAILED,
    IllustrationState.CANCELLED,
}
_TERMINAL_RUN = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}

# Mirrors ``orchestrator/pipeline.py::_INFRA_REFUND_CODES`` — kept in
# sync because both finalize paths share the same § 8.11.4 semantics.
_INFRA_REFUND_CODES = frozenset(
    {
        ERROR_CODE_RENDER_TIMEOUT,
        ERROR_CODE_RENDER_QUEUE_TIMEOUT,
        ERROR_CODE_OOM_REAPED,
    }
)


async def resume_orphan_runs(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    runpod: RunPodClient,
    image_store: ImageStore,
    run_buses: dict[str, EventBus],
    cancel_flags: dict[str, asyncio.Event],
) -> None:
    """Classify orphans under every RUNNING run, schedule resumes,
    reap the rest. Returns synchronously once classification is done;
    actual RunPod polling happens in detached background tasks so
    startup is not blocked by a 30-minute IN_QUEUE wait.
    """
    async with session_factory() as s:
        running_run_ids = list(
            (await s.execute(select(Run.id).where(Run.status == RunStatus.RUNNING))).scalars().all()
        )
    if not running_run_ids:
        return

    for run_id in running_run_ids:
        await _resume_one_run(
            run_id=run_id,
            session_factory=session_factory,
            runpod=runpod,
            image_store=image_store,
            run_buses=run_buses,
            cancel_flags=cancel_flags,
        )


async def _resume_one_run(
    *,
    run_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    runpod: RunPodClient,
    image_store: ImageStore,
    run_buses: dict[str, EventBus],
    cancel_flags: dict[str, asyncio.Event],
) -> None:
    async with session_factory() as s:
        ills = list(
            (await s.execute(select(Illustration).where(Illustration.run_id == run_id)))
            .scalars()
            .all()
        )

        resumable: list[tuple[str, str, bool]] = []  # (ill_id, job_id, is_manual)
        user_alive = False
        reap_ids: list[str] = []
        for ill in ills:
            if ill.state in _TERMINAL_ILL:
                continue
            if ill.state in _RESUMABLE_STATES and ill.runpod_job_id:
                is_manual = ill.state == IllustrationState.MANUAL_RENDERING
                resumable.append((ill.id, ill.runpod_job_id, is_manual))
            elif ill.state in _USER_RESUMABLE_STATES:
                user_alive = True
            else:
                reap_ids.append(ill.id)

        if reap_ids:
            await s.execute(
                update(Illustration)
                .where(Illustration.id.in_(reap_ids))
                .values(
                    state=IllustrationState.FAILED,
                    error_code=ERROR_CODE_OOM_REAPED,
                    runpod_job_id=None,
                )
            )
            await s.commit()

    if not resumable:
        # No GPU job to recover. If a manual chat is still alive, leave
        # the run RUNNING — the next user interaction will finalize via
        # ``manual.py``. Otherwise finalize from current DB state.
        if user_alive:
            logger.warning(
                "Startup resume: run %s — 0 in-flight, %d reaped, manual chat alive",
                run_id,
                len(reap_ids),
            )
            return
        await _finalize_run_if_terminal(
            session_factory=session_factory,
            event_bus=run_buses.get(run_id),
            run_id=run_id,
        )
        logger.warning(
            "Startup resume: run %s — 0 in-flight, %d reaped, finalized",
            run_id,
            len(reap_ids),
        )
        return

    # Ensure SSE plumbing exists so the UI can attach to the live run
    # while the background resumes run.
    bus = run_buses.setdefault(run_id, EventBus())
    cancel_flag = cancel_flags.setdefault(run_id, asyncio.Event())

    for ill_id, job_id, is_manual in resumable:
        asyncio.create_task(
            _resume_one_render(
                session_factory=session_factory,
                runpod=runpod,
                image_store=image_store,
                event_bus=bus,
                cancel_flag=cancel_flag,
                illustration_id=ill_id,
                job_id=job_id,
                is_manual=is_manual,
            )
        )
    logger.warning(
        "Startup resume: run %s — %d render(s) re-polling, %d reaped",
        run_id,
        len(resumable),
        len(reap_ids),
    )


async def _resume_one_render(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    runpod: RunPodClient,
    image_store: ImageStore,
    event_bus: EventBus,
    cancel_flag: asyncio.Event,
    illustration_id: str,
    job_id: str,
    is_manual: bool,
) -> None:
    """Re-poll one persisted RunPod job and complete the illustration.

    Auto-pipeline (Scope B): write canonical image + transition COMPLETED;
    evaluator is bypassed because the in-process branch loop is gone.

    Manual flow: write ``manual_K`` image + append image row +
    ``sub_phase=feedback_gathering`` + back to ``MANUAL_CHATTING``.
    Failure on a manual resume refunds the ``manual_attempts``
    increment and resets ``sub_phase`` to ``concept_design`` so the
    user can retry from a clean state.
    """
    # Look up scene_index once for the status callback.
    async with session_factory() as s:
        ill = await s.get(Illustration, illustration_id)
        if ill is None:
            logger.error("orphan resume: illustration %s vanished", illustration_id)
            return
        scene_index = ill.scene_index
        run_id = ill.run_id

    async def _publish_status(status: str) -> None:
        await event_bus.publish(
            "illustration_runpod_status",
            {
                "illustration_id": illustration_id,
                "scene_index": scene_index,
                "runpod_status": status,
            },
        )

    try:
        image_bytes = await runpod.poll_existing_job(job_id, on_status_change=_publish_status)
    except RunPodQueueTimeoutError as e:
        await _finish_failed(
            session_factory=session_factory,
            event_bus=event_bus,
            illustration_id=illustration_id,
            error_code=ERROR_CODE_RENDER_QUEUE_TIMEOUT,
            error_message=f"Image rendering queue timed out (resumed): {e}",
            is_manual=is_manual,
        )
    except RunPodTimeoutError as e:
        await _finish_failed(
            session_factory=session_factory,
            event_bus=event_bus,
            illustration_id=illustration_id,
            error_code=ERROR_CODE_RENDER_TIMEOUT,
            error_message=f"Image rendering timed out (resumed): {e}",
            is_manual=is_manual,
        )
    except RunPodError as e:
        await _finish_failed(
            session_factory=session_factory,
            event_bus=event_bus,
            illustration_id=illustration_id,
            error_code=ERROR_CODE_RENDER_FAILED,
            error_message=f"Image rendering failed (resumed): {e}",
            is_manual=is_manual,
        )
    except Exception as e:  # pragma: no cover — unexpected
        logger.exception("orphan resume: unexpected error polling job %s", job_id)
        await _finish_failed(
            session_factory=session_factory,
            event_bus=event_bus,
            illustration_id=illustration_id,
            error_code=ERROR_CODE_RENDER_FAILED,
            error_message=f"Image rendering failed (resumed): {e}",
            is_manual=is_manual,
        )
    else:
        await _finish_completed(
            session_factory=session_factory,
            image_store=image_store,
            event_bus=event_bus,
            illustration_id=illustration_id,
            image_bytes=image_bytes,
            is_manual=is_manual,
        )

    await _finalize_run_if_terminal(
        session_factory=session_factory,
        event_bus=event_bus,
        run_id=run_id,
        cancel_flag=cancel_flag,
    )


async def _finish_completed(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    image_store: ImageStore,
    event_bus: EventBus,
    illustration_id: str,
    image_bytes: bytes,
    is_manual: bool,
) -> None:
    async with session_factory() as s:
        repo = RunRepository(s)
        ill = await s.get(Illustration, illustration_id)
        if ill is None:
            return

        if is_manual:
            attempt = ill.manual_attempts  # already incremented pre-dispatch
            manual_path = await save_manual_image(
                image_bytes, image_store, ill.run_id, ill.scene_index, attempt
            )
            # On the concept-design path, ``current_concept`` was set to
            # the just-confirmed candidate before dispatch; on the
            # feedback path it carries the last_agreed_concept. Either
            # way it's the concept that produced this render.
            agreed = ill.current_concept
            prompts_blob: dict = {}
            if ill.current_prompts_json:
                try:
                    prompts_blob = json.loads(ill.current_prompts_json)
                except json.JSONDecodeError:
                    prompts_blob = {}
            positive = prompts_blob.get("positive", "")
            negative = prompts_blob.get("negative", "")

            manual_repo = ManualRepository(s)
            ms = await manual_repo.get_manual_session(ill.id)
            if ms is not None:
                await manual_repo.update_manual_session(
                    ms,
                    last_manual_image_path=manual_path,
                    last_agreed_concept=agreed,
                    sub_phase="feedback_gathering",
                )
            image_url = image_store.url_for(manual_path)
            image_msg = await manual_repo.add_message(
                illustration_id=ill.id,
                role=ManualMessageRole.IMAGE,
                content="",
                image_url=image_url,
                manual_attempt_index=attempt,
                concept_used=agreed,
                positive_prompt=positive,
                negative_prompt=negative,
            )
            await repo.update_illustration(
                ill,
                state=IllustrationState.MANUAL_CHATTING,
                runpod_job_id=None,
            )
            await _publish_ill_state(event_bus, ill, IllustrationState.MANUAL_CHATTING)
            await event_bus.publish(
                "manual_image_rendered",
                {
                    "illustration_id": ill.id,
                    "scene_index": ill.scene_index,
                    "sub_phase": "feedback_gathering",
                    "manual_attempt": attempt,
                    "image_url": image_url,
                    "image_message_id": image_msg.id,
                    "concept_used": agreed,
                    "positive_prompt": positive,
                    "negative_prompt": negative,
                },
            )
        else:
            canonical_path = await save_image(image_bytes, image_store, ill.run_id, ill.scene_index)
            await repo.update_illustration(
                ill,
                state=IllustrationState.COMPLETED,
                image_path=canonical_path,
                runpod_job_id=None,
            )
            image_url = image_store.url_for(canonical_path)
            await _publish_ill_state(event_bus, ill, IllustrationState.COMPLETED)
            await event_bus.publish(
                "illustration_completed",
                {
                    "illustration_id": ill.id,
                    "scene_index": ill.scene_index,
                    "image_url": image_url,
                },
            )


async def _finish_failed(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    event_bus: EventBus,
    illustration_id: str,
    error_code: str,
    error_message: str,
    is_manual: bool,
) -> None:
    async with session_factory() as s:
        repo = RunRepository(s)
        ill = await s.get(Illustration, illustration_id)
        if ill is None:
            return

        if is_manual:
            # Parity with ``manual.py``'s queue-timeout handler: refund
            # the ``manual_attempts`` increment so infra noise doesn't
            # punish the user's budget, reset the sub_phase, and return
            # the illustration to MANUAL_CHATTING for retry. The
            # ``error_code`` is recorded on the row even though the
            # state stays non-terminal — diagnostic only.
            await repo.update_illustration(
                ill,
                state=IllustrationState.MANUAL_CHATTING,
                manual_attempts=max(0, ill.manual_attempts - 1),
                runpod_job_id=None,
                error_code=error_code,
                error_message=error_message,
            )
            manual_repo = ManualRepository(s)
            ms = await manual_repo.get_manual_session(ill.id)
            if ms is not None:
                await manual_repo.update_manual_session(
                    ms,
                    sub_phase="concept_design",
                    last_concept_candidate=None,
                )
            await _publish_ill_state(event_bus, ill, IllustrationState.MANUAL_CHATTING)
        else:
            await repo.update_illustration(
                ill,
                state=IllustrationState.FAILED,
                error_code=error_code,
                error_message=error_message,
                runpod_job_id=None,
            )
            await _publish_ill_state(event_bus, ill, IllustrationState.FAILED)


async def _publish_ill_state(event_bus: EventBus, ill: Illustration, state: str) -> None:
    await event_bus.publish(
        "illustration_state",
        {
            "illustration_id": ill.id,
            "scene_index": ill.scene_index,
            "state": state,
            "concept_attempt": ill.concept_attempt,
            "prompt_attempt": ill.prompt_attempt,
            "current_concept": ill.current_concept,
            "scene_excerpt": ill.scene_excerpt,
        },
    )


async def _finalize_run_if_terminal(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    event_bus: EventBus | None,
    run_id: str,
    cancel_flag: asyncio.Event | None = None,
) -> None:
    """Mirror of ``manual.py::_maybe_finalize_run`` + ``pipeline.py``'s
    completion path. Idempotent: a no-op on already-terminal runs."""
    async with session_factory() as s:
        run = await s.get(Run, run_id)
        if run is None or run.status in _TERMINAL_RUN:
            return
        ills = list(
            (await s.execute(select(Illustration).where(Illustration.run_id == run_id)))
            .scalars()
            .all()
        )
        manual_states = {
            IllustrationState.MANUAL_CHATTING,
            IllustrationState.MANUAL_GENERATING_PROMPTS,
            IllustrationState.MANUAL_RENDERING,
        }
        if any(i.state in manual_states for i in ills):
            return
        if not all(i.state in _TERMINAL_ILL for i in ills):
            return

        completed = sum(1 for i in ills if i.state == IllustrationState.COMPLETED)
        failed = sum(1 for i in ills if i.state == IllustrationState.FAILED)
        cancelled = sum(1 for i in ills if i.state == IllustrationState.CANCELLED)

        if cancelled > 0 and cancel_flag is not None and cancel_flag.is_set():
            await s.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status=RunStatus.CANCELLED,
                    completed_count=completed,
                    failed_count=failed,
                )
            )
            await s.commit()
            if event_bus is not None:
                await event_bus.publish("run_cancelled", {})
            return

        await s.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                status=RunStatus.COMPLETED,
                completed_count=completed,
                failed_count=failed,
            )
        )
        await s.commit()
        if event_bus is not None:
            await event_bus.publish("run_completed", {"completed": completed, "failed": failed})

        if completed == 0 and failed > 0 and cancelled == 0:
            failed_codes = {i.error_code for i in ills if i.state == IllustrationState.FAILED}
            if failed_codes and failed_codes.issubset(_INFRA_REFUND_CODES):
                try:
                    await refund_run_quota(s, run_id)
                except Exception:  # pragma: no cover
                    logger.exception("Quota refund failed for run %s", run_id)
