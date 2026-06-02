"""Unit tests for the orphan-resumer (§ 8.11.5).

Exercises ``_resume_one_render`` directly with a real in-memory SQLite
DB so the SQLAlchemy update/select side effects are observable, and
covers the classifier in ``_resume_one_run`` for the reap / user-alive
branches. RunPod is a stubbed object whose ``poll_existing_job``
returns bytes or raises one of the typed errors.
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.constants import (
    ERROR_CODE_OOM_REAPED,
    ERROR_CODE_RENDER_FAILED,
    ERROR_CODE_RENDER_QUEUE_TIMEOUT,
    ERROR_CODE_RENDER_TIMEOUT,
)
from app.db.models import (
    Base,
    Illustration,
    IllustrationState,
    ManualIllustrationSession,
    ManualMessageRole,
    Run,
    RunStatus,
    Session,
)
from app.db.repositories import ManualRepository
from app.orchestrator.events import EventBus
from app.orchestrator.resume import (
    _resume_one_render,
    _resume_one_run,
    resume_orphan_runs,
)
from app.services.runpod import RunPodError, RunPodQueueTimeoutError, RunPodTimeoutError
from app.services.storage import LocalImageStore

IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest_asyncio.fixture
async def engine_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(factory, *, ill_state, runpod_job_id="rp-job-1", manual_attempts=0):
    async with factory() as s:
        sess = Session()
        s.add(sess)
        await s.flush()
        run = Run(
            session_id=sess.id,
            status=RunStatus.RUNNING,
            source_language="en",
            topic_short="t",
            story_title="title",
            story_topic_description="d",
            story_blocks_json=json.dumps([]),
            style_guide_json=json.dumps(
                {
                    "overall_style_positive": "anime",
                    "overall_style_negative": "photo",
                    "character_lora": "",
                    "character_baseline_description": "",
                }
            ),
            illustration_count=1,
        )
        s.add(run)
        await s.flush()
        ill = Illustration(
            run_id=run.id,
            scene_index=0,
            scene_excerpt="x",
            paragraph_index=0,
            character_role="female",
            initial_concept="c",
            current_concept="c",
            current_prompts_json=json.dumps({"positive": "pos", "negative": "neg"}),
            state=ill_state,
            runpod_job_id=runpod_job_id,
            manual_attempts=manual_attempts,
        )
        s.add(ill)
        await s.commit()
        await s.refresh(run)
        await s.refresh(ill)
        return run.id, ill.id


def _stub_runpod(*, returns=None, raises=None):
    rp = AsyncMock()

    async def _poll(job_id, *, on_status_change=None):
        if raises is not None:
            raise raises
        return returns

    rp.poll_existing_job = AsyncMock(side_effect=_poll)
    return rp


@pytest.mark.asyncio
async def test_auto_completed_writes_canonical_and_transitions_completed(engine_factory, tmp_path):
    """Scope B: auto orphan recovery skips the evaluator and writes the
    recovered bytes straight to canonical, transitioning to COMPLETED."""
    run_id, ill_id = await _seed(engine_factory, ill_state=IllustrationState.RENDERING)
    rp = _stub_runpod(returns=IMAGE_BYTES)
    store = LocalImageStore(str(tmp_path))
    bus = EventBus()

    await _resume_one_render(
        session_factory=engine_factory,
        runpod=rp,
        image_store=store,
        event_bus=bus,
        cancel_flag=asyncio.Event(),
        illustration_id=ill_id,
        job_id="rp-job-1",
        is_manual=False,
    )

    async with engine_factory() as s:
        ill = await s.get(Illustration, ill_id)
        assert ill.state == IllustrationState.COMPLETED
        assert ill.runpod_job_id is None
        assert ill.image_path == f"runs/{run_id}/scene_0.png"
        # Canonical image hits disk.
        run = await s.get(Run, run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.completed_count == 1


@pytest.mark.asyncio
async def test_auto_queue_timeout_marks_failed_with_queue_timeout_code(engine_factory, tmp_path):
    """Auto path: RunPodQueueTimeoutError → FAILED with RENDER_QUEUE_TIMEOUT
    error_code (no retry — would lose FIFO position)."""
    _, ill_id = await _seed(engine_factory, ill_state=IllustrationState.RENDERING)
    rp = _stub_runpod(raises=RunPodQueueTimeoutError("stuck"))
    store = LocalImageStore(str(tmp_path))

    await _resume_one_render(
        session_factory=engine_factory,
        runpod=rp,
        image_store=store,
        event_bus=EventBus(),
        cancel_flag=asyncio.Event(),
        illustration_id=ill_id,
        job_id="rp-job-1",
        is_manual=False,
    )

    async with engine_factory() as s:
        ill = await s.get(Illustration, ill_id)
        assert ill.state == IllustrationState.FAILED
        assert ill.error_code == ERROR_CODE_RENDER_QUEUE_TIMEOUT
        assert ill.runpod_job_id is None


@pytest.mark.asyncio
async def test_auto_in_progress_timeout_marks_failed_with_timeout_code(engine_factory, tmp_path):
    _, ill_id = await _seed(engine_factory, ill_state=IllustrationState.RENDERING)
    rp = _stub_runpod(raises=RunPodTimeoutError("stalled"))
    await _resume_one_render(
        session_factory=engine_factory,
        runpod=rp,
        image_store=LocalImageStore(str(tmp_path)),
        event_bus=EventBus(),
        cancel_flag=asyncio.Event(),
        illustration_id=ill_id,
        job_id="rp-job-1",
        is_manual=False,
    )
    async with engine_factory() as s:
        ill = await s.get(Illustration, ill_id)
        assert ill.state == IllustrationState.FAILED
        assert ill.error_code == ERROR_CODE_RENDER_TIMEOUT


@pytest.mark.asyncio
async def test_auto_runpod_error_marks_failed_with_render_failed_code(engine_factory, tmp_path):
    _, ill_id = await _seed(engine_factory, ill_state=IllustrationState.RENDERING)
    rp = _stub_runpod(raises=RunPodError("FAILED on remote"))
    await _resume_one_render(
        session_factory=engine_factory,
        runpod=rp,
        image_store=LocalImageStore(str(tmp_path)),
        event_bus=EventBus(),
        cancel_flag=asyncio.Event(),
        illustration_id=ill_id,
        job_id="rp-job-1",
        is_manual=False,
    )
    async with engine_factory() as s:
        ill = await s.get(Illustration, ill_id)
        assert ill.state == IllustrationState.FAILED
        assert ill.error_code == ERROR_CODE_RENDER_FAILED


@pytest.mark.asyncio
async def test_manual_completed_writes_manual_image_and_returns_to_chat(engine_factory, tmp_path):
    """Manual orphan recovery writes manual_K, appends image message,
    flips sub_phase to feedback_gathering, returns to MANUAL_CHATTING."""
    run_id, ill_id = await _seed(
        engine_factory,
        ill_state=IllustrationState.MANUAL_RENDERING,
        manual_attempts=2,
    )
    # Seed a manual session in concept_design (pre-render state).
    async with engine_factory() as s:
        ms = ManualIllustrationSession(
            illustration_id=ill_id,
            sub_phase="concept_design",
            last_concept_candidate="some-candidate",
        )
        s.add(ms)
        await s.commit()

    rp = _stub_runpod(returns=IMAGE_BYTES)
    store = LocalImageStore(str(tmp_path))

    await _resume_one_render(
        session_factory=engine_factory,
        runpod=rp,
        image_store=store,
        event_bus=EventBus(),
        cancel_flag=asyncio.Event(),
        illustration_id=ill_id,
        job_id="rp-job-1",
        is_manual=True,
    )

    async with engine_factory() as s:
        ill = await s.get(Illustration, ill_id)
        assert ill.state == IllustrationState.MANUAL_CHATTING
        assert ill.runpod_job_id is None
        # Run NOT finalized — still has a non-terminal illustration.
        run = await s.get(Run, run_id)
        assert run.status == RunStatus.RUNNING

        repo = ManualRepository(s)
        ms = await repo.get_manual_session(ill_id)
        assert ms is not None
        assert ms.sub_phase == "feedback_gathering"
        assert ms.last_manual_image_path == f"runs/{run_id}/manual_0_2.png"

        msgs = await repo.get_messages(ill_id)
        image_msgs = [m for m in msgs if m.role == ManualMessageRole.IMAGE]
        assert len(image_msgs) == 1
        assert image_msgs[0].manual_attempt_index == 2
        assert image_msgs[0].positive_prompt == "pos"


@pytest.mark.asyncio
async def test_manual_queue_timeout_refunds_attempt_and_resets_sub_phase(engine_factory, tmp_path):
    """Manual queue timeout refunds the pre-incremented manual_attempts,
    resets sub_phase to concept_design, returns to MANUAL_CHATTING."""
    _, ill_id = await _seed(
        engine_factory,
        ill_state=IllustrationState.MANUAL_RENDERING,
        manual_attempts=3,
    )
    async with engine_factory() as s:
        s.add(
            ManualIllustrationSession(
                illustration_id=ill_id,
                sub_phase="concept_design",
                last_concept_candidate="held",
            )
        )
        await s.commit()

    rp = _stub_runpod(raises=RunPodQueueTimeoutError("stuck"))
    await _resume_one_render(
        session_factory=engine_factory,
        runpod=rp,
        image_store=LocalImageStore(str(tmp_path)),
        event_bus=EventBus(),
        cancel_flag=asyncio.Event(),
        illustration_id=ill_id,
        job_id="rp-job-1",
        is_manual=True,
    )

    async with engine_factory() as s:
        ill = await s.get(Illustration, ill_id)
        assert ill.state == IllustrationState.MANUAL_CHATTING
        assert ill.manual_attempts == 2  # refunded from 3
        assert ill.error_code == ERROR_CODE_RENDER_QUEUE_TIMEOUT
        assert ill.runpod_job_id is None
        ms = await ManualRepository(s).get_manual_session(ill_id)
        assert ms.sub_phase == "concept_design"
        assert ms.last_concept_candidate is None


@pytest.mark.asyncio
async def test_classifier_reaps_non_resumable_states(engine_factory, tmp_path):
    """An illustration mid-Agent call (no runpod_job_id, state not
    RENDERING/MANUAL_RENDERING) is reaped as OOM_REAPED — these are
    not resumable because the in-process Agent call is gone."""
    _, ill_id = await _seed(
        engine_factory,
        ill_state=IllustrationState.GENERATING_PROMPTS,
        runpod_job_id=None,
    )

    await _resume_one_run(
        run_id=(await _run_id_of(engine_factory, ill_id)),
        session_factory=engine_factory,
        runpod=_stub_runpod(returns=IMAGE_BYTES),
        image_store=LocalImageStore(str(tmp_path)),
        run_buses={},
        cancel_flags={},
    )

    async with engine_factory() as s:
        ill = await s.get(Illustration, ill_id)
        assert ill.state == IllustrationState.FAILED
        assert ill.error_code == ERROR_CODE_OOM_REAPED


@pytest.mark.asyncio
async def test_classifier_keeps_manual_chatting_run_running(engine_factory, tmp_path):
    """An illustration in MANUAL_CHATTING is user-alive — the run stays
    RUNNING so the next user interaction finalizes via manual.py."""
    run_id, _ = await _seed(
        engine_factory,
        ill_state=IllustrationState.MANUAL_CHATTING,
        runpod_job_id=None,
    )

    await _resume_one_run(
        run_id=run_id,
        session_factory=engine_factory,
        runpod=_stub_runpod(returns=IMAGE_BYTES),
        image_store=LocalImageStore(str(tmp_path)),
        run_buses={},
        cancel_flags={},
    )

    async with engine_factory() as s:
        run = await s.get(Run, run_id)
        assert run.status == RunStatus.RUNNING


@pytest.mark.asyncio
async def test_resume_orphan_runs_skips_when_no_running_runs(engine_factory, tmp_path):
    """No-op on a clean DB (no RUNNING runs)."""
    # Don't seed anything — DB is empty.
    await resume_orphan_runs(
        session_factory=engine_factory,
        runpod=_stub_runpod(returns=IMAGE_BYTES),
        image_store=LocalImageStore(str(tmp_path)),
        run_buses={},
        cancel_flags={},
    )
    # Just asserting no exception is raised.


@pytest.mark.asyncio
async def test_resume_one_render_publishes_runpod_status_events(engine_factory, tmp_path):
    """The on_status_change wired by the resumer must publish
    illustration_runpod_status SSE events so the UI label can flip."""
    _, ill_id = await _seed(engine_factory, ill_state=IllustrationState.RENDERING)

    rp = AsyncMock()

    async def _poll(job_id, *, on_status_change=None):
        if on_status_change is not None:
            await on_status_change("IN_QUEUE")
            await on_status_change("IN_PROGRESS")
        return IMAGE_BYTES

    rp.poll_existing_job = AsyncMock(side_effect=_poll)

    events: list[tuple[str, dict]] = []

    class _CapturingBus(EventBus):
        async def publish(self, event_type, data):  # type: ignore[override]
            events.append((event_type, data))
            await super().publish(event_type, data)

    cbus = _CapturingBus()

    await _resume_one_render(
        session_factory=engine_factory,
        runpod=rp,
        image_store=LocalImageStore(str(tmp_path)),
        event_bus=cbus,
        cancel_flag=asyncio.Event(),
        illustration_id=ill_id,
        job_id="rp-job-1",
        is_manual=False,
    )

    status_events = [e for e in events if e[0] == "illustration_runpod_status"]
    assert [e[1]["runpod_status"] for e in status_events] == ["IN_QUEUE", "IN_PROGRESS"]


async def _run_id_of(factory, ill_id):
    async with factory() as s:
        ill = await s.get(Illustration, ill_id)
        return ill.run_id
