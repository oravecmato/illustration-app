import { describe, it, expect, beforeEach } from "vitest";
import { mount } from "@vue/test-utils";
import { setActivePinia, createPinia } from "pinia";
import ManualImageCard from "../src/components/ManualImageCard.vue";
import type { Illustration, ManualMessage } from "../src/types";

function makeIllustration(overrides: Partial<Illustration> = {}): Illustration {
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
    manual_attempts: 1,
    ...overrides,
  };
}

function makeMessage(overrides: Partial<ManualMessage> = {}): ManualMessage {
  return {
    id: "img-1",
    role: "image",
    content: "",
    image_url: "/static/runs/run-1/manual_0_1.png",
    manual_attempt_index: 1,
    concept_used: "A girl on a stage",
    positive_prompt: "1girl, brave, stage",
    negative_prompt: "blurry",
    created_at: "2026-05-28T12:00:00Z",
    ...overrides,
  };
}

describe("ManualImageCard", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders the attempt counter from message.manual_attempt_index", () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration(),
        message: makeMessage({ manual_attempt_index: 3 }),
        isLatestImage: true,
        hasMessagesAfter: false,
        budgetExhausted: false,
      },
    });
    expect(wrapper.get('[data-testid="manual-image-card-attempt"]').text()).toMatch(/3\/5/);
  });

  it("enables both popover triggers when provenance is present", () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration(),
        message: makeMessage(),
        isLatestImage: true,
        hasMessagesAfter: false,
        budgetExhausted: false,
      },
    });
    const concept = wrapper.get('[data-testid="manual-image-card-concept-trigger"]');
    const prompts = wrapper.get('[data-testid="manual-image-card-prompts-trigger"]');
    expect(concept.attributes("disabled")).toBeUndefined();
    expect(prompts.attributes("disabled")).toBeUndefined();
  });

  it("disables popover triggers when provenance fields are null (legacy rows)", () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration(),
        message: makeMessage({
          concept_used: null,
          positive_prompt: null,
          negative_prompt: null,
        }),
        isLatestImage: true,
        hasMessagesAfter: false,
        budgetExhausted: false,
      },
    });
    const concept = wrapper.get('[data-testid="manual-image-card-concept-trigger"]');
    const prompts = wrapper.get('[data-testid="manual-image-card-prompts-trigger"]');
    expect(concept.attributes("disabled")).toBeDefined();
    expect(prompts.attributes("disabled")).toBeDefined();
    expect(concept.attributes("aria-disabled")).toBe("true");
    expect(prompts.attributes("aria-disabled")).toBe("true");
  });

  it("shows Accept + Iterate buttons (footer variant 'choose') for the latest image with no follow-up", () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration(),
        message: makeMessage(),
        isLatestImage: true,
        hasMessagesAfter: false,
        budgetExhausted: false,
      },
    });
    expect(wrapper.find('[data-testid="manual-image-card-accept"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="manual-image-card-iterate"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="manual-image-card-use"]').exists()).toBe(false);
  });

  it("shows only Use (footer variant 'use') for older attempts (messages after)", () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration(),
        message: makeMessage(),
        isLatestImage: false,
        hasMessagesAfter: true,
        budgetExhausted: false,
      },
    });
    expect(wrapper.find('[data-testid="manual-image-card-use"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="manual-image-card-accept"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="manual-image-card-iterate"]').exists()).toBe(false);
  });

  it("shows only Use when budget is exhausted on the latest image", () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration({ manual_attempts: 5 }),
        message: makeMessage({ manual_attempt_index: 5 }),
        isLatestImage: true,
        hasMessagesAfter: false,
        budgetExhausted: true,
      },
    });
    expect(wrapper.find('[data-testid="manual-image-card-use"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="manual-image-card-iterate"]').exists()).toBe(false);
  });

  it("emits 'accept' when Accept is clicked", async () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration(),
        message: makeMessage(),
        isLatestImage: true,
        hasMessagesAfter: false,
        budgetExhausted: false,
      },
    });
    await wrapper.get('[data-testid="manual-image-card-accept"]').trigger("click");
    expect(wrapper.emitted("accept")).toBeTruthy();
    expect(wrapper.emitted("accept")?.length).toBe(1);
  });

  it("emits 'iterate' when Iterate is clicked", async () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration(),
        message: makeMessage(),
        isLatestImage: true,
        hasMessagesAfter: false,
        budgetExhausted: false,
      },
    });
    await wrapper.get('[data-testid="manual-image-card-iterate"]').trigger("click");
    expect(wrapper.emitted("iterate")).toBeTruthy();
    expect(wrapper.emitted("iterate")?.length).toBe(1);
  });

  it("emits 'accept' when Use is clicked on an older attempt", async () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration(),
        message: makeMessage(),
        isLatestImage: false,
        hasMessagesAfter: true,
        budgetExhausted: false,
      },
    });
    await wrapper.get('[data-testid="manual-image-card-use"]').trigger("click");
    expect(wrapper.emitted("accept")).toBeTruthy();
  });

  it("renders no footer when illustration is COMPLETED (defensive)", () => {
    const wrapper = mount(ManualImageCard, {
      props: {
        illustration: makeIllustration({ state: "COMPLETED" }),
        message: makeMessage(),
        isLatestImage: true,
        hasMessagesAfter: false,
        budgetExhausted: false,
      },
    });
    expect(wrapper.find('[data-testid="manual-image-card-accept"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="manual-image-card-iterate"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="manual-image-card-use"]').exists()).toBe(false);
  });
});
