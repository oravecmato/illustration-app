import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


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
    story_title: Mapped[str] = mapped_column(Text)
    story_blocks_json: Mapped[str] = mapped_column(Text)
    style_guide_json: Mapped[str] = mapped_column(Text)
    illustration_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    illustrations: Mapped[list["Illustration"]] = relationship(
        "Illustration", back_populates="run", order_by="Illustration.scene_index"
    )


class Illustration(Base):
    __tablename__ = "illustrations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"), nullable=False)
    scene_index: Mapped[int] = mapped_column(Integer)
    scene_excerpt: Mapped[str] = mapped_column(Text)
    character_role: Mapped[str] = mapped_column(String)
    initial_concept: Mapped[str] = mapped_column(Text)
    current_concept: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String, default=IllustrationState.PENDING)
    concept_attempt: Mapped[int] = mapped_column(Integer, default=1)
    prompt_attempt: Mapped[int] = mapped_column(Integer, default=1)
    current_prompts_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    last_verdict_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    run: Mapped["Run"] = relationship("Run", back_populates="illustrations")
