from datetime import datetime

from pydantic import BaseModel

from app.schemas.claude import StyleGuide


class CreateRunRequest(BaseModel):
    story_text: str


class CreateRunResponse(BaseModel):
    run_id: str


class RunResponse(BaseModel):
    id: str
    status: str
    story_text: str
    style_guide: StyleGuide | None
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
