"""Per-illustration state machine branch."""

import asyncio
import json
import logging

from app.constants import MAX_CONCEPT_ATTEMPTS, MAX_PROMPT_ATTEMPTS_PER_CONCEPT
from app.db.models import Illustration, IllustrationState
from app.db.repositories import RunRepository
from app.orchestrator.events import EventBus
from app.schemas.claude import Companion, StyleGuide, companion_in_pool
from app.services.claude import ClaudeClient
from app.services.images import save_image
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
    story_blocks: list[dict] | None = None,
    story_lock: asyncio.Lock | None = None,
    companions_pool: list[str] | None = None,
) -> None:
    """Run the state machine for a single illustration branch."""
    char_config = character_config or {}
    character_role = illustration.character_role
    blocks = story_blocks if story_blocks is not None else []
    lock = story_lock or asyncio.Lock()
    pool = companions_pool or []

    def _current_companion() -> Companion | None:
        if illustration.companion_description and illustration.companion_interaction:
            return Companion(
                description=illustration.companion_description,
                interaction=illustration.companion_interaction,
            )
        return None

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

    for concept_attempt in range(1, MAX_CONCEPT_ATTEMPTS + 1):
        if cancel_flag.is_set():
            await transition(IllustrationState.CANCELLED)
            return

        if concept_attempt > 1:
            # Rethink concept
            await transition(
                IllustrationState.RETHINKING_CONCEPT,
                concept_attempt=concept_attempt,
                prompt_attempt=1,
            )
            prev_companion = _current_companion()
            try:
                rethink_result = await claude.rethink_concept(
                    current_concept=illustration.current_concept,
                    verdict=_load_last_verdict(illustration),
                    current_scene_excerpt=illustration.scene_excerpt,
                    story_title=story_title,
                    story_blocks=blocks,
                    current_paragraph_index=illustration.paragraph_index,
                    character_role=character_role,
                    current_companion=prev_companion,
                    companions_pool=pool,
                )
            except Exception as e:
                logger.error("rethink_concept failed: %s", e)
                await transition(
                    IllustrationState.FAILED,
                    error_message=f"Concept rethink failed: {e}",
                )
                return

            # Server-side pool fidelity: Agent 4 may only set a companion
            # whose description is present in the agreed pool. If the pool
            # is empty, the companion must be null.
            new_companion: Companion | None = rethink_result.companion
            if new_companion is not None and not companion_in_pool(new_companion.description, pool):
                msg = (
                    f"Agent 4 proposed companion '{new_companion.description}' that is "
                    f"not in the agreed pool {pool}."
                )
                logger.error(msg)
                await transition(
                    IllustrationState.FAILED,
                    error_message=msg,
                )
                return

            # Apply rewrite: mutate the shared in-memory story_blocks,
            # persist the new story_blocks_json on the run, update the
            # illustration's excerpt + concept + companion, then publish
            # paragraph_updated BEFORE the next illustration_state event
            # so the frontend renders the new paragraph before clearing
            # its regenerating-skeleton (§ 9.5). Publish
            # illustration_companion_updated only when the companion
            # actually changed.
            paragraph_index = illustration.paragraph_index
            async with lock:
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
                    )
            await repo.update_illustration(
                illustration,
                current_concept=rethink_result.concept,
                scene_excerpt=rethink_result.scene_excerpt,
                companion_description=(
                    new_companion.description if new_companion is not None else None
                ),
                companion_interaction=(
                    new_companion.interaction if new_companion is not None else None
                ),
            )
            await event_bus.publish(
                "paragraph_updated",
                {
                    "paragraph_index": paragraph_index,
                    "text": rethink_result.paragraph_text,
                },
            )
            companion_changed = (prev_companion is None) != (new_companion is None) or (
                prev_companion is not None
                and new_companion is not None
                and (
                    prev_companion.description != new_companion.description
                    or prev_companion.interaction != new_companion.interaction
                )
            )
            if companion_changed:
                await event_bus.publish(
                    "illustration_companion_updated",
                    {
                        "illustration_id": illustration.id,
                        "scene_index": illustration.scene_index,
                        "companion": (
                            {
                                "description": new_companion.description,
                                "interaction": new_companion.interaction,
                            }
                            if new_companion is not None
                            else None
                        ),
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
                companion=_current_companion(),
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

            # Build workflow with current prompts + style guide
            replacements = {
                "POSITIVE_PROMPT": prompts.positive,
                "NEGATIVE_PROMPT": prompts.negative,
                "CHARACTER_LORA": char_lora,
                "STYLE_POSITIVE_PROMPT": style_guide.overall_style_positive,
                "STYLE_NEGATIVE_PROMPT": style_guide.overall_style_negative,
            }
            workflow, _ = replace_placeholders(workflow_template, replacements)

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
                    companion=_current_companion(),
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
                        companion=_current_companion(),
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

    # All attempts exhausted
    await transition(
        IllustrationState.FAILED,
        error_message="All concept and prompt attempts exhausted",
    )
    await event_bus.publish(
        "illustration_failed",
        {
            "illustration_id": illustration.id,
            "scene_index": illustration.scene_index,
            "error_message": illustration.error_message,
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
