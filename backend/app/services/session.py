"""Session service: chat + finalize.

Wraps Agent 0a (chat) and Agent 0b (build_story) and persists the resulting
data into the ``sessions`` and ``runs`` tables.
"""

import logging
from dataclasses import dataclass

from app.constants import (
    CONFIRMED_ACK,
    SESSION_MAX_MESSAGES,
    SESSION_MESSAGE_MAX_CHARS,
    SUPPORTED_LANGUAGES,
)
from app.db.models import MessageRole, Session, SessionState
from app.db.repositories import RunRepository, SessionRepository
from app.schemas.claude import (
    BuildStoryResponse,
    ChatResponse,
    CollectedBrief,
    companion_in_pool,
    validate_illustration_distribution,
)
from app.services.claude import ClaudeClient, ClaudeError

logger = logging.getLogger(__name__)


# Welcome message is now frontend-only via i18n.t('chat.welcome')


class SessionError(Exception):
    """Raised for user-visible session-level failures."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class FinalizeResult:
    run_id: str
    source_language: str
    topic_short: str
    story_title: str
    story_topic_description: str
    story_blocks: list[dict]
    style_guide: dict
    illustrations: list[dict]
    companions_pool: list[str]


class SessionService:
    def __init__(
        self,
        session_repo: SessionRepository,
        claude: ClaudeClient,
    ):
        self.repo = session_repo
        self.claude = claude

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def create_session(self) -> Session:
        # No welcome message — frontend renders it via i18n.t('chat.welcome')
        return await self.repo.create_session()

    async def get_session_with_messages(self, session_id: str) -> tuple[Session, list]:
        s = await self.repo.get_session(session_id)
        if s is None:
            raise SessionError("SESSION_NOT_FOUND", "Session not found")
        msgs = await self.repo.get_messages(session_id)
        return s, msgs

    # ── Chat turn ────────────────────────────────────────────────────────────

    async def post_message(self, session_id: str, user_content: str) -> ChatResponse:
        text = user_content.strip()
        if not text:
            raise SessionError("EMPTY_MESSAGE", "Message must not be empty")
        if len(text) > SESSION_MESSAGE_MAX_CHARS:
            raise SessionError(
                "MESSAGE_TOO_LONG",
                f"Message exceeds {SESSION_MESSAGE_MAX_CHARS} characters",
            )

        s = await self.repo.get_session(session_id)
        if s is None:
            raise SessionError("SESSION_NOT_FOUND", "Session not found")
        if s.state not in (SessionState.CHATTING, SessionState.AWAITING_CONFIRMATION):
            raise SessionError(
                "SESSION_LOCKED",
                f"Session is in terminal state {s.state} and cannot accept messages",
            )

        msgs = await self.repo.get_messages(session_id)
        if len(msgs) >= SESSION_MAX_MESSAGES:
            raise SessionError(
                "SESSION_TOO_LONG",
                f"Session has reached the maximum of {SESSION_MAX_MESSAGES} messages",
            )

        # Persist user message first so it is part of the transcript on retry.
        await self.repo.add_message(session_id, MessageRole.USER, text)

        transcript = [
            {"role": m.role, "content": m.content} for m in await self.repo.get_messages(session_id)
        ]

        try:
            reply = await self.claude.chat(transcript)
        except ClaudeError as e:
            await self.repo.update_session(
                s,
                state=SessionState.FAILED,
                error_code="CHAT_FAILED",
                error_message=str(e),
            )
            raise SessionError("CHAT_FAILED", str(e)) from e

        # Persist detected language on first detection
        if reply.language and s.source_language is None:
            if reply.language in SUPPORTED_LANGUAGES:
                await self.repo.update_session(s, source_language=reply.language)

        # Normalise the confirmation acknowledgement so the frontend can
        # match it deterministically and so localisation / model drift in
        # the agent's prose cannot break the chat→pipeline handoff.
        normalized_reply = reply.reply
        if reply.phase == "confirmed":
            detected_lang = reply.language or s.source_language or "en"
            normalized_reply = CONFIRMED_ACK.get(detected_lang, CONFIRMED_ACK["en"])
            reply = reply.model_copy(update={"reply": normalized_reply})

        await self.repo.add_message(session_id, MessageRole.ASSISTANT, normalized_reply)

        new_state = {
            "gathering": SessionState.CHATTING,
            "awaiting_confirmation": SessionState.AWAITING_CONFIRMATION,
            "confirmed": SessionState.AWAITING_CONFIRMATION,
        }[reply.phase]

        update_kwargs: dict = {"state": new_state}
        if reply.collected_brief is not None:
            update_kwargs["collected_brief_json"] = reply.collected_brief.model_dump_json()
        if reply.topic_short:
            update_kwargs["topic_short"] = reply.topic_short
        await self.repo.update_session(s, **update_kwargs)

        return reply

    # ── Finalize ─────────────────────────────────────────────────────────────

    async def finalize(
        self,
        session_id: str,
        run_repo: RunRepository,
        run_id: str | None = None,
    ) -> FinalizeResult:
        """Build the story and create the run + illustration records.

        The caller is responsible for kicking off the pipeline once this
        returns, using the returned ``run_id``.

        When ``run_id`` is passed in, the messages endpoint has already
        pre-allocated it and persisted it on the session — Agent 0b's run
        row will be created with that explicit id so the frontend can
        navigate before Agent 0b finishes. In that path, the session is
        already in FINALIZING and ``s.run_id`` already equals ``run_id``;
        the usual "not yet finalized" guards are relaxed accordingly.
        """
        s = await self.repo.get_session(session_id)
        if s is None:
            raise SessionError("SESSION_NOT_FOUND", "Session not found")

        preallocated = run_id is not None
        if preallocated:
            # post_message has already validated the brief, set state to
            # FINALIZING, and stored run_id on the session. Re-validate the
            # brief still exists; everything else is the caller's contract.
            if s.collected_brief_json is None:
                raise SessionError("NO_BRIEF", "Session has no collected brief")
            if s.run_id != run_id:
                raise SessionError(
                    "ALREADY_FINALIZED",
                    "Session run_id does not match the pre-allocated id",
                )
        else:
            if s.state != SessionState.AWAITING_CONFIRMATION:
                raise SessionError(
                    "NOT_READY_TO_FINALIZE",
                    "Session is not awaiting confirmation; finalize is only allowed in that state",
                )
            if s.collected_brief_json is None:
                raise SessionError(
                    "NO_BRIEF",
                    "Session has no collected brief; finalize is impossible",
                )
            if s.run_id is not None:
                raise SessionError(
                    "ALREADY_FINALIZED",
                    "Session has already been finalized",
                )
            await self.repo.update_session(s, state=SessionState.FINALIZING)

        brief = CollectedBrief.model_validate_json(s.collected_brief_json)

        # Get source_language from session (default to 'en' if not set)
        source_language = s.source_language or "en"
        topic_short = s.topic_short or ""

        # Build input dict for Agent 0b
        build_input = {
            "source_language": source_language,
            "topic_short": topic_short,
            "characters": brief.characters,
            "main_character_role": brief.main_character_role,
            "companions": brief.companions,
            "topic": brief.topic,
            "notes": brief.notes,
        }

        try:
            story: BuildStoryResponse = await self.claude.build_story_i18n(build_input)
        except ClaudeError as e:
            await self.repo.update_session(
                s,
                state=SessionState.FAILED,
                error_code="STORY_BUILD_FAILED",
                error_message=str(e),
            )
            raise SessionError("STORY_BUILD_FAILED", str(e)) from e

        # Server-side pool fidelity: every companion attached to an
        # illustration must reference an entry in the brief's companions
        # pool. The brief's pool may be empty, in which case no
        # illustration may have a companion.
        pool = [c.description for c in brief.companions]
        for ill in story.illustrations:
            if ill.companion is None:
                continue
            if not companion_in_pool(ill.companion.description, pool):
                msg = (
                    f"Agent 0b proposed companion '{ill.companion.description}' for "
                    f"scene_index={ill.scene_index} that is not in the agreed pool {pool}."
                )
                await self.repo.update_session(
                    s,
                    state=SessionState.FAILED,
                    error_code="STORY_BUILD_FAILED",
                    error_message=msg,
                )
                raise SessionError("STORY_BUILD_FAILED", msg)

        # Cross-illustration statistical-distribution rules (auto pipeline
        # only): every cast role >= 1, main >= 2, no side > main, no-human
        # cap of 1/5, primary/secondary NH-character placement rules. See
        # ``validate_illustration_distribution`` in schemas.claude for the
        # full list. On violation we fail the run with STORY_BUILD_FAILED;
        # the user can restart the chat with an updated brief.
        try:
            validate_illustration_distribution(brief, story.illustrations, story.reserved_entities)
        except ValueError as e:
            msg = f"Agent 0b output violates distribution rules: {e}"
            await self.repo.update_session(
                s,
                state=SessionState.FAILED,
                error_code="STORY_BUILD_FAILED",
                error_message=msg,
            )
            raise SessionError("STORY_BUILD_FAILED", msg) from e

        # Persist run + illustrations.
        import json as _json

        # Walk story_blocks once to map each illustration scene_index to the
        # index (within story_blocks) of the paragraph block immediately
        # preceding it. The frontend uses paragraph_index to locate the
        # paragraph that Agent 4 rewrites during RETHINKING_CONCEPT cycles.
        paragraph_index_by_scene: dict[int, int] = {}
        last_paragraph_index = -1
        for block_index, block in enumerate(story.story_blocks):
            if block.type == "paragraph":
                last_paragraph_index = block_index
            else:  # illustration
                paragraph_index_by_scene[block.scene_index] = last_paragraph_index

        run = await run_repo.create_run(
            session_id=session_id,
            source_language=source_language,
            topic_short=topic_short,
            story_title=story.story_title,
            story_topic_description=story.story_topic_description,
            story_blocks_json=_json.dumps(
                [b.model_dump() for b in story.story_blocks], ensure_ascii=False
            ),
            style_guide_json=story.style_guide.model_dump_json(),
            illustration_count=len(story.illustrations),
            main_character_role=brief.main_character_role,
            environments_json=_json.dumps(
                [e.model_dump() for e in story.environments], ensure_ascii=False
            ),
            reserved_entities_json=_json.dumps(
                [e.model_dump() for e in story.reserved_entities], ensure_ascii=False
            ),
            id=run_id,
        )

        illustrations: list[dict] = []
        for ill in story.illustrations:
            env = story.environments[ill.scene_index]
            row = await run_repo.create_illustration(
                run_id=run.id,
                scene_index=ill.scene_index,
                scene_excerpt=ill.scene_excerpt,
                paragraph_index=paragraph_index_by_scene[ill.scene_index],
                concept=ill.concept_localized if ill.concept_localized else ill.concept,
                character_role=ill.character_role,
                companion_description=(
                    ill.companion.description if ill.companion is not None else None
                ),
                companion_interaction=(
                    ill.companion.interaction if ill.companion is not None else None
                ),
                environment_label=env.label,
                environment_aspect=env.aspect,
            )
            illustrations.append(
                {
                    "id": row.id,
                    "scene_index": row.scene_index,
                    "scene_excerpt": row.scene_excerpt,
                    "paragraph_index": row.paragraph_index,
                    "character_role": row.character_role,
                    "current_concept": row.current_concept,
                    "state": row.state,
                    "concept_attempt": row.concept_attempt,
                    "prompt_attempt": row.prompt_attempt,
                    "image_url": None,
                    "companion": (
                        {
                            "description": row.companion_description,
                            "interaction": row.companion_interaction,
                        }
                        if row.companion_description is not None
                        else None
                    ),
                }
            )

        # When run_id was pre-allocated, s.run_id is already correct.
        await self.repo.update_session(s, state=SessionState.FINALIZED, run_id=run.id)

        return FinalizeResult(
            run_id=run.id,
            source_language=source_language,
            topic_short=topic_short,
            story_title=story.story_title,
            story_topic_description=story.story_topic_description,
            story_blocks=[b.model_dump() for b in story.story_blocks],
            style_guide=story.style_guide.model_dump(),
            illustrations=illustrations,
            companions_pool=[c.description for c in brief.companions],
        )
