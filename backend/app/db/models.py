import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
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
    # Access-gating provenance (§ 8.11). The opaque access-key string that
    # consumed the quota slot for this run. Nullable for legacy rows from
    # before the gating migration; populated for every new run by the
    # finalize handler. ON DELETE SET NULL so deleting a key from the
    # admin CLI does not cascade-delete historical runs.
    access_key: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("access_keys.key", ondelete="SET NULL"), nullable=True, default=None
    )
    # Idempotency guard for the quota-refund path. Flipped from False to
    # True exactly once when the run terminates with every illustration in
    # an infra-noise bucket (RENDER_TIMEOUT / OOM_REAPED) or with
    # run.error_code=INTERNAL_ERROR. The atomic conditional UPDATE in
    # ``app/api/auth.py::refund_run_quota`` uses this column to make the
    # refund safe under the orchestrator/reap race.
    quota_refunded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

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
    # Structured error category, parallel to ``error_message``. Populated when
    # ``state == FAILED`` so diagnostics can distinguish infrastructure
    # failures (e.g. ``RENDER_TIMEOUT`` — GPU pool stalled, not a prompt
    # problem) from prompt-engineering exhaustions. Nullable: legacy rows
    # and successful illustrations leave it ``None``.
    error_code: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # RunPod job ID of the currently in-flight render (RENDERING /
    # MANUAL_RENDERING). Persisted at submit time and cleared on any
    # terminal outcome (COMPLETED / FAILED). Drives the orphan-resumer
    # in ``app/main.py``: on startup we re-poll any persisted job_id so
    # restart-killed pollers don't waste an already-paid GPU result.
    # Nullable: most of the time no render is in flight.
    runpod_job_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
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
    # Agent 3's declared diff plan (RevisionSummary), JSON-encoded.
    # NULL on the FIRST attempt of every concept because that attempt's
    # prompts come from Agent 1 (GeneratePromptsResponse — no diff to
    # report). Non-null on every subsequent attempt where prompts came
    # from Agent 3 (RevisePromptsResponse).
    revision_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    verdict_json: Mapped[str] = mapped_column(Text, nullable=False)
    nuance_only_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # ComfyUI KSampler seed used for this render. Stored so the salvage
    # agent can detect whether attempts shared a seed (and thus are
    # bit-identical regardless of prompt revisions). Nullable for rows
    # written before the SEED placeholder was introduced.
    seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
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


class AccessKey(Base):
    """Demo-gating access key (§ 5.6, § 8.11).

    Opaque URL-safe string issued by the operator via ``make grant``.
    Each key holds a soft quota of runs (``runs_allowed``) that
    ``require_access_key`` enforces on every paid endpoint
    (``PAID_ENDPOINTS`` in ``app/constants.py``). Admin keys carry
    ``runs_allowed = NULL`` and bypass the quota check while still going
    through the same auth path so the deployment never has a parallel
    no-auth code path that could be reached by accident.
    """

    __tablename__ = "access_keys"

    # Generated via ``secrets.token_urlsafe(24)`` → up to 32 chars of
    # URL-safe base64. 64 col width gives headroom for future widening.
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Human-readable label for the admin CLI's `list-keys` output. Free
    # text, e.g. "Demo invite for Alex" or "Personal admin (Martin)".
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL == admin / unlimited. A non-null integer is the hard ceiling
    # on the number of finalised runs the key may pay for.
    runs_allowed: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Monotonically increasing tally of consumed slots. Atomic
    # conditional UPDATE in ``app/api/auth.py::consume_run_quota``
    # increments this; ``refund_run_quota`` decrements it (clamped at 0).
    runs_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Touched by ``require_access_key`` on every authenticated request
    # so the admin CLI can report stale / unused keys at a glance.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # Set when the operator revokes the key via ``make revoke``. The
    # row is NOT deleted because deletion would cascade-nullify the
    # ``runs.access_key`` provenance of historical runs.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
