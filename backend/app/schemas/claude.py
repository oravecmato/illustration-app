from typing import Literal

from pydantic import BaseModel, field_validator

from app.constants import MAX_ILLUSTRATIONS


class StyleGuide(BaseModel):
    overall_style_positive: str
    overall_style_negative: str
    character_lora: str
    character_baseline_description: str


class IllustrationConcept(BaseModel):
    scene_index: int
    scene_excerpt: str
    concept: str
    character_role: Literal["male", "female", "mother"]


class AnalyzeStoryResponse(BaseModel):
    style_guide: StyleGuide
    illustrations: list[IllustrationConcept]

    @field_validator("illustrations")
    @classmethod
    def truncate_illustrations(cls, v: list[IllustrationConcept]) -> list[IllustrationConcept]:
        return v[:MAX_ILLUSTRATIONS]


class GeneratePromptsResponse(BaseModel):
    character_positive: str
    character_negative: str
    environment: str


class EvaluateImageResponse(BaseModel):
    ok: bool
    problem: Literal["prompt", "concept"] | None
    reasoning: str
    suggestion: str


# Call 3 output is same schema as Call 1
RevisePromptsResponse = GeneratePromptsResponse


class RethinkConceptResponse(BaseModel):
    concept: str
