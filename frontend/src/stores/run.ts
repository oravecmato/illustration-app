import { defineStore } from "pinia";
import { ref } from "vue";
import type { Run, Illustration, SseEvent } from "@/types";
import { postRun, getRun, cancelRun, openSseStream } from "@/services/api";

export const useRunStore = defineStore("run", () => {
  const run = ref<Run | null>(null);
  const illustrations = ref<Illustration[]>([]);
  const isConnecting = ref(false);
  const sseError = ref<string | null>(null);

  let eventSource: EventSource | null = null;

  function handleSseEvent(event: SseEvent): void {
    switch (event.type) {
      case "snapshot": {
        run.value = event.data.run;
        illustrations.value = [...event.data.illustrations];
        break;
      }
      case "style_guide_ready": {
        if (run.value) {
          run.value.style_guide = event.data.style_guide;
          run.value.illustration_count = event.data.illustration_count;
        }
        break;
      }
      case "illustration_state": {
        const ill = illustrations.value.find((i: Illustration) => i.id === event.data.illustration_id);
        if (ill) {
          ill.state = event.data.state;
          ill.concept_attempt = event.data.concept_attempt;
          ill.prompt_attempt = event.data.prompt_attempt;
        }
        break;
      }
      case "illustration_completed": {
        const ill = illustrations.value.find((i: Illustration) => i.id === event.data.illustration_id);
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
        const ill = illustrations.value.find((i: Illustration) => i.id === event.data.illustration_id);
        if (ill) {
          ill.state = "FAILED";
          ill.error_message = event.data.error_message;
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

  async function startRun(storyText: string): Promise<string> {
    const { run_id } = await postRun(storyText);
    return run_id;
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
      }
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

  return {
    run,
    illustrations,
    isConnecting,
    sseError,
    handleSseEvent,
    startRun,
    loadRun,
    subscribe,
    unsubscribe,
    cancel,
  };
});
