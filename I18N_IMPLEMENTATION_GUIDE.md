# i18n Implementation Guide

## Progress Summary

### ✅ Completed (Phase 1 - Foundation)

**Backend:**
- ✅ Updated `constants.py`: `SUPPORTED_LANGUAGES`, `CONFIRMED_ACK` map
- ✅ Updated models: added `source_language`, `topic_short`, `story_topic_description`, nullable `character_role`, `current_workflow`
- ✅ Created translation models: `StoryTranslation`, `StoryBlockTranslation`, `IllustrationConceptTranslation`
- ✅ Generated Alembic migration: `f3dec31ba972_add_i18n_fields_and_translation_tables.py`
- ✅ Created Agent 5 translate prompt: `agents/translate.md`
- ✅ Updated Claude schemas: added `language`/`topic_short` to `ChatResponse`, `workflow` to `GeneratePromptsResponse`/`RethinkConceptResponse`, `concept_localized`/nullable `character_role` to `IllustrationConcept`, `story_topic_description` to `BuildStoryResponse`, `TranslateResponse`
- ✅ Updated API schemas: added i18n fields to `SessionResponse`, `RunResponse`, `IllustrationResponse`; created `TranslateRequest`/`TranslateResponse`
- ✅ Created `utils/hashing.py`: `compute_source_hash()` for staleness detection

**Frontend:**
- ✅ Installed `vue-i18n@^11` and `vue-sonner`
- ✅ Created i18n module: `i18n/supported.ts`, `i18n/locales/{sk,cs,en}.ts`, `i18n/index.ts` with `detectInitialLanguage()`
- ✅ Created `stores/locale.ts` with `setLanguage()` action
- ✅ Updated `main.ts` to register i18n plugin
- ✅ Updated router with `/:lang(sk|cs|en)` prefix, redirects, and `beforeEach` guard
- ✅ Created `composables/useToast.ts` wrapper
- ✅ Updated `App.vue` to add `<Toaster>`
- ✅ Created `i18n/sessionErrors.ts` and `i18n/runErrors.ts` key mappers

### 🚧 Remaining Work (Phase 2 - Backend API)

**1. Update Agent Prompts** (~2 hrs)
Each `.md` file needs updates per spec:

`agents/chat.md`:
- Change: "You chat in Slovak" → "You chat in the user's detected language (Slovak, Czech, or English)"
- Add to output schema: `language` (sk|cs|en|other) and `topic_short` (on confirmed phase)
- Add language detection instructions

`agents/build_story.md`:
- Add input parameter: `source_language` (sk|cs|en)
- Change: "short Slovak story" → "short story in {source_language}"
- Update output schema: add `story_topic_description`, add `concept_localized` to illustrations
- Add Cast Triplet Rule #12: single human + optional companion / companion alone / no characters
- Add Rule #13: ≤2 character-less illustrations per run cap

`agents/generate_prompts.md`:
- Add input: `character_role` (nullable)
- Add output: `workflow` ("single-lora" | "no-lora")
- Add workflow selection rule: `character_role != null` → single-lora, else no-lora

`agents/revise_prompts.md`:
- Same as generate_prompts (Agent 3 uses same schema)

`agents/rethink_concept.md`:
- Add input: `source_language`
- Add output: `workflow`, `concept_localized`, `character_role` (nullable)

**2. Update SessionService** (~3 hrs)
`app/services/session.py`:

```python
# In post_message():
- Extract `language` from ChatResponse
- On first non-null language detection, persist to session.source_language
- On confirmed phase:
  - Store topic_short from ChatResponse
  - Normalize reply using CONFIRMED_ACK[language or 'en']

# In finalize():
- Change to return topic_short immediately (202)
- Spawn background task to call build_story
- Return FinalizeResponse(topic_short=session.topic_short)
```

**3. Create Session-Level SSE** (~1 hr)
`app/api/sessions.py`:

Add endpoint:
```python
@router.get("/{session_id}/events")
async def session_events(session_id: str, ...):
    # Similar to runs SSE but for session lifecycle
    # Events: story_built{run_id}, story_build_failed{error_code}
```

**4. Update RunRepository** (~2 hrs)
`app/db/repositories.py`:

Add methods:
```python
async def get_translation(run_id, language, kind, **indexes) -> Model | None
async def upsert_translation(run_id, language, kind, text, source_hash, **indexes)
async def get_translations_for_run(run_id, language) -> dict
```

**5. Create TranslationService** (~2 hrs)
`app/services/translation.py`:

```python
class TranslationService:
    async def translate_items(
        run_id: str,
        language: str,
        items: list[TranslationItemRequest],
        claude_client,
    ) -> list[TranslationItemResponse]:
        # Filter out already-translated items (check hash)
        # Call Agent 5 with remaining items
        # Persist to translation tables
        # Return all items (cached + fresh)
```

**6. Update Runs API** (~3 hrs)
`app/api/runs.py`:

```python
@router.get("/{run_id}")
async def get_run(run_id: str, lang: str = "sk", ...):
    # Fetch run + illustrations
    # If lang == run.source_language, all states = "source"
    # Else: compute translation_state per field by comparing hashes
    # Return RunDetailResponse with translation_state fields

@router.post("/{run_id}/translations")
async def translate_run(run_id: str, body: TranslateRequest, ...):
    # Call TranslationService
    # Emit translations_refreshed event
    # Return TranslateResponse
```

**7. Update SSE Events** (~2 hrs)
`app/api/runs.py` in `run_events()`:

Add to snapshot building:
- `current_workflow` to illustrations
- `current_concept_translation_state` (compute from translation table)
- `story_title_translation_state`, `story_topic_description_translation_state`
- Per-paragraph `translation_state`

Add event types:
- `illustration_role_updated{illustration_id, character_role}`
- `translations_refreshed{language, items: [...]}` (broadcast when POST /translations completes)

**8. Update Orchestrator** (~3 hrs)
`app/orchestrator/pipeline.py` and `app/orchestrator/branch.py`:

- In build_story step: pass `source_language` and `topic_short` to Agent 0b
- In generate_prompts (Agent 1): extract `workflow`, persist to `illustration.current_workflow`
- In revise_prompts (Agent 3): same
- In rethink_concept (Agent 4):
  - Pass `source_language`
  - Extract `workflow`, `character_role`, `concept_localized`
  - If `character_role` changed, emit `illustration_role_updated` event
  - Update paragraph + concept + excerpt in DB
- Workflow file selection: use `illustrations.current_workflow` to pick `single-lora.json` vs `no-lora.json`

### 🚧 Remaining Work (Phase 3 - Frontend)

**9. Update Types** (~1 hr)
`frontend/src/types/index.ts`:

Add to `Session`:
```typescript
source_language: string | null
detected_language: string | null
topic_short: string | null
```

Add to `Run`:
```typescript
source_language: string
language: string
topic_short: string
story_title_translation_state?: TranslationState
story_topic_description: string
story_topic_description_translation_state?: TranslationState
```

Add to `Illustration`:
```typescript
character_role: string | null
current_workflow: string | null
current_concept_translation_state?: TranslationState
```

Add to story blocks:
```typescript
translation_state?: TranslationState
```

Add:
```typescript
type TranslationState = 'source' | 'fresh' | 'stale' | 'missing'
type Language = 'sk' | 'cs' | 'en'

interface RunTranslationCache {
  story_title: { text: string; source_hash: string }
  story_topic_description: { text: string; source_hash: string }
  paragraphs: Record<number, { text: string; source_hash: string }>
  concepts: Record<number, { text: string; source_hash: string }>
}
```

**10. Update sessionStore** (~2 hrs)
`frontend/src/stores/session.ts`:

Add state:
```typescript
source_language: string | null
topic_short: string | null
lastDetectedLanguage: string | null
isFinalizing: boolean
```

Update actions:
- In message handlers: detect language, call `localeStore.setLanguage()` on first detection
- In `finalize()`: change to async, call POST /finalize (returns 202), subscribe to session SSE
- Add `handleSessionEvent(event)` for story_built/story_build_failed

**11. Update runStore** (~3 hrs)
`frontend/src/stores/run.ts`:

Add state:
```typescript
translations: Record<Language, RunTranslationCache>
currentLanguage: Language
pendingTranslationLanguages: Set<Language>
```

Add actions:
```typescript
async switchLanguage(language: Language) {
  // 1. Check if all items are fresh, if so just swap currentLanguage
  // 2. Otherwise collect missing+stale items
  // 3. Call POST /api/runs/:id/translations
  // 4. Write response into translations[language]
  // 5. Reopen SSE with ?lang={language}
}
```

Update SSE handlers:
- `snapshot`: also populate translations[currentLanguage] cache
- `illustration_state`: add `current_workflow` and `current_concept_translation_state` mutations
- `paragraph_updated`: also write to translations cache
- Add `illustration_role_updated` handler
- Add `translations_refreshed` handler

**12. Create LanguageSwitcher.vue** (~2 hrs)
`frontend/src/components/LanguageSwitcher.vue`:

- Trigger button shows ISO code (SK/CS/EN) + chevron
- floating-vue menu with 3 rows (endonyms from i18n)
- Click calls `localeStore.setLanguage(code, { silent: true })`
- Sets `languageLockedByUser = true`
- Accessibility: aria-haspopup, aria-expanded, aria-label
- Responsive: pure-icon on <480px with bottom-sheet

**13. Create StoryBuildingSkeleton.vue** (~1 hr)
`frontend/src/components/StoryBuildingSkeleton.vue`:

- Title line: `i18n.t('story.building', { topic })`
- 5× `<SkeletonBlock shape="line" :lines="4" />`
- Error state: banner + `i18n.t('story.try_again')` button

**14. Update SessionView** (~2 hrs)
`frontend/src/views/SessionView.vue` (or `HomeView.vue`):

- Add `v-if="sessionStore.isFinalizing"` to show `<StoryBuildingSkeleton>`
- Hide chat thread and composer during finalizing
- Update welcome message: `i18n.t('chat.welcome')` with #bold# parsing

**15. Update RunView** (~1 hr)
`frontend/src/views/RunView.vue`:

- Add `<LanguageSwitcher />` in top-right of container
- Add `padding-right` to title to prevent overlap

**16. Internationalize UI Components** (~3 hrs)
Replace all hard-coded strings with `i18n.t()` calls:

- `ChatMessage.vue`: `i18n.t('chat.assistant_typing')`
- `ChatComposer.vue`: `i18n.t('chat.send')`, `i18n.t('chat.message_placeholder')`, `i18n.t('chat.char_limit')`
- `IllustrationCard.vue`: `i18n.t('story.illustration_n', {n})`, `i18n.t('illustration.state.${state}')`, `i18n.t('illustration.companion_subtitle', {description})`, `i18n.t('illustration.attempt', {current, max})`
- `RunHeader.vue`: `i18n.t('run.status.${status}')`, `i18n.t('run.progress', {completed, total})`, `i18n.t('run.cancel')`
- Error banners: use `sessionErrorKey()`/`runErrorKey()` + `i18n.t()`
- ConceptPopover: `i18n.t('illustration.currentConcept')`

**17. Update API Service** (~1 hr)
`frontend/src/services/api.ts`:

Add:
```typescript
export async function translateRun(
  runId: string,
  language: string,
  items: TranslationItemRequest[]
): Promise<TranslateResponse> {
  // POST /api/runs/:id/translations
}
```

Update `getRun()` to accept `lang` query param.

### 🧪 Testing Phase

**18. Backend Tests** (~4 hrs)
- Update existing test fixtures for new fields
- Add translation flow integration test
- Add workflow selection test
- Add Agent 5 mock response tests

**19. Frontend Tests** (~3 hrs)
- Update store tests for new state/actions
- Add i18n detection tests
- Add translation cache tests
- Add locale switcher tests

**20. Manual Testing** (~2 hrs)
- Test full chat→finalize→translate flow in all 3 languages
- Test language auto-switch on chat detection
- Test translation staleness after Agent 4 rewrite
- Test workflow selection (no-lora vs single-lora)

## Estimated Remaining Time
- Phase 2 (Backend API): ~18 hours
- Phase 3 (Frontend): ~18 hours
- Testing: ~9 hours
**Total: ~45 hours**

## Quick Start Commands

```bash
# Backend migration
cd backend
.venv/bin/alembic upgrade head

# Run backend tests
.venv/bin/pytest

# Run frontend
cd frontend
npm run dev

# Run frontend tests
npm test
```

## Critical Files Reference

**Backend:**
- `app/api/sessions.py` - session endpoints + SSE
- `app/api/runs.py` - run endpoints + SSE
- `app/services/session.py` - chat + finalize logic
- `app/services/translation.py` - NEW: translation orchestration
- `app/orchestrator/pipeline.py` - workflow selection
- `app/orchestrator/branch.py` - per-illustration logic

**Frontend:**
- `src/stores/locale.ts` - language switching
- `src/stores/session.ts` - chat + finalize
- `src/stores/run.ts` - translation cache + switching
- `src/components/LanguageSwitcher.vue` - NEW
- `src/components/StoryBuildingSkeleton.vue` - NEW
- `src/views/SessionView.vue` - skeleton phase
- `src/views/RunView.vue` - switcher placement

## Notes

- The spec is fully updated in SPECIFICATION.md
- All DB migrations are generated and ready
- Core i18n infrastructure (locale files, router, store) is in place
- The remaining work is primarily wiring: connecting the i18n infrastructure to the existing API/UI flows
