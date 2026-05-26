# Anime Illustrator — Project Specification (MVP)

This document is the single source of truth for the implementation. All terms,
schemas, and contracts defined here are normative. Anything not specified is
left to the implementer's reasonable judgment, but must not contradict this
document.

---

## 1. Purpose

A locally-hosted web application that helps a user co-create a short anime
story with an AI assistant, then automatically illustrates that story with up
to **5 anime illustrations** rendered in parallel. Claude (Anthropic API)
drives both the conversation and the visual reasoning; a RunPod Serverless
ComfyUI endpoint performs the image rendering.

The input is **not** a free-form story text. Instead, the user chats with a
virtual assistant (Agent 0a) that:

1. **Gathers** the inputs needed to shape the story — the cast (subject to a
   hard character-vocabulary constraint, see § 7.3.2) and the overall topic
   or concept;
2. **Summarizes** what has been agreed and waits for the user's natural-
   language confirmation;
3. Once confirmed, hands the brief over to a second agent (Agent 0b) that
   **constructs the actual short story together with the illustration
   concepts**, satisfying both the user's intent and the app's hard
   constraints on illustratability (see § 7.3).

After Agent 0b finishes, the chat is replaced by the rendered story (heading,
paragraphs, inline illustration placeholders) and the existing per-
illustration progress cards stay visible below the story. Each illustration
runs through its own per-image self-correction loop driven by Claude's
visual evaluation.

The story itself is not frozen at Agent 0b's output. When the per-image
loop escalates to **Agent 4** (`rethink_concept`), Agent 4 is allowed —
and in fact required — to also rewrite the surrounding paragraph so the
new concept lands on a story beat the renderer can actually depict
(§ 7.1 Call 4). Rewrites preserve the flow, linearity and logic of the
story and are propagated to the live UI: the paragraph re-renders in
place via the SSE `paragraph_updated` event (§ 8.4), having visibly
displayed a skeleton loader while Agent 4 was thinking (§ 9.1 Screen B).
The Pinia store on the client holds the **current** story content and is
the single source of truth the UI binds to; the backend persists the
same current content in `runs.story_blocks_json` so reconnects and
snapshots also reflect the latest state (§ 5.3, § 8.3).

The visual output style is anime/manga, rendered by an Illustrious-based
SDXL ComfyUI workflow with character and style LoRAs. See § 7.3 for the
full creative and prompting brief.

---

## 2. Tech Stack

| Layer       | Technology                                                    |
|-------------|---------------------------------------------------------------|
| Backend     | Python 3.11+, FastAPI, async SQLAlchemy 2.x, aiosqlite, httpx |
| Frontend    | Vue 3 + Vite + TypeScript, Pinia, scoped SCSS                 |
| Database    | SQLite (local file)                                           |
| Migrations  | Alembic (schema versioned in `backend/alembic/versions/`)     |
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
│   ├── alembic.ini                 # Alembic config (script_location, etc.)
│   ├── alembic/
│   │   ├── env.py                  # Wires Alembic to Base.metadata + settings
│   │   ├── script.py.mako          # Migration template
│   │   └── versions/               # Migration scripts, committed to git
│   ├── app/
│   │   ├── main.py                 # FastAPI app, CORS, routers, startup
│   │   ├── config.py               # Settings (pydantic-settings, .env)
│   │   ├── constants.py            # Numeric limits, enum values, welcome text
│   │   ├── character_config.json   # Character role → LoRA + tags (§ 7.3.7)
│   │   ├── agents/                 # Agent system prompts as Markdown (§ 7.4)
│   │   │   ├── chat.md             # Agent 0a — chat / brief gathering
│   │   │   ├── build_story.md      # Agent 0b — story + illustration concepts
│   │   │   ├── generate_prompts.md # Agent 1
│   │   │   ├── evaluate_image.md   # Agent 2
│   │   │   ├── revise_prompts.md   # Agent 3
│   │   │   └── rethink_concept.md  # Agent 4
│   │   ├── db/
│   │   │   ├── models.py           # SQLAlchemy ORM models
│   │   │   ├── session.py          # async engine + session factory
│   │   │   └── repositories.py     # CRUD helpers
│   │   ├── schemas/                # Pydantic models for API + Claude IO
│   │   ├── services/
│   │   │   ├── claude.py           # Anthropic API client; loads agent prompts
│   │   │   ├── runpod.py           # RunPod /run + /status polling
│   │   │   ├── workflow.py         # Placeholder replacement, JSON load
│   │   │   └── images.py           # Save/load image files to disk
│   │   ├── orchestrator/
│   │   │   ├── pipeline.py         # Top-level run orchestration
│   │   │   ├── branch.py           # Per-illustration state machine
│   │   │   └── events.py           # SSE event bus (per-run pub/sub)
│   │   ├── api/
│   │   │   ├── sessions.py         # Chat session endpoints + finalize
│   │   │   ├── runs.py             # GET run snapshot + SSE + cancel
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
    │   │   ├── session.ts          # Chat session store
    │   │   └── run.ts              # Pinia store for the run page
    │   ├── views/
    │   │   ├── HomeView.vue        # Chat interface (no textarea)
    │   │   └── RunView.vue         # Story + inline placeholders + cards
    │   ├── components/
    │   │   ├── ChatThread.vue
    │   │   ├── ChatMessage.vue
    │   │   ├── ChatComposer.vue
    │   │   ├── StoryBlocks.vue         # renders the list of blocks
    │   │   ├── StoryParagraph.vue      # one reactive paragraph block (§ 9.1)
    │   │   ├── InlineIllustration.vue
    │   │   ├── IllustrationCard.vue
    │   │   ├── ConceptPopover.vue      # header info-icon + popover (§ 9.1)
    │   │   ├── SkeletonBlock.vue       # generic skeleton loader (§ 9.1, § 9.3)
    │   │   ├── ProgressCounter.vue
    │   │   ├── RunErrorBanner.vue
    │   │   └── CancelButton.vue
    │   ├── services/
    │   │   └── api.ts              # fetch wrappers + SSE EventSource
    │   ├── i18n/
    │   │   ├── runErrors.ts
    │   │   └── sessionErrors.ts
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
AGENTS_DIR=./app/agents
ALLOWED_ORIGIN=http://localhost:5173
```

All keys are required (the app must refuse to start on missing values, with
a clear error message). Provide `.env.example` with placeholder values.

### Frontend

A `.env` for the frontend with `VITE_API_BASE=http://localhost:8000` is
sufficient. No secrets ever live in the frontend.

The Vite dev server proxies `/static` to the backend (see `vite.config.ts`)
so that root-relative `image_url` paths returned by the API (e.g.
`/static/runs/<run_id>/scene_N.png`) load correctly from the page origin
during development.

---

## 5. Data Model

Four tables (`sessions`, `session_messages`, `runs`, `illustrations`),
managed by **Alembic** migrations. See § 5.0 for the migration
workflow; the schema definitions below are the source of truth and the
initial baseline migration must match them exactly.

### 5.0 Migrations (Alembic)

Schema changes are versioned, not applied implicitly. The previous
`Base.metadata.create_all` approach silently let the on-disk SQLite go
out of sync with the models whenever a column was added or a table was
renamed; Alembic replaces it.

**Setup**

- `alembic` is added to `backend/pyproject.toml` as a runtime
  dependency.
- `backend/alembic.ini` lives at the backend root. Its
  `script_location = alembic` and the SQLAlchemy URL is **not** set in
  the ini file — `env.py` reads it from `settings.database_url` so
  there is one source of truth.
- `backend/alembic/env.py`:
  - Imports `Base` from `app.db.models` and sets
    `target_metadata = Base.metadata` so `--autogenerate` works.
  - Uses the async engine via `connection.run_sync(...)` inside
    `run_migrations_online()` (Alembic's documented async pattern),
    because the production engine is `aiosqlite`.
  - Enables `render_as_batch=True` in `context.configure(...)` so that
    SQLite — which has very limited `ALTER TABLE` support — gets a
    table-rebuild migration path that actually works for column adds /
    renames / drops.
- `backend/alembic/versions/` holds the generated migration scripts.
  All migration files are committed to git.

**Workflow**

- After any change to `app/db/models.py`, the developer runs:
  ```bash
  alembic revision --autogenerate -m "<short description>"
  ```
  inspects the generated script, edits it if autogenerate missed a
  rename (autogenerate sees a drop-and-add), and commits it.
- On startup, the backend applies pending migrations to the
  configured database before serving traffic. This replaces the old
  `create_tables()` call in `app/main.py` lifespan:
  ```python
  from alembic import command
  from alembic.config import Config

  cfg = Config("alembic.ini")
  cfg.attributes["configure_logger"] = False  # FastAPI owns logging
  command.upgrade(cfg, "head")
  ```
  The upgrade is invoked synchronously inside the async lifespan via
  `asyncio.to_thread(...)` since Alembic's command API is sync.
- The CLI is also available for manual ops:
  - `alembic upgrade head` — apply all pending migrations.
  - `alembic downgrade -1` — roll back the most recent migration (used
    rarely; SQLite + `render_as_batch` makes downgrades best-effort).
  - `alembic history` / `alembic current` — inspect state.

**Baseline migration**

- The first migration (e.g. `0001_initial.py`) recreates the full
  four-table schema described in the subsections below. It is
  autogenerated from the models against an empty database and then
  hand-checked.
- Existing dev databases that pre-date Alembic are **not** migrated
  automatically. The README documents the one-off fix: stop the
  backend, move `backend/data/app.db` aside (e.g. `app.db.pre-alembic`),
  start the backend so Alembic creates a fresh schema, and re-run
  whatever data was needed. There is no production data to preserve.

**Tests**

- Backend tests continue to use a temporary SQLite file per test for
  speed. They run `command.upgrade(cfg, "head")` against that
  temporary URL inside the test fixture instead of calling
  `Base.metadata.create_all` directly, so every test exercises the
  exact same DDL path as production.
- A single unit test asserts that
  `alembic revision --autogenerate` against the current models
  produces **no** pending operations — i.e. the models and the
  latest migration are in sync. This catches the common mistake of
  changing a model without generating a migration.

### `sessions`

A chat session that ends either in the creation of a `run` (success path) or
in a typed failure. One session corresponds to one user's attempt at
shaping a story.

| Column                | Type         | Notes                                                |
|-----------------------|--------------|------------------------------------------------------|
| `id`                  | TEXT (UUID4) | Primary key                                          |
| `created_at`          | DATETIME     | UTC                                                  |
| `updated_at`          | DATETIME     | UTC                                                  |
| `state`               | TEXT (enum)  | `CHATTING` / `AWAITING_CONFIRMATION` / `BUILDING_STORY` / `COMPLETED` / `FAILED` |
| `collected_brief_json`| TEXT NULL    | JSON: the brief captured by Agent 0a; set on confirmation. Shape includes the optional `companions` pool (§ 7.1 Call 0a) but the column itself remains plain TEXT JSON — no schema change. |
| `run_id`              | TEXT FK NULL | → `runs.id`; set when Agent 0b finishes and the run is created |
| `error_code`          | TEXT NULL    | `STORY_BUILD_FAILED`, `CHAT_FAILED`, `INTERNAL_ERROR` (see § 8.6) |
| `error_message`       | TEXT NULL    | Human-readable technical detail (English)            |

### `session_messages`

Ordered chat transcript for a session.

| Column        | Type         | Notes                                                       |
|---------------|--------------|-------------------------------------------------------------|
| `id`          | TEXT (UUID4) | Primary key                                                 |
| `session_id`  | TEXT FK      | → `sessions.id`                                             |
| `order_index` | INTEGER      | Monotonic per session, starting at 0                        |
| `role`        | TEXT (enum)  | `user` / `assistant`                                        |
| `content`     | TEXT         | The displayed message text (Slovak for `assistant`)         |
| `phase`       | TEXT NULL    | For `assistant`: `intro` / `gathering` / `awaiting_confirmation` / `confirmed` |
| `created_at`  | DATETIME     | UTC                                                         |

The first row of every session is always an `assistant` message with
`phase='intro'` and `content` equal to the welcome text (see § 9.2.1). It
is inserted by the backend at session creation time and is NOT produced
by Claude.

### `runs`

A run is created **after** the user confirms the brief and Agent 0b
returns the story plus illustration concepts. Runs are no longer created
from raw input text.

| Column              | Type         | Notes                                                       |
|---------------------|--------------|-------------------------------------------------------------|
| `id`                | TEXT (UUID4) | Primary key                                                 |
| `session_id`        | TEXT FK      | → `sessions.id`                                             |
| `created_at`        | DATETIME     | UTC                                                         |
| `updated_at`        | DATETIME     | UTC                                                         |
| `status`            | TEXT (enum)  | `RUNNING` / `COMPLETED` / `FAILED` / `CANCELLED`            |
| `story_title`       | TEXT         | The story's heading, produced by Agent 0b                   |
| `story_blocks_json` | TEXT         | JSON array of typed blocks (see § 7.1, Call 0b output). **Mutable** — when Agent 4 rewrites a paragraph (§ 7.1 Call 4), the orchestrator overwrites the corresponding `paragraph` block's `text` field in this column before continuing the branch. The blocks structure (order, types, scene_index values) never changes after run creation; only individual paragraph `text` values do. |
| `style_guide_json`  | TEXT         | JSON; populated at run creation (no longer null)            |
| `illustration_count`| INTEGER      | Final count after Agent 0b (always exactly 5, per § 7.1)    |
| `completed_count`   | INTEGER      | Successful illustrations                                    |
| `failed_count`      | INTEGER      | Definitively failed illustrations                           |
| `error_code`        | TEXT NULL    | Machine-readable failure tag; see § 8.6                     |
| `error_message`     | TEXT NULL    | Human-readable technical detail (English)                   |

Note: the legacy `story_text` column is removed. The full prose lives in
`story_blocks_json` as `paragraph` blocks. The legacy `NO_SUITABLE_SCENES`
error_code is also removed from runs — that scenario cannot occur after the
new flow, since Agent 0b is producing both the story and its scenes (see
§ 7.1 Call 0b output rules).

### `illustrations`

| Column                   | Type         | Notes                                                                     |
|--------------------------|--------------|---------------------------------------------------------------------------|
| `id`                     | TEXT (UUID4) | Primary key                                                               |
| `run_id`                 | TEXT FK      | → `runs.id`                                                               |
| `scene_index`            | INTEGER      | 0..(illustration_count-1)                                                 |
| `scene_excerpt`          | TEXT         | The passage of the generated story this scene depicts. **Mutable** — Agent 4 (§ 7.1 Call 4) returns a new excerpt together with its rewritten paragraph; the orchestrator overwrites this column with the new excerpt before continuing the branch. The new excerpt is always a verbatim substring of the new paragraph text (re-validated server-side, same rule as Agent 0b). |
| `character_role`         | TEXT (enum)  | `male` / `female` / `mother` — drives MHA character + LoRA selection      |
| `paragraph_index`        | INTEGER      | 0-based index of the paragraph block (among the paragraph subset of `runs.story_blocks_json`) that this illustration is bound to — i.e. the paragraph block sitting immediately before the matching `illustration` block in document order. Persisted at run creation so the orchestrator and the frontend agree on which paragraph Agent 4 rewrites, independently of any later text changes. |
| `initial_concept`        | TEXT         | The concept from Agent 0b; never mutated                                  |
| `current_concept`        | TEXT         | Current concept (changes on concept restart)                              |
| `state`                  | TEXT (enum)  | See § 6 state values                                                      |
| `concept_attempt`        | INTEGER      | 1..3                                                                      |
| `prompt_attempt`         | INTEGER      | 1..3                                                                      |
| `current_prompts_json`   | TEXT NULL    | Last-used prompts (for debugging/visibility)                              |
| `last_verdict_json`      | TEXT NULL    | Last Claude verdict (for debugging/visibility)                            |
| `image_path`             | TEXT NULL    | Relative path under `OUTPUT_DIR`, e.g. `runs/<run_id>/scene_0.png`        |
| `companion_description`  | TEXT NULL    | The companion's `description` from Agent 0b (or Agent 4 after a rewrite), or NULL if no companion. **Mutable** — Agent 4 may set, change, or clear this. |
| `companion_interaction`  | TEXT NULL    | The companion's `interaction` from Agent 0b (or Agent 4), or NULL. **Mutable** — same as above. |
| `error_message`          | TEXT NULL    | Set on terminal failure                                                   |
| `created_at`             | DATETIME     |                                                                           |
| `updated_at`             | DATETIME     |                                                                           |

---

## 6. Illustration State Machine

(Unchanged from previous spec.)

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
        # Agent 4 returns a new concept AND a rewritten paragraph + new
        # excerpt (§ 7.1 Call 4). The orchestrator:
        #   1. validates the new excerpt is a verbatim substring of the
        #      new paragraph;
        #   2. validates that any non-null companion belongs to the
        #      brief's companions pool (§ 7.1 Call 4 rule #7);
        #   3. overwrites runs.story_blocks_json[paragraph_index].text;
        #   4. overwrites illustrations.scene_excerpt;
        #   5. emits SSE paragraph_updated{paragraph_index, text};
        #   6. updates current_concept;
        #   7. overwrites illustrations.companion_description and
        #      illustrations.companion_interaction when the new
        #      companion differs from the previous (including any
        #      transition to/from null); emits SSE
        #      illustration_companion_updated in that case.
        (current_concept, new_paragraph_text, new_scene_excerpt, new_companion) =
            claude.rethink_concept(
                full_story_text=<latest joined paragraph blocks>,
                current_paragraph_text=<latest paragraph at paragraph_index>,
                scene_excerpt=<current excerpt>,
                current_companion=<current illustrations.companion_*>,
                companions_pool=<sessions.collected_brief.companions>,
                failed_concept=<previous current_concept>,
                verdict=<last verdict>,
                style_guide=...,
                character_role=...,
            )
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

### 7.1 Anthropic Messages API (6 distinct calls)

All calls use `claude-sonnet-4-6`. Each agent's full system prompt lives
in a Markdown file under `backend/app/agents/` and is loaded at startup
by `services/claude.py` (see § 7.4). The Pydantic schemas below are the
binding wire contracts; the prose in each agent's `.md` file must produce
output that validates against the corresponding schema.

Strict JSON-only output is enforced for **Calls 0b through 4** via the
system prompt; **Call 0a (chat) returns a JSON envelope whose `reply`
field is free-form Slovak chat text** — see Call 0a below. Every JSON
response is validated with Pydantic, with up to `CLAUDE_JSON_RETRY` (= 2)
re-prompts on parse failure before treating it as an error.

For the `evaluate_image` call, the image is passed as a base64 image block
alongside the text content.

#### Call 0a — `chat` (Agent 0a, "the assistant")

**Purpose:** Conversational gathering of the story brief: the cast (subject
to § 7.3.2) and the overall topic/concept. Detects when enough has been
agreed, proposes a summary, and detects the user's natural-language
confirmation.

**Input (to Claude):**
- The full system prompt from `agents/chat.md`.
- The full prior message transcript of the session, mapped to Claude
  `messages` (the initial Slovak `intro` assistant message is included
  as the first `assistant` turn so the model sees what the user has
  read).
- The freshly POSTed user message as the last `user` turn.

**Output schema:**
```json
{
  "reply": "string (Slovak chat reply, free-form prose)",
  "phase": "gathering" | "awaiting_confirmation" | "confirmed",
  "collected_brief": {
    "characters": [
      { "role": "male" | "female" | "mother", "name_in_story": "string", "short_description": "string" }
    ],
    "companions": [
      { "description": "string (concrete English description of one allowed non-human entity)" }
    ],
    "topic": "string (1–2 sentence summary of the agreed concept)",
    "notes": "string (anything else the user emphasized that should shape the story)"
  } | null
}
```

Rules:

- `phase="gathering"` — assistant still needs more or clearer input. `reply`
  contains the assistant's next chat turn (a question, clarification request,
  or gentle push-back). `collected_brief` is `null`.
- `phase="awaiting_confirmation"` — the assistant has enough to summarize.
  `reply` contains a short human-language summary of what's been agreed
  followed by an explicit ask for the user's approval. `collected_brief` is
  fully populated.
- `phase="confirmed"` — the assistant recognized the user's most recent
  message as approval of the previously proposed summary. `collected_brief`
  is the brief that the user approved (carried forward from the previous
  turn).

  **`reply` is a fixed, deterministic Slovak string** (constant
  `CONFIRMED_ACK_SK` in `backend/app/constants.py`, value:
  `"Skvelé, ide na to. Pripravujem príbeh a ilustrácie…"`). The system
  prompt instructs Agent 0a to use exactly this string on confirmation
  turns, and the server normalizes any close-but-not-identical reply
  back to this constant before persisting / returning, so the frontend
  can safely identify a confirmation turn purely by `phase` without
  having to interpret free-form prose. This is what the frontend keys
  off to auto-start the pipeline (§ 9.1 Screen A): `phase` is a
  categorical machine marker; `reply` is only displayed verbatim in
  the chat thread.

Hard rules enforced by the prompt (and re-checked server-side):

1. **Character constraint.** `collected_brief.characters` may contain **at
   most one** `male`, **at most one** `female`, and **optionally one**
   `mother`. The `mother` role is permitted only when there is also at
   least one of `male` or `female` (she belongs to the main character).
   No other roles are permitted. If the user proposes additional or
   disallowed characters, the assistant must stay in `gathering` and push
   back politely, explaining the demo constraint.
2. **At least one main character.** A valid brief contains at least one
   of `male` or `female`.
3. **Topic present.** `collected_brief.topic` must be non-empty.
4. **No silent confirmation.** The assistant must not jump from `gathering`
   directly to `confirmed`. A confirmed turn must be preceded (in the same
   session) by at least one `awaiting_confirmation` turn, and the latest
   user message must be a plausible affirmative answer (e.g. "áno", "ok",
   "súhlasím", "do toho", "poďme na to"). If the user's reply is
   ambiguous, the assistant must stay in `awaiting_confirmation` and ask
   for a clearer yes/no.
5. **No story output here.** Agent 0a must not write the final story or
   list any scene concepts. That is Agent 0b's job. Its `reply` may
   discuss themes and tone with the user, but must not deliver the
   finished narrative.
6. **Companion pool size.** `collected_brief.companions` may contain
   **at most 2** entries. An empty array (the default) means the story
   has no companions. Agent 0a must not push the user toward companions
   — it only captures them if the user volunteers the idea or
   explicitly agrees when asked.
7. **Companion shape.** Each entry has a non-empty, visualizable
   `description`. Agent 0a nudges the user toward concrete descriptions
   ("a small black cat" not "an animal") before moving to
   `awaiting_confirmation`.
8. **Non-humanoid only.** A companion must have a body plan
   fundamentally different from humans — quadrupeds, winged creatures,
   serpents, mechanical entities without human form factor, etc.
   Anthropomorphic / humanoid creatures (cat-girls, elf-like beings,
   humanoid androids with human faces, etc.) are forbidden and treated
   as humans for scope purposes. Agent 0a refuses such companions and
   stays in `gathering` until the user proposes a non-humanoid one or
   drops the idea.
9. **No companions without a human main character.** Companions belong
   to a human; the prerequisite from rule #2 (at least one of `male` or
   `female`) still applies before any companion can be accepted.

Server-side guard: if the validated response is `phase="confirmed"` but
no `awaiting_confirmation` turn exists in the session history, the backend
overrides the response to `phase="awaiting_confirmation"` (best-effort
recovery) before storing or returning it.

#### Call 0b — `build_story` (Agent 0b, "the storyteller")

**Purpose:** Take the confirmed brief from Agent 0a and produce the final
short story together with the illustration concepts. This is the single
authoritative call that defines a run's content.

**Input:** the validated `collected_brief` from Agent 0a (as JSON in the
user turn).

**Output schema:**
```json
{
  "story": {
    "title": "string",
    "blocks": [
      { "type": "paragraph", "text": "string" },
      { "type": "illustration", "scene_index": 0 }
    ]
  },
  "style_guide": {
    "overall_style_positive": "string",
    "overall_style_negative": "string",
    "character_lora": "string (may be empty; render-time LoRA comes from character_config)",
    "character_baseline_description": "string"
  },
  "illustrations": [
    {
      "scene_index": 0,
      "scene_excerpt": "string (verbatim slice of the story prose this illustration depicts)",
      "concept": "string",
      "character_role": "male" | "female" | "mother",
      "companion": {
        "description": "string (must match — case-insensitive substring or exact — one description from collected_brief.companions)",
        "interaction": "string (concrete visual relationship in this scene)"
      } | null
    }
  ]
}
```

Hard rules enforced by the prompt and re-checked server-side:

1. **Block order and well-formedness.** `story.blocks` is an ordered list
   that begins with a `paragraph`, ends with a `paragraph`, and contains
   exactly `illustrations.length` blocks of type `illustration`. Each
   `illustration` block's `scene_index` matches a row in `illustrations`
   exactly once, and the order of `scene_index` values across the blocks
   is `0, 1, 2, …`.
2. **No `illustration` block adjacent to another `illustration` block.**
   Two consecutive illustration blocks are rejected.
3. **scene_excerpt is a verbatim substring** of the concatenation of all
   `paragraph` blocks' text. The backend verifies this with a substring
   check (whitespace-tolerant) and re-prompts on failure.
4. **Exact count.** `illustrations.length` MUST equal
   `MAX_ILLUSTRATIONS` (5). Any other length — including 1, 2, 3, 4, or
   6+ — is rejected server-side and triggers `CLAUDE_JSON_RETRY`
   re-prompts; if the agent still cannot return exactly 5 after retries,
   finalize ends with `STORY_BUILD_FAILED`. The agent's system prompt
   states this rule explicitly so it plans the story arc around 5
   illustration beats from the start.
5. **Cast.** Every `character_role` used in `illustrations` must
   correspond to a character present in the approved brief. If the brief
   has no `mother`, no illustration may have `character_role="mother"`.
6. **Single-character scenes** (§ 7.3.3) and **specificity of expression /
   gesture / action** (§ 7.3.4) apply — each `concept` must explicitly
   mention at least one concrete facial expression, gesture/posture, or
   action.
7. **Story-design discipline** (§ 7.3.9) — the story must be deliberately
   built around scenes that are illustratable under the MVP's hard
   technical constraints (single human character optionally accompanied
   by one non-human companion, simple ComfyUI workflow with no regional
   prompting or inpainting, naturally-varied environments per scene).
8. **Companion pool fidelity.** If `companion` is set on an illustration,
   its `description` MUST come from the brief's `companions` pool
   (whitespace-tolerant, case-insensitive substring or exact match). The
   server re-checks this on receipt and re-prompts on failure. Agent 0b
   must not invent new companion types.
9. **Companion cadence is a story-design choice.** Agent 0b decides which
   of the 5 scenes feature a companion. There is no required minimum
   or maximum beyond "each scene has at most one companion." When the
   brief's `companions` pool is empty, every illustration's `companion`
   field MUST be `null`. Agent 0b should use companions meaningfully
   (when their presence adds emotional weight) rather than
   decoratively — see § 7.3.9 principle 8.
10. **`interaction` specificity.** When `companion` is set, its
    `interaction` text must describe a visualizable spatial or
    behavioral relationship (`held in lap`, `perched on shoulder`,
    `walking beside her`). Vague phrasing (`there with him`) is
    rejected.
11. **No companion in scenes requiring hand-object precision.** This
    complements § 7.3.9 principle 4. If a scene's `concept` pushes the
    hand-object precision envelope (e.g., character pouring water,
    picking up a coin, holding something delicate), Agent 0b must not
    additionally place a companion that compounds the difficulty.

Unlike the previous spec, Agent 0b **does not** have a "no suitable
scenes" escape hatch. The brief has already been negotiated and confirmed
in Call 0a; the storyteller's job is to deliver. Output that violates the
hard rules above is treated as a Claude failure (`STORY_BUILD_FAILED`).

#### Call 1 — `generate_prompts`

**Input:** `current_concept`, `style_guide`, `character_role` (so the
prompt can pull the right entry from `character_config`), and the
optional `companion` (`{ description, interaction } | null`) attached
to the illustration. When `companion` is non-null the agent must
incorporate it per § 7.3.10 (companion prompting guidance) and apply
the conditional adjustments to the negative baseline described in
§ 7.3.6.

**Output schema:**
```json
{
  "positive": "string",
  "negative": "string"
}
```

The `positive` field is the full per-scene positive prompt (character +
environment + action + expression + companion if any, all expressed as
Danbooru tags). The `negative` field is the full per-scene negative
prompt. Style-level tags are NOT included here — they live in
`style_guide` and are composed in by the workflow itself (see § 7.2).
See § 7.3.4 and § 7.3.10 for the content requirements that this prompt
must satisfy.

#### Call 2 — `evaluate_image`

**Input:** image (base64), `current_concept`, `style_guide`,
`character_role`, and the illustration's `companion` (`{ description,
interaction } | null`). The agent's checklist is companion-aware
(§ 7.3.5 items 1a + 1b).

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

**Input:** current `prompts`, last `verdict`, `current_concept`,
`style_guide`, `character_role`, and the illustration's `companion`
(`{ description, interaction } | null`). When `companion` is non-null
the same companion guidance applies as in Call 1 (§ 7.3.10 + the
§ 7.3.6 conditional negative adjustments).

**Output schema:** same as Call 1.

#### Call 4 — `rethink_concept`

Agent 4's job is broader than in the previous spec. It is no longer
restricted to finding a different visual angle on the same paragraph; it
is allowed (and required) to **rewrite the paragraph itself** so the new
visual concept lands on a story beat the renderer can actually depict.
The narrative arc, flow, and logic of the story must be preserved — the
new paragraph is a functional substitute for the old one — but the
particular *moment* the paragraph crystallizes can change as needed.

**Input (to Claude):**

- `current_concept` — the concept that just failed.
- `verdict_reasoning`, `verdict_suggestion` — last evaluator verdict.
- `failed_concept` — alias of `current_concept`, named explicitly so the
  prompt can reference it as the thing to move away from.
- `full_story_text` — the **current** full story prose, produced by
  joining the `text` fields of every `paragraph` block in
  `runs.story_blocks_json` in document order with single blank lines
  between them. This reflects the latest state of the story including
  any prior Agent 4 rewrites in other branches; the orchestrator reads
  `runs.story_blocks_json` from the DB at the moment of the call.
- `current_paragraph_text` — the **current** text of the paragraph this
  illustration is bound to (the paragraph at
  `illustrations.paragraph_index`).
- `paragraph_index` — same value, passed for the agent's situational
  awareness so it can speak about "the third paragraph" if useful.
- `scene_excerpt` — the current excerpt within `current_paragraph_text`.
- `style_guide`, `character_role`, `character_display` — unchanged from
  before; used so the new concept and the new paragraph stay consistent
  with the global visual continuity and the cast vocabulary.
- `current_companion` — the illustration's current companion
  (`{ description, interaction } | null`).
- `companions_pool` — the brief's full `companions` pool (list of
  `{ description }` entries) so Agent 4 knows which companions, if any,
  it may select from.

**Output schema:**
```json
{
  "concept": "string (a meaningfully different visual concept)",
  "paragraph_text": "string (the rewritten Slovak paragraph that replaces current_paragraph_text)",
  "scene_excerpt": "string (a verbatim substring of paragraph_text — the new excerpt this concept depicts)",
  "companion": {
    "description": "string (must match an entry in companions_pool)",
    "interaction": "string (concrete visual relationship in the new scene)"
  } | null
}
```

Hard rules enforced by the prompt and re-checked server-side:

1. **Functional equivalence of the paragraph.** `paragraph_text` must
   replace `current_paragraph_text` in place inside `full_story_text`
   without disrupting:
   - the linearity and logic of the story arc,
   - the smoothness of the transition from the **preceding** paragraph
     into this one,
   - the smoothness of the transition from this paragraph into the
     **following** one.
   Re-read the surrounding paragraphs and write a substitute that
   slots in cleanly. Same Slovak voice and register as the rest of the
   story (the persona-fragment shared with Agent 0b applies here too —
   see § 7.4).
2. **New concept addresses the failure.** The new `concept` must
   deliberately avoid the failure mode described in `verdict_reasoning`
   / `verdict_suggestion`. If the verdict said "two hands too close to
   the mug caused fused fingers", the new concept must not put a hand
   near a mug; ideally it changes the action entirely.
3. **Excerpt validity.** `scene_excerpt` MUST be a verbatim substring
   of the returned `paragraph_text` (whitespace-tolerant). The server
   re-checks this and re-prompts on failure (same validator path used
   by Agent 0b).
4. **All Agent 0b story-design principles still apply (§ 7.3.9).** In
   particular: single-character moment, concrete depictability
   (named expression / gesture / action), no regional prompting / no
   inpainting, no legible small objects or text in frame. The cast
   constraint (§ 7.3.2) is preserved — the character_role does not
   change. The system prompt of `rethink_concept.md` embeds the same
   directives as `build_story.md` so the agent obeys them in identical
   form (§ 7.4).
5. **Out-of-band side effects.** Agent 4 must not change anything else
   — it does not return a different `character_role`, does not invent
   new characters, does not propose changing the story title, and does
   not propose changes to other paragraphs. Its scope is exactly: one
   paragraph, one concept, one excerpt, optionally one companion.
6. **Companion-aware rethinking.** Agent 4 may keep, drop, or swap the
   scene's companion when rewriting:
   - Dropping (`companion: null`) is the natural choice when the
     evaluator's failure mode was companion-related (e.g. "cat anatomy
     fails").
   - Swapping is the natural choice when the brief lists more than one
     allowed companion and a different one fits the new beat better.
   - Keeping (returning the same description / interaction) is fine
     when the failure was unrelated to the companion.
7. **Pool fidelity (same as Agent 0b).** Any non-null `companion`
   returned by Agent 4 must reference an entry in the run's saved
   `collected_brief.companions` pool (whitespace-tolerant,
   case-insensitive substring or exact match). The persisted brief is
   read from `sessions.collected_brief_json` via the
   `runs.session_id` foreign key. The server re-checks this and
   re-prompts on failure (same validator path used by Agent 0b
   rule #8).
8. **No invention.** Agent 4 must not introduce a companion type that
   was not in the brief, even if it seems to help.

If the validated response violates any rule above, the server treats
that as a Claude failure and re-prompts up to `CLAUDE_JSON_RETRY` (= 2)
times. After that the branch ends as if Agent 4 returned nothing useful
— concept_attempt exhaustion behavior (§ 6 loop semantics) takes over.

The orchestrator persists the returned companion (if any) into
`illustrations.companion_description` and `illustrations.companion_interaction`
at the same time it overwrites the paragraph text, scene excerpt, and
current concept. When the new companion differs from the previous
(including any change to/from null), the orchestrator additionally
emits an `illustration_companion_updated` SSE event (§ 8.4). No event
is emitted when the companion is unchanged.

### 7.2 RunPod ComfyUI Serverless

(Unchanged from previous spec.)

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
| `STYLE_POSITIVE_PROMPT`         | Call 0b → `style_guide.overall_style_positive` |
| `STYLE_NEGATIVE_PROMPT`         | Call 0b → `style_guide.overall_style_negative` |

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

This section defines the creative and prompting conventions that all six
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
character role (`male`, `female`, `mother`) maps to a fixed MHA character
reference used in prompts:

| `character_role` | Character used in prompts                |
|------------------|------------------------------------------|
| `male`           | Izuku Midoriya (use as boy/man archetype)|
| `female`         | Kyoka Jiro (use as girl/woman archetype) |
| `mother`         | Inko Midoriya                            |

This mapping is the *single source of truth* for character identity in
prompts. Agents 1 and 3 must always use these names (plus their canonical
trigger words and visual descriptors) regardless of the names the user
chose during the chat (`name_in_story`). The user-chosen names are
narrative only — they appear in the story prose written by Agent 0b but
are never sent to ComfyUI.

The roster the user is allowed to assemble during the chat is constrained
by the same vocabulary: at most one `male`, at most one `female`, and
optionally one `mother`, with `mother` only allowed when at least one of
`male` / `female` is also present. Agent 0a enforces this during
gathering (§ 7.1, Call 0a).

The mapping lives in `backend/app/constants.py` as a dictionary so that
non-prompt code can also reference it. Trigger words and baseline visual
descriptors for each character are loaded from configuration (see
§ 7.3.7).

#### 7.3.3 Scene composition constraint (MVP)

Each illustration depicts exactly one of the three permitted human
character roles, optionally accompanied by exactly one non-human,
non-anthropomorphic companion drawn from the run's brief pool. Scenes
with multiple human characters, group scenes, crowds, scenes with
multiple non-human entities visible, and scenes with no clear
character focus are excluded.

A non-human companion has a body plan fundamentally different from
humans — quadrupeds, winged creatures, serpents, mechanical entities
without human form factor, etc. Anthropomorphic / humanoid beings
(cat-girls, elf-like beings, humanoid androids with human faces, etc.)
are treated as a *second human* and therefore forbidden.

Because Agent 0b is **constructing** the story together with its scenes
(rather than mining a pre-existing text), it is responsible for
arranging the narrative so that every illustration point satisfies this
constraint. There is still no "no suitable scenes" escape hatch — the
brief was negotiated and confirmed before Agent 0b ran, so satisfying
this constraint is part of Agent 0b's success criteria.

#### 7.3.4 Expression, gesture, and action — mandatory specificity

Since every scene depicts a single character alone, the illustration's
expressiveness depends entirely on what that character is *doing* and
*feeling*. Generic standing poses and ambiguous expressions are not
acceptable.

Agent 0b must construct scenes where the character's emotional state,
gesture, posture, or activity is concrete and depictable. Each `concept`
field must explicitly mention at least one of:

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

When `companion` is present on the illustration, the mandatory
specificity applies to both the human and the human-companion
interaction. The `concept` field must still describe a concrete human
expression / gesture / action, and the `interaction` field must
independently describe a concrete spatial or behavioral relationship
between the human and the companion.

#### 7.3.5 Agent 2 evaluation checklist

Agent 2 (`evaluate_image`) judges each rendered image against this
checklist. The image is `ok` only when **all** of the following hold:

1a. **Exactly one human character is visible.** Multiple visible humans
    → `problem="prompt"`.
1b. **Companion alignment.** If `companion` was specified for this
    illustration, exactly one non-human entity matching the description
    is visible, positioned consistently with the `interaction` field.
    Missing companion → `problem="prompt"`. Multiple companions of the
    same type appearing → `problem="prompt"`. Wrong type of companion
    rendered → `problem="prompt"`. If `companion` was *not* specified
    and a non-human entity nevertheless appears prominently → also
    `problem="prompt"` (Agent 0b did not plan one). A small, peripheral
    non-human element that does not distract is tolerated.
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

**Conditional adjustments when `companion` is present** (Agents 1 and 3
apply these on top of the baseline above when the illustration carries
a non-null `companion`):

- **Do not include** `solo` in the *positive* prompt. The Danbooru `solo`
  tag means "only one entity in the image" and conflicts with the
  companion's presence.
- **Keep the multi-character negatives** (`multiple characters`, `crowd`,
  `two girls`, `two boys`, `2girls`, `2boys`, `group`) — they refer to
  humans.
- **Add anti-duplicate negatives for the companion type.** If the
  companion is a cat, add `2cats, multiple cats` to negatives; if a
  dragon, `2dragons, multiple dragons`; etc. Pattern: one extra clause
  forbidding duplication of the *specific* companion present, derived
  from the companion description.
- **Do not include anti-creature tags.** Phrases like `no animals`,
  `no creatures`, `no pets` must not appear in the negative when a
  companion is present.
- **Do not use "focus" tags** (`animal focus`, `cat focus`, etc.).
  These tags suppress the human and push the non-human into the
  primary subject role, which inverts the composition we want.

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

Agent 0b's `style_guide` output covers global, illustration-wide concerns:

- `overall_style_positive`: anime/MHA style tags applied to every image,
  e.g. `mha style, anime, manga illustration, soft shading, clean
  linework`. Composed with the per-illustration prompts in the workflow.
- `overall_style_negative`: global negatives layered on top of the
  baseline (§ 7.3.6), e.g. `realistic, photo, 3d, western cartoon`.
- `character_lora`: ignored at render time in MVP (see § 7.3.7). May be
  left empty or set to a placeholder by Agent 0b; the rendering pipeline
  takes the actual LoRA from `character_config`.
- `character_baseline_description`: a free-text English description of
  the visual continuity intended across all illustrations of this run
  (e.g., "All scenes share warm afternoon lighting and a storybook-like
  framing"). Agents 1 and 3 reference this when constructing prompts.

The style LoRA applies globally to every visible entity in the frame,
including any companion. This is the desired behavior (consistent look)
but worth stating so reviewers do not flag it as a gap. See § 7.3.10
for the "style LoRA caveat" describing the known limitation when the
style LoRA dominates non-human rendering.

#### 7.3.9 Story-design principles (Agent 0b)

Because the story is being authored *for* the illustrator (not the other
way around), Agent 0b consciously trades off user intent against the
app's purpose — which is to demonstrate AI's ability to **illustrate**
short stories beautifully. The story must therefore be deliberately
designed so that every illustration point falls within the narrow
technical window where Agent 1's prompt and the ComfyUI workflow can
produce a striking result. The following principles are normative and
override any user wish that contradicts them (Agent 0b should honor user
intent in *theme*, *tone*, and *emotional arc*, not in scene mechanics
that violate these rules).

1. **Psychological framing.** The intended viewer experience is to step
   into the *inner emotional* world of a single character — not their
   imagination, but their feelings. Scenes are emotional snapshots, not
   action set-pieces. Quiet, charged moments are preferred over busy ones.
2. **Single-human moments, with optional non-human companion.** Every
   illustration point is a beat where exactly one of the three permitted
   human roles is on the page, optionally accompanied by exactly one
   non-human companion from the brief's pool. Other characters can be
   present in the prose between illustrations, but the illustrated
   moments isolate the single human (plus, optionally, the companion).
3. **Concrete depictability.** Every illustrated moment carries an
   explicit facial expression, gesture/posture, or action that can be
   rendered as a Danbooru tag (see § 7.3.4). Abstract or symbolic
   moments are not chosen as illustration points.
4. **No regional prompting, no inpainting.** The MVP workflow renders a
   single subject in a single pass. Scenes must not require composition
   that depends on regional prompting, multi-pass, or inpainting fixes:
   no held objects that interact precisely with the character's hands in
   ways SDXL famously fails, no scenes that hinge on multiple precisely-
   placed elements, no text that must be legible in the image.
5. **Naturally varying environments.** Each illustrated moment takes
   place in a *different* (at least subtly different) setting. This
   side-steps the absence of cross-scene background consistency: with no
   two backgrounds being the same, the viewer never expects them to be
   the same. The story must motivate these scene-to-scene environment
   changes plausibly (the character moves rooms, walks outside, time
   passes, the weather changes) so they feel inevitable, not engineered.
6. **Right-sized.** The story is written for exactly the number of
   illustrations it contains (between 1 and `MAX_ILLUSTRATIONS`). It is
   short enough to be read in one sitting and not denser than the
   illustration cadence can support.
7. **User intent honored where possible.** Within the constraints above,
   the agreed brief (cast names, topic, tone, notes from the chat) is
   carried into the prose. If a wish from the brief is incompatible with
   the constraints, Agent 0b silently reshapes it rather than asking
   again (the chat phase is over by the time Agent 0b runs). It must not
   produce a story that breaks the constraints to satisfy a wish.
8. **Companions earn their presence.** A companion in a scene must add
   emotional or compositional weight to that beat (the character pets
   the cat for comfort; the dragon perches watchfully on the boy's
   shoulder; the robot stands beside her as she decides). A companion
   that is simply "in the room" for decoration is worse than no
   companion — it dilutes the human's prominence without serving the
   story. If a scene works without a companion, do not add one.

These eight principles apply unchanged to **Agent 4** when it rewrites a
paragraph at concept-restart time (§ 7.1 Call 4). Agent 4 receives the
full current story so it can keep the substitute paragraph consistent
with the arc, the cast, and the neighbouring scenes. The single
additional constraint it has — and that Agent 0b does not — is that the
shape of the story (number of paragraphs, number of illustrations,
their ordering) is fixed at run creation and must not be altered.

#### 7.3.10 Companion prompting guidance

Generic principles that Agents 1 and 3 follow when the illustration's
`companion` field is non-null. **These principles apply regardless of
the kind of non-human entity** — there are no entity-specific code
paths anywhere in the implementation. All non-human handling is driven
by the free-text `description` and category reasoning inside the agent
prompts.

- **Numeric tagging.** Use Danbooru-style numeric tags for the companion
  where applicable (`1cat`, `1dog`, `1dragon`, `1robot`). The human is
  still tagged with its `1girl` / `1boy` form per role. Do not use
  `solo` when a companion is present.
- **Interaction tagging.** Translate the `interaction` field into
  concrete Danbooru-style interaction tags. Examples of the *form*
  expected (not prescribing specific entities): `holding X`,
  `X on shoulder`, `X in lap`, `riding X`, `petting X`, `X beside her`,
  `X behind him`, `X looking up at her`.
- **Size and prominence.** If the companion should be a meaningful
  visual element rather than peripheral background, include explicit
  size or prominence tags (`large X`, `X fills frame`, `close-up on X
  and her`, `full body shown`). Without these the model often renders
  the companion small and in a corner. Conversely, if the companion is
  supposed to be peripheral, no extra emphasis is needed.
- **Non-human anatomy negatives.** Non-human anatomy is less reliably
  rendered than human anatomy. The agent derives appropriate negatives
  from the companion's body plan rather than from its specific
  identity:
  - For four-legged creatures: `extra legs, missing legs, malformed paws`.
  - For winged creatures: `deformed wings, asymmetric wings, broken wings`.
  - For mechanical entities: `bad mechanical design, malformed limbs,
    asymmetric mechanical parts`.
  - For serpentine creatures: `extra heads, broken body, segmented incorrectly`.

  The Agent 1 / Agent 3 system prompts include this as guidance — the
  agent decides which category applies based on the
  `companion.description` text. This is generic reasoning, not a
  hardcoded lookup table.
- **Style LoRA caveat.** When companion rendering looks "off" (e.g.,
  a cat with anime-girl-like eyes due to the style LoRA dominating),
  the style LoRA may need to be slightly reduced for that illustration.
  This is not auto-tuned by the agents in MVP — it is a known
  limitation. A future iteration may add a per-illustration style
  weight override; for MVP we accept the default.

### 7.4 Agent prompt files

Each Claude agent's system prompt lives in its own Markdown file under
`backend/app/agents/`. There are six files, one per call in § 7.1:

| File                  | Agent | Call name           |
|-----------------------|-------|---------------------|
| `chat.md`             | 0a    | `chat`              |
| `build_story.md`      | 0b    | `build_story`       |
| `generate_prompts.md` | 1     | `generate_prompts`  |
| `evaluate_image.md`   | 2     | `evaluate_image`    |
| `revise_prompts.md`   | 3     | `revise_prompts`    |
| `rethink_concept.md`  | 4     | `rethink_concept`   |

Loading rules:

- `services/claude.py` reads all six files at process startup and caches
  their contents in memory. The contents are used verbatim as the
  Anthropic `system` parameter for the corresponding call. No template
  substitution is applied to the prompt body; runtime context (the
  current concept, the brief, the last verdict, etc.) is passed as
  structured JSON inside the `messages` user turn, not interpolated into
  the system prompt.
- The startup loader fails fast with a clear error if any file is
  missing, empty, or unreadable. This is treated the same way as a
  missing required `.env` value.
- The directory is configurable via the `AGENTS_DIR` env var (default
  `./app/agents`) so tests can point at a fixture directory containing
  alternative prompts.
- Editing a `.md` file requires a process restart to take effect (no hot
  reload in MVP).

Each `.md` file is structured for human editing — it should be readable
end-to-end and contain at minimum:

1. A one-line role statement ("You are Agent X, …").
2. The agent's responsibilities and constraints, in plain English.
3. References to the relevant § 7.3 subsections that govern its output.
4. The exact output schema the model must emit (as a fenced JSON block),
   matching the Pydantic schema in § 7.1.
5. For Agent 0a only: an explicit reminder that `reply` is Slovak prose
   and must not contain JSON, headings, or scene lists.
6. For Agents 0b through 4: an explicit reminder that the only output is
   the JSON object — no Markdown fences, no prefatory text, no trailing
   commentary.

Agents 0a and 0b share a short persona-fragment ("the assistant's voice")
that is embedded into each file's text (copy-pasted, not imported) so
that the user experiences a consistent voice across the chat and the
generated story's narration. **Agent 4 (`rethink_concept.md`) embeds the
same persona-fragment and the full Story-design principles block
verbatim from `build_story.md`** (copy-pasted into the file, not
imported at runtime) — because Agent 4 is now also a story-writer when
it substitutes a paragraph (§ 7.1 Call 4). Editing the principles
therefore means editing both files; the agent prompt loader exercises
the same files at startup, so the discipline is purely an authoring
convention. A short comment block at the top of each principles section
in `rethink_concept.md` names `build_story.md` as the source-of-truth
sibling so future editors keep them in sync.

---

## 8. Backend API

All endpoints return JSON unless noted. CORS allows `ALLOWED_ORIGIN`.

The legacy `POST /api/runs` endpoint is **removed**. A run is created
internally as the result of finalizing a session (§ 8.2). Runs cannot be
created from arbitrary input text anymore.

### 8.1 Sessions — chat phase

#### `POST /api/sessions`

Start a new chat session with the user's very first message.

Request body:
```json
{ "content": "string (non-empty, max CHAT_MESSAGE_MAX_CHARS)" }
```

Behavior:
1. Create a `sessions` row with `state=CHATTING`.
2. Insert the welcome message (§ 9.2.1) as the first `session_messages`
   row (`role=assistant`, `phase=intro`).
3. Insert the user's message as the second row (`role=user`).
4. Synchronously invoke Agent 0a with the full transcript so far.
5. Persist the assistant reply (third row) with the returned `phase`.
6. If `phase=confirmed` against the rules in § 7.1 Call 0a, the server
   downgrades it (see § 7.1 Call 0a server-side guard).
7. If `phase=confirmed` (legitimately), the response still returns the
   acknowledgment reply; the client is expected to follow up with
   `POST /api/sessions/{id}/finalize` (§ 8.2). The backend does NOT
   auto-finalize.

Response 201:
```json
{
  "session_id": "uuid",
  "state": "CHATTING" | "AWAITING_CONFIRMATION" | "BUILDING_STORY",
  "messages": [
    { "id": "uuid", "order_index": 0, "role": "assistant", "phase": "intro", "content": "string", "created_at": "iso" },
    { "id": "uuid", "order_index": 1, "role": "user", "phase": null, "content": "string", "created_at": "iso" },
    { "id": "uuid", "order_index": 2, "role": "assistant", "phase": "gathering" | "awaiting_confirmation" | "confirmed", "content": "string", "created_at": "iso" }
  ]
}
```

Errors:
- 400 if `content` is empty or over `CHAT_MESSAGE_MAX_CHARS`.
- 502 if Agent 0a fails after retries (`error_code=CHAT_FAILED`).

After a successful response with `state=AWAITING_CONFIRMATION` the session
row is updated accordingly (the `awaiting_confirmation` phase on the
assistant message sets session `state=AWAITING_CONFIRMATION`).

#### `POST /api/sessions/{id}/messages`

Append a user message and get the assistant's reply.

Request body:
```json
{ "content": "string (non-empty, max CHAT_MESSAGE_MAX_CHARS)" }
```

Behavior: same as `POST /api/sessions` from step 3 onward (persist user
message, invoke Agent 0a, persist assistant reply, update session state).

Response 200:
```json
{
  "session_id": "uuid",
  "state": "CHATTING" | "AWAITING_CONFIRMATION" | "BUILDING_STORY",
  "user_message": { "id": "uuid", "order_index": N, "role": "user", "phase": null, "content": "string", "created_at": "iso" },
  "assistant_message": { "id": "uuid", "order_index": N+1, "role": "assistant", "phase": "gathering" | "awaiting_confirmation" | "confirmed", "content": "string", "created_at": "iso" }
}
```

Errors:
- 404 if session does not exist.
- 409 if session `state` is not `CHATTING` or `AWAITING_CONFIRMATION`
  (e.g. already `BUILDING_STORY`, `COMPLETED`, `FAILED`).
- 400 if `content` is empty or too long.
- 502 if Agent 0a fails after retries.

#### `GET /api/sessions/{id}`

Returns full session state and transcript. Used on reconnect / direct
navigation.

Response 200:
```json
{
  "session": {
    "id": "uuid",
    "state": "CHATTING|AWAITING_CONFIRMATION|BUILDING_STORY|COMPLETED|FAILED",
    "run_id": "uuid|null",
    "error_code": "string|null",
    "error_message": "string|null",
    "created_at": "iso",
    "updated_at": "iso"
  },
  "messages": [ { "id", "order_index", "role", "phase", "content", "created_at" } ]
}
```

### 8.2 Finalize — chat → run handoff

#### `POST /api/sessions/{id}/finalize`

Triggered by the frontend after the user has confirmed (i.e. after a
message exchange that landed on `state=AWAITING_CONFIRMATION` followed
by a user reply that produced an `assistant_message.phase=confirmed`).

Behavior (blocking):
1. Reject with 409 if session is not in a confirmable state. A
   confirmable session is one whose latest assistant message has
   `phase=confirmed`, and whose `state` is one of
   `AWAITING_CONFIRMATION` or `CHATTING` (the latter occurs because step
   2 below has not yet run).
2. Transition session to `state=BUILDING_STORY`.
3. Invoke Agent 0b synchronously with the brief stored on the session
   (the last validated `collected_brief`).
4. Validate the result against the schema and the hard rules in § 7.1
   Call 0b. On validation failure after retries: mark session
   `state=FAILED`, set `error_code=STORY_BUILD_FAILED`, respond 502.
5. Create a `runs` row in `status=RUNNING`, populated with
   `story_title`, `story_blocks_json`, `style_guide_json`,
   `illustration_count`. Create one `illustrations` row per scene in
   `state=PENDING`.
6. Schedule the per-illustration branches (§ 6) as a background task.
7. Update the session: `state=COMPLETED`, `run_id=<new run id>`.

Response 201:
```json
{ "run_id": "uuid" }
```

Errors:
- 404 if session does not exist.
- 409 if session is not in a confirmable state.
- 502 if Agent 0b fails after retries (`error_code=STORY_BUILD_FAILED`).
- 500 if any other unhandled exception occurs (`error_code=INTERNAL_ERROR`).

### 8.3 `GET /api/runs/{run_id}`

Returns a snapshot of the run and all its illustrations. Used by the
frontend on reconnect / direct navigation.

Response 200:
```json
{
  "run": {
    "id": "uuid",
    "session_id": "uuid",
    "status": "RUNNING|COMPLETED|FAILED|CANCELLED",
    "story_title": "string",
    "story_blocks": [
      { "type": "paragraph", "text": "string" },
      { "type": "illustration", "scene_index": 0 }
    ],
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
      "paragraph_index": 0,
      "character_role": "male|female|mother",
      "current_concept": "string",
      "state": "PENDING|...|COMPLETED|FAILED|CANCELLED",
      "concept_attempt": 1,
      "prompt_attempt": 1,
      "image_url": "string|null",
      "companion": { "description": "string", "interaction": "string" } | null
    }
  ]
}
```

`image_url` is `null` until completed, then `/static/runs/<run_id>/scene_N.png`.

`companion` reflects the current state of the illustration's
`companion_description` + `companion_interaction` columns. It is `null`
when the illustration has no companion; otherwise it carries both
fields. Like `scene_excerpt` and `story_blocks`, this value reflects
the latest state after any Agent 4 rewrites have been persisted.

`run.story_blocks` and `illustration.scene_excerpt` always reflect the
**current** content — i.e. the latest state after any Agent 4 paragraph
rewrites have been persisted (§ 5.3, § 5.4). Snapshot consumers
therefore never need to reconcile their local view by reapplying
historical `paragraph_updated` events; the snapshot is already up to
date.

`paragraph_index` is included so the frontend can locate the paragraph
block this illustration is bound to without walking the blocks array.
It is stable for the lifetime of the run — Agent 4 rewrites the
paragraph's `text`, never its position.

### 8.4 `GET /api/runs/{run_id}/events`  (SSE)

(Unchanged contract from previous spec; payload shape updated to match
§ 8.3.)

On connection, the server emits a synthetic `snapshot` event built from
current DB state (mirroring the shape of `GET /api/runs/{run_id}`), then
live events follow. The snapshot is rebuilt for every new subscriber so
reconnects always reflect the latest persisted state, not a stale earlier
view of the pipeline.

For a run in a terminal status (`COMPLETED` / `FAILED` / `CANCELLED`) whose
in-memory event bus is no longer active (e.g. after a server restart), the
endpoint still serves the `snapshot` followed by the matching terminal
event and closes the stream — so the run page remains viewable.

SSE event types (`event:` field) and JSON payloads:

| Event                       | Payload                                                                 |
|-----------------------------|-------------------------------------------------------------------------|
| `snapshot`                  | `{ "run": {...}, "illustrations": [...] }`                              |
| `illustration_state`        | `{ "illustration_id", "scene_index", "state", "concept_attempt", "prompt_attempt", "current_concept", "scene_excerpt" }` |
| `paragraph_updated`         | `{ "paragraph_index", "text" }`                                         |
| `illustration_companion_updated` | `{ "illustration_id", "scene_index", "companion": { "description", "interaction" } \| null }` |
| `illustration_completed`    | `{ "illustration_id", "scene_index", "image_url" }`                     |
| `illustration_failed`       | `{ "illustration_id", "scene_index", "error_message" }`                 |
| `run_completed`             | `{ "completed": N, "failed": M }`                                       |
| `run_failed`                | `{ "error_code": "string", "error_message": "string" }`                 |
| `run_cancelled`             | `{}`                                                                    |
| `heartbeat`                 | `{}` every 15 s to keep the connection alive                            |

The previous `style_guide_ready` event is removed: the style guide is
known at the moment the run is created (Agent 0b ran before
`POST /api/sessions/{id}/finalize` returned), so it is always present in
the initial `snapshot` and never needs a follow-up event.

`illustration_state.current_concept` carries the **currently active**
concept text for the illustration. It is emitted on every state
transition (not only on concept changes) so subscribers don't need
out-of-band reconciliation. In practice the field only meaningfully
*changes* when the branch loops through `RETHINKING_CONCEPT` and Agent 4
replaces the original concept with a new one; the frontend updates the
matching `IllustrationCard` text in place when it observes a new value
(see § 9.2.2).

`illustration_state.scene_excerpt` is included for the same reason —
Agent 4 can rewrite the paragraph and therefore the excerpt
(§ 7.1 Call 4). It is emitted on every state transition; subscribers
write it into the matching illustration object in place. Like
`current_concept`, the field only meaningfully *changes* across a
`RETHINKING_CONCEPT` cycle.

`paragraph_updated` is a new event emitted exactly once per successful
Agent 4 invocation, **after** the database has been updated with the
new paragraph text and before the corresponding `illustration_state`
event that flips the branch out of `RETHINKING_CONCEPT`. Its `text`
field carries the new full paragraph text; `paragraph_index` matches
`illustrations.paragraph_index` for the illustration that triggered the
rewrite. Subscribers replace `story_blocks[paragraph_block_at_index].text`
on the live `run` object in place — because Vue reactivity is
field-level, this re-renders the matching `StoryParagraph` component
without disturbing siblings. The order of paragraph blocks (and of all
blocks generally) is fixed and never broadcast (§ 5.3).

`illustration_companion_updated` is a new event emitted at most once
per successful Agent 4 invocation, **only when the companion actually
changed** (including any change to/from null). When Agent 4 returns the
same companion as before, no event is emitted. Subscribers replace the
matched illustration's `companion` field in place on the existing
reactive object; like the other in-place mutations, this triggers a
field-level re-render of the `IllustrationCard` without remount.

Per-Agent-4 ordering guarantee (one branch, one rethink cycle):

1. `illustration_state` — `state="RETHINKING_CONCEPT"`, fields still
   carry the *old* `current_concept` and `scene_excerpt` (the rethink
   hasn't happened yet on the server when this event is emitted).
2. `paragraph_updated` — the rewritten paragraph text, after server
   persistence.
3. `illustration_companion_updated` — emitted *only when* the
   companion changed, after server persistence.
4. `illustration_state` — `state="GENERATING_PROMPTS"`, fields carry
   the *new* `current_concept` and `scene_excerpt`.

The stream closes after `run_completed`, `run_failed`, or `run_cancelled`.

### 8.5 `POST /api/runs/{run_id}/cancel`

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

### 8.6 Error codes

The following `error_code` values are defined for MVP.

**Session-level** (`sessions.error_code`):

| `error_code`           | Meaning                                                                                          |
|------------------------|--------------------------------------------------------------------------------------------------|
| `CHAT_FAILED`          | Agent 0a failed (Claude error after retries, JSON parse failure, etc.).                          |
| `STORY_BUILD_FAILED`   | Agent 0b failed (Claude error after retries, schema violation, or hard-rule violation that re-prompts could not recover). |
| `INTERNAL_ERROR`       | Any other unhandled exception during session handling.                                            |

**Run-level** (`runs.error_code`):

| `error_code`           | Meaning                                                                                          |
|------------------------|--------------------------------------------------------------------------------------------------|
| `INTERNAL_ERROR`       | Any unhandled exception in the orchestrator after the run was already created.                   |

The previous run-level codes `NO_SUITABLE_SCENES` and `STEP0_FAILED` are
removed. Their replacement at the session layer is `STORY_BUILD_FAILED`
(both situations now manifest, if at all, while Agent 0b is being asked
to author a story — which fails before any run is ever created). The
frontend handles them on the chat screen, not the run screen.

### 8.7 Static file serving

`GET /static/runs/<run_id>/<filename>` serves files from `OUTPUT_DIR`. Use
FastAPI's `StaticFiles` mount.

### 8.8 Orchestrator failure handling

The background orchestrator runs inside an outer try/except block. Any
unhandled exception transitions the run to `status=FAILED` with both
`error_code=INTERNAL_ERROR` and `error_message` set, and emits a
`run_failed` SSE event before closing the stream.

Branch-level failures (a single illustration failing after all attempts)
do **not** trigger a run-level failure — the run completes as
`COMPLETED` with a non-zero `failed_count`. Only unhandled exceptions
take down the whole run.

---

## 9. Frontend

### 9.1 Screens

The frontend is a 2-screen SPA.

#### Screen A — Home (`/`)

**Purpose:** Chat with the virtual assistant (Agent 0a) to agree on a
story brief, then trigger story generation.

There is **no textarea for raw story input** on this screen. The single
input control is the chat composer at the bottom of the chat thread.

**Elements (top to bottom):**

1. **Header:** "Anime ilustrátor". A short subtitle: "Vytvor krátky
   ilustrovaný anime príbeh s pomocou asistenta."
2. **Chat thread** (`ChatThread`): a vertically scrolling list of
   `ChatMessage` items. Assistant messages are aligned left with the
   assistant's avatar; user messages are aligned right. The very first
   message is always the welcome message (see § 9.2.1) rendered with
   the `#word#` segments shown in **bold**.
3. **"Building story" placeholder:** while `session.state ===
   "BUILDING_STORY"`, the chat composer is replaced by an inline status
   strip: a spinner and the Slovak text "Pripravujem príbeh a
   ilustrácie...". The chat thread is read-only during this phase.
4. **Chat composer** (`ChatComposer`): a single-line auto-expanding
   `<textarea>` with a "Odoslať" button. Submits on Enter (Shift+Enter
   inserts newline). Disabled when:
   - the session is in `BUILDING_STORY`, `COMPLETED`, or `FAILED` state,
   - or a request is in flight,
   - or the input is empty or exceeds `CHAT_MESSAGE_MAX_CHARS`.
   A character counter "X / CHAT_MESSAGE_MAX_CHARS" appears below.
5. **Confirm hint:** when the latest assistant message has
   `phase="awaiting_confirmation"`, a small Slovak hint appears
   underneath the composer: "Ak súhlasíš so zhrnutím, odpovedz napríklad
   'áno' alebo 'do toho'." There is no separate confirm button — the
   user types their answer like any other reply.

   The chat experience also covers the optional companion topic
   (§ 7.1 Call 0a rules #6–#9). Agent 0a is expected to surface the
   companion question naturally — e.g. *"Bude v príbehu okrem hlavných
   postáv aj nejaké zviera, robot, alebo iná podobná bytosť?"* — but
   only once the human cast is settled, only if the user has not
   already volunteered an answer, and without insisting if the user
   declines. The verbatim phrasing lives in `chat.md`; this clause
   captures the intent.

   **No "Spustiť ilustrácie" / "Generate illustrations" button exists
   anywhere in the UI.** The pipeline must start automatically when
   Agent 0a returns `phase="confirmed"` (see Behavior below). The
   `ChatComposer` exposes only the "Odoslať" send control.
6. **Error banner** (`SessionErrorBanner`): visible when
   `session.state === "FAILED"`. Displays a Slovak message mapped from
   `session.error_code` via `src/i18n/sessionErrors.ts` (see § 9.4),
   plus a "Skúsiť znova" link that resets to a fresh `/` (drops the
   in-memory session and reloads).

**Behavior:**

- On mount, the store renders the welcome message locally (no backend
  call yet). The session row is only created when the user submits the
  first message — that triggers `POST /api/sessions`.
- On every subsequent submit, `POST /api/sessions/{id}/messages`.
- **Optimistic message rendering.** As soon as the user hits Enter (or
  "Odoslať"), the sessionStore appends the user's message to `messages`
  *before* awaiting the POST response, so the bubble appears
  immediately. The optimistic row carries a temporary client-side id
  (e.g. `temp-<uuid>`) and a `pending: true` flag. While `pending`, the
  bubble may render with a subtle visual cue (e.g. reduced opacity or
  a small clock glyph) but otherwise looks like any other user
  message. The "Asistent píše…" indicator is shown immediately after
  the optimistic row, *not* in place of it.
  - **On success:** the server returns both the persisted user message
    and the assistant reply. The store replaces the optimistic row
    in-place using the server's `id` / `order_index` (preserving array
    position) and appends the assistant message. The `pending` flag is
    cleared.
  - **On failure:** the store rolls back by removing the optimistic
    row, restores the composer's draft content (so the user can edit
    and retry without retyping), and surfaces the error via the
    existing error banner / inline status. `session.state` is *not*
    automatically transitioned to `FAILED` for transient errors
    (network blip, 5xx) — only persisted server-side `FAILED` states
    drive the banner.
  - The same pattern applies to the very first message
    (`sendFirstMessage`): the optimistic user bubble appears before
    `POST /api/sessions` resolves; on success the local `session` is
    populated and the optimistic row is reconciled with the persisted
    one.
- After receiving an assistant reply with `phase="confirmed"`:
  - Show the reply in the chat.
  - Immediately call `POST /api/sessions/{id}/finalize` (no extra UI
    action required). The trigger is the `phase` field on the reply —
    never the prose content — so localisation and minor wording drift
    cannot break the handoff.
  - Show the "Pripravujem príbeh a ilustrácie..." status while the call
    is in flight.
  - On 201 with `{ run_id }`, navigate to `/runs/:run_id`.
  - On error, show the session error banner.

#### Screen B — Run (`/runs/:run_id`)

**Purpose:** Show the generated story together with progress of the
illustrations, or the final state of a completed run.

**Elements (top to bottom):**

1. **Header:** A back link "← Nový príbeh".
2. **Run status pill:** "Beží" (with spinner) / "Hotovo" / "Zlyhalo" /
   "Zrušené".
3. **Run-level error banner** (`RunErrorBanner`): visible when
   `run.status === "FAILED"`. Maps `run.error_code` to a Slovak
   message via `src/i18n/runErrors.ts` (§ 9.4).
4. **Global progress:** "Hotové: K z N". Below it, a minimal horizontal
   bar showing `completed_count / illustration_count`.
5. **Cancel button** (`CancelButton`): visible only while status is
   `RUNNING`. Confirms via a small inline confirmation
   ("Naozaj zrušiť?" + Áno / Nie).
6. **Story** (`StoryBlocks`): the heading `run.story_title` rendered as
   `<h1>`, followed by the ordered `run.story_blocks`:
   - `paragraph` blocks render as a `StoryParagraph` component — one
     instance per paragraph block — keyed by the paragraph's index in
     the paragraph subset of `story_blocks`. Each `StoryParagraph`
     receives that index plus a reactive reference to the block's
     `text` field. It renders the prose in a `<p>` element and is the
     **only** component allowed to read or render paragraph text. See
     "Reactive paragraphs and skeletons" below.
   - `illustration` blocks render as `InlineIllustration` components
     keyed by `scene_index`. Initial state shows a centered loader
     (spinner + caption "Kreslím ilustráciu k tejto pasáži..."). When
     the matching illustration transitions to `COMPLETED`, the loader is
     replaced by the image (full bleed inside its container, max height
     ~520 px, click to open the original). On `FAILED`, shows a small
     sad-face placeholder with caption "Túto ilustráciu sa nepodarilo
     vytvoriť." On `CANCELLED`, shows a greyed-out placeholder.
7. **Illustration cards grid** (`IllustrationCard` × N): below the end
   of the story, the same per-illustration progress cards as in the
   previous spec, with the layout updates described below. They behave
   as the diagnostic / debug view that complements the literary
   in-story rendering above.

**Reactive paragraphs and skeletons**

`StoryParagraph` is a thin reactive wrapper around one paragraph block.
The component binds to two pieces of store state:

1. The block's `text` (read via the runStore — see § 9.2.2). Because
   Vue's reactivity is field-level, mutating
   `run.story_blocks[i].text` on the existing reactive object causes
   any mounted `StoryParagraph` bound to that field to re-render the
   new text **in place**, without remount.
2. A boolean `isRegenerating`, derived from the store getter
   `runStore.isParagraphRegenerating(paragraphIndex)` (§ 9.2.2). It is
   `true` whenever **any** illustration whose `paragraph_index` equals
   this paragraph's index is in state `RETHINKING_CONCEPT`. (More than
   one illustration may, in principle, point at the same paragraph;
   the getter returns `true` if at least one matches.)

While `isRegenerating` is `true`, `StoryParagraph` hides the prose and
renders a **skeleton loader** (`SkeletonBlock`) in its place. The
skeleton occupies the paragraph's natural vertical space (a few
multi-line lines of pulsing placeholder), so the surrounding layout
does not jump. When the SSE `paragraph_updated` event arrives, the
store writes the new `text` to the block; immediately after, the
following `illustration_state` event flips the branch out of
`RETHINKING_CONCEPT`, which flips `isRegenerating` to `false`, which
swaps the skeleton out for the freshly-updated prose — visually the
user sees the skeleton resolve into new paragraph text.

The initial story build by Agent 0b is **not** wrapped by this skeleton
state. At Agent 0b time the run does not exist yet; the user is still
on the chat screen. By the time the user reaches `/runs/:run_id` the
story blocks are already populated. Skeletons only ever appear on a
paragraph during a later Agent 4 rewrite cycle.

**Skeletons inside `IllustrationCard` (replacing concept-as-text)**

The card no longer displays the concept inline. Where the previous spec
showed a `concept` text block, the card now shows either:

- the **final image** (when `state === "COMPLETED"`), or
- a **skeleton placeholder** in the same slot, mirroring the
  illustration's aspect ratio.

The skeleton's aspect ratio matches the actual generated image's aspect
ratio (1:1 for the MVP workflow — see § 7.2 and the workflow's
`empty_latent_image` dimensions). It is rendered via the shared
`SkeletonBlock` component sized through CSS `aspect-ratio: 1 / 1`
(falling back to a padding-bottom trick in older browsers if needed).
While `state` is non-terminal, the skeleton pulses to convey activity.
On `FAILED` it is replaced by the sad-face placeholder; on `CANCELLED`
the card greys out as before. The skeleton must reserve the same space
the final image would, so the cards grid does not reflow when images
finish landing.

**Concept popover in the card header**

The current concept text moves into a popover. The card header gains a
small info-icon (e.g. a question-mark or info glyph) at the right end
of the header row, after the state label. On hover (desktop) or
focus / tap (touch / keyboard) the icon reveals a popover containing:

- A small label, e.g. "Aktuálny koncept".
- The reactive `illustration.current_concept` text.
- Below it, a subtler line "Pasáž príbehu:" followed by
  `illustration.scene_excerpt` truncated to ~200 chars.

The popover content stays reactive: when SSE `illustration_state`
events update `current_concept` or `scene_excerpt`, an open popover
re-renders in place. The popover component is provided by
`floating-vue` (§ 9.5). Accessibility: the icon is a focusable
`<button type="button">` with an `aria-label` (e.g. "Zobraziť koncept"),
the popover is keyboard-dismissible (Esc), and it is also openable on
keyboard focus, not only on hover.

**Each `IllustrationCard` shows (revised list):**

- Scene number "Ilustrácia K" (left of header).
- The current state with its Slovak label (see § 6 table).
- A small spinner / pulse animation while the state is non-terminal.
- The current attempt counters if relevant: "pokus K/3" during
  `RENDERING`, attempt info also during `REVISING_PROMPTS` /
  `RETHINKING_CONCEPT`.
- The **info-icon popover** (right of header) carrying the current
  concept text and the scene excerpt (replaces the old in-body concept
  text and excerpt-preview tooltip). When `illustration.companion` is
  non-null, the popover additionally shows the `interaction` text on a
  separate line.
- The **image slot** in the card body — skeleton (aspect 1:1) until
  `COMPLETED`, then the actual thumbnail (click to open original).
- **Companion subtitle** (only when `illustration.companion` is
  non-null): a small line below the existing scene info reading
  `"V scéne je tiež: {description}"`. When `companion` is null, the
  line is omitted entirely. The subtitle is reactive — when the
  `illustration_companion_updated` SSE event mutates the companion in
  place, the subtitle re-renders without remount; when the companion
  transitions to null, the subtitle disappears; when it transitions
  from null to non-null, it appears.
- On `FAILED`: a short error message (no retry button in MVP).
- On `CANCELLED`: greyed-out card with label "Zrušené".

Reactivity guarantees carried over from the previous spec still hold:
when `current_concept` changes mid-flight (Agent 4 cycle), the
popover's bound text updates in place, no remount, no scroll jump, no
loss of expanded / collapsed UI state.

**Behavior:**

- On mount, call `GET /api/runs/{run_id}` to get a snapshot, then open
  an `EventSource` to `GET /api/runs/{run_id}/events`.
- SSE events update the store. The first SSE event (`snapshot`) is
  treated as authoritative and replaces the snapshot fetched via REST.
- On `run_completed` / `run_failed` / `run_cancelled`, close the
  EventSource but stay on the screen.
- On navigation away, close the EventSource.

### 9.2 Stores

#### 9.2.1 `sessionStore` (Pinia)

State:
- `session: Session | null`
- `messages: ChatMessage[]` (ordered by `order_index`)
- `isSending: boolean`
- `isFinalizing: boolean`
- `error: { code: string, message: string } | null`

Welcome message — local constant, rendered on `HomeView` mount:

> "Ahoj, som tvoj virtuálny asistent a som tu na to, aby som ti pomohol
> vytvoriť krátky ilustrovaný anime príbeh. Aby sme mohli pokračovať,
> musíme sa najprv spolu zhodnúť na nejakom celkovom koncepte príbehu.
> Začni tým, že napíšeš čokoľvek, čo ti príde na myseľ a čo by malo
> ovplyvniť výsledný príbeh. Platí len jedno pravidlo. Keďže ide o
> obmedzenú demo verziu aplikácie, v príbehu môže vystupovať len
> **jeden mužský** a/alebo **jedna ženská** postava. Jedinou povolenou
> výnimkou je, že hlavná postava môže mať aj svoju **matku**."

English source as provided by the product owner (kept here so the
translator and the prompt author can stay aligned with the original
intent):

> "Hi, I'm your virtual assistant and I'm here to help you create the
> short illustrated anime story. In order to proceed, we must agree on
> some kind of overall story concept together. Start with writing
> anything that comes into your mind, that should shape the final
> story. There is only one rule. Since this is a restricted demo
> version of the app, there can be only **one male** and/or **one
> female** character. The only supported exception is that the main
> character can also have their **mother**."

The same Slovak text is also inserted as the first `session_messages`
row when the backend creates the session, so reloading the page after
the first user message preserves the welcome verbatim.

State (additions for optimistic rendering):
- Each `ChatMessage` in `messages` carries an optional `pending: boolean`
  flag and an optional `clientId: string` (only set on optimistic rows
  before the server response reconciles them).

Actions (all message-sending actions implement the optimistic pattern):
- `sendFirstMessage(content)`:
  1. Push an optimistic user `ChatMessage` (`role="user"`, `content`,
     `clientId=temp-<uuid>`, `pending=true`) onto `messages`.
  2. `POST /api/sessions` with `{ content }`.
  3. On success: set `session` from the response and replace the
     optimistic row with the persisted user message (matched by
     `clientId` → server `order_index=0`), then append the assistant
     reply.
  4. On failure: remove the optimistic row by `clientId`, set
     `error`, expose the original `content` so the composer can
     restore the user's draft.
- `sendMessage(content)`:
  1. Push the optimistic user row exactly as above.
  2. `POST /api/sessions/{id}/messages`.
  3. On success: reconcile the optimistic row in-place, append the
     assistant reply.
  4. On failure: rollback (remove optimistic row, restore draft, set
     `error`).
- `finalize()` → `POST /api/sessions/{id}/finalize`, returns `run_id`.
  Triggered automatically when the latest assistant reply has
  `phase="confirmed"`.
- `reset()` → clears all state to start a fresh session.

The optimistic reconciliation MUST preserve the array index of the user
row — replace in place, never `push` then sort. This guarantees the
visual position of the user's bubble does not jitter when the server
response lands.

#### 9.2.2 `runStore` (Pinia)

State:
- `run: Run | null`
- `illustrations: Illustration[]` (by `scene_index` order)
- `isConnecting: boolean`
- `sseError: string | null`

Actions:
- `loadRun(runId)` → GET snapshot.
- `subscribe(runId)` → opens EventSource, dispatches updates.
- `unsubscribe()` → closes EventSource.
- `cancel()` → POST cancel.

Derived getters:
- `illustrationByScene(sceneIndex)` — live illustration object for a
  given scene_index. Used by `StoryBlocks` and `InlineIllustration` to
  look up the current state of each inline placeholder without
  duplicating state.
- `isParagraphRegenerating(paragraphIndex): boolean` — `true` iff at
  least one illustration whose `paragraph_index === paragraphIndex` is
  currently in state `"RETHINKING_CONCEPT"`. Drives the skeleton state
  on `StoryParagraph` (§ 9.1 Screen B).
- `paragraphAt(paragraphIndex): ParagraphBlock | undefined` — returns
  the paragraph block at the given index in the paragraph subset of
  `run.story_blocks`. Used by `StoryParagraph` to read its `text`
  reactively. Implementation note: the getter resolves the position in
  the mixed `story_blocks` array (paragraphs interleaved with
  illustrations) by counting paragraph blocks in document order.

SSE handlers:

- `snapshot` → replaces `run` and `illustrations` wholesale (this is
  authoritative; § 8.4).
- `illustration_state` → finds the illustration by `illustration_id`
  and mutates the existing reactive object **in place**:
  - `state`, `concept_attempt`, `prompt_attempt` always.
  - `current_concept` — always copied from the payload (non-null on
    every transition, per § 8.4).
  - `scene_excerpt` — always copied from the payload. The excerpt can
    change across an Agent 4 cycle (§ 7.1 Call 4); the assignment is
    field-level so any component bound to it (most notably the concept
    popover in `IllustrationCard`) re-renders without remount.
- `paragraph_updated` → locate the paragraph block at
  `event.paragraph_index` in the paragraph subset of
  `run.story_blocks` and assign `block.text = event.text` on that
  existing reactive object. Because the assignment is field-level, the
  `StoryParagraph` bound to that block re-renders in place. The store
  MUST NOT replace the whole `story_blocks` array or swap the block
  object — both would force every `StoryParagraph` to remount and
  break the skeleton-to-text crossfade. A reference-identity assertion
  in the tests verifies this (§ 11.3).
- `illustration_companion_updated` → finds the illustration by
  `illustration_id` and assigns `illustration.companion = event.companion`
  on the existing reactive object (replacement of the whole companion
  field is fine — its inner fields are not bound separately, since the
  whole object can transition to/from null). The IllustrationCard's
  companion subtitle re-renders without remount.
- `illustration_completed`, `illustration_failed`, `run_completed`,
  `run_failed`, `run_cancelled`, `heartbeat` — as previously specified.

The `paragraph_updated` and `illustration_state` events arrive in the
order specified in § 8.4: the paragraph text is replaced *before* the
illustration's state flips out of `RETHINKING_CONCEPT`, so the
`isParagraphRegenerating(paragraphIndex)` getter is still `true` at
the moment the text changes. Visually the skeleton is then dismissed
by the very next event (the `illustration_state` carrying the new
state). This means the user never sees the skeleton ahead of an empty
or stale paragraph; the swap is single-frame.

### 9.3 Styling

- Scoped SCSS per component.
- A small `assets/styles/_tokens.scss` for shared variables (colors,
  spacing, radii, font stacks) and one global `_reset.scss`.
- Minimalistic visual style: light background, generous whitespace,
  one accent color. No UI kit (the only third-party visual component
  is the popover from `floating-vue` — § 9.5).
- Chat bubbles use the accent color for the user side and a neutral
  surface for the assistant side; the welcome message visually matches
  other assistant messages.

#### 9.3.1 Typography

The app's typography is modelled on the Literature & Latte / Scrivener
website (https://www.literatureandlatte.com/scrivener/overview) — a
classical, literary, serif-dominant look that suits the app's purpose
(reading a short illustrated story). Fonts are fetched **for free** from
Google Fonts at runtime.

- **Headings (`<h1>`, `<h2>`, story title, section headers):** `Unna`
  from Google Fonts — the same display serif used by the Scrivener
  site for `.fp-blog-heading` (`font-family: Unna, Georgia, serif;`).
  Weights loaded: 400, 700.
- **Body text (story paragraphs, chat bubbles, card labels, general
  UI):** `Lora` from Google Fonts — a contemporary classical serif
  that pairs cleanly with Unna and is comfortable at small sizes.
  Weights loaded: 400, 600 (and 400-italic if needed for emphasis).
- **Monospace** (used only for debug snippets if any): system
  monospace stack. Not part of the literary aesthetic.

Loading mechanics:

- `index.html` includes a single `<link rel="stylesheet">` to the
  Google Fonts CSS endpoint that requests both families with the
  weights above (a single request with both `?family=Unna:wght@400;700`
  and `&family=Lora:wght@400;600` parameters).
- The two `preconnect` `<link>` tags recommended by Google
  (`https://fonts.googleapis.com` and `https://fonts.gstatic.com`)
  are included immediately before the stylesheet link so font
  fetching starts in parallel with the rest of the boot.
- `_tokens.scss` declares two SCSS variables — `$font-heading`,
  `$font-body` — each ending with appropriate generic fallbacks
  (`Georgia, "Times New Roman", serif`) so that any FOUT during font
  download already lands on a sensible serif.
- The global `body` selector sets `font-family: $font-body`;
  `h1, h2, h3, h4, .story-title` select `$font-heading`.
- No webfont self-hosting in MVP — the Google Fonts CDN is
  authoritative. (If, after MVP, the operator decides to self-host
  for offline use, the spec needs an explicit revision.)

Fallback policy: if both fonts are unreachable (no network, ad-blockers,
etc.), the page must still render readably with the serif fallback
stack. This is a pure-CSS concern and requires no JS handling.

#### 9.3.2 Skeleton aesthetics

Skeletons are rendered by `SkeletonBlock`. The component takes a
`shape` prop (`"line" | "block"` — lines for paragraph skeletons,
blocks for image skeletons) and an optional `lines` prop (default `3`
for the `"line"` shape) plus an optional `aspectRatio` for the
`"block"` shape (default `"1 / 1"` for the IllustrationCard image
slot, matching the workflow's 1:1 output).

Visuals: a subtle linear-gradient sweep animation (background-position
keyframe over ~1.6 s) over a neutral surface color from `_tokens.scss`.
The animation respects `@media (prefers-reduced-motion: reduce)` and
falls back to a static muted block in that case.

### 9.4 Error code → Slovak UX message mapping

Two mapping modules, both unit-tested.

**`src/i18n/sessionErrors.ts`:**

| `error_code`           | Slovak UX message                                                                                                                                |
|------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| `CHAT_FAILED`          | "Asistent momentálne nedokáže odpovedať. Skús to prosím o chvíľu znova."                                                                          |
| `STORY_BUILD_FAILED`   | "Pri tvorbe príbehu sa niečo pokazilo. Skús prosím začať odznova a mierne upraviť zadanie."                                                       |
| `INTERNAL_ERROR`       | "Vyskytla sa neočakávaná chyba. Skontrolujte log servera pre detaily."                                                                            |

**`src/i18n/runErrors.ts`:**

| `error_code`           | Slovak UX message                                                                                                                                |
|------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| `INTERNAL_ERROR`       | "Vyskytla sa neočakávaná chyba pri generovaní ilustrácií. Skontrolujte log servera pre detaily."                                                  |

Unknown codes in either map fall back to the `INTERNAL_ERROR` message.
`null` / `undefined` produces an empty string (the banner stays hidden).

### 9.5 Popover component (`floating-vue`)

The single third-party Vue component dependency is **`floating-vue`** —
a lean popover / tooltip library built on `@floating-ui/dom`. It is
added to `frontend/package.json` as a regular dependency. No other UI
kit (PrimeVue, Vuetify, Headless UI, etc.) is introduced.

Why `floating-vue`:

- Headless / styleable: the popover container is a plain element the
  app styles with scoped SCSS, so it inherits the app's tokens and
  typography (§ 9.3.1) cleanly.
- Lean: it ships only the popover / tooltip primitives we need; no
  global theme, no reset, no opinionated components.
- Accessible by default: handles focus management, ARIA attributes,
  Esc to dismiss, and respects `prefers-reduced-motion`.

Setup:

- Imported in `src/main.ts` with `app.use(FloatingVue, { ... })`.
- The library's CSS is imported once globally (`floating-vue/dist/style.css`).
- A small wrapper component `ConceptPopover.vue` encapsulates the
  app-specific styling and the icon button — every consumer
  (currently only `IllustrationCard`) imports the wrapper, not
  `floating-vue` directly, so future swaps are local.

Usage rule: `floating-vue` is reserved for popover / tooltip surfaces
where the trigger element is icon-sized. It is **not** used to build
modals, dropdown menus, autocomplete lists, or anything else in this
spec. Adding any new use of the library requires extending this
section.

---

## 10. Constants

Defined in `backend/app/constants.py`:

| Name                              | Value | Meaning                                                           |
|-----------------------------------|-------|-------------------------------------------------------------------|
| `MAX_ILLUSTRATIONS`               | 5     | Exact illustrations per run — Agent 0b MUST return exactly this many (§ 7.1 Call 0b rule #4) |
| `MAX_PROMPT_ATTEMPTS_PER_CONCEPT` | 3     | Total image-generation attempts per concept (initial + 2 revisions)|
| `MAX_CONCEPT_ATTEMPTS`            | 3     | Total concepts tried per illustration (initial + 2 rethinks)      |
| `COMFYUI_POLL_TIMEOUT_S`          | 600   | Max wait per ComfyUI job                                          |
| `COMFYUI_POLL_INTERVAL_S`         | 3     | Polling interval                                                  |
| `MAX_CONCURRENT_BRANCHES`         | 5     | Async semaphore over branches (= MAX_ILLUSTRATIONS for MVP)       |
| `CLAUDE_JSON_RETRY`               | 2     | Re-prompts on Claude output JSON parse failure                    |
| `CHAT_MESSAGE_MAX_CHARS`          | 4000  | Hard limit on a single chat message                               |
| `CHAT_MESSAGES_MAX_PER_SESSION`   | 60    | Hard cap on total messages per session (refuse further input)     |
| `ANTHROPIC_MODEL`                 | `"claude-sonnet-4-6"` | Single model used for all 6 calls                 |
| `WELCOME_MESSAGE_SK`              | (multiline string, see § 9.2.1) | Server copy of the welcome text inserted as first session message |
| `CONFIRMED_ACK_SK`                | `"Skvelé, ide na to. Pripravujem príbeh a ilustrácie…"` | Canonical Slovak `reply` returned by Agent 0a on `phase="confirmed"`; server normalizes any other prose to this value (see § 7.1) |

The `STORY_MAX_CHARS` constant from the previous spec is removed (raw
story text is no longer a public input).

---

## 11. Tests (mandatory before delivery)

All tests must pass. Reasonable coverage of the listed scenarios; no need
to chase 100 % line coverage.

### 11.1 Backend unit (`tests/unit/`)

- **Placeholder replacement** (`services/workflow.py`):
  - Replaces all five placeholders nested at arbitrary depths.
  - Leaves unrelated strings untouched.
  - Reports which placeholders were missing.
  - `CHARACTER_LORA` is sourced from `character_config[role].lora_filename`
    based on the per-illustration role.
- **Character config loader**: as previously specified.
- **Agent prompt loader** (new test file, `tests/unit/test_agents_loader.py`):
  - Loads all six `.md` files from a temporary `AGENTS_DIR` fixture and
    exposes them on the Claude client.
  - Refuses to start (raises typed error) when any of the six files is
    missing, empty, or unreadable.
  - The system prompt sent to Anthropic for each call equals the file
    contents verbatim (verified by intercepting the outgoing request with
    respx).
- **Claude IO schemas** (`schemas/...`):
  - Each of the 6 response Pydantic models accepts a valid example.
  - Each rejects a malformed example (missing field, wrong type).
  - **Call 0a (chat) schema:**
    - `reply` is required and is a non-empty string.
    - `phase` must be one of the three allowed values.
    - When `phase=gathering`, `collected_brief` must be `null`.
    - When `phase=awaiting_confirmation` or `phase=confirmed`,
      `collected_brief` must be a fully-populated object.
    - `collected_brief.characters` rejects rosters that violate the cast
      rules (more than one of any role, two `mother` entries, a
      `mother` with no main character, an unknown role string).
  - **Call 0b (build_story) schema and validators:**
    - `illustrations` length must equal `MAX_ILLUSTRATIONS` exactly;
      every other length (0, 1–4, 6+) is rejected.
    - `character_role` must be one of `male` / `female` / `mother`.
    - Block ordering rules: rejects when first or last block is an
      `illustration`; rejects two adjacent `illustration` blocks;
      rejects when `illustration` `scene_index` values don't match
      `illustrations` rows 1-to-1 in the natural order.
    - `scene_excerpt` substring validator: passes when each excerpt
      appears verbatim in the joined paragraph text (whitespace-
      tolerant), rejects otherwise.
- **Claude IO schema — Call 4 (`rethink_concept`):**
  - Accepts a valid response
    `{ concept, paragraph_text, scene_excerpt, companion: null }`.
  - Accepts a valid response with a non-null `companion`.
  - Rejects responses missing any of the three required fields.
  - Server-side validator rejects responses where `scene_excerpt` is
    not a verbatim substring of `paragraph_text` (whitespace-tolerant),
    matching the Agent 0b excerpt rule (§ 7.1 Call 0b rule #3).
- **Companion schema rules (across Calls 0a / 0b / 4):**
  - Call 0a's `collected_brief.companions` accepts an empty array, a
    1-entry array, and a 2-entry array; rejects 3+ entries.
  - Call 0b's per-illustration `companion` accepts both `null` and a
    fully populated `{ description, interaction }`; rejects entries
    that set only `description` or only `interaction`.
  - Call 4's `companion` field has the same accept/reject behavior as
    Call 0b's.
- **Companion pool fidelity validators (server-side, beyond Pydantic):**
  - Agent 0b output post-validation: an illustration whose
    `companion.description` does not match (whitespace-tolerant,
    case-insensitive substring or exact) any entry in
    `collected_brief.companions` is rejected and re-prompted up to
    `CLAUDE_JSON_RETRY` times; ultimate failure surfaces as
    `STORY_BUILD_FAILED`.
  - Agent 4 output post-validation: same rule against the run's saved
    `collected_brief.companions` pool; ultimate failure causes the
    branch to behave as if Agent 4 returned nothing useful, per § 6
    loop semantics.
- **Branch state machine** (`orchestrator/branch.py`):
  - Existing scenarios (happy path, prompt revision, concept restart,
    all attempts exhausted, cancellation, correct character_config
    usage) continue to pass.
  - **Agent 4 paragraph rewrite (new):** given a branch that fails its
    first concept and triggers Agent 4, the mocked Agent 4 response
    `{ concept, paragraph_text, scene_excerpt }` is applied:
      - `runs.story_blocks_json` is updated so the paragraph at the
        branch's `illustrations.paragraph_index` has the new `text`,
        and no other block changes.
      - `illustrations.scene_excerpt` is updated to the new excerpt;
        `illustrations.current_concept` is updated to the new concept;
        `illustrations.initial_concept` is **not** touched.
      - An SSE `paragraph_updated{paragraph_index, text}` event is
        emitted before the post-rethink `illustration_state` event,
        per the ordering in § 8.4.
      - A subsequent Agent 4 call on the same branch receives the
        **already-rewritten** paragraph as `current_paragraph_text`
        and the full latest story as `full_story_text` (verified by
        intercepting the outgoing Claude request via respx and
        inspecting the user-turn JSON payload).
  - **Agent 4 invalid response → retry → fail:** mock Agent 4 to
    return responses that violate the excerpt-substring rule
    `CLAUDE_JSON_RETRY + 1` times in a row; the branch exhausts the
    concept attempt and continues per § 6 loop semantics (no DB
    mutation occurs from invalid responses).
  - **Companion happy-path (new):** the illustration starts with a
    non-null `companion` (set by Agent 0b at run creation). The branch
    runs through to `COMPLETED`. Calls 1 / 2 / 3 receive the companion
    in their input (verified by intercepting the outgoing Claude
    request payload). `companion_description` and
    `companion_interaction` columns remain set on the row.
  - **Agent 4 drops the companion (new):** the branch fails its first
    concept and triggers Agent 4. Mock Agent 4 to return
    `companion: null`. The branch persists `companion_description=NULL`
    and `companion_interaction=NULL` on the illustration row, emits
    `illustration_companion_updated{companion: null}` after
    `paragraph_updated`, then proceeds.
  - **Agent 4 swaps the companion (new):** the brief lists two
    companion entries. Mock Agent 4 to return a companion whose
    `description` matches the *other* brief entry. The branch persists
    the new description and interaction and emits
    `illustration_companion_updated` carrying the new companion.
  - **Agent 4 unchanged companion (new):** Mock Agent 4 to return the
    same companion as the current one. The branch does NOT emit
    `illustration_companion_updated` (no spurious event).
  - **Agent 4 companion not in pool (new):** Mock Agent 4 to return a
    companion whose `description` is not in the brief's pool
    `CLAUDE_JSON_RETRY + 1` times. The branch treats this as failure
    and continues per § 6 loop semantics; no DB mutation occurs from
    invalid responses.
- **Pipeline / run creation** (`orchestrator/pipeline.py`):
  - Runs created with N=3 illustrations spawn 3 branches.
  - Runs created with N=5 succeed end-to-end (mocked clients).
  - Mixed outcome (3 ok, 2 failed) → run `COMPLETED` (not "failed"
    just because some branches failed).
  - Unhandled exception inside orchestrator → run `FAILED` with
    `error_code = INTERNAL_ERROR`.
  - The legacy Step 0 paths (`NO_SUITABLE_SCENES`, `STEP0_FAILED`,
    truncation-from-Step-0) are removed; equivalent scenarios live in
    the session-layer tests below.
- **Session service / Agent 0a flow** (new file, `tests/unit/test_sessions.py`):
  - First message creates a session whose transcript begins with the
    canonical welcome message, followed by the user's message and the
    mocked Agent 0a reply.
  - When Agent 0a returns `phase=gathering`, the session state stays
    `CHATTING` and `collected_brief` is not persisted.
  - When Agent 0a returns `phase=awaiting_confirmation` with a valid
    brief, the session state becomes `AWAITING_CONFIRMATION` and the
    brief is persisted.
  - When Agent 0a returns `phase=confirmed` but no prior
    `awaiting_confirmation` turn exists in the session, the
    server-side guard downgrades it to `awaiting_confirmation` before
    persisting.
  - When Agent 0a returns `phase=confirmed` after a legitimate
    `awaiting_confirmation` turn, the assistant message is persisted
    with that phase but the session does NOT auto-finalize.
  - When Agent 0a raises (Claude error after retries), the session
    transitions to `FAILED` with `error_code=CHAT_FAILED`.
  - Posting a message to a session whose state is `BUILDING_STORY`,
    `COMPLETED`, or `FAILED` returns 409 and persists nothing.
  - `CHAT_MESSAGES_MAX_PER_SESSION` refuses further user input (409).
- **Finalize / Agent 0b flow** (new tests in same file):
  - On confirmable session, Agent 0b is invoked with the persisted
    brief and a `runs` row is created with the returned `story_title`,
    `story_blocks`, `style_guide`, and N `illustrations` rows in
    `PENDING`.
  - On invalid Agent 0b output (schema violation or hard-rule
    violation), after `CLAUDE_JSON_RETRY` retries the session
    transitions to `FAILED` with `error_code=STORY_BUILD_FAILED` and
    no run is created.
  - Finalize against a non-confirmable session returns 409.
  - The created run's `session_id` matches the session.
- **SSE event bus** (`orchestrator/events.py`):
  - `snapshot` is emitted first to a new subscriber (and contains the
    style_guide).
  - Events broadcast to multiple subscribers.
  - Stream closes on terminal run states.
  - `run_failed` payload includes both `error_code` and `error_message`.
  - `illustration_companion_updated` is broadcast to all current
    subscribers after Agent 4 returns a *different* companion
    (including the transition to/from null). Multiple subscribers each
    observe the same payload.
- **RunPod client** (`services/runpod.py`): unchanged from previous
  spec.
- **Alembic / models in sync** (new test file,
  `tests/unit/test_migrations.py`):
  - Spins up a temporary SQLite, runs `command.upgrade(cfg, "head")`,
    then calls Alembic's autogenerate machinery
    (`MigrationContext.configure(...)` + `produce_migrations(...)`)
    against `Base.metadata` and asserts that the resulting `Migrations`
    object is empty. A non-empty diff means somebody changed a model
    without generating a migration, and the test fails with a readable
    description of the missing operations.
  - Asserts that `alembic upgrade head` followed by
    `alembic downgrade base` followed by `alembic upgrade head` leaves
    the schema identical (round-trip safety on a fresh DB).

### 11.2 Backend integration (`tests/integration/`)

Anthropic and RunPod are mocked at the HTTP layer (respx). SQLite uses a
temporary file per test, schema-applied via Alembic (`command.upgrade`)
as described in § 5.0.

- **End-to-end happy path:**
  - `POST /api/sessions` → mocked Agent 0a returns `phase=gathering`.
  - `POST /api/sessions/{id}/messages` → mocked Agent 0a returns
    `phase=awaiting_confirmation` with a valid brief.
  - `POST /api/sessions/{id}/messages` (user "áno") → mocked Agent 0a
    returns `phase=confirmed`.
  - `POST /api/sessions/{id}/finalize` → mocked Agent 0b returns a
    valid story + 3 illustrations → 201 with `run_id`.
  - `GET /api/runs/{id}` returns the run with story blocks and 3
    `PENDING` illustrations.
  - Background work runs to completion → `GET /api/runs/{id}` shows
    `COMPLETED` with image paths written under a tmp `OUTPUT_DIR`. The
    SSE stream emits the expected sequence ending with `run_completed`.
- **STORY_BUILD_FAILED end-to-end:** as above, but mock Agent 0b to
  return invalid output. The finalize call ends with 502, the session
  becomes `FAILED` with `error_code=STORY_BUILD_FAILED`, and no run is
  created.
- **CHAT_FAILED end-to-end:** mock the Anthropic API to return errors
  for Agent 0a. The first `POST /api/sessions` returns 502, the
  persisted session is `FAILED` with `error_code=CHAT_FAILED`.
- **Cancellation:** run a happy-path session through to a run, cancel
  after the first branch transitions to `RENDERING`, verify final
  status `CANCELLED` and that branches transitioned to `CANCELLED`
  rather than continuing.
- **Companion end-to-end (new):** the chat phase produces a brief with
  one `companions` entry. Agent 0b returns 5 illustrations with
  `companion` non-null on scenes 0, 2, 4 and `null` on scenes 1, 3.
  Run completes via mocked Agents 1–3. Assertions:
  - All 5 branches run.
  - The Claude requests for scenes 0/2/4 include the companion in
    their input JSON payload (verified via respx); scenes 1/3 do not.
  - `GET /api/runs/{id}` returns the companion field non-null on
    scenes 0/2/4 and null on scenes 1/3.
- **Agent 4 drops companion end-to-end (new):** with a brief that
  contains one companion and Agent 0b assigning the companion to
  scene 0, Agent 2 mocked to return `problem="concept"` on the first
  attempt for scene 0, Agent 4 mocked to return `companion: null`.
  Assert the SSE stream contains the `illustration_companion_updated`
  event with `companion: null` for scene 0; assert a subsequent
  `GET /api/runs/{id}` returns `companion: null` on scene 0 (persisted).
- **Agent 4 paragraph rewrite end-to-end:** run the pipeline with
  Agent 2 mocked to return `problem="concept"` on the first attempt
  for one branch, and Agent 4 mocked to return a valid
  `{concept, paragraph_text, scene_excerpt}` triple. Assert:
  - The SSE stream contains a `paragraph_updated` event with the
    matching `paragraph_index` and the new `text`, sandwiched in the
    order specified in § 8.4 (between the `RETHINKING_CONCEPT`
    `illustration_state` event and the following
    `GENERATING_PROMPTS` `illustration_state` event).
  - A subsequent `GET /api/runs/{run_id}` returns a `story_blocks`
    payload where the paragraph at the relevant index carries the
    new text (persistence verified).
  - `illustrations[k].scene_excerpt` returned by the snapshot is the
    new excerpt and is a verbatim substring of the new paragraph
    text.
  - `illustrations[k].initial_concept` is unchanged from Agent 0b's
    original concept (immutable, per § 5.4).

### 11.3 Frontend unit (`frontend/tests/`)

Pinia stores and components are tested with Vitest + @vue/test-utils.

- **ChatMessage / ChatThread:**
  - Renders user and assistant messages in transcript order.
  - The welcome message is always shown first when the transcript is
    empty, with the `#word#`-marked segments rendered in **bold**.
  - Shows a small "Asistent píše…" indicator while a request is in
    flight.
- **ChatComposer:**
  - Disabled when the session state is `BUILDING_STORY`, `COMPLETED`,
    or `FAILED`.
  - Disabled while a request is in flight.
  - Enforces `CHAT_MESSAGE_MAX_CHARS` and shows the counter.
  - Submits on Enter, inserts newline on Shift+Enter.
- **SessionErrorBanner:**
  - Hidden when session state is not `FAILED`.
  - Renders the Slovak message mapped via `sessionErrors.ts`.
  - Unknown code falls back to `INTERNAL_ERROR` message.
- **`sessionErrors.ts` mapping** (new unit test file):
  - Each known code maps to its specified Slovak message.
  - Unknown code falls back to `INTERNAL_ERROR`.
  - `null` / `undefined` produces empty string.
- **sessionStore:**
  - `sendFirstMessage` posts to `/api/sessions` and replaces local
    state with the response payload.
  - After receiving an assistant reply with `phase="confirmed"`, the
    store automatically invokes `finalize()` and resolves with the
    `run_id`. The trigger is the `phase` field — the test mocks the
    reply with arbitrary `reply` prose and still expects auto-finalize.
  - On `phase="confirmed"` server response that errors during
    finalize, the store surfaces the error and transitions to a
    failed state without losing the chat transcript.
  - **Optimistic rendering — send happy path:** calling
    `sendMessage("hello")` synchronously appends a user `ChatMessage`
    with `pending=true` and a `clientId` *before* the mocked
    POST resolves; after resolution, the optimistic row is replaced
    in-place (same array index, `pending` cleared, server `id`
    populated) and the assistant reply is appended after it.
  - **Optimistic rendering — send failure rollback:** when the mocked
    POST rejects, the optimistic row is removed by `clientId`, the
    `error` field is set, and the original `content` is exposed (e.g.
    via a `lastFailedDraft` field or returned from the action) so the
    composer can restore it. `session.state` remains `CHATTING`.
  - **Optimistic rendering — first message:** the same pattern applies
    to `sendFirstMessage`; the optimistic user bubble is visible
    before `POST /api/sessions` resolves, and is reconciled on
    success.
  - Reconciliation preserves array order (assertion: the index of the
    user message in `messages` is identical before and after the
    server response lands).
- **IllustrationCard companion subtitle (new):**
  - When mounted with an illustration whose `companion` is non-null,
    the card renders a Slovak subtitle `"V scéne je tiež: {description}"`.
  - When `companion` is `null`, the subtitle is not present in the DOM.
  - When the store mutates `illustration.companion` from non-null to
    null in place (simulating `illustration_companion_updated`), the
    subtitle disappears without remounting the card.
  - When the store mutates `illustration.companion` from null to a
    populated object in place, the subtitle appears without
    remounting the card.
  - When the companion's `description` changes in place, the subtitle
    text updates in place.
- **runStore (new event handler):**
  - `illustration_companion_updated` with a non-null companion writes
    that companion onto the existing illustration object (reference
    survival assertion on the illustration object itself; the
    `companion` field is replaced as a whole).
  - `illustration_companion_updated` with `companion: null` clears the
    field on the existing illustration object.
- **sessionStore (new):**
  - The store correctly parses `collected_brief.companions` from
    Agent 0a's reply payloads (empty, 1-entry, 2-entry).
- **IllustrationCard reactive concept text + popover** (revised):
  - The card no longer renders `current_concept` as an inline body
    text element. The concept text is reachable only via the
    `ConceptPopover` trigger in the card header.
  - Activating the popover trigger (programmatic focus or simulated
    hover via the `floating-vue` test utilities, or a direct
    `wrapper.get('.concept-popover-trigger').trigger('focus')`)
    reveals an element containing the current `current_concept` text
    and the current `scene_excerpt`.
  - Given an `IllustrationCard` mounted with an illustration whose
    `current_concept` is `"A"`, when the parent store updates the
    same reactive object's `current_concept` to `"B"`, the popover
    content updates to show `"B"` **without re-mounting** the card or
    closing the popover (assert via component-instance identity
    survival).
  - The card's image slot renders a `SkeletonBlock` with the expected
    aspect-ratio class while `state` is non-terminal, replaces it
    with the `<img>` on `COMPLETED`, and the skeleton DOES NOT cause
    grid reflow when the image lands (assert the slot keeps the same
    bounding box height across the transition by checking computed
    `aspect-ratio` or padding-bottom).
- **StoryParagraph** (new test file):
  - Mounts a `StoryParagraph` bound to a paragraph block at index `i`.
  - Initially renders the block's `text` in a `<p>`.
  - When `runStore.isParagraphRegenerating(i)` becomes `true`, the
    component swaps the `<p>` for a `SkeletonBlock` (assert via
    `data-testid="paragraph-skeleton"` presence). The prose `<p>` is
    no longer in the DOM during this state.
  - When the block's `text` is mutated on the same reactive object
    (simulating `paragraph_updated`) and then `isParagraphRegenerating`
    flips back to `false`, the `<p>` reappears with the **new** text,
    and `StoryParagraph` has NOT been remounted (assert via stable
    component instance / element reference).
  - Initial mount (run page first load, no rethink in flight) renders
    the prose, never the skeleton — Agent 0b's output is not
    skeleton-gated (§ 9.1).
- **StoryBlocks / InlineIllustration:**
  - Renders `paragraph` blocks as `<StoryParagraph>` (one per
    paragraph block, keyed by paragraph index) and `illustration`
    blocks as `<InlineIllustration>` keyed by `scene_index`.
  - `InlineIllustration` shows a loader when the matching illustration
    state is non-terminal, the image when `COMPLETED`, a sad-face
    placeholder when `FAILED`, and a grey placeholder when `CANCELLED`.
- **IllustrationCard / ProgressCounter / CancelButton / RunErrorBanner /
  runErrors.ts mapping:** behaviors as previously specified, with the
  reduced error_code surface (`INTERNAL_ERROR` only) for runs.
- **runStore:**
  - `snapshot` event replaces full state.
  - `illustration_state` updates the right illustration by id.
  - `illustration_state` with a changed `current_concept` writes the
    new value onto the existing illustration object (asserted by
    holding a reference to the object before the event and observing
    the field change post-event without object identity changing).
  - `illustration_state` with a changed `scene_excerpt` writes the
    new value onto the existing illustration object (same reference-
    survival assertion as `current_concept`).
  - `paragraph_updated` mutates `run.story_blocks[<paragraph block at
    event.paragraph_index>].text` on the **existing** block object
    (reference-identity assertion: the block object retrieved before
    the event is the same JS object after the event, only its `text`
    has changed). The mutation does NOT replace the `story_blocks`
    array.
  - `isParagraphRegenerating(i)` returns `true` when any illustration
    whose `paragraph_index === i` is in state `RETHINKING_CONCEPT`,
    and `false` otherwise. Tested by seeding illustrations in mixed
    states and asserting the getter for every paragraph index.
  - `paragraphAt(i)` returns the i-th paragraph block in document
    order (skipping illustration blocks).
  - `illustration_completed` sets `image_url`.
  - `run_cancelled` sets run status correctly and unsubscribes.
  - `run_failed` sets `error_code` and `error_message`, transitions
    status to `FAILED`, and unsubscribes.
  - `illustrationByScene` getter returns the right illustration by
    `scene_index`.

### 11.4 What is NOT required (out of scope for MVP)

- E2E browser tests (Playwright/Cypress).
- Tests against the real Anthropic API or real RunPod.
- Load/performance tests.
- 100 % coverage.
- Hot reload of `.md` agent prompts.

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
- Retrying a single failed illustration without re-running the whole
  story.
- Resuming a failed session (the user starts a new chat from scratch).
- Editing the brief or the generated story after Agent 0b has produced
  it.
- User accounts / multi-tenant.
- Run / session history listing UI (the DB will accumulate rows, but
  no UI to browse).
- Internationalization beyond Slovak UI labels.
- Mid-flight cancellation of an already-dispatched ComfyUI job.
- Hot reload of agent prompt `.md` files.
- Streaming Agent 0a / Agent 0b responses to the UI token-by-token.
- Two or more human characters in a single illustration.
- Anthropomorphic / humanoid non-human companions (treated as a second
  human for scope purposes).
- Multiple non-human companions in a single illustration.
- Companion types not present in the brief's agreed pool.
- Auto-tuned per-illustration LoRA strengths for companion rendering.

---

## 13. Acceptance criteria

The MVP is considered complete when:

1. All tests defined in § 11.1–11.3 pass, and all lint/format/type-check
   commands defined in § 11.5 exit with zero errors.
2. With valid `.env` values, the six agent `.md` files present, and
   `character_config.json` populated, running `uvicorn` (backend) —
   which applies any pending Alembic migrations on startup — and
   `npm run dev` (frontend) starts both services without errors.
3. A user can land on `/`, read the welcome message, chat with the
   assistant, see the assistant push back when their proposed cast
   violates the character constraint, eventually get a summary and a
   request for confirmation, reply "áno", and be navigated to
   `/runs/:id` once the story is built. **No "Spustiť ilustrácie" /
   "Generate illustrations" (or equivalent) button exists in the UI
   at any point;** the navigation to `/runs/:id` is triggered solely
   by Agent 0a returning `phase="confirmed"`.
   Every user message — including the very first one and the "áno"
   confirmation — appears in the chat thread **immediately** on send,
   before the assistant's reply arrives (verified by manual smoke
   test: with the network throttled, the user bubble is visible while
   the "Asistent píše…" indicator is still active).
4. On `/runs/:id`, the user sees the generated story heading and
   paragraphs immediately, with inline placeholders for the
   illustrations showing loaders, while the illustration cards below
   the story show live progress via SSE. Loaders are replaced by the
   final images as each one completes. When the orchestrator loops
   through `RETHINKING_CONCEPT` for a given illustration:
   - The illustration's bound paragraph swaps to a **skeleton loader**
     (via `StoryParagraph` + `SkeletonBlock`) for the duration of
     Agent 4's work, then reveals the **rewritten paragraph text** in
     place when the `paragraph_updated` SSE event arrives. The change
     is purely reactive — no remount of `StoryParagraph`, no scroll
     jump, no disturbance of any other paragraph.
   - The matching `IllustrationCard` keeps an aspect-ratio skeleton in
     its image slot (rather than displaying concept text) until the
     image actually arrives. Hovering / focusing the info-icon in the
     card header reveals the (now-updated) concept text and the
     (now-updated) scene excerpt via the `floating-vue` popover; the
     popover content is reactive.
   - The card's internal UI state (expanded info, popover open state)
     survives the concept change without being reset.
   - Other illustrations and other cards are not disturbed by another
     branch's rethink cycle.
5. Cancelling an in-flight run brings it to `CANCELLED` within a few
   seconds, and the UI reflects this in both the inline placeholders
   and the cards.
6. Refreshing the run page mid-flight does not lose state — the
   snapshot restores the UI and SSE resumes. Refreshing the home page
   mid-chat does not lose the transcript once the session has been
   created (the backend serves it via `GET /api/sessions/{id}`).
7. No secrets are present in the frontend bundle.
8. When Agent 0b fails (or returns invalid output beyond retry), the
   session ends in `FAILED` with `error_code=STORY_BUILD_FAILED`, the
   chat screen shows the dedicated Slovak message, and no run is
   created.
9. Editing any agent prompt `.md` file and restarting the backend
   visibly changes that agent's behavior on the next call (verified by
   manual smoke test, not automated).
10. **Typography.** On a freshly loaded page (any screen), `Unna`
    (headings) and `Lora` (body) are fetched from Google Fonts and
    applied. With network DevTools open, exactly two font CSS
    families are requested from `fonts.googleapis.com`. If both
    fonts are blocked or fail to load, the page still renders
    readably with the serif fallback stack defined in `_tokens.scss`
    (manual smoke test).
11. **Agent 4 paragraph rewrite, end-to-end.** With the orchestrator
    configured to force a first-pass image evaluation failure with
    `problem="concept"`, the run reaches the `RETHINKING_CONCEPT`
    state for the affected illustration; an SSE
    `paragraph_updated{paragraph_index, text}` event is observable
    on the wire; the affected paragraph's prose visibly changes on
    `/runs/:id` without page reload; a subsequent `GET /api/runs/:id`
    snapshot returns `story_blocks` carrying the rewritten paragraph
    text (i.e. the change is persisted, not merely visual).
12. **Optional companion, end-to-end.** With a brief whose
    `companions` array contains at least one entry, Agent 0b assigns
    that companion to at least one scene, and the resulting
    `GET /api/runs/:id` returns the `companion` field set on the
    matching illustration(s) and `null` on the others. The
    `IllustrationCard` for those illustrations renders the
    `"V scéne je tiež: …"` subtitle. With a brief whose `companions`
    array is empty, every illustration has `companion: null` and no
    card subtitle is rendered — the rest of the app behaves
    identically to the no-companion baseline (backward compatibility).
    Forcing Agent 4 to drop a companion mid-run emits an SSE
    `illustration_companion_updated{companion: null}` event,
    persists the columns as NULL, and the card subtitle disappears
    reactively without a page reload.
