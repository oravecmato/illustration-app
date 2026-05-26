# Remaining i18n Implementation - Exact Code Changes

**Status:** ~40% complete (~24 hrs remaining)
**Progress:** ✅ Foundation + Agent Prompts | 🚧 Backend API | 🚧 Frontend

---

## Critical Path (Highest Priority)

### 1. Update build_story call in SessionService (~30 min)

**File:** `backend/app/services/session.py` line ~150

**Current code:**
```python
story = await self.claude.build_story(brief)
```

**Replace with:**
```python
# Get source_language from session (default to 'en' if not set)
source_language = s.source_language or "en"
topic_short = s.topic_short or ""

# Build input dict for Agent 0b
build_input = {
    "source_language": source_language,
    "topic_short": topic_short,
    "characters": brief.characters,
    "companions": brief.companions,
    "topic": brief.topic,
    "notes": brief.notes,
}

story = await self.claude.build_story_i18n(build_input)
```

**Also update claude.py `build_story` method signature:**
```python
async def build_story_i18n(self, input_dict: dict) -> BuildStoryResponse:
    user_text = (
        f"source_language: {input_dict['source_language']}\n"
        f"topic_short: {input_dict['topic_short']}\n\n"
        f"characters: {json.dumps([c.model_dump() for c in input_dict['characters']], indent=2)}\n"
        f"companions: {json.dumps([c.model_dump() for c in input_dict['companions']], indent=2)}\n"
        f"topic: {input_dict['topic']}\n"
        f"notes: {input_dict['notes']}\n\n"
        "Respond with the JSON object specified in your instructions."
    )
    # ... rest same as before
```

### 2. Update Run creation to store i18n fields (~15 min)

**File:** `backend/app/services/session.py` in `finalize()` method

**After calling `build_story_i18n`, add:**
```python
# Store source_language and topic_short in run
run = await run_repo.create_run(
    session_id=session_id,
    source_language=s.source_language or "en",
    topic_short=s.topic_short or "",
    story_title=story.story_title,
    story_topic_description=story.story_topic_description,
    # ... rest
)
```

**Update `RunRepository.create_run()` signature in `repositories.py`:**
```python
async def create_run(
    self,
    session_id: str,
    source_language: str,
    topic_short: str,
    story_title: str,
    story_topic_description: str,
    # ... rest
) -> Run:
    run = Run(
        session_id=session_id,
        source_language=source_language,
        topic_short=topic_short,
        story_title=story_title,
        story_topic_description=story_topic_description,
        # ... rest
    )
```

### 3. Update Illustration creation for nullable character_role + workflow (~20 min)

**File:** `backend/app/db/repositories.py` in `create_illustrations()`

**Change:**
```python
# Before (character_role was required)
character_role=ill_concept.character_role

# After (nullable)
character_role=ill_concept.character_role,  # Can be None
current_workflow=None,  # Will be set by Agent 1
```

### 4. Update generate_prompts call to return workflow (~30 min)

**File:** `backend/app/orchestrator/branch.py` in Step 1

**Current:**
```python
prompts = await claude.generate_prompts(...)
```

**After receiving prompts, persist workflow:**
```python
prompts = await claude.generate_prompts(...)

# Persist workflow to illustration
await repo.update_illustration(
    illustration.id,
    current_workflow=prompts.workflow,
)
```

**Add to claude.py `generate_prompts` input:**
```python
async def generate_prompts(
    self,
    character_role: str | None,  # Made nullable
    character_display: str | None,
    # ...
) -> GeneratePromptsResponse:
    # When character_role is None, omit character-specific fields
    user_parts = []
    if character_role:
        user_parts.append(f"character_role: {character_role}")
        user_parts.append(f"character_display: {character_display}")
        # ... trigger_tags, outfit, etc
    else:
        user_parts.append("character_role: null")

    user_text = "\n".join(user_parts) + "\n\nconcept: {concept}\n..."
    # ... rest same
```

### 5. Update workflow file selection in RunPod dispatch (~20 min)

**File:** `backend/app/services/runpod.py` or wherever workflow is loaded

**Current:**
```python
workflow_path = settings.WORKFLOW_PATH
with open(workflow_path) as f:
    workflow = json.load(f)
```

**Replace with:**
```python
workflow_filename = illustration.current_workflow or "single-lora.json"
workflow_path = os.path.join(settings.WORKFLOWS_DIR, workflow_filename)
with open(workflow_path) as f:
    workflow = json.load(f)
```

**Update settings:**
```python
# backend/app/config.py
WORKFLOWS_DIR: str = "./app/workflows"  # Instead of WORKFLOW_PATH
```

### 6. Add lang query param to GET /runs/{id} (~1 hr)

**File:** `backend/app/api/runs.py`

**Update endpoint signature:**
```python
@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: str,
    lang: str = "sk",  # New query param
    session: AsyncSession = Depends(get_session),
):
```

**Add translation_state computation:**
```python
from app.utils.hashing import compute_source_hash

# After fetching run and illustrations
run_data = run_to_dict(run)

# If lang == source_language, all states are "source"
if lang == run.source_language:
    run_data["language"] = lang
    run_data["story_title_translation_state"] = "source"
    run_data["story_topic_description_translation_state"] = "source"
    # ... same for paragraphs and concepts
else:
    # Fetch translations from DB
    story_trans = await session.execute(
        select(StoryTranslation).where(
            StoryTranslation.run_id == run_id,
            StoryTranslation.language == lang
        )
    )
    story_trans = story_trans.scalar_one_or_none()

    # Compute translation_state
    if story_trans:
        title_hash = compute_source_hash(run.story_title)
        run_data["story_title_translation_state"] = (
            "fresh" if story_trans.story_title_source_hash == title_hash else "stale"
        )
        run_data["story_title"] = story_trans.story_title
    else:
        run_data["story_title_translation_state"] = "missing"

    # Repeat for story_topic_description, paragraphs, concept_localized
```

### 7. Create POST /runs/{id}/translations endpoint (~2 hrs)

**File:** `backend/app/api/runs.py`

**Add new endpoint:**
```python
@router.post("/{run_id}/translations", response_model=TranslateResponse)
async def translate_run(
    run_id: str,
    body: TranslateRequest,
    session: AsyncSession = Depends(get_session),
    background_tasks: BackgroundTasks,
):
    # 1. Fetch run + illustrations
    run = await run_repo.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    # 2. Filter items: skip already-translated (check source_hash)
    items_to_translate = []
    for item in body.items:
        if item.kind == "story_title":
            existing = await session.execute(
                select(StoryTranslation).where(...)
            )
            trans = existing.scalar_one_or_none()
            current_hash = compute_source_hash(run.story_title)
            if not trans or trans.story_title_source_hash != current_hash:
                items_to_translate.append({
                    "kind": "story_title",
                    "source_text": run.story_title,
                })
        # Repeat for story_topic_description, paragraphs, concepts

    # 3. Call Agent 5 if items_to_translate is non-empty
    if items_to_translate:
        translate_response = await claude.translate(
            target_language=body.language,
            items=items_to_translate,
        )

        # 4. Persist to translation tables
        for trans_item in translate_response.translations:
            if trans_item.kind == "story_title":
                await session.merge(StoryTranslation(
                    run_id=run_id,
                    language=body.language,
                    story_title=trans_item.translated_text,
                    story_title_source_hash=compute_source_hash(run.story_title),
                    # ...
                ))
            # Repeat for other kinds

        await session.commit()

    # 5. Emit translations_refreshed SSE event
    bus = get_event_bus(run_id)
    if bus:
        await bus.publish("translations_refreshed", {
            "language": body.language,
            "items": [item.model_dump() for item in translate_response.translations],
        })

    # 6. Return all items (cached + fresh)
    return fetch_all_translations(run_id, body.language)
```

### 8. Update Agent 4 (rethink_concept) to pass source_language and handle workflow change (~1 hr)

**File:** `backend/app/orchestrator/branch.py` in Step 4

**Before calling Agent 4:**
```python
rethink_response = await claude.rethink_concept(
    source_language=run.source_language,
    character_role=illustration.character_role,  # Pass current (nullable)
    # ... rest
)

# After response, check if character_role changed
if rethink_response.character_role != illustration.character_role:
    # Emit illustration_role_updated event
    await bus.publish("illustration_role_updated", {
        "illustration_id": illustration.id,
        "character_role": rethink_response.character_role,
    })

# Update DB
await repo.update_illustration(
    illustration.id,
    character_role=rethink_response.character_role,
    current_workflow=rethink_response.workflow,
    current_concept=rethink_response.concept,
    # ...
)

# Update paragraph in run.story_blocks
await repo.update_paragraph(
    run_id,
    rethink_response.paragraph_index,
    text=rethink_response.paragraph_text,
)
```

---

## Frontend Critical Path

### 9. Update types/index.ts (~15 min)

**Add to Session:**
```typescript
source_language: string | null
detected_language: string | null
topic_short: string | null
```

**Add to Run:**
```typescript
source_language: string
language: string
topic_short: string
story_title_translation_state?: TranslationState
story_topic_description: string
story_topic_description_translation_state?: TranslationState
```

**Add to Illustration:**
```typescript
character_role: string | null
current_workflow: string | null
current_concept_translation_state?: TranslationState
```

**Add to ParagraphBlock:**
```typescript
translation_state?: TranslationState
```

**Add types:**
```typescript
type TranslationState = 'source' | 'fresh' | 'stale' | 'missing'

interface RunTranslationCache {
  story_title: { text: string; source_hash: string }
  story_topic_description: { text: string; source_hash: string }
  paragraphs: Record<number, { text: string; source_hash: string }>
  concepts: Record<number, { text: string; source_hash: string }>
}
```

### 10. Update sessionStore (~2 hrs)

**File:** `frontend/src/stores/session.ts`

**Add state:**
```typescript
source_language: string | null = null
topic_short: string | null = null
lastDetectedLanguage: string | null = null
isFinalizing: boolean = false
```

**In message handlers, detect language:**
```typescript
// After receiving PostMessageResponse
if (response.detected_language && !this.lastDetectedLanguage) {
  this.lastDetectedLanguage = response.detected_language
  const localeStore = useLocaleStore()
  if (!localeStore.languageLockedByUser && response.detected_language !== localeStore.currentLanguage) {
    localeStore.setLanguage(response.detected_language as Language, { silent: false })
    // Toast is triggered by locale store
  }
}
```

**Update finalize():**
```typescript
async finalize() {
  this.isFinalizing = true
  const res = await api.finalizeSession(this.id!)
  this.topic_short = res.topic_short

  // Subscribe to session SSE
  const eventSource = new EventSource(`/api/sessions/${this.id}/events`)
  eventSource.addEventListener('story_built', (e) => {
    const data = JSON.parse(e.data)
    this.run_id = data.run_id
    this.isFinalizing = false
    router.push(`/${localeStore.currentLanguage}/runs/${data.run_id}`)
    eventSource.close()
  })
  eventSource.addEventListener('story_build_failed', (e) => {
    const data = JSON.parse(e.data)
    this.error_code = data.error_code
    this.isFinalizing = false
    eventSource.close()
  })
}
```

### 11. Update runStore for translations cache (~3 hrs)

**File:** `frontend/src/stores/run.ts`

**Add state:**
```typescript
translations: Record<Language, RunTranslationCache> = {}
currentLanguage: Language = 'sk'
pendingTranslationLanguages: Set<Language> = new Set()
```

**Add switchLanguage action:**
```typescript
async switchLanguage(language: Language) {
  if (language === this.currentLanguage) return
  if (this.pendingTranslationLanguages.has(language)) return

  // Check if all items are fresh
  const allFresh = this.isLanguageFresh(language)

  if (language === this.run.source_language || allFresh) {
    // Just swap, no network call
    this.currentLanguage = language
    this.reopenSSE(language)
    return
  }

  // Collect missing/stale items
  const items = this.collectMissingStaleItems(language)

  this.pendingTranslationLanguages.add(language)
  try {
    const response = await api.translateRun(this.run.id, language, items)

    // Write to cache
    this.translations[language] = this.translations[language] || {}
    for (const item of response.items) {
      if (item.kind === 'story_title') {
        this.translations[language].story_title = {
          text: item.text,
          source_hash: item.source_hash,
        }
      }
      // ... repeat for other kinds
    }

    // If still on this language, patch live view
    if (language === this.currentLanguage) {
      this.run.story_title = response.items.find(i => i.kind === 'story_title')?.text || this.run.story_title
      // ... repeat
    }

    this.currentLanguage = language
    this.reopenSSE(language)
  } finally {
    this.pendingTranslationLanguages.delete(language)
  }
}
```

**Update SSE handlers:**
```typescript
handleIllustrationState(data) {
  const ill = this.illustrations.find(i => i.id === data.illustration_id)
  if (ill) {
    ill.state = data.state
    ill.current_workflow = data.current_workflow
    ill.current_concept_translation_state = data.current_concept_translation_state
    // ...
  }
}

handleTranslationsRefreshed(data) {
  // Write to cache
  this.translations[data.language] = this.translations[data.language] || {}
  for (const item of data.items) {
    // ... write each item
  }

  // If active language matches, patch live view
  if (data.language === this.currentLanguage) {
    this.run.story_title = data.items.find(i => i.kind === 'story_title')?.text || this.run.story_title
    // ...
  }
}

handleIllustrationRoleUpdated(data) {
  const ill = this.illustrations.find(i => i.id === data.illustration_id)
  if (ill) {
    ill.character_role = data.character_role
  }
}
```

### 12. Create LanguageSwitcher.vue (~2 hrs)

**File:** `frontend/src/components/LanguageSwitcher.vue`

```vue
<template>
  <div class="language-switcher">
    <button
      @click="isOpen = !isOpen"
      :aria-label="$t('nav.change_language')"
      aria-haspopup="menu"
      :aria-expanded="isOpen"
    >
      {{ currentLanguage.toUpperCase() }}
      <ChevronIcon :class="{ rotated: isOpen }" />
    </button>

    <VDropdown v-model:shown="isOpen">
      <div class="menu" role="menu">
        <button
          v-for="lang in SUPPORTED_LANGUAGES"
          :key="lang"
          role="menuitemradio"
          :aria-checked="lang === currentLanguage"
          @click="selectLanguage(lang)"
        >
          <CheckIcon v-if="lang === currentLanguage" />
          {{ $t(`language.${lang}`) }}
        </button>
      </div>
    </VDropdown>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useLocaleStore } from '@/stores/locale'
import { SUPPORTED_LANGUAGES } from '@/i18n/supported'

const localeStore = useLocaleStore()
const currentLanguage = computed(() => localeStore.currentLanguage)
const isOpen = ref(false)

function selectLanguage(lang: Language) {
  localeStore.setLanguage(lang, { silent: true })
  isOpen.value = false
}
</script>

<style scoped lang="scss">
.language-switcher {
  position: absolute;
  top: 16px;
  right: 16px;
}
</style>
```

### 13. Create StoryBuildingSkeleton.vue (~1 hr)

**File:** `frontend/src/components/StoryBuildingSkeleton.vue`

```vue
<template>
  <div class="story-building">
    <p class="building-text">
      {{ $t('story.building', { topic: topic_short }) }}
    </p>
    <SkeletonBlock
      v-for="i in 5"
      :key="i"
      shape="line"
      :lines="4"
    />
  </div>
</template>

<script setup lang="ts">
import SkeletonBlock from './SkeletonBlock.vue'

defineProps<{
  topic_short: string
}>()
</script>
```

### 14. Update SessionView to show skeleton (~30 min)

**File:** `frontend/src/views/SessionView.vue` (or HomeView.vue)

```vue
<template>
  <div>
    <div v-if="!sessionStore.isFinalizing">
      <ChatThread />
      <ChatComposer />
    </div>

    <StoryBuildingSkeleton
      v-else-if="sessionStore.isFinalizing"
      :topic_short="sessionStore.topic_short || ''"
    />
  </div>
</template>
```

### 15. Update RunView to add LanguageSwitcher (~15 min)

**File:** `frontend/src/views/RunView.vue`

```vue
<template>
  <div class="run-view">
    <LanguageSwitcher />
    <h1 style="padding-right: calc(72px + 16px)">
      {{ run.story_title }}
    </h1>
    <!-- rest -->
  </div>
</template>

<script setup>
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
</script>
```

### 16. Internationalize all UI components (~3 hrs)

Replace all hard-coded strings with `i18n.t()` calls in:
- ChatMessage.vue
- ChatComposer.vue
- IllustrationCard.vue
- RunHeader.vue
- Error banners

**Example:**
```vue
<!-- Before -->
<p>Asistent píše…</p>

<!-- After -->
<p>{{ $t('chat.assistant_typing') }}</p>
```

---

## Testing & Validation

**After implementation:**
1. Run backend migration: `alembic upgrade head`
2. Test language detection flow (type in Slovak, Czech, English)
3. Test translation refresh (switch language on run page)
4. Test workflow selection (companion-alone scene uses no-lora)
5. Test Agent 4 character_role toggle (human scene → companion-alone)

**Estimated Total Remaining:** ~24 hours
