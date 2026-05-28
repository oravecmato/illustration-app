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


# ── Environment ──────────────────────────────────────────────────────────────


def _normalize_env_label(text: str) -> str:
    """Whitespace-collapsed, case-folded label for cross-illustration comparison."""
    return " ".join(text.lower().split())


class Environment(BaseModel):
    """One per illustration slot. ``label`` is the short locale-specific name
    (e.g. ``"obývačka"``, ``"školská chodba"``, ``"auto"``). The pair
    ``(kind, aspect)`` encodes whether the location is a single-form
    indoor/outdoor place or a *dual* place that can be depicted from
    inside OR outside (a car, a plane, a ship, a wooden cabin). Dual
    places may occupy two of the five scene slots (one ``inside``, one
    ``outside``); plain ``indoor``/``outdoor`` places occupy exactly one.
    """

    label: str
    kind: Literal["indoor", "outdoor", "dual"]
    aspect: Literal["single", "inside", "outside"]

    @model_validator(mode="after")
    def _validate(self) -> "Environment":
        if not self.label.strip():
            raise ValueError("environment.label must be non-empty")
        if self.kind in ("indoor", "outdoor") and self.aspect != "single":
            raise ValueError(f"environment.aspect must be 'single' when kind={self.kind!r}")
        if self.kind == "dual" and self.aspect not in ("inside", "outside"):
            raise ValueError("environment.aspect must be 'inside' or 'outside' when kind='dual'")
        return self


# ── Reserved entities (non-human characters and story-important objects) ─────


class ReservedEntity(BaseModel):
    """A non-human character or story-important object reserved at a specific
    illustration slot (or unassigned). Once an entity is reserved for a
    ``scene_index``, no other illustration may depict it — this side-steps
    cross-illustration object/character consistency, which our renderer
    cannot guarantee.

    The ``kind`` discriminates a recurring non-human character (which also
    appears in the brief's ``companions`` pool when used in a scene) from a
    plain story-important object. ``importance`` ranks the entity for the
    statistical-distribution rules (primary NH-char appears exactly once,
    secondary NH-char at most once and only with a human).

    Disambiguation rule (cars / boats / planes etc.): if a human is at any
    point in the story *inside* the entity, treat it as an environment and
    do NOT add it here; otherwise add it as kind=``"object"``.
    """

    label: str
    kind: Literal["non_human_character", "object"]
    importance: Literal["primary", "secondary"]
    reserved_for_scene_index: int | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ReservedEntity":
        if not self.label.strip():
            raise ValueError("reserved_entity.label must be non-empty")
        if (
            self.reserved_for_scene_index is not None
            and not 0 <= self.reserved_for_scene_index < MAX_ILLUSTRATIONS
        ):
            raise ValueError(
                f"reserved_for_scene_index must be in 0..{MAX_ILLUSTRATIONS - 1} or null"
            )
        return self


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
    main_character_role: Literal["male", "female", "mother"]

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
        # main_character_role must reference an actual cast member, and (per
        # the new statistical distribution rules) cannot be 'mother' unless
        # she is the only human besides herself — which the prior rule
        # forbids. So in practice: main is always male or female.
        if self.main_character_role not in roles:
            raise ValueError(
                f"main_character_role must be one of the characters' roles ({roles!r})"
            )
        if self.main_character_role == "mother" and len(roles) > 1:
            raise ValueError(
                "main_character_role='mother' is only valid when she is the "
                "sole human in the cast — which the cast rules forbid; pick "
                "the male or female lead as main_character_role instead"
            )
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
    # Position N in the list is the environment locked to scene_index=N.
    # See ``Environment`` docstring for dual-aspect semantics.
    environments: list[Environment]
    # Story-important non-human characters and objects. Entries may be
    # ``reserved_for_scene_index=None`` at A0b time if the agent could not
    # commit them to a specific slot yet — orchestrator/A4 must still
    # respect them as exclusion zones for *other* slots.
    reserved_entities: list[ReservedEntity] = []

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

        # Environments: exactly MAX_ILLUSTRATIONS entries; position == scene_index.
        if len(self.environments) != MAX_ILLUSTRATIONS:
            raise ValueError(
                f"environments must contain exactly {MAX_ILLUSTRATIONS} entries, "
                f"got {len(self.environments)}"
            )

        # Group environments by normalized label and enforce dual rules.
        groups: dict[str, list[tuple[int, Environment]]] = {}
        for idx, env in enumerate(self.environments):
            groups.setdefault(_normalize_env_label(env.label), []).append((idx, env))
        for norm_label, group in groups.items():
            kinds = {env.kind for _, env in group}
            if len(kinds) > 1:
                raise ValueError(
                    f"environments sharing label {norm_label!r} must have a "
                    f"consistent kind (got {sorted(kinds)})"
                )
            kind = next(iter(kinds))
            if kind in ("indoor", "outdoor") and len(group) > 1:
                raise ValueError(
                    f"environment label {norm_label!r} is {kind!r} and may "
                    "appear in only one scene slot"
                )
            if kind == "dual":
                if len(group) > 2:
                    raise ValueError(
                        f"dual environment {norm_label!r} may occupy at most "
                        "2 scene slots (inside + outside)"
                    )
                aspects = sorted(env.aspect for _, env in group)
                if len(group) == 2 and aspects != ["inside", "outside"]:
                    raise ValueError(
                        f"dual environment {norm_label!r} occupying 2 slots "
                        "must use one 'inside' aspect and one 'outside' "
                        f"aspect (got {aspects})"
                    )

        # Reserved entities: at most one reservation per scene_index.
        seen_reservations: dict[int, str] = {}
        for entity in self.reserved_entities:
            if entity.reserved_for_scene_index is None:
                continue
            idx = entity.reserved_for_scene_index
            if idx in seen_reservations:
                raise ValueError(
                    f"scene_index={idx} has multiple reserved entities "
                    f"({seen_reservations[idx]!r} and {entity.label!r}); "
                    "at most one reserved entity may be tied to a single "
                    "scene"
                )
            seen_reservations[idx] = entity.label

        # Primary/secondary cardinality (cross-illustration distribution
        # rules — Statistical distribution §). At most one primary
        # non-human character; at most one secondary non-human character.
        # Object importance is unconstrained at this layer because the
        # statistical rules speak about NH-characters and "standalone
        # object shots" separately; the standalone-shot cap is enforced
        # by ``validate_illustration_distribution``.
        primary_nh = [
            e
            for e in self.reserved_entities
            if e.kind == "non_human_character" and e.importance == "primary"
        ]
        if len(primary_nh) > 1:
            raise ValueError(
                "at most one reserved non_human_character may have "
                f"importance='primary' (got {len(primary_nh)})"
            )
        secondary_nh = [
            e
            for e in self.reserved_entities
            if e.kind == "non_human_character" and e.importance == "secondary"
        ]
        if len(secondary_nh) > 1:
            raise ValueError(
                "at most one reserved non_human_character may have "
                f"importance='secondary' (got {len(secondary_nh)})"
            )

        return self


# ── Agents 1, 2, 3, 4 ────────────────────────────────────────────────────────


class GeneratePromptsResponse(BaseModel):
    workflow: Literal["single-lora", "no-lora"]
    positive: str
    negative: str


class EvaluateImageResponse(BaseModel):
    """Verdict from Agent 2 (evaluate_image).

    ``problem`` discriminates which downstream agent the orchestrator
    routes to:

    * ``"prompt"`` — fixable by tag revision in the same concept
      (Agent 3 / revise_prompts).
    * ``"concept"`` — concept must be rewritten in the *same* environment
      (Agent 4 / rethink_concept).
    * ``"environment"`` — the locked environment itself is the renderer
      blocker; concept revision in-place cannot help. Orchestrator
      routes to Agent 4b (rethink_environment), which is the only agent
      allowed to swap the environment for a slot.
    """

    ok: bool
    problem: Literal["prompt", "concept", "environment"] | None
    reasoning: str
    suggestion: str


# Agent 3 output is same schema as Agent 1
RevisePromptsResponse = GeneratePromptsResponse


class RethinkConceptResponse(BaseModel):
    """Agent 4 output.

    The environment is a hard constraint for Agent 4 — it cannot move the
    scene to a new location. If the renderer's blocker is the environment
    itself, the Evaluator emits ``problem="environment"`` and the
    orchestrator routes to Agent 4b (``RethinkEnvironmentResponse``) instead.

    ``narrative_continuity_check`` is a 1–3 sentence English self-audit the
    agent must write *after* drafting ``paragraph_text``. The agent has to
    read the trio ⟨previous paragraph, new paragraph, next paragraph⟩ as a
    whole and explain how the new paragraph flows smoothly between them
    AND what story-level purpose it serves (so the rewrite is never just
    filler text shaped to fit a pretty picture).
    """

    workflow: Literal["single-lora", "no-lora"]
    concept: str
    concept_localized: str
    character_role: Literal["male", "female", "mother"] | None
    paragraph_text: str
    scene_excerpt: str
    companion: Companion | None = None
    narrative_continuity_check: str

    @model_validator(mode="after")
    def _validate(self) -> "RethinkConceptResponse":
        if self.scene_excerpt not in self.paragraph_text:
            raise ValueError("scene_excerpt must be a verbatim substring of paragraph_text")
        if not self.narrative_continuity_check.strip():
            raise ValueError("narrative_continuity_check must be a non-empty string")
        return self


# ── Agent 4b: rethink_environment ────────────────────────────────────────────


class RethinkEnvironmentResponse(BaseModel):
    """Agent 4b output.

    Activated when the Evaluator emits ``problem="environment"``. Unlike
    Agent 4, this agent is allowed — and required — to swap the
    illustration slot to a qualitatively new environment whose features
    avoid the renderer blocker that the Evaluator flagged.

    The replacement environment MUST be disjoint from the other four
    in-use environments to preserve the global no-consistency-needed
    invariant. The same narrative-continuity contract that binds Agent 4
    applies here: the rewritten paragraph must flow smoothly between its
    neighbours and carry real story weight.
    """

    workflow: Literal["single-lora", "no-lora"]
    concept: str
    concept_localized: str
    character_role: Literal["male", "female", "mother"] | None
    paragraph_text: str
    scene_excerpt: str
    companion: Companion | None = None
    environment: Environment
    narrative_continuity_check: str

    @model_validator(mode="after")
    def _validate(self) -> "RethinkEnvironmentResponse":
        if self.scene_excerpt not in self.paragraph_text:
            raise ValueError("scene_excerpt must be a verbatim substring of paragraph_text")
        if not self.narrative_continuity_check.strip():
            raise ValueError("narrative_continuity_check must be a non-empty string")
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


# ── Agent 6: manual_concept ──────────────────────────────────────────────────


ManualPhase = Literal[
    "gathering",
    "awaiting_concept_confirmation",
    "concept_confirmed",
    "gathering_feedback",
    "awaiting_feedback_confirmation",
    "feedback_confirmed",
    "restart_concept",
    "accepted",
]

ManualSubPhase = Literal["concept_design", "feedback_gathering"]


class ManualConceptResponse(BaseModel):
    """Agent 6 output for the § 6A manual chat fallback.

    The phase flag drives the server-side state machine. See § 7.1 Call 6
    for the full phase semantics. The cross-field invariant enforced here:

    * ``concept_candidate`` is required (non-empty) iff
      ``phase in {awaiting_concept_confirmation, concept_confirmed}``;
      it MUST be null for every other phase.
    * ``reply`` is non-empty for every phase except ``accepted``, where
      an empty string is tolerated (mirrors Agent 0a's `phase=confirmed`).
    """

    phase: ManualPhase
    reply: str
    concept_candidate: str | None = None
    prompting_notes_update: str | None = None

    @model_validator(mode="after")
    def _validate_phase(self) -> "ManualConceptResponse":
        if self.phase in ("awaiting_concept_confirmation", "concept_confirmed"):
            if not self.concept_candidate or not self.concept_candidate.strip():
                raise ValueError(f"concept_candidate is required when phase is {self.phase!r}")
        else:
            if self.concept_candidate is not None:
                raise ValueError(f"concept_candidate must be null when phase is {self.phase!r}")
        # `accepted` may carry an empty reply; everything else must be non-empty.
        if self.phase != "accepted" and (not self.reply or not self.reply.strip()):
            raise ValueError("reply must be a non-empty string")
        # `prompting_notes_update`, when present, must be a non-empty string
        # (Agent 6 either updates the memo with content or omits the field;
        # an empty/whitespace-only update is treated as malformed). § 6A.2 #12.
        if self.prompting_notes_update is not None and not self.prompting_notes_update.strip():
            raise ValueError("prompting_notes_update must be a non-empty string when provided")
        return self


# ── Agent 7: manual_revise_prompts ───────────────────────────────────────────


class ManualRevisePromptsResponse(BaseModel):
    """Agent 7 output. Narrower than Agent 1/3: no `workflow` field, because
    the workflow choice is fixed by the illustration's `character_role`
    and Agent 7 cannot toggle it (§ 6A.4 step 5.5 / § 7.1 Call 7)."""

    positive: str
    negative: str

    @model_validator(mode="after")
    def _validate_non_empty(self) -> "ManualRevisePromptsResponse":
        if not self.positive or not self.positive.strip():
            raise ValueError("positive must be a non-empty string")
        if not self.negative or not self.negative.strip():
            raise ValueError("negative must be a non-empty string")
        return self


# ── Cross-illustration distribution validator (auto pipeline only) ───────────


def validate_illustration_distribution(
    brief: CollectedBrief,
    illustrations: list[IllustrationConcept],
    reserved_entities: list[ReservedEntity],
) -> None:
    """Enforce the statistical-distribution rules across all 5 auto-pipeline
    illustrations.

    Rules (auto pipeline only — manual co-creation ignores this validator):

    1. Every cast role in ``brief.characters`` appears at least once across
       ``illustrations[*].character_role``.
    2. ``brief.main_character_role`` appears at least twice.
    3. No side cast role appears more often than the main role.
    4. At most one illustration has ``character_role=None``
       (the no-human cap of 1/5 for the auto pipeline).
    5. The primary non-human-character reserved entity (if any) is
       reserved to exactly one ``scene_index``. The illustration at that
       index must either be ``character_role=None`` (alone shot) or carry
       the main character.
    6. The secondary non-human-character reserved entity (if any) may be
       reserved to at most one ``scene_index``; if reserved, the
       illustration there must carry the main character (not alone).
    7. At most one illustration may be a standalone object/scenery shot —
       an illustration with ``character_role=None`` whose only reserved
       entity is an object (or no entity at all). This shares the cap
       with rule #4.

    Raises ``ValueError`` on the first violation. Callers must catch it
    and trigger an A0b retry (or fail the run with
    ``STORY_BUILD_FAILED`` after exhausting retries).
    """
    cast_roles = [c.role for c in brief.characters]
    main = brief.main_character_role

    # Per-illustration role tallies (None included as the no-human bucket).
    role_counts: dict[str | None, int] = {}
    for ill in illustrations:
        role_counts[ill.character_role] = role_counts.get(ill.character_role, 0) + 1

    # Rule 1: every cast role at least once.
    for role in cast_roles:
        if role_counts.get(role, 0) < 1:
            raise ValueError(f"cast role {role!r} must appear in at least one illustration")

    # Rule 2: main role at least twice.
    if role_counts.get(main, 0) < 2:
        raise ValueError(
            f"main_character_role={main!r} must appear in at least 2 "
            f"illustrations (got {role_counts.get(main, 0)})"
        )

    # Rule 3: no side role exceeds main.
    main_count = role_counts.get(main, 0)
    for role in cast_roles:
        if role == main:
            continue
        if role_counts.get(role, 0) > main_count:
            raise ValueError(
                f"side role {role!r} appears {role_counts.get(role, 0)} "
                f"times, exceeding main_character_role={main!r}'s "
                f"{main_count} appearances"
            )

    # Rule 4: at most one no-human illustration.
    no_human_count = role_counts.get(None, 0)
    if no_human_count > 1:
        raise ValueError(
            "at most 1 illustration may have character_role=null in the "
            f"auto pipeline (got {no_human_count})"
        )

    # Reservations indexed by scene_index for cross-checks.
    reservations_by_index: dict[int, ReservedEntity] = {}
    for entity in reserved_entities:
        if entity.reserved_for_scene_index is not None:
            reservations_by_index[entity.reserved_for_scene_index] = entity

    # Rules 5 & 6: primary / secondary non-human characters.
    primary_nh = next(
        (
            e
            for e in reserved_entities
            if e.kind == "non_human_character" and e.importance == "primary"
        ),
        None,
    )
    if primary_nh is not None:
        if primary_nh.reserved_for_scene_index is None:
            raise ValueError(
                "primary non_human_character reserved entity "
                f"{primary_nh.label!r} must be reserved to exactly one "
                "scene_index"
            )
        target = illustrations[primary_nh.reserved_for_scene_index]
        if target.character_role not in (None, main):
            raise ValueError(
                f"primary non_human_character {primary_nh.label!r} is "
                f"reserved for scene_index={primary_nh.reserved_for_scene_index} "
                f"whose character_role={target.character_role!r} is "
                f"neither null (alone shot) nor the main role {main!r}"
            )

    secondary_nh = next(
        (
            e
            for e in reserved_entities
            if e.kind == "non_human_character" and e.importance == "secondary"
        ),
        None,
    )
    if secondary_nh is not None and secondary_nh.reserved_for_scene_index is not None:
        target = illustrations[secondary_nh.reserved_for_scene_index]
        if target.character_role != main:
            raise ValueError(
                f"secondary non_human_character {secondary_nh.label!r} is "
                f"reserved for scene_index={secondary_nh.reserved_for_scene_index} "
                f"whose character_role={target.character_role!r} is not "
                f"the main role {main!r}; secondary NH characters must "
                "appear with the main human"
            )

    # Rule 7: standalone object/scenery cap shares the no-human budget,
    # which is already capped by rule 4 — nothing extra to validate here
    # unless we ever raise the no-human cap above 1.
