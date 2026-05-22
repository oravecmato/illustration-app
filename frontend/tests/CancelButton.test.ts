import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import CancelButton from "../src/components/CancelButton.vue";

describe("CancelButton", () => {
  it("is visible when run status is RUNNING", () => {
    const wrapper = mount(CancelButton, {
      props: { runStatus: "RUNNING" },
    });
    expect(wrapper.find("button").exists()).toBe(true);
  });

  it("is not visible when run status is COMPLETED", () => {
    const wrapper = mount(CancelButton, {
      props: { runStatus: "COMPLETED" },
    });
    expect(wrapper.find("button").exists()).toBe(false);
  });

  it("is not visible when run status is FAILED", () => {
    const wrapper = mount(CancelButton, {
      props: { runStatus: "FAILED" },
    });
    expect(wrapper.find("button").exists()).toBe(false);
  });

  it("is not visible when run status is CANCELLED", () => {
    const wrapper = mount(CancelButton, {
      props: { runStatus: "CANCELLED" },
    });
    expect(wrapper.find("button").exists()).toBe(false);
  });

  it("shows inline confirmation on click", async () => {
    const wrapper = mount(CancelButton, {
      props: { runStatus: "RUNNING" },
    });
    await wrapper.find("button").trigger("click");
    expect(wrapper.text()).toContain("Naozaj zrušiť?");
    expect(wrapper.text()).toContain("Áno");
    expect(wrapper.text()).toContain("Nie");
  });

  it("emits cancel event on confirmation", async () => {
    const wrapper = mount(CancelButton, {
      props: { runStatus: "RUNNING" },
    });
    await wrapper.find("button").trigger("click");
    // Click "Áno"
    const buttons = wrapper.findAll("button");
    const yesButton = buttons.find((b) => b.text() === "Áno");
    expect(yesButton).toBeDefined();
    await yesButton!.trigger("click");
    expect(wrapper.emitted("cancel")).toBeTruthy();
  });

  it("does not emit cancel when Nie is clicked", async () => {
    const wrapper = mount(CancelButton, {
      props: { runStatus: "RUNNING" },
    });
    await wrapper.find("button").trigger("click");
    const buttons = wrapper.findAll("button");
    const noButton = buttons.find((b) => b.text() === "Nie");
    await noButton!.trigger("click");
    expect(wrapper.emitted("cancel")).toBeFalsy();
  });
});
