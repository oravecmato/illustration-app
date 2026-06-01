"""Top-level run orchestration.

The story has already been authored by Agent 0b before this pipeline runs.
``run.style_guide_json`` is populated and the ``illustrations`` rows already
exist with ``state == PENDING``. This pipeline only orchestrates the
per-illustration branches (Agents 1–4 + RunPod).
"""

import asyncio
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.constants import MAX_CONCURRENT_BRANCHES
from app.db.models import IllustrationState, Run, RunStatus
from app.db.repositories import RunRepository
from app.orchestrator.branch import run_branch
from app.orchestrator.events import EventBus
from app.schemas.claude import StyleGuide
from app.services.claude import ClaudeClient
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
    """Orchestrate the per-illustration branches for an already-authored run."""
    char_config = character_config or {}

    try:
        style_guide = StyleGuide(**json.loads(run.style_guide_json))
        illustrations = await repo.get_illustrations_for_run(run.id)
        # Shared story context: branches read and write paragraph texts
        # during Agent 4 (rethink_concept) cycles. The lock serializes
        # concurrent read-modify-write of run.story_blocks_json.
        story_blocks: list[dict] = (
            json.loads(run.story_blocks_json) if run.story_blocks_json else []
        )
        story_lock = asyncio.Lock()

        if not illustrations:
            # build_story validator guarantees at least 1, but be defensive.
            msg = "Run has no illustrations to render."
            await repo.update_run(
                run,
                status=RunStatus.FAILED,
                error_code="INTERNAL_ERROR",
                error_message=msg,
            )
            await event_bus.publish(
                "run_failed", {"error_code": "INTERNAL_ERROR", "error_message": msg}
            )
            return

        # Refresh snapshot with starting illustration state.
        _update_snapshot(event_bus, run, illustrations)

        # Pre-warm the Anthropic ephemeral cache for reference docs so
        # the first parallel batch of agent calls hits cache instead of
        # racing to create it. Serial single request; safe to no-op
        # when references are disabled (e.g. in tests).
        await claude.warmup_reference_cache()

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
                            story_title=run.story_title,
                            source_language=run.source_language,
                            story_blocks=story_blocks,
                            story_lock=story_lock,
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
                        story_title=run.story_title,
                        source_language=run.source_language,
                        story_blocks=story_blocks,
                        story_lock=story_lock,
                    )

        await asyncio.gather(*[run_with_semaphore(ill) for ill in illustrations])

        # Re-read illustrations from DB so we observe any state writes
        # made by the manual fallback (§ 6A) during the auto branches.
        illustrations = await repo.get_illustrations_for_run(run.id)

        # If any illustration is still in a MANUAL_* state, the run stays
        # in RUNNING and the manual-chat endpoint will finalize the run
        # once the user resolves all manual sessions (§ 6A.3).
        manual_states = {
            IllustrationState.MANUAL_CHATTING,
            IllustrationState.MANUAL_GENERATING_PROMPTS,
            IllustrationState.MANUAL_RENDERING,
        }
        if any(ill.state in manual_states for ill in illustrations):
            return

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
    style_guide_data = json.loads(run.style_guide_json) if run.style_guide_json else None
    story_blocks = json.loads(run.story_blocks_json) if run.story_blocks_json else []

    event_bus.set_snapshot(
        {
            "run": {
                "id": run.id,
                "session_id": run.session_id,
                "status": run.status,
                "story_title": run.story_title,
                "story_blocks": story_blocks,
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
                    "paragraph_index": ill.paragraph_index,
                    "character_role": ill.character_role,
                    "current_concept": ill.current_concept,
                    "state": ill.state,
                    "concept_attempt": ill.concept_attempt,
                    "prompt_attempt": ill.prompt_attempt,
                    "image_url": None,
                    "contains_entity_label": ill.contains_entity_label,
                }
                for ill in illustrations
            ],
        }
    )
