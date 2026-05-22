"""Top-level run orchestration."""

import asyncio
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.constants import MAX_CONCURRENT_BRANCHES
from app.db.models import IllustrationState, Run, RunStatus
from app.db.repositories import RunRepository
from app.orchestrator.branch import run_branch
from app.orchestrator.events import EventBus
from app.services.claude import ClaudeClient, ClaudeError
from app.services.runpod import RunPodClient

logger = logging.getLogger(__name__)


async def run_pipeline(
    run: Run,
    repo: RunRepository,
    claude: ClaudeClient,
    runpod: RunPodClient,
    event_bus: EventBus,
    workflow_template: dict,
    output_dir: str,
    cancel_flag: asyncio.Event,
    character_config: dict | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Orchestrate the full pipeline for a run."""
    char_config = character_config or {}

    try:
        # Step 0: Analyze story
        try:
            analyze_result = await claude.analyze_story(run.story_text)
        except ClaudeError as e:
            logger.error("Step 0 (analyze_story) failed: %s", e)
            await repo.update_run(
                run,
                status=RunStatus.FAILED,
                error_code="STEP0_FAILED",
                error_message=str(e),
            )
            await event_bus.publish(
                "run_failed", {"error_code": "STEP0_FAILED", "error_message": str(e)}
            )
            return

        style_guide = analyze_result.style_guide
        illustrations_data = analyze_result.illustrations  # already truncated by validator

        # Empty illustrations → NO_SUITABLE_SCENES (valid terminal state)
        if not illustrations_data:
            msg = "The story contains no scenes suitable for single-character illustration."
            await repo.update_run(
                run,
                status=RunStatus.FAILED,
                illustration_count=0,
                error_code="NO_SUITABLE_SCENES",
                error_message=msg,
            )
            await event_bus.publish(
                "run_failed", {"error_code": "NO_SUITABLE_SCENES", "error_message": msg}
            )
            return

        await repo.update_run(
            run,
            style_guide_json=style_guide.model_dump_json(),
            illustration_count=len(illustrations_data),
        )
        await event_bus.publish(
            "style_guide_ready",
            {
                "style_guide": style_guide.model_dump(),
                "illustration_count": len(illustrations_data),
            },
        )

        # Create illustration records
        illustrations = []
        for item in illustrations_data:
            ill = await repo.create_illustration(
                run_id=run.id,
                scene_index=item.scene_index,
                scene_excerpt=item.scene_excerpt,
                concept=item.concept,
                character_role=item.character_role,
            )
            illustrations.append(ill)

        # Update snapshot with initial illustration state
        _update_snapshot(event_bus, run, illustrations)

        # Run branches in parallel with semaphore
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_BRANCHES)

        async def run_with_semaphore(ill):
            async with semaphore:
                # Each branch gets its own session to avoid concurrent session issues
                if session_factory is not None:
                    async with session_factory() as branch_session:
                        branch_repo = RunRepository(branch_session)
                        # Re-fetch illustration in this session
                        from sqlalchemy import select

                        from app.db.models import Illustration

                        result = await branch_session.execute(
                            select(Illustration).where(Illustration.id == ill.id)
                        )
                        branch_ill = result.scalar_one()
                        await run_branch(
                            illustration=branch_ill,
                            style_guide=style_guide,
                            workflow_template=workflow_template,
                            output_dir=output_dir,
                            claude=claude,
                            runpod=runpod,
                            repo=branch_repo,
                            event_bus=event_bus,
                            cancel_flag=cancel_flag,
                            character_config=char_config,
                        )
                        # Sync state back to the in-memory illustration for counting
                        ill.state = branch_ill.state
                else:
                    await run_branch(
                        illustration=ill,
                        style_guide=style_guide,
                        workflow_template=workflow_template,
                        output_dir=output_dir,
                        claude=claude,
                        runpod=runpod,
                        repo=repo,
                        event_bus=event_bus,
                        cancel_flag=cancel_flag,
                        character_config=char_config,
                    )

        await asyncio.gather(*[run_with_semaphore(ill) for ill in illustrations])

        # Count outcomes
        completed = sum(1 for ill in illustrations if ill.state == IllustrationState.COMPLETED)
        failed = sum(1 for ill in illustrations if ill.state == IllustrationState.FAILED)
        cancelled = sum(1 for ill in illustrations if ill.state == IllustrationState.CANCELLED)

        if cancelled > 0 and cancel_flag.is_set():
            await repo.update_run(
                run,
                status=RunStatus.CANCELLED,
                completed_count=completed,
                failed_count=failed,
            )
            await event_bus.publish("run_cancelled", {})
        else:
            await repo.update_run(
                run,
                status=RunStatus.COMPLETED,
                completed_count=completed,
                failed_count=failed,
            )
            await event_bus.publish("run_completed", {"completed": completed, "failed": failed})

    except Exception as e:
        logger.error("Pipeline failed with unhandled exception: %s", e)
        await repo.update_run(
            run,
            status=RunStatus.FAILED,
            error_code="INTERNAL_ERROR",
            error_message=str(e),
        )
        await event_bus.publish(
            "run_failed", {"error_code": "INTERNAL_ERROR", "error_message": str(e)}
        )


def _update_snapshot(event_bus: EventBus, run: Run, illustrations) -> None:

    style_guide_data = None
    if run.style_guide_json:
        style_guide_data = json.loads(run.style_guide_json)

    event_bus.set_snapshot(
        {
            "run": {
                "id": run.id,
                "status": run.status,
                "story_text": run.story_text,
                "style_guide": style_guide_data,
                "illustration_count": run.illustration_count,
                "completed_count": run.completed_count,
                "failed_count": run.failed_count,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "updated_at": run.updated_at.isoformat() if run.updated_at else None,
                "error_code": run.error_code,
                "error_message": run.error_message,
            },
            "illustrations": [
                {
                    "id": ill.id,
                    "scene_index": ill.scene_index,
                    "scene_excerpt": ill.scene_excerpt,
                    "character_role": ill.character_role,
                    "current_concept": ill.current_concept,
                    "state": ill.state,
                    "concept_attempt": ill.concept_attempt,
                    "prompt_attempt": ill.prompt_attempt,
                    "image_url": None,
                }
                for ill in illustrations
            ],
        }
    )
