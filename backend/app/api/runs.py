"""API endpoints: GET runs, SSE, cancel.

Runs are no longer created directly by this router — they are created by the
session-finalize endpoint in ``app.api.sessions`` once Agent 0b has produced
the story and scenes.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Illustration,
    IllustrationConceptTranslation,
    IllustrationState,
    Run,
    RunStatus,
    StoryBlockTranslation,
    StoryTranslation,
)
from app.db.repositories import ManualRepository, RunRepository
from app.db.session import get_session_factory
from app.orchestrator.events import EventBus
from app.schemas.api import (
    IllustrationResponse,
    ManualMessageResponse,
    ManualSessionSummary,
    RunDetailResponse,
    RunResponse,
    TranslateRequest,
    TranslateResponse,
    TranslationItemResponse,
)
from app.schemas.claude import Companion, StyleGuide
from app.services.claude import ClaudeClient
from app.services.runpod import RunPodClient
from app.utils.hashing import compute_source_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

# In-memory registry of active run buses and cancel flags. Shared with the
# sessions router so that finalize() can register the bus/flag for the
# spawned pipeline before this router serves SSE for that run id.
_run_buses: dict[str, EventBus] = {}
_cancel_flags: dict[str, asyncio.Event] = {}

# Set by main.py during startup
_claude_client: ClaudeClient | None = None
_runpod_client: RunPodClient | None = None
_workflow_template: dict | None = None
_output_dir: str | None = None
_character_config: dict | None = None


def set_clients(
    claude: ClaudeClient,
    runpod: RunPodClient,
    workflow: dict,
    output_dir: str,
    character_config: dict | None = None,
) -> None:
    global _claude_client, _runpod_client, _workflow_template, _output_dir, _character_config
    _claude_client = claude
    _runpod_client = runpod
    _workflow_template = workflow
    _output_dir = output_dir
    _character_config = character_config


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _compute_translation_state(
    source_text: str,
    translation_hash: str | None,
) -> str:
    """Compute translation state by comparing current source hash with stored hash.

    Returns:
        - "fresh": translation exists and hash matches
        - "stale": translation exists but hash doesn't match
        - "missing": no translation found
    """
    if translation_hash is None:
        return "missing"
    current_hash = compute_source_hash(source_text)
    return "fresh" if translation_hash == current_hash else "stale"


def _build_run_response(
    run: Run,
    language: str = "sk",
    story_trans: StoryTranslation | None = None,
    block_trans_map: dict[int, StoryBlockTranslation] | None = None,
) -> RunResponse:
    """Build RunResponse with translation support.

    Args:
        run: The run model
        language: Target language code (sk, cs, en)
        story_trans: StoryTranslation for this language (if exists)
        block_trans_map: Map of paragraph_index -> StoryBlockTranslation
    """
    style_guide = StyleGuide(**json.loads(run.style_guide_json))
    story_blocks = json.loads(run.story_blocks_json)

    # If language matches source, all states are "source"
    if language == run.source_language:
        # Apply no translations, mark everything as source. Inject `index`
        # (block array position) so the frontend can locate each paragraph
        # by its persistent paragraph_index — the same index used by
        # paragraph_updated events and the translate API.
        for block_index, block in enumerate(story_blocks):
            if block["type"] == "paragraph":
                block["index"] = block_index
                block["translation_state"] = "source"
        return RunResponse(
            id=run.id,
            session_id=run.session_id,
            status=run.status,
            source_language=run.source_language,
            language=language,
            topic_short=run.topic_short,
            story_title=run.story_title,
            story_title_translation_state="source",
            story_topic_description=run.story_topic_description,
            story_topic_description_translation_state="source",
            story_blocks=story_blocks,
            style_guide=style_guide,
            illustration_count=run.illustration_count,
            completed_count=run.completed_count,
            failed_count=run.failed_count,
            created_at=run.created_at,
            updated_at=run.updated_at,
            error_code=run.error_code,
            error_message=run.error_message,
        )

    # Language differs from source - apply translations and compute states
    story_title = run.story_title
    story_title_state = "missing"
    story_topic_desc = run.story_topic_description
    story_topic_desc_state = "missing"

    if story_trans:
        if story_trans.story_title:
            story_title = story_trans.story_title
            story_title_state = _compute_translation_state(
                run.story_title, story_trans.story_title_source_hash
            )
        if story_trans.story_topic_description:
            story_topic_desc = story_trans.story_topic_description
            story_topic_desc_state = _compute_translation_state(
                run.story_topic_description, story_trans.story_topic_description_source_hash
            )

    # Apply paragraph translations. paragraph_index is the block's array
    # position in story_blocks (see SessionService.finalize); inject `index`
    # so the frontend can look up the paragraph deterministically.
    block_trans_map = block_trans_map or {}
    for block_index, block in enumerate(story_blocks):
        if block["type"] != "paragraph":
            continue
        block["index"] = block_index
        trans = block_trans_map.get(block_index)
        if trans and trans.text:
            # Compare against source text before overwriting.
            block["translation_state"] = _compute_translation_state(
                block["text"], trans.text_source_hash
            )
            block["text"] = trans.text
        else:
            block["translation_state"] = "missing"

    return RunResponse(
        id=run.id,
        session_id=run.session_id,
        status=run.status,
        source_language=run.source_language,
        language=language,
        topic_short=run.topic_short,
        story_title=story_title,
        story_title_translation_state=story_title_state,
        story_topic_description=story_topic_desc,
        story_topic_description_translation_state=story_topic_desc_state,
        story_blocks=story_blocks,
        style_guide=style_guide,
        illustration_count=run.illustration_count,
        completed_count=run.completed_count,
        failed_count=run.failed_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
        error_code=run.error_code,
        error_message=run.error_message,
    )


def _build_illustration_response(
    ill,
    language: str | None = None,
    source_language: str | None = None,
    concept_trans: IllustrationConceptTranslation | None = None,
    manual_session: ManualSessionSummary | None = None,
) -> IllustrationResponse:
    """Build IllustrationResponse with translation support.

    Args:
        ill: The illustration model
        language: Target language code (for translation state computation)
        source_language: Source language of the run
        concept_trans: IllustrationConceptTranslation for this language (if exists).
            Holds translations for both ``concept`` and ``scene_excerpt``;
            either field may be null when only one has been translated yet.
    """
    image_url = None
    if ill.image_path:
        image_url = f"/static/{ill.image_path}"
    companion = None
    if ill.companion_description and ill.companion_interaction:
        companion = Companion(
            description=ill.companion_description,
            interaction=ill.companion_interaction,
        )

    current_concept = ill.current_concept
    concept_state = None
    scene_excerpt = ill.scene_excerpt
    scene_excerpt_state = None

    if language and source_language:
        if language == source_language:
            concept_state = "source"
            scene_excerpt_state = "source"
        else:
            if concept_trans and concept_trans.concept_localized:
                concept_state = _compute_translation_state(
                    ill.current_concept, concept_trans.concept_localized_source_hash
                )
                current_concept = concept_trans.concept_localized
            else:
                concept_state = "missing"

            if concept_trans and concept_trans.scene_excerpt_localized:
                scene_excerpt_state = _compute_translation_state(
                    ill.scene_excerpt, concept_trans.scene_excerpt_localized_source_hash
                )
                scene_excerpt = concept_trans.scene_excerpt_localized
            else:
                scene_excerpt_state = "missing"

    return IllustrationResponse(
        id=ill.id,
        scene_index=ill.scene_index,
        scene_excerpt=scene_excerpt,
        scene_excerpt_translation_state=scene_excerpt_state,
        paragraph_index=ill.paragraph_index,
        character_role=ill.character_role,
        current_workflow=ill.current_workflow,
        current_concept=current_concept,
        current_concept_translation_state=concept_state,
        state=ill.state,
        concept_attempt=ill.concept_attempt,
        prompt_attempt=ill.prompt_attempt,
        image_url=image_url,
        companion=companion,
        manual_attempts=ill.manual_attempts or 0,
        manual_session=manual_session,
    )


async def _load_manual_session_summary(
    session: AsyncSession, illustration
) -> ManualSessionSummary | None:
    """Load manual chat rows for an illustration if it has entered the
    manual flow (§ 6A). Returns None for illustrations that never did.
    """
    if illustration.manual_attempts == 0 and illustration.state not in (
        IllustrationState.MANUAL_CHATTING,
        IllustrationState.MANUAL_GENERATING_PROMPTS,
        IllustrationState.MANUAL_RENDERING,
    ):
        # Skip a DB roundtrip for the common case.
        return None
    manual_repo = ManualRepository(session)
    rows = await manual_repo.get_messages(illustration.id)
    if not rows:
        return None
    ms = await manual_repo.get_manual_session(illustration.id)
    last_image_url = None
    sub_phase = "concept_design"
    if ms is not None:
        if ms.last_manual_image_path:
            last_image_url = f"/static/{ms.last_manual_image_path}"
        sub_phase = ms.sub_phase or "concept_design"
    return ManualSessionSummary(
        messages=[
            ManualMessageResponse(
                id=row.id,
                role=row.role,
                content=row.content,
                image_url=row.image_url,
                manual_attempt_index=row.manual_attempt_index,
                concept_used=row.concept_used,
                positive_prompt=row.positive_prompt,
                negative_prompt=row.negative_prompt,
                created_at=row.created_at,
            )
            for row in rows
        ],
        manual_attempts=illustration.manual_attempts or 0,
        last_image_url=last_image_url,
        sub_phase=sub_phase,
    )


async def _build_snapshot(
    run: Run,
    illustrations: list,
    session: AsyncSession,
    language: str = "sk",
) -> dict:
    """Build an SSE snapshot from current DB state (matches RunDetailResponse shape).

    Applies translations for the requested language so that SSE subscribers
    see the same translated payload they'd get from GET /api/runs/{id}?lang=…
    Without this, the snapshot sent on subscribe would clobber any
    translated state the frontend just fetched.
    """
    if language == run.source_language:
        manual_summaries = {
            ill.id: await _load_manual_session_summary(session, ill) for ill in illustrations
        }
        return {
            "run": _build_run_response(run, language=language).model_dump(mode="json"),
            "illustrations": [
                _build_illustration_response(
                    ill,
                    language=language,
                    source_language=run.source_language,
                    manual_session=manual_summaries.get(ill.id),
                ).model_dump(mode="json")
                for ill in illustrations
            ],
        }

    story_trans = (
        await session.execute(
            select(StoryTranslation).where(
                StoryTranslation.run_id == run.id,
                StoryTranslation.language == language,
            )
        )
    ).scalar_one_or_none()

    block_trans_list = (
        (
            await session.execute(
                select(StoryBlockTranslation).where(
                    StoryBlockTranslation.run_id == run.id,
                    StoryBlockTranslation.language == language,
                )
            )
        )
        .scalars()
        .all()
    )
    block_trans_map = {bt.paragraph_index: bt for bt in block_trans_list}

    concept_trans_list = (
        (
            await session.execute(
                select(IllustrationConceptTranslation)
                .join(
                    Illustration, IllustrationConceptTranslation.illustration_id == Illustration.id
                )
                .where(
                    Illustration.run_id == run.id,
                    IllustrationConceptTranslation.language == language,
                )
            )
        )
        .scalars()
        .all()
    )
    concept_trans_map = {ct.illustration_id: ct for ct in concept_trans_list}

    manual_summaries = {
        ill.id: await _load_manual_session_summary(session, ill) for ill in illustrations
    }
    return {
        "run": _build_run_response(
            run, language=language, story_trans=story_trans, block_trans_map=block_trans_map
        ).model_dump(mode="json"),
        "illustrations": [
            _build_illustration_response(
                ill,
                language=language,
                source_language=run.source_language,
                concept_trans=concept_trans_map.get(ill.id),
                manual_session=manual_summaries.get(ill.id),
            ).model_dump(mode="json")
            for ill in illustrations
        ],
    }


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: str,
    lang: str = "sk",
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RunDetailResponse:
    """Get run details with optional language translation.

    Args:
        run_id: The run ID
        lang: Target language code (sk, cs, en). Defaults to 'sk'.
        session: Database session

    Returns:
        Run details with translations applied if lang != source_language
    """
    repo = RunRepository(session)
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    illustrations = await repo.get_illustrations_for_run(run_id)

    # If lang == source_language, no need to fetch translations
    if lang == run.source_language:
        manual_summaries = {
            ill.id: await _load_manual_session_summary(session, ill) for ill in illustrations
        }
        return RunDetailResponse(
            run=_build_run_response(run, language=lang),
            illustrations=[
                _build_illustration_response(
                    ill,
                    language=lang,
                    source_language=run.source_language,
                    manual_session=manual_summaries.get(ill.id),
                )
                for ill in illustrations
            ],
        )

    # Fetch translations for this language
    story_trans = await session.execute(
        select(StoryTranslation).where(
            StoryTranslation.run_id == run_id,
            StoryTranslation.language == lang,
        )
    )
    story_trans = story_trans.scalar_one_or_none()

    # Fetch block translations
    block_trans_result = await session.execute(
        select(StoryBlockTranslation).where(
            StoryBlockTranslation.run_id == run_id,
            StoryBlockTranslation.language == lang,
        )
    )
    block_trans_list = block_trans_result.scalars().all()
    block_trans_map = {bt.paragraph_index: bt for bt in block_trans_list}

    # Fetch concept translations (join with illustrations to filter by run_id)
    concept_trans_result = await session.execute(
        select(IllustrationConceptTranslation)
        .join(Illustration, IllustrationConceptTranslation.illustration_id == Illustration.id)
        .where(
            Illustration.run_id == run_id,
            IllustrationConceptTranslation.language == lang,
        )
    )
    concept_trans_list = concept_trans_result.scalars().all()
    concept_trans_map = {ct.illustration_id: ct for ct in concept_trans_list}

    manual_summaries = {
        ill.id: await _load_manual_session_summary(session, ill) for ill in illustrations
    }
    return RunDetailResponse(
        run=_build_run_response(
            run, language=lang, story_trans=story_trans, block_trans_map=block_trans_map
        ),
        illustrations=[
            _build_illustration_response(
                ill,
                language=lang,
                source_language=run.source_language,
                concept_trans=concept_trans_map.get(ill.id),
                manual_session=manual_summaries.get(ill.id),
            )
            for ill in illustrations
        ],
    )


@router.post("/{run_id}/translations", response_model=TranslateResponse)
async def translate_run(
    run_id: str,
    body: TranslateRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TranslateResponse:
    """Request translations for specific run items.

    This endpoint:
    1. Filters out items that already have fresh translations
    2. Calls Agent 5 to translate remaining items
    3. Persists translations to DB
    4. Emits SSE event for translations_refreshed
    5. Returns all translations (both cached and fresh)

    Args:
        run_id: The run ID
        body: Translation request with language and items to translate
        session: Database session

    Returns:
        All translations for the requested items (with source hashes)
    """
    if _claude_client is None:
        raise HTTPException(status_code=500, detail="Claude client not initialized")

    repo = RunRepository(session)
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    illustrations = await repo.get_illustrations_for_run(run_id)
    story_blocks = json.loads(run.story_blocks_json)

    # Fetch existing translations
    story_trans = await session.execute(
        select(StoryTranslation).where(
            StoryTranslation.run_id == run_id,
            StoryTranslation.language == body.language,
        )
    )
    story_trans = story_trans.scalar_one_or_none()

    block_trans_result = await session.execute(
        select(StoryBlockTranslation).where(
            StoryBlockTranslation.run_id == run_id,
            StoryBlockTranslation.language == body.language,
        )
    )
    block_trans_map = {bt.paragraph_index: bt for bt in block_trans_result.scalars().all()}

    concept_trans_result = await session.execute(
        select(IllustrationConceptTranslation)
        .join(Illustration, IllustrationConceptTranslation.illustration_id == Illustration.id)
        .where(
            Illustration.run_id == run_id,
            IllustrationConceptTranslation.language == body.language,
        )
    )
    concept_trans_map = {ct.illustration_id: ct for ct in concept_trans_result.scalars().all()}

    # Build source data lookup. paragraph_index is the block's array position
    # in story_blocks — same convention as SessionService.finalize.
    illustration_by_scene = {ill.scene_index: ill for ill in illustrations}
    paragraph_by_index = {
        block_index: block.get("text", "")
        for block_index, block in enumerate(story_blocks)
        if block["type"] == "paragraph"
    }

    # Filter items that need translation (missing or stale)
    items_to_translate = []
    all_items_response = []

    for item in body.items:
        if item.kind == "story_title":
            source_text = run.story_title
            source_hash = compute_source_hash(source_text)
            if (
                story_trans
                and story_trans.story_title
                and story_trans.story_title_source_hash == source_hash
            ):
                # Already fresh
                all_items_response.append(
                    TranslationItemResponse(
                        kind="story_title",
                        text=story_trans.story_title,
                        source_hash=source_hash,
                    )
                )
            else:
                items_to_translate.append({"kind": "story_title", "source_text": source_text})

        elif item.kind == "story_topic_description":
            source_text = run.story_topic_description
            source_hash = compute_source_hash(source_text)
            if (
                story_trans
                and story_trans.story_topic_description
                and story_trans.story_topic_description_source_hash == source_hash
            ):
                all_items_response.append(
                    TranslationItemResponse(
                        kind="story_topic_description",
                        text=story_trans.story_topic_description,
                        source_hash=source_hash,
                    )
                )
            else:
                items_to_translate.append(
                    {"kind": "story_topic_description", "source_text": source_text}
                )

        elif item.kind == "paragraph":
            if item.paragraph_index is None:
                continue
            source_text = paragraph_by_index.get(item.paragraph_index, "")
            if not source_text:
                continue
            source_hash = compute_source_hash(source_text)
            existing = block_trans_map.get(item.paragraph_index)
            if existing and existing.text and existing.text_source_hash == source_hash:
                all_items_response.append(
                    TranslationItemResponse(
                        kind="paragraph",
                        paragraph_index=item.paragraph_index,
                        text=existing.text,
                        source_hash=source_hash,
                    )
                )
            else:
                items_to_translate.append(
                    {
                        "kind": "paragraph",
                        "paragraph_index": item.paragraph_index,
                        "source_text": source_text,
                    }
                )

        elif item.kind == "illustration_concept":
            if item.scene_index is None:
                continue
            ill = illustration_by_scene.get(item.scene_index)
            if not ill:
                continue
            source_text = ill.current_concept
            source_hash = compute_source_hash(source_text)
            existing = concept_trans_map.get(ill.id)
            if (
                existing
                and existing.concept_localized
                and existing.concept_localized_source_hash == source_hash
            ):
                all_items_response.append(
                    TranslationItemResponse(
                        kind="illustration_concept",
                        scene_index=item.scene_index,
                        text=existing.concept_localized,
                        source_hash=source_hash,
                    )
                )
            else:
                items_to_translate.append(
                    {
                        "kind": "illustration_concept",
                        "scene_index": item.scene_index,
                        "source_text": source_text,
                    }
                )

        elif item.kind == "scene_excerpt":
            if item.scene_index is None:
                continue
            ill = illustration_by_scene.get(item.scene_index)
            if not ill:
                continue
            source_text = ill.scene_excerpt
            source_hash = compute_source_hash(source_text)
            existing = concept_trans_map.get(ill.id)
            if (
                existing
                and existing.scene_excerpt_localized
                and existing.scene_excerpt_localized_source_hash == source_hash
            ):
                all_items_response.append(
                    TranslationItemResponse(
                        kind="scene_excerpt",
                        scene_index=item.scene_index,
                        text=existing.scene_excerpt_localized,
                        source_hash=source_hash,
                    )
                )
            else:
                items_to_translate.append(
                    {
                        "kind": "scene_excerpt",
                        "scene_index": item.scene_index,
                        "source_text": source_text,
                    }
                )

    # Call Agent 5 if there are items to translate
    if items_to_translate:
        # Anything appended to all_items_response below this point is a
        # newly-translated item, used to build the translations_refreshed
        # SSE payload (we don't re-broadcast already-cached items).
        new_items_offset = len(all_items_response)
        translate_result = await _claude_client.translate(
            target_language=body.language,
            items=items_to_translate,
        )

        # Persist translations to DB
        for trans_item in translate_result.translations:
            if trans_item.kind == "story_title":
                source_hash = compute_source_hash(run.story_title)
                if story_trans:
                    story_trans.story_title = trans_item.translated_text
                    story_trans.story_title_source_hash = source_hash
                else:
                    story_trans = StoryTranslation(
                        run_id=run_id,
                        language=body.language,
                        story_title=trans_item.translated_text,
                        story_title_source_hash=source_hash,
                    )
                    session.add(story_trans)
                all_items_response.append(
                    TranslationItemResponse(
                        kind="story_title",
                        text=trans_item.translated_text,
                        source_hash=source_hash,
                    )
                )

            elif trans_item.kind == "story_topic_description":
                source_hash = compute_source_hash(run.story_topic_description)
                if story_trans:
                    story_trans.story_topic_description = trans_item.translated_text
                    story_trans.story_topic_description_source_hash = source_hash
                else:
                    story_trans = StoryTranslation(
                        run_id=run_id,
                        language=body.language,
                        story_topic_description=trans_item.translated_text,
                        story_topic_description_source_hash=source_hash,
                    )
                    session.add(story_trans)
                all_items_response.append(
                    TranslationItemResponse(
                        kind="story_topic_description",
                        text=trans_item.translated_text,
                        source_hash=source_hash,
                    )
                )

            elif trans_item.kind == "paragraph":
                if trans_item.paragraph_index is None:
                    continue
                source_text = paragraph_by_index.get(trans_item.paragraph_index, "")
                source_hash = compute_source_hash(source_text)
                existing = block_trans_map.get(trans_item.paragraph_index)
                if existing:
                    existing.text = trans_item.translated_text
                    existing.text_source_hash = source_hash
                else:
                    new_block_trans = StoryBlockTranslation(
                        run_id=run_id,
                        language=body.language,
                        paragraph_index=trans_item.paragraph_index,
                        text=trans_item.translated_text,
                        text_source_hash=source_hash,
                    )
                    session.add(new_block_trans)
                    block_trans_map[trans_item.paragraph_index] = new_block_trans
                all_items_response.append(
                    TranslationItemResponse(
                        kind="paragraph",
                        paragraph_index=trans_item.paragraph_index,
                        text=trans_item.translated_text,
                        source_hash=source_hash,
                    )
                )

            elif trans_item.kind == "illustration_concept":
                if trans_item.scene_index is None:
                    continue
                ill = illustration_by_scene.get(trans_item.scene_index)
                if not ill:
                    continue
                source_hash = compute_source_hash(ill.current_concept)
                existing = concept_trans_map.get(ill.id)
                if existing:
                    existing.concept_localized = trans_item.translated_text
                    existing.concept_localized_source_hash = source_hash
                else:
                    new_concept_trans = IllustrationConceptTranslation(
                        illustration_id=ill.id,
                        language=body.language,
                        concept_localized=trans_item.translated_text,
                        concept_localized_source_hash=source_hash,
                    )
                    session.add(new_concept_trans)
                    concept_trans_map[ill.id] = new_concept_trans
                all_items_response.append(
                    TranslationItemResponse(
                        kind="illustration_concept",
                        scene_index=trans_item.scene_index,
                        text=trans_item.translated_text,
                        source_hash=source_hash,
                    )
                )

            elif trans_item.kind == "scene_excerpt":
                if trans_item.scene_index is None:
                    continue
                ill = illustration_by_scene.get(trans_item.scene_index)
                if not ill:
                    continue
                source_hash = compute_source_hash(ill.scene_excerpt)
                existing = concept_trans_map.get(ill.id)
                if existing:
                    existing.scene_excerpt_localized = trans_item.translated_text
                    existing.scene_excerpt_localized_source_hash = source_hash
                else:
                    new_concept_trans = IllustrationConceptTranslation(
                        illustration_id=ill.id,
                        language=body.language,
                        scene_excerpt_localized=trans_item.translated_text,
                        scene_excerpt_localized_source_hash=source_hash,
                    )
                    session.add(new_concept_trans)
                    concept_trans_map[ill.id] = new_concept_trans
                all_items_response.append(
                    TranslationItemResponse(
                        kind="scene_excerpt",
                        scene_index=trans_item.scene_index,
                        text=trans_item.translated_text,
                        source_hash=source_hash,
                    )
                )

        await session.commit()

        # Emit SSE event for translations_refreshed (only the newly-translated
        # items — cached items are already in the frontend's cache).
        event_bus = _run_buses.get(run_id)
        if event_bus:
            new_items = all_items_response[new_items_offset:]
            await event_bus.publish(
                "translations_refreshed",
                {
                    "language": body.language,
                    "items": [item.model_dump() for item in new_items],
                },
            )

    return TranslateResponse(items=all_items_response)


@router.get("/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    lang: str = "sk",
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> StreamingResponse:
    # Load fresh state from DB — used both for the initial snapshot and to
    # handle terminal runs whose bus is no longer active (e.g., after server
    # restart). The snapshot is built in the subscriber's requested language
    # so it doesn't overwrite translated state the frontend just fetched
    # via GET /api/runs/{id}?lang=….
    repo = RunRepository(session)
    run = await repo.get_run(run_id)
    event_bus = _run_buses.get(run_id)
    terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}

    # Pre-creation case: the messages endpoint has pre-allocated the run_id
    # and registered a bus, but Agent 0b is still running in a background
    # task and has not yet created the run row. Subscribe to the bus and
    # let the background task's published "snapshot" (or "run_failed")
    # event provide the first payload.
    if run is None:
        if event_bus is None:
            raise HTTPException(status_code=404, detail="Run not found")

        queue = event_bus.subscribe()

        async def generate_pre_creation():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
                        if event["type"] in ("run_completed", "run_failed", "run_cancelled"):
                            break
                    except TimeoutError:
                        yield "event: heartbeat\ndata: {}\n\n"
            finally:
                event_bus.unsubscribe(queue)

        return StreamingResponse(
            generate_pre_creation(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    illustrations = await repo.get_illustrations_for_run(run_id)
    snapshot = await _build_snapshot(run, illustrations, session, language=lang)

    if event_bus is None:
        # No active bus. If the run is terminal we can still serve a complete
        # snapshot followed by the appropriate terminal event so the frontend
        # closes the stream cleanly.
        if run.status not in terminal:
            raise HTTPException(status_code=404, detail="Run not found or not active")

        async def generate_terminal():
            yield f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"
            if run.status == RunStatus.COMPLETED:
                payload = {"completed": run.completed_count, "failed": run.failed_count}
                event_type = "run_completed"
            elif run.status == RunStatus.FAILED:
                payload = {"error_code": run.error_code, "error_message": run.error_message}
                event_type = "run_failed"
            else:
                payload = {}
                event_type = "run_cancelled"
            yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            generate_terminal(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Active run: refresh the snapshot so subscribers see current state, not
    # the stale snapshot left over from earlier in the pipeline.
    event_bus.set_snapshot(snapshot)
    queue = event_bus.subscribe()

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
                    if event["type"] in ("run_completed", "run_failed", "run_cancelled"):
                        break
                except TimeoutError:
                    # Heartbeat
                    yield "event: heartbeat\ndata: {}\n\n"
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    repo = RunRepository(session)
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    if run.status in terminal:
        raise HTTPException(status_code=409, detail="Run is already in a terminal state")

    cancel_flag = _cancel_flags.get(run_id)
    if cancel_flag:
        cancel_flag.set()

    # § 6A.3 cancellation: illustrations parked in any MANUAL_* state have
    # no long-running async loop to interrupt, so the cancel endpoint must
    # transition them synchronously. Auto-pipeline illustrations are
    # interrupted by the cancel_flag and transitioned by branch.py.
    illustrations = await repo.get_illustrations_for_run(run_id)
    manual_states = {
        IllustrationState.MANUAL_CHATTING,
        IllustrationState.MANUAL_GENERATING_PROMPTS,
        IllustrationState.MANUAL_RENDERING,
    }
    event_bus = _run_buses.get(run_id)
    for ill in illustrations:
        if ill.state in manual_states:
            await repo.update_illustration(ill, state=IllustrationState.CANCELLED)
            if event_bus is not None:
                await event_bus.publish(
                    "illustration_state",
                    {
                        "illustration_id": ill.id,
                        "scene_index": ill.scene_index,
                        "state": IllustrationState.CANCELLED,
                        "concept_attempt": ill.concept_attempt,
                        "prompt_attempt": ill.prompt_attempt,
                        "current_concept": ill.current_concept,
                        "scene_excerpt": ill.scene_excerpt,
                    },
                )
                await event_bus.publish(
                    "illustration_manual_ended",
                    {
                        "illustration_id": ill.id,
                        "scene_index": ill.scene_index,
                        "outcome": "cancelled",
                    },
                )

    # If the pipeline already finished its asyncio.gather and is parked
    # waiting on the manual flow, no background task is going to flip the
    # run to CANCELLED. Do it here once the illustrations are settled.
    if cancel_flag and all(
        ill.state
        in (
            IllustrationState.COMPLETED,
            IllustrationState.FAILED,
            IllustrationState.CANCELLED,
        )
        for ill in illustrations
    ):
        completed = sum(1 for ill in illustrations if ill.state == IllustrationState.COMPLETED)
        failed = sum(1 for ill in illustrations if ill.state == IllustrationState.FAILED)
        await repo.update_run(
            run,
            status=RunStatus.CANCELLED,
            completed_count=completed,
            failed_count=failed,
        )
        if event_bus is not None:
            await event_bus.publish("run_cancelled", {})

    return {"status": "CANCELLED"}
