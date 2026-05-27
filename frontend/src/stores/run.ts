import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { Illustration, Language, Run, SseEvent, TranslationItem } from "@/types";
import { cancelRun, getRun, openSseStream, translateRun } from "@/services/api";
import { i18n } from "@/i18n";

interface RunTranslationCache {
  story_title?: { text: string; source_hash: string };
  story_topic_description?: { text: string; source_hash: string };
  paragraphs: Record<number, { text: string; source_hash: string }>;
  concepts: Record<number, { text: string; source_hash: string }>;
  scene_excerpts: Record<number, { text: string; source_hash: string }>;
}

export const useRunStore = defineStore("run", () => {
  const run = ref<Run | null>(null);
  const illustrations = ref<Illustration[]>([]);
  const isConnecting = ref(false);
  const sseError = ref<string | null>(null);

  // Translation cache: map language -> cached translations
  const translations = ref<Record<string, RunTranslationCache>>({});
  const currentLanguage = ref<Language>("sk");
  const pendingTranslationLanguages = ref<Set<Language>>(new Set());
  // Paragraph indices currently being translated by Agent 5. Populated
  // by ensureTranslations before the request fires and cleared once it
  // resolves; drives the per-paragraph skeleton in StoryParagraph so
  // the user sees the source text being replaced (not blanked) only
  // while the network call is in flight.
  const pendingParagraphTranslations = ref<Set<number>>(new Set());

  let eventSource: EventSource | null = null;

  const illustrationByScene = computed<Map<number, Illustration>>(() => {
    const map = new Map<number, Illustration>();
    for (const ill of illustrations.value) {
      map.set(ill.scene_index, ill);
    }
    return map;
  });

  // Progress counters derived from `illustrations` rather than the
  // `run.completed_count` / `run.failed_count` fields. The backend
  // pipeline only writes those columns to the DB at run termination
  // (see pipeline.py), so any snapshot fetched mid-run carries the
  // stale value 0. Re-deriving from the illustrations array (whose
  // `state` IS updated per-illustration) means switching languages or
  // re-subscribing SSE during an active run no longer resets the
  // progress indicator. (§ 9.2.2)
  const completedCount = computed(
    () => illustrations.value.filter((i) => i.state === "COMPLETED").length,
  );
  const failedCount = computed(
    () => illustrations.value.filter((i) => i.state === "FAILED").length,
  );

  // Map paragraph_index → owning illustration (the illustration whose
  // current/next concept rewrites this paragraph). Each paragraph_index
  // is owned by at most one illustration because Agent 0b forbids two
  // adjacent illustration blocks.
  const illustrationByParagraph = computed<Map<number, Illustration>>(() => {
    const map = new Map<number, Illustration>();
    for (const ill of illustrations.value) {
      map.set(ill.paragraph_index, ill);
    }
    return map;
  });

  function paragraphAt(paragraphIndex: number): string {
    const blocks = run.value?.story_blocks;
    if (!blocks) return "";
    const block = blocks[paragraphIndex];
    return block && block.type === "paragraph" ? block.text : "";
  }

  function isParagraphRegenerating(paragraphIndex: number): boolean {
    const ill = illustrationByParagraph.value.get(paragraphIndex);
    return ill?.state === "RETHINKING_CONCEPT";
  }

  function isParagraphTranslating(paragraphIndex: number): boolean {
    return pendingParagraphTranslations.value.has(paragraphIndex);
  }

  function handleSseEvent(event: SseEvent): void {
    switch (event.type) {
      case "snapshot": {
        run.value = event.data.run;
        illustrations.value = [...event.data.illustrations];
        // Track the language the snapshot was rendered in so subsequent
        // translation lookups compare against the right cache. The SSE
        // endpoint applies translations for the `lang` query param it
        // was opened with, which mirrors what loadRun would have set.
        if (event.data.run?.language) {
          currentLanguage.value = event.data.run.language as Language;
        }
        break;
      }
      case "illustration_state": {
        const ill = illustrations.value.find((i) => i.id === event.data.illustration_id);
        if (ill) {
          ill.state = event.data.state;
          ill.concept_attempt = event.data.concept_attempt;
          ill.prompt_attempt = event.data.prompt_attempt;
          // current_concept and scene_excerpt change when Agent 4
          // rethinks the scene; assigning to the existing reactive
          // object lets the IllustrationCard re-render in place without
          // remounting. (§ 9.2.2)
          ill.current_concept = event.data.current_concept;
          ill.scene_excerpt = event.data.scene_excerpt;
        }
        break;
      }
      case "paragraph_updated": {
        // Agent 4 rewrote the paragraph that frames this illustration.
        // Mutate the existing block in place so the StoryParagraph
        // component re-renders its text while keeping its mounted state
        // (§ 9.5, § 8.4).
        if (run.value) {
          const block = run.value.story_blocks[event.data.paragraph_index];
          if (block && block.type === "paragraph") {
            block.text = event.data.text;
          }
        }
        break;
      }
      case "illustration_completed": {
        const ill = illustrations.value.find((i) => i.id === event.data.illustration_id);
        if (ill) {
          ill.state = "COMPLETED";
          ill.image_url = event.data.image_url;
        }
        // Counters derive from illustrations.value via computed getters,
        // so the state change above is enough — no manual run.* mutation.
        break;
      }
      case "illustration_failed": {
        const ill = illustrations.value.find((i) => i.id === event.data.illustration_id);
        if (ill) {
          ill.state = "FAILED";
        }
        break;
      }
      case "illustration_companion_updated": {
        // Agent 4 may keep/drop/swap the companion during a rewrite.
        // Mutate the existing illustration object in place so the
        // IllustrationCard re-renders the companion subtitle without
        // remounting. (§ 9.2.2)
        const ill = illustrations.value.find((i) => i.id === event.data.illustration_id);
        if (ill) {
          ill.companion = event.data.companion;
        }
        break;
      }
      case "illustration_role_updated": {
        // Agent 4 changed character_role (e.g., human → companion-alone).
        // Update the illustration's role in place.
        const ill = illustrations.value.find((i) => i.id === event.data.illustration_id);
        if (ill) {
          ill.character_role = event.data.character_role;
        }
        break;
      }
      case "translations_refreshed": {
        // Agent 5 completed translations for a target language.
        // Write to cache and update live view if language matches current.
        const lang = event.data.language as Language;
        if (!translations.value[lang]) {
          translations.value[lang] = { paragraphs: {}, concepts: {}, scene_excerpts: {} };
        }
        const cache = translations.value[lang];

        for (const item of event.data.items) {
          if (item.kind === "story_title") {
            cache.story_title = { text: item.text, source_hash: item.source_hash };
            if (lang === currentLanguage.value && run.value) {
              run.value.story_title = item.text;
              run.value.story_title_translation_state = "fresh";
            }
          } else if (item.kind === "story_topic_description") {
            cache.story_topic_description = { text: item.text, source_hash: item.source_hash };
            if (lang === currentLanguage.value && run.value) {
              run.value.story_topic_description = item.text;
              run.value.story_topic_description_translation_state = "fresh";
            }
          } else if (item.kind === "paragraph" && item.paragraph_index !== undefined) {
            cache.paragraphs[item.paragraph_index] = {
              text: item.text,
              source_hash: item.source_hash,
            };
            if (lang === currentLanguage.value && run.value) {
              const block = run.value.story_blocks[item.paragraph_index];
              if (block && block.type === "paragraph") {
                block.text = item.text;
                block.translation_state = "fresh";
              }
            }
          } else if (item.kind === "illustration_concept" && item.scene_index !== undefined) {
            cache.concepts[item.scene_index] = {
              text: item.text,
              source_hash: item.source_hash,
            };
            if (lang === currentLanguage.value) {
              const ill = illustrations.value.find((i) => i.scene_index === item.scene_index);
              if (ill) {
                ill.current_concept = item.text;
                ill.current_concept_translation_state = "fresh";
              }
            }
          } else if (item.kind === "scene_excerpt" && item.scene_index !== undefined) {
            cache.scene_excerpts[item.scene_index] = {
              text: item.text,
              source_hash: item.source_hash,
            };
            if (lang === currentLanguage.value) {
              const ill = illustrations.value.find((i) => i.scene_index === item.scene_index);
              if (ill) {
                ill.scene_excerpt = item.text;
                ill.scene_excerpt_translation_state = "fresh";
              }
            }
          }
        }
        break;
      }
      case "run_completed": {
        if (run.value) {
          run.value.status = "COMPLETED";
        }
        // completed/failed counts are derived from illustrations.value;
        // the per-illustration terminal SSE events already drove them.
        unsubscribe();
        break;
      }
      case "run_failed": {
        if (run.value) {
          run.value.status = "FAILED";
          run.value.error_code = event.data.error_code;
          run.value.error_message = event.data.error_message;
        } else {
          // Pre-creation failure: Agent 0b (or the background task that
          // schedules the pipeline) failed before the run row was
          // persisted. There is no DB row to load — synthesise a minimal
          // FAILED run object so RunView can swap the loading skeleton
          // for the error banner instead of hanging on the loader.
          run.value = {
            id: "",
            session_id: "",
            status: "FAILED",
            source_language: "en",
            language: "en",
            topic_short: "",
            story_title: "",
            story_topic_description: "",
            story_blocks: [],
            style_guide: {
              overall_style_positive: "",
              overall_style_negative: "",
              character_lora: "",
              character_baseline_description: "",
            },
            illustration_count: 0,
            completed_count: 0,
            failed_count: 0,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            error_code: event.data.error_code,
            error_message: event.data.error_message,
          } as Run;
        }
        unsubscribe();
        break;
      }
      case "run_cancelled": {
        if (run.value) {
          run.value.status = "CANCELLED";
        }
        unsubscribe();
        break;
      }
      case "heartbeat":
        break;
    }
  }

  async function loadRun(runId: string, lang?: Language): Promise<void> {
    const data = await getRun(runId, lang);
    run.value = data.run;
    illustrations.value = data.illustrations;
    if (lang) {
      currentLanguage.value = lang;
    } else if (run.value) {
      currentLanguage.value = run.value.source_language as Language;
    }
  }

  /**
   * Check if all items for a language have fresh translations.
   * Returns true if language is source or all translations are fresh.
   */
  function isLanguageFresh(lang: Language): boolean {
    if (!run.value) return false;
    if (lang === run.value.source_language) return true;

    const cache = translations.value[lang];
    if (!cache) return false;

    // Check story title
    if (
      !cache.story_title ||
      run.value.story_title_translation_state === "stale" ||
      run.value.story_title_translation_state === "missing"
    ) {
      return false;
    }

    // Check story topic description
    if (
      !cache.story_topic_description ||
      run.value.story_topic_description_translation_state === "stale" ||
      run.value.story_topic_description_translation_state === "missing"
    ) {
      return false;
    }

    // Check paragraphs
    for (const block of run.value.story_blocks) {
      if (block.type === "paragraph" && block.index !== undefined) {
        if (
          !cache.paragraphs[block.index] ||
          block.translation_state === "stale" ||
          block.translation_state === "missing"
        ) {
          return false;
        }
      }
    }

    // Check concepts and scene excerpts
    for (const ill of illustrations.value) {
      if (
        !cache.concepts[ill.scene_index] ||
        ill.current_concept_translation_state === "stale" ||
        ill.current_concept_translation_state === "missing"
      ) {
        return false;
      }
      if (
        !cache.scene_excerpts[ill.scene_index] ||
        ill.scene_excerpt_translation_state === "stale" ||
        ill.scene_excerpt_translation_state === "missing"
      ) {
        return false;
      }
    }

    return true;
  }

  /**
   * Collect items that need translation (missing or stale).
   */
  function collectMissingStaleItems(): TranslationItem[] {
    if (!run.value) return [];

    const items: TranslationItem[] = [];

    // Story title
    if (
      run.value.story_title_translation_state === "missing" ||
      run.value.story_title_translation_state === "stale"
    ) {
      items.push({ kind: "story_title", text: "", source_hash: "" });
    }

    // Story topic description
    if (
      run.value.story_topic_description_translation_state === "missing" ||
      run.value.story_topic_description_translation_state === "stale"
    ) {
      items.push({ kind: "story_topic_description", text: "", source_hash: "" });
    }

    // Paragraphs
    for (const block of run.value.story_blocks) {
      if (block.type === "paragraph" && block.index !== undefined) {
        if (block.translation_state === "missing" || block.translation_state === "stale") {
          items.push({ kind: "paragraph", paragraph_index: block.index, text: "", source_hash: "" });
        }
      }
    }

    // Concepts and scene excerpts
    for (const ill of illustrations.value) {
      if (
        ill.current_concept_translation_state === "missing" ||
        ill.current_concept_translation_state === "stale"
      ) {
        items.push({
          kind: "illustration_concept",
          scene_index: ill.scene_index,
          text: "",
          source_hash: "",
        });
      }
      if (
        ill.scene_excerpt_translation_state === "missing" ||
        ill.scene_excerpt_translation_state === "stale"
      ) {
        items.push({
          kind: "scene_excerpt",
          scene_index: ill.scene_index,
          text: "",
          source_hash: "",
        });
      }
    }

    return items;
  }

  /**
   * Request translations for any missing/stale items in `lang` and reload.
   * No-op if `lang` is the source language, already fresh, or in-flight.
   * Does not change `currentLanguage` or the SSE subscription — the caller
   * is responsible for those (see `switchLanguage` and RunView.onMounted).
   */
  async function ensureTranslations(lang: Language): Promise<void> {
    if (!run.value) return;
    if (lang === run.value.source_language) return;
    if (pendingTranslationLanguages.value.has(lang)) return;
    if (isLanguageFresh(lang)) return;

    const itemsToRequest = collectMissingStaleItems();
    if (itemsToRequest.length === 0) return;

    // Mark the paragraphs actually being translated so StoryParagraph
    // can swap to a skeleton just for those (not the ones already cached
    // or in source language). Cleared in `finally` after the response.
    const paragraphIndicesInFlight = itemsToRequest
      .filter((item) => item.kind === "paragraph" && item.paragraph_index !== undefined)
      .map((item) => item.paragraph_index as number);
    for (const idx of paragraphIndicesInFlight) {
      pendingParagraphTranslations.value.add(idx);
    }

    pendingTranslationLanguages.value.add(lang);
    try {
      const response = await translateRun(run.value.id, lang, itemsToRequest);

      if (!translations.value[lang]) {
        translations.value[lang] = { paragraphs: {}, concepts: {}, scene_excerpts: {} };
      }
      const cache = translations.value[lang];

      for (const item of response.items) {
        if (item.kind === "story_title") {
          cache.story_title = { text: item.text, source_hash: item.source_hash };
        } else if (item.kind === "story_topic_description") {
          cache.story_topic_description = { text: item.text, source_hash: item.source_hash };
        } else if (item.kind === "paragraph" && item.paragraph_index !== undefined) {
          cache.paragraphs[item.paragraph_index] = {
            text: item.text,
            source_hash: item.source_hash,
          };
        } else if (item.kind === "illustration_concept" && item.scene_index !== undefined) {
          cache.concepts[item.scene_index] = {
            text: item.text,
            source_hash: item.source_hash,
          };
        } else if (item.kind === "scene_excerpt" && item.scene_index !== undefined) {
          cache.scene_excerpts[item.scene_index] = {
            text: item.text,
            source_hash: item.source_hash,
          };
        }
      }

      // Reload so the freshly-translated text appears in the view.
      await loadRun(run.value.id, lang);
    } finally {
      pendingTranslationLanguages.value.delete(lang);
      for (const idx of paragraphIndicesInFlight) {
        pendingParagraphTranslations.value.delete(idx);
      }
    }
  }

  /**
   * Switch to a different language, fetching translations if needed.
   */
  async function switchLanguage(lang: Language): Promise<void> {
    if (!run.value) return;
    if (lang === currentLanguage.value) return;
    if (pendingTranslationLanguages.value.has(lang)) return;

    // Load with the target language so translation_state fields reflect
    // what's already cached server-side.
    await loadRun(run.value.id, lang);

    // For non-source languages, fetch any missing/stale items.
    if (run.value && lang !== run.value.source_language) {
      await ensureTranslations(lang);
    }

    currentLanguage.value = lang;
    if (eventSource && run.value) {
      unsubscribe();
      subscribe(run.value.id, lang);
    }
  }

  function subscribe(runId: string, lang?: Language): void {
    isConnecting.value = true;
    sseError.value = null;

    eventSource = openSseStream(
      runId,
      (event: SseEvent) => {
        isConnecting.value = false;
        handleSseEvent(event);
      },
      (err: Event) => {
        isConnecting.value = false;
        sseError.value = i18n.global.t("errors.run.sse_disconnected");
        console.error("SSE error", err);
      },
      lang,
    );
  }

  function unsubscribe(): void {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  async function cancel(): Promise<void> {
    if (run.value) {
      await cancelRun(run.value.id);
    }
  }

  function reset(): void {
    unsubscribe();
    run.value = null;
    illustrations.value = [];
    isConnecting.value = false;
    sseError.value = null;
    translations.value = {};
    currentLanguage.value = "sk";
    pendingTranslationLanguages.value.clear();
    pendingParagraphTranslations.value.clear();
  }

  return {
    run,
    illustrations,
    illustrationByScene,
    illustrationByParagraph,
    completedCount,
    failedCount,
    paragraphAt,
    isParagraphRegenerating,
    isParagraphTranslating,
    isConnecting,
    sseError,
    translations,
    currentLanguage,
    pendingTranslationLanguages,
    pendingParagraphTranslations,
    handleSseEvent,
    loadRun,
    subscribe,
    unsubscribe,
    cancel,
    reset,
    switchLanguage,
    ensureTranslations,
    isLanguageFresh,
  };
});
