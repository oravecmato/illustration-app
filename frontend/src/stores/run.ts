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
