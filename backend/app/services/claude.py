"""Anthropic API client wrapper for the 7 distinct Claude calls.

Agent system prompts are loaded from Markdown files under ``app/agents``.
"""

import base64
import json
import logging
import os
import re
from collections.abc import Callable

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from app.constants import (
    ANTHROPIC_MODEL,
    CHARACTER_ROLE_MAP,
    CLAUDE_JSON_RETRY,
    MAX_NEGATIVE_TAGS,
    NEGATIVE_PROMPT_BASELINE,
)
from app.schemas.claude import (
    BuildStoryResponse,
    ChatResponse,
    Environment,
    EvaluateImageResponse,
    GeneratePromptsResponse,
    ManualConceptResponse,
    ManualRevisePromptsResponse,
    RethinkConceptResponse,
    RethinkEnvironmentResponse,
    RevisePromptsResponse,
    SalvageCandidate,
    SalvageReviewResponse,
    StyleGuide,
    TranslateResponse,
)

logger = logging.getLogger(__name__)

STRICT_JSON_RETRY_SUFFIX = (
    "\n\nCRITICAL: Your previous response could not be parsed as JSON. "
    "Respond with ONLY valid JSON, no other text whatsoever."
)


def _build_retry_message(previous_raw: str, error: Exception) -> str:
    """Build a retry user-turn that gives the model the specific failure.

    Distinguishes JSON-parse failures (generic suffix) from semantic
    ValidationErrors (echo the validator's message back so the model can
    fix the specific field). Includes a short echo of the previous raw
    response so the model can self-correct rather than regenerate blindly.
    """
    truncated = previous_raw if len(previous_raw) <= 4000 else previous_raw[:4000] + " …[truncated]"
    if isinstance(error, json.JSONDecodeError):
        return f"{STRICT_JSON_RETRY_SUFFIX}\n\nYour previous response was:\n```\n{truncated}\n```"
    # Pydantic ValidationError (or any other semantic failure): tell the
    # model what specifically failed so it can fix that field. The JSON was
    # valid — the problem is content, not formatting.
    return (
        "\n\nYour previous response was valid JSON but failed validation:\n"
        f"{error}\n\n"
        "Re-emit the full JSON object, fixing ONLY the field(s) that the "
        "error above identifies. Keep every other field byte-for-byte "
        "identical to your previous response unless fixing the error "
        "requires changing it. Do not add any prose around the JSON.\n\n"
        f"Your previous response was:\n```\n{truncated}\n```"
    )


def _strip_json_fences(text: str) -> str:
    """Best-effort recovery for agents that wrap JSON in Markdown fences.

    Strips a single leading ```json / ``` fence and trailing ``` fence
    (with surrounding whitespace) so ``json.loads`` can consume the body.
    The agent prompts all forbid this, but the model occasionally lapses
    — falling back here avoids a 502 over a cosmetic wrapping.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop opening fence + optional language tag on first line.
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        else:
            stripped = stripped[3:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    return stripped


_TAG_WEIGHT_RE = re.compile(r"\(([^():]+?)(?::\s*-?\d+(?:\.\d+)?)?\)")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]+")


def _tag_list(prompt: str) -> list[str]:
    """Split a Danbooru-style prompt into comma-separated tags.

    Strips per-tag attention-weight parentheses (``(tag:1.3)``) so the
    bare tag string is what we compare. Empty fragments are dropped.
    """
    tags: list[str] = []
    for raw in prompt.split(","):
        s = raw.strip()
        if not s:
            continue
        # Strip leading/trailing parens-with-weight wrappers.
        m = _TAG_WEIGHT_RE.fullmatch(s)
        if m:
            s = m.group(1).strip()
        tags.append(s)
    return tags


def _normalize_tag(tag: str) -> str:
    """Normalise a tag for comparison: lowercase, strip weight parens,
    drop punctuation/escapes, collapse whitespace, drop trailing
    ``_(qualifier)`` Danbooru disambiguators.
    """
    s = tag.strip().lower()
    # Unescape Danbooru parens like ``bow \(weapon\)`` first.
    s = s.replace("\\(", "(").replace("\\)", ")")
    # Collapse underscores to spaces (Danbooru → SD convention parity).
    s = s.replace("_", " ")
    s = _NON_WORD_RE.sub(" ", s)
    s = " ".join(s.split())
    return s


def _validate_prompts(
    *,
    response: GeneratePromptsResponse | RevisePromptsResponse,
    contains_entity: dict | None,
    expected_workflow: str | None = None,
) -> str | None:
    """Hard validators applied to Agent 1 / Agent 3 prompt responses.

    Returns ``None`` when the response is acceptable, or an English error
    string describing what is wrong (fed back to the model on retry).

    Checks:

    1. ``workflow`` matches ``expected_workflow`` when provided
       (Agent 3 must not switch LoRA mode).
    2. Negative prompt has at most ``MAX_NEGATIVE_TAGS`` comma-separated
       tags (CLIP token cap protection).
    3. No duplicate tags in the negative prompt.
    4. When ``contains_entity`` is non-null, the entity label noun MUST
       appear as a tag (or as a substring of a tag) in the positive
       prompt and MUST NOT appear in the negative prompt.
    """
    if expected_workflow is not None and response.workflow != expected_workflow:
        return (
            f"workflow must equal {expected_workflow!r} (the original "
            f"workflow for this scene). Agent 3 never switches LoRA mode. "
            f"You emitted {response.workflow!r}."
        )

    neg_tags = _tag_list(response.negative)
    if len(neg_tags) > MAX_NEGATIVE_TAGS:
        return (
            f"negative prompt has {len(neg_tags)} comma-separated tags; "
            f"the cap is {MAX_NEGATIVE_TAGS}. CLIP's token window is ~75 "
            "and additions beyond this point cancel each other out and "
            "can backfire. Tighten the negative prompt by dropping "
            "duplicate or low-value anti-X tags."
        )

    seen: set[str] = set()
    duplicates: list[str] = []
    for raw in neg_tags:
        norm = _normalize_tag(raw)
        if not norm:
            continue
        if norm in seen and norm not in duplicates:
            duplicates.append(norm)
        seen.add(norm)
    if duplicates:
        sample = ", ".join(duplicates[:5])
        return (
            f"negative prompt contains duplicate tags: {sample}. Each "
            "concept should be suppressed exactly once — dedupe and "
            "re-emit."
        )

    if contains_entity is not None:
        label = (contains_entity.get("label") or "").strip()
        if label:
            entity_norm = _normalize_tag(label)
            # Use the longest meaningful word from the entity label as the
            # anchor token (skips short connective words like "a", "the").
            anchor_tokens = [t for t in entity_norm.split() if len(t) >= 3]
            if not anchor_tokens:
                anchor_tokens = entity_norm.split()
            if anchor_tokens:
                positive_norm = _normalize_tag(response.positive)
                pos_tag_norms = [_normalize_tag(t) for t in _tag_list(response.positive)]
                # The entity is "present" when at least one anchor token
                # appears either as a standalone tag or as a substring of
                # any positive tag (handles "black cat" vs "cat", or
                # "stag" inside "white stag").
                anchor_present = any(
                    any(tok in pos_tag for pos_tag in pos_tag_norms) or tok in positive_norm
                    for tok in anchor_tokens
                )
                if not anchor_present:
                    return (
                        f"contains_entity is set ({label!r}) but no tag in "
                        "the positive prompt references the entity. The "
                        "entity is the central subject — it MUST appear as "
                        "a positive tag (species noun + description). "
                        f"Expected at least one of these tokens: "
                        f"{anchor_tokens}."
                    )
                neg_tag_norms = [_normalize_tag(t) for t in neg_tags]
                if any(
                    any(tok == nt or tok in nt for nt in neg_tag_norms) for tok in anchor_tokens
                ):
                    return (
                        f"contains_entity is set ({label!r}) but the "
                        "negative prompt references the entity. You must "
                        "never suppress the central subject. Move any "
                        "entity-related tags out of the negative."
                    )

    return None


AGENT_FILES = {
    "chat": "chat.md",
    "build_story": "build_story.md",
    "generate_prompts": "generate_prompts.md",
    "evaluate_image": "evaluate_image.md",
    "revise_prompts": "revise_prompts.md",
    "rethink_concept": "rethink_concept.md",
    "rethink_environment": "rethink_environment.md",
    "translate": "translate.md",
    "manual_concept": "manual_concept.md",
    "manual_revise_prompts": "manual_revise_prompts.md",
    "salvage_review": "salvage.md",
}

# Curated stable domain-knowledge reference docs prepended (with
# ephemeral cache_control) to the system prompt of the listed agents.
# Filename is relative to ``agents_dir/reference``.
REFERENCE_FILES = {
    "illustrious_sdxl": "reference/illustrious_sdxl.md",
}

# Which agents receive which reference docs prepended to their system
# prompt. Prompt-engineering agents only — Agents 0a/0b/2/4/4b/5/6/8 do
# not benefit from renderer-tag domain knowledge.
AGENT_REFERENCE_USAGE: dict[str, tuple[str, ...]] = {
    "generate_prompts": ("illustrious_sdxl",),
    "revise_prompts": ("illustrious_sdxl",),
    "manual_revise_prompts": ("illustrious_sdxl",),
}


def load_agent_prompts(agents_dir: str) -> dict[str, str]:
    """Load every agent system prompt from the agents directory.

    Refuse to start if any file is missing or empty.
    """
    prompts: dict[str, str] = {}
    for key, filename in AGENT_FILES.items():
        path = os.path.join(agents_dir, filename)
        if not os.path.isfile(path):
            raise ClaudeError(f"Agent prompt file not found: {path}")
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            raise ClaudeError(f"Agent prompt file is empty: {path}")
        prompts[key] = text
    return prompts


def load_reference_docs(agents_dir: str) -> dict[str, str]:
    """Load curated reference docs (stable domain knowledge) prepended
    to prompt-engineering agents' system prompts. Refuse to start on
    any missing or empty doc.
    """
    docs: dict[str, str] = {}
    for key, filename in REFERENCE_FILES.items():
        path = os.path.join(agents_dir, filename)
        if not os.path.isfile(path):
            raise ClaudeError(f"Reference doc not found: {path}")
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            raise ClaudeError(f"Reference doc is empty: {path}")
        docs[key] = text
    return docs


class ClaudeError(Exception):
    pass


class ClaudeClient:
    def __init__(
        self,
        api_key: str,
        agent_prompts: dict[str, str],
        reference_docs: dict[str, str] | None = None,
    ):
        self._client = AsyncAnthropic(api_key=api_key)
        missing = set(AGENT_FILES) - set(agent_prompts)
        if missing:
            raise ClaudeError(f"Missing agent prompts: {sorted(missing)}")
        self._prompts = agent_prompts
        self._references = reference_docs or {}
        # Validate that every reference doc the system claims to use is
        # actually loaded — refuse to start on a misconfiguration. (When
        # the caller passes ``None`` we treat references as disabled, so
        # tests can stay terse without losing the prod invariant.)
        if reference_docs is not None:
            for agent_key, ref_keys in AGENT_REFERENCE_USAGE.items():
                for rk in ref_keys:
                    if rk not in reference_docs:
                        raise ClaudeError(
                            f"Reference doc {rk!r} used by agent {agent_key!r} is not loaded."
                        )

    def _system_for(self, agent_key: str) -> str | list[dict]:
        """Build the system parameter for ``agent_key``.

        When the agent uses one or more reference docs, returns a list
        of system blocks with ``cache_control`` on the prepended
        reference content (so the docs are cached across calls) and the
        agent-specific prompt as the final, non-cached block. When the
        agent uses no reference docs (or references are disabled),
        returns the plain agent prompt string — same behaviour as
        before.
        """
        agent_prompt = self._prompts[agent_key]
        ref_keys = AGENT_REFERENCE_USAGE.get(agent_key, ())
        ref_keys = tuple(rk for rk in ref_keys if rk in self._references)
        if not ref_keys:
            return agent_prompt
        blocks: list[dict] = []
        for rk in ref_keys:
            blocks.append(
                {
                    "type": "text",
                    "text": self._references[rk],
                    "cache_control": {"type": "ephemeral"},
                }
            )
        blocks.append({"type": "text", "text": agent_prompt})
        return blocks

    async def _call_with_retry(
        self,
        messages: list[dict],
        response_model: type[BaseModel],
        system: str | list[dict],
        max_tokens: int = 4096,
        post_validator: Callable[[BaseModel], str | None] | None = None,
    ) -> BaseModel:
        """Call Claude with structured-output retry.

        ``post_validator`` is an optional hand-rolled validator that runs
        after the response parses cleanly into ``response_model``. It
        returns ``None`` to accept the response, or an English error
        string describing what is wrong. On error, the response is fed
        back to the model with the error message so it can self-correct
        — same retry budget as JSON / pydantic failures.
        """
        current_messages = list(messages)
        last_error: Exception | None = None
        last_raw: str = ""

        for attempt in range(CLAUDE_JSON_RETRY + 1):
            if attempt > 0 and last_error:
                current_messages = list(messages) + [
                    {
                        "role": "assistant",
                        "content": last_raw,
                    },
                    {
                        "role": "user",
                        "content": _build_retry_message(last_raw, last_error),
                    },
                ]

            response = await self._client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=current_messages,
            )
            raw_text = response.content[0].text

            try:
                data = json.loads(_strip_json_fences(raw_text))
                parsed = response_model(**data)
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = e
                last_raw = raw_text
                logger.warning(
                    "Claude response parse failure (attempt %d): %s; raw=%r",
                    attempt + 1,
                    e,
                    raw_text[:500],
                )
                continue

            if post_validator is not None:
                validator_msg = post_validator(parsed)
                if validator_msg is not None:
                    last_error = ValueError(validator_msg)
                    last_raw = raw_text
                    logger.warning(
                        "Claude response post-validation failed (attempt %d): %s",
                        attempt + 1,
                        validator_msg,
                    )
                    continue

            return parsed

        raise ClaudeError(
            f"Failed to parse Claude response after {CLAUDE_JSON_RETRY + 1} attempts: {last_error}"
        )

    # ── Agent 0a: chat ───────────────────────────────────────────────────────

    async def chat(self, transcript: list[dict]) -> ChatResponse:
        """Run one chat turn. ``transcript`` is the full conversation so far,
        as a list of ``{"role": "user"|"assistant", "content": str}`` messages
        ending with the user's latest message.
        """
        result = await self._call_with_retry(
            messages=transcript,
            response_model=ChatResponse,
            system=self._prompts["chat"],
        )
        return result  # type: ignore[return-value]

    # ── Agent 0b: build_story ────────────────────────────────────────────────

    async def build_story_i18n(
        self,
        input_dict: dict,
        validator_feedback: str | None = None,
    ) -> BuildStoryResponse:
        """
        Build story with i18n support.

        Args:
            input_dict: Dict containing:
                - source_language: str (e.g., 'sk', 'cs', 'en')
                - topic_short: str (brief topic for skeleton UI)
                - characters: list of Character dicts
                - main_character_role: str (one of 'male'|'female'|'mother')
                - non_human_entities: list of NonHumanEntityHint dicts
                  (free-form ``role_in_story`` text from the chat that
                  Agent 0b promotes into NarrativeEntity entries)
                - topic: str (full topic description)
                - notes: str (optional notes)
            validator_feedback: Optional plain-English description of why the
                previous Agent 0b attempt was rejected by server-side
                validators (distribution / quota / scene-lock rules). When
                non-empty, it is appended to the user message so the agent
                can correct course on the retry.
        """
        characters_json = json.dumps(
            [c.model_dump() for c in input_dict["characters"]], ensure_ascii=False, indent=2
        )
        non_human_entities_json = json.dumps(
            [e.model_dump() for e in input_dict["non_human_entities"]],
            ensure_ascii=False,
            indent=2,
        )
        feedback_block = (
            (
                "\n\nYour previous response was REJECTED by the server-side "
                "validator. Please fix the issue and produce a fresh response "
                "that conforms to all rules in your system prompt. Validator "
                f"feedback:\n{validator_feedback}\n"
            )
            if validator_feedback
            else ""
        )
        user_text = (
            f"source_language: {input_dict['source_language']}\n"
            f"topic_short: {input_dict['topic_short']}\n\n"
            f"characters:\n{characters_json}\n\n"
            f"main_character_role: {input_dict['main_character_role']}\n\n"
            f"non_human_entities:\n{non_human_entities_json}\n\n"
            f"topic: {input_dict['topic']}\n\n"
            f"notes: {input_dict.get('notes') or '(none)'}\n"
            f"{feedback_block}\n"
            "Respond with the JSON object specified in your instructions."
        )
        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=BuildStoryResponse,
            system=self._prompts["build_story"],
            max_tokens=8192,
        )
        return result  # type: ignore[return-value]

    # ── Agent 1: generate_prompts ────────────────────────────────────────────

    async def generate_prompts(
        self,
        current_concept: str,
        style_guide: StyleGuide,
        character_role: str | None,
        character_config: dict,
        contains_entity: dict | None = None,
        prompting_notes: str | None = None,
    ) -> GeneratePromptsResponse:
        """Generate prompts for illustration.

        When character_role is None (no-human scene), workflow will be 'no-lora'.

        ``contains_entity`` is the full NarrativeEntity dict (label, kind,
        importance, reserved_for_scene_index) for the entity visually
        present in this scene, or ``None`` for a clean scene. The label
        is the noun phrase the renderer must depict; importance + kind
        guide tag weighting.

        `prompting_notes` is the optional English-only cumulative memo curated by
        Agent 6 in the collaboration mode (§ 6A.2 rule #12, § 7.1 Call 1). NULL in
        the auto pipeline. When present, the prompt treats it as authoritative
        prompt-level guidance about this illustration's known renderer blind
        spots.
        """
        contains_entity_line = (
            f"contains_entity: {json.dumps(contains_entity, ensure_ascii=False)}"
            if contains_entity is not None
            else "contains_entity: null"
        )
        notes_line = (
            f"\nprompting_notes (English-only renderer hints, authoritative):\n{prompting_notes}\n"
            if prompting_notes
            else ""
        )

        if character_role:
            char_entry = character_config[character_role]
            char_display = CHARACTER_ROLE_MAP[character_role]
            user_text = (
                f"character_display: {char_display}\n"
                f"character_role: {character_role}\n"
                f"trigger_tags: {char_entry['trigger_tags']}\n"
                f"outfit_baseline: {char_entry['outfit_baseline']}\n"
                f"style_positive: {style_guide.overall_style_positive}\n"
                f"style_negative: {style_guide.overall_style_negative}\n"
                f"character_baseline_description: {style_guide.character_baseline_description}\n\n"
                f"concept: {current_concept}\n"
                f"{contains_entity_line}\n"
                f"{notes_line}\n"
                f"negative_baseline (MUST appear in negative):\n{NEGATIVE_PROMPT_BASELINE}\n\n"
                'Respond with JSON: {"workflow": "single-lora", '
                '"positive": "...", "negative": "..."}'
            )
        else:
            # No-human scene (no cast character)
            user_text = (
                f"character_role: null\n"
                f"style_positive: {style_guide.overall_style_positive}\n"
                f"style_negative: {style_guide.overall_style_negative}\n\n"
                f"concept: {current_concept}\n"
                f"{contains_entity_line}\n"
                f"{notes_line}\n"
                f"negative_baseline (MUST appear in negative):\n{NEGATIVE_PROMPT_BASELINE}\n\n"
                'Respond with JSON: {"workflow": "no-lora", "positive": "...", "negative": "..."}'
            )

        expected_workflow = "single-lora" if character_role else "no-lora"

        def _validator(parsed: BaseModel) -> str | None:
            return _validate_prompts(
                response=parsed,  # type: ignore[arg-type]
                contains_entity=contains_entity,
                expected_workflow=expected_workflow,
            )

        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=GeneratePromptsResponse,
            system=self._system_for("generate_prompts"),
            post_validator=_validator,
        )
        return result  # type: ignore[return-value]

    # ── Agent 2: evaluate_image ──────────────────────────────────────────────

    async def evaluate_image(
        self,
        image_bytes: bytes,
        current_concept: str,
        style_guide: StyleGuide,
        character_role: str | None,
        character_config: dict,
        contains_entity: dict | None = None,
        recent_failure_summaries: list[str] | None = None,
    ) -> EvaluateImageResponse:
        """Evaluate an image against the 8-point checklist.

        ``recent_failure_summaries`` is an optional newest-first list of
        short English summaries of the previous rejected attempts for the
        SAME concept in the current branch. When two or more recent
        rejections share the same failure mode, Agent 2 is instructed (in
        its system prompt) to escalate from ``problem="prompt"`` to
        ``problem="concept"`` instead of asking for a third tag-revision
        round on a clearly unreachable target.
        """
        image_b64 = base64.standard_b64encode(image_bytes).decode()
        contains_entity_line = (
            f"contains_entity: {json.dumps(contains_entity, ensure_ascii=False)}"
            if contains_entity is not None
            else "contains_entity: null"
        )
        if character_role:
            char_display = CHARACTER_ROLE_MAP[character_role]
            char_entry = character_config[character_role]
            expected_block = (
                f"Expected character: {char_display} (role: {character_role})\n"
                f"Expected trigger tags: {char_entry['trigger_tags']}\n"
            )
        else:
            # Entity-alone or no-character scene — no human expected.
            expected_block = (
                "Expected character: none (character_role: null — "
                "no human should appear in this image)\n"
            )
        if recent_failure_summaries:
            joined = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(recent_failure_summaries))
            recent_block = (
                "\nrecent_failures (newest first, all within the current concept):\n"
                f"{joined}\n"
                "If the current image fails for the same reason as any of "
                "the above and would call for the same prompt-level fix, "
                'consider emitting problem="concept" instead of '
                'problem="prompt" — repeated identical prompt revisions '
                "have not been working.\n"
            )
        else:
            recent_block = ""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Evaluate this anime illustration against the checklist.\n\n"
                            f"{expected_block}"
                            f"Concept: {current_concept}\n"
                            f"{contains_entity_line}\n"
                            f"Global style: {style_guide.overall_style_positive}\n"
                            f"{recent_block}\n"
                            "Respond with JSON per your instructions."
                        ),
                    },
                ],
            }
        ]
        result = await self._call_with_retry(
            messages=messages,
            response_model=EvaluateImageResponse,
            system=self._prompts["evaluate_image"],
        )
        return result  # type: ignore[return-value]

    # ── Agent 3: revise_prompts ──────────────────────────────────────────────

    async def revise_prompts(
        self,
        current_prompts: GeneratePromptsResponse,
        verdict: EvaluateImageResponse,
        current_concept: str,
        style_guide: StyleGuide,
        character_role: str | None,
        character_config: dict,
        contains_entity: dict | None = None,
        prompting_notes: str | None = None,
    ) -> RevisePromptsResponse:
        """Revise prompts after a failed verdict.

        ``prompting_notes`` is the cumulative empirical memo for this
        illustration. In the auto pipeline it is curated by Agent 3 itself
        across retries via ``prompting_notes_update`` in the response. The
        prompt treats it as authoritative renderer-specific guidance about
        this scene's known blind spots. NULL on the first revision attempt
        of a fresh concept.
        """
        contains_entity_line = (
            f"contains_entity: {json.dumps(contains_entity, ensure_ascii=False)}"
            if contains_entity is not None
            else "contains_entity: null"
        )
        notes_line = (
            f"\nprompting_notes (English-only renderer hints, authoritative):\n{prompting_notes}\n"
            if prompting_notes
            else ""
        )
        if character_role:
            char_entry = character_config[character_role]
            char_display = CHARACTER_ROLE_MAP[character_role]
            character_block = (
                f"character_display: {char_display}\n"
                f"character_role: {character_role}\n"
                f"trigger_tags: {char_entry['trigger_tags']}\n"
                f"outfit_baseline: {char_entry['outfit_baseline']}\n"
                f"character_baseline_description: {style_guide.character_baseline_description}\n"
            )
        else:
            # Entity-alone or no-character scene — no human in the prompt.
            character_block = (
                "character_role: null (no human in this scene)\n"
                f"character_baseline_description: {style_guide.character_baseline_description}\n"
            )
        workflow_line = (
            f"current_workflow: {current_prompts.workflow}\n"
            "(keep the same workflow; Agent 3 never switches LoRA mode)\n"
        )
        user_text = (
            f"{character_block}"
            f"{workflow_line}"
            f"style_positive: {style_guide.overall_style_positive}\n"
            f"style_negative: {style_guide.overall_style_negative}\n\n"
            f"concept: {current_concept}\n"
            f"{contains_entity_line}\n"
            f"{notes_line}"
            f"current_positive: {current_prompts.positive}\n"
            f"current_negative: {current_prompts.negative}\n\n"
            f"verdict_problem: {verdict.problem}\n"
            f"verdict_reasoning: {verdict.reasoning}\n"
            f"verdict_suggestion: {verdict.suggestion}\n\n"
            f"negative_baseline (MUST appear in negative):\n{NEGATIVE_PROMPT_BASELINE}\n\n"
            'Respond with JSON: {"workflow": "single-lora"|"no-lora", '
            '"positive": "...", "negative": "...", '
            '"prompting_notes_update": "..." or null}'
        )
        expected_workflow = current_prompts.workflow

        def _validator(parsed: BaseModel) -> str | None:
            return _validate_prompts(
                response=parsed,  # type: ignore[arg-type]
                contains_entity=contains_entity,
                expected_workflow=expected_workflow,
            )

        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=RevisePromptsResponse,
            system=self._system_for("revise_prompts"),
            post_validator=_validator,
        )
        return result  # type: ignore[return-value]

    # ── Agent 4: rethink_concept ─────────────────────────────────────────────

    async def rethink_concept(
        self,
        source_language: str,
        current_scene_index: int,
        current_concept: str,
        verdict: EvaluateImageResponse,
        current_scene_excerpt: str,
        story_title: str,
        story_blocks: list[dict],
        current_paragraph_index: int,
        character_role: str | None,
        current_entity_label: str | None = None,
        narrative_entities: list[dict] | None = None,
    ) -> RethinkConceptResponse:
        """Rethink concept with Agent 4.

        Args:
            source_language: Language of the story (sk, cs, en)
            current_scene_index: Slot Agent 4 is rewriting (drives lock checks)
            current_concept: The failed concept
            verdict: Evaluation verdict from Agent 2
            current_scene_excerpt: Current scene excerpt
            story_title: Story title
            story_blocks: All story blocks
            current_paragraph_index: Index of paragraph for this illustration
            character_role: Character role (nullable for no-human scenes)
            current_entity_label: Label of the NarrativeEntity currently
                attached to this slot (or None for a clean scene).
            narrative_entities: Full unified register (every entry has
                label, kind, importance, reserved_for_scene_index).
                Agent 4 may only depict: (a) the entity reserved for
                ``current_scene_index``, (b) a floating supporting
                entity (``reserved_for_scene_index=None``) it claims for
                this slot, or (c) nothing.
        """
        entities = narrative_entities or []
        # Render the full story for the agent: paragraph texts inline,
        # illustration blocks as numbered markers so the agent can see where
        # in the arc each illustration sits.
        rendered_blocks: list[str] = []
        for idx, block in enumerate(story_blocks):
            if block["type"] == "paragraph":
                tag = " (this paragraph)" if idx == current_paragraph_index else ""
                rendered_blocks.append(f"[BLOCK {idx} PARAGRAPH{tag}]\n{block['text']}")
            else:
                rendered_blocks.append(f"[BLOCK {idx} ILLUSTRATION {block['scene_index']}]")
        full_story = "\n\n".join(rendered_blocks)
        current_paragraph_text = story_blocks[current_paragraph_index]["text"]

        current_entity_label_json = (
            json.dumps(current_entity_label, ensure_ascii=False)
            if current_entity_label is not None
            else "null"
        )
        narrative_entities_json = json.dumps(entities, ensure_ascii=False)

        # Build user text with optional character fields
        if character_role:
            char_display = CHARACTER_ROLE_MAP[character_role]
            user_text = (
                f"source_language: {source_language}\n"
                f"character_display: {char_display}\n"
                f"character_role: {character_role}\n\n"
                f"story_title: {story_title}\n\n"
                f"full_story:\n{full_story}\n\n"
                f"current_scene_index: {current_scene_index}\n"
                f"current_paragraph_index: {current_paragraph_index}\n"
                f"current_paragraph_text: {current_paragraph_text}\n"
                f"current_scene_excerpt: {current_scene_excerpt}\n"
                f"failed_concept: {current_concept}\n"
                f"current_entity_label: {current_entity_label_json}\n"
                f"narrative_entities: {narrative_entities_json}\n"
                f"verdict_reasoning: {verdict.reasoning}\n"
                f"verdict_suggestion: {verdict.suggestion}\n\n"
                "Respond with the JSON object specified in your instructions."
            )
        else:
            # No-human scene (no cast character)
            user_text = (
                f"source_language: {source_language}\n"
                f"character_role: null\n\n"
                f"story_title: {story_title}\n\n"
                f"full_story:\n{full_story}\n\n"
                f"current_scene_index: {current_scene_index}\n"
                f"current_paragraph_index: {current_paragraph_index}\n"
                f"current_paragraph_text: {current_paragraph_text}\n"
                f"current_scene_excerpt: {current_scene_excerpt}\n"
                f"failed_concept: {current_concept}\n"
                f"current_entity_label: {current_entity_label_json}\n"
                f"narrative_entities: {narrative_entities_json}\n"
                f"verdict_reasoning: {verdict.reasoning}\n"
                f"verdict_suggestion: {verdict.suggestion}\n\n"
                "Respond with the JSON object specified in your instructions."
            )

        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=RethinkConceptResponse,
            system=self._prompts["rethink_concept"],
            max_tokens=2048,
        )
        return result  # type: ignore[return-value]

    async def rethink_environment(
        self,
        *,
        source_language: str,
        current_scene_index: int,
        current_concept: str,
        verdict: EvaluateImageResponse,
        current_scene_excerpt: str,
        story_title: str,
        story_blocks: list[dict],
        current_paragraph_index: int,
        character_role: str | None,
        main_character_role: str,
        current_environment: Environment,
        used_environments: list[str],
        current_entity_label: str | None = None,
        narrative_entities: list[dict] | None = None,
    ) -> RethinkEnvironmentResponse:
        """Call Agent 4b to swap the locked environment for a slot.

        Only invoked when Agent 2 emits ``problem='environment'``.
        Entity rules mirror ``rethink_concept`` (see its docstring).
        """
        entities = narrative_entities or []

        rendered_blocks: list[str] = []
        for idx, block in enumerate(story_blocks):
            if block["type"] == "paragraph":
                tag = " (this paragraph)" if idx == current_paragraph_index else ""
                rendered_blocks.append(f"[BLOCK {idx} PARAGRAPH{tag}]\n{block['text']}")
            else:
                rendered_blocks.append(f"[BLOCK {idx} ILLUSTRATION {block['scene_index']}]")
        full_story = "\n\n".join(rendered_blocks)
        current_paragraph_text = story_blocks[current_paragraph_index]["text"]

        # Locate the prev / next paragraph blocks around this illustration.
        prev_paragraph_text = ""
        next_paragraph_text = ""
        for idx in range(current_paragraph_index - 1, -1, -1):
            if story_blocks[idx]["type"] == "paragraph":
                prev_paragraph_text = story_blocks[idx]["text"]
                break
        for idx in range(current_paragraph_index + 1, len(story_blocks)):
            if story_blocks[idx]["type"] == "paragraph":
                next_paragraph_text = story_blocks[idx]["text"]
                break

        current_entity_label_json = (
            json.dumps(current_entity_label, ensure_ascii=False)
            if current_entity_label is not None
            else "null"
        )
        narrative_entities_json = json.dumps(entities, ensure_ascii=False)
        used_envs_json = json.dumps(used_environments, ensure_ascii=False)
        current_env_json = json.dumps(current_environment.model_dump(), ensure_ascii=False)

        char_display_line = ""
        if character_role:
            char_display_line = f"character_display: {CHARACTER_ROLE_MAP[character_role]}\n"

        user_text = (
            f"source_language: {source_language}\n"
            f"{char_display_line}"
            f"character_role: {character_role if character_role else 'null'}\n"
            f"main_character_role: {main_character_role}\n\n"
            f"story_title: {story_title}\n\n"
            f"full_story:\n{full_story}\n\n"
            f"current_scene_index: {current_scene_index}\n"
            f"current_paragraph_index: {current_paragraph_index}\n"
            f"current_paragraph_text: {current_paragraph_text}\n"
            f"previous_paragraph_text: {prev_paragraph_text}\n"
            f"next_paragraph_text: {next_paragraph_text}\n"
            f"current_environment: {current_env_json}\n"
            f"used_environments: {used_envs_json}\n"
            f"current_scene_excerpt: {current_scene_excerpt}\n"
            f"failed_concept: {current_concept}\n"
            f"current_entity_label: {current_entity_label_json}\n"
            f"narrative_entities: {narrative_entities_json}\n"
            f"verdict_reasoning: {verdict.reasoning}\n"
            f"verdict_suggestion: {verdict.suggestion}\n\n"
            "Respond with the JSON object specified in your instructions."
        )

        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=RethinkEnvironmentResponse,
            system=self._prompts["rethink_environment"],
            max_tokens=2048,
        )
        return result  # type: ignore[return-value]

    async def translate(
        self,
        target_language: str,
        items: list[dict],
    ) -> TranslateResponse:
        """Call Agent 5 to translate a list of polymorphic items.

        Args:
            target_language: One of "sk", "cs", "en"
            items: List of dicts with keys: kind, paragraph_index?, scene_index?, source_text
        """
        user_text = (
            f"target_language: {target_language}\n\n"
            f"items: {json.dumps(items, ensure_ascii=False, indent=2)}\n\n"
            "Respond with the JSON object (with 'translations' array) "
            "specified in your instructions."
        )
        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=TranslateResponse,
            system=self._prompts["translate"],
            max_tokens=4096,
        )
        return result  # type: ignore[return-value]

    # ── Agent 6: manual_concept ──────────────────────────────────────────────

    async def manual_concept(
        self,
        *,
        source_language: str,
        sub_phase: str,
        story_title: str,
        story_blocks: list[dict],
        current_paragraph_index: int,
        current_scene_excerpt: str,
        original_concept: str,
        character_role: str | None,
        current_entity: dict | None,
        manual_attempts_consumed: int,
        manual_attempts_remaining: int,
        last_concept_candidate: str | None,
        last_agreed_concept: str | None,
        prompting_notes: str | None,
        transcript: list[dict],
    ) -> ManualConceptResponse:
        """Run one manual-chat turn with Agent 6 (§ 6A, § 7.1 Call 6).

        ``sub_phase`` is the active sub-phase persisted on the manual
        session row (``concept_design`` / ``feedback_gathering``); the
        prompt's phase machine uses it to know which output `phase`
        values are legal on the upcoming reply.

        ``last_concept_candidate`` is the candidate the model itself
        proposed on its previous ``awaiting_concept_confirmation`` turn,
        or ``None`` if no such turn exists. The model uses it to
        recognise approvals and to keep the verbatim handoff stable.

        ``last_agreed_concept`` is the verbatim concept the user
        confirmed before the most recent image; non-null only in the
        feedback-gathering sub-phase.

        ``transcript`` is the prior manual-chat dialogue (excluding
        ``image``-role rows) terminating with the user's latest message,
        formatted as ``{"role": "user"|"assistant", "content": str}``.
        ``image``-role rows are surfaced in this transcript by the
        caller as assistant turns with content ``"[image rendered:
        attempt K]"``.
        """
        rendered_blocks: list[str] = []
        for idx, block in enumerate(story_blocks):
            if block["type"] == "paragraph":
                tag = " (this paragraph)" if idx == current_paragraph_index else ""
                rendered_blocks.append(f"[BLOCK {idx} PARAGRAPH{tag}]\n{block['text']}")
            else:
                rendered_blocks.append(f"[BLOCK {idx} ILLUSTRATION {block['scene_index']}]")
        full_story = "\n\n".join(rendered_blocks)

        current_entity_json = (
            json.dumps(current_entity, ensure_ascii=False) if current_entity is not None else "null"
        )
        char_display = CHARACTER_ROLE_MAP[character_role] if character_role else "null"

        last_candidate_blob = (
            json.dumps(last_concept_candidate, ensure_ascii=False)
            if last_concept_candidate is not None
            else "null"
        )
        last_agreed_blob = (
            json.dumps(last_agreed_concept, ensure_ascii=False)
            if last_agreed_concept is not None
            else "null"
        )
        prompting_notes_blob = (
            json.dumps(prompting_notes, ensure_ascii=False)
            if prompting_notes is not None
            else "null"
        )

        context_blob = (
            f"source_language: {source_language}\n"
            f"sub_phase: {sub_phase}\n"
            f"story_title: {story_title}\n\n"
            f"full_story:\n{full_story}\n\n"
            f"current_paragraph_index: {current_paragraph_index}\n"
            f"current_scene_excerpt: {current_scene_excerpt}\n"
            f"original_concept: {original_concept}\n"
            f"character_role: {character_role or 'null'}\n"
            f"character_display: {char_display}\n"
            f"current_entity: {current_entity_json}\n"
            f"manual_attempts_consumed: {manual_attempts_consumed}\n"
            f"manual_attempts_remaining: {manual_attempts_remaining}\n"
            f"last_concept_candidate: {last_candidate_blob}\n"
            f"last_agreed_concept: {last_agreed_blob}\n"
            f"prompting_notes: {prompting_notes_blob}\n\n"
            "Use the dialogue that follows to continue or open the manual chat. "
            "Respond with the JSON object specified in your instructions."
        )

        messages: list[dict] = [{"role": "user", "content": context_blob}]
        # An assistant ack so the first transcript message can be "user".
        messages.append(
            {
                "role": "assistant",
                "content": "Context received. I will follow Agent 6 protocol.",
            }
        )
        messages.extend(transcript)

        result = await self._call_with_retry(
            messages=messages,
            response_model=ManualConceptResponse,
            system=self._prompts["manual_concept"],
        )
        return result  # type: ignore[return-value]

    # ── Agent 7: manual_revise_prompts ───────────────────────────────────────

    async def manual_revise_prompts(
        self,
        *,
        last_agreed_concept: str,
        user_feedback: str,
        last_positive_prompt: str,
        last_negative_prompt: str,
        style_guide: StyleGuide,
        character_role: str | None,
        character_config: dict,
        contains_entity: dict | None = None,
        prompting_notes: str | None = None,
    ) -> ManualRevisePromptsResponse:
        """Run Agent 7 to translate the user's post-image feedback into
        revised positive/negative prompts (§ 7.1 Call 7, § 6A.4 step 5).

        Workflow choice is NOT decided here — the caller carries forward
        ``illustrations.current_workflow`` (see § 6A.4 step 5.5).
        """
        contains_entity_line = (
            f"contains_entity: {json.dumps(contains_entity, ensure_ascii=False)}"
            if contains_entity is not None
            else "contains_entity: null"
        )

        if character_role:
            char_entry = character_config[character_role]
            char_display = CHARACTER_ROLE_MAP[character_role]
            character_block = (
                f"character_display: {char_display}\n"
                f"character_role: {character_role}\n"
                f"trigger_tags: {char_entry['trigger_tags']}\n"
                f"outfit_baseline: {char_entry['outfit_baseline']}\n"
                f"character_baseline_description: {style_guide.character_baseline_description}\n"
            )
        else:
            character_block = "character_role: null\n"

        notes_block = (
            f"prompting_notes (English-only, authoritative renderer hints curated by Agent 6):\n"
            f"{prompting_notes}\n\n"
            if prompting_notes
            else ""
        )

        user_text = (
            f"{character_block}"
            f"style_positive: {style_guide.overall_style_positive}\n"
            f"style_negative: {style_guide.overall_style_negative}\n\n"
            f"last_agreed_concept: {last_agreed_concept}\n"
            f"{contains_entity_line}\n\n"
            f"last_positive_prompt: {last_positive_prompt}\n"
            f"last_negative_prompt: {last_negative_prompt}\n\n"
            f"user_feedback (raw post-image user prose, may be noisy):\n{user_feedback}\n\n"
            f"{notes_block}"
            f"negative_baseline (MUST appear in negative):\n{NEGATIVE_PROMPT_BASELINE}\n\n"
            'Respond with JSON: {"positive": "...", "negative": "..."}'
        )
        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=ManualRevisePromptsResponse,
            system=self._system_for("manual_revise_prompts"),
        )
        return result  # type: ignore[return-value]

    # ── Agent 8: salvage_review ──────────────────────────────────────────────

    async def salvage_review(
        self,
        *,
        source_language: str,
        candidates: list[SalvageCandidate],
        current_paragraph_text: str,
        previous_paragraph_text: str,
        next_paragraph_text: str,
        current_environment: Environment,
        current_entity: dict | None,
    ) -> SalvageReviewResponse:
        """Run Agent 8 to review nuance-only-failed historical attempts
        after the auto pipeline exhausts its budget (§ 7.1 Call 8).

        The caller has already run the pre-filter and the input
        ``candidates`` are guaranteed to share the live slot's
        environment + entity + role. Agent 8 never sees the image bytes
        — it reasons over verdict metadata and narrative coherence only.
        """
        candidates_json = json.dumps(
            [c.model_dump() for c in candidates], ensure_ascii=False, indent=2
        )
        current_env_json = json.dumps(current_environment.model_dump(), ensure_ascii=False)
        current_entity_json = (
            json.dumps(current_entity, ensure_ascii=False) if current_entity is not None else "null"
        )

        user_text = (
            f"source_language: {source_language}\n\n"
            f"candidates (newest-first):\n{candidates_json}\n\n"
            f"current_paragraph_text: {current_paragraph_text}\n"
            f"previous_paragraph_text: {previous_paragraph_text}\n"
            f"next_paragraph_text: {next_paragraph_text}\n"
            f"current_environment: {current_env_json}\n"
            f"current_entity: {current_entity_json}\n\n"
            "Respond with the JSON object specified in your instructions."
        )
        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=SalvageReviewResponse,
            system=self._prompts["salvage_review"],
            max_tokens=2048,
        )
        return result  # type: ignore[return-value]
