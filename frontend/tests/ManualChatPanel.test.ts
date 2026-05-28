import { describe, it, expect, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import ManualChatPanel from "../src/components/ManualChatPanel.vue";
import type { Illustration, ManualMessage } from "../src/types";

function makeMessage(overrides: Partial<ManualMessage> = {}): ManualMessage {
  return {
    id: `msg-${Math.random()}`,
    role: "assistant",
    content: "",
    image_url: null,
    manual_attempt_index: null,
    created_at: "2026-05-28T12:00:00Z",
    ...overrides,
  };
}

function makeIllustration(messages: ManualMessage[]): Illustration {
  return {
    id: "ill-1",
    scene_index: 0,
    scene_excerpt: "Once upon a time…",
    paragraph_index: 0,
    character_role: "female",
    current_workflow: null,
    current_concept: "A girl on a stage",
    state: "MANUAL_CHATTING",
    concept_attempt: 1,
    prompt_attempt: 1,
    image_url: null,
    companion: null,
    manual_attempts: messages.filter((m) => m.role === "image").length,
    manual_session: {
      messages,
      manual_attempts: messages.filter((m) => m.role === "image").length,
      last_image_url: null,
      sub_phase: "feedback_gathering",
    },
  };
}

describe("ManualChatPanel input lock (§ 6A.10)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("locks input when the latest message is an image (variant 1 active)", () => {
    const messages = [
      makeMessage({ id: "m1", role: "user", content: "concept text" }),
      makeMessage({
        id: "img1",
        role: "image",
        image_url: "/static/x.png",
        manual_attempt_index: 1,
      }),
    ];
    const wrapper = mount(ManualChatPanel, {
      props: { illustration: makeIllustration(messages) },
      global: {
        stubs: { ManualImageCard: true },
      },
    });
    const input = wrapper.get('[data-testid="manual-input"]');
    expect(input.attributes("disabled")).toBeDefined();
    expect(wrapper.find('[data-testid="manual-input-locked"]').exists()).toBe(true);
  });

  it("unlocks input once a non-image message follows the latest image", () => {
    const messages = [
      makeMessage({
        id: "img1",
        role: "image",
        image_url: "/static/x.png",
        manual_attempt_index: 1,
      }),
      makeMessage({ id: "iter1", role: "assistant", content: "Describe what's wrong…" }),
    ];
    const wrapper = mount(ManualChatPanel, {
      props: { illustration: makeIllustration(messages) },
      global: {
        stubs: { ManualImageCard: true },
      },
    });
    const input = wrapper.get('[data-testid="manual-input"]');
    expect(input.attributes("disabled")).toBeUndefined();
    expect(wrapper.find('[data-testid="manual-input-locked"]').exists()).toBe(false);
  });

  it("input is not locked when no image has rendered yet", () => {
    const messages = [
      makeMessage({ id: "welcome", role: "assistant", content: "Hello!" }),
    ];
    const wrapper = mount(ManualChatPanel, {
      props: { illustration: makeIllustration(messages) },
      global: {
        stubs: { ManualImageCard: true },
      },
    });
    const input = wrapper.get('[data-testid="manual-input"]');
    expect(input.attributes("disabled")).toBeUndefined();
  });
});
