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
exactly one human character, optionally accompanied by one
**narrative entity** — a non-human character or story-important object)
and `no-lora.json` (used when the scene depicts no human character — i.e.
a non-human-character narrative entity alone, an object beat, or, rarely,
a pure environment beat with no characters). Agents 1 and 3 decide which
workflow each illustration uses; Agent 0b is responsible for designing
the story so that the resulting mix of workflows is well-motivated
(§ 7.2.1 and § 7.3.11). See § 7.3 for the full creative and prompting
brief.

Two registers are locked at story-build time and form hard constraints
on every per-image rewrite that follows:

* **Environments** — exactly 5 entries on the run, position `N` locked
  to `scene_index=N`. Each entry is `{label, kind, aspect}`; ordinary
  indoor/outdoor places occupy one slot, while *dual* places (cars,
  planes, ships, wooden cabins) may occupy two slots with one `inside`
  aspect and one `outside` aspect. Only **Agent 4b** (`rethink_environment`)
  may swap an environment for a slot, and only once per branch.
* **Narrative entities** — the unified register of all non-human
  characters and story-important objects (`{label, kind, importance,
  reserved_for_scene_index}`). It replaces the legacy split between
  "companions" and "reserved entities". Entities are **scene-locked**:
  once `reserved_for_scene_index=N` is set, that entity may NEVER
  appear in any other slot, even if Agent 4 later drops it from slot
  `N` (the slot stays ghost-reserved forever). See § 5 + § 7.1 Call 0b.

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
│   │   │   ├── rethink_concept.md  # Agent 4 — concept + paragraph rewrite (same env)
│   │   │   ├── rethink_environment.md # Agent 4b — swap a slot's locked environment
│   │   │   ├── manual_concept.md   # Agent 6 — § 6A manual chat concept design
│   │   │   ├── manual_revise_prompts.md # Agent 7 — § 6A manual chat prompt revision
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
│   │       ├── single-lora.json    # 1 human (+ optional narrative entity); LoRA wired in
│   │       └── no-lora.json        # 0 humans (NH-character/object alone, or environment-only)
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
| `collected_brief_json`| TEXT NULL    | JSON: the brief captured by Agent 0a; set on confirmation. Shape includes `characters[]`, the optional `non_human_entities[]` pool (free-form `{label, role_in_story}` hints that Agent 0b later promotes into `NarrativeEntity` records), and a required `main_character_role` (one of `male` / `female` — `mother` is forbidden as main). See § 7.1 Call 0a. The column itself stays plain TEXT JSON — no schema change. |
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
| `main_character_role` | TEXT NULL  | Carried over from `sessions.collected_brief.main_character_role`. Drives the cross-illustration distribution validator (§ 7.1 Call 0b rule). One of `male` / `female`. Nullable only for legacy pre-Alembic rows. |
| `environments_json` | TEXT NULL    | JSON array of exactly **5** `Environment` objects: `{label, kind: indoor\|outdoor\|dual, aspect: single\|inside\|outside}`. Position `N` in the array is locked to `scene_index=N`. Populated by Agent 0b at run creation and **mutable only via Agent 4b** (`rethink_environment`), which may swap one slot's entry at most once per branch. Indoor/outdoor entries occupy exactly one slot; dual entries may occupy two slots with one `inside` and one `outside` aspect (cars, planes, ships, wooden cabins). Nullable only for legacy pre-Alembic rows. |
| `narrative_entities_json` | TEXT NULL | JSON array of `NarrativeEntity` objects: `{label, kind: non_human_character\|object, importance: primary\|secondary\|supporting, reserved_for_scene_index: int\|null}`. The unified register replaces the legacy `companions` + `reserved_entities` split. At most one primary NH-character and at most one secondary NH-character per story. Labels live in a disjoint namespace from environment labels. Entities are **scene-locked**: once `reserved_for_scene_index` is set, it never changes — even after Agent 4 drops the entity, the slot stays ghost-reserved. Nullable only for legacy pre-Alembic rows. |
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
| `contains_entity_label`  | TEXT NULL    | Label of the `NarrativeEntity` (non-human character or object) visually present in this scene, or NULL when the scene contains no entity. The actual entity record (`{label, kind, importance, reserved_for_scene_index}`) lives on `runs.narrative_entities_json` and is matched by normalised label. **Mutable** — Agent 4 and Agent 4b may set it (`entity_action="keep"` / `"claim_floating"`), clear it (`entity_action="drop"`), or leave it null (`entity_action="none"`). Once a label is *first* placed in a slot whose reservation was floating, the entity's `reserved_for_scene_index` is permanently set to that slot. Replaces the legacy `companion_description` + `companion_interaction` columns. |
| `environment_label`      | TEXT NULL    | Denormalised label of this slot's environment (the source of truth is `runs.environments_json[scene_index]`). Cached on the illustration row so the orchestrator can hand Agent 1 / 3 / 4 the environment constraint without joining. **Mutable only by Agent 4b** when it swaps the slot's environment. Nullable only for legacy pre-Alembic rows. |
| `environment_aspect`     | TEXT NULL    | Denormalised aspect for this slot: `single`, `inside`, or `outside`. Same mutation rules as `environment_label`. Nullable only for legacy pre-Alembic rows. |
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

### States

| State                  | Slovak UI label              | Notes                                          |
|------------------------|------------------------------|------------------------------------------------|
| `PENDING`              | "Čaká"                       | Created, not yet started                       |
| `GENERATING_PROMPTS`   | "Pripravujem prompty"        | Claude is producing prompts                    |
| `RENDERING`            | "Kreslím (pokus k/N)"        | ComfyUI job in flight                          |
| `EVALUATING`           | "Vyhodnocujem výsledok"      | Claude inspects the image                      |
| `REVISING_PROMPTS`     | "Upravujem prompty"          | Claude revises prompts after a bad image       |
| `RETHINKING_CONCEPT`   | "Premýšľam koncept"          | Agent 4 proposes a new concept for the scene **inside the same locked environment** |
| `RETHINKING_ENVIRONMENT` | "Prepracovanie prostredia" | Agent 4b is swapping the slot's locked environment (one-shot per branch; extends concept budget by +1). Only fires when the evaluator's verdict is `problem="environment"`. |
| `COMPLETED`            | "Hotovo"                     | Image accepted (auto pipeline OR manual flow — § 6A) |
| `MANUAL_CHATTING`      | "Spoločná tvorba"            | Auto pipeline exhausted; user is chatting with Agent 6 to design a feasible concept manually (§ 6A) |
| `MANUAL_GENERATING_PROMPTS` | "Pripravujem prompty (manuál)" | Agent 1 is translating the agreed manual concept into Danbooru prompts (§ 6A) |
| `MANUAL_RENDERING`     | "Kreslím (manuál, pokus K/5)" | ComfyUI job in flight for a manual attempt (§ 6A)   |
| `FAILED`               | "Nepodarilo sa"              | All automatic attempts exhausted AND the manual flow either was abandoned by the user OR exhausted its own attempt budget (§ 6A) |
| `CANCELLED`            | "Zrušené"                    | Run cancelled while this branch was active     |

### Loop semantics (worst case: 3 × 3 = 9 ComfyUI jobs; 4 × 3 = 12 if Agent 4b fires)

```
# Per-branch local flags (NOT persisted; live only for this run):
#   - env_rethink_used: True once Agent 4b has fired for this slot.
#     Limits Agent 4b to a single invocation per branch.
#   - skip_concept_rethink_once: when set, the *next* outer iteration
#     skips Agent 4 because Agent 4b already rewrote concept + paragraph
#     in the same call.
#
# The "+1 budget" rule: env_rethink_used=True extends the outer
# concept-attempt budget by exactly +1 (i.e. 4 attempts instead of 3),
# acknowledging that Agent 4b's rewrite deserves its own fresh
# inner-loop budget rather than burning the slot it preempted.

env_rethink_used = False
skip_concept_rethink_once = False
concept_attempt = 1
while concept_attempt <= MAX_CONCEPT_ATTEMPTS (3) + (1 if env_rethink_used else 0):
    if concept_attempt > 1 and not skip_concept_rethink_once:
        state = RETHINKING_CONCEPT
        # Agent 4 returns a new concept AND a rewritten paragraph + new
        # excerpt, INSIDE the slot's locked environment (§ 7.1 Call 4).
        # The entity placement uses the unified narrative_entities
        # register and the entity_action discriminator:
        #   - "keep"           — entity reserved for this slot stays
        #   - "drop"           — reserved entity is intentionally
        #                        removed (slot stays ghost-reserved)
        #   - "claim_floating" — a floating supporting entity is
        #                        claimed for this slot (its
        #                        reserved_for_scene_index is then
        #                        permanently set to this slot)
        #   - "none"           — no entity at play in this slot
        # The orchestrator:
        #   1. validates the new excerpt is a verbatim substring of the
        #      new paragraph;
        #   2. validates entity_action ↔ contains_entity_label coherence
        #      and the entity-side scene lock (§ 7.1 Call 4);
        #   3. overwrites runs.story_blocks_json[paragraph_index].text;
        #   4. overwrites illustrations.scene_excerpt + current_concept;
        #   5. emits SSE paragraph_updated{paragraph_index, text};
        #   6. when contains_entity_label changed (including to/from
        #      null), overwrites illustrations.contains_entity_label and
        #      emits SSE illustration_entity_updated{
        #        contains_entity_label, entity: NarrativeEntity | null
        #      } (the full updated entity record from the register, so
        #      the frontend can rebind the entity subtitle in place).
        #   7. when entity_action="claim_floating", also persists the
        #      claim on the register: the entity's
        #      reserved_for_scene_index is set to this slot.
        result = claude.rethink_concept(
            full_story_text=<latest joined paragraph blocks>,
            current_paragraph_text=<latest paragraph at paragraph_index>,
            scene_excerpt=<current excerpt>,
            current_entity=<entity reserved for or currently in this slot>,
            floating_entities=<supporting entities with
                               reserved_for_scene_index=null>,
            environment=<runs.environments_json[scene_index]>,
            failed_concept=<previous current_concept>,
            verdict=<last verdict>,
            style_guide=...,
            character_role=...,
        )
    skip_concept_rethink_once = False
    state = GENERATING_PROMPTS
    prompts = claude.generate_prompts(current_concept, style_guide,
                                      environment=<slot environment>,
                                      contains_entity=<current entity | None>)
    for prompt_attempt in 1..MAX_PROMPT_ATTEMPTS_PER_CONCEPT (3):
        check_cancellation()
        state = RENDERING
        image = runpod.run_workflow(workflow_with_prompts)
        state = EVALUATING
        verdict = claude.evaluate_image(image, current_concept,
                                        style_guide, environment=...)
        if verdict.ok:
            state = COMPLETED
            return success
        if verdict.problem == "environment" and not env_rethink_used:
            # Agent 4b — only agent allowed to swap the slot's locked
            # environment. One-shot per branch; extends the outer budget
            # by +1; on success, the next outer iteration skips Agent 4
            # since 4b already produced fresh concept + paragraph.
            state = RETHINKING_ENVIRONMENT
            result = claude.rethink_environment(...)  # § 7.1 Call 4b
            # Server-side persistence:
            #   - overwrites runs.environments_json[scene_index] AND
            #     illustrations.environment_label/_aspect;
            #   - overwrites story_blocks_json[paragraph_index].text,
            #     scene_excerpt, current_concept;
            #   - applies the same entity_action handling as Agent 4;
            #   - emits SSE illustration_environment_updated{
            #       environment: Environment
            #     }, paragraph_updated, and (when entity changed)
            #     illustration_entity_updated.
            env_rethink_used = True
            skip_concept_rethink_once = True
            break  # exit inner loop -> next outer iteration
        if verdict.problem == "concept":
            break  # exit inner loop -> next concept (Agent 4)
        # verdict.problem == "prompt"
        state = REVISING_PROMPTS
        prompts = claude.revise_prompts(prompts, verdict, ...)
    concept_attempt += 1
state = FAILED  # auto pipeline exhausted; § 6A manual fallback takes over
return failure
```

Each state transition writes to DB and emits one SSE event. The new
SSE events `illustration_entity_updated` and
`illustration_environment_updated` are documented in § 8.4.

---

## 6A. Semi-automatic image generation (manual chat fallback)

### 6A.1 Motivation and high-level behavior

When the fully automatic pipeline (§ 6) exhausts its 3 × 3 attempt
budget for an illustration, the branch does **not** transition straight
to `FAILED` anymore. Instead, the failing illustration's card on
Screen B (§ 9.1) transforms into an interactive chat with a new
**Agent 6 ("the co-illustrator")**. The user and Agent 6 then
collaborate on a concept that is technically feasible on the simple
ComfyUI workflow, and re-trigger RunPod manually until either
(a) the user confirms a result, or (b) the manual attempt budget
(`MAX_MANUAL_ATTEMPTS = 5`) is exhausted. Only then does the
illustration land in `FAILED`.

The feature is a *fallback*, never an entry point: the user reaches
it exclusively through an auto-pipeline failure. The card is the only
surface for the manual flow — there is no separate page, modal, or
route.

### 6A.2 Design philosophy (binding on Agent 6's prompt)

Agent 6's persona is explicitly **assertive, confident, gently
manipulative, and never technically pedantic**. The product premise of
"the app feels limitless" must hold for as long as possible. Concretely
the prompt enforces:

1. **Never enumerate technical limits up front.** Agent 6 must not say
   "we cannot do inpainting", "we cannot do regional prompting",
   "we cannot keep a consistent environment", "only one humanoid
   allowed", etc. Such constraints exist (see § 6A.5) but are *never*
   surfaced unless the user proposes something that violates them, and
   even then Agent 6 explains in **generic, non-technical terms** ("that
   kind of scene is unusually hard for me — let's lean a bit closer to
   something I'm great at").
2. **Never preemptively forbid.** Agent 6 must not pre-empt a user's
   idea with "you cannot ask for X". It only pushes back when the user
   has actually proposed X.
3. **Subtly steer to feasibility.** When a proposal is borderline,
   Agent 6 leads the user toward the nearest feasible concept by
   suggesting concrete alternatives that *sound at least as good*. It
   never lowers ambition openly; it reframes.
4. **Never reduce success probability.** Agent 6 must NEVER propose
   adding elements that demonstrably lower success probability (extra
   humanoids, complex multi-character interaction, abstract metaphors
   without a concrete depictable scene, etc.).
5. **Technical detail on demand only.** If the user explicitly asks
   *why* an idea is hard, Agent 6 may give a short, friendly
   explanation in human terms (≤ 2 sentences). Otherwise: zero
   technical jargon.
6. **No static explainer text in the UI.** The chat is the entire
   surface; the welcome message (§ 6A.7 step 1) is the user's only
   introduction to the flow.
7. **Verbatim concept handoff (binding invariant).** When Agent 6
   asks the user to confirm a concept (phase
   `awaiting_concept_confirmation`, § 7.1 Call 6), the `reply` must
   contain the **exact English concept text** that will be sent to
   Agent 1 — character for character — embedded inside the summary
   bubble (typically delimited by a quoted block, e.g. surrounded by
   straight double quotes or a Markdown blockquote). The model
   chooses the final wording **before** asking for confirmation, not
   after. On `phase=concept_confirmed` the server uses
   `concept_candidate` byte-for-byte as both `illustrations.current_concept`
   *and* as Agent 1's input — without rewriting, re-translating, or
   abbreviating it. Implementation MUST also assert at this seam that
   `concept_candidate` equals the previous turn's `concept_candidate`
   verbatim (no last-second edit during `concept_confirmed`); a
   mismatch is treated as a Claude failure and re-prompted. Stated
   plainly: **what the user sees in the chat history immediately
   before a rendered image equals, byte-for-byte, the source concept
   used to generate that image.**
8. **User drives feedback after each image.** Unlike the auto pipeline
   (where Agent 2 *sees* the image), Agent 6 does **not** see the
   rendered images. Its post-image job is therefore to **elicit
   detailed feedback from the user**, not to propose new concepts on
   its own. The default post-image phase is `gathering_feedback`
   (§ 7.1 Call 6), in which Agent 6:
   - reminds the user — in the very first post-image turn — that it
     cannot see the image and that the user is its eyes (the i18n
     framing string in § 6A.7 step 5 says this explicitly; the agent
     may echo the same idea in subsequent turns when relevant);
   - asks the user to describe what is good and what is wrong in the
     image, in concrete visual terms;
   - actively probes for the user's reaction to the **key, strategic,
     or technically-fragile elements of the agreed concept** — the
     elements Agent 6 estimates are most likely to be misrendered by
     a simple ComfyUI workflow. Example: *"We agreed the cat would
     be perched on her shoulder. Is it actually there, on her
     shoulder?"* The agent does NOT probe every element of the
     concept; only the ones it judges most load-bearing or most
     prone to failure.
   - waits for the user to volunteer feedback on those key elements
     first, and only asks if the user has not addressed them.
9. **No feedback summarization.** Agent 6 does not produce a
   structured summary of the gathered feedback at the end of the
   feedback phase. Once it judges the conversation has covered the
   key elements, it asks a single short closing question — *"Have
   you said everything you wanted to say about the image? If yes,
   we can go for another attempt."* — and on user confirmation
   transitions to `phase=feedback_confirmed`. The server passes the
   raw post-image user-message slice to Agent 7 (§ 7.1 Call 7); it
   does not ask Agent 6 to paraphrase it.
10. **Drift detection.** If during `gathering_feedback` the user's
    feedback starts to drift *off-concept* — i.e. the user is no
    longer talking about elements that are missing from / wrong in /
    excessive over the agreed concept, but about entirely new ideas
    that are not part of the agreed concept — Agent 6 must flag this
    explicitly and ask the user to choose: (a) keep iterating the
    current agreed concept (in which case the new ideas are dropped
    and the feedback phase continues), or (b) discard the current
    agreed concept and **design a fresh one together**. Choice (b)
    is signalled by phase `restart_concept` (§ 7.1 Call 6); on it
    the server resets the manual session into the concept-design
    sub-phase and Agent 6 returns to `gathering` on the next turn.
11. **Polite refusal of impossible / unethical requests.** If at any
    point the user asks for an image that violates the shared
    cross-agent constraints (e.g. two humans on the canvas, see
    § 6A.5 and § 7.3.6) or that is ethically out of bounds
    (sexualized minors, hateful imagery, graphic gore, real
    identifiable persons, etc.), Agent 6 politely declines that
    specific request, briefly explains the limit in generic
    non-technical terms, and offers a feasible alternative that
    captures the same emotional beat. The refusal does **not** end
    the manual session — the agent stays in its current sub-phase
    and continues collaborating.
12. **Maintain cumulative prompt-engineering notes.** Across the
    manual session, Agent 6 incrementally curates a short
    **English-only** memo — `prompting_notes` — that captures
    *prompt-level* lessons distilled from the running feedback:
    things this particular renderer (Illustrious XL + MHA LoRA,
    simple single-pass workflow) has demonstrably struggled with
    on this illustration, plus the prompt-level workarounds that
    helped. Concretely the memo records *renderer weaknesses and
    countermeasures* — e.g. "the robot keeps rendering as mist /
    ghostly figure; needs explicit `mecha, metallic plating,
    glowing eyes, hard edges` tags and `humanoid, person, ghost,
    mist, ethereal` in the negative" — **not** user preferences,
    not aesthetic taste, not concept-level edits (those belong
    in the concept text itself). The memo is updated by Agent 6
    via the optional `prompting_notes_update` output field
    (§ 7.1 Call 6) on any turn where the latest exchange yielded
    a useful prompt-level lesson; when present, it **fully
    overwrites** the previous notes (Agent 6 is responsible for
    folding old lessons into the new memo when relevant — the
    server does not merge). The notes are passed forward as an
    optional input to Agent 1 on the *next* `concept_confirmed`
    dispatch and to Agent 7 on every `feedback_confirmed`
    dispatch, so both prompt-authoring agents see the same
    accumulated knowledge of what works for this illustration.
    The notes **persist across `phase=restart_concept`**
    (rule #10) — switching to a fresh concept does not erase
    what we learned about the renderer's blind spots on this
    illustration, because those blind spots typically transfer
    (LoRA-character anatomy quirks, environment-tag failure
    modes, etc.). The notes are not shown in the UI; they live
    only on `manual_illustration_sessions.prompting_notes`
    (§ 6A.6) and in the agent payloads.

### 6A.3 Entry condition

The orchestrator initiates the manual flow when **all of** the
following hold for an illustration:

- The auto loop in § 6 has exhausted both
  `MAX_CONCEPT_ATTEMPTS` (3) and the inner
  `MAX_PROMPT_ATTEMPTS_PER_CONCEPT` (3) without an accepted image,
  **and** the branch was not cancelled.
- The run is still in `RUNNING` (it has not been cancelled and the
  run-level orchestrator has not aborted via § 8.8).
- `illustrations.manual_attempts` is `0` (the manual flow has never
  been entered for this illustration before).

When all three hold, the orchestrator:

1. Persists `illustrations.state = MANUAL_CHATTING`.
2. Creates the `manual_illustration_sessions` row for this
   illustration (§ 6A.6).
3. Emits one SSE `illustration_state` event with the new state and
   one `illustration_manual_started` event (§ 8.4 amendment) carrying
   the localized welcome message (§ 6A.7 step 1) so the frontend can
   immediately render it as the first chat bubble.
4. Stops touching this illustration from the auto-orchestrator side —
   subsequent transitions are driven by the new endpoints in § 8.10.

The completion-count accounting on the run (`runs.completed_count`,
`runs.failed_count`) does **not** advance while an illustration is in
any `MANUAL_*` state. The run remains in `RUNNING` until every branch
either reaches `COMPLETED` or `FAILED`, including via the manual flow.
This means the global progress bar (§ 9.1 Screen B) can stay at "N-1
of N done" indefinitely while the user takes their time in the manual
chat; that is intentional and matches the user-first philosophy of
the feature.

If the orchestrator itself errors during the entry transition (DB
failure etc.), the branch falls through to `FAILED` with
`error_message` set, exactly as it would have without this feature.

### 6A.4 Per-illustration manual loop

Numbered steps below run inside one illustration's manual flow.
`manual_attempts` starts at `0` and is incremented exactly when a
ComfyUI manual render *starts*. The loop has two distinct
sub-phases — **concept design** and **post-image feedback
gathering** — separated by a render. Agent 6 (§ 7.1 Call 6) is
invoked on every user turn in either sub-phase. The `phase` field
of Agent 6's reply identifies the current step:

| `phase`                          | Sub-phase           | Meaning                                                                                                  |
|----------------------------------|---------------------|----------------------------------------------------------------------------------------------------------|
| `gathering`                      | concept design      | Concept negotiation continues. `concept_candidate` is null.                                              |
| `awaiting_concept_confirmation`  | concept design      | Agent 6 has finalized a concept verbatim (§ 6A.2 rule #7); `reply` quotes it in English; `concept_candidate` carries the same string. |
| `concept_confirmed`              | concept design      | User confirmed the just-quoted concept. Server dispatches Agent 1 + render.                              |
| `gathering_feedback`             | feedback gathering  | Image was rendered; user is describing what works / doesn't. `concept_candidate` and `user_feedback` are null. |
| `awaiting_feedback_confirmation` | feedback gathering  | Agent 6 thinks feedback is complete; asks the user to confirm "did you say everything?".                 |
| `feedback_confirmed`             | feedback gathering  | User confirmed feedback is complete. Server dispatches Agent 7 + render with revised prompts.            |
| `restart_concept`                | drift escape hatch  | User chose to redesign the concept rather than iterate prompts (§ 6A.2 rule #10). Server resets to concept design. |
| `accepted`                       | terminal            | User accepted the most recent rendered image as the canonical illustration.                              |

#### 6A.4.1 Concept-design sub-phase

1. **Open.** State is `MANUAL_CHATTING`. The frontend renders the
   chat surface (§ 9.1 amendment) seeded with Agent 6's localized
   welcome message (the message text is computed by the **backend**
   in the run's `source_language` so it persists in
   `manual_messages` like every other assistant turn, and so all
   future SSE subscribers see the same first bubble; see § 6A.7).
   On open the active sub-phase is **concept design**.
2. **User sends a message.** The frontend POSTs to § 8.10.1. The
   backend appends it to `manual_messages`, then invokes Agent 6
   with the running transcript (§ 7.1 Call 6) and the current
   sub-phase. In the concept-design sub-phase Agent 6 replies with
   one of:
   - `gathering` — still negotiating the concept; `reply` is the
     next assistant turn. No state change. SSE
     `manual_message_appended` (assistant role).
   - `awaiting_concept_confirmation` — Agent 6 has finalized a
     candidate concept that satisfies § 6A.5. `reply` quotes the
     verbatim English concept text inline (per § 6A.2 rule #7) and
     explicitly asks for confirmation in the user's
     `source_language`. `concept_candidate` carries the **exact
     same** English string the user sees quoted in `reply`. No
     state change yet. SSE `manual_message_appended`.
   - `concept_confirmed` — Agent 6 detected the user's most recent
     message as approval of the previously-quoted candidate.
     `concept_candidate` is the carried-forward English string,
     **byte-for-byte identical** to the prior turn's value (server
     asserts this; mismatch → treated as Claude failure and
     re-prompted). The backend behavior on this phase is governed
     by step 3.

   Like Agent 0a, the model is forbidden from jumping directly from
   `gathering` to `concept_confirmed` — a `concept_confirmed` turn
   must be preceded by an `awaiting_concept_confirmation` turn in
   the same manual session, and a server-side guard demotes any
   orphan `concept_confirmed` reply back to
   `awaiting_concept_confirmation`.

3. **On `phase=concept_confirmed`:** server enforces the
   manual-attempt budget *before* dispatching anything. If
   `manual_attempts >= MAX_MANUAL_ATTEMPTS` (= 5) the budget is
   already exhausted by prior attempts; this should not happen
   because the budget check in step 8 already triggered the
   apology turn. Otherwise:
   1. Set `illustrations.current_concept = concept_candidate`
      (overwriting whatever value the auto loop left), update its
      English source-of-truth column and (if `source_language !=
      'en'`) update the source-language row in
      `illustration_concept_translations`. **Stale rows in other
      languages are NOT eagerly retranslated** — the existing
      "show stale + refetch in background" path (§ 5.5) handles
      them when a user with a non-source language visits the run.
   2. Transition state to `MANUAL_GENERATING_PROMPTS`. Emit
      `illustration_state`.
   3. Call Agent 1 (`generate_prompts`, § 7.1 Call 1) with the
      manual concept (verbatim, no edits), the **existing**
      `style_guide` from the run, the existing `character_role`
      / character config (§ 7.3.7), and the current
      `manual_illustration_sessions.prompting_notes` value as the
      optional `prompting_notes` input (NULL if the manual session
      has not accumulated any yet). Agent 1's auto-pipeline
      contract is unchanged — when invoked from the auto loop the
      `prompting_notes` input is always NULL and Agent 1 has no
      idea this is a manual cycle. When invoked here with non-NULL
      notes, Agent 1 treats them as authoritative prompt-level
      hints (see § 7.1 Call 1 and § 6A.2 rule #12).
   4. Persist `current_prompts_json` and `current_workflow` (§ 5
      `illustrations` columns).
   5. Increment `manual_attempts` by 1. Transition state to
      `MANUAL_RENDERING`. Emit `illustration_state`.
   6. Dispatch one ComfyUI job (§ 7.2). Use the exact same workflow,
      LoRA, and characters as the auto loop.
   7. On RunPod success: store the image to
      `OUTPUT_DIR/runs/<run_id>/manual_<scene_index>_<manual_attempts>.png`.
      Do **NOT** overwrite `illustrations.image_path` yet — the
      manual loop only writes to `image_path` on user confirmation
      (step 7 below). Persist the new image's path on the
      `manual_illustration_sessions` row as
      `last_manual_image_path`, and persist
      `last_agreed_concept` = the verbatim concept the user just
      confirmed (so a later prompt-revision cycle in step 5 can
      reference it without re-deriving it from the transcript).
   8. Transition state back to `MANUAL_CHATTING`, **now in the
      feedback-gathering sub-phase** (the server marks the
      `manual_illustration_sessions` row's `phase` column
      accordingly — see § 6A.6). Emit `illustration_state`. Emit
      `manual_image_rendered` (§ 8.4 amendment) with `image_url`,
      `manual_attempts`, and the static, backend-inserted "please
      review" message i18n key (§ 6A.7 step 5) so the frontend can
      render the image and the review prompt as two new bubbles in
      the chat in the correct order.
   9. **No Agent 2 evaluation runs.** The image is presented to
      the user as-is. Agent 6 does not see it either — the user is
      the only viewer (§ 6A.2 rule #8).
   10. On RunPod failure (timeout / non-200 / corrupted image): treat
       as a *consumed* manual attempt (do not retry implicitly).
       Append an assistant chat bubble in the user's language
       informing them the render failed and inviting them to
       describe a different angle, then re-enter the
       **concept-design** sub-phase of `MANUAL_CHATTING`. Emit
       `illustration_state` and `manual_message_appended`. The
       user retains `MAX_MANUAL_ATTEMPTS - manual_attempts`
       remaining tries.

#### 6A.4.2 Feedback-gathering sub-phase

4. **User reviews the image and replies.** The sub-phase is now
   `gathering_feedback`. The user's message is appended to
   `manual_messages` and Agent 6 is invoked. In this sub-phase
   Agent 6 replies with one of:
   - `gathering_feedback` — feedback collection continues. The
     model asks one focused question, probes for the user's
     reaction to a key concept element if the user has not yet
     mentioned it, and otherwise mirrors the user's observations
     (§ 6A.2 rule #8). `concept_candidate` and `user_feedback` are
     `null`. No state change. SSE `manual_message_appended`.
   - `awaiting_feedback_confirmation` — Agent 6 judges the
     conversation has covered the key elements (the user has
     mentioned, or been asked about and replied on, the
     load-bearing parts of the agreed concept) and asks a single
     short closing question — *"Have you said everything you
     wanted to say about the image? If yes, we can go for another
     attempt."* (§ 6A.2 rule #9). `concept_candidate` and
     `user_feedback` are `null`. No state change. SSE
     `manual_message_appended`.
   - `feedback_confirmed` — the user has affirmed feedback is
     complete. `concept_candidate` and `user_feedback` are `null`
     (the agent does not summarize the feedback; the server slices
     it from the transcript — see step 5). The backend behavior on
     this phase is governed by step 5.
   - `restart_concept` — Agent 6 detected feedback drift
     (§ 6A.2 rule #10) AND the user, on being asked, chose to
     redesign rather than iterate. The backend behavior on this
     phase is governed by step 6.
   - `accepted` — the user is happy with the current image and
     wants to keep it. See step 7.

   Server-side guards (mirroring step 2):
   - A `feedback_confirmed` reply must be immediately preceded by
     an `awaiting_feedback_confirmation` reply from Agent 6 in the
     same manual session, with at least one user turn in between
     (the user's confirmation). Orphan `feedback_confirmed` is
     demoted to `gathering_feedback`.
   - An `accepted` reply must be preceded by at least one `image`
     row in the manual transcript (you can't accept what hasn't
     been shown). Otherwise it is demoted to `gathering_feedback`.
   - A `concept_confirmed` reply received in the feedback sub-phase
     is treated as a model bug and demoted to `gathering_feedback`
     (the model must transition through `restart_concept` to leave
     this sub-phase).

5. **On `phase=feedback_confirmed`:** server dispatches a prompt
   revision via the new Agent 7 (`manual_revise_prompts`, § 7.1
   Call 7) instead of routing back through Agent 1. The exact
   sequence:
   1. Re-run the budget pre-check from step 3 (same semantics).
   2. Slice the post-image user-message turns from
      `manual_messages` — every `role='user'` row created **after**
      the most recent `role='image'` row — and concatenate their
      `content` fields into a single `user_feedback_text` blob
      (with newline separators preserved). This is the raw
      feedback handed to Agent 7; no agent paraphrasing happens
      in between.
   3. Transition state to `MANUAL_GENERATING_PROMPTS`. Emit
      `illustration_state`.
   4. Call Agent 7 (`manual_revise_prompts`, § 7.1 Call 7) with:
      - `last_agreed_concept` —
        `manual_illustration_sessions.last_agreed_concept` (the
        verbatim concept the user confirmed before the most recent
        image, see step 3.7).
      - `user_feedback` — the `user_feedback_text` blob computed
        in step 5.2.
      - `last_positive_prompt` / `last_negative_prompt` — the
        positive and negative prompts that produced the most recent
        manual image (read from `current_prompts_json`).
      - `prompting_notes` —
        `manual_illustration_sessions.prompting_notes` (the
        cumulative English memo curated by Agent 6 across this
        manual session, § 6A.2 rule #12). NULL if Agent 6 has not
        produced any notes yet. Agent 7 treats these as
        authoritative prompt-level hints alongside the immediate
        `user_feedback` (see § 7.1 Call 7).
      - `style_guide`, `character_role`, character config — same
        sources as Agent 1.
   5. Persist Agent 7's revised prompts into
      `current_prompts_json` (overwriting). The `workflow` field
      is **not** re-decided here — Agent 7 reuses the same
      `current_workflow` value (it cannot toggle between
      `single-lora` and `no-lora`, because the cast shape is
      fixed for this illustration).
   6. Increment `manual_attempts` by 1. Transition state to
      `MANUAL_RENDERING`. Emit `illustration_state`.
   7. Dispatch one ComfyUI job (§ 7.2) with the revised prompts.
   8. From here on follow steps 3.7 → 3.10 of the concept-design
      sub-phase. On RunPod success, the sub-phase resets to
      `gathering_feedback` (post-image) again, anchored on the
      *same* `last_agreed_concept` — i.e. the concept does not
      change; subsequent iterations of step 5 will pass the
      **most recently used** positive+negative prompts to Agent 7
      (not the originals), so each revision builds on the previous
      attempt's prompts. On RunPod failure the sub-phase resets to
      `gathering_feedback` and Agent 6 invites further iteration.

6. **On `phase=restart_concept`:** server resets the manual session
   to the concept-design sub-phase. No render is dispatched and
   no Agent 7 call happens; `manual_attempts` is **not**
   incremented (the drift exit is free).
   1. Clear `last_agreed_concept` and `last_manual_image_path` on
      `manual_illustration_sessions` (the previous concept and
      its image are no longer the working baseline; they remain in
      `manual_messages` for the transcript but are no longer the
      thing being iterated on). **Do NOT clear `prompting_notes`**
      — the cumulative prompt-engineering memo persists across a
      concept restart on purpose (§ 6A.2 rule #12), because the
      renderer's blind spots typically transfer to the fresh
      concept (LoRA-character anatomy quirks, environment-tag
      failure modes, etc.).
   2. Persist Agent 6's reply (which is the natural-language
      acknowledgement, "OK, let's design a fresh idea together")
      as an assistant row. Emit `manual_message_appended`.
   3. Mark the `manual_illustration_sessions` row's sub-phase as
      `concept_design`. State stays at `MANUAL_CHATTING` (the
      sub-phase is internal — there is no separate
      `MANUAL_CONCEPT_DESIGN` state).
   4. The next user turn re-enters step 2 of this section
      (concept-design `gathering`).

7. **On `phase=accepted`:** server promotes the last manual image to
   the canonical illustration image.
   1. Copy / rename `last_manual_image_path` to the canonical
      `runs/<run_id>/scene_<scene_index>.png` (overwriting any
      previous canonical file if one existed from an earlier auto
      attempt). Set `illustrations.image_path` accordingly.
   2. Transition `illustrations.state = COMPLETED`. Increment
      `runs.completed_count` like a normal completion.
   3. Emit `illustration_state` (COMPLETED), then
      `illustration_completed` (carrying the canonical `image_url`)
      — same payloads the auto loop would emit. The frontend's
      existing logic replaces the chat overlay with the standard
      completed card automatically (§ 9.1 amendment).
   4. The `manual_illustration_sessions` row is retained
      (read-only) for audit / debugging; no further writes happen
      to it after `accepted`. The frontend hides the chat from
      future views of this illustration.

8. **Budget check on every Agent 6 turn.** Independently of the
   `phase`, after each Agent 6 reply is persisted the server checks
   `manual_attempts`. When `manual_attempts >= MAX_MANUAL_ATTEMPTS`
   (i.e. all 5 attempts have been *consumed*) AND the latest reply
   is not `accepted`:
   1. Append a final assistant chat bubble containing the localized
      apology message (§ 6A.7 step 6).
   2. Transition `illustrations.state = FAILED` with
      `error_message = "Manual attempts exhausted"` (English
      sentinel; the UI does not render this — see § 8.6 below).
   3. Increment `runs.failed_count`.
   4. Emit `illustration_state` (FAILED), then
      `illustration_failed`, then `illustration_manual_ended`
      (§ 8.4) so the frontend knows to collapse the chat overlay
      and re-render the standard FAILED card (the existing
      "Túto ilustráciu sa nepodarilo vytvoriť." block, § 9.1).
   5. POSTs to § 8.10 endpoints for this illustration now return
      `409 Conflict`.
9. **Cancellation.** Run cancellation (§ 8.5) checks the manual
   path too: any illustration in a `MANUAL_*` state transitions
   straight to `CANCELLED` on the next cancellation observation
   point (we don't have a long-running async loop here, but the
   POST handlers in § 8.10 each check the run's cancellation flag
   before doing real work and return 409 if set).
10. **User abandonment.** If the user navigates away from the run
    while the illustration is `MANUAL_CHATTING`, nothing happens —
    the state is durable. Returning to the page restores the chat
    exactly via the snapshot (§ 8.4) and the user can continue or
    ignore it. There is no idle timeout in MVP.

### 6A.5 Feasibility envelope enforced by Agent 6

Agent 6's prompt (`agents/manual_concept.md`) explicitly tells the
model that any concept it confirms must satisfy ALL of the following.
These bounds are the same envelope the simple ComfyUI workflow
(§ 7.2) and the auto pipeline already obey; the manual flow does not
introduce any *new* technical capabilities.

- **No inpainting, no regional prompting.** Concepts must describe
  a whole-canvas single scene, not "this corner has X and that corner
  has Y".
- **At most one humanoid.** Zero or one character (from the same
  per-role LoRA set the run already uses — § 7.3.7), and no
  background humans, no crowds, no secondary humanoids. If the user
  proposes a second person, Agent 6 reframes to a single-character
  scene.
- **Narrative entities are non-humanoid only (animate ones).** Same
  rule as Agent 0a (§ 7.1 Call 0a rule #8). The manual concept may
  keep the existing entity, drop it, or substitute another entry
  from the run's `narrative_entities` register (a non-human
  character or an object). It must not invent new entities outside
  the register.
- **No consistent-environment promises.** The model must not commit
  to a setting that depends on continuity with other illustrations
  in the run (e.g. "the same kitchen as in scene 2"). Each manual
  illustration is treated as an isolated scene.
- **Single moment, depictable.** The concept must be a single
  frozen action / pose / expression, mirroring § 7.3.4. No
  "throughout the day" or "starts angry then smiles" composites.

These rules are checked first by Agent 6's prompt (the model is
expected to self-police) and additionally re-checked by the
backend on every `awaiting_concept_confirmation` reply via a
lightweight heuristic over `concept_candidate` text (counts of
humanoid words, presence of "and then", presence of multiple
distinct settings, etc.). On heuristic failure the server demotes
the reply to `gathering`, replaces `reply` with a localized gentle
nudge ("That's a fun direction — can we narrow it to a single
moment with our hero and the cat?"), and lets the conversation
continue. The heuristic is intentionally conservative: false
positives are tolerable, false negatives would push infeasible
concepts to ComfyUI and waste budget.

**Application to Agent 7.** The same envelope applies to **Agent 7
(`manual_revise_prompts`, § 7.1 Call 7)**. Even when the user's
feedback nudges in an out-of-envelope direction ("can you add
another character beside her?"), Agent 7 must refuse to translate
that instruction into prompts and instead keep the revised
prompts within envelope. Agent 7 cannot be used as a side channel
to bypass the constraints Agent 6 already enforces upstream — the
two agents share the same § 6A.5 envelope and the same § 7.3.6
negative-prompt baseline. If a piece of user feedback can be
honored within envelope, Agent 7 honors it; if not, Agent 7
silently drops or reframes it while staying faithful to the
agreed concept. (The user never directly sees Agent 7's reasoning;
the next rendered image is the only feedback channel back to the
user.)

**Ethics envelope.** Independently of the technical envelope above,
Agent 6 must politely decline — per § 6A.2 rule #11 — any request
to depict imagery that is ethically out of bounds (sexualized
minors, non-consensual sexual imagery, hateful content,
identifiable real people in defamatory contexts, gore involving
real-world tragedies, etc.). The list is non-exhaustive; the
prompt instructs the model to use judgement and err on the side
of refusal when in doubt. A refusal stays in the current
sub-phase (concept design → `gathering`; feedback gathering →
`gathering_feedback`) and offers a feasible alternative that
preserves the user's underlying emotional intent. Agent 7 is also
prompted to refuse any prompt-revision request that would
encode such content, even if it slipped past Agent 6 upstream.

### 6A.6 Data model additions

#### `illustrations` (amended)

Two new columns:

| Column              | Type    | Notes                                                                          |
|---------------------|---------|--------------------------------------------------------------------------------|
| `manual_attempts`   | INTEGER | `DEFAULT 0`. Incremented each time a manual ComfyUI render starts.             |
| `manual_state_json` | TEXT    | NULL until the manual flow is entered. Reserved for future per-flow metadata; in MVP the column is created but only stores `{}` so the migration is forward-compatible. |

No other columns change. The existing `image_path` column continues
to hold the canonical scene image; the manual loop only writes to
it on `phase=accepted`.

#### `manual_illustration_sessions` (new table)

One row per illustration that has ever entered the manual flow.

| Column                  | Type         | Notes                                                                                 |
|-------------------------|--------------|---------------------------------------------------------------------------------------|
| `id`                    | TEXT (UUID4) | Primary key.                                                                          |
| `illustration_id`       | TEXT FK      | → `illustrations.id`, UNIQUE (1:1 with the illustration).                             |
| `sub_phase`             | TEXT         | One of `concept_design` / `feedback_gathering`. `concept_design` on creation; flipped to `feedback_gathering` immediately after a successful manual render (§ 6A.4 step 3.8); flipped back to `concept_design` on `phase=restart_concept` (§ 6A.4 step 6) or on RunPod failure during a `concept_confirmed` dispatch. Used by § 8.10.1 to know which Agent 6 phase enum subset is valid for the next turn and by snapshots to restore the right UI affordances on reconnect. |
| `last_manual_image_path`| TEXT NULL    | Relative path under `OUTPUT_DIR` of the most recent manual render that has not yet been promoted to the canonical `image_path`. NULL before the first render. Cleared on `phase=restart_concept`. |
| `last_concept_candidate`| TEXT NULL    | The most recent `concept_candidate` returned by Agent 6 with `phase=awaiting_concept_confirmation`. Used by the server to assert verbatim handoff at `concept_confirmed` (§ 6A.2 rule #7). Reset to NULL after each `concept_confirmed` transition so a stale candidate cannot be re-confirmed. |
| `last_agreed_concept`   | TEXT NULL    | The verbatim English concept the user most recently confirmed (i.e. the same string the next image was rendered from). Persisted on `concept_confirmed`; consumed as Agent 7's `last_agreed_concept` input during a subsequent `feedback_confirmed` dispatch. Cleared on `phase=restart_concept`. |
| `prompting_notes`       | TEXT NULL    | Cumulative **English-only** prompt-engineering memo curated by Agent 6 across this manual session (§ 6A.2 rule #12). NULL until Agent 6 emits its first non-null `prompting_notes_update` (§ 7.1 Call 6). On every subsequent non-null update from Agent 6 the column is **fully overwritten** with the new value (no server-side merging). Consumed by Agent 1 on `concept_confirmed` dispatches and by Agent 7 on `feedback_confirmed` dispatches, as an optional `prompting_notes` input. **Persists across `phase=restart_concept`** (not cleared with `last_agreed_concept` / `last_manual_image_path`). Not surfaced in the UI. |
| `created_at`            | DATETIME     |                                                                                       |
| `updated_at`            | DATETIME     | Bumped on every Agent 6 turn and every render.                                         |

#### `manual_messages` (new table)

Mirrors `session_messages` for the chat session phase, but per
illustration.

| Column            | Type         | Notes                                                                                  |
|-------------------|--------------|----------------------------------------------------------------------------------------|
| `id`              | TEXT (UUID4) | Primary key.                                                                           |
| `illustration_id` | TEXT FK      | → `illustrations.id`. Indexed.                                                         |
| `role`            | TEXT         | `user` / `assistant` / `image`. The `image` role is a synthetic assistant-side message whose `content` is empty and whose `image_url` is the rendered manual attempt. Stored so reloads reproduce the bubble order exactly. |
| `content`         | TEXT         | Empty for `role='image'`; the message text otherwise.                                  |
| `image_url`       | TEXT NULL    | Set only for `role='image'`. Root-relative URL under `/static/...`.                    |
| `manual_attempt_index` | INTEGER NULL | For `role='image'`, the 1-based attempt index (`1..MAX_MANUAL_ATTEMPTS`). NULL otherwise. |
| `created_at`      | DATETIME     |                                                                                        |

The frontend renders each row directly:

- `role='user'` → right-aligned chat bubble in the user's color.
- `role='assistant'` → left-aligned assistant bubble (the
  `**bold**`-via-`#…#` syntax in the localized welcome string is
  rendered with a `<strong>` span; see § 6A.7).
- `role='image'` → full-width image bubble at the card's content
  margin, with the static "review the image" assistant bubble
  immediately after (also a separate `assistant`-role row).

There is no truncation cap on `manual_messages` rows per
illustration; the natural cap comes from `MAX_MANUAL_ATTEMPTS = 5`
plus ~10 assistant turns per attempt = well under the
`CHAT_MESSAGES_MAX_PER_SESSION` envelope. No explicit limit is
enforced server-side beyond a generous safety cap of 200 rows per
illustration (returns 409 after that — this should never trip in
practice).

### 6A.7 Localized strings (i18n)

All assistant-authored "framing" copy lives as i18n keys, not in
Agent 6's prompt or in the database. Agent 6 only authors the
conversational replies. The static framing strings are inserted by
the **backend** on the server side so they persist in
`manual_messages` and round-trip via SSE snapshots; the frontend
does not synthesize chat bubbles on its own.

New keys under `illustration.manual` in each locale dictionary:

1. **`illustration.manual.welcome`** — first assistant bubble at
   step 1. The text contains exactly one bold span delimited by
   `#...#` (so the JSON-safe form is plain text); a small renderer
   on the frontend splits on `#` and wraps the inner segment in
   `<strong>`. Required content (semantics — operator wording may
   vary):

   - English: *"The automatic image generation failed, but no
     panic! We can work on it together by joining human and AI
     skills. If you want to continue working on this illustration,
     just #let me know about your own illustration concept#. I'll
     tell you whether your idea is technically realistic, and we
     can iterate together until we land on the final idea. Then
     I'll translate it into the prompts that go to the image
     generation AI. After we get the image, I'll guide you through
     the next round. Do you want to try?"*
   - Slovak and Czech: equivalent wording, with the same single
     `#...#` bold span.

2. **`illustration.manual.summary_intro`** — never sent as a
   standalone bubble; Agent 6's `awaiting_concept_confirmation`
   `reply` embeds it naturally ("So, just to make sure: …",
   followed by the verbatim English concept text per § 6A.2 rule
   #7). This is a nudge for the prompt, not a UI string. Still
   listed here so the parity test (§ 11.3 / § 9.6.1) keeps the
   three locales aligned on it (the prompt loads the
   active-language value inline as authoring guidance — see
   § 6A.8).

3. **`illustration.manual.render_failed`** — assistant bubble
   inserted at step 3.10 ("RunPod failure"). Short, apologetic,
   invites the user to try a different angle.

4. **`illustration.manual.budget_exhausted`** — final assistant
   bubble at step 6.1: "I'm sorry, I've used up my creative tries
   for this illustration. Sometimes the perfect image just won't
   come, and that's okay. We can keep the rest of the story." or
   equivalent. The wording must NOT be self-deprecating about the
   technology — it stays warm and conversational.

5. **`illustration.manual.review_prompt`** — assistant bubble
   inserted by the backend immediately after every
   `manual_image_rendered` event (§ 6A.4 step 3.8). This is the
   bubble that opens the feedback-gathering sub-phase, so it
   carries three responsibilities at once:
   1. **Show the image as the user's responsibility.** The text
      must say, in plain words, that **Agent 6 itself does not see
      the rendered image** — in the auto pipeline an evaluator
      agent inspected each render, but in the collaboration mode
      the user is the only viewer. The user is therefore explicitly
      asked to be the agent's eyes.
   2. **Instruct the user to be concrete and specific.** Rather
      than the generic "does it look good?", the bubble explicitly
      asks the user to describe what is right and what is wrong on
      the image in concrete visual terms — referencing the agreed
      concept, especially its most load-bearing elements.
   3. **Mention the escape hatches.** A one-line reminder that the
      user can either confirm they want to keep the image as-is
      (which ends the manual flow with success) or, if they want to
      go in a fundamentally different direction, they can simply
      say so and Agent 6 will help redesign the concept from
      scratch.

   English reference wording (semantics — exact phrasing may vary
   across the three locales as long as all three points above are
   preserved):
   *"Here is the image. A quick heads-up: unlike in the fully
   automatic mode, I don't actually see it — you do, and you're my
   eyes. Take a moment to look it over and tell me, as
   specifically as you can, what works and what doesn't. It helps
   most when you compare it to the concept we agreed on — does
   each important element really show up the way we meant it to?
   If you're happy with the image as-is, just say so and we'll
   keep it. If you'd rather discard this direction and design a
   different concept together, that's fine too — just tell me."*
   Same single-bubble length budget as the welcome message; no
   `#...#` formatting in this one.

6. **`illustration.manual.budget_remaining_hint`** — never shown
   as a bubble; appended by the prompt loader to the active
   transcript as authoring guidance for Agent 6 (so the model
   knows how many attempts remain and can pace its assertiveness
   accordingly).

The chat UI text labels (header pill "Spoločná tvorba", the input
placeholder, the disabled-while-rendering hint, etc.) live under
`illustration.manual.ui.*` keys; they are not authored by Agent 6
and are not persisted in `manual_messages`.

### 6A.8 Agent prompt files (Agents 6 and 7)

Two files in `backend/app/agents/` back the manual flow. The startup
loader fails fast if either is missing or empty, same as the
others (§ 7.4).

#### 6A.8.1 `manual_concept.md` (Agent 6)

The file structure mirrors the existing agents:

1. Role statement ("You are Agent 6, the co-illustrator …"),
   explicitly framing the agent's **dual responsibility**: it
   collaborates with the user on a concept *before* each render
   and gathers feedback on the rendered image *after* each render.
2. The §§ 6A.2 design philosophy rules, verbatim, with examples of
   on-tone and off-tone replies. Special emphasis on:
   - **Rule #7 (verbatim concept handoff).** The model must
     finalize the English concept wording before it asks for
     confirmation, embed that exact English text inside its
     summary `reply` (typically as a quoted block), and emit the
     same string in `concept_candidate`. On `concept_confirmed`
     the `concept_candidate` field must be byte-for-byte
     identical to the prior turn's value — no last-second edits.
   - **Rule #8 (user-driven feedback).** The model is reminded
     that it cannot see the rendered image in this mode; it
     collects detailed visual feedback from the user instead of
     proposing new concepts. The probing-for-key-elements
     pattern is illustrated with examples.
   - **Rule #9 (no feedback summarization).** Examples make clear
     that closing the feedback phase is a single short question,
     not a paragraph-long restatement of the user's words.
   - **Rule #10 (drift detection).** Examples show how the model
     phrases the choice between iterating on the agreed concept
     vs. designing a fresh one.
   - **Rule #11 (polite refusal).** Examples of declining
     technically out-of-envelope and ethically out-of-bounds
     requests while staying warm and offering alternatives.
   - **Rule #12 (cumulative prompt-engineering notes).** The
     prompt instructs Agent 6 on the *notes discipline*:
     - The memo is **English-only**, regardless of the run's
       `source_language` (it is consumed by Agent 1 / Agent 7,
       which operate in English).
     - The memo captures **renderer weaknesses and prompt-level
       countermeasures**, NOT user preferences, NOT aesthetic
       taste, NOT concept-level edits. Examples of good notes:
       "the robot keeps rendering as mist or ghostly figure;
       needs explicit `mecha, metallic plating, glowing eyes,
       hard edges` in positive and `ghost, mist, ethereal,
       humanoid` in negative"; "the cat entity drifts to
       background when not anchored; force `on her shoulder,
       close to face` positional tags". Examples of bad notes
       (must NOT be written): "user wants more emotion in the
       face" (concept-level), "user prefers warmer colors"
       (preference), "we agreed the setting is a forest"
       (concept).
     - The memo is updated via the optional
       `prompting_notes_update` output field (§ 7.1 Call 6).
       When emitted, it **fully replaces** the previous notes —
       Agent 6 is responsible for folding still-relevant prior
       lessons into the new value. Omitting the field (or
       emitting `null`) leaves the prior notes untouched.
     - Agent 6 should consider updating the notes on any turn
       where the latest exchange yielded a useful prompt-level
       lesson — typically (but not only) during
       `gathering_feedback`, `awaiting_feedback_confirmation`,
       and `feedback_confirmed`. Updates may also be emitted on
       `restart_concept` turns when the just-discarded concept
       revealed transferable renderer blind spots.
     - The memo is never surfaced to the user; Agent 6 must not
       reference it in `reply` prose.
3. The §§ 6A.5 feasibility envelope, verbatim, plus examples of
   how to reframe common infeasible requests ("two characters
   hugging" → "our hero hugging the cat", etc.).
4. The phase machine in § 6A.4: which `phase` values are valid in
   each sub-phase (concept-design vs feedback-gathering), the
   server-side guard rules (orphan `concept_confirmed`, orphan
   `feedback_confirmed`, mistimed `accepted`, mistimed
   `concept_confirmed` in the feedback sub-phase, etc.). The
   prompt receives the **current sub-phase** as part of the input
   payload (§ 7.1 Call 6) so the model knows which subset of
   phases is legal on the upcoming turn.
5. The output schema (see § 7.1 Call 6 below).
6. The persona-fragment shared with Agent 0a / 0b / 4 (copy-pasted
   into the file), so the voice stays consistent across the
   chat → story → manual fallback arc.

The prompt also embeds the active-language welcome / review /
budget-exhausted strings (§ 6A.7) as authoring context — so the
model's `reply` prose can flow naturally into and out of them
without the user feeling a tonal seam.

#### 6A.8.2 `manual_revise_prompts.md` (Agent 7)

A new file `backend/app/agents/manual_revise_prompts.md` joins the
existing prompt files. Structure:

1. Role statement ("You are Agent 7, the prompt-revision specialist
   for the collaboration mode …"). The agent is told it lives
   *outside* the chat — it never speaks to the user and never sees
   the chat transcript. It receives a single JSON payload with the
   inputs in § 7.1 Call 7 and emits a single JSON object with the
   revised positive/negative prompts.
2. The agent's four (and only four) information sources for
   revision decisions:
   1. The user feedback blob (`user_feedback` input) — the verbatim
      post-image user messages, in the user's source language.
   2. The cumulative prompt-engineering memo
      (`prompting_notes` input) — English-only, curated by Agent 6
      across the manual session (§ 6A.2 rule #12, § 7.1 Call 6).
      When present, the prompt treats this memo as **authoritative
      prompt-level guidance** on this illustration's known
      renderer blind spots — it accumulates lessons from every
      prior attempt in the manual session, including concepts
      that were later discarded via `restart_concept`. When the
      memo conflicts with a fresh user-feedback turn the memo
      wins on prompt-level mechanics (tag choices, negative-tag
      placement) and the user feedback wins on what to depict
      this attempt; both must coexist in the revised prompt.
      When the memo is NULL, Agent 7 falls back to user feedback
      alone, exactly as today.
   3. Its own Danbooru-tag / Illustrious-XL / MHA-LoRA expertise
      (§ 7.3.1, § 7.3.6, § 7.3.10) — copy-pasted into the file the
      same way Agent 3 (`revise_prompts.md`) carries it.
   4. The shared cross-agent constraints — § 6A.5 feasibility
      envelope and the § 7.3.6 negative-prompt baseline. The
      prompt is explicit that **Agent 7 cannot be used to bypass
      those constraints**: if the user's feedback nudges
      out-of-envelope, Agent 7 silently keeps the prompts within
      envelope.
3. Hard rules carried over from Agent 3 (`revise_prompts.md`):
   the Danbooru tag discipline, the unchanged-workflow rule
   (Agent 7 does not toggle `single-lora` ↔ `no-lora`), the
   character LoRA trigger tags from `character_config.json`, etc.
4. The output schema (see § 7.1 Call 7 below).
5. The reminder that the only output is a single JSON object —
   no Markdown fences, no prefatory text, no commentary outside
   the JSON.

### 6A.9 Manual regeneration (user-initiated)

Once an illustration reaches `COMPLETED` the user may still be unhappy
with the result and want to redo just that one image without
re-running the whole pipeline. A kebab menu (⋮) in the
`IllustrationCard` header exposes a single action — **Regenerate
image** — that drops the user back into the § 6A manual chat for that
illustration only.

**Backend endpoint.** `POST /api/illustrations/{id}/regenerate`
(returns `ManualSessionResponse`, same shape as the other § 6A
endpoints). Implemented by `ManualService.start_regeneration`:

| Field on the illustration | Effect of regenerate |
| --- | --- |
| `state` | `COMPLETED → MANUAL_CHATTING`. |
| `image_path` / `image_url` | **Preserved** — used as the fallback the user can revert to via the chat's X button. |
| `manual_attempts` | **Not reset.** The 5-attempt budget is cumulative across regenerations; if the user has already used 3 manual attempts on a prior pass, they have 2 left. |

On the manual session row:

| Column | Effect |
| --- | --- |
| `sub_phase` | Reset to `concept_design`. |
| `last_concept_candidate` | Cleared. |
| `last_agreed_concept` | Cleared. |
| `last_manual_image_path` | Cleared. |
| `prompting_notes` | **Preserved** — the cumulative English memo carries over. |

Existing `manual_messages` rows are **also preserved**. A new
assistant bubble (`MANUAL_WELCOME_REGENERATE`, see § 6A.7) is appended
to the transcript so Agent 6 sees both the prior conversation and the
fresh prompt for the next iteration.

The owning `runs` row is **not** touched. The run may already be
`COMPLETED` or `FAILED`; `_maybe_finalize_run` is a no-op on terminal
runs, so the manual loop runs independently.

**Preconditions** (raise `409` otherwise):
- `illustration.state == COMPLETED` — else `INVALID_STATE`.
- `illustration.manual_attempts < 5` — else `BUDGET_EXHAUSTED`.
- The owning run is not `CANCELLED` — else `RUN_CANCELLED`.

**SSE events emitted** (in this order):
1. `illustration_state` with `state=MANUAL_CHATTING`.
2. `illustration_manual_started` with the welcome message payload
   and `reason: "regeneration"` (the previously implicit `"auto"`
   reason is the default; this field is forward-looking and the
   current frontend ignores it).

**Frontend UX.**
- The kebab menu is visible whenever the card can be regenerated
  (`COMPLETED` and budget left) OR has an active session that may be
  hidden/shown (`MANUAL_*` or `FAILED` with budget left).
- The single menu item "Regenerate image" is disabled (greyed out)
  when the cumulative budget is exhausted.
- The chat panel header gains an X close button. Clicking it hides
  the chat and flips the card back to the previous image (if any) or
  the failure placeholder. The toggle lives in client memory only.
- **Default view-mode rule:** whenever `illustration.image_url` is
  set, the card defaults to showing the image — even while
  `state ∈ MANUAL_*`. This makes regen in-progress refresh-safe: a
  page refresh during a regen returns to the previous image until
  the user re-opens the chat via the kebab. Once the new image is
  accepted, `illustration_completed` automatically hides the chat
  toggle so the card flips to the fresh image.
- Clicking "Regenerate image" while the card is already in a
  `MANUAL_*` state does **not** POST again — it just reveals the
  in-flight chat panel.

### 6A.10 Interactive image cards and explicit acceptance

When a § 6A manual render completes, the chat displays the produced
image as an **interactive `ManualImageCard`** (a mini illustration
card) rather than a raw `<img>` followed by a canned "describe what
you see" assistant bubble. The card has three sections:

- **Header.** Left: attempt counter (`Pokus N/5`). Right: two hover/
  focus/click dropdown icons — one for the **concept** used to render
  this attempt, one for the **positive + negative prompts** Agent 1
  (or Agent 7) emitted. Icons are disabled when the row's per-attempt
  provenance is `NULL` (legacy rows from before this feature).
- **Image.** Click-through anchor opening the full-size image, same
  alt text as before.
- **Footer (two variants).**
  - **Variant 1 — *choose*:** rendered only when this image is the
    **latest** attempt AND no non-image message has been appended
    after it AND the 5-attempt budget is not exhausted AND the
    illustration is still in a `MANUAL_*` state. Shows two ghost
    buttons: **Accept** (deterministic promotion) and **Iterate**
    (appends the iterate-prompt bubble and unlocks input).
  - **Variant 2 — *use*:** rendered for older attempts (any image
    with non-image messages after it) and for the latest attempt
    when the budget is exhausted. Shows a single **Use** ghost
    button that promotes that specific attempt's image to canonical.
  - No footer is rendered when the illustration is already
    `COMPLETED` (defensive — the chat is hidden in that state).

**Input lock UX.** While variant 1 is active for the latest image,
the text input and Send button are disabled and a small italic hint
("Choose Accept or Iterate above to continue.") sits above the
input. Clicking **Iterate** appends an assistant bubble — the
**MANUAL_ITERATE_PROMPT** localized text (see § 6A.7 below) — which
breaks variant 1 (a non-image message now follows the latest image)
and unlocks the input. Variant 1 also unlocks if the user otherwise
types feedback that gets posted through the regular send path.

**Removed:** `_dispatch_render` no longer auto-emits the
**MANUAL_REVIEW_PROMPT** ("I can't see — you're my eyes — tell me
what to change…") after every render. That nudge was redundant with
the card footer and noisy when users already knew the next step.
Older transcripts retain the historical review bubbles as inert
content; they remain rendered exactly like any other assistant row.

**New per-attempt persistence.** `manual_messages` gains three
nullable columns populated only for `role='image'` rows:

| Column | Source | Notes |
| --- | --- | --- |
| `concept_used` | `last_agreed_concept` from the manual session at render time. | The concept Agent 6 / Agent 7 just rendered against. |
| `positive_prompt` | `positive` field of `current_prompts_json` (Agent 1 or Agent 7). | Identical to what ComfyUI received. |
| `negative_prompt` | `negative` field of `current_prompts_json`. | Identical to what ComfyUI received. |

Legacy rows from before the migration keep `NULL` for all three.
The frontend renders the popover icons in a disabled state when any
field it needs is `NULL`. The `manual_image_rendered` SSE payload
carries the same three fields and **no longer carries
`review_message`** (since no canned bubble is emitted).

**New endpoints.**

`POST /api/illustrations/{id}/accept` — body
`{ "manual_attempt_index": K }` (≥ 1). Promotes attempt K's
deterministic temp image (`runs/{run_id}/manual_{scene}_{K}.png`) to
the canonical `runs/{run_id}/scene_{scene}.png`. This **bypasses
Agent 6 entirely** — deterministic server-side promotion, no Claude
call. Implemented by `ManualService.accept_attempt`:

- Preconditions (raise 4xx via `ManualServiceError`):
  - `state ∈ {MANUAL_CHATTING, MANUAL_GENERATING_PROMPTS, MANUAL_RENDERING, FAILED}` → else `INVALID_STATE` (409). `FAILED` is allowed for **post-exhaustion recovery** (see below).
  - Run not cancelled → else `RUN_CANCELLED` (409).
  - An image-row for `(illustration_id, manual_attempt_index=K)`
    exists → else `ATTEMPT_NOT_FOUND` (404).
  - The deterministic source file exists on disk → else
    `ATTEMPT_FILE_MISSING` (410).
- Effects: copy temp → canonical, set `state=COMPLETED`,
  `image_path=canonical`, clear any prior `error_message` (FAILED
  recovery), and update `current_concept` to the accepted row's
  `concept_used` (so the canonical IllustrationCard's ConceptPopover
  shows the right text). Emit the same SSE trio as the existing
  Agent-6 acceptance path: `illustration_state`,
  `illustration_completed`, `illustration_manual_ended` with
  `outcome="completed"`. Then `_maybe_finalize_run`.

**Post-exhaustion recovery.** Once the user spends the 5-attempt
manual budget without ever clicking Accept, the illustration
transitions to `FAILED` (via `_exhaust`, § 6A.7) and the chat is
hidden by default behind the failed placeholder. The frontend
nonetheless keeps the kebab menu's **Show chat** option enabled
whenever a manual session exists and the illustration is not
`COMPLETED` — explicitly including the `FAILED`-exhausted case.
Reopening the chat reveals the full transcript with every historical
`ManualImageCard` showing footer variant *use*; clicking **Use** on
any prior attempt calls `POST /accept`, which (a) accepts the
`FAILED` state precondition, (b) promotes the chosen attempt's
deterministic temp image to canonical, and (c) clears
`error_message`. The illustration ends up in `COMPLETED` with the
chosen image. (See § 9.1 Screen B — *Recovery after manual
exhaustion*.)

The legacy Agent-6 acceptance path (`PHASE_ACCEPTED`) is preserved
as a thin wrapper that resolves "latest attempt" and calls
`accept_attempt(K)` — users who type "yes, accept" still work.

`POST /api/illustrations/{id}/manual/iterate` — no body. Appends one
assistant bubble with the **MANUAL_ITERATE_PROMPT** localized text
to the transcript. Implemented by
`ManualService.append_iterate_prompt`. Idempotent: if the latest
manual message is already the iterate-prompt bubble, returns the
current state without re-appending. State machine is unaffected
(sub_phase remains `feedback_gathering`).

**MANUAL_ITERATE_PROMPT (replaces MANUAL_REVIEW_PROMPT).** Localized
constant in `backend/app/constants.py`:

- **sk:** "Popíš tak detailne ako vieš, čo je s obrázkom zle a v čom
  sa odlišuje od konceptu, na ktorom sme sa dohodli. Ja tento
  obrázok nevidím — si moje oči. Čím lepší bude tvoj popis, tým
  väčšia bude pravdepodobnosť, že sa spoločnými silami dopracujeme
  k jeho požadovanej podobe."
- **cs:** Czech translation of the same meaning.
- **en:** "Describe in as much detail as you can what's wrong with
  the image and how it differs from the concept we agreed on. I
  can't see this image — you are my eyes. The better your
  description, the higher the chance that we'll work our way
  together to the version you want."

**Agent 6 prompt addendum (defense-in-depth).** The
`backend/app/agents/manual_concept.md` system prompt notes that
between an `[image rendered: K]` turn and the next user turn there
is no longer a canned "describe what's wrong" assistant bubble; if
the user clicks the Accept button in the UI, the server promotes
without invoking Agent 6 at all (and may show a `[user accepted
attempt K]` marker in future transcripts — Agent 6 must treat that
as terminal and emit no further reply).

---

## 7. External Service Contracts

### 7.1 Anthropic Messages API (9 distinct calls)

All calls use `claude-sonnet-4-6`. Each agent's full system prompt lives
in a Markdown file under `backend/app/agents/` and is loaded at startup
by `services/claude.py` (see § 7.4). The Pydantic schemas below are the
binding wire contracts; the prose in each agent's `.md` file must produce
output that validates against the corresponding schema.

Strict JSON-only output is enforced for **Calls 0b through 5 and Call 7**
via the system prompt; **Call 0a (chat) returns a JSON envelope whose
`reply` field is free-form prose in the active user language** — see
Call 0a below. **Call 6 (manual_concept)** follows the same
envelope-with-prose pattern as Call 0a — see § 7.1 Call 6 and § 6A.
**Call 7 (manual_revise_prompts)** is strict-JSON like Agents 1 and 3:
it emits only a `positive`/`negative` prompt pair and never produces
user-facing prose. Every JSON response is validated with Pydantic, with up to
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
    "non_human_entities": [
      { "label": "string (concrete English label of one allowed non-human entity — a non-human character or a story-important object)",
        "role_in_story": "string (free-form English phrase describing the entity's role: e.g. \"ally\", \"antagonist\", \"recurring presence\", \"sentimental keepsake\")" }
    ],
    "main_character_role": "male" | "female",
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
6. **Non-human entity pool — no hard cap on count.** Each entry is a
   non-human character (animal, creature, mechanical being, etc.) **or
   a story-important object** (a pocket watch, a locked diary, a
   talisman). Agent 0a must not push the user toward adding entities
   — it only captures them if the user volunteers the idea or
   explicitly agrees when asked. Pool size is not capped in the schema
   (Agent 0b later assigns importance and is bound by the per-importance
   cardinality rules — § 7.1 Call 0b rule #14).
7. **Entity shape.** Each entry has a non-empty, visualizable English
   `label` and a non-empty, free-form English `role_in_story` hint.
   Agent 0a nudges the user toward concrete labels
   ("a small black cat", "the gold pocket watch") rather than vague
   ones ("an animal", "a thing") before moving to
   `awaiting_confirmation`. The `role_in_story` field is *free-form
   prose* the agent will later read to pick the entity's importance
   (e.g. "ally throughout", "antagonist who appears once", "a sentimental
   keepsake the boy carries to school").
8. **Non-humanoid only for animate entities.** A non-human *animate*
   entity (kind that becomes a `non_human_character` in Agent 0b's
   register) must have a body plan fundamentally different from
   humans — quadrupeds, winged creatures, serpents, mechanical
   entities without human form factor, etc. Anthropomorphic / humanoid
   creatures (cat-girls, elf-like beings, humanoid androids with human
   faces, etc.) are forbidden and treated as humans for scope purposes.
   Objects are exempt from this rule. Agent 0a refuses humanoid
   non-human characters and stays in `gathering` until the user
   proposes a non-humanoid one, switches to an object, or drops the
   idea.
9. **No non-human entities without a human main character.**
   Entities exist *for* the human cast; the prerequisite from rule #2
   (at least one of `male` or `female`) still applies before any
   entity can be accepted.
10. **Main character role.** `collected_brief.main_character_role` is
    REQUIRED and must reference one of the cast roles. `mother` is
    forbidden as main (cast rule #1 already prevents a mother-only
    brief). Agent 0a infers it from the conversation; if the user has
    given a male + a female lead without expressing a preference, the
    agent must ask before moving to `awaiting_confirmation`.

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
      "contains_entity_label": "string (label of one entry in narrative_entities, scene-locked once placed)" | null
    }
  ],
  "environments": [
    {
      "label": "string (short locale-specific name, e.g. \"obývačka\", \"školská chodba\", \"auto\")",
      "kind": "indoor" | "outdoor" | "dual",
      "aspect": "single" | "inside" | "outside"
    }
  ],
  "narrative_entities": [
    {
      "label": "string (English label, unique within the register)",
      "kind": "non_human_character" | "object",
      "importance": "primary" | "secondary" | "supporting",
      "reserved_for_scene_index": 0 | 1 | 2 | 3 | 4 | null
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
   illustration whose visible subject is a narrative entity alone, or —
   very rarely — a pure environment beat with no characters at all
   (see rules #12 / #13 below).
6. **Specificity of expression / gesture / action** (§ 7.3.4) applies
   to every illustration that includes either a human character
   (`character_role != null`) or a non-null `contains_entity_label`.
   Each such `concept` must explicitly mention at least one concrete
   facial expression, gesture/posture, or action (for animate
   subjects), or a concrete physical state / depictable role of the
   object (for object beats). For the rare pure-environment beat
   (rule #13), the concept must instead name a concrete, depictable
   moment in the *environment* (lighting, weather, a specific object
   in frame).
7. **Story-design discipline** (§ 7.3.9) — the story must be deliberately
   built around scenes that are illustratable under the MVP's hard
   technical constraints (single human character optionally accompanied
   by one non-human narrative entity, simple ComfyUI workflow with no
   regional prompting or inpainting, locked per-scene environment
   chosen from the run's `environments` register).
8. **Entity register fidelity.** If `contains_entity_label` is set on
   an illustration, its value MUST match an entry in the run's
   `narrative_entities` register (whitespace-tolerant,
   case-insensitive). The server re-checks this on receipt and
   re-prompts on failure. Agent 0b must not invent new entities at
   the illustration level — every entity that appears in any scene
   is also present in `narrative_entities`.
9. **Entity cadence + per-importance cardinality.** Agent 0b decides
   which scenes feature an entity. The hard caps (re-checked by the
   distribution validator, § 7.1 rule #14) are:
   - At most **one** entity with `importance="primary"`
     (`kind="non_human_character"`); when present it appears in
     exactly its `reserved_for_scene_index` and nowhere else.
   - At most **one** entity with `importance="secondary"`
     (`kind="non_human_character"`); when present it appears in
     exactly its `reserved_for_scene_index` *with* a human in the
     same scene (it may never appear alone).
   - Any number of `importance="supporting"` entities (NH-characters
     and objects). Each may appear in at most one scene; supporting
     entities may be reserved to a slot at Agent 0b time **or** left
     floating (`reserved_for_scene_index=null`) to be claimed later
     by Agent 4 / 4b.

   When the brief's `non_human_entities` pool is empty,
   `narrative_entities` MAY also be empty and every illustration's
   `contains_entity_label` MUST be `null`.
10. **`contains_entity_label` is scene-locked.** Once an entity appears
    in scene `N`, it is permanently locked to scene `N`. If a later
    agent (Agent 4 / 4b) drops the entity, the slot stays
    *ghost-reserved* — the same entity may not migrate to a different
    slot.
11. **No entity in scenes requiring hand-object precision.** This
    complements § 7.3.9 principle 4. If a scene's `concept` pushes the
    hand-object precision envelope (e.g., character pouring water,
    picking up a coin, holding something delicate), Agent 0b must not
    additionally place an entity that compounds the difficulty.
12. **Per-illustration cast triplet (workflow-driving).** Every
    illustration falls into exactly one of three cast shapes:
    - **Single human + optional narrative entity** — `character_role`
      is one of `male` / `female` / `mother`; `contains_entity_label`
      is null or set. This is the dominant shape; the
      `single-lora.json` workflow renders it (§ 7.2.1).
    - **Entity alone** — `character_role` is `null`;
      `contains_entity_label` is set. Rendered by `no-lora.json`.
      Permitted only when the entity is `importance="primary"`
      (NH-character) or a floating/reserved supporting entity; a
      `secondary` NH-character may NEVER appear alone (rule #9).
      Used for beats where the entity's *own* presence (the cat
      asleep on the bed; the dragon perched on a rooftop watching;
      the locked diary lying open on the desk) carries the moment.
    - **No characters / no entity** — `character_role` is `null`;
      `contains_entity_label` is `null`. Rendered by `no-lora.json`.
      **Rare** — reserved for story-essential environment beats
      (the empty classroom after she left; the storm rolling in
      over the harbor). Multiple character-less illustrations in
      the same run are discouraged.
13. **Workflow distribution discipline.** Agent 0b implicitly
    determines the workflow each illustration will use via the cast
    shape it returns (rule #12). It must design the story so that the
    overall mix is sensible: most illustrations should feature a
    human character. A run where 4-out-of-5 illustrations are
    character-less is rejected at validation time as poorly aligned
    with the app's purpose. The server caps `no-human` illustrations
    (i.e. `character_role == null`) at **≤ 1 out of 5** and re-prompts
    on violation.
14. **Cross-illustration distribution validator.** Server runs
    `validate_illustration_distribution(brief, illustrations,
    narrative_entities)` (§ schemas/claude.py) which enforces, beyond
    the rules above: every cast role appears at least once;
    `main_character_role` appears at least twice; no side role exceeds
    main; per-entity quotas; entity-side scene lock. Failures re-prompt
    up to `CLAUDE_JSON_RETRY` times.
15. **Environments register.** `environments` MUST contain exactly 5
    entries. Position `N` in the array is the locked environment for
    `scene_index=N`. Indoor and outdoor entries occupy exactly one
    slot (`aspect="single"`). Dual entries (cars, planes, ships,
    wooden cabins) may occupy two slots and only if their aspects
    are one `inside` and one `outside`. Environment labels live in
    a disjoint namespace from `narrative_entities` labels: if a thing
    can host a human inside it during the story, it is an
    `Environment`; otherwise it is a `NarrativeEntity` with
    `kind="object"`. Agent 0b authors all five environments at story-
    build time; only Agent 4b may later swap one (§ 7.1 Call 4b).

Unlike the previous spec, Agent 0b **does not** have a "no suitable
scenes" escape hatch. The brief has already been negotiated and confirmed
in Call 0a; the storyteller's job is to deliver. Output that violates the
hard rules above is treated as a Claude failure (`STORY_BUILD_FAILED`).

#### Call 1 — `generate_prompts`

**Input:** `current_concept` (English — single source of truth),
`style_guide`, `character_role` (`male` / `female` / `mother` / `null` —
when `null`, the agent treats the illustration as character-less; see
rule below), the slot's locked `environment`
(`{ label, kind, aspect }`), the optional `contains_entity`
(`NarrativeEntity | null` — the full register entry for the entity
present in this scene, including `label`, `kind`, `importance`,
`reserved_for_scene_index`), and the optional `prompting_notes: string
| null` — an English-only cumulative prompt-engineering memo from the
collaboration mode (§ 6A.2 rule #12). When `contains_entity` is
non-null the agent must incorporate it per § 7.3.10 (entity prompting
guidance) and apply the conditional adjustments to the negative
baseline described in § 7.3.6.

`prompting_notes` semantics:

- In the **auto pipeline** (§ 6 loops, Step 0 → Step 4 dispatches),
  `prompting_notes` is always `null` — Agent 1 behaves exactly as it
  did before this field existed.
- In the **collaboration mode** (§ 6A.4 step 3.3, `concept_confirmed`
  dispatch), the server passes the current
  `manual_illustration_sessions.prompting_notes` value (null until
  Agent 6 emits its first update). When non-null, Agent 1 treats the
  memo as **authoritative prompt-level guidance** on this
  illustration's known renderer blind spots (e.g. tags that have
  worked or failed on this character / environment in prior manual
  attempts, including across `restart_concept` boundaries) and
  reflects those lessons in `positive` / `negative` without restating
  them. The memo does not change the concept — it only changes how
  the same concept is encoded into prompts.

The `prompting_notes` input is optional in both schema and runtime —
omitting it or passing `null` is identical from Agent 1's
perspective.

**Output schema:**
```json
{
  "positive": "string",
  "negative": "string",
  "workflow": "single-lora" | "no-lora"
}
```

The `positive` field is the full per-scene positive prompt (character +
environment + action + expression + narrative entity if any, all expressed
as Danbooru tags — *always in English*, regardless of the run's source
language). The `negative` field is the full per-scene negative prompt.
Style-level tags are NOT included here — they live in `style_guide` and
are composed in by the workflow itself (see § 7.2). See § 7.3.4 and
§ 7.3.10 for the content requirements that this prompt must satisfy.

**`workflow` selection rule (hard-enforced):**

- Return `"single-lora"` **iff** `character_role` is non-null (i.e. the
  illustration shows exactly one human character — optionally
  accompanied by one narrative entity). The character LoRA wiring is
  taken from `character_config[role]` (§ 7.3.7) and the
  `CHARACTER_LORA` placeholder is filled in by the workflow runner.
- Return `"no-lora"` **iff** `character_role` is `null` (i.e. the
  illustration shows no human — either an entity alone, or no
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
`character_role` (`male` / `female` / `mother` / `null`), the slot's
locked `environment` (`{ label, kind, aspect }`), and the
illustration's `contains_entity` (`NarrativeEntity | null`). The
agent's checklist is entity-aware **and cast-aware** (§ 7.3.5 items
1a + 1b + 1c) and additionally checks that the rendered scene matches
the locked environment (lighting, structure, expected indoor/outdoor
aspect).

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
  "problem": "prompt" | "concept" | "environment",
  "reasoning": "string",
  "suggestion": "string (hint to be passed into the next call)"
}
```

**Routing semantics for `problem`:**

- `"prompt"` — fixable by tag revision in the same concept; routes to
  Agent 3 (`revise_prompts`). Use when the renderer *could* depict
  the concept but the tags missed something (a missing expression,
  wrong colour, lighting tag drift, etc.). Use this verdict even when
  the renderer "missed the environment" but the environment is still
  feasible — that is steerable via tags.
- `"concept"` — the concept itself is the blocker but the locked
  environment remains workable; routes to Agent 4 (`rethink_concept`).
  Agent 4 may rewrite the concept and paragraph in the same locked
  environment.
- `"environment"` — the locked environment itself is the renderer
  blocker; concept revision in-place cannot help; routes to Agent 4b
  (`rethink_environment`). Use only when the env is fundamentally at
  odds with the depictable scene (e.g. a "vast underwater cavern"
  that the model consistently fails to render coherently). One-shot
  per branch; if Agent 4b has already fired (`env_rethink_used=True`),
  the orchestrator demotes the verdict to `"concept"`.

#### Call 3 — `revise_prompts`

**Input:** current `prompts`, last `verdict`, `current_concept`
(English), `style_guide`, `character_role` (`male` / `female` /
`mother` / `null`), the slot's locked `environment`, and the
illustration's `contains_entity` (`NarrativeEntity | null`). When
`contains_entity` is non-null the same entity guidance applies as in
Call 1 (§ 7.3.10 + the § 7.3.6 conditional negative adjustments).

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
- `environment` — the slot's **locked** environment (`{ label, kind,
  aspect }`) from `runs.environments_json[scene_index]`. Agent 4 is
  forbidden from changing it; if the locked environment is the
  renderer blocker, the evaluator should have emitted
  `problem="environment"` and the orchestrator should have routed to
  Agent 4b (§ 7.1 Call 4b) instead.
- `current_entity` — the unified narrative entity currently associated
  with this slot (`NarrativeEntity | null`). Includes `label`, `kind`,
  `importance`, and `reserved_for_scene_index`.
- `floating_entities` — every entity in the run's `narrative_entities`
  register whose `reserved_for_scene_index` is `null` (i.e. floating
  supporting entities still up for grabs). Agent 4 may claim one of
  these for this slot by returning its label with
  `entity_action="claim_floating"`.
- `source_language` — `runs.source_language`. Tells Agent 4 which
  language the rewritten paragraph and the localized concept must be
  authored in. The canonical concept is still English (single source
  of truth for Agents 1 / 2 / 3); the paragraph and the
  `concept_localized` go in `source_language`.

**Output schema:**
```json
{
  "workflow": "single-lora" | "no-lora",
  "concept": "string (canonical English concept, meaningfully different from failed_concept)",
  "concept_localized": "string (the same concept in source_language) | null when source_language='en'",
  "paragraph_text": "string (the rewritten paragraph that replaces current_paragraph_text, in source_language)",
  "scene_excerpt": "string (a verbatim substring of paragraph_text — the new excerpt this concept depicts)",
  "character_role": "male" | "female" | "mother" | null,
  "contains_entity_label": "string (label of the entity present in this rewrite)" | null,
  "entity_action": "keep" | "drop" | "claim_floating" | "none",
  "narrative_continuity_check": "string (1–3 sentence English self-audit Agent 4 writes after drafting paragraph_text — see rule #9)"
}
```

`character_role` is **also rewritable** by Agent 4 (it was already in
Call 4's narrative scope but was implicit; making it explicit clarifies
that Agent 4 can switch a scene from human-with-entity to
entity-alone — and vice versa — as long as the resulting cast shape
(Call 0b rule #12) is one of the three permitted triplets, and the
global per-run cap of ≤ 1 character-less illustration (Call 0b
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
   — it does not invent new characters, does not propose changing the
   story title, and does not propose changes to other paragraphs. Its
   scope is exactly: one paragraph, one concept, one excerpt,
   optionally one narrative entity placement.
6. **Environment is immutable.** Agent 4 must place the new scene
   inside the `environment` passed in. Moving the scene to a different
   place (a different room, a different building, outdoors when the
   slot is indoors, etc.) is forbidden. If the locked environment is
   the failure mode, the evaluator emits `problem="environment"` and
   the orchestrator dispatches Agent 4b instead — Agent 4 is never
   asked to swap the environment.
7. **Entity placement via `entity_action`.** Agent 4 must classify
   what it is doing with this slot's narrative entity by setting the
   `entity_action` discriminator:
   - `"keep"` — the entity reserved for this slot stays in the new
     scene. `contains_entity_label` is non-null and matches
     `current_entity.label`.
   - `"drop"` — the entity reserved for this slot is intentionally
     removed from the new scene. `contains_entity_label` MUST be
     `null`. The slot stays *ghost-reserved* — the entity may never
     appear in any other slot (entity-side scene lock).
   - `"claim_floating"` — a floating supporting entity (one from
     `floating_entities`, i.e. `reserved_for_scene_index=null`) is
     being claimed for this slot. `contains_entity_label` is non-null
     and matches one of the floating entries; on receipt, the server
     permanently sets that entity's `reserved_for_scene_index` to
     this slot.
   - `"none"` — there is no entity at play (no reservation existed
     and no claim is being made). `contains_entity_label` MUST be
     `null`.

   The server enforces the `entity_action` ↔ `contains_entity_label`
   coherence; mismatches re-prompt up to `CLAUDE_JSON_RETRY` times.
8. **Register fidelity (same as Agent 0b).** Any non-null
   `contains_entity_label` must reference an entry in the run's saved
   `narrative_entities` register (whitespace-tolerant, case-insensitive
   substring or exact match). The persisted register is read from
   `runs.narrative_entities_json`. Including a label that belongs to
   an entity reserved for a DIFFERENT slot is rejected (entity-side
   scene lock).
9. **Narrative continuity self-audit.** Agent 4 must write a 1–3
   sentence English `narrative_continuity_check` *after* drafting
   `paragraph_text`, stating in its own words how the rewrite
   preserves the transition into and out of this paragraph. Empty
   strings or trailing whitespace-only strings are rejected. This is
   the prompt's chief defense against subtle narrative drift on
   third-attempt rewrites.

If the validated response violates any rule above, the server treats
that as a Claude failure and re-prompts up to `CLAUDE_JSON_RETRY` (= 2)
times. After that the branch ends as if Agent 4 returned nothing useful
— concept_attempt exhaustion behavior (§ 6 loop semantics) takes over.

The orchestrator persists `contains_entity_label` onto the illustration
row at the same time it overwrites the paragraph text, scene excerpt,
and current concept. When the new label differs from the previous
(including any change to/from null), the orchestrator additionally
emits an `illustration_entity_updated` SSE event (§ 8.4) carrying both
the new label and the **full entity record** from the (possibly
mutated) register. For `entity_action="claim_floating"`, the
orchestrator also updates `runs.narrative_entities_json` to set the
claimed entity's `reserved_for_scene_index` to this slot. No event is
emitted when the label is unchanged.

Agent 4's `concept_localized` and `paragraph_text` together replace
the corresponding source-language texts and **invalidate** any
existing translations for the same paragraph and concept in
`story_block_translations` / `illustration_concept_translations`
(their `source_hash` no longer matches). The orchestrator does not
proactively call Agent 5; staleness is resolved lazily on the next
read in a non-source language (§ 5.5, § 8.9).

#### Call 4b — `rethink_environment` (Agent 4b, "the location scout")

Agent 4b is the **only** agent allowed to swap a slot's locked
environment. It exists for the narrow case where the renderer can
demonstrably not depict the locked environment for this scene — not
because the prompt is wrong, not because the concept is wrong, but
because the environment itself fights the simple ComfyUI workflow.
The evaluator's `problem="environment"` verdict (§ 7.1 Call 2) is
the only way Agent 4b is dispatched.

Loop integration (§ 6 loop semantics):

- One-shot per branch — gated by `env_rethink_used`. After Agent 4b
  fires once, any subsequent `problem="environment"` verdict is
  demoted to `problem="concept"` and routed back to Agent 4.
- On success, Agent 4b extends the branch's outer concept-attempt
  budget by **+1** (i.e. 4 attempts instead of 3), so the swap
  doesn't burn the slot it just rewrote.
- `skip_concept_rethink_once` is set so the *next* outer iteration
  bypasses Agent 4 (Agent 4b has already produced a fresh concept +
  paragraph + environment in this same call).

**Input (to Claude):** identical to Agent 4 except:

- `verdict.problem == "environment"` is implicit.
- A new field `dual_aspect_in_use` — when this slot's old environment
  was a dual entry (`kind="dual"`) and its sibling slot uses the other
  aspect, Agent 4b is told which aspect is taken so it can pick a
  non-conflicting replacement. Dual-rule violations are re-prompted
  server-side.

**Output schema:** mirrors Agent 4 plus a fresh `environment`:

```json
{
  "workflow": "single-lora" | "no-lora",
  "concept": "string",
  "concept_localized": "string | null when source_language='en'",
  "paragraph_text": "string",
  "scene_excerpt": "string (verbatim substring of paragraph_text)",
  "character_role": "male" | "female" | "mother" | null,
  "contains_entity_label": "string | null",
  "entity_action": "keep" | "drop" | "claim_floating" | "none",
  "environment": {
    "label": "string",
    "kind": "indoor" | "outdoor" | "dual",
    "aspect": "single" | "inside" | "outside"
  },
  "narrative_continuity_check": "string (1–3 sentence English self-audit)"
}
```

Hard rules enforced by the prompt and re-checked server-side:

1. **Substantively different environment.** The new `environment.label`
   must be meaningfully distinct from the previous one (case-folded
   substring match against the old label is rejected). Agent 4b must
   not just rename the same place.
2. **Run-level disjointness preserved.** After the swap, the run's
   five-slot `environments` register must still satisfy: each label
   appears in at most 2 slots; labels that appear twice are
   `kind="dual"` with one `inside` and one `outside`; labels that
   appear once are either `single`, `inside`, or `outside`. Conflicts
   re-prompt up to `CLAUDE_JSON_RETRY` times.
3. **Entity contract** — identical to Agent 4 rules #7 and #8
   (`entity_action` ↔ `contains_entity_label` coherence; register
   fidelity; entity-side scene lock).
4. **Narrative continuity** — identical to Agent 4 rule #9
   (`narrative_continuity_check` required).
5. **All Agent 4 paragraph rules still apply** — excerpt validity,
   functional equivalence, story-design discipline, out-of-band side
   effects.

Server-side persistence after a valid Agent 4b response:

- `runs.environments_json[scene_index]` is overwritten with the new
  `environment`.
- `illustrations.environment_label` and `illustrations.environment_aspect`
  are overwritten on the same row.
- `runs.story_blocks_json[paragraph_index].text` is overwritten.
- `illustrations.scene_excerpt`, `current_concept`, `character_role`,
  and `contains_entity_label` are overwritten on the same row.
- Three SSE events are emitted (in this order):
  `illustration_environment_updated{environment}`, `paragraph_updated`,
  and (when the entity label changed) `illustration_entity_updated`.

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

#### Call 6 — `manual_concept` (Agent 6, "the co-illustrator")

**Purpose:** Drive the semi-automatic manual chat flow described in
§ 6A. The agent talks with the user in the run's `source_language`
and operates in one of two sub-phases (§ 6A.4):

1. **Concept-design sub-phase** — collaboratively design a feasible
   illustration concept that fits the envelope in § 6A.5 and finalize
   its **verbatim English wording** *before* asking for confirmation
   (§ 6A.2 rule #7).
2. **Feedback-gathering sub-phase** — after a render, elicit
   detailed visual feedback from the user (Agent 6 itself does not
   see the rendered image); detect drift away from the agreed
   concept; close the phase with a single short confirmation
   question (§ 6A.2 rules #8–#10).

**Input (to Claude):** a JSON user turn containing
- `sub_phase` — `"concept_design"` or `"feedback_gathering"`. The
  server reads it from `manual_illustration_sessions.sub_phase`
  (§ 6A.6) and includes it in every call. The prompt's phase
  machine (§ 6A.8.1 step 4) tells the model which `phase` enum
  subset is legal for the upcoming reply.
- `style_guide` — the run's existing `style_guide` (§ 5 `runs`).
- `character_role` — the illustration's existing role (drives the
  per-role LoRA / character vocabulary the model may rely on).
- `narrative_entities_register` — the same run-level register used
  by Agent 4 (§ 7.1 Call 4); Agent 6 may keep / drop / substitute
  entities (non-human characters or objects) but never invent new
  ones. Entity-side scene locks (§ 7.1 Call 0b rule #10) still apply:
  an entity already locked to a *different* slot may not appear in
  this slot.
- `initial_concept` — the illustration's original concept text
  (English source). Agent 6 may use it as a starting point or
  deliberately depart from it; the user is in charge.
- `last_failure_verdict` — the most recent Agent 2 verdict from
  the auto loop, if any. Helps Agent 6 understand what failed and
  steer away from the same failure mode (without revealing the
  reasoning to the user — see § 6A.2 rule #5).
- `manual_attempts_consumed` — integer, `0..MAX_MANUAL_ATTEMPTS`.
- `manual_attempts_remaining` — convenience field; the prompt uses
  this to pace assertiveness (more remaining → more room to
  iterate; fewer remaining → more decisive recap and confirmation
  ask).
- `last_concept_candidate` — the most recent `concept_candidate`
  Agent 6 itself proposed with `phase=awaiting_concept_confirmation`,
  if any. Used by the model to recognize a user confirmation
  referring to it; used by the server to assert the verbatim
  invariant at `concept_confirmed`.
- `last_agreed_concept` — the verbatim English concept the user
  most recently confirmed (i.e. the one the most recent image was
  rendered from). Non-null only in the `feedback_gathering`
  sub-phase. The model uses it to identify the load-bearing
  concept elements it should probe the user about.
- `prompting_notes` — the current value of
  `manual_illustration_sessions.prompting_notes` (English-only
  cumulative prompt-engineering memo, § 6A.2 rule #12). NULL on
  the first Agent 6 call of the session and on every subsequent
  call until Agent 6 itself populates it via
  `prompting_notes_update`. The server simply round-trips
  whatever value is currently stored — it does not edit, merge,
  or summarize. Persists across `phase=restart_concept`.

And the prior `manual_messages` transcript (excluding `image`-role
rows, which the model receives as a sentinel string
`"[image rendered: attempt K]"` in the assistant slot — Claude
cannot consume images here, and the actual image is for the user,
not the model).

**Output schema:**
```json
{
  "reply": "string (assistant chat turn, free-form prose, in source_language; empty string allowed only on phase='accepted', mirroring Agent 0a)",
  "phase":
      "gathering"
    | "awaiting_concept_confirmation"
    | "concept_confirmed"
    | "gathering_feedback"
    | "awaiting_feedback_confirmation"
    | "feedback_confirmed"
    | "restart_concept"
    | "accepted",
  "concept_candidate": "string (English; verbatim canonical concept the user is being asked to confirm or is confirming) | null",
  "prompting_notes_update": "string (English-only; full replacement of manual_illustration_sessions.prompting_notes) | null"
}
```

The four "structured outputs" the agent can attach to a turn
(per the user-facing design doc) are therefore (a) `concept_candidate`
populated on `awaiting_concept_confirmation` / `concept_confirmed`,
(b) the `feedback_confirmed` flag itself (which tells the server to
slice the post-image user-message transcript and ship it to Agent 7
— Agent 6 does not paraphrase the feedback, per § 6A.2 rule #9),
(c) the `accepted` flag, and (d) the `prompting_notes_update` memo
(§ 6A.2 rule #12). All four are independently optional from turn
to turn; most turns will carry only `reply` and a "still gathering"
`phase`.

**`prompting_notes_update` semantics:**

- The field is the **full replacement value** for
  `manual_illustration_sessions.prompting_notes`. The server does
  not merge old + new — Agent 6 is responsible for folding any
  still-relevant prior lessons into the new memo (the model
  receives the prior value as `prompting_notes` in the input, so
  it can re-emit the old text plus new additions).
- Omitting the field or emitting `null` leaves the stored notes
  untouched (the field defaults to `null` when missing).
- The value MUST be **English**, regardless of the run's
  `source_language` — these notes feed Agent 1 and Agent 7, which
  consume English. The server treats this as a hard validation
  rule on the field; on a non-English heuristic violation the
  server re-prompts up to `CLAUDE_JSON_RETRY` times before
  storing.
- The value MUST be about **prompt-level mechanics** (renderer
  weaknesses and tag-level countermeasures), NOT user preferences
  or concept content. The prompt enforces this via examples
  (§ 6A.8.1); the server does not attempt to semantically
  validate the contents.
- Updates are legal on any `phase`. They are explicitly **not
  cleared** on `phase=restart_concept` (the server preserves the
  notes across concept restarts — § 6A.2 rule #12, § 6A.4 step
  6.1).

`phase` semantics:

**Concept-design sub-phase (`sub_phase = "concept_design"`):**

- `gathering` — still negotiating; `reply` carries the next assistant
  turn (question, suggestion, gentle reframe). `concept_candidate`
  is `null`.
- `awaiting_concept_confirmation` — the agent has a candidate
  concept it considers feasible per § 6A.5. `reply` quotes the
  verbatim English concept inline (§ 6A.2 rule #7) and explicitly
  asks for confirmation in the user's `source_language`.
  `concept_candidate` is the English canonical form (suitable for
  Agent 1), and **must be the exact substring quoted inside `reply`**.
- `concept_confirmed` — the latest user turn is approval of the
  previously-proposed `concept_candidate`. `concept_candidate` is
  the carried-forward English string, **byte-for-byte identical to
  the prior `awaiting_concept_confirmation` turn's
  `concept_candidate`** (server asserts this; mismatch → Claude
  failure and re-prompt). `reply` is short — a one-line
  acknowledgement that we will now render the image.

**Feedback-gathering sub-phase (`sub_phase = "feedback_gathering"`):**

- `gathering_feedback` — feedback collection continues. `reply` is
  the next assistant turn (typically one focused question or a
  probe about a key concept element). `concept_candidate` is `null`.
- `awaiting_feedback_confirmation` — the agent judges feedback is
  complete; `reply` is a single short closing question
  ("Have you said everything you wanted to say about the image?").
  `concept_candidate` is `null`.
- `feedback_confirmed` — the latest user turn affirms feedback is
  complete. `concept_candidate` is `null`. `reply` is a short
  acknowledgement that the next attempt is starting. The server
  slices the post-image user-message transcript into Agent 7's
  `user_feedback` input (§ 7.1 Call 7); Agent 6 does **not**
  paraphrase or summarize.
- `restart_concept` — drift exit (§ 6A.2 rule #10). The previous
  Agent 6 turn must have been a drift question ("…would you like
  to keep iterating, or design a fresh concept together?") and the
  user's reply selects the redesign option. `concept_candidate` is
  `null`. `reply` is a short cheerful acknowledgement ("OK, let's
  design a fresh idea together"). On this phase the server resets
  the sub-phase to `concept_design` and clears `last_agreed_concept`
  and `last_manual_image_path` on the session row.

**Either sub-phase (post-image only):**

- `accepted` — the latest user turn is approval of the most recent
  rendered image. `concept_candidate` is `null`. `reply` is a short
  closing acknowledgement. Only legal when at least one `image`
  row exists in the manual transcript (server guard demotes
  otherwise to `gathering_feedback`).

Hard rules enforced by the prompt and re-checked server-side:

1. **Sub-phase ↔ phase compatibility.** The server rejects (demotes
   to a safe phase) any reply whose `phase` is not legal in the
   active `sub_phase`. Specifically: `concept_confirmed` /
   `awaiting_concept_confirmation` are demoted to
   `gathering_feedback` if received in feedback sub-phase;
   `feedback_confirmed` / `awaiting_feedback_confirmation` /
   `restart_concept` are demoted to `gathering` if received in
   concept-design sub-phase.
2. **Feasibility envelope.** On every
   `awaiting_concept_confirmation` reply, `concept_candidate` must
   satisfy § 6A.5. The server runs the conservative heuristic from
   § 6A.5 and demotes the reply to `gathering` on failure.
3. **Verbatim concept handoff.** On every `concept_confirmed`
   reply, `concept_candidate` must exactly equal the
   `last_concept_candidate` value persisted from the prior
   `awaiting_concept_confirmation` turn (no trailing whitespace
   tolerance — the strings must be byte-identical). On every
   `awaiting_concept_confirmation` reply, the server verifies the
   `concept_candidate` text appears verbatim as a substring of
   `reply` (so the user really did see what they are being asked
   to confirm). A failure is treated as a Claude failure and
   re-prompted up to `CLAUDE_JSON_RETRY` times.
4. **No phase shortcuts.** Server demotes a `concept_confirmed`
   turn with no prior `awaiting_concept_confirmation` in the
   manual session to `awaiting_concept_confirmation`. Server
   demotes a `feedback_confirmed` turn with no prior
   `awaiting_feedback_confirmation` to `gathering_feedback`.
   Server demotes an `accepted` turn that is not immediately
   preceded by an `image` row in the transcript to
   `gathering_feedback`.
5. **No feedback summarization.** The prompt explicitly forbids
   summarizing user feedback in `reply` on `feedback_confirmed`.
   `reply` on `feedback_confirmed` is a short acknowledgement
   only; the actual feedback content is sliced from the transcript
   by the server.
6. **Polite refusal of out-of-bounds requests** (§ 6A.2 rule #11
   and § 6A.5 "Ethics envelope"). When triggered, the model
   stays in its current sub-phase: `gathering` (concept design)
   or `gathering_feedback` (feedback). The refusal text appears
   in `reply`; no structured output (concept_candidate, etc.) is
   emitted on a refusal turn.
7. **Voice continuity.** The persona-fragment shared with Agents
   0a / 0b / 4 applies. Agent 6's prose must read as the same voice
   the user heard during the initial chat.
8. **Tone.** § 6A.2 rules govern all replies. The prompt includes
   explicit positive and negative examples.
9. **Localization.** `reply` is in the run's `source_language`; the
   server does not re-translate it. If the run's `source_language`
   is `en`, the model writes in English. The frontend's i18n layer
   only affects framing strings (welcome / review / exhausted) —
   not Agent 6's authored replies. **Exception:** the verbatim
   English `concept_candidate` text embedded inside
   `awaiting_concept_confirmation` `reply` is in English regardless
   of `source_language` (§ 6A.2 rule #7 — what the user sees is
   what gets sent to Agent 1).
10. **Single output.** Agent 6 returns exactly one JSON object per
    call; no Markdown fences, no prefatory text, no trailing
    commentary (same rule as Agents 0b–5).
11. **`prompting_notes_update` discipline.** When the field is
    present and non-null, the server validates that the value is
    a plain English string (heuristic; see § 6A.2 rule #12 and
    § 6A.8.1) and that it is a *full replacement* — Agent 6 has
    been told the server does not merge with the prior notes.
    Validation failures are re-prompted up to
    `CLAUDE_JSON_RETRY` times; on persistent failure the server
    discards the update for that turn (the `reply` / `phase` /
    `concept_candidate` outputs are still applied) so the
    conversation continues. The update is **not** cleared on
    `phase=restart_concept` (§ 6A.4 step 6.1).

#### Call 7 — `manual_revise_prompts` (Agent 7, "the collaboration prompt reviser")

**Purpose:** In the collaboration mode (§ 6A), translate the user's
post-image feedback into revised positive/negative prompts that aim
the next ComfyUI render at the same agreed concept but better. Agent
7 is dispatched by the server on `phase=feedback_confirmed` (§ 6A.4
step 5). It is **not** part of the auto pipeline — Agent 3
(`revise_prompts`, § 7.1 Call 3) continues to handle prompt revision
in the auto loop.

Agent 7 lives outside the chat: it never speaks to the user, never
sees the chat transcript directly, and never produces a `reply`
field. Its sole job is to read a structured input payload and emit
a revised positive/negative prompt pair.

**Input (to Claude):**
- `last_agreed_concept` — the verbatim English concept the user
  confirmed before the most recent render. Same string Agent 1 was
  invoked with on the previous render. The agreed concept does
  **not** change here — Agent 7's revisions stay faithful to it
  (concept-level edits are out of scope for this agent and would
  reach Agent 6's `restart_concept` exit instead).
- `user_feedback` — the verbatim post-image user-message blob
  computed by § 6A.4 step 5.2 (raw user prose in the run's
  `source_language`, newline-separated). Agent 7's prompt tells
  the model that this is unedited user text, possibly noisy, that
  it must read carefully and triage.
- `last_positive_prompt` / `last_negative_prompt` — the exact
  positive and negative prompt strings that produced the most
  recent manual image. On the second-and-later iteration these
  are the **previously revised** prompts, not the originals —
  each iteration builds on the last (§ 6A.4 step 5.8).
- `prompting_notes` — the current value of
  `manual_illustration_sessions.prompting_notes` (English-only
  cumulative prompt-engineering memo curated by Agent 6 across
  this manual session, § 6A.2 rule #12). NULL until Agent 6 has
  populated it at least once. When non-null, Agent 7 treats this
  memo as **authoritative prompt-level guidance** — it
  accumulates lessons across every manual attempt on this
  illustration, including across `restart_concept` boundaries.
  Conflict resolution: the memo wins on prompt-level mechanics
  (tag choices, negative-tag placement) while the immediate
  `user_feedback` wins on what to depict this attempt. Both
  must coexist in the revised prompts.
- `style_guide` — same as Agent 1 / Agent 3.
- `character_role` — same as Agent 1 / Agent 3. Agent 7 cannot
  change the workflow choice (`single-lora` ↔ `no-lora`) because
  the cast shape is fixed for this illustration; the server reuses
  `illustrations.current_workflow` after this call.
- `contains_entity` — same as Agent 1 / Agent 3 (the run-level
  `NarrativeEntity | null` whose label is on the illustration row).

**Output schema:**
```json
{
  "positive": "string (revised positive prompt; same Danbooru-style format as Agent 1/3)",
  "negative": "string (revised negative prompt; same baseline + scene-specific negatives)"
}
```

The output shape is intentionally a subset of Agent 3's — no
`workflow`, no `notes`, no concept commentary — because Agent 7's
contract is narrower (cast shape and concept are both fixed).

Hard rules enforced by the prompt:

1. **Stay within the § 6A.5 envelope.** Even if the user's feedback
   explicitly asks for an out-of-envelope change (a second
   character, regional prompting effects, text inside the image,
   etc.), the revised prompts must remain within envelope. The
   prompt makes clear that Agent 7 is not a side channel to bypass
   the constraints Agent 6 enforces upstream.
2. **Stay within the § 7.3.6 negative-prompt baseline.** All
   safety/anatomy/quality/multi-character negatives from the
   baseline must remain in `negative`. Agent 7 may add scene- or
   feedback-specific negatives on top of them.
3. **Honor the agreed concept first.** When user feedback conflicts
   with the agreed concept (e.g. the user contradicts an element of
   the concept that was previously confirmed), Agent 7 prefers the
   agreed concept. The model is instructed that such conflicts are
   rare in normal use because Agent 6's drift detection should
   have caught them upstream; when they do arrive, the safe bet is
   to keep the concept intact and treat the conflicting feedback
   as noise.
4. **Same Danbooru / Illustrious / MHA discipline as Agent 3.** The
   prompt embeds the § 7.3.1 / § 7.3.6 / § 7.3.10 conventions
   verbatim (copy-pasted from `revise_prompts.md` as authoring
   guidance, the same way Agent 4 copy-pastes from
   `build_story.md`).
5. **Polite refusal.** If `user_feedback` contains a request for
   ethically out-of-bounds content (§ 6A.5 "Ethics envelope"),
   Agent 7 ignores that portion of the feedback while honoring the
   rest. It does not have a refusal channel back to the user —
   the absence of the requested element in the next image is its
   only signal. (Agent 6's upstream refusal should normally catch
   such cases first.)
6. **Single output.** Agent 7 returns exactly one JSON object per
   call; no Markdown fences, no prefatory text, no trailing
   commentary (same rule as Agents 0b–5).

### 7.2 RunPod ComfyUI Serverless

The app ships **two** workflow files in `app/workflows/`, both in
**ComfyUI API format**:

- `single-lora.json` — single human character (optionally accompanied
  by one non-human narrative entity, animate or inanimate). The
  character LoRA is wired in via the `CHARACTER_LORA` placeholder.
- `no-lora.json` — no human character (entity-alone scene, or pure
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
| `male` / `female` / `mother` | `single-lora.json`  | Single human + optional non-human entity        |
| `null`                       | `no-lora.json`      | Entity alone, or no characters at all           |

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

This section defines the creative and prompting conventions that all
nine Claude agents must respect. The technical contracts in § 7.1
stay generic; this section makes them concrete for the MVP visual
stack.

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
prompts. Agents 1, 3, and 7 must always use these names (plus their
canonical trigger words and visual descriptors) regardless of the names
the user chose during the chat (`name_in_story`). The user-chosen names
are narrative only — they appear in the story prose written by Agent 0b
but are never sent to ComfyUI.

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

1. **Single human + optional non-human entity** — dominant shape. One
   of the three permitted human character roles, optionally accompanied
   by exactly one non-human entity (animate non-humanoid character, or
   story-important object) drawn from the run's `narrative_entities`
   register. Rendered by `single-lora.json` (§ 7.2.1).
2. **Entity alone** — no human character; exactly one non-human entity
   from the register is the visible subject (e.g. the cat sleeping on
   the windowsill, the gold pocket watch resting on a table). Rendered
   by `no-lora.json`. Capped at ≤ 1 per run by Call 0b rule #13.
3. **No characters** — *rare*; reserved for story-essential environment
   beats. No human, no entity. Rendered by `no-lora.json`. Capped at
   ≤ 1 per run by Call 0b rule #13.

Scenes with multiple human characters, group scenes, crowds, scenes
with multiple non-human entities visible, and scenes whose subject is
ambiguous are excluded under all three shapes.

For shapes 1 and 2, when the entity is a `non_human_character` it must
have a body plan fundamentally different from humans — quadrupeds,
winged creatures, serpents, mechanical entities without human form
factor, etc. Anthropomorphic / humanoid beings (cat-girls, elf-like
beings, humanoid androids with human faces, etc.) are treated as a
*second human* and therefore forbidden as non-human entities. Objects
(`kind="object"`) are exempt from the body-plan rule — they are
inanimate and never compete with the human for the "single character"
slot.

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

Agents 1, 3, and 7 carry this discipline into the actual Danbooru tags.
The `positive` field must include explicit emotion/expression tags and
explicit action/pose tags. Vague tags like `standing`, `looking`, or
`posing` alone are insufficient and must be augmented with specifics.

Agent 2 evaluates this discipline as part of its checklist (see § 7.3.5).
A correctly rendered character with a vague or ambiguous expression should
be rejected with `problem="prompt"` and a suggestion to add specifics.

When `contains_entity_label` is non-null on the illustration, the
mandatory specificity applies to both the human and the
human-entity interaction. The `concept` field must describe a
concrete human expression / gesture / action **and** a concrete
spatial or behavioral relationship between the human and the entity
(e.g. "Mia kneels beside the small black cat, one hand resting gently
on its back" — single sentence carrying expression, gesture, and the
interaction with the entity).

For entity-alone scenes (shape 2, `character_role=null` with
`contains_entity_label` non-null), the specificity rule shifts to the
entity itself: the `concept` field must describe the entity in a
concrete, depictable state — a specific posture, action, lighting, or
contextual cue (e.g. "the gold pocket watch lying open on the desk,
hands frozen at 9:14, lamplight glinting on the rim"). Generic "object
on a surface" or "animal in a meadow" beats are not acceptable.

#### 7.3.5 Agent 2 evaluation checklist

Agent 2 (`evaluate_image`) judges each rendered image against this
checklist. The image is `ok` only when **all** of the following hold:

1a. **Cast shape matches `character_role`.** If `character_role` is
    non-null, exactly one human is visible; multiple visible humans →
    `problem="prompt"`. If `character_role` is null, no humans are
    visible; any visible human → `problem="prompt"`.
1b. **Entity alignment.** If `contains_entity_label` was specified for
    this illustration, exactly one non-human entity matching that label
    is visible and prominently positioned per the concept. Missing
    entity → `problem="prompt"`. Multiple copies of the same entity
    type appearing → `problem="prompt"`. Wrong kind of entity rendered
    (e.g. a dog when the label said cat, or a watch when the label said
    locket) → `problem="prompt"`. If `contains_entity_label` was *not*
    specified and a non-human entity nevertheless appears prominently →
    also `problem="prompt"` (Agent 0b did not plan one). A small,
    peripheral non-human element that does not distract is tolerated.
1c. **Environment matches the slot.** The visible environment is
    consistent with the locked `environment` for this scene (label and
    aspect — `single`, `inside`, or `outside`). A renderer miss that
    is plausibly steerable through prompt tweaks → `problem="prompt"`.
    Persistent inability of the environment to host the planned action,
    or a fundamental concept/environment clash that no prompt edit can
    fix → `problem="environment"` (routes to Agent 4b — see § 7.1
    Call 2 routing semantics and Call 4b).
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

Agents 1, 3, and 7 must always include in `negative` a standard safety
and quality baseline, in addition to scene-specific negatives. The
baseline includes at minimum:

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

**Conditional adjustments when `contains_entity_label` is non-null**
(Agents 1, 3, and 7 apply these on top of the baseline above when the
illustration carries a non-null entity label):

- **Do not include** `solo` in the *positive* prompt. The Danbooru
  `solo` tag means "only one entity in the image" and conflicts with
  the entity's presence (animate or inanimate).
- **Keep the multi-character negatives** (`multiple characters`, `crowd`,
  `two girls`, `two boys`, `2girls`, `2boys`, `group`) — they refer to
  humans.
- **Add anti-duplicate negatives for the entity type.** Pattern: one
  extra clause forbidding duplication of the *specific* entity
  present, derived from the entity label. If the entity is a cat, add
  `2cats, multiple cats`; if a dragon, `2dragons, multiple dragons`;
  if a pocket watch, `multiple watches, two pocket watches`; etc.
- **Do not include anti-creature / anti-object tags.** Phrases like
  `no animals`, `no creatures`, `no pets`, `no objects` must not appear
  in the negative when an entity is present.
- **Do not use "focus" tags** (`animal focus`, `cat focus`,
  `object focus`, etc.) when a human is also in the scene. These tags
  suppress the human and push the entity into the primary subject role,
  which inverts the intended composition. Entity-alone scenes
  (`character_role=null`) are the only case where appropriate focus
  tags may be used to keep the inanimate or non-human entity prominent.

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
  framing"). Agents 1, 3, and 7 reference this when constructing prompts.

The style LoRA applies globally to every visible element in the frame,
including any non-human entity. This is the desired behavior
(consistent look) but worth stating so reviewers do not flag it as a
gap. See § 7.3.10 for the "style LoRA caveat" describing the known
limitation when the style LoRA dominates non-human rendering.

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
2. **Single-human moments, with optional non-human entity.** Every
   illustration point is a beat where exactly one of the three permitted
   human roles is on the page, optionally accompanied by exactly one
   non-human entity (animate or inanimate) drawn from the run's
   `narrative_entities` register. Other characters can be present in
   the prose between illustrations, but the illustrated moments isolate
   the single human (plus, optionally, the entity). Entity-alone beats
   (no human, single non-human entity) and pure-environment beats are
   also permitted but capped (§ 7.1 Call 0b rule #13).
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
8. **Entities earn their presence.** A non-human entity in a scene
   must add emotional or compositional weight to that beat — whether
   it is a creature (the character pets the cat for comfort; the
   dragon perches watchfully on the boy's shoulder; the robot stands
   beside her as she decides) or an inanimate object (the gold pocket
   watch she holds at the moment of decision; the locket she opens by
   lamplight). An entity that is simply "in the frame" for decoration
   is worse than no entity — it dilutes the focal subject's prominence
   without serving the story. If a scene works without an entity, do
   not add one. Entity-alone scenes (no human) are reserved for beats
   where the entity itself *is* the story moment.

These eight principles apply unchanged to **Agent 4** when it rewrites a
paragraph at concept-restart time (§ 7.1 Call 4). Agent 4 receives the
full current story so it can keep the substitute paragraph consistent
with the arc, the cast, and the neighbouring scenes. The single
additional constraint it has — and that Agent 0b does not — is that the
shape of the story (number of paragraphs, number of illustrations,
their ordering) is fixed at run creation and must not be altered.

#### 7.3.10 Entity prompting guidance

Generic principles that Agents 1, 3, and 7 follow when the
illustration's `contains_entity_label` field is non-null. **These
principles apply regardless of the kind of non-human entity** — there
are no entity-specific code paths anywhere in the implementation. The
agent reasons about each entity from its `label` and `kind`
(`non_human_character` for living non-human creatures, `object` for
inanimate items) as supplied in the run's `narrative_entities`
register.

- **Numeric tagging.** Use Danbooru-style numeric tags for the entity
  where applicable. For `kind="non_human_character"` use the animal /
  creature form (`1cat`, `1dog`, `1dragon`, `1robot`). For
  `kind="object"` use a singular object tag mirroring the label
  (`1watch`, `1locket`, `1book`, `1lantern`). The human is still tagged
  with its `1girl` / `1boy` form per role. Do not use `solo` when an
  entity is present, regardless of kind.
- **Interaction / placement tagging.** Translate the human-entity
  relationship implied by the concept into concrete Danbooru-style
  tags. For animate entities, examples of the *form* expected (not
  prescribing specific entities): `holding X`, `X on shoulder`,
  `X in lap`, `riding X`, `petting X`, `X beside her`, `X behind him`,
  `X looking up at her`. For inanimate entities the same shape applies
  with object-appropriate verbs: `holding X`, `X on desk`, `X in hand`,
  `X on table`, `gazing at X`. For entity-alone scenes (no human), the
  tags describe the entity's state and placement directly (`X resting
  on windowsill`, `X open on table, lamplight`).
- **Size and prominence.** If the entity should be a meaningful visual
  element rather than peripheral background, include explicit size or
  prominence tags (`large X`, `X fills frame`, `close-up on X and her`,
  `full body shown`). Without these the model often renders the entity
  small and in a corner. Conversely, if the entity is supposed to be
  peripheral, no extra emphasis is needed.
- **Non-human anatomy negatives** (for `kind="non_human_character"`).
  Non-human anatomy is less reliably rendered than human anatomy. The
  agent derives appropriate negatives from the entity's body plan
  rather than from its specific identity:
  - For four-legged creatures: `extra legs, missing legs, malformed paws`.
  - For winged creatures: `deformed wings, asymmetric wings, broken wings`.
  - For mechanical entities: `bad mechanical design, malformed limbs,
    asymmetric mechanical parts`.
  - For serpentine creatures: `extra heads, broken body, segmented incorrectly`.
- **Object-specific negatives** (for `kind="object"`). Inanimate
  entities do not have anatomy but do have shape, material, and
  legibility concerns the agent derives from the label:
  - For mechanical / detailed objects (watches, instruments, gears):
    `malformed mechanism, wrong number of dials, illegible details`.
  - For text-bearing objects (books, signs, letters): `unreadable text,
    garbled text, fake writing` — the workflow cannot reliably render
    legible text, so the prompt should typically obscure the writing
    surface or avoid close-ups of it.
  - For symmetric objects (lockets, jars, mirrors): `asymmetric
    silhouette, lopsided shape, distorted symmetry`.
  - For multi-part assemblies (lanterns, instruments): `missing parts,
    extra parts, misaligned components`.

  Agents 1 / 3 / 7 decide which category applies based on the
  `label` text. This is generic reasoning, not a hardcoded lookup
  table.
- **Style LoRA caveat.** When entity rendering looks "off" (e.g.,
  a cat with anime-girl-like eyes due to the style LoRA dominating, or
  an object that takes on cartoon character traits), the style LoRA
  may need to be slightly reduced for that illustration. This is not
  auto-tuned by the agents in MVP — it is a known limitation. A future
  iteration may add a per-illustration style weight override; for MVP
  we accept the default.

### 7.4 Agent prompt files

Each Claude agent's system prompt lives in its own Markdown file under
`backend/app/agents/`. There are nine files, one per call in § 7.1:

| File                        | Agent | Call name                |
|-----------------------------|-------|--------------------------|
| `chat.md`                   | 0a    | `chat`                   |
| `build_story.md`            | 0b    | `build_story`            |
| `generate_prompts.md`       | 1     | `generate_prompts`       |
| `evaluate_image.md`         | 2     | `evaluate_image`         |
| `revise_prompts.md`         | 3     | `revise_prompts`         |
| `rethink_concept.md`        | 4     | `rethink_concept`        |
| `translate.md`              | 5     | `translate`              |
| `manual_concept.md`         | 6     | `manual_concept`         |
| `manual_revise_prompts.md`  | 7     | `manual_revise_prompts`  |

Loading rules:

- `services/claude.py` reads all nine files at process startup and caches
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
8. For Agent 6 (`manual_concept.md`): the design philosophy from
   § 6A.2 verbatim (including the verbatim-concept-handoff,
   user-driven-feedback, drift-detection, and refusal rules), the
   feasibility envelope from § 6A.5 verbatim, the phase machine
   from § 6A.4 (which `phase` values are legal in each `sub_phase`),
   and the embedded persona-fragment shared with Agents 0a / 0b / 4.
   Agent 6 follows the same JSON-only-output discipline as Agents
   0b–5, except that its `reply` field is free-form prose like
   Agent 0a's.
9. For Agent 7 (`manual_revise_prompts.md`): the § 7.3.1 / § 7.3.6 /
   § 7.3.10 prompting conventions verbatim (copy-pasted from
   `revise_prompts.md` the same way Agent 4 copy-pastes from
   `build_story.md`), the § 6A.5 envelope verbatim (including the
   "Application to Agent 7" paragraph), the "agreed concept first"
   conflict-resolution rule (§ 7.1 Call 7), and the explicit
   reminder that Agent 7 never writes user-facing prose — its only
   output is the `{positive, negative}` JSON object. A short
   comment block at the top of the §§ 7.3 sections names
   `revise_prompts.md` as the source-of-truth sibling so future
   editors keep them in sync.

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
      "contains_entity_label": "string|null",
      "environment": { "label": "string", "kind": "indoor|outdoor|dual", "aspect": "single|inside|outside" } | null
    }
  ],
  "environments": [
    { "label": "string", "kind": "indoor|outdoor|dual", "aspect": "single|inside|outside" }
  ],
  "narrative_entities": [
    { "label": "string", "kind": "non_human_character|object", "importance": "primary|secondary|supporting", "reserved_for_scene_index": 0 }
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

`contains_entity_label` reflects the current state of the
illustration's `contains_entity_label` column — the label of the
`NarrativeEntity` visually present in this scene, or `null` for scenes
with no entity. The full entity record (with `kind`, `importance`,
`reserved_for_scene_index`) is on the top-level
`narrative_entities[]` array and matched by normalised label. Like
`scene_excerpt` and `story_blocks`, this value reflects the latest
state after any Agent 4 / Agent 4b rewrites have been persisted.

`environment` reflects the run's `environments_json[scene_index]`
entry — the locked indoor/outdoor/dual environment Agent 0b assigned
to this slot, mutated only by Agent 4b. The same entries are also
exposed in the top-level `environments[]` array so consumers can read
the full register without walking illustrations.

`environments[]` and `narrative_entities[]` are the two registers
locked at story-build time (§ 1, § 5). `environments[]` always has
exactly 5 entries with position `N` == `scene_index=N`.
`narrative_entities[]` is the unified pool that replaces the legacy
`companions` + `reserved_entities` split. Both are mutable in
narrowly-scoped ways: Agent 4b may swap one environment slot's entry
per branch, and Agent 4 / Agent 4b mutate per-illustration
`contains_entity_label` via the `entity_action` discriminator. The
top-level arrays let the frontend render entity-aware affordances
(e.g. tooltips, register inspectors) without per-event reconciliation.

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
| `illustration_entity_updated`    | `{ "illustration_id", "scene_index", "contains_entity_label": "string\|null", "entity": { "label", "kind", "importance", "reserved_for_scene_index" } \| null }` — emitted by Agent 4 / Agent 4b when the scene's entity changes (set, swapped, or dropped). `entity` carries the full record from `narrative_entities[]` after the mutation (or null when dropped). |
| `illustration_environment_updated` | `{ "illustration_id", "scene_index", "environment": { "label", "kind", "aspect" } }` — emitted by Agent 4b when it swaps the slot's environment. |
| `illustration_role_updated` | `{ "illustration_id", "scene_index", "character_role": "male\|female\|mother\|null" }` — emitted only when Agent 4 swaps a scene's cast shape |
| `translations_refreshed`    | `{ "language", "items": [ { "kind": "story_title\|story_topic_description\|paragraph\|illustration_concept", "paragraph_index"?: N, "scene_index"?: N, "text": "string" } ] }` — emitted to every subscriber after § 8.9 completes, so multi-tab views in the same language stay in sync |
| `illustration_completed`    | `{ "illustration_id", "scene_index", "image_url" }`                     |
| `illustration_failed`       | `{ "illustration_id", "scene_index", "error_message" }`                 |
| `illustration_manual_started` | `{ "illustration_id", "scene_index", "welcome_message": { "role": "assistant", "content": "string (the localized welcome text in source_language, with `#…#` bold markers preserved)", "id": "string", "created_at": "ISO-8601" } }` — emitted once when an illustration transitions into `MANUAL_CHATTING` for the first time (§ 6A.3). |
| `manual_message_appended`   | `{ "illustration_id", "scene_index", "message": { "id", "role": "user\|assistant", "content", "created_at" }, "phase": "gathering\|awaiting_concept_confirmation\|concept_confirmed\|gathering_feedback\|awaiting_feedback_confirmation\|feedback_confirmed\|restart_concept\|accepted\|null", "sub_phase": "concept_design\|feedback_gathering" }` — emitted whenever a new chat row is persisted in `manual_messages` (§ 6A.6). One event per row; user echoes are emitted just like assistant turns so other tabs stay in sync. `phase` carries Agent 6's reply phase when the row is assistant-authored (and is `null` for user echoes and for the static framing bubbles inserted by the backend like the welcome / render-failed / review-prompt bubbles). `sub_phase` is the post-event session sub-phase, included on every event so frontends can update affordances in lockstep with the message. |
| `manual_image_rendered`     | `{ "illustration_id", "scene_index", "manual_attempt": K, "image_url": "string", "review_message": { "id", "role": "assistant", "content": "string (the localized review prompt in source_language)", "created_at" }, "sub_phase": "feedback_gathering" }` — emitted after a successful manual render (§ 6A.4 step 3.8). The frontend renders the image bubble and the review-prompt bubble in this order. `sub_phase` is always `feedback_gathering` here (a render flips the session into that sub-phase). |
| `illustration_manual_ended` | `{ "illustration_id", "scene_index", "outcome": "completed\|exhausted\|cancelled" }` — emitted when the manual flow terminates (user accepted the image → `completed`; attempts exhausted → `exhausted`; run cancelled → `cancelled`). The frontend uses this to collapse the chat overlay. |
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

`illustration_entity_updated` is emitted at most once per successful
Agent 4 or Agent 4b invocation, **only when the scene's
`contains_entity_label` actually changes** (including any change
to/from `null`). When the agent's `entity_action` is `"none"` or
`"keep"` and yields the same label as before, no event is emitted.
Subscribers locate the illustration by `illustration_id` and assign
`illustration.contains_entity_label = event.contains_entity_label` on
the existing reactive object; the optional `entity` payload is used
to update any in-memory entity register the frontend keeps
(e.g. `run.narrative_entities[]`). Like the other in-place mutations,
this triggers a field-level re-render of the `IllustrationCard`
without remount.

`illustration_environment_updated` is emitted at most once per
successful Agent 4b invocation, **only when the slot's environment
record changes** (label, kind, or aspect). The payload carries the
post-mutation `Environment` record. Subscribers assign it to the
matching illustration's `environment` field **and** overwrite
`run.environments[scene_index]` on the live `run` object — both
mutations are necessary so the snapshot view and per-card view stay
consistent.

Per-rethink ordering guarantees (one branch, one rethink cycle):

**Agent 4 (concept rethink):**

1. `illustration_state` — `state="RETHINKING_CONCEPT"`, fields still
   carry the *old* `current_concept` and `scene_excerpt` (the rethink
   hasn't happened yet on the server when this event is emitted).
2. `paragraph_updated` — the rewritten paragraph text, after server
   persistence.
3. `illustration_entity_updated` — emitted *only when* the entity
   label changed, after server persistence.
4. `illustration_role_updated` — emitted *only when* Agent 4 swapped
   the scene's `character_role` (rare), after server persistence.
5. `illustration_state` — `state="GENERATING_PROMPTS"`, fields carry
   the *new* `current_concept` and `scene_excerpt`.

**Agent 4b (environment rethink):**

1. `illustration_state` — `state="RETHINKING_ENVIRONMENT"`, fields
   still carry the *old* `current_concept`, `scene_excerpt`, and
   `environment`.
2. `paragraph_updated` — the rewritten paragraph text, after server
   persistence.
3. `illustration_environment_updated` — the new environment record
   for this slot, after server persistence.
4. `illustration_entity_updated` — emitted *only when* the entity
   label changed (Agent 4b may also drop or claim an entity as part
   of the swap), after server persistence.
5. `illustration_state` — `state="GENERATING_PROMPTS"`, fields carry
   the *new* `current_concept`, `scene_excerpt`, and `environment`.
   The branch's `skip_concept_rethink_once` flag is now set so the
   next outer-loop iteration bypasses Agent 4.

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

### 8.10 Manual illustration chat (§ 6A)

Three endpoints back the manual chat fallback. All are scoped to a
single illustration; they share the `:illustration_id` path
parameter, are guarded by the run's cancellation flag, and emit SSE
events on the parent run's event bus so other tabs viewing the run
see chat activity in real time. Behind the scenes Agent 6 is invoked
on every user-message POST; the prompt-proposing / -revising steps
(Agent 1 in the concept-design sub-phase, Agent 7 in the
feedback-gathering sub-phase) and the RunPod render are
server-internal side effects of `concept_confirmed` and
`feedback_confirmed` turns respectively.

The endpoints return **only the new events** since the request, not
the full transcript — the frontend reconstructs the transcript from
the same snapshot SSE event used by the auto loop (§ 8.4). The
snapshot payload (§ 8.3) is extended with a per-illustration
`manual_session: { messages: [...], manual_attempts: K, last_image_url: "string|null", sub_phase: "concept_design"|"feedback_gathering" } | null`
object so reconnects and deep links restore the chat exactly,
including which sub-phase the user is currently in (so the frontend
can render the right affordances — concept-iteration vs.
feedback-on-image — without an extra round trip).

#### 8.10.1 `POST /api/illustrations/{illustration_id}/manual/messages`

Append a user message to the manual chat and let Agent 6 (and possibly
Agent 1 + RunPod) react. Idempotency is NOT enforced server-side in
MVP — the frontend is responsible for disabling the send button while
a request is in flight (mirrors § 8.1's chat send pattern).

Request body:
```json
{ "content": "string (user message, ≤ CHAT_MESSAGE_MAX_CHARS)" }
```

Server flow (in this exact order):

1. Reject with **404** if the illustration does not exist.
2. Reject with **409** if the illustration is not in `MANUAL_CHATTING`.
3. Reject with **409** if the run is cancelled or has reached a
   terminal status.
4. Persist the user row in `manual_messages`. Emit
   `manual_message_appended`.
5. Invoke Agent 6 (§ 7.1 Call 6) with the input fields per § 7.1,
   including the current
   `manual_illustration_sessions.sub_phase`.
6. Apply server guards (sub-phase ↔ phase compatibility, phase
   demotion, feasibility heuristic, verbatim-handoff assertion;
   § 6A.4 / § 6A.5 / § 7.1 Call 6 hard rules 1–4).
7. Persist Agent 6's assistant row in `manual_messages`. Emit
   `manual_message_appended`.
8. If the final phase is `concept_confirmed`: perform the dispatch
   sequence in § 6A.4 step 3 (state transitions, Agent 1 call,
   render, image bubble) and on success flip
   `manual_illustration_sessions.sub_phase` to
   `feedback_gathering`. Each step writes to DB and emits its SSE
   event before the next step starts.
9. If the final phase is `feedback_confirmed`: perform the
   prompt-revision dispatch sequence in § 6A.4 step 5 (slice
   post-image user messages, call Agent 7, render, image bubble).
   On success the sub-phase stays at `feedback_gathering`
   (the same agreed concept is being iterated on). Each step
   writes to DB and emits its SSE event before the next step
   starts.
10. If the final phase is `restart_concept`: perform the reset
    sequence in § 6A.4 step 6 (clear `last_agreed_concept` and
    `last_manual_image_path`, flip `sub_phase` to `concept_design`).
    No render is dispatched and `manual_attempts` is not
    incremented.
11. If the final phase is `accepted`: perform the promotion sequence
    in § 6A.4 step 7.
12. Run the budget check (§ 6A.4 step 8). If it trips, emit the
    apology turn, set the illustration to `FAILED`, and emit
    `illustration_state` (FAILED), `illustration_failed`, and
    `illustration_manual_ended` with `outcome="exhausted"`.

Response 200: a thin envelope confirming acceptance —
```json
{
  "illustration_id": "string",
  "state": "MANUAL_CHATTING|MANUAL_GENERATING_PROMPTS|MANUAL_RENDERING|COMPLETED|FAILED",
  "manual_attempts": K,
  "sub_phase": "concept_design|feedback_gathering"
}
```
The frontend treats the SSE stream as the source of truth for the
new messages and image; this response is only used to confirm the
POST, re-enable the input, and (via `sub_phase`) update the input
placeholder / affordances for the next user turn.

Errors:

- 400 if `content` is empty or exceeds `CHAT_MESSAGE_MAX_CHARS`.
- 404 if the illustration does not exist.
- 409 if the illustration is not in `MANUAL_CHATTING`, the run is
  in a terminal state, or the manual flow has already been ended
  (`outcome="exhausted"` previously emitted).
- 502 if Agent 6 fails after `CLAUDE_JSON_RETRY` retries; the
  manual session stays in `MANUAL_CHATTING` (in the same sub-phase
  it was in) and the user can retry the same message. No state
  change is persisted on this path (the user's row IS persisted at
  step 4; the assistant row at step 7 is what fails).
- 502 if Agent 1 fails on a `concept_confirmed` turn (after Agent 6
  succeeded). The illustration is rolled back to `MANUAL_CHATTING`
  in the concept-design sub-phase and an
  `illustration.manual.render_failed` assistant bubble is
  appended.
- 502 if Agent 7 fails on a `feedback_confirmed` turn (after
  Agent 6 succeeded). The illustration is rolled back to
  `MANUAL_CHATTING` in the feedback-gathering sub-phase
  (the agreed concept and its image remain the working baseline)
  and an `illustration.manual.render_failed` assistant bubble is
  appended.
- 502 if RunPod fails on the manual render. See § 6A.4 step 3.10
  for the behavior; the response is still 502 and the frontend
  shows a toast.

#### 8.10.2 `GET /api/illustrations/{illustration_id}/manual`

Returns the full manual chat for a single illustration (used by the
frontend on a hard refresh when the SSE snapshot has not yet
arrived, and for tests). Response body:

```json
{
  "illustration_id": "string",
  "state": "MANUAL_CHATTING|MANUAL_GENERATING_PROMPTS|MANUAL_RENDERING|COMPLETED|FAILED",
  "manual_attempts": K,
  "sub_phase": "concept_design|feedback_gathering",
  "messages": [
    { "id": "string", "role": "user|assistant|image", "content": "string", "image_url": "string|null", "manual_attempt_index": "K|null", "created_at": "ISO-8601" }
  ],
  "last_image_url": "string|null",
  "last_agreed_concept": "string|null"
}
```

- 404 if the illustration does not exist.
- 200 with `state` reflecting any terminal state if the manual flow
  has ended. After `COMPLETED` or exhausted-FAILED the messages are
  retained for read-only history.

#### 8.10.3 Cancellation behavior

`POST /api/runs/{run_id}/cancel` (§ 8.5) checks every illustration's
state. For each illustration in any `MANUAL_*` state it:

1. Transitions the illustration to `CANCELLED`.
2. Emits `illustration_state` (CANCELLED) and `illustration_manual_ended`
   with `outcome="cancelled"`.

This happens synchronously inside the cancel handler — there are no
long-running async manual loops to interrupt; all manual writes are
inside POST handlers in § 8.10.1 which all start with the
cancellation check.

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

**Manual illustration endpoint** (HTTP-only, not persisted on any row;
§ 8.10):

| `error_code`           | Meaning                                                                                          |
|------------------------|--------------------------------------------------------------------------------------------------|
| `MANUAL_CHAT_FAILED`   | Agent 6 failed after `CLAUDE_JSON_RETRY` retries. The manual session remains in `MANUAL_CHATTING` in its current sub-phase; the user can retry. |
| `MANUAL_PROMPT_FAILED` | Agent 1 failed after retries on a `concept_confirmed` turn, or Agent 7 failed after retries on a `feedback_confirmed` turn. The branch is rolled back to `MANUAL_CHATTING` (in the matching sub-phase) and an apology bubble is appended. |
| `MANUAL_RENDER_FAILED` | RunPod failed on a manual render. The manual attempt is consumed; the branch returns to `MANUAL_CHATTING` (or to `FAILED` if the budget is now exhausted). |

On terminal exhaustion (§ 6A.4 step 8), the illustration's
`error_message` is set to a non-localized sentinel (`"Manual attempts
exhausted"`) and the **state** alone — `FAILED` with the
`illustration_manual_ended` event preceding it — is what the frontend
uses to render the standard FAILED card. There is intentionally no
user-facing error code for "manual exhausted" since the chat itself
already explained the situation conversationally (§ 6A.7 key #4).

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
   subtitle (`i18n.t('app.subtitle')`). The `LanguageSwitcher` is **not**
   rendered by this view — it is mounted once in `App.vue` and floats in
   the top-right of the centered app container on every screen (§ 9.8).
   The view is responsible only for reserving enough top whitespace so
   the switcher never overlaps the title at any supported viewport width.
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

   The chat experience also covers the optional non-human entity topic
   (§ 7.1 Call 0a rules #6–#9). Agent 0a is expected to surface the
   entity question naturally — e.g. *"Bude v príbehu okrem hlavných
   postáv aj nejaké zviera, robot, kúzelný predmet alebo iná dôležitá
   bytosť či vec?"* — but only once the human cast is settled, only if
   the user has not already volunteered hints, and without insisting if
   the user declines. The verbatim phrasing lives in `chat.md`; this
   clause captures the intent. Entities the user mentions are stored on
   the brief as `non_human_entities[]` hints (label + role_in_story)
   and promoted by Agent 0b into the run's `narrative_entities`
   register at story-build time.

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
   followed by the story title. The `LanguageSwitcher` is mounted once
   by `App.vue` in the top-right of the centered container (§ 9.8) — it
   is **not** part of this view's template. The header reserves top
   whitespace so the floating switcher never overlaps the story title
   even when titles are unusually long.
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
  text and excerpt-preview tooltip). When `illustration.environment`
  is present, the popover additionally shows the environment label and
  aspect on a separate small line (e.g. "Prostredie: auto · vnútro").
- The **image slot** in the card body — skeleton (aspect 1:1) until
  `COMPLETED`, then the actual thumbnail (click to open original).
- **Entity subtitle** (only when `illustration.contains_entity_label`
  is non-null): a small line below the existing scene info reading
  `i18n.t('illustration.containsEntity', { label })`, where the
  localised string is e.g. *"V scéne je tiež: {label}"* (Slovak),
  *"Ve scéně je také: {label}"* (Czech), *"Also in the scene: {label}"*
  (English). The `label` placeholder is filled from
  `illustration.contains_entity_label`. When the label is null, the
  line is omitted entirely. The subtitle is reactive — when the
  `illustration_entity_updated` SSE event mutates the label in place,
  the subtitle re-renders without remount; when the label transitions
  to null, the subtitle disappears; when it transitions from null to
  non-null, it appears.
- **Environment subtitle** (always shown once `illustration.environment`
  is populated): a small line reading
  `i18n.t('illustration.environment', { label, aspect })`, e.g.
  *"Prostredie: les · vonku"*. Reactive to the
  `illustration_environment_updated` SSE event (Agent 4b swap).
- On `FAILED`: a short error message (no retry button in MVP).
- On `CANCELLED`: greyed-out card with label "Zrušené".
- On `MANUAL_CHATTING` / `MANUAL_GENERATING_PROMPTS` / `MANUAL_RENDERING`:
  the card **transforms** into a chat surface (§ 9.1A) — the image
  slot, attempt counter, and concept popover are replaced by the
  chat transcript. The card header keeps the "Ilustrácia N" label
  but swaps the state pill for a `Spoločná tvorba` pill (carrying
  the same spinner semantics as the other non-terminal pills) with
  a small `manual_attempts/MAX_MANUAL_ATTEMPTS` counter beneath
  (e.g. "Pokus 2 z 5"). On `COMPLETED` reached via manual confirmation,
  the chat collapses and the card renders as a standard completed
  card with the accepted image. On `FAILED` reached via budget
  exhaustion (`illustration_manual_ended.outcome="exhausted"`), the
  chat collapses and the card renders the standard FAILED card
  ("Túto ilustráciu sa nepodarilo vytvoriť.") — the apology turn
  Agent 6 produced is dropped from the user's view, because the
  rendered failure card carries the same message in a more familiar
  form. (Tests cover both paths.)

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

### 9.1A IllustrationCard chat takeover (§ 6A)

When an illustration enters any `MANUAL_*` state, the `IllustrationCard`
swaps its body to a `ManualChatPanel` component. The header (scene
number + state pill + attempt counter) stays visible above. Layout
rules:

- The chat occupies the card's natural width (no popout, no modal).
  It is **not** the same component as the home-screen chat
  (`ChatPanel.vue`); see § 9.1B for why a separate component exists.
- The transcript scrolls inside the card. Default height = the
  natural height of the image slot it replaces (the 1:1 skeleton's
  aspect-ratio box), so cards in the grid keep their footprint. The
  panel internally scrolls beyond that height; the card itself
  doesn't grow. The image-bubble rows ignore this clamp and expand
  the card vertically when present (the rendered image is the most
  important content in the chat).
- Bubble alignment, color, and typography mirror the home-screen
  chat for visual continuity (the user already knows the look from
  Screen A).
- The input area is a single-line auto-growing `<textarea>` plus a
  send button. Send is disabled while a request is in flight (the
  store tracks `isSendingManualMessage[illustration_id]`). The
  placeholder is sub-phase-dependent: when
  `manual_session.sub_phase === "concept_design"` the placeholder
  reads `i18n.t('illustration.manual.ui.input_placeholder_concept')`
  (e.g. "Popíš, ako by mal obrázok vyzerať…"); when
  `sub_phase === "feedback_gathering"` it reads
  `i18n.t('illustration.manual.ui.input_placeholder_feedback')`
  (e.g. "Povedz, čo na obrázku funguje a čo nie…"). The base
  `input_placeholder` key is removed.
- When state is `MANUAL_GENERATING_PROMPTS` or `MANUAL_RENDERING`,
  the input area is replaced by a centered indeterminate progress
  bar with the localized hint
  `i18n.t('illustration.manual.ui.rendering_hint')` (Slovak:
  "Vytváram obrázok podľa nášho konceptu…"). The user cannot type
  while a render is in flight — this prevents both a confused
  duplicate dispatch and a race between the user's next concept
  and the render result.
- Image bubbles render the manual render at full content-margin
  width with a small caption `"Pokus K"` (or localized equivalent).
  Click opens the original.
- The `#…#` bold marker in `illustration.manual.welcome` is rendered
  via a tiny helper (`splitBoldMarker`) that splits the string on
  `#`, alternates plain / `<strong>` spans, and asserts exactly one
  bold span in dev mode. The helper lives in
  `frontend/src/utils/manualBold.ts` and is unit-tested
  (§ 11.3 amendment).

When the manual flow ends:

- On `illustration_manual_ended.outcome="completed"`, the panel
  unmounts and the card re-renders as a standard completed card
  with the canonical image — the existing reactive switch on
  `illustration.state === "COMPLETED"` handles this with no extra
  code in the panel.
- On `outcome="exhausted"`, the panel unmounts and the card
  renders the FAILED card (existing path).
- On `outcome="cancelled"`, the panel unmounts and the card
  renders the CANCELLED card (existing path).

The `manual_session` data on each illustration is held on the
runStore (§ 9.2.2 amendment): `runStore.illustrationManualSessions:
Map<illustration_id, { messages, manual_attempts, last_image_url, sub_phase, last_agreed_concept }>`,
mutated in place by the SSE event handlers and re-initialized from
each `snapshot` event. `sub_phase` is updated locally on every
`manual_message_appended` / `manual_image_rendered` event (each
carries the post-event `sub_phase` value, see § 8.4) and on the
POST response and the snapshot, so all tabs converge on the same
affordances. The store also exposes a Promise-returning action
`runStore.sendManualMessage(illustration_id, content)` used by the
panel.

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
- `currentLanguage: 'sk' | 'cs' | 'en'` — the language of the
  translation snapshot currently materialized into `run` /
  `illustrations`. This is an **internal cache-key**, not a UI
  binding: the language switcher reads from
  `localeStore.currentLanguage` exclusively (§ 9.8). The two values
  are kept in sync by `localeStore.setLanguage` (switcher path) and
  by `RunView`'s `route.params.lang` watcher (URL path); see § 9.6.5.
- `pendingTranslationLanguages: Set<Language>` — languages currently
  being refreshed via § 8.9; used to de-duplicate concurrent
  switches.
- `pendingParagraphTranslations: Set<number>` — `paragraph_index`es
  currently included in an in-flight § 8.9 translation request.
  Populated by `ensureTranslations` immediately before the POST and
  cleared in its `finally` block. Only paragraphs actually being
  translated (i.e. those whose translation in the target language is
  `missing` or `stale`) are listed — already-cached paragraphs and
  source-language paragraphs are NOT included, so the per-paragraph
  skeleton only appears for text that genuinely cannot be served from
  Pinia or the DB yet. Drives `isParagraphTranslating(paragraphIndex)`.
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
     in-flight call. **`missing` paragraphs** instead swap to a
     per-paragraph skeleton (`StoryParagraph` reads
     `isParagraphTranslating`) so the user sees the text being
     fetched rather than a stale or empty paragraph. When the
     response arrives, write each item into `translations[language]`
     (and into the live `run` / `illustrations` view if the active
     language still matches).
  3. While the call is in flight, `pendingTranslationLanguages.add(language)`
     AND each in-flight paragraph index is added to
     `pendingParagraphTranslations`. The store ignores duplicate
     concurrent `switchLanguage(language)` calls for the same
     language. Both sets are cleared in the `finally` block, so the
     skeletons resolve into translated text in the same tick as the
     cache update.
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
- `isParagraphTranslating(paragraphIndex): boolean` — `true` iff
  `paragraphIndex` is in `pendingParagraphTranslations`. Drives the
  same `StoryParagraph` skeleton (logical OR with
  `isParagraphRegenerating`) for the duration of an Agent 5 call. The
  skeleton is per-paragraph and only covers the paragraphs whose
  translation is being fetched — paragraphs already present in the
  Pinia cache (or in the DB-backed snapshot) keep showing their text
  through the switch.
- `completedCount: number` — derived from
  `illustrations.filter(i => i.state === 'COMPLETED').length`. Used
  by `ProgressCounter` instead of `run.completed_count` because the
  backend pipeline only persists `runs.completed_count` to the DB at
  run termination (see § 7); any mid-run snapshot fetched via
  GET `/api/runs/:id` or rebuilt by the SSE endpoint therefore carries
  `0`. Deriving from the illustrations array (whose `state` IS updated
  per-illustration both in DB and via SSE) means the progress
  indicator stays consistent across language switches and SSE
  re-subscriptions during an active run.
- `failedCount: number` — derived analogously
  (`i.state === 'FAILED'`).
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
- `illustration_entity_updated` → finds the illustration by
  `illustration_id` and assigns
  `illustration.contains_entity_label = event.contains_entity_label`
  on the existing reactive object. The label is a plain string (or
  null), so field-level assignment is sufficient — the
  IllustrationCard's entity subtitle re-renders without remount. If
  the payload's `entity` is non-null, the store ALSO upserts the full
  record into `run.narrative_entities[]` (matched by normalised
  label), so inspectors or tooltips that read the register stay in
  sync. If the payload's `entity` is null and the label was dropped,
  the store does NOT remove the record from `run.narrative_entities[]`
  — the register is append-only on the frontend; ghost-reserved
  entities stay visible for debugging.
- `illustration_environment_updated` → finds the illustration by
  `illustration_id` and assigns `illustration.environment =
  event.environment` (a fresh `Environment` object — the inner fields
  are not bound separately). The store ALSO overwrites
  `run.environments[event.scene_index] = event.environment` so the
  top-level register stays consistent with the per-illustration
  view. The IllustrationCard's environment subtitle and the concept
  popover's environment line re-render without remount.
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
- `illustration_completed`, `illustration_failed` → flip the matching
  illustration's `state` (and `image_url` on completion). Progress
  counters are NOT incremented manually; they are derived from
  `illustrations[].state` via the `completedCount` / `failedCount`
  computed getters above, so the state flip is sufficient.
- `run_completed`, `run_failed`, `run_cancelled`, `heartbeat` — as
  previously specified. `run_completed` only flips `run.status`; the
  final completed/failed totals come from the derived getters.

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
  switcher), `toast`, and `illustration.manual` (§ 6A.7 keys —
  `welcome`, `summary_intro`, `render_failed`, `budget_exhausted`,
  `review_prompt`, `budget_remaining_hint`, and `ui.*` for the chat
  panel labels).
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

`setLanguage` is invoked only from in-app code paths: the language
switcher (§ 9.8) and the chat auto-switch (§ 9.6.6). For URL-driven
language changes — a direct visit to `/cs/runs/:id`, a bookmark, or
a browser back/forward step — the locale store is updated by the
router guard (`beforeEach`) and does **not** go through
`setLanguage`. The run store therefore has to be synced separately
on those paths:

- On initial mount, `RunView` reads `route.params.lang` and passes
  it as the `language` argument to `runStore.loadRun()` and
  `runStore.subscribe()` so the very first snapshot and SSE stream
  are fetched in the URL language.
- A watcher in `RunView` observes `route.params.lang` and calls
  `runStore.switchLanguage(newLang)` whenever it changes. This is a
  no-op when the change was triggered by the switcher (the value is
  already in sync at that point), and it handles back/forward and
  direct deep links uniformly.

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
  props `position="bottom-left"` and `rich-colors` enabled.
  The library's stylesheet (`vue-sonner/style.css`) is imported
  once in `main.ts` so toasts render with their built-in styling.
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

A small component **mounted exactly once in `App.vue`** and rendered
in the top-right of the centered page container on every screen
(no view re-renders the switcher inline). Implementation rules:

- **Single source of truth:** the switcher's displayed/active language
  is read from `localeStore.currentLanguage` **only**. It must NOT
  branch on `route.name` or read from the `runStore` for display
  purposes. The `runStore` exposes its own `currentLanguage` solely
  as a cache-key for "which translation snapshot is currently loaded"
  (§ 9.2.2) — that is an internal concern, not a UI binding. The two
  are kept in sync by `localeStore.setLanguage` (for switcher clicks)
  and by `RunView`'s route watcher (for direct URL navigation and
  browser back/forward), see § 9.6.5.
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
  true })` and closes the menu. The locale store is responsible for
  rewriting the URL, persisting to `localStorage`, and (when the
  active route is `/runs/:run_id`) cascading to `runStore.switchLanguage`.
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
| `MAX_MANUAL_ATTEMPTS`             | 5     | Total manual renders the user can request via the § 6A chat fallback before the illustration is force-FAILED. Counts each dispatched ComfyUI job, whether the render itself succeeded or failed. |
| `COMFYUI_POLL_TIMEOUT_S`          | 600   | Max wait per ComfyUI job                                          |
| `COMFYUI_POLL_INTERVAL_S`         | 3     | Polling interval                                                  |
| `MAX_CONCURRENT_BRANCHES`         | 5     | Async semaphore over branches (= MAX_ILLUSTRATIONS for MVP)       |
| `CLAUDE_JSON_RETRY`               | 2     | Re-prompts on Claude output JSON parse failure                    |
| `CHAT_MESSAGE_MAX_CHARS`          | 4000  | Hard limit on a single chat message                               |
| `CHAT_MESSAGES_MAX_PER_SESSION`   | 60    | Hard cap on total messages per session (refuse further input)     |
| `ANTHROPIC_MODEL`                 | `"claude-sonnet-4-6"` | Single model used for all 8 calls (chat, build_story, generate_prompts, evaluate_image, revise_prompts, rethink_concept, translate, manual_concept) |
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
  - Loads all nine `.md` files (chat, build_story, generate_prompts,
    evaluate_image, revise_prompts, rethink_concept, translate,
    manual_concept, manual_revise_prompts) from a temporary
    `AGENTS_DIR` fixture and exposes them on the Claude client.
  - Refuses to start (raises typed error) when any of the nine files
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

- **Agent 6 manual_concept** (`tests/unit/test_manual_concept.py`):
  - Schema validation accepts each of `gathering` /
    `awaiting_concept_confirmation` / `concept_confirmed` /
    `gathering_feedback` / `awaiting_feedback_confirmation` /
    `feedback_confirmed` / `restart_concept` / `accepted` and
    rejects unknown phase values.
  - Sub-phase ↔ phase compatibility: a `concept_confirmed` reply
    received while `sub_phase = "feedback_gathering"` is demoted
    to `gathering_feedback`; a `feedback_confirmed` reply while
    `sub_phase = "concept_design"` is demoted to `gathering`;
    likewise for the other cross-sub-phase combinations.
  - Verbatim concept handoff (§ 6A.2 rule #7, § 7.1 Call 6 rule 3):
    - On `awaiting_concept_confirmation`, the assertion that
      `concept_candidate` appears verbatim inside `reply` passes
      when the strings match and fails (treated as Claude failure
      and re-prompted) when they diverge by even one character.
    - On `concept_confirmed`, the assertion that
      `concept_candidate` equals the previous turn's
      `last_concept_candidate` byte-for-byte passes when identical
      and fails otherwise.
  - Server-side phase guards: a `concept_confirmed` reply with no
    prior `awaiting_concept_confirmation` in the manual session is
    demoted to `awaiting_concept_confirmation`. A `feedback_confirmed`
    reply with no prior `awaiting_feedback_confirmation` is demoted
    to `gathering_feedback`. An `accepted` reply that is not
    immediately preceded by an `image` row is demoted to
    `gathering_feedback`.
  - Feasibility heuristic flips obviously infeasible candidates
    (multi-character, multi-setting, "and then …") to `gathering`.
  - `restart_concept` resets the session: `last_agreed_concept`
    and `last_manual_image_path` are cleared, `sub_phase` flips to
    `concept_design`, `manual_attempts` is unchanged.
  - Post-image user-message slicing (§ 6A.4 step 5.2): given a
    fixture transcript with multiple `user`, `assistant`, and
    `image` rows, the slicer returns exactly the `user` rows
    created after the most recent `image` row, joined by newlines,
    with no agent paraphrasing in between.
  - Budget arithmetic: after `MAX_MANUAL_ATTEMPTS` renders, the
    next `concept_confirmed` *or* `feedback_confirmed` turn
    force-FAILs the illustration and emits the apology bubble +
    `illustration_manual_ended(outcome=exhausted)`.

- **Agent 7 manual_revise_prompts**
  (`tests/unit/test_manual_revise_prompts.py`):
  - Schema validation: the output schema accepts a `{positive,
    negative}` pair and rejects extra fields (no `workflow`, no
    `reply`, no `concept_candidate`).
  - The Anthropic system prompt sent to Claude equals
    `manual_revise_prompts.md` verbatim (intercepted with respx).
  - Input plumbing: given a stub Agent 7 that echoes its inputs,
    the dispatch in § 6A.4 step 5 passes the correct
    `last_agreed_concept`, the correct `user_feedback` blob (the
    post-image user-message slice), the **most recent**
    `last_positive_prompt` / `last_negative_prompt` (i.e. the
    revised prompts from the previous iteration, not the
    originals), and the unchanged `style_guide` /
    `character_role` / `companion`.
  - Negative-prompt baseline (§ 7.3.6) survives revision: a
    stub Agent 7 that drops the baseline causes the dispatch to
    treat the call as a Claude failure and re-prompt up to
    `CLAUDE_JSON_RETRY` times (the server reasserts the baseline
    invariants on Agent 7's output the same way it does for
    Agent 1 / Agent 3).
  - Workflow choice cannot toggle: even if Agent 7's output
    somehow implied a different cast shape, the dispatch reuses
    `illustrations.current_workflow` (it never re-reads any
    workflow hint from Agent 7's output).

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
- **Manual flow happy path (§ 6A):** mock auto-pipeline failure for
  one illustration → assert transition to `MANUAL_CHATTING` and the
  `illustration_manual_started` event with the welcome bubble. Send
  two user messages (gathering → awaiting_confirmation → confirmed)
  with Agent 6 mocked; assert Agent 1 + RunPod are dispatched on
  the confirmed turn; assert `MANUAL_RENDERING` → `MANUAL_CHATTING`
  with an `image` row appended and the `review_prompt` bubble after
  it. Send an "accepted" reply; assert promotion to `COMPLETED`,
  canonical `image_path` set, and `illustration_completed` emitted
  with the canonical URL. Assert `runs.completed_count` increments.
- **Manual flow exhaustion (§ 6A):** drive 5 confirmed → render
  iterations without ever sending `accepted`. Assert the 6th
  confirmed turn force-FAILs the illustration, emits the apology
  bubble, and emits `illustration_manual_ended(outcome=exhausted)`.
  POSTing to § 8.10.1 afterwards returns 409.
- **Manual flow cancellation:** with an illustration in
  `MANUAL_CHATTING`, POST `/cancel`. Assert the illustration
  transitions to `CANCELLED`, emits `illustration_manual_ended
  (outcome=cancelled)`, and that subsequent POSTs to § 8.10.1
  return 409.
- **Manual flow render failure budget:** mock RunPod to raise
  during a manual render. Assert `manual_attempts` is still
  incremented (the attempt is consumed), the user receives the
  `manual.render_failed` bubble, and the branch returns to
  `MANUAL_CHATTING` with the remaining budget intact.

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
  - The "active" row (check glyph and active styling) is driven by
    `localeStore.currentLanguage` on every route — mounting the
    switcher on `/cs/runs/:id` while the runStore is empty (or while
    its internal `currentLanguage` is still `sk`) still shows `cs`
    as active.
  - Clicking a non-active item invokes `localeStore.setLanguage(code,
    { silent: true })` exactly once and closes the menu.
  - Clicking the active item is a no-op (the menu still closes).
  - Selecting a language manually sets
    `localeStore.languageLockedByUser = true`.
  - The trigger button has the accessibility attributes specified
    in § 9.8 (`aria-haspopup`, `aria-expanded`, `aria-label`).
  - The switcher is mounted exactly once (in `App.vue`); no view
    template imports or renders it directly.
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
- **RunView URL-lang sync (§ 9.6.5):**
  - Mounting `RunView` at `/cs/runs/:id` calls `runStore.loadRun(id,
    'cs')` and `runStore.subscribe(id, 'cs')` exactly once (the `cs`
    argument is taken from `route.params.lang`, not from any store
    default).
  - Changing `route.params.lang` from `cs` to `sk` (without going
    through the switcher — e.g. simulated `router.replace`) invokes
    `runStore.switchLanguage('sk')` exactly once.
  - A switcher click on `/cs/runs/:id` results in exactly one
    `runStore.switchLanguage` call (the route-watcher path is a
    no-op after the locale store has already cascaded).
- **ManualChatPanel (§ 9.1A, § 6A):**
  - Renders the welcome message with exactly one `<strong>` span
    when `illustration.manual.welcome` contains a single `#…#`
    bold marker (via the `splitBoldMarker` helper).
  - Does NOT render the welcome bubble when `manual_session.messages`
    is non-empty (i.e. it has already been persisted by the
    backend) — i.e. the welcome bubble is read from the backend
    transcript, not synthesized client-side.
  - The send button and `<textarea>` are disabled while
    `runStore.isSendingManualMessage[illustration_id]` is true.
  - During `MANUAL_GENERATING_PROMPTS` and `MANUAL_RENDERING`,
    the input area is replaced by the indeterminate progress bar
    + `illustration.manual.ui.rendering_hint`.
  - After `manual_image_rendered`, the next two bubbles are
    (a) an image bubble whose `<img>` src equals the event's
    `image_url`, (b) an assistant bubble carrying the
    `review_message.content` text. The panel also updates
    `manual_session.sub_phase` to `feedback_gathering` from the
    event payload.
  - Sub-phase-dependent input placeholder (§ 9.1A): when
    `manual_session.sub_phase === "concept_design"` the input
    `placeholder` attribute equals
    `i18n.t('illustration.manual.ui.input_placeholder_concept')`;
    when it equals `"feedback_gathering"` the placeholder equals
    `i18n.t('illustration.manual.ui.input_placeholder_feedback')`.
    A `manual_message_appended` event whose `phase` is
    `restart_concept` flips the placeholder back to the concept
    one on the next render tick.
  - On `illustration_manual_ended(outcome=completed)` the panel
    unmounts and the card reverts to the standard completed
    layout. On `outcome=exhausted` it unmounts and the FAILED
    card is rendered (existing path). On `outcome=cancelled` it
    unmounts and the CANCELLED card is rendered.
- **`splitBoldMarker` utility:** unit tests for the `#…#`-parsing
  helper (zero, one, two markers; empty string; nested `#`
  rejected with a clear error in dev mode).

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
