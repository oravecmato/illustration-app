"""Per-illustration state machine branch."""

import asyncio
import json
import logging

from app.constants import MAX_CONCEPT_ATTEMPTS, MAX_PROMPT_ATTEMPTS_PER_CONCEPT
from app.db.models import Illustration, IllustrationState
from app.db.repositories import RunRepository
from app.orchestrator.events import EventBus
from app.schemas.claude import StyleGuide
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
) -> None:
    """Run the state machine for a single illustration branch."""
    char_config = character_config or {}
    character_role = illustration.character_role

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
            try:
                rethink_result = await claude.rethink_concept(
                    current_concept=illustration.current_concept,
                    verdict=_load_last_verdict(illustration),
                    scene_excerpt=illustration.scene_excerpt,
                    style_guide=style_guide,
                    character_role=character_role,
                )
                await repo.update_illustration(illustration, current_concept=rethink_result.concept)
            except Exception as e:
                logger.error("rethink_concept failed: %s", e)
                await transition(
                    IllustrationState.FAILED,
                    error_message=f"Concept rethink failed: {e}",
                )
                return

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
