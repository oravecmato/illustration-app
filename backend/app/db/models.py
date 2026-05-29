import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SessionState(StrEnum):
    CHATTING = "CHATTING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    FINALIZING = "FINALIZING"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IllustrationState(StrEnum):
    PENDING = "PENDING"
    GENERATING_PROMPTS = "GENERATING_PROMPTS"
    RENDERING = "RENDERING"
    EVALUATING = "EVALUATING"
    REVISING_PROMPTS = "REVISING_PROMPTS"
    RETHINKING_CONCEPT = "RETHINKING_CONCEPT"
    RETHINKING_ENVIRONMENT = "RETHINKING_ENVIRONMENT"
    SALVAGE_REVIEW = "SALVAGE_REVIEW"
    MANUAL_CHATTING = "MANUAL_CHATTING"
    MANUAL_GENERATING_PROMPTS = "MANUAL_GENERATING_PROMPTS"
    MANUAL_RENDERING = "MANUAL_RENDERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ManualMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    IMAGE = "image"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    state: Mapped[str] = mapped_column(String, default=SessionState.CHATTING)
    source_language: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    detected_language: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    topic_short: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    collected_brief_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    messages: Mapped[list["SessionMessage"]] = relationship(
        "SessionMessage",
        back_populates="session",
        order_by="SessionMessage.created_at",
    )


class SessionMessage(Base):
    __tablename__ = "session_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped["Session"] = relationship("Session", back_populates="messages")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default=RunStatus.RUNNING)
    source_language: Mapped[str] = mapped_column(String)
    topic_short: Mapped[str] = mapped_column(Text)
    story_title: Mapped[str] = mapped_column(Text)
    story_topic_description: Mapped[str] = mapped_column(Text)
    story_blocks_json: Mapped[str] = mapped_column(Text)
    style_guide_json: Mapped[str] = mapped_column(Text)
    illustration_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Main human character role from the brief (e.g. "male" or "female").
    # Drives statistical-distribution validation. Nullable for legacy rows
    # that pre-date the column.
    main_character_role: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # JSON-encoded list of 5 Environment objects, position == scene_index.
    # See app.schemas.claude.Environment for shape. Nullable for legacy rows.
    environments_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # JSON-encoded list of NarrativeEntity objects — the unified register of
    # story-important non-human characters and objects (replaces the legacy
    # companion / reserved_entities split). Each entry has importance
    # (primary|secondary|supporting), kind (non_human_character|object), and
    # optional reserved_for_scene_index (scene lock). See
    # app.schemas.claude.NarrativeEntity. Nullable for legacy rows.
    narrative_entities_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    illustrations: Mapped[list["Illustration"]] = relationship(
        "Illustration", back_populates="run", order_by="Illustration.scene_index"
    )


class Illustration(Base):
    __tablename__ = "illustrations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"), nullable=False)
    scene_index: Mapped[int] = mapped_column(Integer)
    scene_excerpt: Mapped[str] = mapped_column(Text)
    paragraph_index: Mapped[int] = mapped_column(Integer)
    character_role: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    current_workflow: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    initial_concept: Mapped[str] = mapped_column(Text)
    current_concept: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String, default=IllustrationState.PENDING)
    concept_attempt: Mapped[int] = mapped_column(Integer, default=1)
    prompt_attempt: Mapped[int] = mapped_column(Integer, default=1)
    current_prompts_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    last_verdict_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # Label of the NarrativeEntity (non-human character or object) visually
    # present in this scene. Null when the scene contains no narrative
    # entity. Source-of-truth for the unified entity register; the actual
    # entity record lives on Run.narrative_entities_json (matched by
    # normalized label). See app.schemas.claude.IllustrationConcept.
    contains_entity_label: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Denormalised environment label + aspect for this slot (Run.environments_json
    # is the source of truth; these columns make per-illustration reads cheap
    # and let Agent 4 receive the constraint without joining). Mutated only by
    # Agent 4b on environment rethink. Nullable for legacy rows.
    environment_label: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    environment_aspect: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    manual_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    manual_state_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Auto-pipeline prompting notes — empirical renderer lessons curated by
    # Agent 3 (revise_prompts) across retries. Analogue of the manual flow's
    # ManualIllustrationSession.prompting_notes. Reset by Agent 4b when the
    # environment is swapped (the lesson may have been env-bound). Nullable
    # because notes are optional and only populated once Agent 3 has
    # something worth recording.
    prompting_notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    run: Mapped["Run"] = relationship("Run", back_populates="illustrations")
    manual_session: Mapped["ManualIllustrationSession | None"] = relationship(
        "ManualIllustrationSession",
        back_populates="illustration",
        uselist=False,
    )
    manual_messages: Mapped[list["ManualMessage"]] = relationship(
        "ManualMessage",
        back_populates="illustration",
        order_by="ManualMessage.created_at",
    )
    attempt_history: Mapped[list["IllustrationAttemptHistory"]] = relationship(
        "IllustrationAttemptHistory",
        back_populates="illustration",
        order_by="(IllustrationAttemptHistory.concept_attempt, "
        "IllustrationAttemptHistory.prompt_attempt, "
        "IllustrationAttemptHistory.created_at)",
    )


class IllustrationAttemptHistory(Base):
    """Per-attempt snapshot written after every auto-pipeline Agent 2 verdict.

    The salvage agent (§ 7.1 Call 8) reasons over these rows when the auto
    pipeline has exhausted its budgets. Rows are immutable once written and
    are never deleted by the application.
    """

    __tablename__ = "illustration_attempt_history"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    illustration_id: Mapped[str] = mapped_column(
        String, ForeignKey("illustrations.id"), nullable=False, index=True
    )
    concept_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str] = mapped_column(String, nullable=False)
    concept_used: Mapped[str] = mapped_column(Text, nullable=False)
    concept_localized: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    paragraph_text: Mapped[str] = mapped_column(Text, nullable=False)
    scene_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    environment_label: Mapped[str] = mapped_column(Text, nullable=False)
    environment_kind: Mapped[str] = mapped_column(String, nullable=False)
    environment_aspect: Mapped[str] = mapped_column(String, nullable=False)
    contains_entity_label: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    character_role: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    current_workflow: Mapped[str] = mapped_column(String, nullable=False)
    positive_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    verdict_json: Mapped[str] = mapped_column(Text, nullable=False)
    nuance_only_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    illustration: Mapped["Illustration"] = relationship(
        "Illustration", back_populates="attempt_history"
    )

    __table_args__ = (
        Index(
            "ix_illustration_attempt_history_illustration_nuance",
            "illustration_id",
            "nuance_only_failure",
        ),
    )


class ManualIllustrationSession(Base):
    """One row per illustration that has ever entered the manual flow (§ 6A)."""

    __tablename__ = "manual_illustration_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    illustration_id: Mapped[str] = mapped_column(
        String, ForeignKey("illustrations.id"), nullable=False, unique=True
    )
    sub_phase: Mapped[str] = mapped_column(
        String, nullable=False, default="concept_design", server_default="concept_design"
    )
    last_manual_image_path: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    last_concept_candidate: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    last_agreed_concept: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    prompting_notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    illustration: Mapped["Illustration"] = relationship(
        "Illustration", back_populates="manual_session"
    )


class ManualMessage(Base):
    """Chat row in an illustration's manual flow (§ 6A)."""

    __tablename__ = "manual_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    illustration_id: Mapped[str] = mapped_column(
        String, ForeignKey("illustrations.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    manual_attempt_index: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Per-attempt provenance for `role=image` rows. Populated only when the
    # row is the image record of a manual render; all other roles leave
    # these NULL. Legacy rows from before the migration also stay NULL
    # (frontend disables the corresponding popovers).
    concept_used: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    positive_prompt: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    illustration: Mapped["Illustration"] = relationship(
        "Illustration", back_populates="manual_messages"
    )


class StoryTranslation(Base):
    """Stores translated story_title and story_topic_description per language."""

    __tablename__ = "story_translations"

    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"), primary_key=True)
    language: Mapped[str] = mapped_column(String, primary_key=True)
    story_title: Mapped[str] = mapped_column(Text)
    story_title_source_hash: Mapped[str] = mapped_column(String)
    story_topic_description: Mapped[str] = mapped_column(Text)
    story_topic_description_source_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class StoryBlockTranslation(Base):
    """Stores translated paragraph text per language."""

    __tablename__ = "story_block_translations"

    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"), primary_key=True)
    paragraph_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(String, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    text_source_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class IllustrationConceptTranslation(Base):
    """Per-illustration, per-language translations.

    Stores both the translated concept (technical visual description) and the
    translated scene_excerpt (a short literary quote from the paragraph).
    Either field may be missing if only one has been translated so far, so
    both are nullable.
    """

    __tablename__ = "illustration_concept_translations"

    illustration_id: Mapped[str] = mapped_column(
        String, ForeignKey("illustrations.id"), primary_key=True
    )
    language: Mapped[str] = mapped_column(String, primary_key=True)
    concept_localized: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    concept_localized_source_hash: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    scene_excerpt_localized: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    scene_excerpt_localized_source_hash: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
