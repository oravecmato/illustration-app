"""Per-illustration state machine branch."""

import asyncio
import json
import logging
import os
import random

from app.constants import (
    ERROR_CODE_RENDER_FAILED,
    ERROR_CODE_RENDER_TIMEOUT,
    MAX_CONCEPT_ATTEMPTS,
    MAX_PROMPT_ATTEMPTS_PER_CONCEPT,
    RUNPOD_TIMEOUT_RETRY,
)
from app.db.models import Illustration, IllustrationAttemptHistory, IllustrationState
from app.db.repositories import ManualRepository, RunRepository
from app.orchestrator.events import EventBus
from app.schemas.claude import (
    Environment,
    SalvageCandidate,
    StyleGuide,
    _normalize_entity_label,
    _normalize_whitespace,
)
from app.services.claude import ClaudeClient
from app.services.images import copy_image, save_history_image, save_image
from app.services.manual import ManualService
from app.services.runpod import RunPodClient, RunPodTimeoutError
from app.services.workflow import replace_placeholders

logger = logging.getLogger(__name__)


async def run_branch(
    illustration: Illustration,
    style_guide: StyleGuide,
    workflow_template: dict,
    output_dir: str,
    claude: ClaudeClient,
    runpod: RunPodClient,
    repo: RunRepository,
    event_bus: EventBus,
    cancel_flag: asyncio.Event,
    character_config: dict | None = None,
    story_title: str = "",
    source_language: str = "sk",
    story_blocks: list[dict] | None = None,
    story_lock: asyncio.Lock | None = None,
) -> None:
    """Run the state machine for a single illustration branch.

    The unified narrative_entities register is read from the Run row on
    every iteration (no in-process cache) so concurrent branches see each
    other's ``claim_floating`` writes immediately. Mutations to the
    register are serialised by ``story_lock``.
    """
    char_config = character_config or {}
    character_role = illustration.character_role
    blocks = story_blocks if story_blocks is not None else []
    lock = story_lock or asyncio.Lock()

    async def _load_entities() -> list[dict]:
        """Read the current narrative_entities list from the run row."""
        run_obj = await repo.get_run(illustration.run_id)
        if run_obj is None or run_obj.narrative_entities_json is None:
            return []
        return json.loads(run_obj.narrative_entities_json)

    def _find_entity(entities: list[dict], label: str | None) -> dict | None:
        if label is None:
            return None
        norm = _normalize_entity_label(label)
        for e in entities:
            if _normalize_entity_label(e["label"]) == norm:
                return e
        return None

    async def _current_entity() -> dict | None:
        """The NarrativeEntity dict currently attached to this slot, or None."""
        if not illustration.contains_entity_label:
            return None
        entities = await _load_entities()
        return _find_entity(entities, illustration.contains_entity_label)

    async def transition(state: IllustrationState, **extra) -> None:
        await repo.update_illustration(illustration, state=state, **extra)
        await event_bus.publish(
            "illustration_state",
            {
                "illustration_id": illustration.id,
                "scene_index": illustration.scene_index,
                "state": state,
                "concept_attempt": illustration.concept_attempt,
                "prompt_attempt": illustration.prompt_attempt,
                # Surface the currently-active concept + excerpt so the
                # frontend can reactively re-render the IllustrationCard's
                # concept and excerpt text when Agent 4 rethinks them
                # (§ 8.4, § 9.1, § 9.5).
                "current_concept": illustration.current_concept,
                "scene_excerpt": illustration.scene_excerpt,
            },
        )

    if cancel_flag.is_set():
        await transition(IllustrationState.CANCELLED)
        return

    # Environment-rethink bookkeeping (§ 11 Agent 4b):
    # - env_rethink_used: True once Agent 4b has fired for this slot.
    #   Only one environment swap is allowed per branch.
    # - skip_concept_rethink_once: when set, the next outer iteration
    #   bypasses Agent 4 (rethink_concept) because Agent 4b already wrote
    #   a fresh concept + paragraph as part of the swap.
    # The "+1 budget" edge case: when env_rethink_used flips True, the
    # outer loop is allowed one extra concept_attempt iteration. We
    # express this by NOT incrementing concept_attempt on the iteration
    # in which A4b ran (the env swap is "free").
    env_rethink_used = False
    skip_concept_rethink_once = False
    concept_attempt = 1
    while concept_attempt <= MAX_CONCEPT_ATTEMPTS + (1 if env_rethink_used else 0):
        if cancel_flag.is_set():
            await transition(IllustrationState.CANCELLED)
            return

        # Consume the skip flag at the top of each iteration. A4b sets it
        # in the inner loop; the *next* outer iteration reads it once to
        # bypass A4 (rethink_concept) — because A4b has already rewritten
        # the concept + paragraph as part of the env swap — and then
        # clears it so subsequent iterations behave normally.
        skip_concept_rethink_this_iter = skip_concept_rethink_once
        skip_concept_rethink_once = False

        if concept_attempt > 1 and not skip_concept_rethink_this_iter:
            # Rethink concept
            await transition(
                IllustrationState.RETHINKING_CONCEPT,
                concept_attempt=concept_attempt,
                prompt_attempt=1,
            )
            prev_entity_label = illustration.contains_entity_label
            entities_snapshot = await _load_entities()
            try:
                rethink_result = await claude.rethink_concept(
                    source_language=source_language,
                    current_scene_index=illustration.scene_index,
                    current_concept=illustration.current_concept,
                    verdict=_load_last_verdict(illustration),
                    current_scene_excerpt=illustration.scene_excerpt,
                    story_title=story_title,
                    story_blocks=blocks,
                    current_paragraph_index=illustration.paragraph_index,
                    character_role=character_role,
                    current_entity_label=prev_entity_label,
                    narrative_entities=entities_snapshot,
                )
            except Exception as e:
                logger.error("rethink_concept failed: %s", e)
                await transition(
                    IllustrationState.FAILED,
                    error_message=f"Concept rethink failed: {e}",
                )
                return

            # Check if character_role changed
            role_changed = rethink_result.character_role != character_role
            if role_changed:
                # Update local character_role and emit event
                character_role = rethink_result.character_role
                await event_bus.publish(
                    "illustration_role_updated",
                    {
                        "illustration_id": illustration.id,
                        "scene_index": illustration.scene_index,
                        "character_role": character_role,
                    },
                )

            # Defence-in-depth: validate entity_action ↔ entity state under
            # the story lock (so a concurrent claim_floating on the same
            # entity cannot race with us), then apply the run-level
            # narrative_entities mutation atomically with the paragraph
            # rewrite. The Pydantic validator already enforced action ↔
            # contains_entity_label coherence; here we check against the
            # actual registry state at apply time.
            paragraph_index = illustration.paragraph_index
            async with lock:
                live_entities = await _load_entities()
                action = rethink_result.entity_action
                new_label = rethink_result.contains_entity_label

                err: str | None = None
                if action == "keep":
                    ent = _find_entity(live_entities, new_label)
                    if ent is None:
                        err = (
                            f"Agent 4 entity_action='keep' references unknown entity {new_label!r}."
                        )
                    elif ent.get("reserved_for_scene_index") != illustration.scene_index:
                        err = (
                            f"Agent 4 entity_action='keep' but entity {new_label!r} "
                            f"is not reserved for this slot "
                            f"(reserved_for_scene_index="
                            f"{ent.get('reserved_for_scene_index')})."
                        )
                elif action == "drop":
                    ent = _find_entity(live_entities, prev_entity_label)
                    if ent is None or ent.get("reserved_for_scene_index") != (
                        illustration.scene_index
                    ):
                        err = (
                            "Agent 4 entity_action='drop' but this slot has no "
                            "active entity reservation to drop."
                        )
                elif action == "claim_floating":
                    ent = _find_entity(live_entities, new_label)
                    if ent is None:
                        err = (
                            f"Agent 4 entity_action='claim_floating' references "
                            f"unknown entity {new_label!r}."
                        )
                    elif ent.get("importance") != "supporting":
                        err = (
                            f"Agent 4 may only claim 'supporting' entities; "
                            f"{new_label!r} is {ent.get('importance')!r}."
                        )
                    elif ent.get("reserved_for_scene_index") is not None:
                        err = (
                            f"Agent 4 tried to claim entity {new_label!r} but it "
                            f"is already reserved for scene_index="
                            f"{ent.get('reserved_for_scene_index')}."
                        )
                # action == "none" requires no further checks.

                if err is not None:
                    logger.error(err)
                    await transition(
                        IllustrationState.FAILED,
                        error_message=err,
                    )
                    return

                if action == "claim_floating":
                    for e in live_entities:
                        if _normalize_entity_label(e["label"]) == _normalize_entity_label(
                            new_label
                        ):
                            e["reserved_for_scene_index"] = illustration.scene_index
                            break

                # Apply rewrite: mutate shared blocks + persist run row.
                if 0 <= paragraph_index < len(blocks):
                    blocks[paragraph_index] = {
                        "type": "paragraph",
                        "text": rethink_result.paragraph_text,
                    }
                run_obj = await repo.get_run(illustration.run_id)
                if run_obj is not None:
                    await repo.update_run(
                        run_obj,
                        story_blocks_json=json.dumps(blocks, ensure_ascii=False),
                        narrative_entities_json=json.dumps(live_entities, ensure_ascii=False),
                    )
            await repo.update_illustration(
                illustration,
                character_role=rethink_result.character_role,
                current_workflow=f"{rethink_result.workflow}.json",
                current_concept=rethink_result.concept_localized,
                scene_excerpt=rethink_result.scene_excerpt,
                contains_entity_label=new_label,
            )
            await event_bus.publish(
                "paragraph_updated",
                {
                    "paragraph_index": paragraph_index,
                    "text": rethink_result.paragraph_text,
                },
            )
            entity_changed = prev_entity_label != new_label
            if entity_changed:
                new_entity_dict = _find_entity(live_entities, new_label) if new_label else None
                await event_bus.publish(
                    "illustration_entity_updated",
                    {
                        "illustration_id": illustration.id,
                        "scene_index": illustration.scene_index,
                        "contains_entity_label": new_label,
                        "entity": new_entity_dict,
                    },
                )

        # Generate prompts for current concept
        if cancel_flag.is_set():
            await transition(IllustrationState.CANCELLED)
            return

        await transition(
            IllustrationState.GENERATING_PROMPTS,
            concept_attempt=concept_attempt,
            prompt_attempt=1,
        )
        try:
            prompts = await claude.generate_prompts(
                current_concept=illustration.current_concept,
                style_guide=style_guide,
                character_role=character_role,
                character_config=char_config,
                contains_entity=await _current_entity(),
                prompting_notes=illustration.prompting_notes,
            )
            # Persist workflow to illustration (Agent 1 response)
            illustration = await repo.update_illustration(
                illustration,
                current_workflow=f"{prompts.workflow}.json",
            )
        except Exception as e:
            logger.error("generate_prompts failed: %s", e)
            await transition(
                IllustrationState.FAILED,
                error_message=f"Prompt generation failed: {e}",
            )
            return

        concept_succeeded = False
        # Newest-first English summaries of the previous rejected verdicts
        # for THIS concept. Reset every outer (concept) iteration. Agent 2
        # sees this list and is instructed to escalate to problem="concept"
        # when the same failure mode repeats.
        recent_failure_summaries: list[str] = []
        # Seed-lock state for the inner (prompt-revision) loop. Both reset
        # every outer iteration because a concept/environment rewrite makes
        # the previous seed's composition no longer a relevant reference.
        # When the previous verdict was a nuance-only near-miss, we keep
        # the same seed for ONE next attempt so the prompt revision steers
        # within the same composition instead of resampling the whole
        # latent. Otherwise we reroll. See "seed-lock rule" docstring above.
        previous_seed: int | None = None
        lock_seed_next: bool = False
        for prompt_attempt in range(1, MAX_PROMPT_ATTEMPTS_PER_CONCEPT + 1):
            if cancel_flag.is_set():
                await transition(IllustrationState.CANCELLED)
                return

            await transition(
                IllustrationState.RENDERING,
                concept_attempt=concept_attempt,
                prompt_attempt=prompt_attempt,
                current_prompts_json=prompts.model_dump_json(),
            )

            # CHARACTER_LORA comes from character_config per-illustration (§ 7.3.7)
            char_lora = char_config.get(character_role, {}).get("lora_filename", "")

            # Load workflow file based on illustration.current_workflow
            # Fall back to workflow_template if current_workflow not set (for tests)
            if illustration.current_workflow:
                workflow_filename = illustration.current_workflow
                workflow_path = os.path.join(
                    os.path.dirname(__file__), "..", "workflows", workflow_filename
                )
                try:
                    with open(workflow_path) as f:
                        workflow_template_to_use = json.load(f)
                except FileNotFoundError:
                    logger.warning(
                        "Workflow file %s not found, falling back to default",
                        workflow_path,
                    )
                    workflow_template_to_use = workflow_template
            else:
                workflow_template_to_use = workflow_template

            # Build workflow with current prompts + style guide.
            # SEED selection — see "seed-lock rule" comment where
            # ``previous_seed`` / ``lock_seed_next`` are initialised.
            # Default is a fresh random seed per render so prompt
            # revisions actually move the diffusion process. When the
            # previous attempt in this concept missed only on nuance
            # (item #3, near-miss), we reuse that seed for one attempt
            # so the prompt edit refines within the same composition.
            if lock_seed_next and previous_seed is not None:
                seed = previous_seed
                logger.info(
                    "seed-lock: reusing seed %d for prompt_attempt %d (previous "
                    "verdict was nuance_only_failure)",
                    seed,
                    prompt_attempt,
                )
            else:
                seed = random.randint(0, 2**32 - 1)
            # Consume the lock; next attempt re-decides based on the
            # verdict we are about to receive.
            lock_seed_next = False

            # Render with up to ``RUNPOD_TIMEOUT_RETRY`` retries on
            # ``RunPodTimeoutError`` only. A timeout means the GPU pool
            # stalled — the workflow is fine. Each retry uses a fresh
            # random seed (the cached prompt-hash may have been what
            # got the original job queued behind a slow worker). The
            # prompt_attempt counter is NOT bumped across these retries:
            # they are infrastructure recovery, not prompt-engineering
            # signals. Other ``RunPodError`` failures (FAILED/CANCELLED
            # remote status, malformed response) fail immediately with
            # ``error_code=RENDER_FAILED`` — they almost always indicate
            # a workflow/auth issue that a retry would not heal.
            image_bytes: bytes | None = None
            timeout_exc: Exception | None = None
            for timeout_attempt in range(RUNPOD_TIMEOUT_RETRY + 1):
                if timeout_attempt > 0:
                    # Reroll seed for the timeout retry. Overrides any
                    # seed-lock — the previous job never produced an
                    # image, so there is no composition to lock onto.
                    seed = random.randint(0, 2**32 - 1)
                    logger.warning(
                        "runpod timeout retry %d/%d for illustration %s "
                        "(scene_index=%d, c%d/a%d) — new seed %d",
                        timeout_attempt,
                        RUNPOD_TIMEOUT_RETRY,
                        illustration.id,
                        illustration.scene_index,
                        concept_attempt,
                        prompt_attempt,
                        seed,
                    )
                replacements = {
                    "POSITIVE_PROMPT": prompts.positive,
                    "NEGATIVE_PROMPT": prompts.negative,
                    "CHARACTER_LORA": char_lora,
                    "STYLE_POSITIVE_PROMPT": style_guide.overall_style_positive,
                    "STYLE_NEGATIVE_PROMPT": style_guide.overall_style_negative,
                    "SEED": seed,
                }
                workflow, _ = replace_placeholders(workflow_template_to_use, replacements)
                try:
                    image_bytes = await runpod.run_workflow(workflow)
                    timeout_exc = None
                    break
                except RunPodTimeoutError as e:
                    timeout_exc = e
                    continue
                except Exception as e:
                    logger.error("runpod.run_workflow failed: %s", e)
                    await transition(
                        IllustrationState.FAILED,
                        error_message=f"Image rendering failed: {e}",
                        error_code=ERROR_CODE_RENDER_FAILED,
                    )
                    return

            if image_bytes is None:
                logger.error(
                    "runpod.run_workflow timed out after %d retries: %s",
                    RUNPOD_TIMEOUT_RETRY,
                    timeout_exc,
                )
                await transition(
                    IllustrationState.FAILED,
                    error_message=f"Image rendering failed: {timeout_exc}",
                    error_code=ERROR_CODE_RENDER_TIMEOUT,
                )
                return

            if cancel_flag.is_set():
                await transition(IllustrationState.CANCELLED)
                return

            await transition(
                IllustrationState.EVALUATING,
                concept_attempt=concept_attempt,
                prompt_attempt=prompt_attempt,
            )

            try:
                verdict = await claude.evaluate_image(
                    image_bytes=image_bytes,
                    current_concept=illustration.current_concept,
                    style_guide=style_guide,
                    character_role=character_role,
                    character_config=char_config,
                    contains_entity=await _current_entity(),
                    recent_failure_summaries=recent_failure_summaries or None,
                    positive_prompt=prompts.positive,
                )
            except Exception as e:
                logger.error("evaluate_image failed: %s", e)
                await transition(
                    IllustrationState.FAILED,
                    error_message=f"Image evaluation failed: {e}",
                )
                return

            await repo.update_illustration(
                illustration, last_verdict_json=verdict.model_dump_json()
            )
            if not verdict.ok:
                # Prepend so the list stays newest-first. Cap at 3 to
                # keep the prompt compact; older context rarely matters
                # since the inner loop tops out at 3 attempts per concept.
                summary = (
                    f"attempt {prompt_attempt}: problem={verdict.problem}; "
                    f"reasoning={verdict.reasoning}"
                )
                recent_failure_summaries.insert(0, summary)
                del recent_failure_summaries[3:]

            # Update seed-lock state based on this verdict. We only lock
            # when the verdict was a nuance-only near-miss AND the inner
            # loop will continue (i.e. problem routes back to Agent 3 for
            # prompt revision). On problem="concept" or "environment" the
            # outer loop will reset both flags anyway, but we also clear
            # explicitly here so the intent is local.
            if not verdict.ok and verdict.nuance_only_failure and verdict.problem == "prompt":
                previous_seed = seed
                lock_seed_next = True
            else:
                previous_seed = None
                lock_seed_next = False

            # Persist the immutable attempt-history snapshot (§ 5).
            # Done before the success branch so successful attempts are
            # also recorded (verdict.ok=true rows exist for audit /
            # parity even though they are filtered out of salvage).
            history_image_path = await save_history_image(
                image_bytes,
                output_dir,
                illustration.run_id,
                illustration.id,
                concept_attempt,
                prompt_attempt,
            )
            await _persist_attempt_history(
                repo=repo,
                illustration=illustration,
                blocks=blocks,
                concept_attempt=concept_attempt,
                prompt_attempt=prompt_attempt,
                image_path=history_image_path,
                character_role=character_role,
                prompts=prompts,
                verdict=verdict,
                seed=seed,
            )

            if verdict.ok:
                # Save image and mark as completed
                image_path = await save_image(
                    image_bytes, output_dir, illustration.run_id, illustration.scene_index
                )
                await repo.update_illustration(
                    illustration,
                    state=IllustrationState.COMPLETED,
                    image_path=image_path,
                )
                image_url = (
                    f"/static/runs/{illustration.run_id}/scene_{illustration.scene_index}.png"
                )
                await event_bus.publish(
                    "illustration_completed",
                    {
                        "illustration_id": illustration.id,
                        "scene_index": illustration.scene_index,
                        "image_url": image_url,
                    },
                )
                concept_succeeded = True
                return

            if verdict.problem == "environment" and not env_rethink_used:
                # Fast-path to Agent 4b: the locked environment itself is
                # the renderer blocker. Swap it once (only one swap per
                # branch) and restart the concept with the new environment.
                await _do_environment_rethink(
                    illustration=illustration,
                    blocks=blocks,
                    lock=lock,
                    repo=repo,
                    event_bus=event_bus,
                    claude=claude,
                    source_language=source_language,
                    story_title=story_title,
                    style_guide=style_guide,
                    character_role=character_role,
                    verdict=verdict,
                    transition=transition,
                    concept_attempt=concept_attempt,
                )
                # Refresh local character_role from the row
                # (A4b may have changed them).
                character_role = illustration.character_role
                env_rethink_used = True
                skip_concept_rethink_once = True
                break  # break prompt loop; outer iteration ends without
                # incrementing concept_attempt (the "+1 budget" effect).

            if verdict.problem == "concept":
                # Break inner loop, go to next concept
                break

            # verdict.problem == "prompt" — revise and retry
            if prompt_attempt < MAX_PROMPT_ATTEMPTS_PER_CONCEPT:
                await transition(
                    IllustrationState.REVISING_PROMPTS,
                    concept_attempt=concept_attempt,
                    prompt_attempt=prompt_attempt,
                )
                try:
                    revised = await claude.revise_prompts(
                        current_prompts=prompts,
                        verdict=verdict,
                        current_concept=illustration.current_concept,
                        style_guide=style_guide,
                        character_role=character_role,
                        character_config=char_config,
                        contains_entity=await _current_entity(),
                        prompting_notes=illustration.prompting_notes,
                    )
                except Exception as e:
                    logger.error("revise_prompts failed: %s", e)
                    await transition(
                        IllustrationState.FAILED,
                        error_message=f"Prompt revision failed: {e}",
                    )
                    return
                # Persist prompting_notes_update (auto-pipeline analogue of
                # the manual flow's ManualConceptResponse.prompting_notes_update).
                if revised.prompting_notes_update is not None:
                    illustration = await repo.update_illustration(
                        illustration,
                        prompting_notes=revised.prompting_notes_update,
                    )
                prompts = revised

        if concept_succeeded:
            return

        concept_attempt += 1

    # All automatic attempts exhausted. Before handing off to § 6A
    # manual, give the salvage agent (§ 7.1 Call 8) a chance to accept
    # one of the historical attempts whose only failure was an
    # expression-nuance drift inside the same emotional neighbourhood.
    salvaged = await _do_salvage_review(
        illustration=illustration,
        blocks=blocks,
        lock=lock,
        repo=repo,
        event_bus=event_bus,
        claude=claude,
        output_dir=output_dir,
        source_language=source_language,
        transition=transition,
    )
    if salvaged:
        return

    # Salvage agent did not rescue the branch — enter the § 6A manual
    # chat fallback. The branch task ends here; the rest of the manual
    # flow runs synchronously inside the POST /api/illustrations/{id}/
    # manual/messages handler.
    manual_repo = ManualRepository(repo.session)
    manual_service = ManualService(
        run_repo=repo,
        manual_repo=manual_repo,
        claude=claude,
        runpod=runpod,
        event_bus=event_bus,
        cancel_flag=cancel_flag,
        workflow_template=workflow_template,
        output_dir=output_dir,
        character_config=char_config,
    )
    await manual_service.open_manual_flow(illustration, source_language=source_language)


async def _do_environment_rethink(
    *,
    illustration: Illustration,
    blocks: list[dict],
    lock: asyncio.Lock,
    repo: RunRepository,
    event_bus: EventBus,
    claude: ClaudeClient,
    source_language: str,
    story_title: str,
    style_guide: StyleGuide,
    character_role: str | None,
    verdict,
    transition,
    concept_attempt: int,
) -> None:
    """Run Agent 4b for this illustration: swap the locked environment.

    Reads the run-level context (full environment list, narrative
    entities, main character role) from the DB, calls Agent 4b, then
    persists the resulting changes to the run + illustration + shared
    story_blocks. Publishes the same event sequence Agent 4 publishes
    so the frontend reactively re-renders. Entity handling mirrors
    Agent 4 (see ``run_branch`` for action ↔ registry coherence rules).
    """
    await transition(
        IllustrationState.RETHINKING_ENVIRONMENT,
        concept_attempt=concept_attempt,
        prompt_attempt=1,
    )

    run_obj = await repo.get_run(illustration.run_id)
    if run_obj is None:
        # Should never happen — the branch was created from this run.
        raise RuntimeError("run row vanished mid-branch")

    environments_raw = json.loads(run_obj.environments_json or "[]")
    entities_raw = json.loads(run_obj.narrative_entities_json or "[]")
    main_character_role = run_obj.main_character_role or ""

    if not environments_raw or illustration.scene_index >= len(environments_raw):
        raise RuntimeError(
            f"run {run_obj.id} has no locked environment for scene_index={illustration.scene_index}"
        )
    current_env_dict = environments_raw[illustration.scene_index]
    current_env = Environment(**current_env_dict)

    # Labels of every OTHER slot, normalised. The new env must avoid these.
    used_environments = [
        _normalize_entity_label(env["label"])
        for idx, env in enumerate(environments_raw)
        if idx != illustration.scene_index
    ]

    prev_entity_label = illustration.contains_entity_label

    try:
        result = await claude.rethink_environment(
            source_language=source_language,
            current_scene_index=illustration.scene_index,
            current_concept=illustration.current_concept,
            verdict=verdict,
            current_scene_excerpt=illustration.scene_excerpt,
            story_title=story_title,
            story_blocks=blocks,
            current_paragraph_index=illustration.paragraph_index,
            character_role=character_role,
            main_character_role=main_character_role,
            current_environment=current_env,
            used_environments=used_environments,
            current_entity_label=prev_entity_label,
            narrative_entities=entities_raw,
        )
    except Exception as e:
        logger.error("rethink_environment failed: %s", e)
        await repo.update_illustration(
            illustration,
            state=IllustrationState.FAILED,
            error_message=f"Environment rethink failed: {e}",
        )
        raise

    # Reject env labels that collide with another slot's normalised label.
    new_norm = _normalize_entity_label(result.environment.label)
    if new_norm in used_environments:
        msg = (
            f"Agent 4b proposed environment label "
            f"'{result.environment.label}' which collides with another "
            "slot — rejecting."
        )
        logger.error(msg)
        await repo.update_illustration(
            illustration,
            state=IllustrationState.FAILED,
            error_message=msg,
        )
        raise RuntimeError(msg)

    # Atomic persist: env + entity registry mutation + paragraph rewrite
    # all under the shared lock. Validate entity_action against the live
    # registry first to avoid races with concurrent claim_floating moves
    # from other branches.
    paragraph_index = illustration.paragraph_index
    async with lock:
        run_obj_locked = await repo.get_run(illustration.run_id)
        live_entities = (
            json.loads(run_obj_locked.narrative_entities_json or "[]")
            if run_obj_locked is not None
            else []
        )

        def _find(label: str | None) -> dict | None:
            if label is None:
                return None
            norm = _normalize_entity_label(label)
            for e in live_entities:
                if _normalize_entity_label(e["label"]) == norm:
                    return e
            return None

        action = result.entity_action
        new_label = result.contains_entity_label

        err: str | None = None
        if action == "keep":
            ent = _find(new_label)
            if ent is None:
                err = f"Agent 4b entity_action='keep' references unknown entity {new_label!r}."
            elif ent.get("reserved_for_scene_index") != illustration.scene_index:
                err = (
                    f"Agent 4b entity_action='keep' but entity {new_label!r} "
                    f"is not reserved for this slot."
                )
        elif action == "drop":
            ent = _find(prev_entity_label)
            if ent is None or ent.get("reserved_for_scene_index") != illustration.scene_index:
                err = (
                    "Agent 4b entity_action='drop' but this slot has no "
                    "active entity reservation to drop."
                )
        elif action == "claim_floating":
            ent = _find(new_label)
            if ent is None:
                err = (
                    f"Agent 4b entity_action='claim_floating' references "
                    f"unknown entity {new_label!r}."
                )
            elif ent.get("importance") != "supporting":
                err = (
                    f"Agent 4b may only claim 'supporting' entities; "
                    f"{new_label!r} is {ent.get('importance')!r}."
                )
            elif ent.get("reserved_for_scene_index") is not None:
                err = (
                    f"Agent 4b tried to claim entity {new_label!r} but it "
                    f"is already reserved for scene_index="
                    f"{ent.get('reserved_for_scene_index')}."
                )

        if err is not None:
            logger.error(err)
            await repo.update_illustration(
                illustration,
                state=IllustrationState.FAILED,
                error_message=err,
            )
            raise RuntimeError(err)

        if action == "claim_floating":
            for e in live_entities:
                if _normalize_entity_label(e["label"]) == _normalize_entity_label(new_label):
                    e["reserved_for_scene_index"] = illustration.scene_index
                    break

        environments_raw[illustration.scene_index] = result.environment.model_dump()
        if 0 <= paragraph_index < len(blocks):
            blocks[paragraph_index] = {
                "type": "paragraph",
                "text": result.paragraph_text,
            }
        if run_obj_locked is not None:
            await repo.update_run(
                run_obj_locked,
                environments_json=json.dumps(environments_raw, ensure_ascii=False),
                story_blocks_json=json.dumps(blocks, ensure_ascii=False),
                narrative_entities_json=json.dumps(live_entities, ensure_ascii=False),
            )

    role_changed = result.character_role != character_role
    # Reset prompting_notes — any renderer lesson learned against the
    # previous environment may not apply to the new one.
    await repo.update_illustration(
        illustration,
        character_role=result.character_role,
        current_workflow=f"{result.workflow}.json",
        current_concept=result.concept_localized,
        scene_excerpt=result.scene_excerpt,
        contains_entity_label=new_label,
        environment_label=result.environment.label,
        environment_aspect=result.environment.aspect,
        prompting_notes=None,
    )

    await event_bus.publish(
        "paragraph_updated",
        {"paragraph_index": paragraph_index, "text": result.paragraph_text},
    )
    if role_changed:
        await event_bus.publish(
            "illustration_role_updated",
            {
                "illustration_id": illustration.id,
                "scene_index": illustration.scene_index,
                "character_role": result.character_role,
            },
        )
    if prev_entity_label != new_label:
        new_entity_dict = None
        if new_label:
            for e in live_entities:
                if _normalize_entity_label(e["label"]) == _normalize_entity_label(new_label):
                    new_entity_dict = e
                    break
        await event_bus.publish(
            "illustration_entity_updated",
            {
                "illustration_id": illustration.id,
                "scene_index": illustration.scene_index,
                "contains_entity_label": new_label,
                "entity": new_entity_dict,
            },
        )
    await event_bus.publish(
        "illustration_environment_updated",
        {
            "illustration_id": illustration.id,
            "scene_index": illustration.scene_index,
            "environment": result.environment.model_dump(),
        },
    )


def _load_last_verdict(illustration: Illustration):
    from app.schemas.claude import EvaluateImageResponse

    if illustration.last_verdict_json:
        data = json.loads(illustration.last_verdict_json)
        return EvaluateImageResponse(**data)
    return EvaluateImageResponse(
        ok=False, problem="concept", reasoning="Previous concept failed", suggestion=""
    )


async def _persist_attempt_history(
    *,
    repo: RunRepository,
    illustration: Illustration,
    blocks: list[dict],
    concept_attempt: int,
    prompt_attempt: int,
    image_path: str,
    character_role: str | None,
    prompts,
    verdict,
    seed: int,
) -> None:
    # Agent 3's RevisePromptsResponse carries `revision_summary`; Agent 1's
    # GeneratePromptsResponse does not. Persist the JSON only when present
    # so the column is NULL on the first attempt of each concept (clean
    # signal of "no revision happened here").
    revision_summary_json: str | None = None
    rev_summary = getattr(prompts, "revision_summary", None)
    if rev_summary is not None:
        revision_summary_json = rev_summary.model_dump_json()
    """Append one ``illustration_attempt_history`` row capturing the
    current attempt's snapshot (§ 5). Called once per Agent 2 verdict,
    regardless of ``verdict.ok``.
    """
    paragraph_text = (
        blocks[illustration.paragraph_index]["text"]
        if 0 <= illustration.paragraph_index < len(blocks)
        else ""
    )
    # Resolve environment_kind from the live run row (only label +
    # aspect are denormalised on the illustration; kind lives on
    # runs.environments_json).
    environment_kind = ""
    run_obj = await repo.get_run(illustration.run_id)
    if run_obj is not None and run_obj.environments_json:
        envs = json.loads(run_obj.environments_json)
        if 0 <= illustration.scene_index < len(envs):
            environment_kind = envs[illustration.scene_index].get("kind", "")
    await repo.add_attempt_history(
        illustration_id=illustration.id,
        concept_attempt=concept_attempt,
        prompt_attempt=prompt_attempt,
        image_path=image_path,
        concept_used=illustration.current_concept,
        concept_localized=None,
        paragraph_text=paragraph_text,
        scene_excerpt=illustration.scene_excerpt,
        paragraph_index=illustration.paragraph_index,
        environment_label=illustration.environment_label or "",
        environment_kind=environment_kind,
        environment_aspect=illustration.environment_aspect or "single",
        contains_entity_label=illustration.contains_entity_label,
        character_role=character_role,
        current_workflow=illustration.current_workflow or "",
        positive_prompt=prompts.positive,
        negative_prompt=prompts.negative,
        verdict_json=verdict.model_dump_json(),
        nuance_only_failure=bool(verdict.nuance_only_failure),
        seed=seed,
        revision_summary_json=revision_summary_json,
    )


async def _do_salvage_review(
    *,
    illustration: Illustration,
    blocks: list[dict],
    lock: asyncio.Lock,
    repo: RunRepository,
    event_bus: EventBus,
    claude: ClaudeClient,
    output_dir: str,
    source_language: str,
    transition,
) -> bool:
    """Run Agent 8 over surviving attempt-history rows (§ 7.1 Call 8).

    Returns ``True`` when the salvage path completed the illustration
    (image promoted to canonical path, ``COMPLETED`` emitted); ``False``
    when the branch should fall through to § 6A manual.

    Pre-filter (§ 6): keep only rows with ``nuance_only_failure=true``
    AND matching ``(environment_label, environment_aspect)``,
    ``contains_entity_label`` (null-equal), and ``character_role``
    against the live illustration row.
    """
    history = await repo.get_attempt_history(illustration.id)
    if not history:
        return False

    live_entity_norm = (
        _normalize_entity_label(illustration.contains_entity_label)
        if illustration.contains_entity_label
        else None
    )
    live_env_label_norm = (
        _normalize_entity_label(illustration.environment_label)
        if illustration.environment_label
        else None
    )

    def _row_matches(row: IllustrationAttemptHistory) -> bool:
        if not row.nuance_only_failure:
            return False
        row_env_norm = (
            _normalize_entity_label(row.environment_label) if row.environment_label else None
        )
        if row_env_norm != live_env_label_norm:
            return False
        if row.environment_aspect != (illustration.environment_aspect or "single"):
            return False
        row_entity_norm = (
            _normalize_entity_label(row.contains_entity_label)
            if row.contains_entity_label
            else None
        )
        if row_entity_norm != live_entity_norm:
            return False
        if row.character_role != illustration.character_role:
            return False
        return True

    surviving = [row for row in history if _row_matches(row)]
    if not surviving:
        return False

    # Build the current environment + entity context for Agent 8.
    run_obj = await repo.get_run(illustration.run_id)
    if run_obj is None:
        return False
    environments_raw = json.loads(run_obj.environments_json or "[]")
    if illustration.scene_index >= len(environments_raw):
        return False
    current_env = Environment(**environments_raw[illustration.scene_index])

    entities_raw = json.loads(run_obj.narrative_entities_json or "[]")
    current_entity: dict | None = None
    if illustration.contains_entity_label:
        norm = _normalize_entity_label(illustration.contains_entity_label)
        for e in entities_raw:
            if _normalize_entity_label(e["label"]) == norm:
                current_entity = e
                break

    # Prev / next paragraphs around this illustration's paragraph block.
    paragraph_index = illustration.paragraph_index
    prev_paragraph_text = ""
    next_paragraph_text = ""
    for idx in range(paragraph_index - 1, -1, -1):
        if blocks[idx]["type"] == "paragraph":
            prev_paragraph_text = blocks[idx]["text"]
            break
    for idx in range(paragraph_index + 1, len(blocks)):
        if blocks[idx]["type"] == "paragraph":
            next_paragraph_text = blocks[idx]["text"]
            break
    current_paragraph_text = (
        blocks[paragraph_index]["text"] if 0 <= paragraph_index < len(blocks) else ""
    )

    # Build candidate list (newest-first — history already returns desc).
    candidates: list[SalvageCandidate] = []
    for idx, row in enumerate(surviving):
        try:
            verdict_data = json.loads(row.verdict_json)
        except json.JSONDecodeError:
            verdict_data = {"reasoning": "", "suggestion": ""}
        candidates.append(
            SalvageCandidate(
                candidate_index=idx,
                concept_attempt=row.concept_attempt,
                prompt_attempt=row.prompt_attempt,
                concept_used=row.concept_used,
                paragraph_text=row.paragraph_text,
                scene_excerpt=row.scene_excerpt,
                environment=Environment(
                    label=row.environment_label,
                    kind=row.environment_kind,
                    aspect=row.environment_aspect,
                ),
                contains_entity_label=row.contains_entity_label,
                character_role=row.character_role,
                verdict_reasoning=verdict_data.get("reasoning", ""),
                verdict_suggestion=verdict_data.get("suggestion", ""),
            )
        )

    await transition(IllustrationState.SALVAGE_REVIEW)

    try:
        salvage = await claude.salvage_review(
            source_language=source_language,
            candidates=candidates,
            current_paragraph_text=current_paragraph_text,
            previous_paragraph_text=prev_paragraph_text,
            next_paragraph_text=next_paragraph_text,
            current_environment=current_env,
            current_entity=current_entity,
        )
    except Exception as e:
        # Schema retries exhausted or other error — treat as reject_all
        # so the frontend can leave the diagnostics state, then fall
        # through to the manual flow.
        logger.warning("salvage_review failed (treating as reject_all): %s", e)
        await event_bus.publish(
            "illustration_salvage_resolved",
            {
                "illustration_id": illustration.id,
                "scene_index": illustration.scene_index,
                "outcome": "rejected_all",
                "reasoning": f"salvage agent failed: {e}",
            },
        )
        return False

    if salvage.decision == "reject_all":
        await event_bus.publish(
            "illustration_salvage_resolved",
            {
                "illustration_id": illustration.id,
                "scene_index": illustration.scene_index,
                "outcome": "rejected_all",
                "reasoning": salvage.reasoning,
            },
        )
        return False

    # decision == "accept" — apply the candidate.
    if not 0 <= salvage.candidate_index < len(candidates):
        logger.warning(
            "salvage_review returned out-of-range candidate_index=%d (have %d); rejecting",
            salvage.candidate_index,
            len(candidates),
        )
        await event_bus.publish(
            "illustration_salvage_resolved",
            {
                "illustration_id": illustration.id,
                "scene_index": illustration.scene_index,
                "outcome": "rejected_all",
                "reasoning": "candidate_index out of range",
            },
        )
        return False

    chosen = candidates[salvage.candidate_index]
    chosen_row = surviving[salvage.candidate_index]

    # If an override paragraph is supplied, validate the scene_excerpt
    # substring rule before mutating anything. On failure, fall through
    # to manual exactly like reject_all.
    new_paragraph_text: str | None = None
    if salvage.paragraph_text_override is not None:
        if _normalize_whitespace(chosen.scene_excerpt) not in _normalize_whitespace(
            salvage.paragraph_text_override
        ):
            logger.warning(
                "salvage_review paragraph_text_override missing scene_excerpt verbatim; rejecting",
            )
            await event_bus.publish(
                "illustration_salvage_resolved",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "outcome": "rejected_all",
                    "reasoning": "override missing scene_excerpt",
                },
            )
            return False
        new_paragraph_text = salvage.paragraph_text_override
    else:
        # Use the candidate's historical paragraph as-is.
        new_paragraph_text = chosen.paragraph_text

    # Copy the historical attempt image to the canonical scene slot.
    canonical_relative = f"runs/{illustration.run_id}/scene_{illustration.scene_index}.png"
    await copy_image(chosen_row.image_path, output_dir, canonical_relative)

    # Persist paragraph rewrite if it differs from the current text.
    if new_paragraph_text != current_paragraph_text and 0 <= paragraph_index < len(blocks):
        async with lock:
            blocks[paragraph_index] = {"type": "paragraph", "text": new_paragraph_text}
            run_obj_locked = await repo.get_run(illustration.run_id)
            if run_obj_locked is not None:
                await repo.update_run(
                    run_obj_locked,
                    story_blocks_json=json.dumps(blocks, ensure_ascii=False),
                )
        await event_bus.publish(
            "paragraph_updated",
            {"paragraph_index": paragraph_index, "text": new_paragraph_text},
        )

    # Promote the canonical image_path + mark COMPLETED.
    await repo.update_illustration(
        illustration,
        state=IllustrationState.COMPLETED,
        image_path=canonical_relative,
    )

    payload: dict = {
        "illustration_id": illustration.id,
        "scene_index": illustration.scene_index,
        "outcome": "accepted",
        "candidate_index": salvage.candidate_index,
        "reasoning": salvage.reasoning,
    }
    if salvage.paragraph_text_override is not None:
        payload["paragraph_text_override"] = salvage.paragraph_text_override
    await event_bus.publish("illustration_salvage_resolved", payload)

    image_url = f"/static/runs/{illustration.run_id}/scene_{illustration.scene_index}.png"
    await event_bus.publish(
        "illustration_completed",
        {
            "illustration_id": illustration.id,
            "scene_index": illustration.scene_index,
            "image_url": image_url,
        },
    )
    return True
