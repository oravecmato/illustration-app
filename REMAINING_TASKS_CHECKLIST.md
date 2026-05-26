# i18n Implementation - Remaining Tasks Checklist

**Current Status:** ~40% Complete | **Remaining:** ~24 hours

Use this checklist to track progress. Mark items with [x] as you complete them.

---

## Backend Tasks (12 hours total)

### Phase 1: Core Service Updates (4 hours)

- [ ] **Task 1.1** - Update `build_story` method in `claude.py` (~30 min)
  - Location: `backend/app/services/claude.py` line ~136
  - Change: Rename to `build_story_i18n`, update to accept dict with source_language + topic_short
  - Test: Call with mock brief, verify user_text includes new fields

- [ ] **Task 1.2** - Update `finalize()` in SessionService (~30 min)
  - Location: `backend/app/services/session.py` line ~142
  - Change: Pass source_language + topic_short to build_story_i18n
  - Test: Finalize a session, check DB has source_language set

- [ ] **Task 1.3** - Update `RunRepository.create_run()` (~20 min)
  - Location: `backend/app/db/repositories.py`
  - Change: Add source_language, topic_short, story_topic_description params
  - Test: Create run, verify all fields persisted

- [ ] **Task 1.4** - Update `create_illustrations()` for nullable character_role (~20 min)
  - Location: `backend/app/db/repositories.py`
  - Change: Allow character_role=None, add current_workflow=None
  - Test: Create illustration with character_role=None

- [ ] **Task 1.5** - Update `generate_prompts` call in branch.py (~45 min)
  - Location: `backend/app/orchestrator/branch.py` Step 1
  - Change: Handle nullable character_role, persist workflow from response
  - Test: Run pipeline, verify current_workflow set in DB

- [ ] **Task 1.6** - Update workflow file selection (~30 min)
  - Location: Check `backend/app/services/workflow.py` or runpod dispatch
  - Change: Select workflow file based on illustration.current_workflow
  - Test: Dispatch job with no-lora.json workflow

### Phase 2: Translation API (4 hours)

- [ ] **Task 2.1** - Add `lang` query param to `GET /runs/{id}` (~2 hrs)
  - Location: `backend/app/api/runs.py` 
  - Change: Add translation_state computation for all fields
  - Test: GET /runs/:id?lang=cs returns Czech translations

- [ ] **Task 2.2** - Create `POST /runs/{id}/translations` endpoint (~2 hrs)
  - Location: `backend/app/api/runs.py` (new endpoint)
  - Change: Filter items, call Agent 5, persist, emit SSE
  - Test: POST translation request, verify DB rows created

### Phase 3: SSE & Agent Updates (4 hours)

- [ ] **Task 3.1** - Add session-level SSE endpoint (~1 hr)
  - Location: `backend/app/api/sessions.py` (new endpoint)
  - Change: Stream story_built / story_build_failed events
  - Test: Finalize session, subscribe to /sessions/:id/events

- [ ] **Task 3.2** - Update SSE snapshot builder (~1 hr)
  - Location: `backend/app/api/runs.py` in `run_events()`
  - Change: Add current_workflow, translation_state to snapshot
  - Test: Subscribe to /runs/:id/events, verify snapshot has new fields

- [ ] **Task 3.3** - Add new SSE event handlers (~1 hr)
  - Location: `backend/app/api/runs.py`
  - Change: Add translations_refreshed, illustration_role_updated
  - Test: Emit events, verify clients receive them

- [ ] **Task 3.4** - Update Agent 4 call in branch.py (~1 hr)
  - Location: `backend/app/orchestrator/branch.py` Step 4
  - Change: Pass source_language, handle character_role toggle, emit role_updated
  - Test: Force Agent 4 path, verify paragraph updated + role changed

---

## Frontend Tasks (12 hours total)

### Phase 1: Type Definitions (1 hour)

- [ ] **Task 4.1** - Update types/index.ts (~1 hr)
  - Location: `frontend/src/types/index.ts`
  - Change: Add i18n fields to Session, Run, Illustration interfaces
  - Test: npm run type-check passes

### Phase 2: Store Updates (5 hours)

- [ ] **Task 5.1** - Update sessionStore state (~30 min)
  - Location: `frontend/src/stores/session.ts`
  - Change: Add source_language, topic_short, lastDetectedLanguage, isFinalizing
  - Test: Store compiles without errors

- [ ] **Task 5.2** - Add language detection to message handlers (~1 hr)
  - Location: `frontend/src/stores/session.ts`
  - Change: Call localeStore.setLanguage on first detection
  - Test: Type Czech message, UI switches to Czech

- [ ] **Task 5.3** - Update finalize() for SSE (~1 hr)
  - Location: `frontend/src/stores/session.ts`
  - Change: Return 202 immediately, subscribe to session SSE
  - Test: Finalize → skeleton shows → navigates to run on story_built

- [ ] **Task 5.4** - Add runStore translations cache state (~30 min)
  - Location: `frontend/src/stores/run.ts`
  - Change: Add translations, currentLanguage, pendingTranslationLanguages
  - Test: Store compiles

- [ ] **Task 5.5** - Implement switchLanguage action (~2 hrs)
  - Location: `frontend/src/stores/run.ts`
  - Change: Add full switchLanguage logic with freshness check
  - Test: Switch language on run page, verify translation fetched

### Phase 3: UI Components (6 hours)

- [ ] **Task 6.1** - Create LanguageSwitcher.vue (~2 hrs)
  - Location: `frontend/src/components/LanguageSwitcher.vue` (new file)
  - Change: Create component with floating-vue menu
  - Test: Click switcher, select language, verify UI changes

- [ ] **Task 6.2** - Create StoryBuildingSkeleton.vue (~1 hr)
  - Location: `frontend/src/components/StoryBuildingSkeleton.vue` (new file)
  - Change: Show building message + 5 skeletons
  - Test: Finalize session, skeleton appears

- [ ] **Task 6.3** - Update SessionView for skeleton phase (~30 min)
  - Location: `frontend/src/views/SessionView.vue` or HomeView.vue
  - Change: Show skeleton when isFinalizing=true
  - Test: Skeleton shows after confirmation

- [ ] **Task 6.4** - Update RunView to add LanguageSwitcher (~15 min)
  - Location: `frontend/src/views/RunView.vue`
  - Change: Import and render LanguageSwitcher in top-right
  - Test: Switcher appears on run page

- [ ] **Task 6.5** - Internationalize all UI strings (~2.5 hrs)
  - Locations:
    - [ ] `frontend/src/components/ChatMessage.vue`
    - [ ] `frontend/src/components/ChatComposer.vue`
    - [ ] `frontend/src/components/IllustrationCard.vue`
    - [ ] `frontend/src/components/RunHeader.vue`
    - [ ] `frontend/src/components/SessionErrorBanner.vue`
    - [ ] `frontend/src/components/RunErrorBanner.vue`
  - Change: Replace all hard-coded strings with $t() calls
  - Test: Switch language, all text changes

---

## Testing & Validation

- [ ] **Test 1** - Run Alembic migration
  ```bash
  cd backend && .venv/bin/alembic upgrade head
  ```

- [ ] **Test 2** - Backend tests pass
  ```bash
  cd backend && .venv/bin/pytest
  ```

- [ ] **Test 3** - Frontend tests pass
  ```bash
  cd frontend && npm test
  ```

- [ ] **Test 4** - Lint checks pass
  ```bash
  # Backend
  cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
  
  # Frontend
  cd frontend && npm run lint && npm run type-check
  ```

- [ ] **Test 5** - End-to-end manual test
  1. [ ] Start in Slovak, agent detects language
  2. [ ] Confirm brief, skeleton shows with topic_short
  3. [ ] Navigate to run page, see Slovak story
  4. [ ] Switch to Czech via LanguageSwitcher
  5. [ ] Translations load, story shows in Czech
  6. [ ] Switch to English
  7. [ ] Force Agent 4 path, verify paragraph rewrites
  8. [ ] Test companion-alone scene uses no-lora workflow

---

## Progress Tracking

**Completed:** 0 / 28 tasks (0%)

**Time Estimate:**
- Backend: 12 hours (14 tasks)
- Frontend: 12 hours (13 tasks) 
- Testing: 2 hours (1 task)
**Total: 26 hours**

---

## Quick Reference

**Key Files to Modify:**
- Backend: `services/session.py`, `services/claude.py`, `api/runs.py`, `api/sessions.py`, `orchestrator/branch.py`, `db/repositories.py`
- Frontend: `types/index.ts`, `stores/session.ts`, `stores/run.ts`, All view/component files

**Already Complete:**
✅ Models + migrations
✅ Agent prompts (all 7)
✅ API schemas
✅ i18n locale files (sk/cs/en)
✅ Router with /:lang prefix
✅ Toast system setup
✅ Error key mappers

**Detailed Implementation:** See `IMPLEMENTATION_REMAINING.md` for exact code snippets.
