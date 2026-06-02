# Technical Decisions

This document records key technical and library choices made during development.

---

## Flag Icons Library (2026-05-26)

**Decision**: Use `country-flag-icons` npm package for displaying country flags in the language switcher.

**Rationale**:
- **Lightweight**: Tree-shakeable - we only import the 3 flags we need (SK, CZ, GB)
- **Modern**: Actively maintained, works with modern bundlers
- **Format**: SVG-based with data URLs - no separate image files needed
- **Framework-agnostic**: Works seamlessly with Vue 3
- **Small bundle impact**: Only ~1-2KB per flag icon with tree shaking

**Implementation**:
- Import individual flag SVGs: `import SK from 'country-flag-icons/string/3x2/SK'`
- Display in `LanguageSwitcher.vue` component
- Show flags in both the button (instead of language codes) and dropdown menu items

**Alternatives considered**:
- `flag-icons` - CSS-based, widely used but larger bundle size
- `vue-flags` - Vue-specific but adds unnecessary abstraction
- Unicode emoji flags - Zero dependencies but inconsistent rendering across platforms

**References**:
- npm: https://www.npmjs.com/package/country-flag-icons
- GitHub: https://github.com/catamphetamine/country-flag-icons

---

## Reactive i18n Implementation (2026-05-26)

**Decision**: All user-visible text in the frontend must be reactive to language changes, using Vue computed properties or direct template `$t()` calls that automatically react to `i18n.global.locale` changes.

**Problem**:
When users switch languages via the LanguageSwitcher, some text remained in the original language:
- App title and intro text (hardcoded in Slovak)
- Welcome message (captured once at session start, not reactive)
- LanguageSwitcher display (not updating to show current selection)

**Solution**:
1. **Template text**: Use `$t()` directly in templates - automatically reactive to locale changes
2. **Computed text**: For text used in script logic, use `computed(() => t('key'))` - recomputes when locale changes
3. **Store messages**: Dynamic messages (like welcome) should be computed properties or regenerated on language change
4. **No hardcoded text**: All user-visible strings must come from locale files (`sk.ts`, `cs.ts`, `en.ts`)

**Implementation pattern**:
```vue
<template>
  <!-- Reactive - automatically updates when locale changes -->
  <h1>{{ $t('app.title') }}</h1>
  <p>{{ $t('app.intro') }}</p>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// For script use - also reactive
const dynamicMessage = computed(() => t('some.key'))
</script>
```

**Affected components**:
- `HomeView.vue` - app title and intro text
- `RunView.vue` - "New story" link and page title
- `session.ts` store - welcome message must be computed
- `LanguageSwitcher.vue` - must show current language reactively

**Note**: The `i18n.global.locale` is a reactive ref, so any template `$t()` call or `computed(() => t())` automatically updates when the locale changes via `localeStore.setLanguage()`.

---

## Unified Story View — Loading & Loaded States (2026-05-27)

**Decision**: Render the story-generation loading state and the live run state through a single, structurally identical view. Loading is just one of several states the view describes; it must not be a separate, divergent component tree.

### Problem

The current loading screen (`StorySkeletonLoader.vue`, shown from `HomeView.vue` while `isFinalizing && topicShort`) is structurally and visually disconnected from the destination view (`RunView.vue` / `StoryView.vue`):

- Centered italic single-line "Creating story…" text — no header, no status pill, no progress affordance.
- Five plain rectangles (80 px each) — they do not mirror the paragraph+illustration rhythm that follows.
- A second orphan component (`StoryBuildingSkeleton.vue`) was prototyped but never wired up.
- The transition from "loading" to "run page" feels like navigating to a different product: title, status pill, progress indicator, and illustration cards all appear at once with no continuity of layout.

This breaks the perceived-performance contract a skeleton is meant to honor: the placeholder should occupy the same shape the real content will occupy, so the eye does not re-acquire the layout on swap.

### Solution overview

1. **Promote `RunView` to handle the pre-run "building" phase as well.** During the brief window between session finalize (POST `/sessions/:id/finalize`) and the first SSE snapshot, the page already shows the run view scaffold, populated from local state (`session.topicShort`).
2. **Drive the difference with a single boolean** — `loading` (true while the run object has not yet been materialised; false once `store.run` is present). The template branches only at the leaves (status pill content, progress bar fill, paragraph/illustration body), not at the page level.
3. **Reuse existing contextual skeletons** (`SkeletonBlock shape="text"` for paragraphs, a new card-shaped sibling for illustrations) so placeholder rhythm exactly matches the real `StoryView` layout — same gap, same max-width, same horizontal padding, same vertical spacing between paragraphs and illustration slots.
4. **Delete `StorySkeletonLoader.vue` and the orphan `StoryBuildingSkeleton.vue`.** Neither will have a remaining caller after the refactor.

### View structure (loading ↔ loaded parity)

The page shell is identical in both states. Only the highlighted slots vary.

| Slot              | Loading state                                                                                     | Loaded state                                                                |
| ----------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `<h1>` title      | `session.topicShort` (the short topic phrase from the finalize response)                          | `store.run.story_title`                                                     |
| Status pill       | Spinner glyph + `$t('story.building')` ("Generating…", localised)                                 | Existing `statusLabel` + spinner only when `status === 'RUNNING'`           |
| Progress label    | `$t('story.building_progress_label')` (e.g. "Preparing illustrations…") — same line height/margin | Existing "Completed: X of Y"                                                |
| Progress bar      | Same-dimensions gray rail with an indeterminate CSS keyframe (sliding accent), no determinate fill | Existing green determinate fill                                             |
| Cancel button     | Hidden (no run id to cancel yet)                                                                  | As today                                                                    |
| Body              | 5 × paragraph skeleton (`SkeletonBlock shape="text" :lines="4"`) interleaved with 5 × full-card illustration skeleton, in the natural paragraph→illustration order | `<StoryView>` with real `StoryParagraph` + `IllustrationCard`               |

Header, pill, progress label, and progress bar must keep identical box metrics across the two states so the swap is visually a fade-in of content, not a re-layout.

### Component plan

- **`RunView.vue`** becomes the entry point for both the building phase and the run phase. Routing change: after `sendMessage` returns a `run_id`, `HomeView` navigates to `/runs/:run_id` immediately (as today), but `RunView` tolerates `store.run === null` by rendering the loading variant seeded from `session.topicShort` (read via `useSessionStore`, kept alive across the navigation by Pinia).
- **`StoryView.vue`** gains a `loading: boolean` prop (default `false`). When `true`, it renders a fixed array of 5 placeholder paragraph/illustration pairs instead of iterating `blocks`. The container element, gap, and max-width stay identical to the loaded state.
- **`ProgressCounter.vue`** keeps responsibility for the determinate bar. A new sibling **`IndeterminateProgress.vue`** renders the loading variant. Both share the `.progress-bar` dimensions (6 px height, full width, `#e0e0e0` rail, 3 px radius); the indeterminate component overlays a 30 %-wide accent stripe (`#4caf50`) animated `translateX(-100%) → translateX(333%)` on a 1.4 s linear loop. Extracting the shared rail into a tiny base mixin/SCSS partial is acceptable but optional — the contract is "identical dimensions and rail color", not "shared DOM".
  - Rationale for two components rather than a `mode` prop: each component has zero conditionals and its CSS animation is independent. A `mode` prop would force a runtime branch on what is effectively two static visuals.
- **Illustration skeleton**: extend the body rendering inside `StoryView` (loading branch) to drop a `SkeletonBlock shape="rect" aspect-ratio="1 / 1"` wrapped in the existing `.story-illustration` container. No `IllustrationCard` chrome (no border, no "Illustration N" header, no excerpt) — only the bare skeleton occupying the same 560 px-max centered slot. Reuse `SkeletonBlock` directly; do **not** introduce a new `IllustrationSkeleton.vue` wrapper for this single use.
- **Paragraph skeleton**: `SkeletonBlock shape="text" :lines="4"`, rendered inside a `.story-paragraph` wrapper so margins match real paragraphs. The existing `min-height` on the real `.story-paragraph` (none today) must remain absent so paragraphs reflow naturally once text arrives — the current `StoryParagraph` already swaps skeleton → text with no fixed height, so this constraint is satisfied for free; the rule is documented to prevent future regressions.
- **`StorySkeletonLoader.vue` and `StoryBuildingSkeleton.vue`** are deleted. `HomeView.vue` loses the `v-if isFinalizing && topicShort` branch and always renders the chat panel until navigation occurs.

### Loading-state lifecycle

1. User confirms in chat → `sendMessage` resolves with `run_id` and `topicShort` is set on the session store.
2. `HomeView` navigates to `/runs/:run_id`.
3. `RunView` mounts. `store.run` is `null`; `loading` is `true`. It renders the unified scaffold using `sessionStore.topicShort` for the `<h1>`, the indeterminate progress bar, and `StoryView :loading="true"`.
4. `store.subscribe()` opens SSE. The first snapshot populates `store.run`; `loading` flips to `false`. The header text changes (topic → real `story_title`), the status pill switches to its `RUNNING` styling, the progress bar swaps to determinate, and the body skeletons swap to real `StoryParagraph` + `IllustrationCard` rows.
5. Because the page shell never re-mounts, the swap is per-slot and the layout does not jump.

### Refresh resilience

Because navigation to `/runs/:run_id` happens the instant `finalize` returns — before any story content exists — the user can refresh the browser at any moment during generation and land on the same URL. The run row is persisted in the DB by the finalize handler before it responds, so `RunView.onMounted` always finds it via `store.loadRun(runId)` (or via the SSE-from-DB fallback for runs whose in-memory bus is gone after an uvicorn reload, per the existing snapshot-rebuild behavior).

The only piece of state that does not survive a refresh is `sessionStore.topicShort` (Pinia in-memory, scoped to the originating chat session). For the brief window between mount and the first SSE snapshot, the `<h1>` would otherwise be empty.

**Resolution**: the title falls back through a three-step chain:

```
store.run?.story_title  ??  sessionStore.topicShort  ??  $t('story.building')
```

- Normal flow (no refresh): `topicShort` is present immediately, so the heading shows the topic until the real title arrives.
- After refresh: both run-derived values are briefly absent, so the heading shows the localised "Generating story…" placeholder until `loadRun` / SSE populate `story_title`.
- Once loaded, the chain naturally resolves to `story_title` and stays there.

This keeps the `<h1>` non-empty at every frame, with no need to persist `topicShort` to `localStorage` or to round-trip it through the run API.

### i18n additions

New keys in `frontend/src/i18n/locales/{sk,cs,en}.ts`:

- `story.building` — already exists (used today by the orphan); keep it for the status pill label **and** as the `<h1>` fallback on refresh.
- `story.building_progress_label` — new, e.g. EN "Preparing your illustrations…", SK "Pripravujem ilustrácie…", CS "Připravuji ilustrace…". Sits in the same line position as the determinate counter.

The existing `story.building_with_topic` becomes redundant (the topic now lives in the `<h1>`, not in the loading sentence) and is removed in the same change.

### Acceptance criteria

- Removing `StorySkeletonLoader.vue` and `StoryBuildingSkeleton.vue` leaves no broken imports (verified by `npm run type-check` and `npm run lint`).
- Switching between `loading=true` and `loading=false` in `RunView` does **not** change the bounding box of `<h1>`, the status pill, or the progress bar (visually verifiable; can be asserted in a Vitest DOM test by comparing computed heights of those nodes across the two render branches).
- Paragraph and illustration skeletons render inside the same `.story` container, with the same gap and max-width, and at the same horizontal position as real paragraphs/cards.
- The indeterminate progress bar uses the same rail color (`#e0e0e0`), height (6 px), and width (100 % of `.progress-counter`) as the determinate one. The animated accent uses the same green (`#4caf50`).
- No new locale strings are missing from any of the three locale files (Vitest snapshot or a small key-parity test).
- The body skeleton consists of exactly 5 paragraphs (each 4 lines) interleaved with 5 illustration card-sized placeholders, ordered paragraph → illustration → paragraph → illustration → ….

### Out of scope

- Animating the swap from loading to loaded (cross-fade etc.). The structural parity already eliminates the layout jump; motion polish can come later.
- Reworking the chat→home transition or `HomeView` styling.
- Changing the SSE / store contract — `topicShort` is already produced by finalize and persisted in `useSessionStore`.

---

## Backend hosting on Fly.io (2026-06-01)

**Decision**: Host the FastAPI backend on a single pinned Fly.io
Machine in the `fra` region.

**Rationale**:
- **In-process orchestrator**: the branch-per-illustration asyncio
  fan-out lives inside the uvicorn worker, with the SSE event bus
  and cancel flags held in module-level dicts. Horizontally
  scaling would mean serialising both, which is an order of
  magnitude more work than the demo justifies.
- **Persistent volume**: SQLite database + ComfyUI workflow JSONs
  + (until R2 was added) image bytes need durable storage between
  deploys. Fly's `/data` volume gives us that without an external
  database service.
- **Cheap idle cost**: the demo is bursty (long generation
  sessions, then days of silence). Fly Machines on a single-CPU
  shared-cpu-1x VM are cents-per-month at idle.
- **`auto_stop_machines=false`**: the orchestrator is in-process,
  so suspending the machine mid-pipeline would lose every branch.
  Keeping it always-on is cheaper than the engineering work to
  make the pipeline restart-safe at the orchestrator level (the
  startup orphan resumer in § 8.8.1 of `SPECIFICATION.md` only
  recovers in-flight *RunPod* jobs, not in-flight Claude calls).

**Implementation**:
- `backend/Dockerfile` — multi-stage, non-root user, `urllib`
  HEALTHCHECK against `/health`.
- `backend/fly.toml` — `app = "anime-illustrator-api"`, volume
  mounted at `/data`, single machine pinned, `auto_stop_machines
  = false`, `min_machines_running = 1`.
- `app/main.py` exposes `/health` (cheap, no DB roundtrip) used
  by both the Fly healthcheck and the GitHub Actions deploy
  smoke-test.
- VM size: `shared-cpu-1x` with **1 GB RAM** (raised from the
  default 256 MB — see *VM memory sizing* below).

**Alternatives considered**:
- **Render / Railway**: equivalent ergonomics, slightly worse
  cold-start, no Fly Machines API for the deploy step.
- **Self-host on a VPS**: cheaper at idle but requires hand-rolled
  TLS, healthcheck-driven restart, and OS upgrades. Demo is not
  worth the maintenance tax.
- **Kubernetes / ECS**: massive overkill for a single-machine
  in-process orchestrator.

---

## Frontend hosting on Cloudflare Pages (2026-06-01)

**Decision**: Host the Vite-built Vue SPA on Cloudflare Pages with
a `_redirects` file proxying `/static/*` to the Fly backend.

**Rationale**:
- **Free tier suffices**: the demo's traffic is negligible vs.
  the Pages free quota.
- **Static asset proxy**: Pages's `_redirects` file lets us serve
  rendered illustrations from the same origin as the SPA without
  CORS headaches. Even after R2 was introduced, the same
  mechanism transparently routes any legacy `/static/...` URLs
  still in the DB to the Fly backend.
- **SPA fallback**: `_redirects` also handles the vue-router
  history-mode catch-all (`/* /index.html 200`), so deep links
  like `/sk/runs/<id>` survive a hard refresh.
- **CI integration**: `cloudflare/wrangler-action@v3` lets the
  same GitHub Actions workflow that deploys the backend also
  deploy the frontend, gated on the same green-CI invariant.

**Implementation**:
- `frontend/public/_redirects`:
  ```
  /static/*  https://anime-illustrator-api.fly.dev/static/:splat  200
  /*         /index.html                                          200
  ```
- `VITE_API_BASE` is **baked at build time** by the GitHub
  Actions workflow (`VITE_API_BASE: https://anime-illustrator-api.fly.dev`).
  `api.ts` falls back to `http://localhost:8000` only when the
  build-time env var is empty — i.e. for local dev. The
  build-time injection means we do **not** rely on
  `frontend/.env.production` being checked in.
- `.wrangler/` is a local cache, gitignored.

**Alternatives considered**:
- **Vercel**: equivalent, but the team is already on Cloudflare
  for DNS + R2; one fewer vendor is one fewer dashboard.
- **GitHub Pages**: no `_redirects` equivalent, no env-var
  injection at build time.
- **Same-origin serving from Fly**: would force the SPA to share
  the Fly machine's CPU + RAM and cap concurrency. No upside.

---

## Image storage on Cloudflare R2 (2026-06-01)

**Decision**: Persist all illustration PNGs (canonical, per-attempt
history, manual flow) on Cloudflare R2 instead of the Fly volume,
selected via the `IMAGE_STORE_BACKEND` env var.

**Rationale**:
- **Volume durability vs. cost**: Fly volumes are SSD-priced; the
  bytes are write-once, read-many static images that R2 stores at
  egress-free rates orders of magnitude cheaper.
- **No egress fees**: R2 to Cloudflare Pages is on-network, so
  serving the illustrations costs nothing per request.
- **Portable DB**: storing only logical keys
  (`runs/<run_id>/scene_N.png`) means a backend switch is a
  config flip + byte copy, not a schema migration. The DB row is
  the canonical pointer; the public URL is derived by the
  configured `ImageStore` at read time.

**Implementation**:
- `app/services/storage.py` — `ImageStore` Protocol,
  `LocalImageStore`, `R2ImageStore`, `get_image_store(settings)`
  factory.
- Required secrets when `IMAGE_STORE_BACKEND=r2`:
  `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
  `R2_BUCKET`, `R2_PUBLIC_BASE`, `R2_PREFIX` (default `dev`),
  `R2_JURISDICTION` (default `default`).
- `aioboto3>=13.0` as a mandatory runtime dep (top-level import in
  `storage.py` rather than an optional one — avoids the "optional
  import drift" footgun where Fly deploys fail because the dep
  wasn't pinned).

**Alternatives considered**:
- **S3**: equivalent API but ~10× cost with egress fees.
- **Backblaze B2**: cheaper than S3 but adds a third vendor.
- **Keep on Fly volume**: simplest, but breaks on volume
  migration and ties image lifetime to backend deploy.

---

## R2 EU jurisdiction support (2026-06-02)

**Decision**: Make the R2 endpoint URL configurable via a
`R2_JURISDICTION` setting (`default` or `eu`).

**Problem**: Buckets created in Cloudflare's EU jurisdiction
(`anime-illustrator-images` is one) must be accessed via
`https://<account_id>.eu.r2.cloudflarestorage.com`. Hitting the
default endpoint (`<account_id>.r2.cloudflarestorage.com`) for an
EU bucket returns `403 AccessDenied` **even with a correctly
scoped Object Read+Write token** — the error is indistinguishable
from a permissions problem, which cost real diagnostic time.

**Implementation**:
- `R2_JURISDICTION` env var consumed in `app/services/storage.py`
  when constructing the boto3 endpoint URL.
- Diagnostic probe at `/tmp/claude/r2_probe.py` (not committed —
  one-shot debug tool) tests `HeadBucket`/`PutObject`/`GetObject`/
  `DeleteObject` across endpoint × addressing-style combinations
  so a future "AccessDenied" can be narrowed to jurisdiction vs.
  ACL in minutes.

**References**:
- Cloudflare R2 jurisdictional endpoints docs:
  https://developers.cloudflare.com/r2/reference/data-location/

---

## CI/CD pipeline (2026-06-01)

**Decision**: Three CI workflows + one deploy workflow in
`.github/workflows/`, all gated on the same green-SHA invariant
before deploy can fire.

**Rationale**:
- **Separation of concerns**: `backend-ci.yml`, `frontend-ci.yml`,
  and `security.yml` each fail-fast on their own concern and can
  be retried independently. `deploy.yml` only consumes their
  status.
- **Single deploy step for both surfaces**: one workflow flips
  both backend (Fly) and frontend (Cloudflare Pages) so they
  never drift in production from a half-deploy.

**Implementation**:
- `backend-ci.yml` — `ruff check` + `ruff format --check` +
  `pytest -q`.
- `frontend-ci.yml` — `eslint` + `vue-tsc --noEmit` + `vitest run`.
- `security.yml` — gitleaks (secret scan), `pip-audit --strict`
  (Python deps), `npm audit` (JS deps), CodeQL (Python + TS),
  Trivy SARIF (container image).
- `deploy.yml` — waits for the three CI workflows to be green for
  the **same SHA**, then runs `flyctl deploy` for the backend
  with `--ha=false` (single-machine) and `wrangler-action` for
  the frontend with `VITE_API_BASE` injected at build time.
  Smoke-tests `/health` on the freshly deployed backend before
  reporting success.

**Alternatives considered**:
- **One mega-workflow**: easier to read end-to-end, but a flaky
  npm-audit run would block backend deploys for no reason.
- **Self-hosted runners**: zero upside for this workload, all
  downsides (maintenance, secrets surface).

---

## VM memory sizing — 1 GB (2026-06-02)

**Decision**: Run the Fly Machine at **1 GB RAM** instead of the
default 256 MB.

**Problem**: With 256 MB, the orchestrator's 5 concurrent branches
each holding a Claude HTTP client + an SSE EventBus + Python
import overhead reliably OOM-killed mid-pipeline. The kernel
dropped the uvicorn worker around scene 3–4, leaving runs stuck
in `RUNNING` forever (this is exactly the failure mode the
startup orphan resumer was built to recover from — but recovery
is not a substitute for not dying).

**Rationale**:
- **Cheaper than the engineering**: the price delta on a shared-CPU
  Fly Machine between 256 MB and 1 GB is small enough that
  re-architecting the orchestrator to stream branches instead of
  fanning them out would cost more in engineering time than the
  RAM bill saves in a year of demo use.
- **Headroom for R2 client**: `aioboto3` is not lean. With R2 in
  the picture even idle workers sit around 200–300 MB.

**Implementation**: `backend/fly.toml` sets `memory = "1gb"`.

---

## uvicorn `--timeout-graceful-shutdown 5` (2026-06-02)

**Decision**: Cap the graceful-shutdown window when uvicorn
reloads.

**Problem**: When uvicorn's `--reload` triggers a worker recycle
during an in-flight Claude / RunPod call **or** with an open SSE
stream, the worker enters
`Waiting for connections to close. (CTRL+C to force quit)`
indefinitely. Any new request that arrives during that window
(e.g. a manual-chat `POST` to
`/api/illustrations/{id}/manual/messages`) infinite-pends in the
browser. Developer experience cratered.

**Rationale**:
- 5 s is short enough that a stuck reload aborts before the
  developer notices, long enough that "clean" in-flight HTTP
  requests usually finish.
- SSE clients are designed to reconnect on disconnect anyway —
  forcing them to do so on reload is correct behaviour.

**Implementation**: `backend/Makefile`'s `serve-bg` target invokes
uvicorn with `--reload --timeout-graceful-shutdown 5`. In
production (Dockerfile / fly.toml) `--reload` is never set, so
the flag is dev-only.

---

## Schema management via Alembic (2026-05-30)

**Decision**: All schema changes go through Alembic migrations
(`backend/alembic/versions/`); `Base.metadata.create_all` is
**not** called in production.

**Rationale**:
- **Reproducibility across environments**: the Fly volume's
  `app.db` carries production schema; the test fixtures use a
  per-test temp DB; the local dev DB lives in `backend/data/`.
  All three exercise the same DDL path
  (`command.upgrade(cfg, "head")`) so a schema mismatch between
  environments cannot ship green.
- **Forward-only history**: every model change pairs with a
  versioned migration file checked into git. Reviewable in PRs,
  rollback-able if needed.
- **Catches "forgot to migrate"**: a unit test
  (`tests/unit/test_migrations.py::test_models_match_latest_migration`)
  runs `alembic revision --autogenerate` against the live models
  and asserts the result has no pending ops. CI fails loudly if a
  developer changes a model without generating a migration.

**Implementation**:
- `backend/alembic.ini` + `backend/alembic/env.py` (sync +
  `aiosqlite` async paths, `render_as_batch=True` for SQLite
  ALTER TABLE).
- `app/db/migrations.py` exposes `upgrade_to_head_async(url)`
  which the FastAPI lifespan invokes before `init_db()`. Required
  because `env.py` calls `asyncio.run()` internally for async
  URLs, which would conflict with the running event loop.
- `make migrate` and `make revision msg="..."` Makefile targets.

**Alternatives considered**:
- **`create_all` at startup**: drift-prone, can't subtract
  columns or rename, no record of when changes happened.
- **Hand-rolled SQL scripts**: equivalent to Alembic but without
  the autogenerate scaffolding or the model-drift guard test.

---

## Access-key gating (2026-06-01)

**Decision**: Gate every paid endpoint (Anthropic or RunPod spend)
behind a single `X-Access-Key` FastAPI dependency, with per-key
finalize-run quota and an automatic refund on infrastructure
failure.

**Rationale**:
- **Cost ceiling for a public demo**: the dominant risk is a
  stranger discovering the URL and burning the Anthropic/RunPod
  budget. A 32-char URL-safe key gates the entry point; a
  per-key quota counted in *finalized runs* caps spend even from
  a friend who got over-eager.
- **No real identity**: OAuth/magic-link/email-verification is
  more product than this demo can justify. An opaque key in
  `localStorage` + a `?invite=<key>` bootstrap link covers the
  share flow without a user table.
- **Refund is fair**: when a run terminates purely because of
  infra noise (RunPod timeout, queue exhaustion, orphan reap),
  the user's quota is credited back exactly once — guarded by a
  `runs.quota_refunded` boolean so concurrent failure paths
  collapse to a single refund.

**Implementation**:
- Single dependency `require_access_key` in `app/api/auth.py`,
  mounted on the canonical `PAID_ENDPOINTS` tuple
  (`app/constants.py`). A coverage test enumerates the live
  FastAPI router and fails loudly if a paid endpoint lacks the
  guard.
- `access_keys` table with `key`, `label`, `runs_allowed` (NULL
  for admin/unlimited), `runs_used`, `last_used_at`,
  `revoked_at`.
- Admin CLI `python -m app.cli.grant --label "..." --max N`
  mints keys and prints a shareable
  `https://anime-illustrator.pages.dev/?invite=<key>` URL.
- See `SPECIFICATION.md` § 8.11 for the full contract.

**Alternatives considered**:
- **JWT / session auth**: introduces a login surface and a user
  identity model the demo doesn't need.
- **Per-IP rate limiting only**: easily defeated by NAT or a VPN;
  the demo's threat model is "stranger spending my money", not
  "user spamming themselves", which an IP cap addresses badly.

---

## Single-machine pinning + startup orphan resumer (2026-06-02)

**Decision**: Run exactly one Fly Machine (no horizontal scaling)
and handle process restarts via a startup classifier that
re-attaches to in-flight RunPod jobs rather than restarting from
scratch.

**Rationale**:
- **In-process orchestrator simplicity**: branches are asyncio
  tasks under a single uvicorn worker; the `EventBus` and
  `cancel_flags` are module-level dicts. Making them survive
  horizontal scaling would mean broker (Redis pubsub or
  equivalent) + sticky-session SSE + a distributed cancel flag.
  All real engineering, all uninteresting for a demo.
- **Restart recovery is cheap**: the dominant failure case is a
  deploy or an OOM, not a partition. As long as a single process
  comes back up and can re-read the DB, the in-flight RunPod
  jobs (which are stored under their `job_id` on the GPU side
  and now also on `illustrations.runpod_job_id`) can be
  re-polled without losing FIFO position.
- **Cost transparency**: one machine = one bill line.

**Implementation**:
- `backend/fly.toml`: `auto_stop_machines = false`,
  `min_machines_running = 1`, deploy with `--ha=false`.
- `app/orchestrator/resume.py::resume_orphan_runs` runs in the
  FastAPI lifespan after the RunPod and ImageStore clients are
  wired. Classifies every non-terminal illustration under every
  `RUNNING` run into resumable / user-resumable / orphan, then
  detaches background tasks to re-attach to the live RunPod
  jobs and reaps the rest with `error_code = OOM_REAPED`.
- See `SPECIFICATION.md` § 8.8.1 for the four-bucket classifier
  and § 7.2 for `poll_existing_job` / `get_status`.

**Alternatives considered**:
- **Persist the orchestrator to a queue (Celery / Arq / SQS)**:
  the right answer for a non-demo. Too much surface area to
  justify here.
- **Re-run the whole branch from scratch on restart**: would
  burn Claude budget on attempts the user has already paid for
  and would lose FIFO queue position on already-submitted GPU
  jobs.
