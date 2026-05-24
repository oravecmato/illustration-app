import { describe, it, expect, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useRunStore } from "../src/stores/run";
import type { Illustration, Run, StyleGuide } from "../src/types";

function makeStyleGuide(overrides: Partial<StyleGuide> = {}): StyleGuide {
  return {
    overall_style_positive: "watercolor",
    overall_style_negative: "photorealistic",
    character_lora: "mha_character",
    character_baseline_description: "A boy with green hair",
    ...overrides,
  };
}

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: "run-1",
    session_id: "sess-1",
    status: "RUNNING",
    story_title: "Skúšobný príbeh",
    story_blocks: [
      { type: "paragraph", text: "Bol raz jeden chlapec." },
      { type: "illustration", scene_index: 0 },
    ],
    style_guide: makeStyleGuide(),
    illustration_count: 2,
    completed_count: 0,
    failed_count: 0,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    error_code: null,
    error_message: null,
    ...overrides,
  };
}

function makeIllustration(overrides: Partial<Illustration> = {}): Illustration {
  return {
    id: "ill-1",
    scene_index: 0,
    scene_excerpt: "Once upon a time...",
    character_role: "male",
    current_concept: "A boy crying",
    state: "PENDING",
    concept_attempt: 1,
    prompt_attempt: 1,
    image_url: null,
    ...overrides,
  };
}

describe("runStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("snapshot event replaces full state", () => {
    const store = useRunStore();
    const run = makeRun();
    const illustrations = [makeIllustration(), makeIllustration({ id: "ill-2", scene_index: 1 })];

    store.handleSseEvent({ type: "snapshot", data: { run, illustrations } });

    expect(store.run).toEqual(run);
    expect(store.illustrations).toHaveLength(2);
  });

  it("illustrationByScene maps scene_index to the matching illustration", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [
          makeIllustration({ id: "ill-1", scene_index: 0 }),
          makeIllustration({ id: "ill-2", scene_index: 2 }),
        ],
      },
    });

    expect(store.illustrationByScene.get(0)?.id).toBe("ill-1");
    expect(store.illustrationByScene.get(2)?.id).toBe("ill-2");
    expect(store.illustrationByScene.get(1)).toBeUndefined();
  });

  it("illustration_state event updates the right illustration by id", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [
          makeIllustration({ id: "ill-1", state: "PENDING" }),
          makeIllustration({ id: "ill-2", scene_index: 1, state: "PENDING" }),
        ],
      },
    });

    store.handleSseEvent({
      type: "illustration_state",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        state: "RENDERING",
        concept_attempt: 1,
        prompt_attempt: 1,
      },
    });

    const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(ill?.state).toBe("RENDERING");
    // Other illustration unchanged
    const ill2 = store.illustrations.find((i: Illustration) => i.id === "ill-2");
    expect(ill2?.state).toBe("PENDING");
  });

  it("illustration_completed event sets image_url", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [makeIllustration({ id: "ill-1", state: "EVALUATING" })],
      },
    });

    store.handleSseEvent({
      type: "illustration_completed",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        image_url: "/static/runs/run-1/scene_0.png",
      },
    });

    const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(ill?.state).toBe("COMPLETED");
    expect(ill?.image_url).toBe("/static/runs/run-1/scene_0.png");
  });

  it("run_cancelled sets run status to CANCELLED", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: { run: makeRun({ status: "RUNNING" }), illustrations: [] },
    });

    store.handleSseEvent({ type: "run_cancelled", data: {} });

    expect(store.run?.status).toBe("CANCELLED");
  });

  it("run_completed sets run status to COMPLETED", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: { run: makeRun({ status: "RUNNING" }), illustrations: [] },
    });

    store.handleSseEvent({
      type: "run_completed",
      data: { completed: 2, failed: 0 },
    });

    expect(store.run?.status).toBe("COMPLETED");
  });

  it("tolerates out-of-order events without crashing", () => {
    const store = useRunStore();
    // Send illustration_state before snapshot
    expect(() => {
      store.handleSseEvent({
        type: "illustration_state",
        data: {
          illustration_id: "nonexistent",
          scene_index: 0,
          state: "RENDERING",
          concept_attempt: 1,
          prompt_attempt: 1,
        },
      });
    }).not.toThrow();
  });

  it("tolerates duplicate events without crashing", () => {
    const store = useRunStore();
    const snapshotData = {
      run: makeRun(),
      illustrations: [makeIllustration()],
    };

    expect(() => {
      store.handleSseEvent({ type: "snapshot", data: snapshotData });
      store.handleSseEvent({ type: "snapshot", data: snapshotData });
    }).not.toThrow();
  });

  it("run_failed sets error_code and error_message and transitions to FAILED", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: { run: makeRun({ status: "RUNNING" }), illustrations: [] },
    });

    store.handleSseEvent({
      type: "run_failed",
      data: { error_code: "STORY_BUILD_FAILED", error_message: "Story build failed." },
    });

    expect(store.run?.status).toBe("FAILED");
    expect(store.run?.error_code).toBe("STORY_BUILD_FAILED");
    expect(store.run?.error_message).toBe("Story build failed.");
  });

  it("reset() clears run and illustrations", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: { run: makeRun(), illustrations: [makeIllustration()] },
    });

    store.reset();

    expect(store.run).toBeNull();
    expect(store.illustrations).toHaveLength(0);
  });
});
