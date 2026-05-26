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

Between the user's confirmation and Agent 0b actually delivering, the chat
is replaced by a **story-skeleton view** — a one-line "Generating the story
on …" header (using a short topic phrase that Agent 0a produced in the
active UI language on the confirmed turn, see § 7.1 Call 0a) and five
paragraph-shaped skeleton blocks. This view replaces the previous in-chat
"Pripravujem príbeh a ilustrácie…" status strip so the user has a clear
visual signal that authorship is in progress rather than the chat hanging
(§ 9.1 Screen A).

The app is **multilingual** with first-class support for **Slovak (`sk`)**,
**Czech (`cs`)**, and **English (`en`)**. The user's interface language is
selected automatically from the browser on first load, can be overridden
by an always-present URL path prefix (`/sk/`, `/cs/`, `/en/`), and can be
changed at any time from a language switcher in the top-right of the
centered app container (§ 9.6). Agent 0a detects the language the user is
chatting in and the app auto-switches to it (with a toast notification) the
first time the detection lands on a different language than the one
currently displayed. The agreed story (title, short topic phrase, prose
paragraphs) is authored by Agent 0b in the active language; image concepts
and ComfyUI prompts are always authored in English first (single source of
truth) and accompanied by a same-call translation into the active language
purely for the UI. Subsequent language switches on `/runs/:id` lazily
translate just-in-time via a dedicated **translation agent (Agent 5)** and
cache the result both in Pinia and in the database so the same translation
is never produced twice. See § 5.5, § 7.1 Call 5, § 8.9, § 9.6.

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

The visual output style is anime/manga, rendered by Illustrious-based
SDXL ComfyUI workflows with character and style LoRAs. The app ships
**two** workflows — `single-lora.json` (used when the scene depicts
exactly one human character, optionally accompanied by one non-human
companion) and `no-lora.json` (used when the scene depicts no human
character — i.e. a non-human companion alone, or, rarely, a pure
environment beat with no characters). Agents 1 and 3 decide which
workflow each illustration uses; Agent 0b is responsible for designing
the story so that the resulting mix of workflows is well-motivated
(§ 7.2.1 and § 7.3.11). See § 7.3 for the full creative and prompting
brief.

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
| i18n (FE)   | `vue-i18n` (v9 / Composition API mode) + `vue-router` `/:lang/` path prefix |
| Toasts (FE) | `vue-sonner` (lean, headless-friendly toast library)          |

No specific package versions are pinned in this spec; use current stable
releases at the time of implementation.

All code, identifiers, and code comments are in **English**. UI text
displayed to the end user is **multilingual** — Slovak (`sk`), Czech
(`cs`), and English (`en`) are first-class languages and all
non-AI-generated UI strings exist as keyed messages in
`frontend/src/i18n/locales/{sk,cs,en}.ts`. The chosen language is
reflected in the URL via an always-present `/:lang/` path prefix
(§ 9.6). AI-generated story content (title, topic, paragraphs, image
concepts) is authored in the active language at run-creation time and
translated lazily into other languages on demand (§ 5.5, § 7.1 Call 5).

Throughout this document, **`{lang}`** denotes any one of `sk` / `cs` /
`en`. The set of supported languages is fixed at MVP; adding a new
language is a non-trivial change that touches the locale files, the
`SUPPORTED_LANGUAGES` constant, and the prompt-side language list for
Agent 0a and Agent 5.

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
│   │   │   ├── rethink_concept.md  # Agent 4
│   │   │   └── translate.md        # Agent 5 — on-demand translations
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
│   │   └── workflows/              # ComfyUI workflow files (API format, § 7.2)
│   │       ├── single-lora.json    # 1 human (+ optional companion); LoRA wired in
│   │       └── no-lora.json        # 0 humans (companion-only or environment-only)
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
    │   ├── main.ts                 # Vue + Pinia + vue-i18n + router + toaster
    │   ├── App.vue                 # Mounts <RouterView/> + language switcher + <Toaster/>
    │   ├── router/
    │   │   └── index.ts            # /:lang/ prefix, redirect "/" → "/{detected}/"
    │   ├── stores/
    │   │   ├── session.ts          # Chat session store (i18n-aware welcome)
    │   │   ├── run.ts              # Pinia store for the run page (+ translation cache)
    │   │   └── locale.ts           # Active language + language-switch logic (§ 9.6)
    │   ├── views/
    │   │   ├── HomeView.vue        # Chat / story-skeleton / run-link container
    │   │   └── RunView.vue         # Story + inline placeholders + cards
    │   ├── components/
    │   │   ├── ChatThread.vue
    │   │   ├── ChatMessage.vue
    │   │   ├── ChatComposer.vue
    │   │   ├── StoryBuildingSkeleton.vue # § 9.1 Screen A: "Generating the story on …" + 5 skeletons
    │   │   ├── StoryBlocks.vue         # renders the list of blocks
    │   │   ├── StoryParagraph.vue      # one reactive paragraph block (§ 9.1)
    │   │   ├── InlineIllustration.vue
    │   │   ├── IllustrationCard.vue
    │   │   ├── ConceptPopover.vue      # header info-icon + popover (§ 9.1)
    │   │   ├── SkeletonBlock.vue       # generic skeleton loader (§ 9.1, § 9.3)
    │   │   ├── LanguageSwitcher.vue    # § 9.6 top-right flag + name picker
    │   │   ├── ProgressCounter.vue
    │   │   ├── RunErrorBanner.vue
    │   │   └── CancelButton.vue
    │   ├── services/
    │   │   └── api.ts              # fetch wrappers + SSE EventSource
    │   ├── i18n/
    │   │   ├── index.ts            # vue-i18n setup, detection, route guard helpers (§ 9.6)
    │   │   ├── locales/
    │   │   │   ├── sk.ts
    │   │   │   ├── cs.ts
    │   │   │   └── en.ts
    │   │   ├── runErrors.ts        # error_code → i18n key map
    │   │   └── sessionErrors.ts    # error_code → i18n key map
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
WORKFLOWS_DIR=./app/workflows
AGENTS_DIR=./app/agents
ALLOWED_ORIGIN=http://localhost:5173
```

All keys are required (the app must refuse to start on missing values, with
a clear error message). Provide `.env.example` with placeholder values.

### Frontend

A `.env` for the frontend with `VITE_API_BASE=http://localhost:8000` is
sufficient. No secrets ever live in the frontend. The set of UI languages
is hard-coded in the frontend (`sk`, `cs`, `en`) — not env-configurable.

The Vite dev server proxies `/static` to the backend (see `vite.config.ts`)
so that root-relative `image_url` paths returned by the API (e.g.
`/static/runs/<run_id>/scene_N.png`) load correctly from the page origin
during development.

---

## 5. Data Model

Seven tables (`sessions`, `session_messages`, `runs`, `illustrations`,
`story_translations`, `story_block_translations`,
`illustration_concept_translations`), managed by **Alembic** migrations.
See § 5.0 for the migration workflow; the schema definitions below are
the source of truth and the initial baseline migration must match them
exactly. The three `*_translations` tables are described in § 5.5.

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
| `source_language`     | TEXT NULL    | One of `sk` / `cs` / `en`. Set on the assistant turn whose Agent 0a output first emits a non-`other` `language` field, and again on `phase="confirmed"` (locks the language Agent 0b will author in). Stays `NULL` while still gathering and never seen a concrete language. |
| `topic_short`         | TEXT NULL    | Short ≤8-word topic phrase emitted by Agent 0a on the `phase="confirmed"` turn (in `source_language`). Surfaced to the frontend immediately so the story-skeleton view can render "Generating the story on …" before Agent 0b returns (§ 7.1 Call 0a, § 8.2, § 9.1 Screen A). |
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
| `source_language`   | TEXT         | One of `sk` / `cs` / `en`. The language Agent 0b authored the story in (carried forward from `sessions.source_language`). Acts as the "source of truth" marker: queries for the story in any other language go through the translation tables in § 5.5. |
| `topic_short`       | TEXT         | The short topic phrase from Agent 0a's confirmed turn (in `source_language`). Stored on the run so reloads and snapshots can show "Generating the story on …" even if the user navigates away and back while Agent 0b is still working. |
| `story_title`       | TEXT         | The story's heading, produced by Agent 0b **in `source_language`**. Translations live in `story_translations`. |
| `story_topic_description` | TEXT   | One-sentence English-equivalent topic description produced by Agent 0b in `source_language`. Distinct from `topic_short`: this one is a full sentence Agent 0b expands from the brief, used by the runs UI as a subtitle and by Agent 5 as input when translating. |
| `story_blocks_json` | TEXT         | JSON array of typed blocks (see § 7.1, Call 0b output). Paragraph blocks carry **`source_language`** prose. **Mutable** — when Agent 4 rewrites a paragraph (§ 7.1 Call 4), the orchestrator overwrites the corresponding `paragraph` block's `text` field in this column before continuing the branch. The blocks structure (order, types, scene_index values) never changes after run creation; only individual paragraph `text` values do. Translations of paragraph text live in `story_block_translations` (§ 5.5). |
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
| `initial_concept`        | TEXT         | The concept from Agent 0b **in English** (canonical source of truth); never mutated.   |
| `current_concept`        | TEXT         | Current concept **in English** (changes on concept restart). Translations live in `illustration_concept_translations` (§ 5.5). |
| `state`                  | TEXT (enum)  | See § 6 state values                                                      |
| `concept_attempt`        | INTEGER      | 1..3                                                                      |
| `prompt_attempt`         | INTEGER      | 1..3                                                                      |
| `current_prompts_json`   | TEXT NULL    | Last-used prompts (for debugging/visibility)                              |
| `current_workflow`       | TEXT NULL    | The ComfyUI workflow name chosen for the most recent generate/revise call: `single-lora` or `no-lora` (§ 7.2.1). Persisted so reconnects and snapshots can show which workflow is in flight. NULL until Agent 1 has been called at least once. **Mutable** — Agent 3 may choose a different workflow on revision (rare; usually stays the same across revisions for a given concept). |
| `last_verdict_json`      | TEXT NULL    | Last Claude verdict (for debugging/visibility)                            |
| `image_path`             | TEXT NULL    | Relative path under `OUTPUT_DIR`, e.g. `runs/<run_id>/scene_0.png`        |
| `companion_description`  | TEXT NULL    | The companion's `description` from Agent 0b (or Agent 4 after a rewrite), or NULL if no companion. **Mutable** — Agent 4 may set, change, or clear this. |
| `companion_interaction`  | TEXT NULL    | The companion's `interaction` from Agent 0b (or Agent 4), or NULL. **Mutable** — same as above. |
| `error_message`          | TEXT NULL    | Set on terminal failure                                                   |
| `created_at`             | DATETIME     |                                                                           |
| `updated_at`             | DATETIME     |                                                                           |

### 5.5 Translation tables

Localised copies of every piece of AI-generated text live in dedicated
tables, never as additional columns on `runs` or `illustrations`. This
keeps the source-language schema stable, lets new languages be added
without DDL changes, and avoids per-language column proliferation. The
"source of truth" copy stays in the existing columns
(`runs.story_title`, `runs.story_topic_description`,
`runs.story_blocks_json[].text`, `illustrations.current_concept` /
`initial_concept`); these tables hold the **non-source** language
copies plus a hash of the source text they were translated from, so
the translation client can detect when a stored translation has gone
stale because the source mutated (e.g. an Agent 4 paragraph rewrite,
or — for concepts — an Agent 4 concept change).

All three tables share the same minimal columns:

- `id` — UUID4 primary key.
- `language` — `sk` / `cs` / `en`. The source-language row is NEVER
  stored here; if `runs.source_language == 'sk'`, then no row with
  `language='sk'` exists in any of these tables for that run.
- `source_hash` — SHA-256 (hex, 64 chars) of the source text at the
  time the translation was generated. On read, the server (or the
  client, when it has both) recomputes the hash of the current source
  text and compares: mismatch ⇒ the translation is stale and must be
  refetched via Agent 5.
- `text` — the localised text itself.
- `created_at` / `updated_at` — UTC.

#### `story_translations`

One row per `(run_id, language)`. Carries the run-wide localised
strings.

| Column            | Type         | Notes                                                       |
|-------------------|--------------|-------------------------------------------------------------|
| `id`              | TEXT (UUID4) | Primary key                                                 |
| `run_id`          | TEXT FK      | → `runs.id`                                                 |
| `language`        | TEXT         | `sk` / `cs` / `en`; unique together with `run_id`           |
| `story_title`     | TEXT         | Localised `runs.story_title`                                |
| `story_topic_description` | TEXT | Localised `runs.story_topic_description`                    |
| `story_title_source_hash` | TEXT | SHA-256 of `runs.story_title` at translation time           |
| `story_topic_description_source_hash` | TEXT | SHA-256 of `runs.story_topic_description` at translation time |
| `created_at`      | DATETIME     |                                                             |
| `updated_at`      | DATETIME     | Bumped on every refresh via Agent 5                         |

Unique constraint: `(run_id, language)`.

#### `story_block_translations`

One row per `(run_id, paragraph_index, language)`. `paragraph_index`
is the same 0-based index used by `illustrations.paragraph_index` —
i.e. the position within the *paragraph-only* subset of
`runs.story_blocks_json` in document order. This grants per-paragraph
freshness so Agent 4 rewriting a single paragraph only invalidates
that paragraph's translations, not the whole story.

| Column            | Type         | Notes                                                       |
|-------------------|--------------|-------------------------------------------------------------|
| `id`              | TEXT (UUID4) | Primary key                                                 |
| `run_id`          | TEXT FK      | → `runs.id`                                                 |
| `paragraph_index` | INTEGER      | 0-based index among paragraph blocks                        |
| `language`        | TEXT         | `sk` / `cs` / `en`; unique together with `run_id` + `paragraph_index` |
| `text`            | TEXT         | Localised paragraph text                                    |
| `source_hash`     | TEXT         | SHA-256 of the source paragraph text at translation time    |
| `created_at`      | DATETIME     |                                                             |
| `updated_at`      | DATETIME     | Bumped on every refresh via Agent 5                         |

Unique constraint: `(run_id, paragraph_index, language)`.

#### `illustration_concept_translations`

One row per `(illustration_id, language)`. Carries the localised
*UI-display* concept text. Note: image prompts (Agent 1 / 3 output)
are **never** translated — they go to ComfyUI as Danbooru tags and
must stay in their canonical form. Only the human-readable concept
text shown in the `ConceptPopover` is localised.

| Column             | Type         | Notes                                                       |
|--------------------|--------------|-------------------------------------------------------------|
| `id`               | TEXT (UUID4) | Primary key                                                 |
| `illustration_id`  | TEXT FK      | → `illustrations.id`                                        |
| `language`         | TEXT         | `sk` / `cs` / `en`; unique together with `illustration_id`  |
| `concept`          | TEXT         | Localised `illustrations.current_concept`                   |
| `source_hash`      | TEXT         | SHA-256 of `illustrations.current_concept` at translation time |
| `created_at`       | DATETIME     |                                                             |
| `updated_at`       | DATETIME     | Bumped on every refresh via Agent 5                         |

Unique constraint: `(illustration_id, language)`.

**Eager seeding at run creation.** Because Agent 0b emits each
illustration's `concept` in both English *and* the source language
(§ 7.1 Call 0b), the orchestrator inserts an
`illustration_concept_translations` row at run creation **only if**
`runs.source_language != 'en'`. When the source language is English,
no row is needed (English IS the source). The same eager seed applies
when Agent 4 returns a new concept (it returns the English source AND
the same-language translation) — the orchestrator updates / inserts
the source-language translation row alongside the English-source
update. Other languages remain absent until the user actually
requests them via § 8.9.

**Staleness rule for reads.** When the client requests the runs
snapshot in `language=L` (§ 8.3) and `L != runs.source_language`:

- For each translatable field, look up its `*_translations` row.
- If the row is absent → that field is **missing in `L`**; the server
  returns the source-language value and flags the gap so the client
  knows to fetch via § 8.9.
- If the row is present but the recomputed source hash does not match
  the stored `source_hash` → that field is **stale in `L`**; the
  server returns the stored stale text PLUS a flag so the client can
  display the stale value immediately and trigger a background
  refresh.

The "show stale + refetch in background" behavior is what gives the
user the requested experience of never staring at an empty paragraph
while Agent 5 is working — they see the previous translation and it
silently updates in place once Agent 5 returns.

#### Indexes

- `story_translations`: composite index on `(run_id, language)` (also
  the unique constraint).
- `story_block_translations`: composite index on
  `(run_id, language, paragraph_index)`.
- `illustration_concept_translations`: index on
  `(illustration_id, language)` (also the unique constraint).

These indexes serve the dominant access pattern: "give me everything
needed to render run X in language L".

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

### 7.1 Anthropic Messages API (7 distinct calls)

All calls use `claude-sonnet-4-6`. Each agent's full system prompt lives
in a Markdown file under `backend/app/agents/` and is loaded at startup
by `services/claude.py` (see § 7.4). The Pydantic schemas below are the
binding wire contracts; the prose in each agent's `.md` file must produce
output that validates against the corresponding schema.

Strict JSON-only output is enforced for **Calls 0b through 5** via the
system prompt; **Call 0a (chat) returns a JSON envelope whose `reply`
field is free-form prose in the active user language** — see Call 0a
below. Every JSON response is validated with Pydantic, with up to
`CLAUDE_JSON_RETRY` (= 2) re-prompts on parse failure before treating
it as an error.

For the `evaluate_image` call, the image is passed as a base64 image block
alongside the text content.

#### Call 0a — `chat` (Agent 0a, "the assistant")

**Purpose:** Conversational gathering of the story brief: the cast (subject
to § 7.3.2) and the overall topic/concept. Detects when enough has been
agreed, proposes a summary, and detects the user's natural-language
confirmation. Additionally **detects the user's chat language** and
emits a short topic phrase on the confirmation turn so the frontend can
render the story-skeleton view (§ 9.1 Screen A) before Agent 0b runs.

**Input (to Claude):**
- The full system prompt from `agents/chat.md`.
- The full prior message transcript of the session, mapped to Claude
  `messages`. The welcome message is **not** part of the transcript
  sent to Claude — it lives only in the frontend (§ 9.6.2). The first
  turn the model sees is therefore always the user's first message.
- The freshly POSTed user message as the last `user` turn.

**Output schema:**
```json
{
  "reply": "string (chat reply, free-form prose, in the same language as the user's latest message)",
  "phase": "gathering" | "awaiting_confirmation" | "confirmed",
  "language": "sk" | "cs" | "en" | "other" | null,
  "topic_short": "string (≤8 words, in the detected language, only on phase='confirmed')" | null,
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

**`language` semantics:**

- Set to one of `sk` / `cs` / `en` when the model has enough signal from
  the latest user turn to classify with confidence.
- Set to `other` when the user clearly wrote in a language outside the
  supported set (Polish, Hungarian, German, etc.). The frontend treats
  `other` as "fall back to English" (§ 9.6.3).
- Set to `null` only when the model lacks signal — e.g. the first turn
  is a one-word emoji or pure punctuation. The frontend keeps its
  current language until a future turn provides signal.
- **Emission policy (server-enforced):** the agent emits a non-null
  `language` on (a) the **first turn at which it can classify** and
  (b) the **`phase="confirmed"` turn** (re-emitted so the server can
  lock the source language for Agent 0b even if the user switched
  languages mid-chat). On every other turn the field MAY be `null`;
  the backend ignores `null` values and keeps `sessions.source_language`
  unchanged. When the model emits a non-null value, the backend writes
  it to `sessions.source_language` only on the two emission points
  above; intermediate emissions are persisted to the message row only
  (so the frontend can react via the auto-switch flow, § 9.6.3) and do
  not overwrite `sessions.source_language` until the confirmed turn
  locks it in.

**`topic_short` semantics:**

- Emitted only on `phase="confirmed"`. On every other phase the field
  MUST be `null`.
- Written in the detected `language` (or English if `language="other"`).
- Concise: ≤ 8 words, capturing the topic in headline form (e.g.
  *"Mladý hrdina v lete na vidieku"*, *"A girl saying goodbye to her
  cat"*). The frontend renders this verbatim in the story-skeleton
  view as: *"Generating the story on … "* / *"Vytváram príbeh o …"* /
  *"Vytvářím příběh o …"*.

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
  turn). `topic_short` is set (per the rules above).

  **The model is instructed to leave `reply` empty (`""`) on the
  confirmed turn.** The chat-thread message shown to the user is a
  fixed deterministic per-language acknowledgment that lives on the
  frontend (`i18n.t('chat.confirmedAck')` — see § 9.6.2). The backend
  also keeps a server-side copy of the same per-language strings in
  `app/constants.py` as `CONFIRMED_ACK[lang]` (Slovak: "Skvelé, ide na
  to. Pripravujem príbeh a ilustrácie…"; Czech: "Skvělé, jdeme na to.
  Připravuji příběh a ilustrace…"; English: "Great, let's do it.
  Preparing the story and illustrations…"). On `phase="confirmed"`
  the server normalizes whatever the model wrote in `reply` to
  `CONFIRMED_ACK[sessions.source_language]` (falling back to `en` if
  the session's source language is `NULL` or `other`) before
  persisting, so reloads from the database show the canonical string.
  The frontend ignores the persisted `reply` in favor of
  `i18n.t('chat.confirmedAck')` and only displays the persisted text
  as a fallback if i18n is misconfigured. This is what the frontend
  keys off to auto-start the pipeline (§ 9.1 Screen A): `phase` is a
  categorical machine marker; the acknowledgment prose is purely UI.

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

**Input (to Claude):** a JSON user turn containing
- the validated `collected_brief` from Agent 0a;
- `source_language` — the value the server resolved on the confirmed
  turn (`sk` / `cs` / `en`; never `null` or `other` here — see § 8.2
  for how the server resolves these cases before invoking Agent 0b);
- `topic_short` — for Agent 0b's situational awareness (it must not
  echo this verbatim, but the story should clearly be *on this topic*).

**Output schema:**
```json
{
  "story": {
    "title": "string (in source_language)",
    "topic_description": "string (one full sentence, in source_language)",
    "blocks": [
      { "type": "paragraph", "text": "string (in source_language)" },
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
      "scene_excerpt": "string (verbatim slice of the source-language story prose this illustration depicts)",
      "concept": "string (the canonical English concept — single source of truth, used by Agents 1 / 2 / 3)",
      "concept_localized": "string (the same concept in source_language; used by the UI ConceptPopover; same meaning, idiomatic phrasing) | null when source_language='en'",
      "character_role": "male" | "female" | "mother" | null,
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
5. **Cast.** Every non-null `character_role` used in `illustrations`
   must correspond to a character present in the approved brief. If the
   brief has no `mother`, no illustration may have
   `character_role="mother"`. **`character_role` MAY be `null`** for an
   illustration whose visible subject is the companion alone, or — very
   rarely — a pure environment beat with no characters at all (see
   rules #12 / #13 below).
6. **Specificity of expression / gesture / action** (§ 7.3.4) applies
   to every illustration that includes either a human character
   (`character_role != null`) or a companion. Each such `concept` must
   explicitly mention at least one concrete facial expression,
   gesture/posture, or action. For the rare pure-environment beat
   (rule #13), the concept must instead name a concrete, depictable
   moment in the *environment* (lighting, weather, a specific object
   in frame).
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
12. **Per-illustration cast triplet (workflow-driving).** Every
    illustration falls into exactly one of three cast shapes:
    - **Single human + optional companion** — `character_role` is one
      of `male` / `female` / `mother`; `companion` is null or set.
      This is the dominant shape; the `single-lora.json` workflow
      renders it (§ 7.2.1).
    - **Companion alone** — `character_role` is `null`; `companion` is
      set. Rendered by `no-lora.json`. Used for beats where the
      companion's *own* presence (the cat asleep on the bed; the
      dragon perched on a rooftop watching) carries the moment.
    - **No characters** — `character_role` is `null`; `companion` is
      `null`. Rendered by `no-lora.json`. **Rare** — reserved for
      story-essential environment beats (the empty classroom after
      she left; the storm rolling in over the harbor). Multiple
      character-less illustrations in the same run are discouraged;
      Agent 0b should not produce more than one such scene unless the
      story arc strongly motivates it.
13. **Workflow distribution discipline.** Agent 0b implicitly
    determines the workflow each illustration will use via the cast
    shape it returns (rule #12). It must design the story so that the
    overall mix is sensible: most illustrations should feature a
    human character. A run where 4-out-of-5 illustrations are
    character-less environment beats is rejected at validation time
    as poorly aligned with the app's purpose. The server caps
    `no-human` illustrations (i.e. `character_role == null`) at
    **≤ 2 out of 5** and re-prompts on violation.

Unlike the previous spec, Agent 0b **does not** have a "no suitable
scenes" escape hatch. The brief has already been negotiated and confirmed
in Call 0a; the storyteller's job is to deliver. Output that violates the
hard rules above is treated as a Claude failure (`STORY_BUILD_FAILED`).

#### Call 1 — `generate_prompts`

**Input:** `current_concept` (English — single source of truth),
`style_guide`, `character_role` (`male` / `female` / `mother` / `null` —
when `null`, the agent treats the illustration as character-less; see
rule below), and the optional `companion` (`{ description, interaction }
| null`) attached to the illustration. When `companion` is non-null the
agent must incorporate it per § 7.3.10 (companion prompting guidance)
and apply the conditional adjustments to the negative baseline
described in § 7.3.6.

**Output schema:**
```json
{
  "positive": "string",
  "negative": "string",
  "workflow": "single-lora" | "no-lora"
}
```

The `positive` field is the full per-scene positive prompt (character +
environment + action + expression + companion if any, all expressed as
Danbooru tags — *always in English*, regardless of the run's source
language). The `negative` field is the full per-scene negative prompt.
Style-level tags are NOT included here — they live in `style_guide` and
are composed in by the workflow itself (see § 7.2). See § 7.3.4 and
§ 7.3.10 for the content requirements that this prompt must satisfy.

**`workflow` selection rule (hard-enforced):**

- Return `"single-lora"` **iff** `character_role` is non-null (i.e. the
  illustration shows exactly one human character — optionally
  accompanied by one non-human companion). The character LoRA wiring
  is taken from `character_config[role]` (§ 7.3.7) and the
  `CHARACTER_LORA` placeholder is filled in by the workflow runner.
- Return `"no-lora"` **iff** `character_role` is `null` (i.e. the
  illustration shows no human — either the companion alone, or no
  characters at all). The `no-lora.json` workflow does not have a
  `CHARACTER_LORA` placeholder (§ 7.2.1).

Any other combination (e.g. `workflow="single-lora"` with
`character_role=null`, or `workflow="no-lora"` with a non-null
`character_role`) is rejected server-side and re-prompted up to
`CLAUDE_JSON_RETRY` times. The agent is told the rule is *purely
mechanical* and gives no creative latitude — workflow follows directly
from `character_role`.

#### Call 2 — `evaluate_image`

**Input:** image (base64), `current_concept` (English), `style_guide`,
`character_role` (`male` / `female` / `mother` / `null`), and the
illustration's `companion` (`{ description, interaction } | null`). The
agent's checklist is companion-aware **and cast-aware** (§ 7.3.5 items
1a + 1b + 1c).

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

**Input:** current `prompts`, last `verdict`, `current_concept`
(English), `style_guide`, `character_role` (`male` / `female` /
`mother` / `null`), and the illustration's `companion` (`{ description,
interaction } | null`). When `companion` is non-null the same companion
guidance applies as in Call 1 (§ 7.3.10 + the § 7.3.6 conditional
negative adjustments).

**Output schema:** same as Call 1 (i.e. `{ positive, negative,
workflow }`). The `workflow` selection rule is identical to Call 1 and
is hard-enforced server-side. Agent 3 almost always returns the same
workflow as the previous attempt — it has no reason to switch
workflows just because a prompt failed — but the field is still
required and re-validated to keep the contract uniform.

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
- `source_language` — `runs.source_language`. Tells Agent 4 which
  language the rewritten paragraph and the localized concept must be
  authored in. The canonical concept is still English (single source
  of truth for Agents 1 / 2 / 3); the paragraph and the
  `concept_localized` go in `source_language`.

**Output schema:**
```json
{
  "concept": "string (canonical English concept, meaningfully different from failed_concept)",
  "concept_localized": "string (the same concept in source_language) | null when source_language='en'",
  "paragraph_text": "string (the rewritten paragraph that replaces current_paragraph_text, in source_language)",
  "scene_excerpt": "string (a verbatim substring of paragraph_text — the new excerpt this concept depicts)",
  "character_role": "male" | "female" | "mother" | null,
  "companion": {
    "description": "string (must match an entry in companions_pool)",
    "interaction": "string (concrete visual relationship in the new scene)"
  } | null
}
```

`character_role` is **also rewritable** by Agent 4 (it was already in
Call 4's narrative scope but was implicit; making it explicit clarifies
that Agent 4 can switch a scene from human-with-companion to
companion-alone — and vice versa — as long as the resulting cast
shape (Call 0b rule #12) is one of the three permitted triplets, and
the global per-run cap of ≤ 2 character-less illustrations (Call 0b
rule #13) is still respected across the run after applying this
change). The orchestrator persists the new `character_role` on the
illustration row and uses it on the subsequent Call 1 / Call 3, which
in turn updates `current_workflow`.

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

Agent 4's `concept_localized` and `paragraph_text` together replace
the corresponding source-language texts and **invalidate** any
existing translations for the same paragraph and concept in
`story_block_translations` / `illustration_concept_translations`
(their `source_hash` no longer matches). The orchestrator does not
proactively call Agent 5; staleness is resolved lazily on the next
read in a non-source language (§ 5.5, § 8.9).

#### Call 5 — `translate` (Agent 5, "the translator")

**Purpose:** Translate AI-generated story content from its
`source_language` into a requested target language. Invoked lazily,
only when the user is viewing `/runs/:id` and switches into a
language for which not every piece of content has an up-to-date
translation. The contract is intentionally generic so a single call
can refresh anywhere from one paragraph to the entire story.

**When NOT to call:** Agent 5 is *only* invoked from the
`POST /api/runs/{run_id}/translations` endpoint (§ 8.9). It is never
invoked from the chat phase, from finalize, from any branch state
transition, or from Agent 4. The chat phase has its own i18n flow
(detection + auto-switch + frontend-localized welcome / ack), and
the initial run-creation already emits source-language + English
content, so Agent 5 is exclusively for *later* language switches.

**Input (to Claude):** a JSON user turn containing
- `source_language` — the run's source language;
- `target_language` — one of `sk` / `cs` / `en`; never equal to
  `source_language`;
- `items` — an ordered array describing each piece of text to
  translate. The shape is polymorphic so a single call can mix kinds:
  ```json
  [
    { "kind": "story_title", "text": "string" },
    { "kind": "story_topic_description", "text": "string" },
    { "kind": "paragraph", "paragraph_index": 0, "text": "string" },
    { "kind": "illustration_concept", "scene_index": 0, "text": "string" }
  ]
  ```
  `text` is always the **current source-language value** of the
  field. The backend selects items based on the staleness rule
  (§ 5.5) and the client's request payload (§ 8.9).
- `context` — a small JSON envelope carrying the run's
  `story_title` and `story_topic_description` in the source language
  (even when those are themselves being translated in this call).
  This gives Agent 5 enough thematic context to keep tone and proper
  nouns consistent across items.

**Output schema:**
```json
{
  "items": [
    { "kind": "story_title", "text": "string (translated)" },
    { "kind": "story_topic_description", "text": "string (translated)" },
    { "kind": "paragraph", "paragraph_index": 0, "text": "string (translated)" },
    { "kind": "illustration_concept", "scene_index": 0, "text": "string (translated)" }
  ]
}
```

Hard rules enforced by the prompt and re-checked server-side:

1. **Same length and order.** `output.items` has exactly the same
   length as `input.items`, in the same order, with each item's
   `kind` matching the input position. Items that identify a
   position (`paragraph_index`, `scene_index`) preserve that
   identifier verbatim. Mismatches are rejected and re-prompted.
2. **No translation drift.** The translator must preserve the
   meaning, tone, register, and proper nouns of the source. The
   shared persona-fragment from `build_story.md` (and
   `rethink_concept.md`) is embedded in `translate.md` so the
   translated prose matches the voice of the authored prose.
3. **Idiomatic target language.** Output is fluent target-language
   prose, not a literal word-for-word translation. Names of human
   characters (`name_in_story`) are kept verbatim; only generic nouns
   and verbs are rendered idiomatically.
4. **No additions.** The translator must not invent new content,
   editorialize, or add explanatory footnotes. Length parity is not
   required, but the translation must cover the source's meaning
   completely.
5. **Concept translations are still UI text, not prompts.** The
   `illustration_concept` items translate the human-readable concept
   text shown in the `ConceptPopover`. They are **never** sent to
   ComfyUI; the canonical English concept stays the source of truth
   for image generation. The translator is reminded explicitly that
   Danbooru tag syntax is not the goal here — prose is.
6. **Empty input is rejected.** `items` must be non-empty. The
   backend never sends an empty array; if all items are fresh, the
   endpoint returns immediately without calling Claude (§ 8.9).

The orchestrator persists the returned items into the appropriate
`*_translations` tables (creating or updating rows by
`(run_id, language[, paragraph_index | illustration_id])`) with the
freshly-computed `source_hash` of each input `text`. If the source
text changes again later (Agent 4 rewrite), the next read in that
language detects the stale `source_hash` and triggers another Agent 5
call (§ 5.5).

### 7.2 RunPod ComfyUI Serverless

The app ships **two** workflow files in `app/workflows/`, both in
**ComfyUI API format**:

- `single-lora.json` — single human character (optionally accompanied
  by one non-human companion). The character LoRA is wired in via the
  `CHARACTER_LORA` placeholder.
- `no-lora.json` — no human character (companion alone, or pure
  environment). No character LoRA is referenced in this file; the
  `CHARACTER_LORA` placeholder is **not** present.

Both workflows share the same five placeholder strings (some optional)
that the workflow runner replaces recursively (matching by exact string
equality, regardless of JSON path):

- `POSITIVE_PROMPT`           (required in both files)
- `NEGATIVE_PROMPT`           (required in both files)
- `CHARACTER_LORA`            (required in `single-lora.json`; absent in `no-lora.json`)
- `STYLE_POSITIVE_PROMPT`     (required in both files)
- `STYLE_NEGATIVE_PROMPT`     (required in both files)

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
| `CHARACTER_LORA`                | `character_config[role].lora_filename` (see § 7.3.7) — used only by `single-lora.json` |
| `STYLE_POSITIVE_PROMPT`         | Call 0b → `style_guide.overall_style_positive` |
| `STYLE_NEGATIVE_PROMPT`         | Call 0b → `style_guide.overall_style_negative` |

If a placeholder is not found in the workflow JSON, log a warning but
continue. Track which placeholders were found, for diagnostics.

#### 7.2.1 Workflow selection

The workflow used for a given illustration is determined by Agent 1
(and confirmed by Agent 3 on revision) via the `workflow` field of
Call 1 / Call 3's output (§ 7.1). The choice is **purely mechanical**
and follows from `illustrations.character_role`:

| `character_role`             | Workflow            | Cast shape (per Call 0b rule #12)              |
|------------------------------|---------------------|-------------------------------------------------|
| `male` / `female` / `mother` | `single-lora.json`  | Single human + optional companion              |
| `null`                       | `no-lora.json`      | Companion alone, or no characters at all       |

Server-side enforcement:

1. The workflow runner picks the workflow file by mapping the
   agent-returned `workflow` string (`"single-lora"` / `"no-lora"`)
   to `${WORKFLOWS_DIR}/single-lora.json` /
   `${WORKFLOWS_DIR}/no-lora.json` respectively.
2. Before dispatch, it verifies that the agent's choice matches the
   illustration's current `character_role`:
   - `single-lora` ⇔ non-null role,
   - `no-lora`     ⇔ null role.
   A mismatch is treated as a Claude failure and re-prompted up to
   `CLAUDE_JSON_RETRY` times (§ 7.1 Call 1). If the agent still
   misclassifies, the branch transitions to `FAILED` with a
   `current_workflow=NULL` row and an informative `error_message`.
3. `illustrations.current_workflow` is set to the agent-returned
   value once verification passes, so reconnects and snapshots
   accurately reflect which workflow is rendering each scene.
4. When the agent returns `"single-lora"` but the workflow JSON has
   no `CHARACTER_LORA` placeholder (or vice versa: returns
   `"no-lora"` but the JSON unexpectedly has `CHARACTER_LORA`), the
   workflow runner refuses to dispatch and logs a clear error — this
   protects against the wrong file being shipped under the wrong
   name.

Per-language note: the workflow files are language-agnostic. Prompts
go to ComfyUI in English regardless of the run's `source_language`
(see Call 1 output rules and § 7.3.1).

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

Each illustration falls into one of three permitted cast shapes
(§ 7.1 Call 0b rule #12):

1. **Single human + optional companion** — dominant shape. One of the
   three permitted human character roles, optionally accompanied by
   exactly one non-human, non-anthropomorphic companion drawn from the
   run's brief pool. Rendered by `single-lora.json` (§ 7.2.1).
2. **Companion alone** — no human character; exactly one non-human
   companion from the brief's pool is the visible subject. Rendered by
   `no-lora.json`.
3. **No characters** — *rare*; reserved for story-essential environment
   beats. No human, no companion. Rendered by `no-lora.json`. Capped at
   ≤ 2 per run by Call 0b rule #13.

Scenes with multiple human characters, group scenes, crowds, scenes
with multiple non-human entities visible, and scenes whose subject is
ambiguous are excluded under all three shapes.

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
`backend/app/agents/`. There are seven files, one per call in § 7.1:

| File                  | Agent | Call name           |
|-----------------------|-------|---------------------|
| `chat.md`             | 0a    | `chat`              |
| `build_story.md`      | 0b    | `build_story`       |
| `generate_prompts.md` | 1     | `generate_prompts`  |
| `evaluate_image.md`   | 2     | `evaluate_image`    |
| `revise_prompts.md`   | 3     | `revise_prompts`    |
| `rethink_concept.md`  | 4     | `rethink_concept`   |
| `translate.md`        | 5     | `translate`         |

Loading rules:

- `services/claude.py` reads all seven files at process startup and caches
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
5. For Agent 0a only: an explicit reminder that `reply` is prose in
   the user's language and must not contain JSON, headings, or scene
   lists; plus the language-detection / `topic_short` rules from § 7.1
   Call 0a.
6. For Agents 0b through 5: an explicit reminder that the only output
   is the JSON object — no Markdown fences, no prefatory text, no
   trailing commentary.
7. For Agent 5 (`translate.md`): the embedded persona-fragment from
   `build_story.md` (so translated prose matches the authored voice)
   and the list of supported `target_language` codes.

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
1. Create a `sessions` row with `state=CHATTING` and
   `source_language=NULL`. The welcome message is **not** persisted
   here — it lives only on the frontend (§ 9.6.2).
2. Insert the user's message as the first row (`role=user`).
3. Synchronously invoke Agent 0a with the transcript so far.
4. Persist the assistant reply (second row) with the returned `phase`.
5. If Agent 0a's response carries a non-null `language`:
   - If `language` is one of `sk` / `cs` / `en`, write it to
     `sessions.source_language` (overwriting the previous value).
   - If `language` is `"other"`, write `"en"` to
     `sessions.source_language` (Agent 0b authors in English when the
     user's actual language is unsupported).
   The `language` value itself is also returned in the response so
   the frontend can drive the auto-switch flow (§ 9.6.3).
6. If `phase=confirmed` against the rules in § 7.1 Call 0a, the server
   downgrades it (see § 7.1 Call 0a server-side guard).
7. If `phase=confirmed` (legitimately): the server normalizes `reply`
   to the per-language `CONFIRMED_ACK` constant (§ 7.1 Call 0a) and
   writes `topic_short` to `sessions.topic_short`. The response
   returns the acknowledgment reply, the `topic_short`, and the
   resolved `source_language`; the client is expected to follow up
   with `POST /api/sessions/{id}/finalize` (§ 8.2). The backend does
   NOT auto-finalize.

Response 201:
```json
{
  "session_id": "uuid",
  "state": "CHATTING" | "AWAITING_CONFIRMATION" | "BUILDING_STORY",
  "source_language": "sk" | "cs" | "en" | null,
  "detected_language": "sk" | "cs" | "en" | "other" | null,
  "topic_short": "string" | null,
  "messages": [
    { "id": "uuid", "order_index": 0, "role": "user", "phase": null, "content": "string", "created_at": "iso" },
    { "id": "uuid", "order_index": 1, "role": "assistant", "phase": "gathering" | "awaiting_confirmation" | "confirmed", "content": "string", "created_at": "iso" }
  ]
}
```

`source_language` reflects `sessions.source_language` *after* the
server's normalization (§ 8.1 step 5). `detected_language` is the
raw `language` value Agent 0a returned on this turn — exposed
separately so the frontend can detect mismatches and trigger the
auto-switch + toast (§ 9.6.3). `topic_short` is non-null only when
the assistant reply's `phase` is `"confirmed"`.

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
  "source_language": "sk" | "cs" | "en" | null,
  "detected_language": "sk" | "cs" | "en" | "other" | null,
  "topic_short": "string" | null,
  "user_message": { "id": "uuid", "order_index": N, "role": "user", "phase": null, "content": "string", "created_at": "iso" },
  "assistant_message": { "id": "uuid", "order_index": N+1, "role": "assistant", "phase": "gathering" | "awaiting_confirmation" | "confirmed", "content": "string", "created_at": "iso" }
}
```

Same i18n semantics as `POST /api/sessions`: `source_language` is the
post-normalization value persisted on the session;
`detected_language` is the raw `language` from this turn's Agent 0a
output; `topic_short` is non-null only when `assistant_message.phase
=== "confirmed"`. See § 9.6.3 for the frontend auto-switch flow.

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
    "source_language": "sk|cs|en|null",
    "topic_short": "string|null",
    "run_id": "uuid|null",
    "error_code": "string|null",
    "error_message": "string|null",
    "created_at": "iso",
    "updated_at": "iso"
  },
  "messages": [ { "id", "order_index", "role", "phase", "content", "created_at" } ]
}
```

The session row carries `source_language` and `topic_short` so a
direct navigation to `/runs/:id` (or a reload of the chat page after
confirmation) can render the story-skeleton view (§ 9.1 Screen A)
correctly while Agent 0b is still working.

### 8.2 Finalize — chat → run handoff

#### `POST /api/sessions/{id}/finalize`

Triggered by the frontend after the user has confirmed (i.e. after a
message exchange that landed on `state=AWAITING_CONFIRMATION` followed
by a user reply that produced an `assistant_message.phase=confirmed`).

Behavior (non-blocking — returns as soon as the building-story
intent is recorded, so the frontend can switch from the chat thread
to the story-skeleton view immediately):

1. Reject with 409 if session is not in a confirmable state. A
   confirmable session is one whose latest assistant message has
   `phase=confirmed`, and whose `state` is one of
   `AWAITING_CONFIRMATION` or `CHATTING` (the latter occurs because
   step 2 below has not yet run).
2. Resolve `source_language`: if `sessions.source_language` is
   `NULL` (the user never gave detectable signal), default to `"en"`
   and write it back to the session. Already-resolved values
   (including `"en"` previously coerced from `"other"`) are kept
   verbatim.
3. Transition session to `state=BUILDING_STORY`. Persist
   `source_language` and `topic_short` on the session row if not
   already persisted (the latter was set on the confirmed turn, so
   this is usually a no-op).
4. Respond **202 Accepted** with the resolved language + topic. The
   server then *asynchronously* (background task) invokes Agent 0b
   and, on success, creates the `runs` + `illustrations` rows,
   transitions the session to `COMPLETED` + `run_id=<id>`, and
   begins the per-illustration branches (§ 6). On Agent 0b failure
   after retries it transitions the session to `FAILED` with
   `error_code=STORY_BUILD_FAILED`.
5. The frontend learns the eventual outcome via a session-level
   SSE stream (`GET /api/sessions/{id}/events`, § 8.2.1).
   Specifically: a `story_built` event carries the new `run_id`
   when Agent 0b succeeds (the frontend then navigates to
   `/runs/:run_id`); a `story_build_failed` event carries the
   `error_code` / `error_message` when it does not.

Response 202:
```json
{
  "session_id": "uuid",
  "state": "BUILDING_STORY",
  "source_language": "sk" | "cs" | "en",
  "topic_short": "string"
}
```

Errors:
- 404 if session does not exist.
- 409 if session is not in a confirmable state.
- 500 if scheduling the background task itself fails
  (`error_code=INTERNAL_ERROR`). Agent 0b failures do not surface as
  HTTP errors here — they surface via the SSE stream in § 8.2.1.

#### 8.2.1 `GET /api/sessions/{id}/events` (SSE)

Session-level SSE stream used by the frontend during the
`BUILDING_STORY` phase. The stream opens once the client receives
the 202 from `POST /api/sessions/{id}/finalize` and closes on the
first terminal event.

On connection, the server emits a synthetic `session_snapshot`
event built from the current session row, so reconnects pick up the
latest state without races.

| Event                  | Payload                                                                          |
|------------------------|----------------------------------------------------------------------------------|
| `session_snapshot`     | `{ "state", "source_language", "topic_short", "run_id" \| null, "error_code" \| null, "error_message" \| null }` |
| `story_built`          | `{ "run_id": "uuid" }` — Agent 0b succeeded; the run is ready                    |
| `story_build_failed`   | `{ "error_code": "STORY_BUILD_FAILED", "error_message": "string" }`              |
| `heartbeat`            | `{}` every 15 s                                                                  |

The stream closes after `story_built` or `story_build_failed`. The
frontend then closes the EventSource and either navigates to
`/runs/:run_id` or shows the session error banner (§ 9.1 Screen A).

### 8.3 `GET /api/runs/{run_id}?lang={lang}`

Returns a snapshot of the run and all its illustrations. Used by the
frontend on reconnect / direct navigation. The `lang` query parameter
is optional and defaults to the run's `source_language`. Accepted
values: `sk` / `cs` / `en`.

Response 200:
```json
{
  "run": {
    "id": "uuid",
    "session_id": "uuid",
    "status": "RUNNING|COMPLETED|FAILED|CANCELLED",
    "source_language": "sk|cs|en",
    "language": "sk|cs|en",
    "story_title": "string (in `language`)",
    "story_title_translation_state": "source|fresh|stale|missing",
    "story_topic_description": "string (in `language`)",
    "story_topic_description_translation_state": "source|fresh|stale|missing",
    "topic_short": "string (in source_language; not translated by Agent 5)",
    "story_blocks": [
      { "type": "paragraph", "paragraph_index": 0, "text": "string (in `language`)", "translation_state": "source|fresh|stale|missing" },
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
      "scene_excerpt": "string (in `language`)",
      "paragraph_index": 0,
      "character_role": "male|female|mother|null",
      "current_concept": "string (in `language` — UI-display concept; the canonical English source is on the server, never sent)",
      "current_concept_translation_state": "source|fresh|stale|missing",
      "current_workflow": "single-lora|no-lora|null",
      "state": "PENDING|...|COMPLETED|FAILED|CANCELLED",
      "concept_attempt": 1,
      "prompt_attempt": 1,
      "image_url": "string|null",
      "companion": { "description": "string", "interaction": "string" } | null
    }
  ]
}
```

`translation_state` semantics (per § 5.5):

- `"source"` — `language == run.source_language`; the field is the
  canonical source. No translation row consulted.
- `"fresh"` — translation row exists and its `source_hash` matches
  the current source. The returned text is the up-to-date
  translation.
- `"stale"` — translation row exists but its `source_hash` does NOT
  match (source mutated since translation). The returned text is the
  stored *stale* translation; the client should call § 8.9 in the
  background to refresh.
- `"missing"` — no translation row exists. The returned text is the
  source-language fallback; the client should call § 8.9 to fill
  the gap.

Notes:

- `topic_short` is intentionally never translated by Agent 5 — it is
  a confirmation-time string that lives only as a "Generating the
  story on …" header before the run actually exists in `runs`. By
  the time the user lands on `/runs/:id`, the skeleton is already
  gone and `topic_short` is purely an archival/snapshot field; the
  UI uses `story_topic_description` instead.
- `current_concept` returned here is the **UI-display** concept in
  the requested language. The English canonical concept is not part
  of this response (it stays server-side for Agents 1/2/3). Only
  the staleness machinery uses it.
- `scene_excerpt` follows the same translation logic as paragraphs
  (it is conceptually a "view" of a paragraph): for the requested
  language, the server computes the excerpt from the localised
  paragraph text by finding the same character range. When the
  paragraph translation is `missing` or `stale`, the excerpt is
  returned in the source language together with the appropriate
  `translation_state` carried on the paragraph block.

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

### 8.4 `GET /api/runs/{run_id}/events?lang={lang}`  (SSE)

(Unchanged contract from previous spec; payload shape updated to match
§ 8.3.)

The optional `lang` query parameter selects which language all
language-bearing payloads are rendered in (defaults to the run's
`source_language`). The server uses the same translation-resolution
logic as § 8.3 — present-translation, stale-translation, or
source-fallback are all valid and are flagged via `translation_state`
fields where applicable. Two clients on the same run may subscribe in
different languages independently.

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
| `snapshot`                  | `{ "run": {...}, "illustrations": [...] }` — same shape as § 8.3, in subscriber's `lang` |
| `illustration_state`        | `{ "illustration_id", "scene_index", "state", "concept_attempt", "prompt_attempt", "current_concept", "current_concept_translation_state", "scene_excerpt", "current_workflow" }` |
| `paragraph_updated`         | `{ "paragraph_index", "text", "translation_state" }`                    |
| `illustration_companion_updated` | `{ "illustration_id", "scene_index", "companion": { "description", "interaction" } \| null }` |
| `illustration_role_updated` | `{ "illustration_id", "scene_index", "character_role": "male\|female\|mother\|null" }` — emitted only when Agent 4 swaps a scene's cast shape |
| `translations_refreshed`    | `{ "language", "items": [ { "kind": "story_title\|story_topic_description\|paragraph\|illustration_concept", "paragraph_index"?: N, "scene_index"?: N, "text": "string" } ] }` — emitted to every subscriber after § 8.9 completes, so multi-tab views in the same language stay in sync |
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

### 8.9 `POST /api/runs/{run_id}/translations`

On-demand translation endpoint that backs the runs-view language
switcher. Invoked by the frontend whenever the user switches to a
language for which some piece of run content is `missing` or `stale`
(per § 5.5 / § 8.3). May also be called proactively by the FE on
mount when the requested language is non-source.

Request body:

```json
{
  "target_language": "sk" | "cs" | "en",
  "items": [
    { "kind": "story_title" },
    { "kind": "story_topic_description" },
    { "kind": "paragraph", "paragraph_index": 0 },
    { "kind": "illustration_concept", "scene_index": 0 }
  ]
}
```

- `target_language` must differ from the run's `source_language`. A
  request with `target_language == run.source_language` is rejected
  with **400** (nothing to translate).
- `items` is non-empty and lists exactly the fields the client wants
  refreshed. The server looks up the *current source-language* value
  of each item, builds the Agent 5 input (§ 7.1 Call 5), and on
  success persists each result into the corresponding translation
  table (creating or updating the row keyed by the item's natural
  identifier) with a freshly-computed `source_hash`.
- Items the server already considers `fresh` (existing row, matching
  `source_hash`) are **skipped silently** — the server filters them
  out of the Agent 5 input. This is the "never translate twice"
  guarantee: if a tab races to call this endpoint with items another
  tab has already refreshed, the second tab's call is effectively a
  no-op for those items.
- If the resulting filtered input is empty (all requested items are
  already fresh), the server skips Agent 5 entirely and returns 200
  with the current values from the translation tables.

Response 200:

```json
{
  "target_language": "sk",
  "items": [
    { "kind": "story_title", "text": "string (translated)" },
    { "kind": "paragraph", "paragraph_index": 0, "text": "string (translated)" },
    { "kind": "illustration_concept", "scene_index": 0, "text": "string (translated)" }
  ]
}
```

The response items mirror the *resolved* state of every requested
item — whether it was freshly translated by this call or already
fresh in the DB. The frontend writes each item to the same place in
its Pinia store regardless of whether Agent 5 actually ran.

Errors:

- 400 if `target_language` equals `run.source_language`, if
  `items` is empty, if an unknown `kind` appears, or if an item
  identifier (`paragraph_index` / `scene_index`) is out of range
  for this run.
- 404 if the run does not exist.
- 502 if Agent 5 fails after `CLAUDE_JSON_RETRY` retries; the
  endpoint still persists any items it received valid translations
  for (Agent 5 returns its items in one call, so partial results
  only occur on parse-recovery edges — see § 7.1 Call 5 rule #1).

Side effect: emits a `translations_refreshed` SSE event (§ 8.4) on
the run's event bus, scoped to subscribers in `target_language`, so
sibling tabs / windows pick up the same translations without having
to re-request them.

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

**Translation endpoint** (HTTP-only, not persisted on any row):

| `error_code`           | Meaning                                                                                          |
|------------------------|--------------------------------------------------------------------------------------------------|
| `TRANSLATE_FAILED`     | Agent 5 failed after `CLAUDE_JSON_RETRY` retries. Returned in the 502 body so the frontend can show a toast and keep displaying the stale / source-language fallback. |

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

The frontend is a 2-screen SPA, served under a mandatory `/:lang/`
path prefix (§ 9.6). Visiting `/` redirects (server-side 200 or
client-side `replace`) to `/{detected}/` where `detected` is one of
`sk` / `cs` / `en`. Both screens described below sit under that
prefix:

- **Screen A — Home:** `/sk/`, `/cs/`, `/en/`.
- **Screen B — Run:** `/sk/runs/:run_id`, `/cs/runs/:run_id`,
  `/en/runs/:run_id`.

The two `:lang/` variations of the same logical screen are the same
route record in `vue-router`; navigating between them keeps the
component instance mounted (§ 9.6.5), so switching language never
unmounts the chat thread or the runs view.

#### Screen A — Home (`/:lang/`)

**Purpose:** Chat with the virtual assistant (Agent 0a) to agree on a
story brief, then trigger story generation.

There is **no textarea for raw story input** on this screen. The single
input control is the chat composer at the bottom of the chat thread.

**Elements (top to bottom):**

1. **Header:** the app title (`i18n.t('app.title')`) and a short
   subtitle (`i18n.t('app.subtitle')`). The header row also hosts the
   `LanguageSwitcher` in its **top-right** slot, anchored to the
   centered app container; the switcher is sized so it never overlaps
   the title or the subtitle at any supported viewport width (§ 9.8).
2. **Chat thread** (`ChatThread`): a vertically scrolling list of
   `ChatMessage` items. Assistant messages are aligned left with the
   assistant's avatar; user messages are aligned right. The very first
   message is always the welcome message — rendered locally from
   `i18n.t('chat.welcome')` (see § 9.6.2). The welcome is **not** a
   real `session_messages` row; it is a frontend-only "pretend" turn
   that swaps language together with the rest of the UI. Once the
   user submits their first message, the chat thread shows the
   welcome (still local), the user's message, and from then on the
   real persisted turns. The welcome's `#word#`-marked segments
   render in **bold**.
3. **Story-building skeleton** (`StoryBuildingSkeleton`): while
   `session.state === "BUILDING_STORY"`, the chat thread and the
   composer are *both* removed from the layout and replaced by this
   component. It shows:
   - A single line `i18n.t('home.generatingOn', { topic: session.topic_short })`,
     e.g. *"Vytváram príbeh o: Mladý hrdina v lete na vidieku"*
     / *"Vytvářím příběh o: Mladý hrdina v létě na venkově"*
     / *"Generating the story on: A boy's summer in the countryside"*.
     `topic_short` is taken from the session row (§ 5.1) — it was
     produced by Agent 0a on the confirmed turn in the session's
     `source_language`. It is intentionally **not** translated by the
     UI language switcher; the boilerplate label *"Generating the
     story on: "* is localized, the topic phrase is the author-language
     verbatim.
   - Five `SkeletonBlock` paragraph-skeletons stacked vertically at a
     "middle generic" line height (~ 4–6 pulsing lines each). No
     illustration cards yet — they only appear after navigation to
     `/:lang/runs/:run_id`.
   The skeleton view is entered as soon as `POST /api/sessions/{id}/finalize`
   returns 202 (§ 8.2). The frontend then opens
   `GET /api/sessions/{id}/events` (§ 8.2.1) and listens for
   `story_built` (→ navigate to `/:lang/runs/:run_id`) or
   `story_build_failed` (→ swap the skeleton for the session error
   banner, restore the chat thread read-only with the transcript).
4. **Chat composer** (`ChatComposer`): a single-line auto-expanding
   `<textarea>` with a send button (`i18n.t('chat.send')`). Submits on
   Enter (Shift+Enter inserts newline). Hidden entirely while the
   story-building skeleton is active. Disabled when:
   - the session is `COMPLETED` or `FAILED`,
   - or a request is in flight,
   - or the input is empty or exceeds `CHAT_MESSAGE_MAX_CHARS`.
   A character counter "X / CHAT_MESSAGE_MAX_CHARS" appears below.
5. **Confirm hint:** when the latest assistant message has
   `phase="awaiting_confirmation"`, a small localized hint appears
   underneath the composer (`i18n.t('chat.confirmHint')`), e.g.
   "Ak súhlasíš so zhrnutím, odpovedz napríklad 'áno' alebo 'do toho'."
   There is no separate confirm button — the user types their answer
   like any other reply.

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
   `session.state === "FAILED"`. Displays a message localized via
   `i18n.t(sessionErrors[session.error_code])` against the active
   locale, where `sessionErrors` maps each code to an i18n key in
   `src/i18n/sessionErrors.ts` (see § 9.4),
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
  - Show the per-language `i18n.t('chat.confirmedAck')` as the
    rendered text of that assistant bubble (ignore the persisted
    `content` for display — the i18n key is the source of truth,
    § 7.1 Call 0a).
  - Immediately call `POST /api/sessions/{id}/finalize` (no extra UI
    action required). The trigger is the `phase` field on the reply —
    never the prose content — so localisation and minor wording drift
    cannot break the handoff.
  - On 202: transition the local UI into the
    `StoryBuildingSkeleton` view (§ 9.1 Screen A element #3) using
    `topic_short` from the response. Open the session SSE stream
    (§ 8.2.1).
  - On the SSE `story_built` event, navigate to `/:lang/runs/:run_id`.
  - On `story_build_failed`, exit the skeleton, show the session
    error banner.
  - On any other error during finalize, show the session error
    banner.

- On any session POST response (`POST /api/sessions` or
  `POST /api/sessions/{id}/messages`), the store also processes
  `detected_language` per § 9.6.3 to drive the auto-switch + toast.

#### Screen B — Run (`/:lang/runs/:run_id`)

**Purpose:** Show the generated story together with progress of the
illustrations, or the final state of a completed run.

**Elements (top to bottom):**

1. **Header:** A back link (`i18n.t('runs.newStory')`) on the left
   and the `LanguageSwitcher` in the top-right slot (§ 9.8). The
   switcher is positioned so it never overlaps the story title even
   when titles are unusually long (multi-line title still keeps a
   right gutter for the switcher).
2. **Run status pill:** "Beží" (with spinner) / "Hotovo" / "Zlyhalo" /
   "Zrušené".
3. **Run-level error banner** (`RunErrorBanner`): visible when
   `run.status === "FAILED"`. Maps `run.error_code` to an i18n key
   via `src/i18n/runErrors.ts` and renders the message in the active
   locale (§ 9.4).
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

- A small label, `i18n.t('illustration.currentConcept')` (Slovak:
  "Aktuálny koncept"; Czech: "Aktuální koncept"; English: "Current
  concept").
- The reactive **translated** `illustration.current_concept` text —
  i.e. the version in the active UI language (per § 8.3 / § 5.5).
  This replaces the previous behavior of showing the English source;
  the popover now mirrors the user's reading language. If the
  translation state is `stale` or `missing`, the popover displays
  whichever value the snapshot returned (stale translation or
  source fallback) and the runStore fires a background § 8.9 call
  to refresh.
- Below it, a subtler line `i18n.t('illustration.storyExcerpt')`
  followed by `illustration.scene_excerpt` (in the active language,
  same translation logic as paragraphs) truncated to ~200 chars.

The popover content stays reactive: when SSE `illustration_state`
events update `current_concept` or `scene_excerpt`, an open popover
re-renders in place. The popover component is provided by
`floating-vue` (§ 9.5). Accessibility: the icon is a focusable
`<button type="button">` with an `aria-label` (e.g. "Zobraziť koncept"),
the popover is keyboard-dismissible (Esc), and it is also openable on
keyboard focus, not only on hover.

**Each `IllustrationCard` shows (revised list):**

- Scene number, rendered via `i18n.t('story.illustration_n', { n: K })`
  (left of header).
- The current state, rendered via `i18n.t('illustration.state.${state}')`
  against the active locale (the state-key table is documented in § 6).
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
- `session: Session | null` (now includes `source_language` and
  `topic_short`)
- `messages: ChatMessage[]` (ordered by `order_index`)
- `lastDetectedLanguage: 'sk' | 'cs' | 'en' | 'other' | null` — the
  raw `detected_language` from the most recent server response. Used
  by the auto-switch listener (§ 9.6.3) and reset to `null` on
  language-switch acknowledgement.
- `isSending: boolean`
- `isFinalizing: boolean` — `true` between the user's `confirmed`
  turn and the SSE `story_built` / `story_build_failed` event. Drives
  the `StoryBuildingSkeleton` visibility (§ 9.1 Screen A).
- `error: { code: string, message: string } | null`

Welcome message — frontend-only, rendered on `HomeView` mount from
the `i18n.t('chat.welcome')` key. The key carries the same prose in
all three locale files (`sk.ts`, `cs.ts`, `en.ts`); the `#word#`
segments stay across all three so the bold renderer (§ 9.6.2) works
uniformly. The welcome is **not** sent to Claude as part of the
transcript and **not** persisted as a `session_messages` row (§ 7.1
Call 0a, § 8.1). It is a "pretend" assistant turn that the chat
thread always shows first.

English source (canonical, kept here for product-owner reference):

> "Hi, I'm your virtual assistant and I'm here to help you create the
> short illustrated anime story. In order to proceed, we must agree on
> some kind of overall story concept together. Start with writing
> anything that comes into your mind, that should shape the final
> story. There is only one rule. Since this is a restricted demo
> version of the app, there can be only **one male** and/or **one
> female** character. The only supported exception is that the main
> character can also have their **mother**."

The Slovak and Czech equivalents live verbatim in the corresponding
locale files. Editing the welcome means editing all three locale
files (mechanical, but a unit test enforces parity of the `#word#`
markers across the three).

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
- `finalize()` → `POST /api/sessions/{id}/finalize` (202-based; § 8.2).
  Triggered automatically when the latest assistant reply has
  `phase="confirmed"`. The action sets `isFinalizing=true`, stores
  the response's `topic_short` on the session, opens the session SSE
  stream (§ 8.2.1), and resolves with `{ run_id }` when the
  `story_built` event arrives. On `story_build_failed` it rejects
  with the error and sets `isFinalizing=false`.
- `reset()` → clears all state to start a fresh session.

The optimistic reconciliation MUST preserve the array index of the user
row — replace in place, never `push` then sort. This guarantees the
visual position of the user's bubble does not jitter when the server
response lands.

#### 9.2.2 `runStore` (Pinia)

State:
- `run: Run | null` (carries `source_language`, `language`,
  `story_title`, `story_topic_description`, `topic_short`,
  `story_blocks` with translation states — all per § 8.3)
- `illustrations: Illustration[]` (by `scene_index` order; carries
  `current_concept`, `current_concept_translation_state`,
  `current_workflow`, `character_role: string|null`)
- `translations: Record<Language, RunTranslationCache>` — the
  in-memory per-language cache of every piece of translatable text
  for this run, keyed by language. Each cache entry stores the text
  AND the `source_hash` that was current when the entry was
  generated, mirroring the DB schema (§ 5.5). The cache survives
  language switches inside `/runs/:run_id` so the user can switch
  back and forth without re-fetching. Cleared on `loadRun()` for a
  new run.
- `currentLanguage: 'sk' | 'cs' | 'en'` — the language the runStore
  is currently presenting. Bound to the locale store (§ 9.6) but
  treated as the source of truth for "which language was the
  snapshot fetched in" purposes.
- `pendingTranslationLanguages: Set<Language>` — languages currently
  being refreshed via § 8.9; used to de-duplicate concurrent
  switches.
- `isConnecting: boolean`
- `sseError: string | null`

Actions:
- `loadRun(runId, language)` → GET snapshot in the given language.
  Replaces `run` + `illustrations` + writes the returned text into
  `translations[language]`.
- `subscribe(runId, language)` → opens EventSource with
  `?lang={language}`, dispatches updates.
- `unsubscribe()` → closes EventSource.
- `cancel()` → POST cancel.
- `switchLanguage(language)` — central action invoked by the locale
  store when the user changes UI language while on `/runs/:run_id`
  (§ 9.6.4). Behavior:
  1. If `language === run.source_language` OR every translatable
     field in `translations[language]` is `"fresh"` against current
     source hashes → swap `currentLanguage` and re-render from the
     cache, no network call.
  2. Otherwise: collect the set of `missing` + `stale` items into
     an array of `{ kind, paragraph_index?, scene_index? }` and
     issue `POST /api/runs/:run_id/translations` (§ 8.9) for that
     subset. The cached `stale` values stay visible during the
     in-flight call. When the response arrives, write each item
     into `translations[language]` (and into the live `run` /
     `illustrations` view if the active language still matches).
  3. While the call is in flight, `pendingTranslationLanguages.add(language)`.
     The store ignores duplicate concurrent `switchLanguage(language)`
     calls for the same language. Clears the entry on response.
  4. Also reopens the EventSource with `?lang={newLanguage}` so
     subsequent live events arrive pre-translated and so other tabs'
     `translations_refreshed` events are observed.

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
  authoritative; § 8.4). The payload is already projected for
  `currentLanguage` per § 8.4 — the store ALSO copies every
  translatable field into `translations[currentLanguage]` along with
  its `source_hash` and `translation_state`, so subsequent
  `switchLanguage()` calls back to the same language hit the cache.
- `illustration_state` → finds the illustration by `illustration_id`
  and mutates the existing reactive object **in place**:
  - `state`, `concept_attempt`, `prompt_attempt` always.
  - `current_concept` — always copied from the payload (non-null on
    every transition, per § 8.4). The payload's
    `current_concept_translation_state` is copied alongside; if the
    state is `"stale"` or `"missing"` and the active language is not
    the source language, the store enqueues a lazy translation
    refresh by calling `switchLanguage(currentLanguage)` (which
    de-duplicates against any in-flight call).
  - `current_workflow` — always copied from the payload (selected by
    Agents 1 / 3 per § 7.1; drives the workflow-aware rendering of
    the IllustrationCard, e.g. omitting the "character" badge when
    `current_workflow === "no-lora"`).
  - `scene_excerpt` — always copied from the payload. The excerpt can
    change across an Agent 4 cycle (§ 7.1 Call 4); the assignment is
    field-level so any component bound to it (most notably the concept
    popover in `IllustrationCard`) re-renders without remount.
- `paragraph_updated` → locate the paragraph block at
  `event.paragraph_index` in the paragraph subset of
  `run.story_blocks` and assign `block.text = event.text` and
  `block.translation_state = event.translation_state` on that
  existing reactive object. Because the assignment is field-level, the
  `StoryParagraph` bound to that block re-renders in place. The store
  MUST NOT replace the whole `story_blocks` array or swap the block
  object — both would force every `StoryParagraph` to remount and
  break the skeleton-to-text crossfade. A reference-identity assertion
  in the tests verifies this (§ 11.3). The store ALSO writes the new
  text + hash into `translations[currentLanguage]` for the
  `paragraph[i]` slot so the cache stays in sync.
- `illustration_companion_updated` → finds the illustration by
  `illustration_id` and assigns `illustration.companion = event.companion`
  on the existing reactive object (replacement of the whole companion
  field is fine — its inner fields are not bound separately, since the
  whole object can transition to/from null). The IllustrationCard's
  companion subtitle re-renders without remount.
- `illustration_role_updated` → finds the illustration by
  `illustration_id` and assigns `illustration.character_role =
  event.character_role` on the existing reactive object. The role
  field is nullable (§ 5) and toggling it drives whether the
  `no-lora` vs `single-lora` badge renders on the card. A field-level
  assignment keeps the card mounted across the change.
- `translations_refreshed` → cross-tab / cross-session sync event
  emitted by § 8.9 whenever any other client refreshes translations
  for this run. Payload carries `{ language, items: [...] }`. The
  store writes each item into `translations[event.language]` along
  with its `source_hash`. If `event.language === currentLanguage`,
  it also patches the live `run` / `illustrations` views in place
  (paragraph text, story_title, story_topic_description,
  illustration concept_localized) using the same field-level
  assignment rules as the dedicated handlers above — no array or
  object replacement, so no remounts.
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
  surface for the assistant side; the welcome message (rendered
  frontend-only via `i18n.t('chat.welcome')` — § 9.6) visually matches
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

### 9.4 Error code → i18n key mapping

Two mapping modules, both unit-tested. Each module maps a backend
`error_code` to an i18n message **key**, not a literal string — the
actual rendered text is resolved by `i18n.t(key)` against the locale
files in `src/i18n/locales/{sk,cs,en}.ts` (§ 9.6.1). The same code
therefore renders in whichever UI language is currently active.

**`src/i18n/sessionErrors.ts`:**

| `error_code`           | i18n key                       |
|------------------------|--------------------------------|
| `CHAT_FAILED`          | `errors.session.chat_failed`   |
| `STORY_BUILD_FAILED`   | `errors.session.story_build_failed` |
| `TRANSLATE_FAILED`     | `errors.session.translate_failed`   |
| `INTERNAL_ERROR`       | `errors.session.internal_error`     |

**`src/i18n/runErrors.ts`:**

| `error_code`           | i18n key                       |
|------------------------|--------------------------------|
| `INTERNAL_ERROR`       | `errors.run.internal_error`    |
| `TRANSLATE_FAILED`     | `errors.run.translate_failed`  |

Unknown codes in either map fall back to the corresponding
`internal_error` key. `null` / `undefined` produces an empty string
(the banner stays hidden). Each locale file MUST provide every key
listed above; a unit test enforces key-parity across the three
locales (§ 11.3).

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

### 9.6 Internationalization module (`vue-i18n`)

The app supports three UI languages — Slovak (`sk`), Czech (`cs`), and
English (`en`) — at every screen. The locale lives in the URL path
(`/:lang/...`), so every page is bookmarkable in a chosen language and
copy-pasted links preserve the language for the recipient.

#### 9.6.1 Setup

- `vue-i18n` v9 in Composition-API mode is added to
  `frontend/package.json`. Configured in `src/i18n/index.ts`:
  ```ts
  createI18n({
    legacy: false,
    locale: detectInitialLanguage(),
    fallbackLocale: 'en',
    messages: { sk, cs, en },
    missingWarn: import.meta.env.DEV,
    fallbackWarn: import.meta.env.DEV,
  })
  ```
- Locale dictionaries live under `src/i18n/locales/{sk,cs,en}.ts`.
  Each is a plain TypeScript object with the same nested shape — top-level
  groups include `chat`, `story`, `nav`, `errors.session`, `errors.run`,
  `language` (display names of the three languages used by the
  switcher), and `toast`.
- `src/main.ts` registers the i18n plugin with `app.use(i18n)` before
  mounting the router.

Locale-file parity is enforced by a unit test (§ 11.3): if any key is
present in one locale and missing in another, the test fails. Adding a
new string therefore forces all three files to be updated in the same
commit. Translations the operator hasn't yet provided are committed as
the English text wrapped in a `// TODO(translate)` comment — this keeps
the keys present while flagging untranslated copy in code review.

#### 9.6.2 Supported languages constant

`src/i18n/supported.ts` exports:

```ts
export const SUPPORTED_LANGUAGES = ['sk', 'cs', 'en'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]
```

The router guards (§ 9.6.4), the language switcher (§ 9.8), the locale
store (`stores/locale.ts`), and the chat / run stores all import from
this single module. There is no other place where the list of
supported languages lives in the frontend.

#### 9.6.3 Initial language detection

`detectInitialLanguage()` (in `src/i18n/index.ts`) resolves the
initial language in this order:

1. **URL prefix.** If the current `window.location.pathname` starts
   with `/sk/`, `/cs/`, `/en/`, or equals `/sk`, `/cs`, `/en`, use
   that. (The router resolves the same value once mounted; this is
   only relevant for the very first paint.)
2. **Persisted preference.** `localStorage.getItem('illustration-app:language')`
   if it is one of `SUPPORTED_LANGUAGES`.
3. **Browser locale.** `navigator.language` is matched against
   `SUPPORTED_LANGUAGES` after stripping the region (`'sk-SK'` → `'sk'`).
4. **Fallback.** `'en'`.

The chosen value is immediately written back to `localStorage` so a
subsequent visit without a path prefix bounces to the same language.

#### 9.6.4 Routing

`src/router/index.ts` defines a single parent route with `path:
'/:lang(sk|cs|en)'` and nests every existing route underneath as a
child (`''` → SessionView, `runs/:run_id` → RunView). The redirect
strategy:

- `path: '/'` redirects to `/{detectInitialLanguage()}/`.
- `path: '/runs/:run_id'` (any legacy un-prefixed link, e.g. links
  copy-pasted from before i18n shipped) redirects to
  `/{detectInitialLanguage()}/runs/:run_id`.
- A catch-all `path: '/:pathMatch(.*)*'` redirects to
  `/{detectInitialLanguage()}/` — the app does not present a 404 in
  MVP; un-routable URLs bounce home in the user's language.

A global `beforeEach` guard, on every navigation:

1. Reads `to.params.lang`. If it is not in `SUPPORTED_LANGUAGES`, it
   replaces the route with the user's detected language (this is a
   safety net — the path regex already restricts to the three
   languages).
2. Writes the new language into the locale store (§ 9.6.5) and into
   `i18n.global.locale.value`.
3. Sets `document.documentElement.lang` to the new language.

Route components do NOT each call `useI18n()` just to pick the locale —
the guard guarantees `i18n.global.locale.value` matches the URL by the
time the component mounts.

#### 9.6.5 Locale store (`stores/locale.ts`)

A Pinia store with:

- State: `currentLanguage: Language` (initialized from
  `detectInitialLanguage()`; kept in sync with both the URL and
  `i18n.global.locale.value`).
- Action `setLanguage(language: Language, { silent?: boolean })`:
  1. If `language === currentLanguage`, no-op.
  2. Replace the `lang` segment of the current route with the new
     value (`router.replace`). This triggers the `beforeEach` guard
     which updates `i18n` and `documentElement.lang`.
  3. Persist to `localStorage`.
  4. If the active route is `/runs/:run_id`, call
     `runStore.switchLanguage(language)` (§ 9.2.2).
  5. If the active route is the SessionView with an active session,
     no action on the session itself is needed — the welcome bubble
     and any other purely-UI text re-render reactively from `i18n.t`,
     and the persisted chat transcript already contains the
     user/Claude messages in the source language as originally
     produced.

#### 9.6.6 Auto-switch on chat detection

Agent 0a emits `language: 'sk' | 'cs' | 'en' | 'other'` per § 7.1
Call 0a. The chat-message SSE handler (or fetch response, depending
on transport per § 8.1):

1. Ignores `'other'` and any value equal to the current language.
2. For one of `sk` / `cs` / `en` that differs from
   `localeStore.currentLanguage` AND that has not yet been
   auto-switched in this session (the session store tracks
   `lastDetectedLanguage`):
   a. Calls `localeStore.setLanguage(detected, { silent: false })`.
   b. Fires a toast (§ 9.7) via `toast.info(i18n.t('toast.language_switched', { language: i18n.t(`language.${detected}`) }))`.
   c. Records `lastDetectedLanguage = detected` on the session store
      to avoid re-toasting on every subsequent turn.

The auto-switch never fires after the user has manually selected a
language via the LanguageSwitcher (§ 9.8) — the manual switch sets a
`languageLockedByUser` flag on the locale store that suppresses any
further auto-switching for the lifetime of the session.

### 9.7 Toast notifications (`vue-sonner`)

The app uses **`vue-sonner`** — the Vue port of the `sonner` library —
as the single toast surface. Added to `frontend/package.json` as a
regular dependency. No other notification system (alerts, custom
banners outside the inline error banners, etc.) is introduced.

Setup:

- `<Toaster />` is rendered once at the top of `App.vue` with
  props `position="top-center"` and `rich-colors` enabled.
- A thin wrapper `src/composables/useToast.ts` exposes
  `{ info, success, error }` functions that call `sonner`'s API
  with the app's default options (5 s duration, dismissable).
- Wrappers always go through `i18n.t(key, params)` — toast text
  is never hard-coded at the call site. Keys live under the
  `toast.*` group in each locale file.

Use sites in MVP:

- Auto-switch announcement (§ 9.6.6) — `toast.language_switched`.
- Translation refresh failure — `toast.translate_failed`
  (rendered when the lazy translation request from § 9.2.2
  `switchLanguage()` returns a `TRANSLATE_FAILED` error code).

Adding any new toast call site requires extending this list and the
corresponding `toast.*` keys in every locale.

### 9.8 Language switcher (`LanguageSwitcher.vue`)

A small component rendered in the top-right of the centered page
container on every screen. Implementation rules:

- Trigger: a button showing the active language as its ISO code
  (`SK` / `CS` / `EN`) plus a small chevron. No flag emoji — flags
  are politically loaded and don't map cleanly to languages (e.g.
  Swiss German). The chevron rotates 180° when the menu is open.
- Surface: a 3-row menu mounted via `floating-vue` (§ 9.5) with
  one row per supported language. Each row shows the language's
  endonym (`Slovenčina` / `Čeština` / `English` — read from
  `i18n.t('language.${code}')` so it changes with the active
  locale). The active language row is marked with a check glyph.
- Click handler invokes `localeStore.setLanguage(code, { silent:
  true })` and closes the menu.
- Manual selection sets `localeStore.languageLockedByUser = true`
  (§ 9.6.6).

Positioning rules (NOT-overlap with titles):

- The switcher is rendered inside the same centered container as
  the page content, anchored with `position: absolute; top: 16px;
  right: 16px;` relative to the container (NOT the viewport). This
  guarantees it sits inside the safe area even on wide viewports.
- The page header (the `<h1>` title on SessionView, the story
  title on RunView) reserves a right-side padding equal to the
  switcher's width plus a 16 px gap (`padding-right: calc(72px +
  16px)`). The switcher therefore never overlaps the title and the
  title never reflows when the menu opens.
- On viewports narrower than 480 px the switcher shrinks to a
  pure-icon (globe) button and the menu becomes a centered
  bottom-anchored sheet via `floating-vue`'s `bottom-end`
  placement, eliminating right-margin pressure on tight screens.

Accessibility: the trigger is a `<button>` with
`aria-haspopup="menu"`, `aria-expanded`, and an `aria-label` resolved
from `i18n.t('nav.change_language')`. The menu items have
`role="menuitemradio"` with `aria-checked` on the active row.

### 9.9 Story-building skeleton view (`StoryBuildingSkeleton.vue`)

Rendered on SessionView between the user's confirmation turn and the
arrival of the `story_built` event on the session-level SSE stream
(§ 8.2.1). When the skeleton is shown, BOTH the chat thread and the
chat composer are hidden — the user's task is complete and there is
nothing for them to type until the run page loads.

Layout:

- A single centered line of body text reading `i18n.t('story.building',
  { topic: session.topic_short })` — e.g. *"Generating the story on the
  topic of the brave little fox…"* The `topic_short` value comes from
  Agent 0a's last `confirmed` turn (§ 7.1 Call 0a).
- Below the line, **exactly five** `SkeletonBlock shape="line"
  :lines="4"` placeholders stacked vertically with the same spacing
  the real `StoryParagraph` will use, so the visual rhythm is
  preserved across the transition.
- No illustration placeholders are shown here — the illustrations
  belong on the run page, not the session page.

Transition out: on `story_built`, the sessionStore (§ 9.2.1) sets the
run id and the router navigates to `/:lang/runs/:run_id/`. Because the
skeleton lives on a different route than the run view, there is no
in-place crossfade — the router transition handles it.

Transition error: on `story_build_failed`, the skeleton is replaced
inline by an error banner rendering the i18n message for
`STORY_BUILD_FAILED` (§ 9.4) plus a button bound to
`i18n.t('story.try_again')`. The button resets the session store and
returns the chat thread + composer with the user's last brief
preserved as a draft, so they can edit and re-confirm without retyping
from scratch.

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
| `ANTHROPIC_MODEL`                 | `"claude-sonnet-4-6"` | Single model used for all 7 calls (chat, build_story, generate_prompts, evaluate_image, revise_prompts, rethink_concept, translate) |
| `SUPPORTED_LANGUAGES`             | `("sk", "cs", "en")` | Tuple of UI / story languages the backend accepts (§ 9.6). The chat agent emits one of these or `"other"`; the build_story, translate, and run APIs all validate against this tuple. |
| `CONFIRMED_ACK`                   | `Mapping[str, str]` (see below) | Per-language canonical `reply` returned by Agent 0a on `phase="confirmed"`; the chat service looks up `CONFIRMED_ACK[detected_language]` and overwrites any other prose Claude returned. |

`CONFIRMED_ACK` contents (one entry per `SUPPORTED_LANGUAGES`):

| Language | Canonical reply text                                                          |
|----------|-------------------------------------------------------------------------------|
| `sk`     | `"Skvelé, ide na to. Pripravujem príbeh a ilustrácie…"`                       |
| `cs`     | `"Skvělé, jdu na to. Připravuji příběh a ilustrace…"`                         |
| `en`     | `"Great, on it. Building your story and illustrations…"`                      |

If Agent 0a returns `language="other"` on a `confirmed` turn, the
server falls back to `CONFIRMED_ACK["en"]` (English is the universal
fallback per § 9.6.1 fallbackLocale).

The `STORY_MAX_CHARS` constant from the previous spec is removed (raw
story text is no longer a public input). The `WELCOME_MESSAGE_SK`
constant from the prior spec revision is also removed — the welcome
message is now a frontend-only i18n string (`i18n.t('chat.welcome')`,
§ 9.6.1) and never round-trips through the backend.

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
  - Loads all seven `.md` files (chat, build_story, generate_prompts,
    evaluate_image, revise_prompts, rethink_concept, translate) from a
    temporary `AGENTS_DIR` fixture and exposes them on the Claude
    client.
  - Refuses to start (raises typed error) when any of the seven files
    is missing, empty, or unreadable.
  - The system prompt sent to Anthropic for each call equals the file
    contents verbatim (verified by intercepting the outgoing request with
    respx).
- **Claude IO schemas** (`schemas/...`):
  - Each of the 7 response Pydantic models accepts a valid example.
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
  - `POST /api/sessions` → mocked Agent 0a returns `phase=gathering`
    with `language: 'sk'`.
  - `POST /api/sessions/{id}/messages` → mocked Agent 0a returns
    `phase=awaiting_confirmation` with a valid brief.
  - `POST /api/sessions/{id}/messages` (user "áno") → mocked Agent 0a
    returns `phase=confirmed` with `language: 'sk'` and a
    `topic_short` value.
  - `POST /api/sessions/{id}/finalize` returns **202** carrying
    `topic_short` immediately (§ 8.2).
  - The session-level SSE stream (`GET /api/sessions/{id}/events`,
    § 8.2.1) emits `story_built{run_id}` after the mocked Agent 0b
    returns 5 valid illustrations.
  - `GET /api/runs/{id}?lang=sk` returns the run with story blocks
    and 5 `PENDING` illustrations, `source_language = 'sk'`.
  - Background work runs to completion → `GET /api/runs/{id}` shows
    `COMPLETED` with image paths written under a tmp `OUTPUT_DIR`. The
    SSE stream emits the expected sequence ending with `run_completed`.
- **STORY_BUILD_FAILED end-to-end:** as above, but mock Agent 0b to
  return invalid output. The finalize call still returns 202 (the
  failure is asynchronous); the session-level SSE stream then emits
  `story_build_failed{error_code: "STORY_BUILD_FAILED"}`, the
  persisted session ends in `FAILED` with the same error code, and no
  run is created.
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
- **Workflow selection end-to-end (new):** drive a run whose Agent 0b
  output yields a mix of `character_role: null` rows and non-null
  rows. Assert:
  - Every row with `character_role IS NULL` ends up with
    `current_workflow = "no-lora"` and the recorded RunPod dispatch
    used `no-lora.json` (no `CHARACTER_LORA` substitution).
  - Every row with `character_role` set ends up with
    `current_workflow = "single-lora"` and the dispatched workflow
    file is `single-lora.json` with the correct `CHARACTER_LORA`
    placeholder substituted (per § 7.2.1).
  - Agent 4 mocked to flip a row from `single-lora` to `no-lora`
    emits `illustration_role_updated{character_role: null}` on the
    SSE stream and a subsequent dispatch uses `no-lora.json`.
- **Translation end-to-end (new):** finalize a session with
  `source_language = 'sk'`. After the run completes:
  - `GET /api/runs/{id}?lang=sk` returns every translation_state
    field as `"source"`.
  - `POST /api/runs/{id}/translations` with all paragraph + concept
    items for `language = 'cs'` invokes the mocked Agent 5 (translate)
    once, persists rows in the three translation tables (§ 5.5),
    returns 200 with the full set, and emits a `translations_refreshed`
    event on the run-level SSE stream carrying the same items.
  - A second `POST /api/runs/{id}/translations` request for the same
    items returns immediately with the cached values and DOES NOT
    invoke Agent 5 again (the "never translate twice" rule of § 8.9).
  - Force a paragraph rewrite (Agent 4 mocked path) for one paragraph.
    The `source_hash` for `paragraph[i]` changes; a subsequent
    `GET /api/runs/{id}?lang=cs` reports that paragraph's
    `translation_state` as `"stale"` while keeping the previous cached
    Czech text. A targeted POST for that one item invokes Agent 5
    again and updates the row to `"fresh"`.
- **TRANSLATE_FAILED end-to-end (new):** mock Agent 5 to raise. The
  `POST /api/runs/{id}/translations` call returns 502 with
  `error_code = "TRANSLATE_FAILED"`; no rows are persisted in the
  translation tables for the affected items; a subsequent retry with
  Agent 5 mocked to succeed completes normally.

### 11.3 Frontend unit (`frontend/tests/`)

Pinia stores and components are tested with Vitest + @vue/test-utils.

- **ChatMessage / ChatThread:**
  - Renders user and assistant messages in transcript order.
  - The welcome message (resolved frontend-only via
    `i18n.t('chat.welcome')`, § 9.6.1) is always shown first when the
    transcript is empty, with the `#word#`-marked segments rendered
    in **bold**. The welcome message is not part of `session.messages`
    and is not sent to the backend on any subsequent turn.
  - Shows a small typing indicator (i18n key `chat.assistant_typing`)
    while a request is in flight.
- **ChatComposer:**
  - Disabled when the session state is `BUILDING_STORY`, `COMPLETED`,
    or `FAILED`.
  - Disabled while a request is in flight.
  - Enforces `CHAT_MESSAGE_MAX_CHARS` and shows the counter.
  - Submits on Enter, inserts newline on Shift+Enter.
- **SessionErrorBanner:**
  - Hidden when session state is not `FAILED`.
  - Renders the message resolved by `i18n.t(sessionErrors[code])`.
  - Unknown code falls back to `errors.session.internal_error`.
  - The exact same component, mounted with `locale='cs'` / `'en'`,
    renders the Czech / English translation of the same key.
- **`sessionErrors.ts` mapping** (new unit test file):
  - Each known `error_code` maps to its specified i18n key (§ 9.4).
  - Unknown code falls back to `errors.session.internal_error`.
  - `null` / `undefined` produces empty string.
  - **Locale parity:** for each of `sk`, `cs`, `en` the locale file
    contains every key listed in `sessionErrors.ts` and
    `runErrors.ts`; the test fails if any key is missing in any
    locale.
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
  reduced error_code surface (`INTERNAL_ERROR`, `TRANSLATE_FAILED`)
  for runs and i18n-key-based message resolution (§ 9.4).
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
- **i18n module (`src/i18n/`):**
  - `detectInitialLanguage()` returns the URL-prefix language when
    present, the `localStorage` value when set, then the browser
    locale stripped to its base tag, then `'en'` (each path covered
    by a dedicated test that mocks the relevant input).
  - Locale-file parity: every key in `sk.ts` is present in `cs.ts`
    and `en.ts` and vice versa. The test walks the nested object
    structure recursively and reports any missing path.
  - The catch-all router redirect targets the detected language
    (e.g. when `localStorage` is `'cs'`, `/foo/bar` resolves to
    `/cs/`).
- **LanguageSwitcher.vue:**
  - Renders three menu items in the order `sk`, `cs`, `en` with the
    endonym labels resolved from `i18n.t('language.${code}')`.
  - Clicking a non-active item invokes `localeStore.setLanguage(code,
    { silent: true })` exactly once and closes the menu.
  - Clicking the active item is a no-op (the menu still closes).
  - Selecting a language manually sets
    `localeStore.languageLockedByUser = true`.
  - The trigger button has the accessibility attributes specified
    in § 9.8 (`aria-haspopup`, `aria-expanded`, `aria-label`).
- **localeStore (`stores/locale.ts`):**
  - `setLanguage('cs')` from `'sk'` calls `router.replace` with the
    `lang` path segment rewritten to `'cs'` and writes `'cs'` into
    both `i18n.global.locale.value` and `localStorage`.
  - `setLanguage(current)` is a no-op (no router push, no storage
    write).
  - When the route is `/runs/:run_id`, `setLanguage` additionally
    invokes `runStore.switchLanguage` with the new language.
  - The Agent 0a chat handler invokes `setLanguage(detected, {
    silent: false })` exactly once per session (subsequent identical
    detections do not re-toast).
  - Manual selection prevents subsequent chat-driven auto-switches
    (asserted by setting `languageLockedByUser = true` then dispatching
    a chat reply with a different `language` value and verifying
    `setLanguage` was not called).
- **StoryBuildingSkeleton.vue:**
  - Renders the title line via `i18n.t('story.building', { topic })`
    with the topic value from a mounted-in test prop.
  - Renders exactly five `SkeletonBlock shape="line"` placeholders
    in DOM order under the title.
  - Renders an error banner (mapped via `sessionErrors.ts`) plus a
    `i18n.t('story.try_again')` button when the session reaches the
    `story_build_failed` state during the skeleton phase.
  - Clicking `try_again` invokes the session-store reset action
    (preserving the user's last draft, per § 9.9).
- **sessionStore (i18n + skeleton):**
  - After receiving an Agent 0a reply carrying `language: 'cs'` and
    `phase: 'confirmed'`, the store records `lastDetectedLanguage = 'cs'`
    and calls `localeStore.setLanguage('cs', { silent: false })` exactly
    once. A second confirmed reply with the same `language` does not
    re-invoke `setLanguage`.
  - After `POST /api/sessions/{id}:finalize` responds `202` with
    `topic_short`, the store sets `isFinalizing = true` and
    `topic_short = <value>`, hiding the chat composer and revealing
    the skeleton view via a derived getter.
  - On `story_built` SSE event, the store sets `run_id` and
    `isFinalizing = false`; on `story_build_failed`, it sets
    `error_code` and `isFinalizing = false`.
- **runStore (i18n + translations):**
  - `loadRun(runId, 'sk')` populates `translations['sk']` from the
    snapshot's translatable fields, each with its `source_hash`.
  - `switchLanguage('en')` when `currentLanguage === 'en'` is a
    no-op (no fetch, no SSE reopen).
  - `switchLanguage('cs')` when `translations['cs']` is fully fresh
    against current source hashes performs no network call and just
    flips `currentLanguage` + re-renders.
  - `switchLanguage('cs')` when at least one item is missing or stale
    issues exactly one `POST /api/runs/:id/translations` carrying only
    the missing+stale item descriptors and writes the response back
    into the cache.
  - Concurrent `switchLanguage('cs')` invocations while
    `pendingTranslationLanguages.has('cs')` do not issue a second
    POST.
  - `translations_refreshed` SSE event for `language === currentLanguage`
    patches the live `run` / `illustrations` fields in place
    (reference-survival assertion on `run.story_blocks` and on each
    illustration object).
  - `translations_refreshed` SSE event for a different language only
    writes the cache, does not touch the live view.
  - `illustration_role_updated` SSE event mutates
    `illustration.character_role` on the existing illustration object
    (reference-survival assertion).
  - `illustration_state` event with a new `current_workflow` value
    mutates that field in place.

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

- Retrying a single failed illustration without re-running the whole
  story.
- Resuming a failed session (the user starts a new chat from scratch).
- Editing the brief or the generated story after Agent 0b has produced
  it.
- User accounts / multi-tenant.
- Run / session history listing UI (the DB will accumulate rows, but
  no UI to browse).
- UI / story languages other than Slovak, Czech, and English (the
  data model in § 5.5 is open — any ISO language code can be added by
  shipping a new locale file and extending `SUPPORTED_LANGUAGES`, but
  MVP ships exactly those three).
- Inline RTL / vertical-script layout support (none of the three MVP
  languages requires it).
- Server-rendered translated content via SSR / SEO crawlers
  (translations are fetched on demand by the SPA).
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
2. With valid `.env` values, the seven agent `.md` files present, and
   `character_config.json` populated, running `uvicorn` (backend) —
   which applies any pending Alembic migrations on startup — and
   `npm run dev` (frontend) starts both services without errors.
3. A user can land on `/` (which redirects to `/{detected_lang}/`),
   read the welcome message (resolved via `i18n.t('chat.welcome')`),
   chat with the assistant, see the assistant push back when their
   proposed cast violates the character constraint, eventually get a
   summary and a request for confirmation, reply with an affirmative
   ("áno" / "ano" / "yes" / …), and be navigated to
   `/{lang}/runs/:id` once the story is built. **No "Generate" (or
   equivalent) button exists in the UI at any point;** the navigation
   to `/{lang}/runs/:id` is triggered solely by Agent 0a returning
   `phase="confirmed"` AND the subsequent `story_built` SSE event
   from the session-level stream (§ 8.2.1). Every user message —
   including the very first one and the confirmation — appears in
   the chat thread **immediately** on send, before the assistant's
   reply arrives (verified by manual smoke test: with the network
   throttled, the user bubble is visible while the assistant-typing
   indicator is still active).
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
   `StoryBuildingSkeleton` swaps inline to the error banner showing
   the i18n-resolved message for the active locale, and no run is
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
13. **Path-prefix routing.** A fresh visit to `/` redirects to one of
    `/sk/`, `/cs/`, `/en/` per the detection rules of § 9.6.3.
    Direct visits to `/sk/`, `/cs/`, `/en/` open the SessionView with
    the matching UI language. Direct visits to `/runs/:run_id` (no
    prefix) redirect to `/{detected}/runs/:run_id` without losing
    the run id. A direct visit to `/cs/runs/:run_id` shows the run
    rendered in Czech (story text translated lazily via § 8.9 when
    Czech is not the source language). The browser URL always
    carries the active `lang` segment.
14. **Chat language auto-switch.** When the user opens the chat in
    `/sk/` and types in Czech, Agent 0a returns
    `language: 'cs'` (§ 7.1 Call 0a). The locale store transitions
    to `'cs'`, the URL rewrites to `/cs/`, the UI strings re-render
    in Czech, and a `vue-sonner` toast announces the switch (i18n
    key `toast.language_switched`). A subsequent same-detection turn
    does NOT re-toast. After the user manually picks a language via
    the LanguageSwitcher, further chat-driven auto-switches do not
    fire.
15. **Workflow selection.** With a brief whose `companions` array is
    empty and a build that yields one or more illustrations with
    `character_role = null`, every `character_role IS NULL` row has
    `current_workflow = "no-lora"` and the dispatched ComfyUI job
    uses `no-lora.json` (§ 7.2.1) — no `CHARACTER_LORA` placeholder
    is substituted. Rows with a non-null `character_role` have
    `current_workflow = "single-lora"` and use `single-lora.json`.
    The acceptance check inspects both the DB rows and the recorded
    workflow file name from the RunPod dispatch logs.
16. **Story-building skeleton.** Upon Agent 0a returning
    `phase="confirmed"`, the frontend hides the chat thread and
    composer and shows `StoryBuildingSkeleton.vue` (§ 9.9) with
    `i18n.t('story.building', { topic })` and exactly five
    paragraph-shaped skeleton lines. The transition to
    `/:lang/runs/:run_id/` is triggered by the `story_built` SSE
    event from § 8.2.1, not by polling. On `story_build_failed`,
    the skeleton swaps inline to an error banner with a retry
    button that returns the user to the chat composer with their
    draft preserved.
17. **Translation refresh.** Switching from `/sk/runs/:id` to
    `/cs/runs/:id` (for a run whose `source_language = sk`) issues
    exactly one `POST /api/runs/:id/translations` request the first
    time, returns all paragraph + concept_localized + story_title
    + story_topic_description items, and updates the UI in place
    without remounting `StoryParagraph` or `IllustrationCard`.
    Switching back to `/sk/` performs no network call (the source
    is already in memory). Switching to `/en/` later issues a
    second translation request only for items that are missing or
    stale; if every item is already cached and fresh, no POST is
    issued. A second tab open on the same run receives the
    `translations_refreshed` SSE event when the first tab triggers
    a refresh and patches its own view in place if it is currently
    viewing the same language.
