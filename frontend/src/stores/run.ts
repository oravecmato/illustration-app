import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { Illustration, Run, SseEvent } from "@/types";
import { cancelRun, getRun, openSseStream } from "@/services/api";

export const useRunStore = defineStore("run", () => {
  const run = ref<Run | null>(null);
  const illustrations = ref<Illustration[]>([]);
  const isConnecting = ref(false);
  const sseError = ref<string | null>(null);

  let eventSource: EventSource | null = null;

  const illustrationByScene = computed<Map<number, Illustration>>(() => {
    const map = new Map<number, Illustration>();
    for (const ill of illustrations.value) {
      map.set(ill.scene_index, ill);
    }
    return map;
  });

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

  function handleSseEvent(event: SseEvent): void {
    switch (event.type) {
      case "snapshot": {
        run.value = event.data.run;
        illustrations.value = [...event.data.illustrations];
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
        if (run.value) {
          run.value.completed_count++;
        }
        break;
      }
      case "illustration_failed": {
        const ill = illustrations.value.find((i) => i.id === event.data.illustration_id);
        if (ill) {
          ill.state = "FAILED";
        }
        if (run.value) {
          run.value.failed_count++;
        }
        break;
      }
      case "run_completed": {
        if (run.value) {
          run.value.status = "COMPLETED";
          run.value.completed_count = event.data.completed;
          run.value.failed_count = event.data.failed;
        }
        unsubscribe();
        break;
      }
      case "run_failed": {
        if (run.value) {
          run.value.status = "FAILED";
          run.value.error_code = event.data.error_code;
          run.value.error_message = event.data.error_message;
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

  async function loadRun(runId: string): Promise<void> {
    const data = await getRun(runId);
    run.value = data.run;
    illustrations.value = data.illustrations;
  }

  function subscribe(runId: string): void {
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
        sseError.value = "Spojenie prerušené";
        console.error("SSE error", err);
      },
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
  }

  return {
    run,
    illustrations,
    illustrationByScene,
    illustrationByParagraph,
    paragraphAt,
    isParagraphRegenerating,
    isConnecting,
    sseError,
    handleSseEvent,
    loadRun,
    subscribe,
    unsubscribe,
    cancel,
    reset,
  };
});
