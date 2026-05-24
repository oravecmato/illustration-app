from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.claude import CollectedBrief, StyleGuide

# ── Sessions ─────────────────────────────────────────────────────────────────


class SessionMessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class SessionResponse(BaseModel):
    id: str
    state: str
    collected_brief: CollectedBrief | None
    run_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[SessionMessageResponse]


class PostMessageRequest(BaseModel):
    content: str


class PostMessageResponse(BaseModel):
    session: SessionResponse
    phase: Literal["gathering", "awaiting_confirmation", "confirmed"]


class FinalizeResponse(BaseModel):
    run_id: str


# ── Runs ─────────────────────────────────────────────────────────────────────


class RunResponse(BaseModel):
    id: str
    session_id: str
    status: str
    story_title: str
    story_blocks: list[dict[str, Any]]
    style_guide: StyleGuide
    illustration_count: int
    completed_count: int
    failed_count: int
    created_at: datetime
    updated_at: datetime
    error_code: str | None
    error_message: str | None


class IllustrationResponse(BaseModel):
    id: str
    scene_index: int
    scene_excerpt: str
    character_role: str
    current_concept: str
    state: str
    concept_attempt: int
    prompt_attempt: int
    image_url: str | None


class RunDetailResponse(BaseModel):
    run: RunResponse
    illustrations: list[IllustrationResponse]
