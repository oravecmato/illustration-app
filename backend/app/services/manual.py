"""Manual chat fallback service (§ 6A).

Drives Agent 6 (`manual_concept`) for one illustration whose automatic
pipeline has been exhausted, and dispatches Agent 7
(`manual_revise_prompts`) on every prompt-revision iteration triggered
by the user's post-image feedback.

The service is invoked synchronously from the manual-chat POST endpoint
— it does not own a background task. Each call appends a user message,
runs Agent 6, then (depending on the returned `phase` and the active
sub-phase persisted on the `manual_illustration_sessions` row) may
dispatch Agent 1 + RunPod (concept-design path) or Agent 7 + RunPod
(feedback-gathering path) before persisting the result and returning.

Cancellation is observed via the same per-run cancel flag the auto
pipeline uses: every state transition consults it.
"""

import asyncio
import json
import logging
import os

from app.constants import (
    MANUAL_BUDGET_EXHAUSTED,
    MANUAL_ITERATE_PROMPT,
    MANUAL_RENDER_FAILED,
    MANUAL_WELCOME,
    MANUAL_WELCOME_REGENERATE,
    MAX_MANUAL_ATTEMPTS,
)
from app.db.models import (
    Illustration,
    IllustrationState,
    ManualMessageRole,
    RunStatus,
)
from app.db.repositories import ManualRepository, RunRepository
from app.orchestrator.events import EventBus
from app.schemas.claude import StyleGuide, _normalize_entity_label
from app.services.claude import ClaudeClient, ClaudeError
from app.services.images import copy_image, save_manual_image
from app.services.runpod import RunPodClient
from app.services.workflow import replace_placeholders

logger = logging.getLogger(__name__)

# Sub-phase string constants persisted on `manual_illustration_sessions.sub_phase`.
SUB_PHASE_CONCEPT_DESIGN = "concept_design"
SUB_PHASE_FEEDBACK_GATHERING = "feedback_gathering"

# Phase-string constants for Agent 6's reply (mirrors schemas/claude.py).
PHASE_GATHERING = "gathering"
PHASE_AWAITING_CONCEPT_CONFIRMATION = "awaiting_concept_confirmation"
PHASE_CONCEPT_CONFIRMED = "concept_confirmed"
PHASE_GATHERING_FEEDBACK = "gathering_feedback"
PHASE_AWAITING_FEEDBACK_CONFIRMATION = "awaiting_feedback_confirmation"
PHASE_FEEDBACK_CONFIRMED = "feedback_confirmed"
PHASE_RESTART_CONCEPT = "restart_concept"
PHASE_ACCEPTED = "accepted"

# Phase enums legal in each sub-phase (server demotes everything else).
_CONCEPT_DESIGN_PHASES = {
    PHASE_GATHERING,
    PHASE_AWAITING_CONCEPT_CONFIRMATION,
    PHASE_CONCEPT_CONFIRMED,
    PHASE_ACCEPTED,  # technically only valid post-render but guarded below
}
_FEEDBACK_GATHERING_PHASES = {
    PHASE_GATHERING_FEEDBACK,
    PHASE_AWAITING_FEEDBACK_CONFIRMATION,
    PHASE_FEEDBACK_CONFIRMED,
    PHASE_RESTART_CONCEPT,
    PHASE_ACCEPTED,
}


class ManualServiceError(Exception):
    """User-visible failure inside the manual flow."""

    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _localized(table: dict[str, str], language: str) -> str:
    return table.get(language) or table["en"]


def _is_run_terminal(status: str) -> bool:
    return status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)


class ManualService:
    """Orchestrates the § 6A chat for one illustration."""

    def __init__(
        self,
        *,
        run_repo: RunRepository,
        manual_repo: ManualRepository,
        claude: ClaudeClient,
        runpod: RunPodClient,
        event_bus: EventBus | None,
        cancel_flag: asyncio.Event | None,
        workflow_template: dict,
        output_dir: str,
        character_config: dict | None = None,
    ):
        self.run_repo = run_repo
        self.manual_repo = manual_repo
        self.claude = claude
        self.runpod = runpod
        self.event_bus = event_bus
        self.cancel_flag = cancel_flag
        self.workflow_template = workflow_template
        self.output_dir = output_dir
        self.character_config = character_config or {}

    # ── Public API ──────────────────────────────────────────────────────────

    async def open_manual_flow(
        self,
        illustration: Illustration,
        source_language: str,
    ) -> None:
        """Open the manual flow for an illustration (§ 6A.3).

        Persists a manual_illustration_sessions row, writes the localized
        welcome bubble, transitions the illustration to MANUAL_CHATTING,
        and emits `illustration_manual_started`.
        """
        existing = await self.manual_repo.get_manual_session(illustration.id)
        if existing is None:
            await self.manual_repo.create_manual_session(illustration.id)

        welcome_text = _localized(MANUAL_WELCOME, source_language)
        welcome_msg = await self.manual_repo.add_message(
            illustration_id=illustration.id,
            role=ManualMessageRole.ASSISTANT,
            content=welcome_text,
        )

        await self.run_repo.update_illustration(
            illustration,
            state=IllustrationState.MANUAL_CHATTING,
        )

        if self.event_bus is not None:
            await self.event_bus.publish(
                "illustration_state",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "state": IllustrationState.MANUAL_CHATTING,
                    "concept_attempt": illustration.concept_attempt,
                    "prompt_attempt": illustration.prompt_attempt,
                    "current_concept": illustration.current_concept,
                    "scene_excerpt": illustration.scene_excerpt,
                },
            )
            await self.event_bus.publish(
                "illustration_manual_started",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "sub_phase": SUB_PHASE_CONCEPT_DESIGN,
                    "welcome_message": {
                        "id": welcome_msg.id,
                        "role": welcome_msg.role,
                        "content": welcome_msg.content,
                        "created_at": welcome_msg.created_at.isoformat(),
                    },
                },
            )

    async def start_regeneration(
        self,
        illustration: Illustration,
        source_language: str,
    ) -> None:
        """Begin a fresh § 6A regeneration on a COMPLETED illustration (§ 6A.9).

        Resets the manual session flow state (sub_phase → concept_design;
        clears last_concept_candidate / last_agreed_concept /
        last_manual_image_path) while KEEPING ``prompting_notes`` (cumulative
        memo) and ``image_path`` (so the UI can fall back to the previously
        accepted image if the user closes the chat). ``manual_attempts`` is
        NOT reset — the 5-attempt budget is cumulative across regenerations.
        Prior ``manual_messages`` rows are preserved; a localized welcome
        bubble is appended to the existing transcript.

        Note: the parent run may already be in a terminal status
        (COMPLETED/FAILED). We intentionally leave ``run.status`` alone;
        ``_maybe_finalize_run`` is a noop for already-terminal runs, so the
        new render outcomes won't toggle the run back to non-terminal.
        """
        if self.cancel_flag is not None and self.cancel_flag.is_set():
            raise ManualServiceError("RUN_CANCELLED", "Run is cancelled", 409)

        if illustration.state != IllustrationState.COMPLETED:
            raise ManualServiceError(
                "INVALID_STATE",
                f"Regeneration requires a COMPLETED illustration (current: {illustration.state})",
                409,
            )

        if illustration.manual_attempts >= MAX_MANUAL_ATTEMPTS:
            raise ManualServiceError(
                "BUDGET_EXHAUSTED",
                "Manual attempt budget exhausted for this illustration",
                409,
            )

        run = await self.run_repo.get_run(illustration.run_id)
        if run is None:
            raise ManualServiceError("RUN_NOT_FOUND", "Run not found", 404)
        if run.status == RunStatus.CANCELLED:
            raise ManualServiceError("RUN_CANCELLED", "Run is cancelled", 409)

        # Reset session flow state in place. KEEP prompting_notes.
        ms = await self.manual_repo.get_manual_session(illustration.id)
        if ms is None:
            ms = await self.manual_repo.create_manual_session(illustration.id)
        await self.manual_repo.update_manual_session(
            ms,
            sub_phase=SUB_PHASE_CONCEPT_DESIGN,
            last_agreed_concept=None,
            last_concept_candidate=None,
            last_manual_image_path=None,
        )

        # Append the regenerate welcome bubble to the existing transcript
        # (history accumulates across regenerations — § 6A.9).
        welcome_text = _localized(MANUAL_WELCOME_REGENERATE, source_language)
        welcome_msg = await self.manual_repo.add_message(
            illustration_id=illustration.id,
            role=ManualMessageRole.ASSISTANT,
            content=welcome_text,
        )

        # Flip state. Do NOT touch image_path (canonical previous image stays
        # as the UI fallback) and do NOT touch manual_attempts (cumulative).
        await self.run_repo.update_illustration(
            illustration,
            state=IllustrationState.MANUAL_CHATTING,
        )

        if self.event_bus is not None:
            await self.event_bus.publish(
                "illustration_state",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "state": IllustrationState.MANUAL_CHATTING,
                    "concept_attempt": illustration.concept_attempt,
                    "prompt_attempt": illustration.prompt_attempt,
                    "current_concept": illustration.current_concept,
                    "scene_excerpt": illustration.scene_excerpt,
                },
            )
            await self.event_bus.publish(
                "illustration_manual_started",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "sub_phase": SUB_PHASE_CONCEPT_DESIGN,
                    "reason": "regeneration",
                    "welcome_message": {
                        "id": welcome_msg.id,
                        "role": welcome_msg.role,
                        "content": welcome_msg.content,
                        "created_at": welcome_msg.created_at.isoformat(),
                    },
                },
            )

    async def post_message(self, illustration: Illustration, user_content: str) -> Illustration:
        """Append a user message and let Agent 6 (and possibly the renderer)
        respond. Returns the (possibly mutated) illustration row.
        """
        if self.cancel_flag is not None and self.cancel_flag.is_set():
            raise ManualServiceError("RUN_CANCELLED", "Run is cancelled", 409)

        if illustration.state != IllustrationState.MANUAL_CHATTING:
            raise ManualServiceError(
                "INVALID_STATE",
                f"Illustration is not in MANUAL_CHATTING (current: {illustration.state})",
                409,
            )

        run = await self.run_repo.get_run(illustration.run_id)
        if run is None:
            raise ManualServiceError("RUN_NOT_FOUND", "Run not found", 404)
        if run.status == RunStatus.CANCELLED:
            raise ManualServiceError("RUN_CANCELLED", "Run is cancelled", 409)

        text = (user_content or "").strip()
        if not text:
            raise ManualServiceError("EMPTY_MESSAGE", "Message must not be empty", 400)

        # 1. Load (or lazily create) the manual session row to read sub_phase
        #    and the carried-forward verbatim/agreed concepts.
        ms = await self.manual_repo.get_manual_session(illustration.id)
        if ms is None:
            ms = await self.manual_repo.create_manual_session(illustration.id)
        sub_phase = ms.sub_phase or SUB_PHASE_CONCEPT_DESIGN

        # 2. Persist user row + publish.
        user_msg = await self.manual_repo.add_message(
            illustration_id=illustration.id,
            role=ManualMessageRole.USER,
            content=text,
        )
        await self._publish_message(illustration, user_msg, sub_phase=sub_phase)

        # 3. Build transcript and run Agent 6.
        transcript = await self._build_transcript(illustration.id)
        story_blocks = json.loads(run.story_blocks_json) if run.story_blocks_json else []
        original_concept = illustration.initial_concept or illustration.current_concept

        current_entity = await self._entity_dict_from_illustration(illustration, run)

        try:
            agent_response = await self.claude.manual_concept(
                source_language=run.source_language,
                sub_phase=sub_phase,
                story_title=run.story_title,
                story_blocks=story_blocks,
                current_paragraph_index=illustration.paragraph_index,
                current_scene_excerpt=illustration.scene_excerpt,
                original_concept=original_concept,
                character_role=illustration.character_role,
                current_entity=current_entity,
                manual_attempts_consumed=illustration.manual_attempts,
                manual_attempts_remaining=max(
                    0, MAX_MANUAL_ATTEMPTS - illustration.manual_attempts
                ),
                last_concept_candidate=ms.last_concept_candidate,
                last_agreed_concept=ms.last_agreed_concept,
                prompting_notes=ms.prompting_notes,
                transcript=transcript,
            )
        except ClaudeError as e:
            logger.error("manual_concept failed: %s", e)
            raise ManualServiceError("MANUAL_CHAT_FAILED", str(e), 502) from e

        # § 6A.2 rule #12: Agent 6's `prompting_notes_update`, when present,
        # fully overwrites the cumulative memo. Omission/null leaves the
        # stored value untouched. Persisted regardless of `phase` so notes
        # accumulate across all turn types (including the ones that survive
        # `restart_concept`).
        if agent_response.prompting_notes_update is not None:
            await self.manual_repo.update_manual_session(
                ms, prompting_notes=agent_response.prompting_notes_update
            )

        phase = agent_response.phase

        # 4. Sub-phase ↔ phase compatibility demotions (§ 7.1 Call 6 rule #1
        #    and the "phase machine" in § 6A.4).
        phase = self._demote_phase_for_sub_phase(phase, sub_phase)

        # 5. Phase-specific structural guards.
        # `concept_confirmed` requires a prior `awaiting_concept_confirmation`
        # turn in this manual session (the model's own — last_concept_candidate
        # tracks it).
        if phase == PHASE_CONCEPT_CONFIRMED and not ms.last_concept_candidate:
            phase = PHASE_GATHERING

        # `feedback_confirmed` requires a prior `awaiting_feedback_confirmation`
        # turn (the most recent assistant turn before the user's latest).
        if phase == PHASE_FEEDBACK_CONFIRMED and not await self._has_recent_assistant_phase(
            illustration.id, PHASE_AWAITING_FEEDBACK_CONFIRMATION
        ):
            phase = PHASE_GATHERING_FEEDBACK

        # `accepted` requires at least one prior image row in the transcript.
        if phase == PHASE_ACCEPTED and illustration.manual_attempts < 1:
            phase = (
                PHASE_GATHERING_FEEDBACK
                if sub_phase == SUB_PHASE_FEEDBACK_GATHERING
                else PHASE_GATHERING
            )

        # Budget exhaustion: cannot dispatch another render.
        if (
            phase in (PHASE_CONCEPT_CONFIRMED, PHASE_FEEDBACK_CONFIRMED)
            and illustration.manual_attempts >= MAX_MANUAL_ATTEMPTS
        ):
            phase = (
                PHASE_GATHERING_FEEDBACK
                if sub_phase == SUB_PHASE_FEEDBACK_GATHERING
                else PHASE_GATHERING
            )

        # Verbatim handoff assertion on concept_confirmed (§ 6A.2 rule #7).
        if phase == PHASE_CONCEPT_CONFIRMED:
            if agent_response.concept_candidate != ms.last_concept_candidate:
                logger.warning(
                    "concept_confirmed verbatim mismatch (will demote to "
                    "awaiting_concept_confirmation): prior=%r new=%r",
                    ms.last_concept_candidate,
                    agent_response.concept_candidate,
                )
                phase = PHASE_AWAITING_CONCEPT_CONFIRMATION

        # Verbatim presence check on awaiting_concept_confirmation:
        # the candidate must appear verbatim inside the reply (so the user
        # really saw the same string they are being asked to confirm).
        if (
            phase == PHASE_AWAITING_CONCEPT_CONFIRMATION
            and agent_response.concept_candidate
            and agent_response.concept_candidate not in agent_response.reply
        ):
            logger.warning(
                "awaiting_concept_confirmation: concept_candidate not present "
                "verbatim inside reply; demoting to gathering"
            )
            phase = PHASE_GATHERING

        # 6. Persist assistant row + publish (use the possibly-demoted phase).
        assistant_msg = await self.manual_repo.add_message(
            illustration_id=illustration.id,
            role=ManualMessageRole.ASSISTANT,
            content=agent_response.reply,
        )
        await self._publish_message(illustration, assistant_msg, sub_phase=sub_phase)

        # 7. Persist candidate / agreed-concept side-effects.
        if phase == PHASE_AWAITING_CONCEPT_CONFIRMATION and agent_response.concept_candidate:
            await self.manual_repo.update_manual_session(
                ms, last_concept_candidate=agent_response.concept_candidate
            )

        # 8. Dispatch side-effects per (possibly-demoted) phase.
        if phase in (
            PHASE_GATHERING,
            PHASE_AWAITING_CONCEPT_CONFIRMATION,
            PHASE_GATHERING_FEEDBACK,
            PHASE_AWAITING_FEEDBACK_CONFIRMATION,
        ):
            return illustration

        if phase == PHASE_RESTART_CONCEPT:
            # Reset session to concept_design; clear baseline references.
            await self.manual_repo.update_manual_session(
                ms,
                sub_phase=SUB_PHASE_CONCEPT_DESIGN,
                last_agreed_concept=None,
                last_concept_candidate=None,
                last_manual_image_path=None,
            )
            return illustration

        if phase == PHASE_ACCEPTED:
            await self._accept_last_manual_image(illustration)
            return illustration

        if phase == PHASE_CONCEPT_CONFIRMED:
            candidate = agent_response.concept_candidate
            assert candidate is not None  # schema guarantees + verbatim guard above
            # Clear last_concept_candidate so it can't be re-confirmed.
            await self.manual_repo.update_manual_session(ms, last_concept_candidate=None)
            illustration = await self._run_concept_render(
                illustration, run.style_guide_json, candidate
            )
            return illustration

        if phase == PHASE_FEEDBACK_CONFIRMED:
            illustration = await self._run_feedback_render(illustration, run.style_guide_json)
            return illustration

        # Defensive: should never reach here.
        logger.warning("Unhandled phase after demotions: %r", phase)
        return illustration

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _demote_phase_for_sub_phase(phase: str, sub_phase: str) -> str:
        """Map agent-emitted `phase` onto a phase legal for `sub_phase`.

        See § 7.1 Call 6 rule #1.
        """
        if sub_phase == SUB_PHASE_CONCEPT_DESIGN:
            if phase in _CONCEPT_DESIGN_PHASES:
                return phase
            # Feedback-side phases received during concept design → gathering.
            return PHASE_GATHERING
        if sub_phase == SUB_PHASE_FEEDBACK_GATHERING:
            if phase in _FEEDBACK_GATHERING_PHASES:
                return phase
            # Concept-side phases received during feedback gathering →
            # gathering_feedback (the model must transition through
            # restart_concept to leave this sub-phase).
            return PHASE_GATHERING_FEEDBACK
        # Unknown sub_phase: be conservative.
        return PHASE_GATHERING

    async def _build_transcript(self, illustration_id: str) -> list[dict]:
        """Materialise the manual-chat transcript for Agent 6.

        `image`-role rows surface as assistant turns with content
        "[image rendered: attempt K]" so the model knows where each
        render landed without trying to consume the image bytes.
        """
        rows = await self.manual_repo.get_messages(illustration_id)
        transcript: list[dict] = []
        for row in rows:
            if row.role == ManualMessageRole.IMAGE:
                k = row.manual_attempt_index if row.manual_attempt_index is not None else "?"
                transcript.append(
                    {"role": "assistant", "content": f"[image rendered: attempt {k}]"}
                )
                continue
            transcript.append({"role": row.role, "content": row.content})
        return transcript

    async def _has_recent_assistant_phase(self, illustration_id: str, _phase_marker: str) -> bool:
        """Best-effort check: did the model recently emit
        `awaiting_feedback_confirmation`?

        We don't persist agent phases in `manual_messages`. The closest
        proxy is "at least one assistant turn since the most recent
        image row". Since § 6A.10 removed the auto-emitted review prompt,
        the first assistant turn after the image IS the model's own
        feedback-gathering reply — so a single such turn is enough.
        """
        rows = await self.manual_repo.get_messages(illustration_id)
        # rows are sorted ascending by created_at.
        last_image_idx = -1
        for i, row in enumerate(rows):
            if row.role == ManualMessageRole.IMAGE:
                last_image_idx = i
        if last_image_idx < 0:
            return False
        assistant_turns_post_image = [
            i
            for i, row in enumerate(rows[last_image_idx + 1 :], start=last_image_idx + 1)
            if row.role == ManualMessageRole.ASSISTANT
        ]
        return len(assistant_turns_post_image) >= 1

    async def _publish_message(self, illustration: Illustration, msg, *, sub_phase: str) -> None:
        if self.event_bus is None:
            return
        await self.event_bus.publish(
            "manual_message_appended",
            {
                "illustration_id": illustration.id,
                "scene_index": illustration.scene_index,
                "sub_phase": sub_phase,
                "message": {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "image_url": msg.image_url,
                    "manual_attempt_index": msg.manual_attempt_index,
                    "created_at": msg.created_at.isoformat(),
                },
            },
        )

    async def _publish_state(self, illustration: Illustration, state: str) -> None:
        if self.event_bus is None:
            return
        await self.event_bus.publish(
            "illustration_state",
            {
                "illustration_id": illustration.id,
                "scene_index": illustration.scene_index,
                "state": state,
                "concept_attempt": illustration.concept_attempt,
                "prompt_attempt": illustration.prompt_attempt,
                "current_concept": illustration.current_concept,
                "scene_excerpt": illustration.scene_excerpt,
            },
        )

    async def _run_concept_render(
        self,
        illustration: Illustration,
        style_guide_json: str,
        concept_candidate: str,
    ) -> Illustration:
        """Concept-design path: dispatch Agent 1 + RunPod."""
        style_guide = StyleGuide(**json.loads(style_guide_json))
        character_role = illustration.character_role
        run = await self.run_repo.get_run(illustration.run_id)
        current_entity = await self._entity_dict_from_illustration(illustration, run)

        # Cumulative prompt-engineering memo (§ 6A.2 rule #12). NULL until
        # Agent 6 has emitted its first `prompting_notes_update`.
        ms = await self.manual_repo.get_manual_session(illustration.id)
        prompting_notes = ms.prompting_notes if ms is not None else None

        # MANUAL_GENERATING_PROMPTS
        await self.run_repo.update_illustration(
            illustration,
            state=IllustrationState.MANUAL_GENERATING_PROMPTS,
            current_concept=concept_candidate,
        )
        await self._publish_state(illustration, IllustrationState.MANUAL_GENERATING_PROMPTS)

        try:
            prompts = await self.claude.generate_prompts(
                current_concept=concept_candidate,
                style_guide=style_guide,
                character_role=character_role,
                character_config=self.character_config,
                contains_entity=current_entity,
                prompting_notes=prompting_notes,
            )
        except Exception as e:
            logger.error("manual generate_prompts failed: %s", e)
            await self._handle_manual_failure(illustration, MANUAL_RENDER_FAILED)
            raise ManualServiceError(
                "MANUAL_PROMPT_FAILED",
                f"Prompt generation failed: {e}",
                502,
            ) from e

        # Persist current_prompts + workflow choice. The workflow CAN change
        # here vs. the original auto-pipeline choice (e.g. concept dropped
        # the character) — Agent 1 picks it deterministically from
        # character_role.
        await self.run_repo.update_illustration(
            illustration,
            current_prompts_json=prompts.model_dump_json(),
            current_workflow=f"{prompts.workflow}.json",
        )

        await self._dispatch_render(
            illustration,
            style_guide=style_guide,
            positive=prompts.positive,
            negative=prompts.negative,
            character_role=character_role,
            agreed_concept=concept_candidate,
        )
        return illustration

    async def _run_feedback_render(
        self,
        illustration: Illustration,
        style_guide_json: str,
    ) -> Illustration:
        """Feedback-gathering path: slice user feedback, dispatch Agent 7 +
        RunPod with revised prompts."""
        style_guide = StyleGuide(**json.loads(style_guide_json))
        character_role = illustration.character_role
        run = await self.run_repo.get_run(illustration.run_id)
        current_entity = await self._entity_dict_from_illustration(illustration, run)

        ms = await self.manual_repo.get_manual_session(illustration.id)
        if ms is None or not ms.last_agreed_concept:
            # Should not happen — sub_phase=feedback_gathering implies a
            # successful prior render which set last_agreed_concept.
            await self._handle_manual_failure(illustration, MANUAL_RENDER_FAILED)
            raise ManualServiceError(
                "MANUAL_STATE_CORRUPT",
                "Cannot revise prompts without a recorded agreed concept",
                500,
            )

        if not illustration.current_prompts_json:
            await self._handle_manual_failure(illustration, MANUAL_RENDER_FAILED)
            raise ManualServiceError(
                "MANUAL_STATE_CORRUPT",
                "Cannot revise prompts without prior prompts on file",
                500,
            )
        prior_prompts = json.loads(illustration.current_prompts_json)
        last_positive = prior_prompts.get("positive", "")
        last_negative = prior_prompts.get("negative", "")

        user_feedback_text = await self._slice_post_image_user_feedback(illustration.id)

        # MANUAL_GENERATING_PROMPTS
        await self.run_repo.update_illustration(
            illustration,
            state=IllustrationState.MANUAL_GENERATING_PROMPTS,
        )
        await self._publish_state(illustration, IllustrationState.MANUAL_GENERATING_PROMPTS)

        try:
            revised = await self.claude.manual_revise_prompts(
                last_agreed_concept=ms.last_agreed_concept,
                user_feedback=user_feedback_text,
                last_positive_prompt=last_positive,
                last_negative_prompt=last_negative,
                style_guide=style_guide,
                character_role=character_role,
                character_config=self.character_config,
                contains_entity=current_entity,
                prompting_notes=ms.prompting_notes,
            )
        except Exception as e:
            logger.error("manual_revise_prompts (Agent 7) failed: %s", e)
            await self._handle_manual_failure(illustration, MANUAL_RENDER_FAILED)
            raise ManualServiceError(
                "MANUAL_PROMPT_FAILED",
                f"Prompt revision failed: {e}",
                502,
            ) from e

        # Persist revised prompts. workflow is carried forward (§ 6A.4 step 5.5).
        revised_prompts_blob = {
            "workflow": prior_prompts.get("workflow", "single-lora"),
            "positive": revised.positive,
            "negative": revised.negative,
        }
        await self.run_repo.update_illustration(
            illustration,
            current_prompts_json=json.dumps(revised_prompts_blob),
        )

        await self._dispatch_render(
            illustration,
            style_guide=style_guide,
            positive=revised.positive,
            negative=revised.negative,
            character_role=character_role,
            agreed_concept=ms.last_agreed_concept,
        )
        return illustration

    async def _entity_dict_from_illustration(self, illustration: Illustration, run) -> dict | None:
        """Look up the NarrativeEntity dict attached to this illustration.

        Returns the entity entry from ``run.narrative_entities_json``
        matching ``illustration.contains_entity_label`` (normalised), or
        ``None`` when the slot has no active entity or the registry is
        missing.
        """
        if not illustration.contains_entity_label or run is None:
            return None
        if not run.narrative_entities_json:
            return None
        entities = json.loads(run.narrative_entities_json)
        norm = _normalize_entity_label(illustration.contains_entity_label)
        for e in entities:
            if _normalize_entity_label(e["label"]) == norm:
                return e
        return None

    async def _slice_post_image_user_feedback(self, illustration_id: str) -> str:
        """Concatenate every `user`-role message that came AFTER the most
        recent `image`-role row, newline-separated (§ 6A.4 step 5.2)."""
        rows = await self.manual_repo.get_messages(illustration_id)
        last_image_idx = -1
        for i, row in enumerate(rows):
            if row.role == ManualMessageRole.IMAGE:
                last_image_idx = i
        if last_image_idx < 0:
            return ""
        chunks = [
            row.content
            for row in rows[last_image_idx + 1 :]
            if row.role == ManualMessageRole.USER and row.content.strip()
        ]
        return "\n".join(chunks)

    async def _dispatch_render(
        self,
        illustration: Illustration,
        *,
        style_guide: StyleGuide,
        positive: str,
        negative: str,
        character_role: str | None,
        agreed_concept: str,
    ) -> None:
        """Increment manual_attempts, dispatch one ComfyUI job, persist
        the result, flip sub_phase to `feedback_gathering` on success,
        emit SSE."""
        new_attempts = illustration.manual_attempts + 1
        await self.run_repo.update_illustration(
            illustration,
            state=IllustrationState.MANUAL_RENDERING,
            manual_attempts=new_attempts,
        )
        await self._publish_state(illustration, IllustrationState.MANUAL_RENDERING)

        if self.cancel_flag is not None and self.cancel_flag.is_set():
            await self.run_repo.update_illustration(illustration, state=IllustrationState.CANCELLED)
            await self._publish_state(illustration, IllustrationState.CANCELLED)
            if self.event_bus is not None:
                await self.event_bus.publish(
                    "illustration_manual_ended",
                    {
                        "illustration_id": illustration.id,
                        "scene_index": illustration.scene_index,
                        "outcome": "cancelled",
                    },
                )
            await self._maybe_finalize_run(illustration.run_id)
            return

        workflow_filename = illustration.current_workflow or "single-lora.json"
        workflow_path = os.path.join(
            os.path.dirname(__file__), "..", "workflows", workflow_filename
        )
        try:
            with open(workflow_path) as f:
                workflow_template = json.load(f)
        except FileNotFoundError:
            logger.warning(
                "Workflow file %s not found, falling back to default",
                workflow_path,
            )
            workflow_template = self.workflow_template

        char_lora = (
            self.character_config.get(character_role, {}).get("lora_filename", "")
            if character_role
            else ""
        )
        replacements = {
            "POSITIVE_PROMPT": positive,
            "NEGATIVE_PROMPT": negative,
            "CHARACTER_LORA": char_lora,
            "STYLE_POSITIVE_PROMPT": style_guide.overall_style_positive,
            "STYLE_NEGATIVE_PROMPT": style_guide.overall_style_negative,
        }
        workflow, _ = replace_placeholders(workflow_template, replacements)

        try:
            image_bytes = await self.runpod.run_workflow(workflow)
        except Exception as e:
            logger.error("manual runpod.run_workflow failed: %s", e)
            # On RunPod failure: reset sub_phase to concept_design (auto loop
            # parity — the user gets to redesign the concept). § 6A.4 step 3.10.
            ms = await self.manual_repo.get_manual_session(illustration.id)
            if ms is not None:
                await self.manual_repo.update_manual_session(
                    ms,
                    sub_phase=SUB_PHASE_CONCEPT_DESIGN,
                    last_concept_candidate=None,
                )
            await self._handle_manual_failure(illustration, MANUAL_RENDER_FAILED)
            if new_attempts >= MAX_MANUAL_ATTEMPTS:
                await self._exhaust(illustration)
            raise ManualServiceError(
                "MANUAL_RENDER_FAILED",
                f"Image rendering failed: {e}",
                502,
            ) from e

        manual_path = await save_manual_image(
            image_bytes,
            self.output_dir,
            illustration.run_id,
            illustration.scene_index,
            new_attempts,
        )

        # Persist last_manual_image_path + last_agreed_concept; flip sub_phase
        # to feedback_gathering (§ 6A.4 step 3.7 / 3.8).
        ms = await self.manual_repo.get_manual_session(illustration.id)
        if ms is not None:
            await self.manual_repo.update_manual_session(
                ms,
                last_manual_image_path=manual_path,
                last_agreed_concept=agreed_concept,
                sub_phase=SUB_PHASE_FEEDBACK_GATHERING,
            )

        image_url = f"/static/{manual_path}"

        # Persist per-attempt provenance (§ 6A.10) on the image row so the
        # frontend's `ManualImageCard` can show the exact concept + prompts
        # that produced this attempt — even after later iterations replace
        # the illustration's live `current_concept` / `current_prompts_json`.
        image_msg = await self.manual_repo.add_message(
            illustration_id=illustration.id,
            role=ManualMessageRole.IMAGE,
            content="",
            image_url=image_url,
            manual_attempt_index=new_attempts,
            concept_used=agreed_concept,
            positive_prompt=positive,
            negative_prompt=negative,
        )

        await self.run_repo.update_illustration(
            illustration, state=IllustrationState.MANUAL_CHATTING
        )
        await self._publish_state(illustration, IllustrationState.MANUAL_CHATTING)

        if self.event_bus is not None:
            await self.event_bus.publish(
                "manual_image_rendered",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "sub_phase": SUB_PHASE_FEEDBACK_GATHERING,
                    "manual_attempt": new_attempts,
                    "image_url": image_url,
                    "image_message_id": image_msg.id,
                    "concept_used": agreed_concept,
                    "positive_prompt": positive,
                    "negative_prompt": negative,
                },
            )

        if new_attempts >= MAX_MANUAL_ATTEMPTS:
            await self._exhaust(illustration)

    async def _handle_manual_failure(
        self, illustration: Illustration, message_table: dict[str, str]
    ) -> None:
        """Append the localized failure bubble and return to MANUAL_CHATTING."""
        run = await self.run_repo.get_run(illustration.run_id)
        language = run.source_language if run else "en"
        bubble_text = _localized(message_table, language)
        msg = await self.manual_repo.add_message(
            illustration_id=illustration.id,
            role=ManualMessageRole.ASSISTANT,
            content=bubble_text,
        )
        await self.run_repo.update_illustration(
            illustration, state=IllustrationState.MANUAL_CHATTING
        )
        await self._publish_state(illustration, IllustrationState.MANUAL_CHATTING)
        ms = await self.manual_repo.get_manual_session(illustration.id)
        sub_phase = ms.sub_phase if ms is not None else SUB_PHASE_CONCEPT_DESIGN
        await self._publish_message(illustration, msg, sub_phase=sub_phase)

    async def _exhaust(self, illustration: Illustration) -> None:
        """Mark the manual flow as exhausted (§ 6A.4 step 6)."""
        run = await self.run_repo.get_run(illustration.run_id)
        language = run.source_language if run else "en"
        bubble_text = _localized(MANUAL_BUDGET_EXHAUSTED, language)
        msg = await self.manual_repo.add_message(
            illustration_id=illustration.id,
            role=ManualMessageRole.ASSISTANT,
            content=bubble_text,
        )
        await self.run_repo.update_illustration(
            illustration,
            state=IllustrationState.FAILED,
            error_message="Manual attempts exhausted",
        )
        await self._publish_state(illustration, IllustrationState.FAILED)
        ms = await self.manual_repo.get_manual_session(illustration.id)
        sub_phase = ms.sub_phase if ms is not None else SUB_PHASE_CONCEPT_DESIGN
        await self._publish_message(illustration, msg, sub_phase=sub_phase)
        if self.event_bus is not None:
            await self.event_bus.publish(
                "illustration_failed",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "error_message": illustration.error_message,
                },
            )
            await self.event_bus.publish(
                "illustration_manual_ended",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "outcome": "exhausted",
                },
            )
        await self._maybe_finalize_run(illustration.run_id)

    async def accept_attempt(self, illustration: Illustration, manual_attempt_index: int) -> None:
        """Promote a specific manual attempt's image to the canonical scene
        image (§ 6A.10).

        Generalisation of the Agent-6 ``PHASE_ACCEPTED`` path: a user can
        explicitly accept any prior manual attempt via the UI button.
        Bypasses Agent 6 entirely — deterministic server-side promotion.
        """
        if self.cancel_flag is not None and self.cancel_flag.is_set():
            raise ManualServiceError("RUN_CANCELLED", "Run is cancelled", 409)

        # Also accept FAILED — § 6A.10 post-exhaustion recovery: once the
        # manual budget is spent, the illustration transitions to FAILED,
        # but the user can still promote one of the prior attempts.
        if illustration.state not in (
            IllustrationState.MANUAL_CHATTING,
            IllustrationState.MANUAL_GENERATING_PROMPTS,
            IllustrationState.MANUAL_RENDERING,
            IllustrationState.FAILED,
        ):
            raise ManualServiceError(
                "INVALID_STATE",
                f"Acceptance requires a MANUAL_* or FAILED state (current: {illustration.state})",
                409,
            )

        run = await self.run_repo.get_run(illustration.run_id)
        if run is None:
            raise ManualServiceError("RUN_NOT_FOUND", "Run not found", 404)
        if run.status == RunStatus.CANCELLED:
            raise ManualServiceError("RUN_CANCELLED", "Run is cancelled", 409)

        image_row = await self.manual_repo.get_image_message(illustration.id, manual_attempt_index)
        if image_row is None:
            raise ManualServiceError(
                "ATTEMPT_NOT_FOUND",
                f"No manual attempt {manual_attempt_index} found",
                404,
            )

        # Reconstruct the deterministic source path (§ 6A.4: save_manual_image
        # writes to runs/{run_id}/manual_{scene_index}_{K}.png).
        source_relative = (
            f"runs/{illustration.run_id}/manual_{illustration.scene_index}"
            f"_{manual_attempt_index}.png"
        )
        source_abs = os.path.join(self.output_dir, source_relative)
        if not os.path.exists(source_abs):
            raise ManualServiceError(
                "ATTEMPT_FILE_MISSING",
                f"Attempt image not found on disk: {source_relative}",
                410,
            )

        canonical_relative = f"runs/{illustration.run_id}/scene_{illustration.scene_index}.png"
        await copy_image(source_relative, self.output_dir, canonical_relative)

        update_kwargs: dict = dict(
            state=IllustrationState.COMPLETED,
            image_path=canonical_relative,
            # Clear the prior FAILED error_message (post-exhaustion recovery).
            error_message=None,
        )
        # Surface the concept that actually produced the accepted image.
        if image_row.concept_used:
            update_kwargs["current_concept"] = image_row.concept_used
        await self.run_repo.update_illustration(illustration, **update_kwargs)

        image_url = f"/static/{canonical_relative}"
        if self.event_bus is not None:
            await self.event_bus.publish(
                "illustration_state",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "state": IllustrationState.COMPLETED,
                    "concept_attempt": illustration.concept_attempt,
                    "prompt_attempt": illustration.prompt_attempt,
                    "current_concept": illustration.current_concept,
                    "scene_excerpt": illustration.scene_excerpt,
                },
            )
            await self.event_bus.publish(
                "illustration_completed",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "image_url": image_url,
                },
            )
            await self.event_bus.publish(
                "illustration_manual_ended",
                {
                    "illustration_id": illustration.id,
                    "scene_index": illustration.scene_index,
                    "outcome": "completed",
                },
            )
        await self._maybe_finalize_run(illustration.run_id)

    async def _accept_last_manual_image(self, illustration: Illustration) -> None:
        """Thin wrapper preserving the Agent-6 ``PHASE_ACCEPTED`` code path.

        Resolves the latest manual attempt and delegates to ``accept_attempt``.
        """
        if illustration.manual_attempts < 1:
            raise ManualServiceError(
                "NO_MANUAL_IMAGE",
                "No manual image has been rendered yet",
                409,
            )
        await self.accept_attempt(illustration, illustration.manual_attempts)

    async def append_iterate_prompt(self, illustration: Illustration, source_language: str) -> None:
        """Append the localized iterate-prompt bubble (§ 6A.10).

        Called when the user clicks the "Iterate" button on a freshly
        rendered manual image. Idempotent: if the latest message is
        already an assistant bubble (i.e. the iterate prompt is already
        on the transcript), this is a no-op.
        """
        if self.cancel_flag is not None and self.cancel_flag.is_set():
            raise ManualServiceError("RUN_CANCELLED", "Run is cancelled", 409)

        if illustration.state not in (
            IllustrationState.MANUAL_CHATTING,
            IllustrationState.MANUAL_GENERATING_PROMPTS,
            IllustrationState.MANUAL_RENDERING,
        ):
            raise ManualServiceError(
                "INVALID_STATE",
                f"Iterate requires a MANUAL_* state (current: {illustration.state})",
                409,
            )

        run = await self.run_repo.get_run(illustration.run_id)
        if run is None:
            raise ManualServiceError("RUN_NOT_FOUND", "Run not found", 404)
        if run.status == RunStatus.CANCELLED:
            raise ManualServiceError("RUN_CANCELLED", "Run is cancelled", 409)

        # Idempotency: only append if the most recent row is the just-rendered
        # image. If anything has been said since (including a previous iterate
        # bubble), do nothing.
        rows = await self.manual_repo.get_messages(illustration.id)
        if not rows:
            raise ManualServiceError(
                "NO_MANUAL_IMAGE",
                "No manual image has been rendered yet",
                409,
            )
        if rows[-1].role != ManualMessageRole.IMAGE:
            return

        iterate_text = _localized(MANUAL_ITERATE_PROMPT, source_language)
        msg = await self.manual_repo.add_message(
            illustration_id=illustration.id,
            role=ManualMessageRole.ASSISTANT,
            content=iterate_text,
        )
        ms = await self.manual_repo.get_manual_session(illustration.id)
        sub_phase = ms.sub_phase if ms is not None else SUB_PHASE_FEEDBACK_GATHERING
        await self._publish_message(illustration, msg, sub_phase=sub_phase)

    async def _maybe_finalize_run(self, run_id: str) -> None:
        """If every illustration is in a terminal state, mark the run done."""
        run = await self.run_repo.get_run(run_id)
        if run is None or _is_run_terminal(run.status):
            return
        illustrations = await self.run_repo.get_illustrations_for_run(run_id)
        terminal = {
            IllustrationState.COMPLETED,
            IllustrationState.FAILED,
            IllustrationState.CANCELLED,
        }
        if not all(ill.state in terminal for ill in illustrations):
            return
        completed = sum(1 for ill in illustrations if ill.state == IllustrationState.COMPLETED)
        failed = sum(1 for ill in illustrations if ill.state == IllustrationState.FAILED)
        cancelled = sum(1 for ill in illustrations if ill.state == IllustrationState.CANCELLED)
        if cancelled > 0 and self.cancel_flag is not None and self.cancel_flag.is_set():
            await self.run_repo.update_run(
                run,
                status=RunStatus.CANCELLED,
                completed_count=completed,
                failed_count=failed,
            )
            if self.event_bus is not None:
                await self.event_bus.publish("run_cancelled", {})
        else:
            await self.run_repo.update_run(
                run,
                status=RunStatus.COMPLETED,
                completed_count=completed,
                failed_count=failed,
            )
            if self.event_bus is not None:
                await self.event_bus.publish(
                    "run_completed",
                    {"completed": completed, "failed": failed},
                )
