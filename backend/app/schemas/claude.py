from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, model_validator

from app.constants import MAX_ILLUSTRATIONS


def _normalize_companion_text(text: str) -> str:
    return " ".join(text.lower().split())


def companion_in_pool(description: str, pool: Iterable[str]) -> bool:
    """Whitespace-tolerant, case-insensitive pool-fidelity check.

    Returns True iff ``description`` matches at least one pool entry by
    exact normalized equality or by normalized substring (either
    direction — pool entry inside description, or description inside
    pool entry).
    """
    norm = _normalize_companion_text(description)
    if not norm:
        return False
    for entry in pool:
        e = _normalize_companion_text(entry)
        if not e:
            continue
        if norm == e or norm in e or e in norm:
            return True
    return False


# ── Shared shapes ────────────────────────────────────────────────────────────


class StyleGuide(BaseModel):
    overall_style_positive: str
    overall_style_negative: str
    character_lora: str
    character_baseline_description: str


class Companion(BaseModel):
    """A non-human companion attached to an illustration.

    Both fields are required and non-empty. Used in Agent 0b output and
    Agent 4 output. The ``description`` must reference an entry in the
    run's ``collected_brief.companions`` pool (pool-fidelity check runs
    server-side, outside this schema).
    """

    description: str
    interaction: str

    @model_validator(mode="after")
    def _validate_non_empty(self) -> "Companion":
        if not self.description.strip():
            raise ValueError("companion.description must be non-empty")
        if not self.interaction.strip():
            raise ValueError("companion.interaction must be non-empty")
        return self


class IllustrationConcept(BaseModel):
    scene_index: int
    scene_excerpt: str
    concept: str
    concept_localized: str | None = None  # Used by Agent 0b; null for Agents 1/3/4
    character_role: Literal["male", "female", "mother"] | None = None
    companion: Companion | None = None


# ── Agent 0a: chat ───────────────────────────────────────────────────────────


class BriefCharacter(BaseModel):
    role: Literal["male", "female", "mother"]
    name_in_story: str
    short_description: str


class BriefCompanion(BaseModel):
    """One companion entry in the brief's agreed pool (Agent 0a)."""

    description: str

    @model_validator(mode="after")
    def _validate_non_empty(self) -> "BriefCompanion":
        if not self.description.strip():
            raise ValueError("companion description must be non-empty")
        return self


class CollectedBrief(BaseModel):
    characters: list[BriefCharacter]
    companions: list[BriefCompanion] = []
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
        if len(self.companions) > 2:
            raise ValueError("companions may contain at most 2 entries")
        return self


class ChatResponse(BaseModel):
    reply: str
    phase: Literal["gathering", "awaiting_confirmation", "confirmed"]
    language: Literal["sk", "cs", "en", "other"] | None = None
    topic_short: str | None = None
    collected_brief: CollectedBrief | None = None

    @model_validator(mode="after")
    def _validate_brief_presence(self) -> "ChatResponse":
        if self.phase == "gathering" and self.collected_brief is not None:
            raise ValueError("collected_brief must be null when phase is 'gathering'")
        if self.phase in ("awaiting_confirmation", "confirmed") and self.collected_brief is None:
            raise ValueError(
                "collected_brief is required when phase is 'awaiting_confirmation' or 'confirmed'"
            )
        if self.phase == "confirmed" and not self.topic_short:
            raise ValueError("topic_short is required when phase is 'confirmed'")
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
    story_topic_description: str
    story_blocks: list[ParagraphBlock | IllustrationBlock]
    style_guide: StyleGuide
    illustrations: list[IllustrationConcept]

    @model_validator(mode="after")
    def _validate_structure(self) -> "BuildStoryResponse":
        # Exact-count rule (§ 7.1 Call 0b rule #4): Agent 0b must return
        # exactly MAX_ILLUSTRATIONS illustrations — no fewer, no more.
        if len(self.illustrations) != MAX_ILLUSTRATIONS:
            raise ValueError(
                f"illustrations must contain exactly {MAX_ILLUSTRATIONS} entries, "
                f"got {len(self.illustrations)}"
            )

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

        # Illustrations and block indices must match 1-to-1
        illus_indices = [i.scene_index for i in self.illustrations]
        if sorted(illus_indices) != sorted(block_indices):
            raise ValueError(
                "scene_index values in illustrations must match those in story_blocks 1-to-1"
            )
        if len(set(illus_indices)) != len(illus_indices):
            raise ValueError("illustration scene_index values must be unique")

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
    workflow: Literal["single-lora", "no-lora"]
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
    workflow: Literal["single-lora", "no-lora"]
    concept: str
    concept_localized: str
    character_role: Literal["male", "female", "mother"] | None
    paragraph_text: str
    scene_excerpt: str
    companion: Companion | None = None

    @model_validator(mode="after")
    def _validate_excerpt_in_paragraph(self) -> "RethinkConceptResponse":
        if self.scene_excerpt not in self.paragraph_text:
            raise ValueError("scene_excerpt must be a verbatim substring of paragraph_text")
        return self


# ── Agent 5: translate ───────────────────────────────────────────────────────


class TranslationItem(BaseModel):
    kind: Literal[
        "story_title",
        "story_topic_description",
        "paragraph",
        "illustration_concept",
        "scene_excerpt",
    ]
    paragraph_index: int | None = None
    scene_index: int | None = None
    translated_text: str


class TranslateResponse(BaseModel):
    translations: list[TranslationItem]
