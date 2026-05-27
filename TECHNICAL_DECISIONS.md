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
