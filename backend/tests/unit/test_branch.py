"""Unit tests for per-illustration branch state machine (§11.1)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import IllustrationState
from app.schemas.claude import (
    EvaluateImageResponse,
    GeneratePromptsResponse,
    RethinkConceptResponse,
    RethinkEnvironmentResponse,
    RevisePromptsResponse,
    RevisionSummary,
    StyleGuide,
)
from app.services.storage import LocalImageStore

_TEST_IMAGE_STORE = LocalImageStore("/tmp")

STYLE_GUIDE = StyleGuide(
    overall_style_positive="watercolor",
    overall_style_negative="photorealistic",
    character_lora="",
    character_baseline_description="A young girl",
)

PROMPTS = GeneratePromptsResponse(
    workflow="single-lora",
    positive="brave knight, forest",
    negative="blurry",
)

REVISED_PROMPTS = RevisePromptsResponse(
    revision_summary=RevisionSummary(
        kept=["brave knight", "forest"],
        removed=[],
        added=[],
        reweighted=[],
        restructured=False,
        restructure_reason=None,
    ),
    workflow="single-lora",
    positive="brave knight, forest",
    negative="blurry",
)

VERDICT_OK = EvaluateImageResponse(
    ok=True,
    problem=None,
    reasoning="Looks great",
    suggestion="",
)

VERDICT_FAIL_PROMPT = EvaluateImageResponse(
    ok=False,
    problem="prompt",
    reasoning="Too blurry",
    suggestion="Make it sharper",
)

VERDICT_FAIL_PROMPT_NUANCE = EvaluateImageResponse(
    ok=False,
    problem="prompt",
    reasoning="Expression is in the same neighbourhood as the concept but not the exact beat.",
    suggestion="Push the expression tag harder.",
    nuance_only_failure=True,
)

VERDICT_FAIL_CONCEPT = EvaluateImageResponse(
    ok=False,
    problem="concept",
    reasoning="Wrong scene",
    suggestion="Change concept",
)

VERDICT_FAIL_ENVIRONMENT = EvaluateImageResponse(
    ok=False,
    problem="environment",
    reasoning="The locked environment cannot be rendered.",
    suggestion="Swap to a more concrete locale.",
)

RETHOUGHT_ENVIRONMENT = RethinkEnvironmentResponse(
    workflow="single-lora",
    concept="character at the attic window",
    concept_localized="postava pri podkrovnom okne",
    character_role="male",
    paragraph_text="Stál pri podkrovnom okne a pozeral von. Pršalo.",
    scene_excerpt="Stál pri podkrovnom okne a pozeral von.",
    environment={"label": "podkrovie", "kind": "indoor", "aspect": "single"},
    narrative_continuity_check="ok",
)

RETHOUGHT_CONCEPT = RethinkConceptResponse(
    workflow="single-lora",
    concept="New concept for the scene",
    concept_localized="New concept for the scene",
    character_role="male",
    paragraph_text="Stál pri okne a hľadel von. Pršalo a on plakal.",
    scene_excerpt="Pršalo a on plakal.",
    narrative_continuity_check="ok",
)

IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


CHARACTER_CONFIG = {
    "male": {
        "display_name": "Izuku Midoriya",
        "lora_filename": "midoriya_v1.safetensors",
        "trigger_tags": "midoriya izuku, green hair",
        "outfit_baseline": "school uniform",
    },
    "female": {
        "display_name": "Kyoka Jiro",
        "lora_filename": "jirou_v1.safetensors",
        "trigger_tags": "jirou kyouka, short hair",
        "outfit_baseline": "school uniform",
    },
    "mother": {
        "display_name": "Inko Midoriya",
        "lora_filename": "inko_v1.safetensors",
        "trigger_tags": "midoriya inko, green hair",
        "outfit_baseline": "casual clothes",
    },
}


def make_illustration(run_id="run-1", scene_index=0, character_role="male"):
    ill = MagicMock()
    ill.id = f"ill-{scene_index}"
    ill.run_id = run_id
    ill.scene_index = scene_index
    ill.scene_excerpt = "Once upon a time..."
    ill.paragraph_index = 0
    ill.character_role = character_role
    ill.initial_concept = "A boy crying in the rain"
    ill.current_concept = "A boy crying in the rain"
    ill.state = IllustrationState.PENDING
    ill.concept_attempt = 1
    ill.prompt_attempt = 1
    ill.image_path = None
    ill.error_message = None
    ill.contains_entity_label = None
    ill.last_verdict_json = None
    ill.current_prompts_json = None
    ill.environment_label = None
    ill.environment_aspect = None
    ill.current_workflow = None
    return ill


def make_services(
    generate_prompts_return=None,
    evaluate_image_return=None,
    revise_prompts_return=None,
    rethink_concept_return=None,
    rethink_environment_return=None,
    run_workflow_return=None,
):
    claude = AsyncMock()
    claude.generate_prompts.return_value = generate_prompts_return or PROMPTS
    claude.evaluate_image.return_value = evaluate_image_return or VERDICT_OK
    claude.revise_prompts.return_value = revise_prompts_return or REVISED_PROMPTS
    claude.rethink_concept.return_value = rethink_concept_return or RETHOUGHT_CONCEPT
    claude.rethink_environment.return_value = rethink_environment_return or RETHOUGHT_ENVIRONMENT

    runpod = AsyncMock()
    runpod.run_workflow.return_value = run_workflow_return or IMAGE_BYTES

    return claude, runpod


async def run_branch(illustration, style_guide, claude, runpod, cancel_flag=None):
    """Helper to run a branch and return the final illustration state."""
    from app.orchestrator.branch import run_branch as _run_branch

    repo = AsyncMock()
    repo.update_illustration = AsyncMock(side_effect=lambda ill, **kwargs: _apply(ill, **kwargs))
    # branch._load_entities() reads run_obj.narrative_entities_json; give it a
    # real string so json.loads() works during rethink_concept paths.
    stub_run = MagicMock()
    stub_run.narrative_entities_json = "[]"
    stub_run.environments_json = "[]"
    stub_run.story_blocks_json = None
    stub_run.main_character_role = "male"
    repo.get_run = AsyncMock(return_value=stub_run)
    repo.update_run = AsyncMock(return_value=stub_run)
    repo.session = MagicMock()
    event_bus = AsyncMock()

    if cancel_flag is None:
        cancel_flag = asyncio.Event()

    workflow_template = {"node": {"inputs": {"text": "POSITIVE_PROMPT", "lora": "CHARACTER_LORA"}}}

    # The exhaustion path in branch.py constructs a ManualService and calls
    # open_manual_flow(). We don't want unit tests to depend on a real
    # SQLAlchemy session — stub the service so it just transitions state.
    async def _stub_open_manual_flow(ill, source_language):
        await repo.update_illustration(ill, state=IllustrationState.MANUAL_CHATTING)

    fake_service = MagicMock()
    fake_service.open_manual_flow = AsyncMock(side_effect=_stub_open_manual_flow)

    with (
        patch("app.orchestrator.branch.ManualService", return_value=fake_service),
        patch("app.orchestrator.branch.ManualRepository", return_value=MagicMock()),
    ):
        await _run_branch(
            illustration=illustration,
            style_guide=style_guide,
            workflow_template=workflow_template,
            image_store=_TEST_IMAGE_STORE,
            claude=claude,
            runpod=runpod,
            repo=repo,
            event_bus=event_bus,
            cancel_flag=cancel_flag,
            character_config=CHARACTER_CONFIG,
            story_title="A short story",
            story_blocks=[
                {"type": "paragraph", "text": "Stál pri okne a hľadel von."},
                {"type": "illustration", "scene_index": 0},
            ],
        )
    return illustration


def _apply(ill, **kwargs):
    for k, v in kwargs.items():
        setattr(ill, k, v)
    return ill


@pytest.mark.asyncio
async def test_happy_path_first_attempt_succeeds():
    ill = make_illustration()
    claude, runpod = make_services(evaluate_image_return=VERDICT_OK)
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.COMPLETED
    claude.generate_prompts.assert_called_once()
    runpod.run_workflow.assert_called_once()
    claude.evaluate_image.assert_called_once()


@pytest.mark.asyncio
async def test_prompt_revision_path():
    """First attempt returns prompt-bad, second attempt succeeds."""
    ill = make_illustration()
    claude, runpod = make_services()
    claude.evaluate_image.side_effect = [VERDICT_FAIL_PROMPT, VERDICT_OK]
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.COMPLETED
    assert runpod.run_workflow.call_count == 2
    claude.revise_prompts.assert_called_once()


@pytest.mark.asyncio
async def test_concept_restart_path():
    """All 3 prompt attempts fail with problem=prompt on concept 1 -> concept 2 succeeds."""
    ill = make_illustration()
    claude, runpod = make_services()
    # 3 prompt failures on concept 1, then success on concept 2
    claude.evaluate_image.side_effect = [
        VERDICT_FAIL_PROMPT,
        VERDICT_FAIL_PROMPT,
        VERDICT_FAIL_PROMPT,
        VERDICT_OK,
    ]
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.COMPLETED
    claude.rethink_concept.assert_called_once()
    assert runpod.run_workflow.call_count == 4


@pytest.mark.asyncio
async def test_concept_rejection_immediate():
    """Verdict returns problem=concept on attempt 1 -> immediately move to next concept."""
    ill = make_illustration()
    claude, runpod = make_services()
    claude.evaluate_image.side_effect = [VERDICT_FAIL_CONCEPT, VERDICT_OK]
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.COMPLETED
    # Should not call revise_prompts on concept rejection
    claude.revise_prompts.assert_not_called()
    assert runpod.run_workflow.call_count == 2


@pytest.mark.asyncio
async def test_all_attempts_exhausted_enters_manual_flow():
    """All 3 concepts, all 3 prompt attempts each → MANUAL_CHATTING (§ 6A).

    The branch no longer transitions straight to FAILED on auto-pipeline
    exhaustion; it hands off to the manual chat fallback by transitioning
    the illustration to MANUAL_CHATTING and creating a manual session
    row. Exhaustion-to-FAILED only happens later, inside the manual flow,
    when the manual budget itself is exhausted.
    """
    ill = make_illustration()
    claude, runpod = make_services()
    claude.evaluate_image.return_value = VERDICT_FAIL_PROMPT
    await run_branch(ill, STYLE_GUIDE, claude, runpod)
    assert ill.state == IllustrationState.MANUAL_CHATTING


@pytest.mark.asyncio
async def test_cancellation_stops_branch():
    """Cancel flag set before start -> branch transitions to CANCELLED."""
    ill = make_illustration()
    claude, runpod = make_services()
    cancel_flag = asyncio.Event()
    cancel_flag.set()  # Set before running
    await run_branch(ill, STYLE_GUIDE, claude, runpod, cancel_flag=cancel_flag)
    assert ill.state == IllustrationState.CANCELLED
    # No external calls should be made
    claude.generate_prompts.assert_not_called()
    runpod.run_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_character_lora_from_character_config():
    """Branch uses the correct lora_filename from character_config based on character_role."""
    from app.orchestrator.branch import run_branch as _run_branch

    captured_workflow = []

    async def capture_workflow(workflow, **_kwargs):
        captured_workflow.append(workflow)
        return IMAGE_BYTES

    ill = make_illustration(character_role="female")
    claude, runpod = make_services(evaluate_image_return=VERDICT_OK)
    runpod.run_workflow.side_effect = capture_workflow

    repo = AsyncMock()
    repo.update_illustration = AsyncMock(side_effect=lambda i, **kwargs: _apply(i, **kwargs))
    stub_run = MagicMock()
    stub_run.narrative_entities_json = "[]"
    stub_run.environments_json = "[]"
    stub_run.story_blocks_json = None
    stub_run.main_character_role = "female"
    repo.get_run = AsyncMock(return_value=stub_run)
    repo.update_run = AsyncMock(return_value=stub_run)
    repo.session = MagicMock()
    event_bus = AsyncMock()

    workflow_template = {
        "node": {
            "inputs": {
                "lora": "CHARACTER_LORA",
                "positive": "POSITIVE_PROMPT",
                "negative": "NEGATIVE_PROMPT",
                "style_pos": "STYLE_POSITIVE_PROMPT",
                "style_neg": "STYLE_NEGATIVE_PROMPT",
            }
        }
    }

    await _run_branch(
        illustration=ill,
        style_guide=STYLE_GUIDE,
        workflow_template=workflow_template,
        image_store=_TEST_IMAGE_STORE,
        claude=claude,
        runpod=runpod,
        repo=repo,
        event_bus=event_bus,
        cancel_flag=asyncio.Event(),
        character_config=CHARACTER_CONFIG,
        story_title="Test Story",
        source_language="sk",
        story_blocks=[
            {"type": "paragraph", "text": "Test paragraph."},
            {"type": "illustration", "scene_index": 0},
        ],
    )

    assert ill.state == IllustrationState.COMPLETED
    # The lora value in the submitted workflow must be the female lora_filename
    # Check that workflow was captured and contains the expected lora
    assert len(captured_workflow) > 0, "No workflow was captured"
    wf = captured_workflow[0]
    # Navigate the workflow structure - it may vary based on template
    if "node" in wf:
        assert wf["node"]["inputs"]["lora"] == "jirou_v1.safetensors"
    else:
        # If structure is different, just verify lora value exists somewhere
        import json

        wf_str = json.dumps(wf)
        assert "jirou_v1.safetensors" in wf_str, f"Expected lora not found in workflow: {wf}"


# ---- Environment-rethink path (Agent 4b, § 11) ----------------------------


def _make_env_repo():
    """Build a repo mock whose ``get_run`` returns a run with locked envs.

    The run-level fields ``environments_json``, ``narrative_entities_json``,
    and ``main_character_role`` are what ``_do_environment_rethink``
    reads from the DB.
    """
    fake_run = MagicMock()
    fake_run.id = "run-1"
    fake_run.main_character_role = "male"
    fake_run.environments_json = json.dumps(
        [
            {"label": "obývačka", "kind": "indoor", "aspect": "single"},
            {"label": "kuchyňa", "kind": "indoor", "aspect": "single"},
            {"label": "spálňa", "kind": "indoor", "aspect": "single"},
            {"label": "kúpeľňa", "kind": "indoor", "aspect": "single"},
            {"label": "záhrada", "kind": "outdoor", "aspect": "single"},
        ]
    )
    fake_run.narrative_entities_json = "[]"
    fake_run.story_blocks_json = None

    repo = AsyncMock()
    repo.update_illustration = AsyncMock(side_effect=lambda ill, **kwargs: _apply(ill, **kwargs))
    repo.get_run = AsyncMock(return_value=fake_run)
    repo.update_run = AsyncMock(return_value=fake_run)
    repo.session = MagicMock()
    return repo, fake_run


async def _run_branch_with_env_context(
    illustration,
    claude,
    runpod,
    repo,
    *,
    scene_index_for_env=0,
):
    """Drive run_branch through the env-rethink path using a custom repo."""
    from app.orchestrator.branch import run_branch as _run_branch

    event_bus = AsyncMock()
    cancel_flag = asyncio.Event()
    workflow_template = {"node": {"inputs": {"text": "POSITIVE_PROMPT", "lora": "CHARACTER_LORA"}}}

    async def _stub_open_manual_flow(ill, source_language):
        await repo.update_illustration(ill, state=IllustrationState.MANUAL_CHATTING)

    fake_service = MagicMock()
    fake_service.open_manual_flow = AsyncMock(side_effect=_stub_open_manual_flow)

    with (
        patch("app.orchestrator.branch.ManualService", return_value=fake_service),
        patch("app.orchestrator.branch.ManualRepository", return_value=MagicMock()),
    ):
        await _run_branch(
            illustration=illustration,
            style_guide=STYLE_GUIDE,
            workflow_template=workflow_template,
            image_store=_TEST_IMAGE_STORE,
            claude=claude,
            runpod=runpod,
            repo=repo,
            event_bus=event_bus,
            cancel_flag=cancel_flag,
            character_config=CHARACTER_CONFIG,
            story_title="Test story",
            story_blocks=[
                {"type": "paragraph", "text": "Pôvodný odsek."},
                {"type": "illustration", "scene_index": scene_index_for_env},
            ],
        )
    return event_bus


@pytest.mark.asyncio
async def test_environment_rethink_path_swaps_env_and_succeeds():
    """verdict.problem='environment' → Agent 4b fires → new env persisted, next concept succeeds."""
    ill = make_illustration()
    ill.paragraph_index = 0
    claude, runpod = make_services()
    # 1st evaluation: env-rejected → A4b fires. 2nd evaluation: ok.
    claude.evaluate_image.side_effect = [VERDICT_FAIL_ENVIRONMENT, VERDICT_OK]
    repo, fake_run = _make_env_repo()

    event_bus = await _run_branch_with_env_context(ill, claude, runpod, repo)

    # A4b was invoked exactly once.
    claude.rethink_environment.assert_called_once()
    # A4 (concept rethink) was NOT invoked — A4b's output replaced the concept.
    claude.rethink_concept.assert_not_called()
    # Final state is COMPLETED (second render passed evaluation).
    assert ill.state == IllustrationState.COMPLETED
    # New env persisted at the slot's scene_index in the run's environments_json.
    update_run_calls = [
        c for c in repo.update_run.await_args_list if "environments_json" in c.kwargs
    ]
    envs = json.loads(update_run_calls[-1].kwargs["environments_json"])
    assert envs[ill.scene_index]["label"] == "podkrovie"
    # Per-illustration env fields were updated.
    assert ill.environment_label == "podkrovie"
    assert ill.environment_aspect == "single"
    # Concept was rewritten via A4b output.
    assert ill.current_concept == "postava pri podkrovnom okne"
    assert ill.scene_excerpt == "Stál pri podkrovnom okne a pozeral von."
    # The illustration_environment_updated event was published.
    event_topics = [c.args[0] for c in event_bus.publish.await_args_list]
    assert "illustration_environment_updated" in event_topics
    assert "paragraph_updated" in event_topics


@pytest.mark.asyncio
async def test_environment_rethink_only_fires_once_per_branch():
    """A4b is one-shot; subsequent env verdicts must NOT trigger another swap."""
    ill = make_illustration()
    ill.paragraph_index = 0
    claude, runpod = make_services()
    # After A4b, every subsequent verdict is also env-rejected — but A4b
    # must not fire again. Eventually the branch exhausts its budget and
    # enters MANUAL_CHATTING.
    claude.evaluate_image.return_value = VERDICT_FAIL_ENVIRONMENT
    repo, _ = _make_env_repo()

    await _run_branch_with_env_context(ill, claude, runpod, repo)

    # rethink_environment fires exactly once even though every verdict
    # is still 'environment'.
    assert claude.rethink_environment.await_count == 1
    # Branch falls through to manual fallback on exhaustion.
    assert ill.state == IllustrationState.MANUAL_CHATTING


@pytest.mark.asyncio
async def test_environment_rethink_rejects_label_collision():
    """A4b output that clashes with an in-use env label is rejected → FAILED."""
    ill = make_illustration()
    ill.paragraph_index = 0
    claude, runpod = make_services(
        rethink_environment_return=RethinkEnvironmentResponse(
            workflow="single-lora",
            concept="character in the living room window",
            concept_localized="postava pri okne obývačky",
            character_role="male",
            paragraph_text="Stál v obývačke a hľadel von oknom.",
            scene_excerpt="Stál v obývačke a hľadel von oknom.",
            # 'obývačka' is already at scene_index=0 in the fake run; the
            # slot under test is scene_index=1 (kuchyňa). The proposed
            # label clashes with another slot — must be rejected.
            environment={"label": "obývačka", "kind": "indoor", "aspect": "single"},
            narrative_continuity_check="ok",
        ),
    )
    claude.evaluate_image.return_value = VERDICT_FAIL_ENVIRONMENT
    repo, _ = _make_env_repo()

    # Slot under test is scene_index=1 — its label is 'kuchyňa'. The A4b
    # output proposes 'obývačka' which is taken by scene_index=0.
    ill.scene_index = 1
    ill.id = "ill-1"

    # The collision branch in _do_environment_rethink marks the row FAILED
    # and then re-raises a RuntimeError; we expect both behaviours.
    with pytest.raises(RuntimeError, match="collides"):
        await _run_branch_with_env_context(ill, claude, runpod, repo, scene_index_for_env=1)

    claude.rethink_environment.assert_called_once()
    assert ill.state == IllustrationState.FAILED
    assert "collides" in (ill.error_message or "")


# ---- Seed-lock rule (nuance_only_failure) ---------------------------------


async def _run_branch_capturing_seeds(ill, claude, runpod_side_effect):
    """Run a branch and return the list of seeds sent into runpod."""
    from app.orchestrator.branch import run_branch as _run_branch

    captured_seeds: list[int] = []

    def _find_seed(obj):
        if isinstance(obj, dict):
            if "seed" in obj and isinstance(obj["seed"], int):
                return obj["seed"]
            for v in obj.values():
                s = _find_seed(v)
                if s is not None:
                    return s
        elif isinstance(obj, list):
            for item in obj:
                s = _find_seed(item)
                if s is not None:
                    return s
        return None

    async def capture(workflow, **_kwargs):
        # The branch loads the real workflow file (matching prompts.workflow)
        # from disk, so the structure is the ComfyUI graph — scan for KSampler's
        # numeric seed wherever it sits.
        seed_val = _find_seed(workflow)
        assert seed_val is not None, f"no numeric seed found in workflow: {workflow!r}"
        captured_seeds.append(seed_val)
        return await runpod_side_effect()

    runpod = AsyncMock()
    runpod.run_workflow.side_effect = capture

    repo = AsyncMock()
    repo.update_illustration = AsyncMock(side_effect=lambda i, **kwargs: _apply(i, **kwargs))
    stub_run = MagicMock()
    stub_run.narrative_entities_json = "[]"
    stub_run.environments_json = "[]"
    stub_run.story_blocks_json = None
    stub_run.main_character_role = "male"
    repo.get_run = AsyncMock(return_value=stub_run)
    repo.update_run = AsyncMock(return_value=stub_run)
    repo.session = MagicMock()
    event_bus = AsyncMock()

    workflow_template = {
        "node": {
            "inputs": {
                "lora": "CHARACTER_LORA",
                "positive": "POSITIVE_PROMPT",
                "negative": "NEGATIVE_PROMPT",
                "style_pos": "STYLE_POSITIVE_PROMPT",
                "style_neg": "STYLE_NEGATIVE_PROMPT",
                "seed": "SEED",
            }
        }
    }

    async def _stub_open_manual_flow(i, source_language):
        await repo.update_illustration(i, state=IllustrationState.MANUAL_CHATTING)

    fake_service = MagicMock()
    fake_service.open_manual_flow = AsyncMock(side_effect=_stub_open_manual_flow)

    with (
        patch("app.orchestrator.branch.ManualService", return_value=fake_service),
        patch("app.orchestrator.branch.ManualRepository", return_value=MagicMock()),
    ):
        await _run_branch(
            illustration=ill,
            style_guide=STYLE_GUIDE,
            workflow_template=workflow_template,
            image_store=_TEST_IMAGE_STORE,
            claude=claude,
            runpod=runpod,
            repo=repo,
            event_bus=event_bus,
            cancel_flag=asyncio.Event(),
            character_config=CHARACTER_CONFIG,
            story_title="Test",
            source_language="sk",
            story_blocks=[
                {"type": "paragraph", "text": "Test paragraph."},
                {"type": "illustration", "scene_index": 0},
            ],
        )
    return captured_seeds


@pytest.mark.asyncio
async def test_seed_locked_after_nuance_only_failure():
    """Verdict 1 = nuance-only failure → verdict 2's render must reuse the same seed."""
    ill = make_illustration()
    claude, _ = make_services()
    claude.evaluate_image.side_effect = [VERDICT_FAIL_PROMPT_NUANCE, VERDICT_OK]

    async def _img():
        return IMAGE_BYTES

    seeds = await _run_branch_capturing_seeds(ill, claude, _img)
    assert ill.state == IllustrationState.COMPLETED
    assert len(seeds) == 2
    assert seeds[0] == seeds[1], f"seed-lock failed: {seeds!r}"


@pytest.mark.asyncio
async def test_seed_rerolls_after_non_nuance_failure():
    """Verdict 1 = ordinary prompt failure → verdict 2's render must use a DIFFERENT seed."""
    ill = make_illustration()
    claude, _ = make_services()
    claude.evaluate_image.side_effect = [VERDICT_FAIL_PROMPT, VERDICT_OK]

    async def _img():
        return IMAGE_BYTES

    seeds = await _run_branch_capturing_seeds(ill, claude, _img)
    assert ill.state == IllustrationState.COMPLETED
    assert len(seeds) == 2
    # 32-bit random space ⇒ collision probability ~2^-32, safe to assert inequality.
    assert seeds[0] != seeds[1], f"expected reroll, got identical seeds: {seeds!r}"


@pytest.mark.asyncio
async def test_seed_lock_consumed_after_one_attempt():
    """Lock applies for exactly ONE attempt: nuance-only → reuse → ordinary failure → reroll."""
    ill = make_illustration()
    claude, _ = make_services()
    # 3 failures (max), branch then enters manual flow. We only need to inspect
    # the seed pattern across the 3 renders within the single concept.
    claude.evaluate_image.side_effect = [
        VERDICT_FAIL_PROMPT_NUANCE,  # attempt 1 → lock for attempt 2
        VERDICT_FAIL_PROMPT,  # attempt 2 (seed reused) → lock cleared
        VERDICT_FAIL_PROMPT,  # attempt 3 (fresh seed)
        # Concept restart → new random seed for the new concept's first render.
        # Then we let it succeed to terminate the branch cleanly.
        VERDICT_OK,
    ]

    async def _img():
        return IMAGE_BYTES

    seeds = await _run_branch_capturing_seeds(ill, claude, _img)
    assert ill.state == IllustrationState.COMPLETED
    assert len(seeds) == 4
    # attempt 1 vs 2: locked → equal
    assert seeds[0] == seeds[1]
    # attempt 2 vs 3: lock consumed → different (reroll)
    assert seeds[1] != seeds[2]
    # attempt 3 vs first attempt of new concept: different (outer reset + reroll)
    assert seeds[2] != seeds[3]


@pytest.mark.asyncio
async def test_seed_resets_on_concept_change():
    """Nuance-only failure on the LAST prompt attempt of concept 1 must NOT
    leak the seed into concept 2's first render — the outer loop reset
    clears ``previous_seed`` and ``lock_seed_next``."""
    ill = make_illustration()
    claude, _ = make_services()
    # 3 nuance-only failures → concept exhausted → new concept → success.
    claude.evaluate_image.side_effect = [
        VERDICT_FAIL_PROMPT_NUANCE,
        VERDICT_FAIL_PROMPT_NUANCE,
        VERDICT_FAIL_PROMPT_NUANCE,
        VERDICT_OK,
    ]

    async def _img():
        return IMAGE_BYTES

    seeds = await _run_branch_capturing_seeds(ill, claude, _img)
    assert ill.state == IllustrationState.COMPLETED
    assert len(seeds) == 4
    # Within concept 1: all three attempts locked together (each verdict
    # was nuance-only, so each subsequent attempt reused the previous seed).
    assert seeds[0] == seeds[1] == seeds[2]
    # Concept change wipes the lock — first render of concept 2 must use a
    # fresh random seed.
    assert seeds[3] != seeds[2]
