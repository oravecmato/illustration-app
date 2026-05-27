from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.claude import CollectedBrief, Companion, StyleGuide

# ── Sessions ─────────────────────────────────────────────────────────────────


class SessionMessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class SessionResponse(BaseModel):
    id: str
    state: str
    source_language: str | None
    detected_language: str | None
    topic_short: str | None
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
    language: str | None = None
    detected_language: str | None = None
    topic_short: str | None = None
    # Pre-allocated run id, returned only when phase == "confirmed". The
    # backend persists it on the session and schedules Agent 0b + the
    # pipeline as a background task. The frontend uses it to navigate
    # immediately so the building-state loader is visible while Agent 0b
    # is still working.
    run_id: str | None = None


# ── Runs ─────────────────────────────────────────────────────────────────────


class RunResponse(BaseModel):
    id: str
    session_id: str
    status: str
    source_language: str
    language: str
    topic_short: str
    story_title: str
    story_title_translation_state: Literal["source", "fresh", "stale", "missing"] | None = None
    story_topic_description: str
    story_topic_description_translation_state: (
        Literal["source", "fresh", "stale", "missing"] | None
    ) = None
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
    scene_excerpt_translation_state: Literal["source", "fresh", "stale", "missing"] | None = None
    paragraph_index: int
    character_role: str | None
    current_workflow: str | None
    current_concept: str
    current_concept_translation_state: Literal["source", "fresh", "stale", "missing"] | None = None
    state: str
    concept_attempt: int
    prompt_attempt: int
    image_url: str | None
    companion: Companion | None = None


class RunDetailResponse(BaseModel):
    run: RunResponse
    illustrations: list[IllustrationResponse]


# ── Translations ─────────────────────────────────────────────────────────────


class TranslationItemRequest(BaseModel):
    kind: Literal[
        "story_title",
        "story_topic_description",
        "paragraph",
        "illustration_concept",
        "scene_excerpt",
    ]
    paragraph_index: int | None = None
    scene_index: int | None = None


class TranslationItemResponse(BaseModel):
    kind: Literal[
        "story_title",
        "story_topic_description",
        "paragraph",
        "illustration_concept",
        "scene_excerpt",
    ]
    paragraph_index: int | None = None
    scene_index: int | None = None
    text: str
    source_hash: str


class TranslateRequest(BaseModel):
    language: Literal["sk", "cs", "en"]
    items: list[TranslationItemRequest]


class TranslateResponse(BaseModel):
    items: list[TranslationItemResponse]
