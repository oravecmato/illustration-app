import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import RunErrorBanner from "../src/components/RunErrorBanner.vue";
import type { Run } from "../src/types";

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: "run-1",
    status: "RUNNING",
    story_text: "story",
    style_guide: null,
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

  it("shows the NO_SUITABLE_SCENES guidance message for that error code", () => {
    const wrapper = mount(RunErrorBanner, {
      props: {
        run: makeRun({ status: "FAILED", error_code: "NO_SUITABLE_SCENES" }),
      },
    });
    expect(wrapper.text()).toContain("Zadaný text nie je vhodný");
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
