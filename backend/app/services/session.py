"""Session service: chat + finalize.

Wraps Agent 0a (chat) and Agent 0b (build_story) and persists the resulting
data into the ``sessions`` and ``runs`` tables.
"""

import logging
from dataclasses import dataclass

from app.constants import CONFIRMED_ACK_SK, SESSION_MAX_MESSAGES, SESSION_MESSAGE_MAX_CHARS
from app.db.models import MessageRole, Session, SessionState
from app.db.repositories import RunRepository, SessionRepository
from app.schemas.claude import (
    BuildStoryResponse,
    ChatResponse,
    CollectedBrief,
)
from app.services.claude import ClaudeClient, ClaudeError

logger = logging.getLogger(__name__)


WELCOME_MESSAGE = (
    "Ahoj! Som tvoj asistent pre Anime Illustrator. Spolu vymyslíme krátky "
    "ilustrovaný príbeh. Povedz mi, o kom a o čom by mal byť — kto je hlavná "
    "postava (chlapec, dievča, prípadne mama) a aká téma ťa zaujíma?"
)


class SessionError(Exception):
    """Raised for user-visible session-level failures."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class FinalizeResult:
    run_id: str
    story_title: str
    story_blocks: list[dict]
    style_guide: dict
    illustrations: list[dict]


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
        s = await self.repo.create_session()
        await self.repo.add_message(s.id, MessageRole.ASSISTANT, WELCOME_MESSAGE)
        return s

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

        # Normalise the confirmation acknowledgement so the frontend can
        # match it deterministically and so localisation / model drift in
        # the agent's prose cannot break the chat→pipeline handoff.
        if reply.phase == "confirmed":
            reply = reply.model_copy(update={"reply": CONFIRMED_ACK_SK})

        await self.repo.add_message(session_id, MessageRole.ASSISTANT, reply.reply)

        new_state = {
            "gathering": SessionState.CHATTING,
            "awaiting_confirmation": SessionState.AWAITING_CONFIRMATION,
            "confirmed": SessionState.AWAITING_CONFIRMATION,
        }[reply.phase]

        update_kwargs: dict = {"state": new_state}
        if reply.collected_brief is not None:
            update_kwargs["collected_brief_json"] = reply.collected_brief.model_dump_json()
        await self.repo.update_session(s, **update_kwargs)

        return reply

    # ── Finalize ─────────────────────────────────────────────────────────────

    async def finalize(
        self,
        session_id: str,
        run_repo: RunRepository,
    ) -> FinalizeResult:
        """Build the story and create the run + illustration records.

        The caller is responsible for kicking off the pipeline once this
        returns, using the returned ``run_id``.
        """
        s = await self.repo.get_session(session_id)
        if s is None:
            raise SessionError("SESSION_NOT_FOUND", "Session not found")
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

        try:
            story: BuildStoryResponse = await self.claude.build_story(brief)
        except ClaudeError as e:
            await self.repo.update_session(
                s,
                state=SessionState.FAILED,
                error_code="STORY_BUILD_FAILED",
                error_message=str(e),
            )
            raise SessionError("STORY_BUILD_FAILED", str(e)) from e

        # Persist run + illustrations.
        import json as _json

        run = await run_repo.create_run(
            session_id=session_id,
            story_title=story.story_title,
            story_blocks_json=_json.dumps(
                [b.model_dump() for b in story.story_blocks], ensure_ascii=False
            ),
            style_guide_json=story.style_guide.model_dump_json(),
            illustration_count=len(story.illustrations),
        )

        illustrations: list[dict] = []
        for ill in story.illustrations:
            row = await run_repo.create_illustration(
                run_id=run.id,
                scene_index=ill.scene_index,
                scene_excerpt=ill.scene_excerpt,
                concept=ill.concept,
                character_role=ill.character_role,
            )
            illustrations.append(
                {
                    "id": row.id,
                    "scene_index": row.scene_index,
                    "scene_excerpt": row.scene_excerpt,
                    "character_role": row.character_role,
                    "current_concept": row.current_concept,
                    "state": row.state,
                    "concept_attempt": row.concept_attempt,
                    "prompt_attempt": row.prompt_attempt,
                    "image_url": None,
                }
            )

        await self.repo.update_session(s, state=SessionState.FINALIZED, run_id=run.id)

        return FinalizeResult(
            run_id=run.id,
            story_title=story.story_title,
            story_blocks=[b.model_dump() for b in story.story_blocks],
            style_guide=story.style_guide.model_dump(),
            illustrations=illustrations,
        )
