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
    source_language: "sk",
    language: "sk",
    topic_short: "test",
    story_title: "Skúšobný príbeh",
    story_topic_description: "Skúšobný popis",
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
    paragraph_index: 0,
    character_role: "male",
    current_concept: "A boy crying",
    state: "PENDING",
    concept_attempt: 1,
    prompt_attempt: 1,
    image_url: null,
    contains_entity_label: null,
    current_workflow: null,
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
        current_concept: "A boy crying",
        scene_excerpt: "Once upon a time...",
      },
    });

    const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(ill?.state).toBe("RENDERING");
    // Other illustration unchanged
    const ill2 = store.illustrations.find((i: Illustration) => i.id === "ill-2");
    expect(ill2?.state).toBe("PENDING");
  });

  it("illustration_state event updates current_concept on the same object", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [makeIllustration({ id: "ill-1", current_concept: "Original" })],
      },
    });

    // Hold the reference to the existing reactive object so we can
    // verify the field changes without object identity changing.
    const originalRef = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(originalRef?.current_concept).toBe("Original");

    store.handleSseEvent({
      type: "illustration_state",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        state: "RETHINKING_CONCEPT",
        concept_attempt: 2,
        prompt_attempt: 1,
        current_concept: "Rethought",
        scene_excerpt: "Once upon a time...",
      },
    });

    const afterRef = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(afterRef).toBe(originalRef); // same object identity
    expect(afterRef?.current_concept).toBe("Rethought");
  });

  it("illustration_runpod_status writes runpod_status onto the illustration", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [makeIllustration({ id: "ill-1", state: "RENDERING" })],
      },
    });

    store.handleSseEvent({
      type: "illustration_runpod_status",
      data: { illustration_id: "ill-1", scene_index: 0, runpod_status: "IN_QUEUE" },
    });
    expect(store.illustrations.find((i) => i.id === "ill-1")?.runpod_status).toBe("IN_QUEUE");

    store.handleSseEvent({
      type: "illustration_runpod_status",
      data: { illustration_id: "ill-1", scene_index: 0, runpod_status: "IN_PROGRESS" },
    });
    expect(store.illustrations.find((i) => i.id === "ill-1")?.runpod_status).toBe("IN_PROGRESS");
  });

  it("illustration_completed clears runpod_status", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [makeIllustration({ id: "ill-1", state: "RENDERING" })],
      },
    });
    store.handleSseEvent({
      type: "illustration_runpod_status",
      data: { illustration_id: "ill-1", scene_index: 0, runpod_status: "IN_PROGRESS" },
    });
    store.handleSseEvent({
      type: "illustration_completed",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        image_url: "/static/runs/run-1/scene_0.png",
      },
    });
    expect(store.illustrations.find((i) => i.id === "ill-1")?.runpod_status).toBeNull();
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
          current_concept: "any",
          scene_excerpt: "any",
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

  it("illustration_state event mutates scene_excerpt in place", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [
          makeIllustration({ id: "ill-1", scene_excerpt: "Original excerpt" }),
        ],
      },
    });

    const originalRef = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    store.handleSseEvent({
      type: "illustration_state",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        state: "GENERATING_PROMPTS",
        concept_attempt: 2,
        prompt_attempt: 1,
        current_concept: "New concept",
        scene_excerpt: "Rewritten excerpt",
      },
    });

    const afterRef = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(afterRef).toBe(originalRef);
    expect(afterRef?.scene_excerpt).toBe("Rewritten excerpt");
  });

  it("paragraph_updated event rewrites the matching paragraph block in place", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun({
          story_blocks: [
            { type: "paragraph", text: "Pôvodný odsek." },
            { type: "illustration", scene_index: 0 },
            { type: "paragraph", text: "Druhý odsek." },
          ],
        }),
        illustrations: [],
      },
    });

    store.handleSseEvent({
      type: "paragraph_updated",
      data: { paragraph_index: 0, text: "Prepísaný odsek." },
    });

    expect(store.run?.story_blocks[0]).toEqual({
      type: "paragraph",
      text: "Prepísaný odsek.",
    });
    // Other blocks unchanged
    expect(store.run?.story_blocks[2]).toEqual({
      type: "paragraph",
      text: "Druhý odsek.",
    });
  });

  it("paragraphAt and isParagraphRegenerating expose paragraph state for the view", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun({
          story_blocks: [
            { type: "paragraph", text: "Prvý odsek." },
            { type: "illustration", scene_index: 0 },
          ],
        }),
        illustrations: [
          makeIllustration({
            id: "ill-1",
            scene_index: 0,
            paragraph_index: 0,
            state: "RENDERING",
          }),
        ],
      },
    });

    expect(store.paragraphAt(0)).toBe("Prvý odsek.");
    expect(store.isParagraphRegenerating(0)).toBe(false);

    store.handleSseEvent({
      type: "illustration_state",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        state: "RETHINKING_CONCEPT",
        concept_attempt: 2,
        prompt_attempt: 1,
        current_concept: "New concept",
        scene_excerpt: "Once upon a time...",
      },
    });

    expect(store.isParagraphRegenerating(0)).toBe(true);
  });

  it("illustration_entity_updated sets contains_entity_label on the matching illustration", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [makeIllustration({ id: "ill-1", contains_entity_label: null })],
      },
    });

    const originalRef = store.illustrations.find((i: Illustration) => i.id === "ill-1");

    store.handleSseEvent({
      type: "illustration_entity_updated",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        contains_entity_label: "a small black cat",
        entity: {
          label: "a small black cat",
          kind: "non_human_character",
          importance: "primary",
          reserved_for_scene_index: 0,
        },
      },
    });

    const afterRef = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(afterRef).toBe(originalRef); // same object identity
    expect(afterRef?.contains_entity_label).toBe("a small black cat");
  });

  it("illustration_entity_updated can drop the scene entity (label → null)", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [
          makeIllustration({
            id: "ill-1",
            contains_entity_label: "a small black cat",
          }),
        ],
      },
    });

    store.handleSseEvent({
      type: "illustration_entity_updated",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        contains_entity_label: null,
        entity: null,
      },
    });

    const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(ill?.contains_entity_label).toBeNull();
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

  // ── § 6A manual chat SSE ───────────────────────────────────────────────

  it("illustration_manual_started seeds the welcome bubble", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [makeIllustration({ id: "ill-1", state: "MANUAL_CHATTING" })],
      },
    });

    store.handleSseEvent({
      type: "illustration_manual_started",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        sub_phase: "concept_design",
        welcome_message: {
          id: "msg-w",
          role: "assistant",
          content: "Niečo sa zaseklo. #Skús povedať, čo si predstavuješ.#",
          created_at: "2026-05-27T17:00:00Z",
        },
      },
    });

    const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(ill?.manual_session?.messages).toHaveLength(1);
    expect(ill?.manual_session?.messages[0].role).toBe("assistant");
  });

  it("manual_message_appended appends a chat row", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [makeIllustration({ id: "ill-1", state: "MANUAL_CHATTING" })],
      },
    });

    store.handleSseEvent({
      type: "manual_message_appended",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        sub_phase: "concept_design",
        message: {
          id: "msg-1",
          role: "user",
          content: "Make her brave",
          image_url: null,
          manual_attempt_index: null,
          created_at: "2026-05-27T17:01:00Z",
        },
      },
    });

    const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(ill?.manual_session?.messages).toHaveLength(1);
    expect(ill?.manual_session?.messages[0].content).toBe("Make her brave");
  });

  it("manual_image_rendered appends only the image row with provenance (§ 6A.10)", () => {
    const store = useRunStore();
    store.handleSseEvent({
      type: "snapshot",
      data: {
        run: makeRun(),
        illustrations: [makeIllustration({ id: "ill-1", state: "MANUAL_RENDERING" })],
      },
    });

    store.handleSseEvent({
      type: "manual_image_rendered",
      data: {
        illustration_id: "ill-1",
        scene_index: 0,
        sub_phase: "feedback_gathering",
        manual_attempt: 1,
        image_url: "/static/runs/run-1/manual_0_1.png",
        image_message_id: "img-1",
        concept_used: "A boy at the door",
        positive_prompt: "1boy, doorway, determined",
        negative_prompt: "blurry",
      },
    });

    const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
    expect(ill?.manual_attempts).toBe(1);
    expect(ill?.manual_session?.last_image_url).toBe("/static/runs/run-1/manual_0_1.png");
    // § 6A.10: only the image row — no canned review-prompt bubble.
    expect(ill?.manual_session?.messages).toHaveLength(1);
    const imageRow = ill?.manual_session?.messages[0];
    expect(imageRow?.role).toBe("image");
    expect(imageRow?.concept_used).toBe("A boy at the door");
    expect(imageRow?.positive_prompt).toBe("1boy, doorway, determined");
    expect(imageRow?.negative_prompt).toBe("blurry");
  });

  describe("§ 6A.9 regeneration", () => {
    it("showManualChat / hideManualChat flip the toggle for one illustration", () => {
      const store = useRunStore();
      store.showManualChat("ill-1");
      expect(store.chatToggle["ill-1"]).toBe("shown");
      store.hideManualChat("ill-1");
      expect(store.chatToggle["ill-1"]).toBe("hidden");
      // Unrelated ids stay untouched.
      expect(store.chatToggle["ill-2"]).toBeUndefined();
    });

    it("illustration_completed clears any chat toggle for that illustration", () => {
      const store = useRunStore();
      store.handleSseEvent({
        type: "snapshot",
        data: {
          run: makeRun(),
          illustrations: [makeIllustration({ state: "MANUAL_CHATTING" })],
        },
      });
      store.showManualChat("ill-1");
      expect(store.chatToggle["ill-1"]).toBe("shown");

      store.handleSseEvent({
        type: "illustration_completed",
        data: { illustration_id: "ill-1", scene_index: 0, image_url: "/static/x.png" },
      });
      // Hide takes precedence so the new image is shown.
      expect(store.chatToggle["ill-1"]).toBe("hidden");
    });

    it("regenerateIllustration POSTs, applies returned session, and shows chat without clearing image_url", async () => {
      const store = useRunStore();
      store.handleSseEvent({
        type: "snapshot",
        data: {
          run: makeRun(),
          illustrations: [
            makeIllustration({
              state: "COMPLETED",
              image_url: "/static/old.png",
              manual_attempts: 1,
            }),
          ],
        },
      });

      const originalFetch = globalThis.fetch;
      globalThis.fetch = async () =>
        ({
          ok: true,
          json: async () => ({
            illustration_id: "ill-1",
            state: "MANUAL_CHATTING",
            manual_attempts: 1,
            messages: [
              {
                id: "m-1",
                role: "assistant",
                content: "welcome back",
                image_url: null,
                manual_attempt_index: null,
                created_at: "2026-05-28T00:00:00Z",
              },
            ],
            last_image_url: null,
            sub_phase: "concept_design",
          }),
        }) as Response;

      try {
        await store.regenerateIllustration("ill-1");
      } finally {
        globalThis.fetch = originalFetch;
      }

      const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
      expect(ill?.state).toBe("MANUAL_CHATTING");
      expect(ill?.image_url).toBe("/static/old.png"); // preserved!
      expect(ill?.manual_session?.messages).toHaveLength(1);
      expect(ill?.manual_session?.sub_phase).toBe("concept_design");
      expect(store.chatToggle["ill-1"]).toBe("shown");
    });

    it("reset() clears chatToggle", () => {
      const store = useRunStore();
      store.showManualChat("ill-1");
      store.reset();
      expect(store.chatToggle["ill-1"]).toBeUndefined();
    });
  });

  describe("§ 6A.10 interactive image cards", () => {
    it("acceptManualAttempt POSTs and reflects COMPLETED state locally", async () => {
      const store = useRunStore();
      store.handleSseEvent({
        type: "snapshot",
        data: {
          run: makeRun(),
          illustrations: [
            makeIllustration({ id: "ill-1", state: "MANUAL_CHATTING", manual_attempts: 2 }),
          ],
        },
      });

      let postedBody: unknown = null;
      const originalFetch = globalThis.fetch;
      globalThis.fetch = async (_input, init) => {
        postedBody = init?.body ? JSON.parse(init.body as string) : null;
        return {
          ok: true,
          json: async () => ({
            illustration_id: "ill-1",
            state: "COMPLETED",
            manual_attempts: 2,
            messages: [],
            last_image_url: "/static/runs/run-1/scene_0.png",
            sub_phase: "feedback_gathering",
          }),
        } as Response;
      };

      try {
        await store.acceptManualAttempt("ill-1", 2);
      } finally {
        globalThis.fetch = originalFetch;
      }

      expect(postedBody).toEqual({ manual_attempt_index: 2 });
      const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
      expect(ill?.state).toBe("COMPLETED");
      expect(ill?.image_url).toBe("/static/runs/run-1/scene_0.png");
    });

    it("requestIterate POSTs and applies the returned session", async () => {
      const store = useRunStore();
      store.handleSseEvent({
        type: "snapshot",
        data: {
          run: makeRun(),
          illustrations: [
            makeIllustration({ id: "ill-1", state: "MANUAL_CHATTING", manual_attempts: 1 }),
          ],
        },
      });

      let calls = 0;
      const originalFetch = globalThis.fetch;
      globalThis.fetch = async () => {
        calls++;
        return {
          ok: true,
          json: async () => ({
            illustration_id: "ill-1",
            state: "MANUAL_CHATTING",
            manual_attempts: 1,
            messages: [
              {
                id: "msg-iter",
                role: "assistant",
                content: "Popíš čo je zle…",
                image_url: null,
                manual_attempt_index: null,
                created_at: "2026-05-28T12:00:00Z",
              },
            ],
            last_image_url: null,
            sub_phase: "feedback_gathering",
          }),
        } as Response;
      };

      try {
        await store.requestIterate("ill-1");
      } finally {
        globalThis.fetch = originalFetch;
      }

      expect(calls).toBe(1);
      const ill = store.illustrations.find((i: Illustration) => i.id === "ill-1");
      expect(ill?.manual_session?.messages).toHaveLength(1);
      expect(ill?.manual_session?.messages[0].content).toBe("Popíš čo je zle…");
    });
  });
});
