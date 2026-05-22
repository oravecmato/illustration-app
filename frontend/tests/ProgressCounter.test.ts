import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import ProgressCounter from "../src/components/ProgressCounter.vue";

describe("ProgressCounter", () => {
  it("renders 'Hotové: K z N' when illustration_count is known", () => {
    const wrapper = mount(ProgressCounter, {
      props: { completedCount: 2, illustrationCount: 5 },
    });
    expect(wrapper.text()).toContain("Hotové: 2 z 5");
  });

  it("renders 'Hotové: 0 z —' when illustration_count is null", () => {
    const wrapper = mount(ProgressCounter, {
      props: { completedCount: 0, illustrationCount: null },
    });
    expect(wrapper.text()).toContain("Hotové: 0 z —");
  });

  it("renders progress bar when illustration_count is known", () => {
    const wrapper = mount(ProgressCounter, {
      props: { completedCount: 3, illustrationCount: 5 },
    });
    expect(wrapper.find(".progress-bar").exists()).toBe(true);
  });

  it("is hidden when hidden prop is true (e.g. NO_SUITABLE_SCENES)", () => {
    const wrapper = mount(ProgressCounter, {
      props: { completedCount: 0, illustrationCount: null, hidden: true },
    });
    expect(wrapper.find(".progress-counter").exists()).toBe(false);
  });

  it("is visible when hidden prop is false", () => {
    const wrapper = mount(ProgressCounter, {
      props: { completedCount: 0, illustrationCount: null, hidden: false },
    });
    expect(wrapper.find(".progress-counter").exists()).toBe(true);
  });
});
