"""Per-illustration state machine branch."""

import asyncio
import json
import logging
import os

from app.constants import MAX_CONCEPT_ATTEMPTS, MAX_PROMPT_ATTEMPTS_PER_CONCEPT
from app.db.models import Illustration, IllustrationState
from app.db.repositories import ManualRepository, RunRepository
from app.orchestrator.events import EventBus
from app.schemas.claude import (
    Environment,
    StyleGuide,
    _normalize_entity_label,
)
from app.services.claude import ClaudeClient
from app.services.images import save_image
from app.services.manual import ManualService
from app.services.runpod import RunPodClient
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

            # Build workflow with current prompts + style guide
            replacements = {
                "POSITIVE_PROMPT": prompts.positive,
                "NEGATIVE_PROMPT": prompts.negative,
                "CHARACTER_LORA": char_lora,
                "STYLE_POSITIVE_PROMPT": style_guide.overall_style_positive,
                "STYLE_NEGATIVE_PROMPT": style_guide.overall_style_negative,
            }
            workflow, _ = replace_placeholders(workflow_template_to_use, replacements)

            try:
                image_bytes = await runpod.run_workflow(workflow)
            except Exception as e:
                logger.error("runpod.run_workflow failed: %s", e)
                await transition(
                    IllustrationState.FAILED,
                    error_message=f"Image rendering failed: {e}",
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
                    prompts = await claude.revise_prompts(
                        current_prompts=prompts,
                        verdict=verdict,
                        current_concept=illustration.current_concept,
                        style_guide=style_guide,
                        character_role=character_role,
                        character_config=char_config,
                        contains_entity=await _current_entity(),
                    )
                except Exception as e:
                    logger.error("revise_prompts failed: %s", e)
                    await transition(
                        IllustrationState.FAILED,
                        error_message=f"Prompt revision failed: {e}",
                    )
                    return

        if concept_succeeded:
            return

        concept_attempt += 1

    # All automatic attempts exhausted — enter the § 6A manual chat
    # fallback instead of going straight to FAILED. The branch task ends
    # here; the rest of the manual flow runs synchronously inside the
    # POST /api/illustrations/{id}/manual/messages handler.
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
    await repo.update_illustration(
        illustration,
        character_role=result.character_role,
        current_workflow=f"{result.workflow}.json",
        current_concept=result.concept_localized,
        scene_excerpt=result.scene_excerpt,
        contains_entity_label=new_label,
        environment_label=result.environment.label,
        environment_aspect=result.environment.aspect,
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
