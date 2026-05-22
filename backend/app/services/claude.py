"""Anthropic API client wrapper for the 5 distinct Claude calls."""

import base64
import json
import logging

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from app.constants import (
    ANTHROPIC_MODEL,
    CHARACTER_ROLE_MAP,
    CLAUDE_JSON_RETRY,
    NEGATIVE_PROMPT_BASELINE,
)
from app.schemas.claude import (
    AnalyzeStoryResponse,
    EvaluateImageResponse,
    GeneratePromptsResponse,
    RethinkConceptResponse,
    RevisePromptsResponse,
    StyleGuide,
)

logger = logging.getLogger(__name__)

STRICT_JSON_RETRY_SUFFIX = (
    "\n\nCRITICAL: Your previous response could not be parsed as JSON. "
    "Respond with ONLY valid JSON, no other text whatsoever."
)

# ── Agent 0: analyze_story ────────────────────────────────────────────────────

_ANALYZE_STORY_SYSTEM = """\
You are a scene-selection assistant for an anime illustration pipeline that uses Illustrious XL \
(an SDXL fine-tune for anime) with My Hero Academia (MHA) character LoRAs.

Your job: read a story and identify up to 5 scenes that are suitable for single-character \
anime illustration. Output strict JSON — no markdown, no extra text.

═══ SELECTION CONSTRAINTS (all must be satisfied) ═══

1. EXACTLY ONE character per scene — acting alone.
   Exclude: group scenes, two or more characters interacting, crowds, scenes with no clear \
character focus.

2. The character must match one of exactly three permitted roles:
   • "male"   — a boy or young man       → will be rendered as Izuku Midoriya
   • "female" — a girl or young woman    → will be rendered as Kyoka Jiro
   • "mother" — a mother / maternal figure → will be rendered as Inko Midoriya
   Map each selected scene's character to the closest role above. The story's character \
names are narrative-only; never use them in output.

3. MANDATORY SPECIFICITY — the scene must have at least one of:
   • A named facial expression  (e.g. "tears streaming down her face", "wide-eyed shock")
   • A specific gesture/posture (e.g. "kneeling, head bowed", "clutching book to chest")
   • A concrete action          (e.g. "pouring tea from a kettle", "picking up a fallen coin")
   Vague descriptions such as "standing there" or "looking around" are NOT acceptable.

4. If no scene passes all three constraints, return illustrations: []
   DO NOT invent scenes or relax constraints to avoid an empty result.

═══ STYLE GUIDE RULES ═══

• overall_style_positive: Danbooru-style comma-separated anime tags applied globally to every \
illustration (e.g. "mha style, anime, manga illustration, soft shading, clean linework, \
vibrant colors")
• overall_style_negative: global style negatives (e.g. "realistic, photo, 3d render, \
western cartoon, painterly")
• character_lora: always set to empty string "" (the pipeline fills this from config)
• character_baseline_description: English prose describing the shared visual mood, lighting, \
and framing continuity across all illustrations of this run

═══ OUTPUT FORMAT ═══

{
  "style_guide": {
    "overall_style_positive": "...",
    "overall_style_negative": "...",
    "character_lora": "",
    "character_baseline_description": "..."
  },
  "illustrations": [
    {
      "scene_index": 0,
      "scene_excerpt": "exact or near-exact passage from the story",
      "concept": "concrete description including expression/gesture/action",
      "character_role": "male" | "female" | "mother"
    }
  ]
}
"""

# ── Agent 2: evaluate_image ───────────────────────────────────────────────────

_EVALUATE_IMAGE_SYSTEM = """\
You are a quality-control evaluator for an anime illustration pipeline \
(Illustrious XL + MHA LoRAs).
You judge rendered images against a 7-point checklist. \
Output strict JSON — no markdown, no extra text.

═══ EVALUATION CHECKLIST ═══

The image is OK only when ALL of the following hold:
1. Exactly one character is visible. Multiple visible characters → problem="prompt".
2. The character matches the expected role (see context) — recognisable as the corresponding \
MHA character.
3. The character's expression, gesture, or action is clearly identifiable and matches the concept. \
Vague or generic poses (just standing, looking) → problem="prompt" with suggestion to add specifics.
4. The illustration is style-consistent: anime/MHA look, no realism, no off-style rendering.
5. No anatomical deformities: extra/missing/fused fingers, distorted face, misaligned eyes.
6. Safe for general audiences: no suggestive, revealing, or sexualized content. \
Safety violations → problem="concept".
7. Scene composition serves the concept: environment supports the action, framing is appropriate.

═══ PROBLEM CLASSIFICATION ═══

• problem="concept" — failures that prompt revision cannot plausibly fix:
  safety violations, fundamental impossibility of the concept, repeated failures.
• problem="prompt"  — fixable issues: missing expression, wrong environment, mild anatomy issues,\
 wrong character details, generic pose.

═══ OUTPUT FORMAT ═══

On success:
{"ok": true, "problem": null, "reasoning": "...", "suggestion": ""}

On failure:
{"ok": false, "problem": "prompt" | "concept", "reasoning": "...", "suggestion": "actionable hint"}
"""


class ClaudeError(Exception):
    pass


class ClaudeClient:
    def __init__(self, api_key: str):
        self._client = AsyncAnthropic(api_key=api_key)

    async def _call_with_retry(
        self,
        messages: list[dict],
        response_model: type[BaseModel],
        system: str,
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
                max_tokens=4096,
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

    async def analyze_story(self, story_text: str) -> AnalyzeStoryResponse:
        messages = [
            {
                "role": "user",
                "content": (
                    "Analyze this story and identify suitable single-character scenes for anime "
                    "illustration following the constraints in your instructions.\n\n"
                    f"Story:\n{story_text}\n\n"
                    "Respond with JSON matching this schema exactly:\n"
                    '{"style_guide": {"overall_style_positive": "...", '
                    '"overall_style_negative": "...", "character_lora": "", '
                    '"character_baseline_description": "..."}, '
                    '"illustrations": [{"scene_index": 0, "scene_excerpt": "...", '
                    '"concept": "...", "character_role": "male"|"female"|"mother"}]}'
                ),
            }
        ]
        result = await self._call_with_retry(messages, AnalyzeStoryResponse, _ANALYZE_STORY_SYSTEM)
        return result  # type: ignore[return-value]

    async def generate_prompts(
        self,
        current_concept: str,
        style_guide: StyleGuide,
        character_role: str,
        character_config: dict,
    ) -> GeneratePromptsResponse:
        char_entry = character_config[character_role]
        char_display = CHARACTER_ROLE_MAP[character_role]
        system = _build_prompt_engineer_system(char_display, char_entry, style_guide)
        messages = [
            {
                "role": "user",
                "content": (
                    f"Generate Danbooru-tag prompts for this illustration concept.\n\n"
                    f"Concept: {current_concept}\n\n"
                    f"Visual continuity note: {style_guide.character_baseline_description}\n\n"
                    "Respond with JSON:\n"
                    '{"character_positive": "...", "character_negative": "...", '
                    '"environment": "..."}'
                ),
            }
        ]
        result = await self._call_with_retry(messages, GeneratePromptsResponse, system)
        return result  # type: ignore[return-value]

    async def evaluate_image(
        self,
        image_bytes: bytes,
        current_concept: str,
        style_guide: StyleGuide,
        character_role: str,
        character_config: dict,
    ) -> EvaluateImageResponse:
        char_display = CHARACTER_ROLE_MAP[character_role]
        char_entry = character_config[character_role]
        image_b64 = base64.standard_b64encode(image_bytes).decode()
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
                            f"Evaluate this anime illustration against the 7-point checklist.\n\n"
                            f"Expected character: {char_display} (role: {character_role})\n"
                            f"Expected trigger tags: {char_entry['trigger_tags']}\n"
                            f"Concept: {current_concept}\n"
                            f"Global style: {style_guide.overall_style_positive}\n\n"
                            "Respond with JSON per your instructions."
                        ),
                    },
                ],
            }
        ]
        result = await self._call_with_retry(
            messages, EvaluateImageResponse, _EVALUATE_IMAGE_SYSTEM
        )
        return result  # type: ignore[return-value]

    async def revise_prompts(
        self,
        current_prompts: GeneratePromptsResponse,
        verdict: EvaluateImageResponse,
        current_concept: str,
        style_guide: StyleGuide,
        character_role: str,
        character_config: dict,
    ) -> RevisePromptsResponse:
        char_entry = character_config[character_role]
        char_display = CHARACTER_ROLE_MAP[character_role]
        system = _build_prompt_engineer_system(char_display, char_entry, style_guide)
        messages = [
            {
                "role": "user",
                "content": (
                    f"Revise these Danbooru-tag prompts based on the evaluation feedback.\n\n"
                    f"Concept: {current_concept}\n"
                    f"Current prompts:\n"
                    f"  character_positive: {current_prompts.character_positive}\n"
                    f"  character_negative: {current_prompts.character_negative}\n"
                    f"  environment: {current_prompts.environment}\n\n"
                    f"Evaluation problem: {verdict.problem}\n"
                    f"Reasoning: {verdict.reasoning}\n"
                    f"Suggestion: {verdict.suggestion}\n\n"
                    "Respond with JSON:\n"
                    '{"character_positive": "...", "character_negative": "...", '
                    '"environment": "..."}'
                ),
            }
        ]
        result = await self._call_with_retry(messages, RevisePromptsResponse, system)
        return result  # type: ignore[return-value]

    async def rethink_concept(
        self,
        current_concept: str,
        verdict: EvaluateImageResponse,
        scene_excerpt: str,
        style_guide: StyleGuide,
        character_role: str,
    ) -> RethinkConceptResponse:
        char_display = CHARACTER_ROLE_MAP[character_role]
        system = _build_rethink_system(char_display, character_role)
        messages = [
            {
                "role": "user",
                "content": (
                    "The current illustration concept has repeatedly failed. Propose a completely "
                    "different concept for the SAME scene excerpt.\n\n"
                    f"Scene excerpt: {scene_excerpt}\n"
                    f"Failed concept: {current_concept}\n"
                    f"Why it failed: {verdict.reasoning}\n"
                    f"Suggestion: {verdict.suggestion}\n\n"
                    "The new concept must:\n"
                    "- Depict the SAME scene from the excerpt\n"
                    "- Feature exactly one character (the same role)\n"
                    "- Include a concrete expression, gesture, or action\n"
                    "- Be fundamentally different from the failed concept\n\n"
                    f'Respond with JSON: {{"concept": "..."}}'
                ),
            }
        ]
        result = await self._call_with_retry(messages, RethinkConceptResponse, system)
        return result  # type: ignore[return-value]


def _build_prompt_engineer_system(
    char_display: str,
    char_entry: dict,
    style_guide: StyleGuide,
) -> str:
    """Build the system prompt for Agents 1 and 3 (generate/revise prompts)."""
    return f"""\
You are a ComfyUI Danbooru-tag prompt engineer for Illustrious XL (SDXL anime fine-tune) \
with MHA character LoRAs.
Output strict JSON — no markdown, no extra text.

═══ CHARACTER ═══
Name: {char_display}
Trigger tags (MUST appear in character_positive): {char_entry["trigger_tags"]}
Outfit baseline (include when scene-appropriate): {char_entry["outfit_baseline"]}

═══ GLOBAL STYLE (handled by the workflow, for context only) ═══
Positive: {style_guide.overall_style_positive}
Negative: {style_guide.overall_style_negative}

═══ CRITICAL PROMPT RULES ═══

1. Danbooru-style COMMA-SEPARATED TAGS ONLY — never natural language sentences.
   ✓ Good: "1boy, midoriya izuku, green hair, freckles, crying, tears on cheeks, fist clenched"
   ✗ Bad:  "Izuku is crying while clenching his fist in the rain"

2. character_positive MUST include ALL of these:
   a) All trigger tags: {char_entry["trigger_tags"]}
   b) Solo-character enforcer: "1boy" / "1girl" / "1woman" (choose one, matching the character)
   c) Specific emotion/expression tags (e.g. "crying", "determined expression", "wide eyes")
   d) Specific action/pose tags (e.g. "outstretched arm", "kneeling", "head bowed")
   e) Outfit baseline: {char_entry["outfit_baseline"]}

3. character_negative MUST include this full baseline (append scene-specific negatives after):
   {NEGATIVE_PROMPT_BASELINE}

4. environment: location and atmosphere tags only — no character tags here.
   Example: "classroom, desks, window, afternoon light, soft shadows"

5. Vague tags alone are insufficient: "standing", "looking", "posing" must be paired with specifics.
"""


def _build_rethink_system(char_display: str, character_role: str) -> str:
    """Build the system prompt for Agent 4 (rethink concept)."""
    return f"""\
You are a creative concept writer for an anime illustration pipeline (Illustrious XL + MHA LoRAs).
Output strict JSON — no markdown, no extra text.

Your task: propose a DIFFERENT visual concept for the same scene, featuring {char_display} \
(role: {character_role}) in a single-character still illustration.

The new concept must:
• Depict the SAME story moment (same scene excerpt)
• Feature EXACTLY ONE character ({char_display})
• Include a CONCRETE and DEPICTABLE element — name at least one of:
  - A specific facial expression (crying, shocked, determined, etc.)
  - A specific gesture or posture (reaching out, kneeling, clutching something, etc.)
  - A specific action being performed (pouring, picking up, running, etc.)
• Be meaningfully DIFFERENT from the failed concept — change the visual approach, angle, or focus
• Stay safe for general audiences

Output format: {{"concept": "..."}}
"""
