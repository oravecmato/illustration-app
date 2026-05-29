"""Anthropic API client wrapper for the 7 distinct Claude calls.

Agent system prompts are loaded from Markdown files under ``app/agents``.
"""

import base64
import json
import logging
import os

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from app.constants import (
    ANTHROPIC_MODEL,
    CHARACTER_ROLE_MAP,
    CLAUDE_JSON_RETRY,
    NEGATIVE_PROMPT_BASELINE,
)
from app.schemas.claude import (
    BuildStoryResponse,
    ChatResponse,
    Companion,
    Environment,
    EvaluateImageResponse,
    GeneratePromptsResponse,
    ManualConceptResponse,
    ManualRevisePromptsResponse,
    RethinkConceptResponse,
    RethinkEnvironmentResponse,
    RevisePromptsResponse,
    StyleGuide,
    TranslateResponse,
)

logger = logging.getLogger(__name__)

STRICT_JSON_RETRY_SUFFIX = (
    "\n\nCRITICAL: Your previous response could not be parsed as JSON. "
    "Respond with ONLY valid JSON, no other text whatsoever."
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


class ClaudeError(Exception):
    pass


class ClaudeClient:
    def __init__(self, api_key: str, agent_prompts: dict[str, str]):
        self._client = AsyncAnthropic(api_key=api_key)
        missing = set(AGENT_FILES) - set(agent_prompts)
        if missing:
            raise ClaudeError(f"Missing agent prompts: {sorted(missing)}")
        self._prompts = agent_prompts

    async def _call_with_retry(
        self,
        messages: list[dict],
        response_model: type[BaseModel],
        system: str,
        max_tokens: int = 4096,
    ) -> BaseModel:
        current_messages = list(messages)
        last_error: Exception | None = None

        for attempt in range(CLAUDE_JSON_RETRY + 1):
            if attempt > 0 and last_error:
                current_messages = list(messages) + [
                    {
                        "role": "user",
                        "content": STRICT_JSON_RETRY_SUFFIX,
                    }
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
                return response_model(**data)
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = e
                logger.warning(
                    "Claude response parse failure (attempt %d): %s; raw=%r",
                    attempt + 1,
                    e,
                    raw_text[:500],
                )

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
                - companions: list of Companion dicts
                - topic: str (full topic description)
                - notes: str (optional notes)
            validator_feedback: Optional plain-English description of why the
                previous Agent 0b attempt was rejected by server-side
                validators (pool fidelity or distribution rules). When
                non-empty, it is appended to the user message so the agent
                can correct course on the retry.
        """
        characters_json = json.dumps(
            [c.model_dump() for c in input_dict["characters"]], ensure_ascii=False, indent=2
        )
        companions_json = json.dumps(
            [c.model_dump() for c in input_dict["companions"]], ensure_ascii=False, indent=2
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
            f"companions:\n{companions_json}\n\n"
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
        companion: Companion | None = None,
        prompting_notes: str | None = None,
    ) -> GeneratePromptsResponse:
        """Generate prompts for illustration.

        When character_role is None (companion-alone scenes), workflow will be 'no-lora'.

        `prompting_notes` is the optional English-only cumulative memo curated by
        Agent 6 in the collaboration mode (§ 6A.2 rule #12, § 7.1 Call 1). NULL in
        the auto pipeline. When present, the prompt treats it as authoritative
        prompt-level guidance about this illustration's known renderer blind
        spots.
        """
        companion_line = (
            f"companion: {json.dumps(companion.model_dump(), ensure_ascii=False)}"
            if companion is not None
            else "companion: null"
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
                f"{companion_line}\n"
                f"{notes_line}\n"
                f"negative_baseline (MUST appear in negative):\n{NEGATIVE_PROMPT_BASELINE}\n\n"
                'Respond with JSON: {"workflow": "single-lora", '
                '"positive": "...", "negative": "..."}'
            )
        else:
            # Companion-alone scene (no character)
            user_text = (
                f"character_role: null\n"
                f"style_positive: {style_guide.overall_style_positive}\n"
                f"style_negative: {style_guide.overall_style_negative}\n\n"
                f"concept: {current_concept}\n"
                f"{companion_line}\n"
                f"{notes_line}\n"
                f"negative_baseline (MUST appear in negative):\n{NEGATIVE_PROMPT_BASELINE}\n\n"
                'Respond with JSON: {"workflow": "no-lora", "positive": "...", "negative": "..."}'
            )

        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=GeneratePromptsResponse,
            system=self._prompts["generate_prompts"],
        )
        return result  # type: ignore[return-value]

    # ── Agent 2: evaluate_image ──────────────────────────────────────────────

    async def evaluate_image(
        self,
        image_bytes: bytes,
        current_concept: str,
        style_guide: StyleGuide,
        character_role: str,
        character_config: dict,
        companion: Companion | None = None,
    ) -> EvaluateImageResponse:
        char_display = CHARACTER_ROLE_MAP[character_role]
        char_entry = character_config[character_role]
        image_b64 = base64.standard_b64encode(image_bytes).decode()
        companion_line = (
            f"companion: {json.dumps(companion.model_dump(), ensure_ascii=False)}"
            if companion is not None
            else "companion: null"
        )
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
                            f"Expected character: {char_display} (role: {character_role})\n"
                            f"Expected trigger tags: {char_entry['trigger_tags']}\n"
                            f"Concept: {current_concept}\n"
                            f"{companion_line}\n"
                            f"Global style: {style_guide.overall_style_positive}\n\n"
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
        character_role: str,
        character_config: dict,
        companion: Companion | None = None,
    ) -> RevisePromptsResponse:
        char_entry = character_config[character_role]
        char_display = CHARACTER_ROLE_MAP[character_role]
        companion_line = (
            f"companion: {json.dumps(companion.model_dump(), ensure_ascii=False)}"
            if companion is not None
            else "companion: null"
        )
        user_text = (
            f"character_display: {char_display}\n"
            f"character_role: {character_role}\n"
            f"trigger_tags: {char_entry['trigger_tags']}\n"
            f"outfit_baseline: {char_entry['outfit_baseline']}\n"
            f"style_positive: {style_guide.overall_style_positive}\n"
            f"style_negative: {style_guide.overall_style_negative}\n"
            f"character_baseline_description: {style_guide.character_baseline_description}\n\n"
            f"concept: {current_concept}\n"
            f"{companion_line}\n"
            f"current_positive: {current_prompts.positive}\n"
            f"current_negative: {current_prompts.negative}\n\n"
            f"verdict_problem: {verdict.problem}\n"
            f"verdict_reasoning: {verdict.reasoning}\n"
            f"verdict_suggestion: {verdict.suggestion}\n\n"
            f"negative_baseline (MUST appear in negative):\n{NEGATIVE_PROMPT_BASELINE}\n\n"
            'Respond with JSON: {"positive": "...", "negative": "..."}'
        )
        result = await self._call_with_retry(
            messages=[{"role": "user", "content": user_text}],
            response_model=RevisePromptsResponse,
            system=self._prompts["revise_prompts"],
        )
        return result  # type: ignore[return-value]

    # ── Agent 4: rethink_concept ─────────────────────────────────────────────

    async def rethink_concept(
        self,
        source_language: str,
        current_concept: str,
        verdict: EvaluateImageResponse,
        current_scene_excerpt: str,
        story_title: str,
        story_blocks: list[dict],
        current_paragraph_index: int,
        character_role: str | None,
        current_companion: Companion | None = None,
        companions_pool: list[str] | None = None,
    ) -> RethinkConceptResponse:
        """Rethink concept with Agent 4.

        Args:
            source_language: Language of the story (sk, cs, en)
            current_concept: The failed concept
            verdict: Evaluation verdict from Agent 2
            current_scene_excerpt: Current scene excerpt
            story_title: Story title
            story_blocks: All story blocks
            current_paragraph_index: Index of paragraph for this illustration
            character_role: Character role (nullable for companion-alone scenes)
            current_companion: Current companion (if any)
            companions_pool: Pool of allowed companions
        """
        pool = companions_pool or []
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

        current_companion_json = (
            json.dumps(current_companion.model_dump(), ensure_ascii=False)
            if current_companion is not None
            else "null"
        )
        companions_pool_json = json.dumps(pool, ensure_ascii=False)

        # Build user text with optional character fields
        if character_role:
            char_display = CHARACTER_ROLE_MAP[character_role]
            user_text = (
                f"source_language: {source_language}\n"
                f"character_display: {char_display}\n"
                f"character_role: {character_role}\n\n"
                f"story_title: {story_title}\n\n"
                f"full_story:\n{full_story}\n\n"
                f"current_paragraph_index: {current_paragraph_index}\n"
                f"current_paragraph_text: {current_paragraph_text}\n"
                f"current_scene_excerpt: {current_scene_excerpt}\n"
                f"failed_concept: {current_concept}\n"
                f"current_companion: {current_companion_json}\n"
                f"companions_pool: {companions_pool_json}\n"
                f"verdict_reasoning: {verdict.reasoning}\n"
                f"verdict_suggestion: {verdict.suggestion}\n\n"
                "Respond with the JSON object specified in your instructions."
            )
        else:
            # Companion-alone scene
            user_text = (
                f"source_language: {source_language}\n"
                f"character_role: null\n\n"
                f"story_title: {story_title}\n\n"
                f"full_story:\n{full_story}\n\n"
                f"current_paragraph_index: {current_paragraph_index}\n"
                f"current_paragraph_text: {current_paragraph_text}\n"
                f"current_scene_excerpt: {current_scene_excerpt}\n"
                f"failed_concept: {current_concept}\n"
                f"current_companion: {current_companion_json}\n"
                f"companions_pool: {companions_pool_json}\n"
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
        current_companion: Companion | None = None,
        companions_pool: list[str] | None = None,
        reserved_entities: list[dict] | None = None,
    ) -> RethinkEnvironmentResponse:
        """Call Agent 4b to swap the locked environment for a slot.

        Only invoked when Agent 2 emits ``problem='environment'``.
        """
        pool = companions_pool or []
        reserved = reserved_entities or []

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

        current_companion_json = (
            json.dumps(current_companion.model_dump(), ensure_ascii=False)
            if current_companion is not None
            else "null"
        )
        companions_pool_json = json.dumps(pool, ensure_ascii=False)
        reserved_json = json.dumps(reserved, ensure_ascii=False)
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
            f"current_paragraph_index: {current_paragraph_index}\n"
            f"current_paragraph_text: {current_paragraph_text}\n"
            f"previous_paragraph_text: {prev_paragraph_text}\n"
            f"next_paragraph_text: {next_paragraph_text}\n"
            f"current_environment: {current_env_json}\n"
            f"used_environments: {used_envs_json}\n"
            f"current_scene_excerpt: {current_scene_excerpt}\n"
            f"failed_concept: {current_concept}\n"
            f"current_companion: {current_companion_json}\n"
            f"companions_pool: {companions_pool_json}\n"
            f"reserved_entities: {reserved_json}\n"
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
        current_companion: Companion | None,
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

        current_companion_json = (
            json.dumps(current_companion.model_dump(), ensure_ascii=False)
            if current_companion is not None
            else "null"
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
            f"current_companion: {current_companion_json}\n"
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
        companion: Companion | None = None,
        prompting_notes: str | None = None,
    ) -> ManualRevisePromptsResponse:
        """Run Agent 7 to translate the user's post-image feedback into
        revised positive/negative prompts (§ 7.1 Call 7, § 6A.4 step 5).

        Workflow choice is NOT decided here — the caller carries forward
        ``illustrations.current_workflow`` (see § 6A.4 step 5.5).
        """
        companion_line = (
            f"companion: {json.dumps(companion.model_dump(), ensure_ascii=False)}"
            if companion is not None
            else "companion: null"
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
            f"{companion_line}\n\n"
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
            system=self._prompts["manual_revise_prompts"],
        )
        return result  # type: ignore[return-value]
