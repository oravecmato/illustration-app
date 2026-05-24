from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from app.constants import MAX_ILLUSTRATIONS

# ── Shared shapes ────────────────────────────────────────────────────────────


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


# ── Agent 0a: chat ───────────────────────────────────────────────────────────


class BriefCharacter(BaseModel):
    role: Literal["male", "female", "mother"]
    name_in_story: str
    short_description: str


class CollectedBrief(BaseModel):
    characters: list[BriefCharacter]
    topic: str
    notes: str

    @model_validator(mode="after")
    def _validate_cast(self) -> "CollectedBrief":
        roles = [c.role for c in self.characters]
        if not (1 <= len(roles) <= 3):
            raise ValueError("characters must contain 1 to 3 entries")
        if len(set(roles)) != len(roles):
            raise ValueError("each role may appear at most once")
        if roles == ["mother"]:
            raise ValueError("a brief consisting only of 'mother' is invalid")
        if "mother" in roles and not ({"male", "female"} & set(roles)):
            raise ValueError("'mother' requires at least one of 'male' or 'female'")
        return self


class ChatResponse(BaseModel):
    reply: str
    phase: Literal["gathering", "awaiting_confirmation", "confirmed"]
    collected_brief: CollectedBrief | None

    @model_validator(mode="after")
    def _validate_brief_presence(self) -> "ChatResponse":
        if self.phase == "gathering" and self.collected_brief is not None:
            raise ValueError("collected_brief must be null when phase is 'gathering'")
        if self.phase in ("awaiting_confirmation", "confirmed") and self.collected_brief is None:
            raise ValueError(
                "collected_brief is required when phase is 'awaiting_confirmation' or 'confirmed'"
            )
        return self


# ── Agent 0b: build_story ────────────────────────────────────────────────────


class ParagraphBlock(BaseModel):
    type: Literal["paragraph"]
    text: str


class IllustrationBlock(BaseModel):
    type: Literal["illustration"]
    scene_index: int


StoryBlock = ParagraphBlock | IllustrationBlock


class BuildStoryResponse(BaseModel):
    story_title: str
    story_blocks: list[ParagraphBlock | IllustrationBlock]
    style_guide: StyleGuide
    illustrations: list[IllustrationConcept]

    @field_validator("illustrations")
    @classmethod
    def _truncate_illustrations(cls, v: list[IllustrationConcept]) -> list[IllustrationConcept]:
        return v[:MAX_ILLUSTRATIONS]

    @model_validator(mode="after")
    def _validate_structure(self) -> "BuildStoryResponse":
        blocks = self.story_blocks
        if len(blocks) < 2:
            raise ValueError("story_blocks must contain at least 2 entries")
        if blocks[0].type != "paragraph":
            raise ValueError("story_blocks must start with a paragraph block")
        if blocks[-1].type != "paragraph":
            raise ValueError("story_blocks must end with a paragraph block")

        # No two adjacent illustration blocks
        for prev, curr in zip(blocks, blocks[1:], strict=False):
            if prev.type == "illustration" and curr.type == "illustration":
                raise ValueError("two illustration blocks must not be adjacent")

        # scene_index of illustration blocks must be 0, 1, 2, ... in order
        block_indices = [b.scene_index for b in blocks if isinstance(b, IllustrationBlock)]
        if block_indices != list(range(len(block_indices))):
            raise ValueError(
                "illustration block scene_index values must be 0,1,2,... in document order"
            )

        # Truncated illustrations and block indices must match 1-to-1
        illus_indices = [i.scene_index for i in self.illustrations]
        if sorted(illus_indices) != sorted(block_indices):
            raise ValueError(
                "scene_index values in illustrations must match those in story_blocks 1-to-1"
            )
        if len(set(illus_indices)) != len(illus_indices):
            raise ValueError("illustration scene_index values must be unique")
        if not (1 <= len(self.illustrations) <= MAX_ILLUSTRATIONS):
            raise ValueError(
                f"illustrations must contain between 1 and {MAX_ILLUSTRATIONS} entries"
            )

        # Each scene_excerpt must be a verbatim substring of *some* paragraph block.
        paragraphs = [b.text for b in blocks if isinstance(b, ParagraphBlock)]
        joined = "\n".join(paragraphs)
        for ill in self.illustrations:
            if ill.scene_excerpt not in joined:
                raise ValueError(
                    f"scene_excerpt for scene_index={ill.scene_index} is not a verbatim "
                    "substring of any paragraph block"
                )

        return self


# ── Agents 1, 2, 3, 4 ────────────────────────────────────────────────────────


class GeneratePromptsResponse(BaseModel):
    positive: str
    negative: str


class EvaluateImageResponse(BaseModel):
    ok: bool
    problem: Literal["prompt", "concept"] | None
    reasoning: str
    suggestion: str


# Agent 3 output is same schema as Agent 1
RevisePromptsResponse = GeneratePromptsResponse


class RethinkConceptResponse(BaseModel):
    concept: str
