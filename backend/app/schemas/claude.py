from typing import Literal

from pydantic import BaseModel, model_validator

from app.constants import MAX_ILLUSTRATIONS


def _normalize_entity_label(text: str) -> str:
    """Whitespace-collapsed, case-folded label for cross-illustration comparison."""
    return " ".join(text.lower().split())


# ── Shared shapes ────────────────────────────────────────────────────────────


class StyleGuide(BaseModel):
    overall_style_positive: str
    overall_style_negative: str
    character_lora: str
    character_baseline_description: str


# ── Environment ──────────────────────────────────────────────────────────────


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


# ── Narrative entities (non-human characters + story-important objects) ─────


class NarrativeEntity(BaseModel):
    """One non-human character or story-important object that belongs to the
    story. The unified replacement for the legacy ``companion`` /
    ``reserved_entity`` split — there is only one register now and the
    same rules apply uniformly to friendly creatures, antagonists, and
    objects.

    ``importance`` ranks the entity for cross-illustration quotas
    (cf. ``validate_illustration_distribution``):

    * ``primary`` — at most ONE primary NH-character per story. MUST be
      pre-reserved to a specific ``scene_index`` by Agent 0b. Targets
      exactly one appearance overall (graceful drop by Agent 4 may
      lower this to zero — see locking semantics).
    * ``secondary`` — at most ONE secondary NH-character per story.
      MUST be pre-reserved by Agent 0b. At most one appearance overall,
      AND the slot where it appears must contain at least one human
      cast member (it may never appear alone).
    * ``supporting`` — any number of supporting NH-characters and
      objects. May be ``reserved_for_scene_index=None`` (floating) when
      first emitted by Agent 0b; the first agent that includes a
      floating entity in a scene permanently claims that slot for it.
      At most one appearance per supporting entity.

    Locking semantics (the ``reserved_for_scene_index`` field):

    * Once set to ``N``, never changes — even if Agent 4 later drops
      the entity from slot ``N`` (graceful degradation), the entity
      stays forever associated with that slot and may NEVER appear in
      any other slot. This sidesteps cross-illustration consistency
      problems the renderer cannot solve.
    * ``None`` means "floating" — eligible to be claimed by any later
      agent into the slot it's being rewritten for. Only supporting
      entities may be floating at Agent 0b time.

    Disambiguation (cars / boats / planes / cabins): if a human is at
    any point in the story *inside* the entity, treat it as an
    ``Environment`` and do NOT add it here; otherwise add it as
    ``kind="object"``.
    """

    label: str
    kind: Literal["non_human_character", "object"]
    importance: Literal["primary", "secondary", "supporting"]
    reserved_for_scene_index: int | None = None

    @model_validator(mode="after")
    def _validate(self) -> "NarrativeEntity":
        if not self.label.strip():
            raise ValueError("narrative_entity.label must be non-empty")
        if (
            self.reserved_for_scene_index is not None
            and not 0 <= self.reserved_for_scene_index < MAX_ILLUSTRATIONS
        ):
            raise ValueError(
                f"reserved_for_scene_index must be in 0..{MAX_ILLUSTRATIONS - 1} or null"
            )
        # Primary/secondary NH characters MUST be reserved by Agent 0b.
        # Only supporting entities may be floating.
        if self.importance in ("primary", "secondary") and self.kind != "non_human_character":
            raise ValueError(
                "importance='primary' and importance='secondary' are reserved "
                "for kind='non_human_character'; use 'supporting' for objects"
            )
        if self.importance in ("primary", "secondary") and self.reserved_for_scene_index is None:
            raise ValueError(
                f"importance={self.importance!r} entity {self.label!r} must "
                "have reserved_for_scene_index set (only 'supporting' entities "
                "may be floating)"
            )
        return self


class IllustrationConcept(BaseModel):
    """One illustration slot. ``contains_entity_label`` is the single
    handle for "what non-human entity is visually present in this
    scene"; it replaces the legacy ``companion`` field. When non-null,
    the label MUST match an entity in the run's narrative_entities
    register, AND that entity's ``reserved_for_scene_index`` must equal
    this illustration's ``scene_index`` (or be ``None`` at the moment of
    placement, in which case the placement implicitly claims the slot).
    """

    scene_index: int
    scene_excerpt: str
    concept: str
    concept_localized: str | None = None  # Used by Agent 0b; null for Agents 1/3/4
    character_role: Literal["male", "female", "mother"] | None = None
    contains_entity_label: str | None = None


# ── Agent 0a: chat ───────────────────────────────────────────────────────────


class BriefCharacter(BaseModel):
    role: Literal["male", "female", "mother"]
    name_in_story: str
    short_description: str


class NonHumanEntityHint(BaseModel):
    """One non-human entity hint collected from the user during chat.

    Replaces the legacy ``BriefCompanion`` and broadens the concept: this
    now covers friendly companions, antagonists, recurring creatures,
    and story-important objects alike. Agent 0b promotes each hint into
    a ``NarrativeEntity`` with concrete importance + slot reservation.

    ``role_in_story`` is free-form English text the agent uses to decide
    importance (e.g. ``"ally"``, ``"antagonist"``, ``"recurring
    presence"``, ``"sentimental keepsake"``).
    """

    label: str
    role_in_story: str

    @model_validator(mode="after")
    def _validate(self) -> "NonHumanEntityHint":
        if not self.label.strip():
            raise ValueError("non_human_entity.label must be non-empty")
        if not self.role_in_story.strip():
            raise ValueError("non_human_entity.role_in_story must be non-empty")
        return self


class CollectedBrief(BaseModel):
    characters: list[BriefCharacter]
    non_human_entities: list[NonHumanEntityHint] = []
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
        # Non-human entity label uniqueness (normalized).
        seen_labels: set[str] = set()
        for ent in self.non_human_entities:
            norm = _normalize_entity_label(ent.label)
            if norm in seen_labels:
                raise ValueError(f"non_human_entities contains duplicate label {ent.label!r}")
            seen_labels.add(norm)
        # main_character_role must reference an actual cast member.
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
    # Unified register of all story-important non-human characters and
    # objects. Replaces the legacy ``reserved_entities`` + ``companions``
    # split. See ``NarrativeEntity`` for shape and locking semantics.
    narrative_entities: list[NarrativeEntity] = []

    @model_validator(mode="after")
    def _validate_structure(self) -> "BuildStoryResponse":
        # Exact-count rule (§ 7.1 Call 0b rule #4).
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

        # No two adjacent illustration blocks.
        for prev, curr in zip(blocks, blocks[1:], strict=False):
            if prev.type == "illustration" and curr.type == "illustration":
                raise ValueError("two illustration blocks must not be adjacent")

        # scene_index of illustration blocks must be 0, 1, 2, ... in order.
        block_indices = [b.scene_index for b in blocks if isinstance(b, IllustrationBlock)]
        if block_indices != list(range(len(block_indices))):
            raise ValueError(
                "illustration block scene_index values must be 0,1,2,... in document order"
            )

        # Illustrations and block indices must match 1-to-1.
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
        env_groups: dict[str, list[tuple[int, Environment]]] = {}
        for idx, env in enumerate(self.environments):
            env_groups.setdefault(_normalize_entity_label(env.label), []).append((idx, env))
        for norm_label, group in env_groups.items():
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

        # narrative_entities: label uniqueness (normalized).
        seen_entity_labels: set[str] = set()
        for entity in self.narrative_entities:
            norm = _normalize_entity_label(entity.label)
            if norm in seen_entity_labels:
                raise ValueError(f"narrative_entities contains duplicate label {entity.label!r}")
            seen_entity_labels.add(norm)
            # narrative_entity labels must not collide with environment labels.
            if norm in env_groups:
                raise ValueError(
                    f"narrative_entity label {entity.label!r} collides with an "
                    "environment label; entities and environments live in "
                    "disjoint namespaces"
                )

        # Primary / secondary NH character cardinality.
        primary_nh = [
            e
            for e in self.narrative_entities
            if e.kind == "non_human_character" and e.importance == "primary"
        ]
        if len(primary_nh) > 1:
            raise ValueError(
                "at most one narrative_entity may have kind='non_human_character' "
                f"and importance='primary' (got {len(primary_nh)})"
            )
        secondary_nh = [
            e
            for e in self.narrative_entities
            if e.kind == "non_human_character" and e.importance == "secondary"
        ]
        if len(secondary_nh) > 1:
            raise ValueError(
                "at most one narrative_entity may have kind='non_human_character' "
                f"and importance='secondary' (got {len(secondary_nh)})"
            )

        # contains_entity_label fidelity: every non-null value must reference
        # a registered entity, and the entity-side scene lock must hold —
        # if entity.reserved_for_scene_index is set, only that scene_index
        # may carry the entity. (Slots may host multiple *historically*
        # reserved entities but only ONE active contains_entity_label per
        # slot, which is enforced structurally by the schema since each
        # IllustrationConcept has at most one contains_entity_label.)
        entity_by_label: dict[str, NarrativeEntity] = {
            _normalize_entity_label(e.label): e for e in self.narrative_entities
        }
        for ill in self.illustrations:
            if ill.contains_entity_label is None:
                continue
            norm = _normalize_entity_label(ill.contains_entity_label)
            if norm not in entity_by_label:
                raise ValueError(
                    f"illustration scene_index={ill.scene_index} references "
                    f"contains_entity_label={ill.contains_entity_label!r} which "
                    "is not in the narrative_entities register"
                )
            ent = entity_by_label[norm]
            if (
                ent.reserved_for_scene_index is not None
                and ent.reserved_for_scene_index != ill.scene_index
            ):
                raise ValueError(
                    f"illustration scene_index={ill.scene_index} references "
                    f"entity {ent.label!r} which is reserved for scene_index="
                    f"{ent.reserved_for_scene_index}; entities are scene-locked"
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


# Agent 3 output is same schema as Agent 1.
RevisePromptsResponse = GeneratePromptsResponse


class RethinkConceptResponse(BaseModel):
    """Agent 4 output.

    The environment is a hard constraint — Agent 4 cannot move the
    scene. If the renderer's blocker is the environment itself, the
    Evaluator emits ``problem="environment"`` and the orchestrator
    routes to Agent 4b (``RethinkEnvironmentResponse``) instead.

    Entity placement (the unified narrative_entities system):

    * ``contains_entity_label`` — the entity Agent 4 commits to depict
      in this rewrite (or ``None`` for a clean scene). Must reference
      either (a) the entity reserved for this slot, (b) a floating
      supporting entity Agent 4 is claiming for this slot, or (c) be
      ``None`` (drop or clean scene). Including an entity reserved for
      a DIFFERENT slot is rejected by the server.
    * ``entity_action`` — discriminates intent so the server can
      validate the move:
        - ``"keep"`` — entity reserved for this slot stays present
          (contains_entity_label is non-null and matches the
          reservation).
        - ``"drop"`` — entity reserved for this slot is intentionally
          dropped (contains_entity_label is null; the slot stays
          reserved forever — ghost reservation).
        - ``"claim_floating"`` — a floating supporting entity (with
          ``reserved_for_scene_index=None``) is being claimed for this
          slot (contains_entity_label is non-null and matches that
          entity).
        - ``"none"`` — there is no narrative_entity at play in this
          slot (no reservation existed, no claim made).

    ``narrative_continuity_check`` is a 1–3 sentence English self-audit
    Agent 4 must write *after* drafting ``paragraph_text``; see Agent 4
    prompt for details.
    """

    workflow: Literal["single-lora", "no-lora"]
    concept: str
    concept_localized: str
    character_role: Literal["male", "female", "mother"] | None
    paragraph_text: str
    scene_excerpt: str
    contains_entity_label: str | None = None
    entity_action: Literal["keep", "drop", "claim_floating", "none"] = "none"
    narrative_continuity_check: str

    @model_validator(mode="after")
    def _validate(self) -> "RethinkConceptResponse":
        if self.scene_excerpt not in self.paragraph_text:
            raise ValueError("scene_excerpt must be a verbatim substring of paragraph_text")
        if not self.narrative_continuity_check.strip():
            raise ValueError("narrative_continuity_check must be a non-empty string")
        # entity_action ↔ contains_entity_label coherence.
        if self.entity_action in ("keep", "claim_floating"):
            if not self.contains_entity_label or not self.contains_entity_label.strip():
                raise ValueError(
                    f"contains_entity_label must be non-empty when "
                    f"entity_action={self.entity_action!r}"
                )
        else:  # drop, none
            if self.contains_entity_label is not None:
                raise ValueError(
                    f"contains_entity_label must be null when entity_action={self.entity_action!r}"
                )
        return self


# ── Agent 4b: rethink_environment ────────────────────────────────────────────


class RethinkEnvironmentResponse(BaseModel):
    """Agent 4b output. Mirrors Agent 4's entity-placement contract;
    additionally emits a fresh ``Environment`` because this agent's
    raison d'être is swapping the locked environment for a slot.
    """

    workflow: Literal["single-lora", "no-lora"]
    concept: str
    concept_localized: str
    character_role: Literal["male", "female", "mother"] | None
    paragraph_text: str
    scene_excerpt: str
    contains_entity_label: str | None = None
    entity_action: Literal["keep", "drop", "claim_floating", "none"] = "none"
    environment: Environment
    narrative_continuity_check: str

    @model_validator(mode="after")
    def _validate(self) -> "RethinkEnvironmentResponse":
        if self.scene_excerpt not in self.paragraph_text:
            raise ValueError("scene_excerpt must be a verbatim substring of paragraph_text")
        if not self.narrative_continuity_check.strip():
            raise ValueError("narrative_continuity_check must be a non-empty string")
        if self.entity_action in ("keep", "claim_floating"):
            if not self.contains_entity_label or not self.contains_entity_label.strip():
                raise ValueError(
                    f"contains_entity_label must be non-empty when "
                    f"entity_action={self.entity_action!r}"
                )
        else:
            if self.contains_entity_label is not None:
                raise ValueError(
                    f"contains_entity_label must be null when entity_action={self.entity_action!r}"
                )
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
        if self.phase != "accepted" and (not self.reply or not self.reply.strip()):
            raise ValueError("reply must be a non-empty string")
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
    narrative_entities: list[NarrativeEntity],
) -> None:
    """Enforce the statistical-distribution rules across all 5 auto-pipeline
    illustrations of one run.

    Cast-role rules (auto pipeline only — manual co-creation ignores these):

    1. Every cast role in ``brief.characters`` appears at least once across
       ``illustrations[*].character_role``.
    2. ``brief.main_character_role`` appears at least twice.
    3. No side cast role appears more often than the main role.
    4. At most one illustration has ``character_role=None`` (the no-human
       cap of 1/5).

    Narrative-entity rules (the unified register; cf.
    ``NarrativeEntity``):

    5. For each entity, ``appearances`` = number of illustrations whose
       ``contains_entity_label`` matches the entity's label. Quotas:
         * primary NH-character: ``appearances <= 1``; if 1, that
           illustration's scene_index equals the entity's
           ``reserved_for_scene_index`` AND character_role is either
           ``None`` (alone shot) or any cast role (with-cast shot).
         * secondary NH-character: ``appearances <= 1``; if 1, that
           illustration's scene_index equals the entity's
           ``reserved_for_scene_index`` AND character_role is a cast
           role (never ``None`` — secondary may not appear alone).
         * supporting entity: ``appearances <= 1``; if 1, the scene
           obeys the entity-side scene lock (rule 6).
    6. Entity-side scene lock: an entity with a non-null
       ``reserved_for_scene_index`` may only appear at that one slot.
       (Per-slot single-active is enforced structurally by the schema
       since each illustration has at most one ``contains_entity_label``;
       *ghost* reservations from prior drops do not block new active
       displays in the same slot.)

    Raises ``ValueError`` on the first violation.
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

    cast_role_set = set(cast_roles)

    # Build entity-by-normalized-label and per-entity appearance lists.
    entity_by_label: dict[str, NarrativeEntity] = {
        _normalize_entity_label(e.label): e for e in narrative_entities
    }
    appearances_by_label: dict[str, list[IllustrationConcept]] = {
        norm: [] for norm in entity_by_label
    }
    for ill in illustrations:
        if ill.contains_entity_label is None:
            continue
        norm = _normalize_entity_label(ill.contains_entity_label)
        if norm not in entity_by_label:
            raise ValueError(
                f"illustration scene_index={ill.scene_index} references "
                f"contains_entity_label={ill.contains_entity_label!r} which "
                "is not in the narrative_entities register"
            )
        appearances_by_label[norm].append(ill)

    # Rules 5 & 6: per-entity quotas + scene lock.
    for norm, entity in entity_by_label.items():
        appearances = appearances_by_label[norm]
        # All importance levels share a hard cap of 1 appearance.
        if len(appearances) > 1:
            raise ValueError(
                f"narrative_entity {entity.label!r} (importance="
                f"{entity.importance!r}) appears in {len(appearances)} "
                "illustrations; the cap is 1 — entities are scene-locked"
            )

        if not appearances:
            # Zero appearances is allowed for any importance (graceful drop
            # by Agent 4 may reduce primary/secondary to zero too).
            continue

        ill = appearances[0]

        # Rule 6 (entity-side scene lock): if reserved_for_scene_index is
        # set, the appearance MUST be at that slot.
        if (
            entity.reserved_for_scene_index is not None
            and entity.reserved_for_scene_index != ill.scene_index
        ):
            raise ValueError(
                f"narrative_entity {entity.label!r} is reserved for "
                f"scene_index={entity.reserved_for_scene_index} but appears "
                f"at scene_index={ill.scene_index}; entities are scene-locked"
            )

        # Rule 5 (importance-specific character_role constraints).
        if entity.kind == "non_human_character" and entity.importance == "secondary":
            if ill.character_role not in cast_role_set:
                raise ValueError(
                    f"secondary non_human_character {entity.label!r} appears "
                    f"in scene_index={ill.scene_index} with character_role="
                    f"{ill.character_role!r}; secondary NH characters must "
                    "appear with a human cast member (never alone)"
                )
        if entity.kind == "non_human_character" and entity.importance == "primary":
            # Primary may be alone OR with any cast role — both fine.
            if ill.character_role is not None and ill.character_role not in cast_role_set:
                raise ValueError(
                    f"primary non_human_character {entity.label!r} appears "
                    f"in scene_index={ill.scene_index} with character_role="
                    f"{ill.character_role!r} which is not a cast role"
                )
