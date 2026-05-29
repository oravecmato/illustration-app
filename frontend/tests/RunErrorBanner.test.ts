import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import RunErrorBanner from "../src/components/RunErrorBanner.vue";
import type { Run, StyleGuide } from "../src/types";

function makeStyleGuide(): StyleGuide {
  return {
    overall_style_positive: "watercolor",
    overall_style_negative: "photorealistic",
    character_lora: "mha_character",
    character_baseline_description: "A boy",
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
    story_blocks: [{ type: "paragraph", text: "Bol raz." }],
    style_guide: makeStyleGuide(),
    illustration_count: 0,
    completed_count: 0,
    failed_count: 0,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    error_code: null,
    error_message: null,
    ...overrides,
  };
}

describe("RunErrorBanner", () => {
  it("is hidden when run status is not FAILED", () => {
    const wrapper = mount(RunErrorBanner, {
      props: { run: makeRun({ status: "RUNNING" }) },
    });
    expect(wrapper.find(".run-error-banner").exists()).toBe(false);
  });

  it("is hidden when run is null", () => {
    const wrapper = mount(RunErrorBanner, {
      props: { run: null },
    });
    expect(wrapper.find(".run-error-banner").exists()).toBe(false);
  });

  it("is visible when run status is FAILED", () => {
    const wrapper = mount(RunErrorBanner, {
      props: {
        run: makeRun({ status: "FAILED", error_code: "INTERNAL_ERROR" }),
      },
    });
    expect(wrapper.find(".run-error-banner").exists()).toBe(true);
  });

  it("shows the TRANSLATE_FAILED guidance message for that error code", () => {
    const wrapper = mount(RunErrorBanner, {
      props: {
        run: makeRun({ status: "FAILED", error_code: "TRANSLATE_FAILED" }),
      },
    });
    expect(wrapper.text()).toContain("Preklad ilustrácií");
  });

  it("falls back to INTERNAL_ERROR message for unknown error_code", () => {
    const wrapper = mount(RunErrorBanner, {
      props: {
        run: makeRun({ status: "FAILED", error_code: "SOME_UNKNOWN_CODE" }),
      },
    });
    expect(wrapper.text()).toContain("neočakávaná chyba");
  });
});
