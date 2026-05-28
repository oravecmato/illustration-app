"""Unit tests for ManualService (§ 6A).

Uses a real in-memory SQLite + aiosqlite database so the SQLAlchemy
side-effects (id/timestamp population) work without HTTP-layer mocks.
Claude and RunPod are AsyncMock instances.
"""

import asyncio
import json
import os
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.constants import MAX_MANUAL_ATTEMPTS
from app.db.models import (
    Base,
    Illustration,
    IllustrationState,
    ManualMessageRole,
    Run,
    RunStatus,
    Session,
)
from app.db.repositories import ManualRepository, RunRepository
from app.schemas.claude import (
    GeneratePromptsResponse,
    ManualConceptResponse,
    ManualRevisePromptsResponse,
    StyleGuide,
)
from app.services.manual import ManualService, ManualServiceError

STYLE_GUIDE = StyleGuide(
    overall_style_positive="watercolor",
    overall_style_negative="photorealistic",
    character_lora="",
    character_baseline_description="A young girl",
)

CHARACTER_CONFIG = {
    "female": {
        "display_name": "Kyoka Jiro",
        "lora_filename": "jirou_v1.safetensors",
        "trigger_tags": "jirou kyouka, short hair",
        "outfit_baseline": "school uniform",
    },
}

IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest_asyncio.fixture
async def db_session():
    """Real in-memory SQLite session — each test gets a fresh engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_run(db_session):
    sess = Session()
    db_session.add(sess)
    await db_session.flush()
    run = Run(
        session_id=sess.id,
        status=RunStatus.RUNNING,
        source_language="en",
        topic_short="Test",
        story_title="Test Story",
        story_topic_description="A test",
        story_blocks_json=json.dumps([{"type": "paragraph", "text": "Once upon a time."}]),
        style_guide_json=json.dumps(STYLE_GUIDE.model_dump()),
        illustration_count=1,
    )
    db_session.add(run)
    await db_session.flush()
    ill = Illustration(
        run_id=run.id,
        scene_index=0,
        scene_excerpt="Once upon a time.",
        paragraph_index=0,
        character_role="female",
        initial_concept="A girl on a stage",
        current_concept="A girl on a stage",
        state=IllustrationState.MANUAL_CHATTING,  # post-exhaustion state
    )
    db_session.add(ill)
    await db_session.commit()
    await db_session.refresh(ill)
    return run, ill


def _make_service(db_session, *, claude=None, runpod=None, cancel_flag=None, tmp_path=None):
    run_repo = RunRepository(db_session)
    manual_repo = ManualRepository(db_session)
    output_dir = str(tmp_path) if tmp_path else "/tmp"
    return ManualService(
        run_repo=run_repo,
        manual_repo=manual_repo,
        claude=claude or AsyncMock(),
        runpod=runpod or AsyncMock(),
        event_bus=None,  # exercise the no-bus path
        cancel_flag=cancel_flag,
        workflow_template={
            "node": {
                "inputs": {
                    "lora": "CHARACTER_LORA",
                    "positive": "POSITIVE_PROMPT",
                    "negative": "NEGATIVE_PROMPT",
                    "style_pos": "STYLE_POSITIVE_PROMPT",
                    "style_neg": "STYLE_NEGATIVE_PROMPT",
                }
            }
        },
        output_dir=output_dir,
        character_config=CHARACTER_CONFIG,
    )


@pytest.mark.asyncio
async def test_open_manual_flow_seeds_session_and_welcome(db_session):
    _, ill = await _seed_run(db_session)
    # Reset state — open_manual_flow is the canonical entry point.
    ill.state = IllustrationState.RENDERING
    await db_session.commit()

    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")

    assert ill.state == IllustrationState.MANUAL_CHATTING
    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms is not None
    msgs = await ManualRepository(db_session).get_messages(ill.id)
    assert len(msgs) == 1
    assert msgs[0].role == ManualMessageRole.ASSISTANT
    assert msgs[0].content  # non-empty welcome


@pytest.mark.asyncio
async def test_post_message_gathering_phase_only_appends_bubbles(db_session):
    _, ill = await _seed_run(db_session)
    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="gathering",
            reply="Tell me more — what should the character be feeling?",
        )
    )
    service = _make_service(db_session, claude=claude)
    # Open first so the welcome bubble exists.
    await service.open_manual_flow(ill, source_language="en")

    await service.post_message(ill, "Make her brave")

    msgs = await ManualRepository(db_session).get_messages(ill.id)
    # welcome + user + assistant
    assert len(msgs) == 3
    assert msgs[1].role == ManualMessageRole.USER
    assert msgs[1].content == "Make her brave"
    assert msgs[2].role == ManualMessageRole.ASSISTANT
    assert ill.state == IllustrationState.MANUAL_CHATTING
    assert ill.manual_attempts == 0  # no render happened


@pytest.mark.asyncio
async def test_post_message_invalid_state_rejected(db_session):
    _, ill = await _seed_run(db_session)
    ill.state = IllustrationState.COMPLETED
    await db_session.commit()
    service = _make_service(db_session)
    with pytest.raises(ManualServiceError) as exc:
        await service.post_message(ill, "Hi")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_post_message_empty_rejected(db_session):
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    with pytest.raises(ManualServiceError) as exc:
        await service.post_message(ill, "   ")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_post_message_cancel_flag_rejected(db_session):
    _, ill = await _seed_run(db_session)
    cancel = asyncio.Event()
    cancel.set()
    service = _make_service(db_session, cancel_flag=cancel)
    with pytest.raises(ManualServiceError) as exc:
        await service.post_message(ill, "Hi")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_post_message_confirmed_demoted_without_prior_awaiting(db_session):
    """`concept_confirmed` without a prior `last_concept_candidate` is demoted."""
    _, ill = await _seed_run(db_session)
    claude = AsyncMock()
    # Returns concept_confirmed straight away — should be demoted because
    # the manual session has no `last_concept_candidate` recorded yet.
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Going for it.",
            concept_candidate="A girl on a stage",
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service = _make_service(db_session, claude=claude, runpod=runpod)
    # Skip welcome — no prior awaiting_concept_confirmation means demotion.
    await service.post_message(ill, "Yes go")

    # No render happened.
    runpod.run_workflow.assert_not_called()
    assert ill.manual_attempts == 0
    assert ill.state == IllustrationState.MANUAL_CHATTING


@pytest.mark.asyncio
async def test_accept_without_image_raises(db_session):
    _, ill = await _seed_run(db_session)
    # Set manual_attempts to satisfy the schema guard inside post_message.
    ill.manual_attempts = 1
    await db_session.commit()
    # Open so there's an assistant turn already.
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="accepted",
            reply="Great!",
        )
    )
    service.claude = claude

    with pytest.raises(ManualServiceError) as exc:
        await service.post_message(ill, "I love it")
    # Post-§ 6A.10 refactor: PHASE_ACCEPTED delegates to accept_attempt(K),
    # which requires an actual image-row in `manual_messages`. The
    # artificial manual_attempts=1 with no image-row surfaces as
    # ATTEMPT_NOT_FOUND (was NO_MANUAL_IMAGE under the path-based check).
    assert exc.value.code == "ATTEMPT_NOT_FOUND"


@pytest.mark.asyncio
async def test_confirmed_render_path_increments_attempts(db_session, tmp_path):
    _, ill = await _seed_run(db_session)
    # Pre-seed a prior assistant message + last_concept_candidate so the
    # verbatim handoff invariant is satisfied.
    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(ms, last_concept_candidate="A girl on a stage")

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Going for it.",
            concept_candidate="A girl on a stage",
        )
    )
    claude.generate_prompts = AsyncMock(
        return_value=GeneratePromptsResponse(
            workflow="single-lora",
            positive="brave girl, stage",
            negative="blurry",
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes, that's perfect")

    assert ill.manual_attempts == 1
    assert ill.state == IllustrationState.MANUAL_CHATTING
    runpod.run_workflow.assert_called_once()
    # Image file written to tmp_path/runs/<run_id>/manual_0_1.png
    expected_dir = os.path.join(str(tmp_path), "runs", ill.run_id)
    files = os.listdir(expected_dir)
    assert any(f.startswith("manual_0_1") for f in files)


@pytest.mark.asyncio
async def test_budget_exhaustion_marks_failed(db_session, tmp_path):
    _, ill = await _seed_run(db_session)
    ill.manual_attempts = MAX_MANUAL_ATTEMPTS - 1
    await db_session.commit()

    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(ms, last_concept_candidate="A girl on a stage")

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Last attempt.",
            concept_candidate="A girl on a stage",
        )
    )
    claude.generate_prompts = AsyncMock(
        return_value=GeneratePromptsResponse(
            workflow="single-lora",
            positive="brave girl, stage",
            negative="blurry",
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes, final attempt")

    assert ill.manual_attempts == MAX_MANUAL_ATTEMPTS
    assert ill.state == IllustrationState.FAILED
    # Run should also be finalized since this was the only illustration.
    run = await RunRepository(db_session).get_run(ill.run_id)
    assert run.status == RunStatus.COMPLETED  # 0 completed, 1 failed, none cancelled


# ── New § 6A.4 service paths ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_awaiting_concept_confirmation_persists_candidate(db_session):
    """When Agent 6 returns `awaiting_concept_confirmation`, the candidate
    is persisted to ms.last_concept_candidate for the next turn's verbatim
    check."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")

    candidate = "A girl on a stage, eyes closed."
    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="awaiting_concept_confirmation",
            reply=f"Shall I go with: {candidate}",
            concept_candidate=candidate,
        )
    )
    service.claude = claude

    await service.post_message(ill, "Yes please propose one")

    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.last_concept_candidate == candidate
    assert ms.sub_phase == "concept_design"
    assert ill.manual_attempts == 0


@pytest.mark.asyncio
async def test_concept_confirmed_verbatim_mismatch_demoted(db_session):
    """If `concept_confirmed.concept_candidate` does not match the previously
    persisted `last_concept_candidate` byte-for-byte, the phase is demoted
    to `awaiting_concept_confirmation` and no render happens."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(ms, last_concept_candidate="A girl on a stage")

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Going for it.",
            # Drifted by a single character — should fail verbatim check.
            concept_candidate="A girl on a stage.",
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes go")

    runpod.run_workflow.assert_not_called()
    assert ill.manual_attempts == 0
    assert ill.state == IllustrationState.MANUAL_CHATTING


@pytest.mark.asyncio
async def test_concept_confirmed_render_flips_sub_phase_to_feedback(db_session, tmp_path):
    """A successful concept_confirmed render must set sub_phase to
    `feedback_gathering` and persist `last_agreed_concept`."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    candidate = "A girl on a stage"
    await manual_repo.update_manual_session(ms, last_concept_candidate=candidate)

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Going for it.",
            concept_candidate=candidate,
        )
    )
    claude.generate_prompts = AsyncMock(
        return_value=GeneratePromptsResponse(
            workflow="single-lora", positive="brave girl, stage", negative="blurry"
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes please")

    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.sub_phase == "feedback_gathering"
    assert ms.last_agreed_concept == candidate
    # last_concept_candidate is cleared after dispatching the render.
    assert ms.last_concept_candidate is None
    assert ill.manual_attempts == 1


@pytest.mark.asyncio
async def test_feedback_gathering_phase_only_appends_bubbles(db_session, tmp_path):
    """In `feedback_gathering` sub-phase, plain `gathering_feedback` phase
    should not dispatch Agent 7 / RunPod."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(
        ms,
        sub_phase="feedback_gathering",
        last_agreed_concept="A girl on a stage",
    )

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="gathering_feedback",
            reply="Tell me what you'd like to change.",
        )
    )
    claude.manual_revise_prompts = AsyncMock()
    runpod = AsyncMock()
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "It was OK but too dark")

    claude.manual_revise_prompts.assert_not_called()
    runpod.run_workflow.assert_not_called()
    assert ill.manual_attempts == 0


@pytest.mark.asyncio
async def test_feedback_confirmed_dispatches_agent7_and_increments(db_session, tmp_path):
    """`feedback_confirmed` in `feedback_gathering` sub-phase must invoke
    Agent 7 + RunPod and increment manual_attempts."""
    _, ill = await _seed_run(db_session)
    # Pre-seed: one prior manual render so sub_phase=feedback_gathering and
    # current_prompts_json exists.
    ill.manual_attempts = 1
    ill.current_prompts_json = json.dumps(
        {"workflow": "single-lora", "positive": "brave girl", "negative": "blurry"}
    )
    ill.current_workflow = "single-lora.json"
    await db_session.commit()

    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(
        ms,
        sub_phase="feedback_gathering",
        last_agreed_concept="A girl on a stage",
    )

    # Two assistant turns + one image row are required for
    # _has_recent_assistant_phase to accept feedback_confirmed.
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.IMAGE,
        content="",
        image_url="/static/runs/x/manual_0_1.png",
        manual_attempt_index=1,
    )
    # Canned review-prompt bubble (first post-image assistant turn).
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.ASSISTANT,
        content="What did you think?",
    )
    # User feedback
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.USER,
        content="Too dark, make it brighter",
    )
    # Agent's awaiting_feedback_confirmation turn (second post-image assistant).
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.ASSISTANT,
        content="So you'd like a brighter version — shall I render?",
    )

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="feedback_confirmed",
            reply="On it.",
        )
    )
    claude.manual_revise_prompts = AsyncMock(
        return_value=ManualRevisePromptsResponse(
            positive="brave girl, brighter lighting",
            negative="blurry, dark",
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes please render")

    claude.manual_revise_prompts.assert_called_once()
    # last_agreed_concept should appear in the Agent 7 call args.
    kwargs = claude.manual_revise_prompts.call_args.kwargs
    assert kwargs["last_agreed_concept"] == "A girl on a stage"
    assert "Too dark" in kwargs["user_feedback"]
    runpod.run_workflow.assert_called_once()
    assert ill.manual_attempts == 2
    # Sub-phase stays in feedback_gathering after a successful render.
    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.sub_phase == "feedback_gathering"


@pytest.mark.asyncio
async def test_restart_concept_resets_session(db_session):
    """`restart_concept` clears agreed/candidate concepts and flips sub_phase
    back to `concept_design`. No render is dispatched."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(
        ms,
        sub_phase="feedback_gathering",
        last_agreed_concept="A girl on a stage",
        last_concept_candidate="A girl on a stage",
        last_manual_image_path="runs/x/manual_0_1.png",
    )

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="restart_concept",
            reply="Sure, let's start over with a fresh concept.",
        )
    )
    runpod = AsyncMock()
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Let's start over with something different")

    runpod.run_workflow.assert_not_called()
    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.sub_phase == "concept_design"
    assert ms.last_agreed_concept is None
    assert ms.last_concept_candidate is None
    assert ms.last_manual_image_path is None


@pytest.mark.asyncio
async def test_feedback_phase_during_concept_design_demoted(db_session):
    """Server demotes feedback-side phases to `gathering` when the session
    is still in `concept_design`."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="feedback_confirmed",
            reply="On it.",
        )
    )
    runpod = AsyncMock()
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Render now")

    runpod.run_workflow.assert_not_called()
    assert ill.manual_attempts == 0
    assert ill.state == IllustrationState.MANUAL_CHATTING
    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.sub_phase == "concept_design"


@pytest.mark.asyncio
async def test_concept_phase_during_feedback_gathering_demoted(db_session):
    """Server demotes concept-side phases to `gathering_feedback` when the
    session is in `feedback_gathering` (model must use restart_concept to
    leave that sub-phase)."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(
        ms,
        sub_phase="feedback_gathering",
        last_agreed_concept="A girl on a stage",
        last_concept_candidate="A new concept",
    )

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Going for it.",
            concept_candidate="A new concept",
        )
    )
    runpod = AsyncMock()
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes")

    runpod.run_workflow.assert_not_called()
    assert ill.manual_attempts == 0
    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.sub_phase == "feedback_gathering"


# ── prompting_notes (§ 6A.2 rule #12) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompting_notes_update_persisted(db_session):
    """When Agent 6 returns a non-null `prompting_notes_update`, the server
    fully overwrites `manual_illustration_sessions.prompting_notes`."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")

    new_notes = "Robot renders as mist. Add mecha, metallic plating, hard edges."
    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="gathering_feedback",
            reply="Got it.",
            prompting_notes_update=new_notes,
        )
    )
    service.claude = claude
    # Put session into feedback sub-phase so gathering_feedback is legal.
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(
        ms, sub_phase="feedback_gathering", last_agreed_concept="A girl on a stage"
    )

    await service.post_message(ill, "It looks like a ghost")

    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.prompting_notes == new_notes


@pytest.mark.asyncio
async def test_prompting_notes_update_overwrites_prior(db_session):
    """A new non-null update fully replaces any prior memo — no merging."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(
        ms,
        sub_phase="feedback_gathering",
        last_agreed_concept="A girl on a stage",
        prompting_notes="OLD notes about robots.",
    )

    new_notes = "NEW notes: companion drift; anchor with on shoulder."
    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="gathering_feedback",
            reply="Got it.",
            prompting_notes_update=new_notes,
        )
    )
    service.claude = claude

    await service.post_message(ill, "The cat is off the shoulder")

    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.prompting_notes == new_notes
    assert "OLD" not in ms.prompting_notes


@pytest.mark.asyncio
async def test_prompting_notes_untouched_when_update_omitted(db_session):
    """When Agent 6 omits `prompting_notes_update` (null), the stored memo
    is left intact."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    prior = "Existing renderer hints memo."
    await manual_repo.update_manual_session(ms, prompting_notes=prior)

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="gathering",
            reply="Tell me more.",
            # No prompting_notes_update — defaults to None.
        )
    )
    service.claude = claude

    await service.post_message(ill, "Hmm")

    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.prompting_notes == prior


@pytest.mark.asyncio
async def test_restart_concept_preserves_prompting_notes(db_session):
    """`restart_concept` must NOT clear `prompting_notes` (§ 6A.4 step 6.1,
    § 6A.2 rule #12). The renderer-blind-spot memo transfers to the fresh
    concept."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    memo = "Robot renders as mist. Add mecha, hard edges."
    await manual_repo.update_manual_session(
        ms,
        sub_phase="feedback_gathering",
        last_agreed_concept="A girl on a stage",
        last_concept_candidate="A girl on a stage",
        last_manual_image_path="runs/x/manual_0_1.png",
        prompting_notes=memo,
    )

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="restart_concept",
            reply="OK, fresh idea.",
        )
    )
    service.claude = claude

    await service.post_message(ill, "Let's try something completely different")

    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    # Concept references are cleared…
    assert ms.last_agreed_concept is None
    assert ms.last_concept_candidate is None
    assert ms.last_manual_image_path is None
    assert ms.sub_phase == "concept_design"
    # …but the prompt-engineering memo persists.
    assert ms.prompting_notes == memo


@pytest.mark.asyncio
async def test_concept_confirmed_dispatch_passes_prompting_notes_to_agent1(db_session, tmp_path):
    """Agent 1 (generate_prompts) on the concept_confirmed render path
    receives the current `prompting_notes` as input."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    memo = "Use solid body tags; suppress ghost/mist negatives."
    await manual_repo.update_manual_session(
        ms,
        last_concept_candidate="A girl on a stage",
        prompting_notes=memo,
    )

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Going for it.",
            concept_candidate="A girl on a stage",
        )
    )
    claude.generate_prompts = AsyncMock(
        return_value=GeneratePromptsResponse(
            workflow="single-lora", positive="brave girl", negative="blurry"
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes please render")

    claude.generate_prompts.assert_called_once()
    kwargs = claude.generate_prompts.call_args.kwargs
    assert kwargs["prompting_notes"] == memo


@pytest.mark.asyncio
async def test_feedback_confirmed_dispatch_passes_prompting_notes_to_agent7(db_session, tmp_path):
    """Agent 7 (manual_revise_prompts) on the feedback_confirmed path
    receives the current `prompting_notes` as input."""
    _, ill = await _seed_run(db_session)
    ill.manual_attempts = 1
    ill.current_prompts_json = json.dumps(
        {"workflow": "single-lora", "positive": "brave girl", "negative": "blurry"}
    )
    ill.current_workflow = "single-lora.json"
    await db_session.commit()

    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    memo = "Renderer tends to anthropomorphise the cat — strengthen anti-anthro negs."
    await manual_repo.update_manual_session(
        ms,
        sub_phase="feedback_gathering",
        last_agreed_concept="A girl on a stage",
        prompting_notes=memo,
    )
    # Seed image + assistant turns so feedback_confirmed survives the guard.
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.IMAGE,
        content="",
        image_url="/static/runs/x/manual_0_1.png",
        manual_attempt_index=1,
    )
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.ASSISTANT,
        content="What did you think?",
    )
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.USER,
        content="Too dark",
    )
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.ASSISTANT,
        content="Render brighter?",
    )

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="feedback_confirmed",
            reply="On it.",
        )
    )
    claude.manual_revise_prompts = AsyncMock(
        return_value=ManualRevisePromptsResponse(
            positive="brave girl, bright", negative="blurry, dark"
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes")

    claude.manual_revise_prompts.assert_called_once()
    kwargs = claude.manual_revise_prompts.call_args.kwargs
    assert kwargs["prompting_notes"] == memo


@pytest.mark.asyncio
async def test_manual_concept_call_passes_current_prompting_notes(db_session):
    """Every Agent 6 invocation receives the current stored `prompting_notes`
    as input (so the model can decide whether to extend or rewrite)."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    memo = "Prior memo content."
    await manual_repo.update_manual_session(ms, prompting_notes=memo)

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(phase="gathering", reply="OK.")
    )
    service.claude = claude

    await service.post_message(ill, "Hello")

    claude.manual_concept.assert_called_once()
    kwargs = claude.manual_concept.call_args.kwargs
    assert kwargs["prompting_notes"] == memo


# ── § 6A.9 start_regeneration ───────────────────────────────────────────────


async def _seed_completed(db_session):
    """Seed a Run with a COMPLETED illustration carrying an existing
    manual session (prior accepted manual flow)."""
    run, ill = await _seed_run(db_session)
    ill.state = IllustrationState.COMPLETED
    ill.image_path = f"runs/{run.id}/scene_0.png"
    ill.manual_attempts = 2
    await db_session.commit()
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.create_manual_session(ill.id)
    await manual_repo.update_manual_session(
        ms,
        sub_phase="feedback_gathering",
        last_agreed_concept="A girl on a stage",
        last_concept_candidate=None,
        last_manual_image_path=f"runs/{run.id}/manual_0_2.png",
        prompting_notes="Renderer fuses fingers — emphasise hand anatomy.",
    )
    # Seed a few prior messages (history accumulates across regens).
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.ASSISTANT,
        content="Welcome bubble from prior flow",
    )
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.USER,
        content="Make her brave",
    )
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.IMAGE,
        content="",
        image_url="/static/runs/x/manual_0_1.png",
        manual_attempt_index=1,
    )
    return run, ill


@pytest.mark.asyncio
async def test_regenerate_flips_state_and_resets_session(db_session):
    _, ill = await _seed_completed(db_session)
    prior_image_path = ill.image_path
    prior_attempts = ill.manual_attempts

    service = _make_service(db_session)
    await service.start_regeneration(ill, source_language="en")

    assert ill.state == IllustrationState.MANUAL_CHATTING
    # image_path is preserved (UI fallback)
    assert ill.image_path == prior_image_path
    # manual_attempts is cumulative — not reset
    assert ill.manual_attempts == prior_attempts

    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms.sub_phase == "concept_design"
    assert ms.last_agreed_concept is None
    assert ms.last_concept_candidate is None
    assert ms.last_manual_image_path is None
    # prompting_notes preserved
    assert ms.prompting_notes == "Renderer fuses fingers — emphasise hand anatomy."


@pytest.mark.asyncio
async def test_regenerate_preserves_prior_messages_and_appends_welcome(db_session):
    _, ill = await _seed_completed(db_session)
    prior_msgs = await ManualRepository(db_session).get_messages(ill.id)
    prior_count = len(prior_msgs)

    service = _make_service(db_session)
    await service.start_regeneration(ill, source_language="sk")

    msgs = await ManualRepository(db_session).get_messages(ill.id)
    assert len(msgs) == prior_count + 1
    welcome = msgs[-1]
    assert welcome.role == ManualMessageRole.ASSISTANT
    # Localized SK welcome contains the substring "Ideme znova".
    assert "Ideme znova" in welcome.content


@pytest.mark.asyncio
async def test_regenerate_rejects_non_completed_state(db_session):
    _, ill = await _seed_run(db_session)  # state = MANUAL_CHATTING
    service = _make_service(db_session)
    with pytest.raises(ManualServiceError) as exc:
        await service.start_regeneration(ill, source_language="en")
    assert exc.value.code == "INVALID_STATE"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_regenerate_rejects_exhausted_budget(db_session):
    _, ill = await _seed_completed(db_session)
    ill.manual_attempts = MAX_MANUAL_ATTEMPTS
    await db_session.commit()
    service = _make_service(db_session)
    with pytest.raises(ManualServiceError) as exc:
        await service.start_regeneration(ill, source_language="en")
    assert exc.value.code == "BUDGET_EXHAUSTED"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_regenerate_cancel_flag_rejected(db_session):
    _, ill = await _seed_completed(db_session)
    cancel = asyncio.Event()
    cancel.set()
    service = _make_service(db_session, cancel_flag=cancel)
    with pytest.raises(ManualServiceError) as exc:
        await service.start_regeneration(ill, source_language="en")
    assert exc.value.code == "RUN_CANCELLED"


@pytest.mark.asyncio
async def test_regenerate_creates_session_if_missing(db_session):
    """A never-manually-edited COMPLETED illustration (auto-pipeline result)
    has no ManualIllustrationSession row. Regenerate creates one."""
    run, ill = await _seed_run(db_session)
    ill.state = IllustrationState.COMPLETED
    ill.image_path = f"runs/{run.id}/scene_0.png"
    ill.manual_attempts = 0
    await db_session.commit()
    # Sanity: no manual session yet.
    assert await ManualRepository(db_session).get_manual_session(ill.id) is None

    service = _make_service(db_session)
    await service.start_regeneration(ill, source_language="en")

    ms = await ManualRepository(db_session).get_manual_session(ill.id)
    assert ms is not None
    assert ms.sub_phase == "concept_design"
    assert ms.prompting_notes is None  # nothing carried over (never had one)


@pytest.mark.asyncio
async def test_regenerate_publishes_sse_with_reason(db_session):
    _, ill = await _seed_completed(db_session)

    published: list[tuple[str, dict]] = []

    class _Bus:
        async def publish(self, event_type, payload):
            published.append((event_type, payload))

    service = _make_service(db_session)
    service.event_bus = _Bus()
    await service.start_regeneration(ill, source_language="en")

    event_types = [e for e, _ in published]
    assert "illustration_state" in event_types
    assert "illustration_manual_started" in event_types
    started = next(p for e, p in published if e == "illustration_manual_started")
    assert started["reason"] == "regeneration"
    assert started["sub_phase"] == "concept_design"
    assert "welcome_message" in started


# ── § 6A.10 interactive image cards ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_render_populates_per_attempt_columns(db_session, tmp_path):
    """§ 6A.10: the image-row written by `_dispatch_render` carries the
    concept and prompts that produced it."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    candidate = "A girl on a stage"
    await manual_repo.update_manual_session(ms, last_concept_candidate=candidate)

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Going for it.",
            concept_candidate=candidate,
        )
    )
    claude.generate_prompts = AsyncMock(
        return_value=GeneratePromptsResponse(
            workflow="single-lora",
            positive="brave girl, stage",
            negative="blurry, bad anatomy",
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes please render")

    rows = await manual_repo.get_messages(ill.id)
    image_rows = [r for r in rows if r.role == ManualMessageRole.IMAGE]
    assert len(image_rows) == 1
    img = image_rows[0]
    assert img.concept_used == candidate
    assert img.positive_prompt == "brave girl, stage"
    assert img.negative_prompt == "blurry, bad anatomy"


@pytest.mark.asyncio
async def test_dispatch_render_no_longer_appends_review_bubble(db_session, tmp_path):
    """§ 6A.10: no canned MANUAL_REVIEW_PROMPT assistant turn is appended
    after a manual render. The transcript ends with the image row."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(ms, last_concept_candidate="A girl on a stage")

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Going for it.",
            concept_candidate="A girl on a stage",
        )
    )
    claude.generate_prompts = AsyncMock(
        return_value=GeneratePromptsResponse(
            workflow="single-lora", positive="brave girl", negative="blurry"
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes")

    rows = await manual_repo.get_messages(ill.id)
    # Last row must be the image — no assistant "I can't see…" bubble
    # appended after it.
    assert rows[-1].role == ManualMessageRole.IMAGE
    for row in rows:
        assert "can't see" not in row.content
        assert "nevidím" not in row.content


@pytest.mark.asyncio
async def test_manual_image_rendered_payload_carries_provenance(db_session, tmp_path):
    """§ 6A.10: manual_image_rendered SSE payload includes concept + prompts
    and no longer carries review_message."""
    _, ill = await _seed_run(db_session)
    service = _make_service(db_session, tmp_path=tmp_path)
    await service.open_manual_flow(ill, source_language="en")
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.get_manual_session(ill.id)
    await manual_repo.update_manual_session(ms, last_concept_candidate="A girl on a stage")

    published: list[tuple[str, dict]] = []

    class _Bus:
        async def publish(self, event_type, payload):
            published.append((event_type, payload))

    service.event_bus = _Bus()

    claude = AsyncMock()
    claude.manual_concept = AsyncMock(
        return_value=ManualConceptResponse(
            phase="concept_confirmed",
            reply="Going for it.",
            concept_candidate="A girl on a stage",
        )
    )
    claude.generate_prompts = AsyncMock(
        return_value=GeneratePromptsResponse(
            workflow="single-lora", positive="brave girl", negative="blurry"
        )
    )
    runpod = AsyncMock()
    runpod.run_workflow = AsyncMock(return_value=IMAGE_BYTES)
    service.claude = claude
    service.runpod = runpod

    await service.post_message(ill, "Yes")

    rendered = next(p for e, p in published if e == "manual_image_rendered")
    assert rendered["concept_used"] == "A girl on a stage"
    assert rendered["positive_prompt"] == "brave girl"
    assert rendered["negative_prompt"] == "blurry"
    assert "review_message" not in rendered


async def _seed_with_image(db_session, *, attempt_index: int = 1, tmp_path=None):
    """Seed a MANUAL_CHATTING illustration with a real on-disk attempt image.

    Returns (run, illustration, output_dir, manual_repo).
    """
    run, ill = await _seed_run(db_session)
    ill.manual_attempts = attempt_index
    await db_session.commit()
    manual_repo = ManualRepository(db_session)
    ms = await manual_repo.create_manual_session(ill.id)
    await manual_repo.update_manual_session(
        ms,
        sub_phase="feedback_gathering",
        last_agreed_concept="A girl on a stage",
        last_manual_image_path=f"runs/{ill.run_id}/manual_0_{attempt_index}.png",
    )
    output_dir = str(tmp_path) if tmp_path is not None else "/tmp"
    # Write the deterministic source file so accept_attempt can copy it.
    src_dir = os.path.join(output_dir, "runs", ill.run_id)
    os.makedirs(src_dir, exist_ok=True)
    src_path = os.path.join(src_dir, f"manual_0_{attempt_index}.png")
    with open(src_path, "wb") as f:
        f.write(IMAGE_BYTES)
    await manual_repo.add_message(
        illustration_id=ill.id,
        role=ManualMessageRole.IMAGE,
        content="",
        image_url=f"/static/runs/{ill.run_id}/manual_0_{attempt_index}.png",
        manual_attempt_index=attempt_index,
        concept_used="A girl on a stage",
        positive_prompt="brave girl, stage",
        negative_prompt="blurry",
    )
    return run, ill, output_dir, manual_repo


@pytest.mark.asyncio
async def test_accept_attempt_promotes_latest(db_session, tmp_path):
    """`accept_attempt(K=latest)` copies temp → canonical and flips state to
    COMPLETED, emitting the SSE trio."""
    _, ill, output_dir, manual_repo = await _seed_with_image(
        db_session, attempt_index=1, tmp_path=tmp_path
    )
    published: list[tuple[str, dict]] = []

    class _Bus:
        async def publish(self, event_type, payload):
            published.append((event_type, payload))

    service = _make_service(db_session, tmp_path=tmp_path)
    service.event_bus = _Bus()

    await service.accept_attempt(ill, 1)

    assert ill.state == IllustrationState.COMPLETED
    assert ill.image_path == f"runs/{ill.run_id}/scene_0.png"
    # Canonical file exists on disk.
    canonical = os.path.join(output_dir, "runs", ill.run_id, "scene_0.png")
    assert os.path.exists(canonical)
    event_types = [e for e, _ in published]
    assert "illustration_state" in event_types
    assert "illustration_completed" in event_types
    ended = next(p for e, p in published if e == "illustration_manual_ended")
    assert ended["outcome"] == "completed"


@pytest.mark.asyncio
async def test_accept_attempt_promotes_older(db_session, tmp_path):
    """`accept_attempt(K=older)` works on a prior attempt (image row + file
    both exist for K=1 even though manual_attempts has progressed to 3)."""
    _, ill, output_dir, manual_repo = await _seed_with_image(
        db_session, attempt_index=1, tmp_path=tmp_path
    )
    # Advance the budget — but the K=1 image row + file are still present.
    ill.manual_attempts = 3
    await db_session.commit()

    service = _make_service(db_session, tmp_path=tmp_path)
    await service.accept_attempt(ill, 1)

    assert ill.state == IllustrationState.COMPLETED
    canonical = os.path.join(output_dir, "runs", ill.run_id, "scene_0.png")
    assert os.path.exists(canonical)


@pytest.mark.asyncio
async def test_accept_attempt_updates_current_concept(db_session, tmp_path):
    """When the accepted attempt's image row has `concept_used`, the
    illustration's `current_concept` is updated to match — so the
    IllustrationCard popover shows the right concept."""
    _, ill, _, _ = await _seed_with_image(db_session, attempt_index=1, tmp_path=tmp_path)
    # Drift the live concept; accept_attempt must restore it from the row.
    ill.current_concept = "Drifted concept (e.g. set by a later iteration)"
    await db_session.commit()

    service = _make_service(db_session, tmp_path=tmp_path)
    await service.accept_attempt(ill, 1)
    assert ill.current_concept == "A girl on a stage"


@pytest.mark.asyncio
async def test_accept_attempt_invalid_state(db_session, tmp_path):
    _, ill, _, _ = await _seed_with_image(db_session, attempt_index=1, tmp_path=tmp_path)
    ill.state = IllustrationState.COMPLETED  # not a MANUAL_* state
    await db_session.commit()

    service = _make_service(db_session, tmp_path=tmp_path)
    with pytest.raises(ManualServiceError) as exc:
        await service.accept_attempt(ill, 1)
    assert exc.value.code == "INVALID_STATE"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_accept_attempt_from_failed_state(db_session, tmp_path):
    """§ 6A.10 post-exhaustion recovery: after the manual budget is spent
    the illustration is FAILED; the user can still promote a prior
    attempt via the UI. accept_attempt() must accept the FAILED state
    and clear the prior error_message."""
    _, ill, output_dir, _ = await _seed_with_image(db_session, attempt_index=1, tmp_path=tmp_path)
    ill.state = IllustrationState.FAILED
    ill.error_message = "Manual attempts exhausted"
    ill.manual_attempts = 5
    await db_session.commit()

    service = _make_service(db_session, tmp_path=tmp_path)
    await service.accept_attempt(ill, 1)

    assert ill.state == IllustrationState.COMPLETED
    assert ill.image_path == f"runs/{ill.run_id}/scene_0.png"
    assert ill.error_message is None
    canonical = os.path.join(output_dir, "runs", ill.run_id, "scene_0.png")
    assert os.path.exists(canonical)


@pytest.mark.asyncio
async def test_accept_attempt_attempt_not_found(db_session, tmp_path):
    _, ill, _, _ = await _seed_with_image(db_session, attempt_index=1, tmp_path=tmp_path)
    service = _make_service(db_session, tmp_path=tmp_path)
    with pytest.raises(ManualServiceError) as exc:
        await service.accept_attempt(ill, 99)
    assert exc.value.code == "ATTEMPT_NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_accept_attempt_file_missing(db_session, tmp_path):
    """If the deterministic temp file is gone (e.g. disk cleanup), the
    server raises ATTEMPT_FILE_MISSING (410)."""
    _, ill, output_dir, _ = await _seed_with_image(db_session, attempt_index=1, tmp_path=tmp_path)
    # Delete the source file.
    os.remove(os.path.join(output_dir, "runs", ill.run_id, "manual_0_1.png"))

    service = _make_service(db_session, tmp_path=tmp_path)
    with pytest.raises(ManualServiceError) as exc:
        await service.accept_attempt(ill, 1)
    assert exc.value.code == "ATTEMPT_FILE_MISSING"
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_accept_attempt_run_cancelled(db_session, tmp_path):
    _, ill, _, _ = await _seed_with_image(db_session, attempt_index=1, tmp_path=tmp_path)
    cancel = asyncio.Event()
    cancel.set()
    service = _make_service(db_session, tmp_path=tmp_path, cancel_flag=cancel)
    with pytest.raises(ManualServiceError) as exc:
        await service.accept_attempt(ill, 1)
    assert exc.value.code == "RUN_CANCELLED"


@pytest.mark.asyncio
async def test_append_iterate_prompt_appends_localized_bubble(db_session, tmp_path):
    """`append_iterate_prompt` adds one assistant bubble carrying the
    localized MANUAL_ITERATE_PROMPT text."""
    _, ill, _, manual_repo = await _seed_with_image(db_session, attempt_index=1, tmp_path=tmp_path)
    ill.state = IllustrationState.MANUAL_CHATTING
    await db_session.commit()
    prior_count = len(await manual_repo.get_messages(ill.id))

    service = _make_service(db_session, tmp_path=tmp_path)
    await service.append_iterate_prompt(ill, source_language="sk")

    rows = await manual_repo.get_messages(ill.id)
    assert len(rows) == prior_count + 1
    new_row = rows[-1]
    assert new_row.role == ManualMessageRole.ASSISTANT
    # Slovak iterate prompt contains the substring "Popíš".
    assert "Popíš" in new_row.content


@pytest.mark.asyncio
async def test_append_iterate_prompt_idempotent(db_session, tmp_path):
    """If the most recent row is not an image (i.e. the iterate prompt has
    already been appended, or the user has typed since), a second call
    is a no-op."""
    _, ill, _, manual_repo = await _seed_with_image(db_session, attempt_index=1, tmp_path=tmp_path)
    ill.state = IllustrationState.MANUAL_CHATTING
    await db_session.commit()
    service = _make_service(db_session, tmp_path=tmp_path)

    await service.append_iterate_prompt(ill, source_language="en")
    count_after_first = len(await manual_repo.get_messages(ill.id))
    await service.append_iterate_prompt(ill, source_language="en")
    count_after_second = len(await manual_repo.get_messages(ill.id))
    assert count_after_second == count_after_first


@pytest.mark.asyncio
async def test_append_iterate_prompt_invalid_state(db_session, tmp_path):
    _, ill, _, _ = await _seed_with_image(db_session, attempt_index=1, tmp_path=tmp_path)
    ill.state = IllustrationState.COMPLETED
    await db_session.commit()

    service = _make_service(db_session, tmp_path=tmp_path)
    with pytest.raises(ManualServiceError) as exc:
        await service.append_iterate_prompt(ill, source_language="en")
    assert exc.value.code == "INVALID_STATE"
