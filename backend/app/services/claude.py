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
    EvaluateImageResponse,
    GeneratePromptsResponse,
    RethinkConceptResponse,
    RevisePromptsResponse,
    StyleGuide,
    TranslateResponse,
)

logger = logging.getLogger(__name__)

STRICT_JSON_RETRY_SUFFIX = (
    "\n\nCRITICAL: Your previous response could not be parsed as JSON. "
    "Respond with ONLY valid JSON, no other text whatsoever."
)


AGENT_FILES = {
    "chat": "chat.md",
    "build_story": "build_story.md",
    "generate_prompts": "generate_prompts.md",
    "evaluate_image": "evaluate_image.md",
    "revise_prompts": "revise_prompts.md",
    "rethink_concept": "rethink_concept.md",
    "translate": "translate.md",
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
                data = json.loads(raw_text)
                return response_model(**data)
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = e
                logger.warning("Claude response parse failure (attempt %d): %s", attempt + 1, e)

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

    async def build_story_i18n(self, input_dict: dict) -> BuildStoryResponse:
        """
        Build story with i18n support.

        Args:
            input_dict: Dict containing:
                - source_language: str (e.g., 'sk', 'cs', 'en')
                - topic_short: str (brief topic for skeleton UI)
                - characters: list of Character dicts
                - companions: list of Companion dicts
                - topic: str (full topic description)
                - notes: str (optional notes)
        """
        characters_json = json.dumps(
            [c.model_dump() for c in input_dict["characters"]], ensure_ascii=False, indent=2
        )
        companions_json = json.dumps(
            [c.model_dump() for c in input_dict["companions"]], ensure_ascii=False, indent=2
        )
        user_text = (
            f"source_language: {input_dict['source_language']}\n"
            f"topic_short: {input_dict['topic_short']}\n\n"
            f"characters:\n{characters_json}\n\n"
            f"companions:\n{companions_json}\n\n"
            f"topic: {input_dict['topic']}\n\n"
            f"notes: {input_dict.get('notes') or '(none)'}\n\n"
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
    ) -> GeneratePromptsResponse:
        """Generate prompts for illustration.

        When character_role is None (companion-alone scenes), workflow will be 'no-lora'.
        """
        companion_line = (
            f"companion: {json.dumps(companion.model_dump(), ensure_ascii=False)}"
            if companion is not None
            else "companion: null"
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
                f"{companion_line}\n\n"
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
                f"{companion_line}\n\n"
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
