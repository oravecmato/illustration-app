# Anime Illustrator — Project Specification (MVP)

This document is the single source of truth for the implementation. All terms,
schemas, and contracts defined here are normative. Anything not specified is
left to the implementer's reasonable judgment, but must not contradict this
document.

---

## 1. Purpose

A locally-hosted web application that takes a narrative text as input,
identifies suitable scenes to illustrate, and produces a set of visually
consistent **anime illustrations** using Claude (Anthropic API) for
reasoning and a RunPod Serverless ComfyUI endpoint for image rendering.

The MVP processes one input text per run, producing up to **5 illustrations
in parallel**, with per-illustration self-correction loops driven by
Claude's visual evaluation of each generated image.

The visual output style is anime/manga, rendered by an Illustrious-based
SDXL ComfyUI workflow with character and style LoRAs. See § 7.3 for the
full creative and prompting brief.

---

## 2. Tech Stack

| Layer       | Technology                                                    |
|-------------|---------------------------------------------------------------|
| Backend     | Python 3.11+, FastAPI, async SQLAlchemy 2.x, aiosqlite, httpx |
| Frontend    | Vue 3 + Vite + TypeScript, Pinia, scoped SCSS                 |
| Database    | SQLite (local file, created on first startup)                 |
| Realtime    | Server-Sent Events (SSE)                                      |
| Image gen   | RunPod Serverless ComfyUI endpoint (external)                 |
| LLM         | Anthropic Messages API, model `claude-sonnet-4-6`             |
| Tests (BE)  | pytest, pytest-asyncio, respx (HTTP mocking)                  |
| Tests (FE)  | Vitest, @vue/test-utils                                       |
| Lint (BE)   | Ruff (lint + format)                                          |
| Lint (FE)   | ESLint (`@typescript-eslint` + `eslint-plugin-vue`) + `vue-tsc` |

No specific package versions are pinned in this spec; use current stable
releases at the time of implementation.

All code, identifiers, and code comments are in **English**. UI text
displayed to the end user is in **Slovak**.

---

## 3. Suggested Project Structure

```
anime-illustrator/
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── app/
│   │   ├── main.py                 # FastAPI app, CORS, routers, startup
│   │   ├── config.py               # Settings (pydantic-settings, .env)
│   │   ├── constants.py            # Numeric limits, enum values
│   │   ├── db/
│   │   │   ├── models.py           # SQLAlchemy ORM models
│   │   │   ├── session.py          # async engine + session factory
│   │   │   └── repositories.py     # CRUD helpers
│   │   ├── schemas/                # Pydantic models for API + Claude IO
│   │   ├── services/
│   │   │   ├── claude.py           # Anthropic API client wrapper
│   │   │   ├── runpod.py           # RunPod /run + /status polling
│   │   │   ├── workflow.py         # Placeholder replacement, JSON load
│   │   │   └── images.py           # Save/load image files to disk
│   │   ├── orchestrator/
│   │   │   ├── pipeline.py         # Top-level run orchestration
│   │   │   ├── branch.py           # Per-illustration state machine
│   │   │   └── events.py           # SSE event bus (per-run pub/sub)
│   │   ├── api/
│   │   │   ├── runs.py             # POST/GET endpoints + SSE
│   │   │   └── static.py           # Image file serving (optional)
│   │   └── workflows/
│   │       └── default.json        # The single ComfyUI workflow (API format)
│   ├── output/                     # Generated images (gitignored)
│   ├── data/                       # SQLite file (gitignored)
│   └── tests/
│       ├── unit/
│       └── integration/
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html
    ├── src/
    │   ├── main.ts
    │   ├── App.vue
    │   ├── router/                 # 2 routes: Home, Run
    │   ├── stores/
    │   │   └── run.ts              # Pinia store
    │   ├── views/
    │   │   ├── HomeView.vue
    │   │   └── RunView.vue
    │   ├── components/
    │   │   ├── IllustrationCard.vue
    │   │   ├── ProgressCounter.vue
    │   │   └── CancelButton.vue
    │   ├── services/
    │   │   └── api.ts              # fetch wrappers + SSE EventSource
    │   ├── types/                  # Shared TS types (mirror backend schemas)
    │   └── assets/styles/
    └── tests/
```

---

## 4. Configuration

### Backend `.env`

```
ANTHROPIC_API_KEY=...
RUNPOD_API_KEY=...
RUNPOD_ENDPOINT_ID=...
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
OUTPUT_DIR=./output
WORKFLOW_PATH=./app/workflows/default.json
ALLOWED_ORIGIN=http://localhost:5173
```

All keys are required (the app must refuse to start on missing values, with
a clear error message). Provide `.env.example` with placeholder values.

### Frontend

A `.env` for the frontend with `VITE_API_BASE=http://localhost:8000` is
sufficient. No secrets ever live in the frontend.

---

## 5. Data Model

Two tables, created automatically on startup via SQLAlchemy
`Base.metadata.create_all`. No Alembic for MVP.

### `runs`

| Column              | Type       | Notes                                 |
|---------------------|------------|---------------------------------------|
| `id`                | TEXT (UUID4) | Primary key                         |
| `created_at`        | DATETIME   | UTC                                   |
| `updated_at`        | DATETIME   | UTC                                   |
| `status`            | TEXT (enum)| `RUNNING` / `COMPLETED` / `FAILED` / `CANCELLED` |
| `story_text`        | TEXT       | Full input                            |
| `style_guide_json`  | TEXT       | JSON; null until Step 0 finishes      |
| `illustration_count`| INTEGER    | Final count after Step 0 (≤ 5)        |
| `completed_count`   | INTEGER    | Successful illustrations              |
| `failed_count`      | INTEGER    | Definitively failed illustrations     |
| `error_code`        | TEXT NULL  | Machine-readable failure tag, e.g. `NO_SUITABLE_SCENES`, `STEP0_FAILED`, `INTERNAL_ERROR`. Set when `status=FAILED`. Drives the Slovak UX message on the frontend. |
| `error_message`     | TEXT NULL  | Human-readable technical detail (English). Set on `FAILED`. |

### `illustrations`

| Column                   | Type        | Notes                                                                     |
|--------------------------|-------------|---------------------------------------------------------------------------|
| `id`                     | TEXT (UUID4)| Primary key                                                               |
| `run_id`                 | TEXT (FK)   | → `runs.id`                                                               |
| `scene_index`            | INTEGER     | 0..(illustration_count-1)                                                 |
| `scene_excerpt`          | TEXT        | The passage of the story this scene depicts                               |
| `character_role`         | TEXT (enum) | `male` / `female` / `mother` — which of the three permitted roles this scene depicts (per § 7.3.2). |
| `initial_concept`        | TEXT        | The concept from Step 0; never mutated                                    |
| `current_concept`        | TEXT        | Current concept (changes on concept restart)                              |
| `state`                  | TEXT (enum) | See § 6 state values                                                      |
| `concept_attempt`        | INTEGER     | 1..3                                                                      |
| `prompt_attempt`         | INTEGER     | 1..3                                                                      |
| `current_prompts_json`   | TEXT NULL   | Last-used prompts (for debugging/visibility)                              |
| `last_verdict_json`      | TEXT NULL   | Last Claude verdict (for debugging/visibility)                            |
| `image_path`             | TEXT NULL   | Relative path under `OUTPUT_DIR`, e.g. `runs/<run_id>/scene_0.png`        |
| `error_message`          | TEXT NULL   | Set on terminal failure                                                   |
| `created_at`             | DATETIME    |                                                                           |
| `updated_at`             | DATETIME    |                                                                           |

---

## 6. Illustration State Machine

### States

| State                  | Slovak UI label              | Notes                                          |
|------------------------|------------------------------|------------------------------------------------|
| `PENDING`              | "Čaká"                       | Created, not yet started                       |
| `GENERATING_PROMPTS`   | "Pripravujem prompty"        | Claude is producing prompts                    |
| `RENDERING`            | "Kreslím (pokus k/N)"        | ComfyUI job in flight                          |
| `EVALUATING`           | "Vyhodnocujem výsledok"      | Claude inspects the image                      |
| `REVISING_PROMPTS`     | "Upravujem prompty"          | Claude revises prompts after a bad image       |
| `RETHINKING_CONCEPT`   | "Premýšľam koncept"          | Claude proposes a new concept for the scene    |
| `COMPLETED`            | "Hotovo"                     | Image accepted                                 |
| `FAILED`               | "Nepodarilo sa"              | All attempts exhausted, or unrecoverable error |
| `CANCELLED`            | "Zrušené"                    | Run cancelled while this branch was active     |

### Loop semantics (worst case: 3 × 3 = 9 ComfyUI jobs)

```
for concept_attempt in 1..MAX_CONCEPT_ATTEMPTS (3):       # initial + 2 restarts
    if concept_attempt > 1:
        state = RETHINKING_CONCEPT
        current_concept = claude.rethink_concept(...)
    state = GENERATING_PROMPTS
    prompts = claude.generate_prompts(current_concept, style_guide)
    for prompt_attempt in 1..MAX_PROMPT_ATTEMPTS_PER_CONCEPT (3):
        check_cancellation()
        state = RENDERING
        image = runpod.run_workflow(workflow_with_prompts)
        state = EVALUATING
        verdict = claude.evaluate_image(image, current_concept, style_guide)
        if verdict.ok:
            state = COMPLETED
            return success
        if verdict.problem == "concept":
            break  # exit inner loop -> next concept
        # verdict.problem == "prompt"
        state = REVISING_PROMPTS
        prompts = claude.revise_prompts(prompts, verdict, ...)
state = FAILED
return failure
```

Each state transition writes to DB and emits one SSE event.

---

## 7. External Service Contracts

### 7.1 Anthropic Messages API (5 distinct calls)

All calls use `claude-sonnet-4-6` and force JSON-only output via a strict
system prompt. The implementer must validate every response against the
schema below using Pydantic, and re-prompt up to **2 times** on parse
failure before treating it as an error.

For the `evaluate_image` call, the image is passed as a base64 image block
alongside the text content.

#### Call 0 — `analyze_story`

**Input (text):** the full input story.

**Output schema:**
```json
{
  "style_guide": {
    "overall_style_positive": "string (visual style applied to all illustrations)",
    "overall_style_negative": "string (style traits to avoid)",
    "character_lora": "string (LoRA identifier or empty string)",
    "character_baseline_description": "string (persistent character description)"
  },
  "illustrations": [
    {
      "scene_index": 0,
      "scene_excerpt": "string",
      "concept": "string",
      "character_role": "male" | "female" | "mother"
    }
  ]
}
```

`character_role` is the canonical role of the **single** character appearing
in this scene. It drives which MHA character name is used in prompts (see
§ 7.3). It is one of exactly three values: `male`, `female`, `mother`.

**Empty `illustrations` array signals "no suitable scenes".** The orchestrator
interprets this as a terminal run failure with `error_code =
NO_SUITABLE_SCENES`. This is not an exception — it is a valid Step 0 output
when the input text lacks scenes featuring exactly one of the three
permitted character roles (see § 7.3 for the constraint). The agent must
not invent scenes to avoid an empty result.

The backend truncates non-empty `illustrations` arrays to `MAX_ILLUSTRATIONS`
if longer.

#### Call 1 — `generate_prompts`

**Input:** `current_concept`, `style_guide`.

**Output schema:**
```json
{
  "positive": "string",
  "negative": "string"
}
```

The `positive` field is the full per-scene positive prompt (character +
environment + action + expression, all expressed as Danbooru tags). The
`negative` field is the full per-scene negative prompt. Style-level tags
are NOT included here — they live in `style_guide` and are composed in
by the workflow itself (see § 7.2). See § 7.3.4 for the content
requirements that this prompt must satisfy.

#### Call 2 — `evaluate_image`

**Input:** image (base64), `current_concept`, `style_guide`.

**Output schema:**
```json
{
  "ok": true,
  "problem": null,
  "reasoning": "string",
  "suggestion": ""
}
```
or
```json
{
  "ok": false,
  "problem": "prompt" | "concept",
  "reasoning": "string",
  "suggestion": "string (hint to be passed into the next call)"
}
```

#### Call 3 — `revise_prompts`

**Input:** current `prompts`, last `verdict`, `current_concept`, `style_guide`.

**Output schema:** same as Call 1.

#### Call 4 — `rethink_concept`

**Input:** `current_concept`, last `verdict`, `scene_excerpt`, `style_guide`.

**Output schema:**
```json
{
  "concept": "string (a different concept for the SAME scene_excerpt)"
}
```

### 7.2 RunPod ComfyUI Serverless

The `default.json` workflow file is in **ComfyUI API format**. Five
placeholder strings appear as values in this file and must be replaced
recursively (matching by exact string equality, regardless of JSON path):

- `POSITIVE_PROMPT`
- `NEGATIVE_PROMPT`
- `CHARACTER_LORA`
- `STYLE_POSITIVE_PROMPT`
- `STYLE_NEGATIVE_PROMPT`

The workflow author composes style and scene prompts together inside the
workflow itself. The recommended convention is to use two CLIP Text Encode
nodes per polarity — one containing the style placeholder, one containing
the scene placeholder — and combine their conditionings (e.g. via
`ConditioningConcat`). Alternatively, a single CLIP Text Encode node may
contain the literal string `STYLE_POSITIVE_PROMPT, POSITIVE_PROMPT`, in
which case substitution fills both placeholders inside the same text.
Either approach works with the same substitution logic.

Mapping:

| Placeholder                     | Source                                |
|---------------------------------|---------------------------------------|
| `POSITIVE_PROMPT`               | Call 1 / Call 3 → `positive`          |
| `NEGATIVE_PROMPT`               | Call 1 / Call 3 → `negative`          |
| `CHARACTER_LORA`                | `character_config[role].lora_filename` (see § 7.3.7) |
| `STYLE_POSITIVE_PROMPT`         | Step 0 → `style_guide.overall_style_positive` |
| `STYLE_NEGATIVE_PROMPT`         | Step 0 → `style_guide.overall_style_negative` |

If a placeholder is not found in the workflow JSON, log a warning but
continue. Track which placeholders were found, for diagnostics.

**Endpoint flow:**
1. `POST https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/run` with
   `{"input": {"workflow": <substituted JSON>}}` and
   `Authorization: Bearer {RUNPOD_API_KEY}`. Returns `{"id": "<job_id>"}`.
2. Poll `GET .../status/{job_id}` every `COMFYUI_POLL_INTERVAL_S` seconds
   until status is one of `COMPLETED`, `FAILED`, `CANCELLED`, `TIMED_OUT`,
   or `COMFYUI_POLL_TIMEOUT_S` elapsed.
3. On `COMPLETED`, extract images from `output.images` (worker-comfyui 5.x
   schema: list of `{filename, type, data}` where `type` is `"base64"` or
   `"s3_url"`). Save the first image to disk.

**Image storage:** `OUTPUT_DIR/runs/<run_id>/scene_<scene_index>.png`. The
relative path (relative to `OUTPUT_DIR`) is stored in `illustrations.image_path`.

---

### 7.3 Creative brief for prompt design

This section defines the creative and prompting conventions that all five
Claude agents must respect. The technical contracts in § 7.1 stay generic;
this section makes them concrete for the MVP visual stack.

#### 7.3.1 Visual stack

- **Base model:** Illustrious XL v1.0 (SDXL fine-tune for anime/illustration).
- **Prompt language:** Danbooru-style tags, comma-separated — *not* natural
  language sentences. Example of the expected form: `1girl, school uniform,
  long hair, smiling, hands clasped, classroom, soft window light`.
  Sentences will degrade Illustrious output significantly.
- **Character LoRAs:** MHA-style character LoRAs. Each LoRA has a trigger
  word that must appear in the positive prompt for the character to be
  recognized.
- **Style LoRA:** a single MHA anime style LoRA applied globally to every
  illustration in a run.

#### 7.3.2 Character vocabulary — hard rule

Each illustration in the MVP depicts **exactly one** character. The
character role from Call 0's output (`male`, `female`, `mother`) maps
to a fixed MHA character reference used in prompts:

| `character_role` | Character used in prompts                |
|------------------|------------------------------------------|
| `male`           | Izuku Midoriya (use as boy/man archetype)|
| `female`         | Kyoka Jiro (use as girl/woman archetype) |
| `mother`         | Inko Midoriya                            |

This mapping is the *single source of truth* for character identity in
prompts. Agents 1 and 3 must always use these names (plus their canonical
trigger words and visual descriptors) regardless of the names that appear
in the input text. The input text's character names are narrative only —
they are never sent to ComfyUI.

The mapping lives in `backend/app/constants.py` as a dictionary so that
non-prompt code can also reference it (e.g., during prompt construction in
Agent 1 / Agent 3). Trigger words and baseline visual descriptors for each
character are loaded from configuration (see § 7.3.7).

#### 7.3.3 Single-character scene constraint (MVP)

Agent 0 must select **only scenes that contain exactly one of the three
permitted character roles** acting alone. Scenes with multiple characters
present, group scenes, scenes with crowds, and scenes with no clear
character focus must be excluded.

If the input text yields no such scenes, Agent 0 returns an empty
`illustrations` array (see § 7.1, Call 0). The orchestrator treats this as
a typed terminal failure: `status=FAILED`, `error_code=NO_SUITABLE_SCENES`.
The frontend translates this code to the Slovak UX message defined in
§ 9.1.

Agent 0 must not invent scenes or relax the constraint to avoid an empty
result.

#### 7.3.4 Expression, gesture, and action — mandatory specificity

Since every scene depicts a single character alone, the illustration's
expressiveness depends entirely on what that character is *doing* and
*feeling*. Generic standing poses and ambiguous expressions are not
acceptable.

Agent 0 must select scenes where the character's emotional state, gesture,
posture, or activity is concrete and depictable. Each `concept` field
must explicitly mention at least one of:

- A specific **facial expression** (`crying`, `surprised`, `determined`,
  `furrowed brow`, `wide-eyed`, etc.),
- A specific **gesture or posture** (`reaching out`, `clutching a book to
  chest`, `kneeling`, `head bowed`, etc.),
- A specific **action being performed** (`pouring water from a kettle`,
  `picking up a coin`, `running through a field`, etc.).

A combination of these is preferred over any single one.

Agents 1 and 3 carry this discipline into the actual Danbooru tags. The
`positive` field must include explicit emotion/expression tags and
explicit action/pose tags. Vague tags like `standing`, `looking`, or
`posing` alone are insufficient and must be augmented with specifics.

Agent 2 evaluates this discipline as part of its checklist (see § 7.3.5).
A correctly rendered character with a vague or ambiguous expression should
be rejected with `problem="prompt"` and a suggestion to add specifics.

#### 7.3.5 Agent 2 evaluation checklist

Agent 2 (`evaluate_image`) judges each rendered image against this
checklist. The image is `ok` only when **all** of the following hold:

1. **Exactly one character is visible.** Multiple visible characters →
   `problem="prompt"`.
2. **The character matches the expected role** (male, female, or mother)
   per § 7.3.2 — recognizable as the corresponding MHA character.
3. **The character's expression, gesture, or action is clearly
   identifiable and matches the concept.** Vague or generic poses →
   `problem="prompt"` with a suggestion to add specifics.
4. **The illustration is style-consistent** with `style_guide` — anime/MHA
   look, no realism, no off-style rendering.
5. **No anatomical deformities** — extra fingers, fused limbs, distorted
   face, misaligned eyes are unacceptable.
6. **Safe for general audiences** — no suggestive, revealing, or otherwise
   inappropriate content. Any safety issue → `problem="concept"`
   (concept-level rejection, not a prompt fix).
7. **The scene composition serves the concept** — environment supports the
   action, framing is appropriate.

`problem="concept"` is reserved for failures that prompt revision cannot
plausibly fix: safety violations, fundamental impossibility of the
concept, or repeated failure of the same kind across attempts.

`problem="prompt"` is the default for fixable issues: missing or wrong
expression, missing action, wrong environment, mild anatomy issues.

#### 7.3.6 Negative prompt baseline

Agents 1 and 3 must always include in `negative` a standard safety and
quality baseline, in addition to scene-specific negatives. The baseline
includes at minimum:

- Safety: `nsfw, suggestive, revealing clothing, lingerie, nudity,
  cleavage, underwear, sexualized`.
- Anatomy: `bad anatomy, extra fingers, missing fingers, fused fingers,
  malformed hands, extra limbs, distorted face, asymmetric eyes`.
- Quality: `low quality, blurry, watermark, signature, text, jpeg
  artifacts`.
- Composition: `multiple characters, crowd, two girls, two boys, 2girls,
  2boys, group` — to reinforce the single-character constraint.

The exact baseline string lives in `backend/app/constants.py` so it is
reusable and consistent across agents 1 and 3.

#### 7.3.7 Character configuration

The mapping in § 7.3.2 needs concrete details to be useful in prompts:
each role needs its LoRA trigger word(s) and a short baseline visual
descriptor. These are stored in a config file `backend/app/character_config.json`
with the following shape:

```json
{
  "male": {
    "display_name": "Izuku Midoriya",
    "lora_filename": "<filename of the LoRA in ComfyUI/models/loras/>",
    "trigger_tags": "midoriya izuku, green hair, green eyes, freckles, short hair",
    "outfit_baseline": "<canonical outfit tags, e.g. school uniform>"
  },
  "female": {
    "display_name": "Kyoka Jiro",
    "lora_filename": "...",
    "trigger_tags": "jirou kyouka, short hair, black hair, dark purple hair, ear jacks",
    "outfit_baseline": "..."
  },
  "mother": {
    "display_name": "Inko Midoriya",
    "lora_filename": "...",
    "trigger_tags": "midoriya inko, green hair, low ponytail, plump, mature female",
    "outfit_baseline": "..."
  }
}
```

The exact trigger tags and outfit baselines are filled in by the operator
when the LoRAs are downloaded (the values shown above are illustrative).
The implementation must read this file at startup and refuse to run if it
is malformed or any required role is missing.

The `CHARACTER_LORA` placeholder in the ComfyUI workflow is filled from
`character_config[role].lora_filename` at render time, based on the role
of the scene being rendered (this is what § 7.2 already shows in its
mapping table).

#### 7.3.8 Style guide responsibilities

Agent 0's `style_guide` output covers global, illustration-wide concerns:

- `overall_style_positive`: anime/MHA style tags applied to every image,
  e.g. `mha style, anime, manga illustration, soft shading, clean
  linework`. Composed with the per-illustration prompts in the workflow.
- `overall_style_negative`: global negatives layered on top of the
  baseline (§ 7.3.6), e.g. `realistic, photo, 3d, western cartoon`.
- `character_lora`: ignored at render time in MVP (see § 7.3.7). May be
  left empty or set to a placeholder by Agent 0; the rendering pipeline
  takes the actual LoRA from `character_config`.
- `character_baseline_description`: a free-text English description of
  the visual continuity intended across all illustrations of this run
  (e.g., "All scenes share warm afternoon lighting and a storybook-like
  framing"). Agents 1 and 3 reference this when constructing prompts.

---

## 8. Backend API

All endpoints return JSON unless noted. CORS allows `ALLOWED_ORIGIN`.

### `POST /api/runs`

Start a new run.

Request body:
```json
{ "story_text": "string (non-empty)" }
```

Response 201:
```json
{ "run_id": "uuid" }
```

Errors:
- 400 if `story_text` is empty or too long (>50 000 chars).
- 503 if startup config is invalid (should not normally happen after boot).

The endpoint persists the run with `status=RUNNING`, schedules the
orchestrator as a background task, and returns immediately.

### `GET /api/runs/{run_id}`

Returns a snapshot of the run and all its illustrations. Used by the
frontend on reconnect / direct navigation.

Response 200:
```json
{
  "run": {
    "id": "uuid",
    "status": "RUNNING|COMPLETED|FAILED|CANCELLED",
    "story_text": "string",
    "style_guide": { ... } | null,
    "illustration_count": 0,
    "completed_count": 0,
    "failed_count": 0,
    "created_at": "iso",
    "updated_at": "iso",
    "error_code": "string|null",
    "error_message": "string|null"
  },
  "illustrations": [
    {
      "id": "uuid",
      "scene_index": 0,
      "scene_excerpt": "string",
      "character_role": "male|female|mother",
      "current_concept": "string",
      "state": "PENDING|...|COMPLETED|FAILED|CANCELLED",
      "concept_attempt": 1,
      "prompt_attempt": 1,
      "image_url": "string|null"
    }
  ]
}
```

`image_url` is `null` until completed, then `/static/runs/<run_id>/scene_N.png`.

### `GET /api/runs/{run_id}/events`  (SSE)

Server-Sent Events stream.

On connection, the server emits a synthetic `snapshot` event mirroring the
shape of `GET /api/runs/{run_id}`, then live events follow.

SSE event types (`event:` field) and JSON payloads:

| Event                       | Payload                                                                 |
|-----------------------------|-------------------------------------------------------------------------|
| `snapshot`                  | `{ "run": {...}, "illustrations": [...] }`                              |
| `style_guide_ready`         | `{ "style_guide": {...}, "illustration_count": N }`                     |
| `illustration_state`        | `{ "illustration_id", "scene_index", "state", "concept_attempt", "prompt_attempt" }` |
| `illustration_completed`    | `{ "illustration_id", "scene_index", "image_url" }`                     |
| `illustration_failed`       | `{ "illustration_id", "scene_index", "error_message" }`                 |
| `run_completed`             | `{ "completed": N, "failed": M }`                                       |
| `run_failed`                | `{ "error_code": "string", "error_message": "string" }`                 |
| `run_cancelled`             | `{}`                                                                    |
| `heartbeat`                 | `{}` every 15 s to keep the connection alive                            |

The stream closes after `run_completed`, `run_failed`, or `run_cancelled`.

### `POST /api/runs/{run_id}/cancel`

Marks the run for cancellation. Active branches must observe a cooperative
cancellation flag at every state transition and at every poll cycle of
ComfyUI. Already-running ComfyUI jobs are allowed to finish (RunPod itself
is not cancelled mid-flight in MVP — document this), but no further calls
are made and the branch transitions to `CANCELLED`.

Response 200:
```json
{ "status": "CANCELLED" }
```

Returns 409 if the run is already in a terminal state.

### Static file serving

`GET /static/runs/<run_id>/<filename>` serves files from `OUTPUT_DIR`. Use
FastAPI's `StaticFiles` mount.

### Orchestrator failure handling

The background orchestrator (Step 0 + per-illustration branches) runs
inside an outer try/except block. Any unhandled exception, plus the
specific known terminal conditions below, must transition the run to
`status=FAILED` with both `error_code` and `error_message` set, and emit
a `run_failed` SSE event before closing the stream.

The following `error_code` values are defined for MVP:

| `error_code`             | Meaning                                                                                            |
|--------------------------|----------------------------------------------------------------------------------------------------|
| `NO_SUITABLE_SCENES`     | Agent 0 returned an empty `illustrations` array (§ 7.3.3). Frontend shows the dedicated UX message. |
| `STEP0_FAILED`           | Agent 0 itself failed (Claude error after retries, JSON parse failure, etc.).                       |
| `INTERNAL_ERROR`         | Any other unhandled exception in the orchestrator.                                                  |

Branch-level failures (a single illustration failing after all attempts)
do **not** trigger a run-level failure — the run completes as
`COMPLETED` with a non-zero `failed_count`. Only Step 0 errors and
unhandled exceptions take down the whole run.

---

## 9. Frontend

### 9.1 Screens

The frontend is a 2-screen SPA.

#### Screen A — Home (`/`)

**Purpose:** Submit input text for a new run.

**Elements:**
- App title "Anime ilustrátor".
- A `<textarea>` labelled "Text príbehu", min height ~12 rows, with a
  character counter "X / 50000".
- A primary button "Vygenerovať ilustrácie", disabled when the textarea is
  empty or over the limit.
- Below the button, a short hint: "Aplikácia vyberie vhodné miesta v texte
  a vygeneruje k nim anime ilustrácie. Trvá to niekoľko minút."

**Behavior:**
- On submit, `POST /api/runs`, then navigate to `/runs/:run_id`.
- On error, show a toast / inline error with a Slovak message.

#### Screen B — Run (`/runs/:run_id`)

**Purpose:** Show progress of an in-flight run, or the final results of a
completed one.

**Elements (top to bottom):**
1. **Header:** "Generovanie anime ilustrácií". A back link "← Nový text".
2. **Run status pill:** "Beží" (with spinner) / "Hotovo" / "Zlyhalo" / "Zrušené".
3. **Run-level error banner:** visible when `run.status === "FAILED"` —
   displays the Slovak UX message corresponding to `run.error_code` (see
   § 9.4). Spans the full width above the global progress.
4. **Global progress:** "Hotové: K z N" (where N is `illustration_count`
   once known, otherwise "—"). Below it, a minimal horizontal bar showing
   `completed_count / illustration_count` (no fake percentages). Hidden
   when the run is in the `FAILED` state with `error_code =
   NO_SUITABLE_SCENES` (no illustrations were ever planned, so the
   counter is meaningless).
5. **Cancel button:** "Zrušiť beh" — visible only while status is `RUNNING`.
   Confirms via a small inline confirmation ("Naozaj zrušiť?" + Áno / Nie).
6. **Illustration grid:** a responsive grid of `IllustrationCard` items,
   one per illustration. Hidden when `illustrations.length === 0`.

**Each `IllustrationCard` shows:**
- Scene number "Ilustrácia K".
- The current state with its Slovak label (see § 6 table).
- A small spinner / pulse animation while the state is non-terminal.
- The current attempt counters if relevant: "pokus K/3" during `RENDERING`,
  attempt info also during `REVISING_PROMPTS` / `RETHINKING_CONCEPT`.
- An excerpt-preview tooltip or expandable section showing
  `scene_excerpt` (truncated to ~200 chars in the card body).
- On `COMPLETED`: the image (full bleed inside the card, max-height
  ~400 px, click to open the original).
- On `FAILED`: a short error message and a sad-face affordance (no retry
  button in MVP).
- On `CANCELLED`: greyed-out card with label "Zrušené".

**Behavior:**
- On mount, call `GET /api/runs/{run_id}` to get a snapshot, then open an
  `EventSource` to `GET /api/runs/{run_id}/events`.
- SSE events update the store. The first SSE event (`snapshot`) is treated
  as the authoritative state and replaces the snapshot fetched via REST
  (the REST call is a fallback if SSE fails).
- On `run_completed` / `run_failed` / `run_cancelled`, close the EventSource
  but stay on the screen.
- On navigation away, close the EventSource.

### 9.2 Pinia store: `runStore`

State:
- `run: Run | null`
- `illustrations: Illustration[]` (by `scene_index` order)
- `isConnecting: boolean`
- `sseError: string | null`

Actions:
- `startRun(storyText)` → POST, sets `run`, returns `run_id`.
- `loadRun(runId)` → GET snapshot.
- `subscribe(runId)` → opens EventSource, dispatches updates.
- `unsubscribe()` → closes EventSource.
- `cancel()` → POST cancel.

Internal mutations triggered by SSE events update the right illustration in
place by `illustration_id`.

### 9.3 Styling

- Scoped SCSS per component.
- A small `assets/styles/_tokens.scss` for shared variables (colors,
  spacing, radii) and one global `_reset.scss`.
- Minimalistic visual style: light background, generous whitespace,
  one accent color. No UI kit.

### 9.4 Error code → Slovak UX message mapping

When the run-level error banner is shown (§ 9.1, Screen B element #3),
the frontend maps `run.error_code` to a Slovak message as follows:

| `error_code`           | Slovak UX message                                                                                              |
|------------------------|----------------------------------------------------------------------------------------------------------------|
| `NO_SUITABLE_SCENES`   | "Zadaný text nie je vhodný ako zdroj ilustrácií. Mal by obsahovať aspoň jednu jasnú scénu s jednou postavou — chlapcom/mužom, dievčaťom/ženou alebo matkou — ktorá robí niečo konkrétne." |
| `STEP0_FAILED`         | "Analýza textu zlyhala. Skúste prosím znova, prípadne upravte vstupný text."                                   |
| `INTERNAL_ERROR`       | "Vyskytla sa neočakávaná chyba. Skontrolujte log servera pre detaily."                                         |

Unknown codes fall back to the `INTERNAL_ERROR` message. The mapping
lives in a TypeScript module (e.g. `src/i18n/runErrors.ts`) so it is
testable in isolation.

---

## 10. Constants

Defined in `backend/app/constants.py`:

| Name                              | Value | Meaning                                                           |
|-----------------------------------|-------|-------------------------------------------------------------------|
| `MAX_ILLUSTRATIONS`               | 5     | Hard cap on illustrations per run (truncate Step 0 output)        |
| `MAX_PROMPT_ATTEMPTS_PER_CONCEPT` | 3     | Total image-generation attempts per concept (initial + 2 revisions)|
| `MAX_CONCEPT_ATTEMPTS`            | 3     | Total concepts tried per illustration (initial + 2 rethinks)      |
| `COMFYUI_POLL_TIMEOUT_S`          | 600   | Max wait per ComfyUI job                                          |
| `COMFYUI_POLL_INTERVAL_S`         | 3     | Polling interval                                                  |
| `MAX_CONCURRENT_BRANCHES`         | 5     | Async semaphore over branches (= MAX_ILLUSTRATIONS for MVP)       |
| `CLAUDE_JSON_RETRY`               | 2     | Re-prompts on Claude output JSON parse failure                    |
| `STORY_MAX_CHARS`                 | 50000 | Hard limit on input length                                        |
| `ANTHROPIC_MODEL`                 | `"claude-sonnet-4-6"` | Single model used for all 5 calls                 |

---

## 11. Tests (mandatory before delivery)

All tests must pass. Reasonable coverage of the listed scenarios; no need
to chase 100 % line coverage.

### 11.1 Backend unit (`tests/unit/`)

- **Placeholder replacement** (`services/workflow.py`):
  - Replaces all five placeholders (`POSITIVE_PROMPT`, `NEGATIVE_PROMPT`,
    `CHARACTER_LORA`, `STYLE_POSITIVE_PROMPT`, `STYLE_NEGATIVE_PROMPT`)
    nested at arbitrary depths.
  - Leaves unrelated strings untouched.
  - Reports which placeholders were missing.
  - `CHARACTER_LORA` is sourced from `character_config[role].lora_filename`
    based on the per-illustration role (per § 7.3.7), not from
    `style_guide.character_lora`.
- **Character config loader** (new test file):
  - Loads a valid `character_config.json` and exposes all three roles.
  - Refuses to start (raises typed error) when the file is missing,
    malformed JSON, or missing any of the three required roles
    (`male`, `female`, `mother`).
  - Refuses to start when any role entry is missing required keys
    (`lora_filename`, `trigger_tags`).
- **Claude IO schemas** (`schemas/...`):
  - Each of the 5 response Pydantic models accepts a valid example.
  - Each rejects a malformed example (missing field, wrong type).
  - `analyze_story`:
    - Truncation to `MAX_ILLUSTRATIONS` when more arrive.
    - Empty `illustrations: []` is a valid response (NOT a schema error).
    - `character_role` must be one of `male`, `female`, `mother`; any
      other value is rejected.
- **Branch state machine** (`orchestrator/branch.py`), with Claude and
  RunPod fully mocked:
  - Happy path: first attempt succeeds → `COMPLETED`.
  - Prompt revision path: 1st attempt prompt-bad, 2nd attempt ok.
  - Concept restart path: all 3 prompt attempts fail with `problem="prompt"`
    on concept 1 → falls through to concept 2; concept 2 succeeds.
  - Concept rejection: verdict returns `problem="concept"` on attempt 1 →
    immediately move to next concept.
  - All attempts exhausted → `FAILED` with sensible error.
  - Cancellation observed: flag set mid-run → `CANCELLED`, no further
    external calls.
  - Branch uses the correct `character_config` entry based on its
    `character_role` (verified via the workflow substitution).
- **Top-level orchestrator** (`orchestrator/pipeline.py`):
  - Step 0 produces N=3 illustrations → 3 branches spawned, aggregate
    counts correct.
  - Step 0 produces N=8 → truncated to 5.
  - All branches succeed → run `COMPLETED` with `completed_count = N`.
  - Mixed outcome (3 ok, 2 failed) → run `COMPLETED` (run is not "failed"
    just because some branches failed).
  - Step 0 returns empty `illustrations: []` → run `FAILED` with
    `error_code = NO_SUITABLE_SCENES`, `run_failed` SSE event emitted
    with the same code. No branches spawned, no ComfyUI calls made.
  - Step 0 itself raises (Claude error) → run `FAILED` with
    `error_code = STEP0_FAILED`.
  - Unhandled exception inside orchestrator → run `FAILED` with
    `error_code = INTERNAL_ERROR`.
- **SSE event bus** (`orchestrator/events.py`):
  - `snapshot` is emitted first to a new subscriber.
  - Events broadcast to multiple subscribers (idempotent).
  - Stream closes on terminal run states.
  - `run_failed` payload includes both `error_code` and `error_message`.
- **RunPod client** (`services/runpod.py`), HTTP mocked with respx:
  - `/run` returns 200 → parses job_id.
  - `/status` polled until `COMPLETED` → returns image bytes.
  - Timeout path raises a typed error.
  - `FAILED`/`CANCELLED`/`TIMED_OUT` raise a typed error.

### 11.2 Backend integration (`tests/integration/`)

Anthropic and RunPod are mocked at the HTTP layer (respx). SQLite uses a
temporary file per test.

- **End-to-end happy path:** `POST /api/runs` → background work runs to
  completion → `GET /api/runs/{id}` returns `COMPLETED` with image paths
  written under a tmp `OUTPUT_DIR`. The SSE stream emits the expected
  sequence ending with `run_completed`.
- **NO_SUITABLE_SCENES end-to-end:** mock Anthropic to return an empty
  `illustrations: []` from Agent 0. `POST /api/runs` → background work
  transitions the run to `FAILED` with `error_code = NO_SUITABLE_SCENES`.
  `GET /api/runs/{id}` reflects this. The SSE stream emits a single
  `run_failed` event carrying the code, then closes. No ComfyUI calls
  are made.
- **Mixed outcome with cancellation:** start a run, cancel after the first
  branch transitions to `RENDERING`, verify final status `CANCELLED` and
  that branches transitioned to `CANCELLED` rather than continuing.

### 11.3 Frontend unit (`frontend/tests/`)

Pinia store and components are tested with Vitest + @vue/test-utils.

- **IllustrationCard:**
  - Renders the correct Slovak label for each of the 9 states.
  - Shows spinner for non-terminal states, hides it for terminal states.
  - Shows attempt counter ("pokus 2/3") only during `RENDERING`,
    `REVISING_PROMPTS`, `RETHINKING_CONCEPT`.
  - Renders image on `COMPLETED`, error text on `FAILED`.
- **ProgressCounter:**
  - Renders "Hotové: K z N".
  - Renders "Hotové: 0 z —" when illustration_count is unknown.
  - Hidden when run status is `FAILED` with `error_code = NO_SUITABLE_SCENES`.
- **CancelButton:**
  - Visible only when run status is `RUNNING`.
  - Requires inline confirmation before calling the API.
- **RunErrorBanner** (new component):
  - Hidden when run status is not `FAILED`.
  - Visible when run status is `FAILED`, displays the Slovak UX message
    mapped from `error_code` (see § 9.4).
  - For `NO_SUITABLE_SCENES`, shows the dedicated guidance message.
  - For unknown `error_code`, falls back to the `INTERNAL_ERROR` message.
- **`runErrors.ts` i18n mapping** (new unit test file):
  - Each known code maps to its specified Slovak message.
  - Unknown code falls back to `INTERNAL_ERROR` message.
  - `null` / `undefined` code produces empty string (banner stays hidden).
- **runStore:**
  - `snapshot` event replaces full state.
  - `illustration_state` event updates the right illustration by id.
  - `illustration_completed` event sets `image_url`.
  - `run_cancelled` sets run status correctly and unsubscribes.
  - `run_failed` event sets `error_code` and `error_message`, transitions
    status to `FAILED`, and unsubscribes from SSE.
  - Tolerates out-of-order or duplicate events without crashing.

### 11.4 What is NOT required (out of scope for MVP)

- E2E browser tests (Playwright/Cypress).
- Tests against the real Anthropic API or real RunPod.
- Load/performance tests.
- 100 % coverage.

### 11.5 Linting and type-checking

Mandatory before delivery. The setup is intentionally lightweight, not
strict — the goal is to catch obvious mistakes and keep style consistent,
not to fight the tooling.

**Backend (configured in `backend/pyproject.toml`):**

- **Ruff** for both linting and formatting (Black-compatible). Rule
  selection: defaults plus `I` (isort), `B` (bugbear), `UP` (pyupgrade).
  Line length 100. Target Python 3.11.
- **`mypy` is NOT required** for MVP. Type hints in code are welcome but
  no type checker enforces them.

Commands:
```bash
ruff check .
ruff format --check .
```

**Frontend (configured in `frontend/eslint.config.js` and `tsconfig.json`):**

- **ESLint** with flat config:
  - `eslint-plugin-vue` preset `vue3-recommended` (or `vue3-essential` if
    `vue3-recommended` causes friction with WIP code).
  - `@vue/eslint-config-typescript` — the **non-type-checked** variant
    (the type-checked rule set is heavy and slow; we rely on `vue-tsc`
    for actual type checking).
  - No Prettier in MVP. Use `eslint --fix` for auto-fixable issues.
- **TypeScript** strictness in `tsconfig.json`:
  - `"strict": true`,
  - but relax `"noUnusedLocals": false` and `"noUnusedParameters": false`
    to allow unfinished variables during development.
- **`vue-tsc`** for type checking with `--noEmit`.

Commands (npm scripts):
```bash
npm run lint         # eslint .
npm run type-check   # vue-tsc --noEmit
```

**All four commands above must exit with zero errors before the work is
considered complete.** Warnings configured as warnings are tolerated;
warnings configured as errors (the default for most rules in the chosen
presets) are not.

---

## 12. Non-goals for MVP (explicitly out of scope)

- Multiple workflows / workflow selection by Claude.
- Retrying a single failed illustration without re-running the whole story.
- User accounts / multi-tenant.
- Run history listing UI (the DB will accumulate runs, but no UI to browse).
- Migrations.
- Internationalization beyond Slovak UI labels.
- Mid-flight cancellation of an already-dispatched ComfyUI job.

---

## 13. Acceptance criteria

The MVP is considered complete when:

1. All tests defined in § 11.1–11.3 pass, and all lint/format/type-check
   commands defined in § 11.5 exit with zero errors.
2. With valid `.env` values, running `uvicorn` (backend) and `npm run dev`
   (frontend) starts both services without errors.
3. A user can paste a text on `/`, click the button, be navigated to
   `/runs/:id`, see live updates via SSE, and end with up to 5 anime
   illustrations rendered in the grid.
4. Cancelling an in-flight run brings it to `CANCELLED` within a few
   seconds, and the UI reflects this.
5. Refreshing the run page mid-flight does not lose state — the snapshot
   restores the UI and SSE resumes.
6. No secrets are present in the frontend bundle.
7. When the input text contains no scenes suitable for single-character
   illustration (per § 7.3.3), the run terminates as `FAILED` with
   `error_code = NO_SUITABLE_SCENES`, and the frontend displays the
   dedicated Slovak UX message from § 9.4 instead of an empty grid.
