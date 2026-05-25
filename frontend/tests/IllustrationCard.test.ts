import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import { reactive } from "vue";
import IllustrationCard from "../src/components/IllustrationCard.vue";
import type { Illustration } from "../src/types";

function makeIllustration(overrides: Partial<Illustration> = {}): Illustration {
  return {
    id: "ill-1",
    scene_index: 0,
    scene_excerpt: "Once upon a time in a land far away...",
    character_role: "male",
    current_concept: "A boy crying with tears on his cheeks",
    state: "PENDING",
    concept_attempt: 1,
    prompt_attempt: 1,
    image_url: null,
    ...overrides,
  };
}

const STATE_LABELS: Record<string, string> = {
  PENDING: "Čaká",
  GENERATING_PROMPTS: "Pripravujem prompty",
  RENDERING: "Kreslím (pokus",
  EVALUATING: "Vyhodnocujem výsledok",
  REVISING_PROMPTS: "Upravujem prompty",
  RETHINKING_CONCEPT: "Premýšľam koncept",
  COMPLETED: "Hotovo",
  FAILED: "Nepodarilo sa",
  CANCELLED: "Zrušené",
};

describe("IllustrationCard", () => {
  it("shows scene number", () => {
    const wrapper = mount(IllustrationCard, {
      props: { illustration: makeIllustration({ scene_index: 2 }) },
    });
    expect(wrapper.text()).toContain("Ilustrácia 3");
  });

  it.each(Object.entries(STATE_LABELS))("shows correct Slovak label for state %s", (state, label) => {
    const wrapper = mount(IllustrationCard, {
      props: {
        illustration: makeIllustration({
          state: state as Illustration["state"],
          prompt_attempt: 1,
          concept_attempt: 1,
        }),
      },
    });
    expect(wrapper.text()).toContain(label);
  });

  const nonTerminalStates: Illustration["state"][] = [
    "PENDING",
    "GENERATING_PROMPTS",
    "RENDERING",
    "EVALUATING",
    "REVISING_PROMPTS",
    "RETHINKING_CONCEPT",
  ];

  it.each(nonTerminalStates)("shows spinner for non-terminal state %s", (state) => {
    const wrapper = mount(IllustrationCard, {
      props: { illustration: makeIllustration({ state }) },
    });
    expect(wrapper.find(".spinner").exists()).toBe(true);
  });

  const terminalStates: Illustration["state"][] = ["COMPLETED", "FAILED", "CANCELLED"];

  it.each(terminalStates)("hides spinner for terminal state %s", (state) => {
    const wrapper = mount(IllustrationCard, {
      props: {
        illustration: makeIllustration({
          state,
          image_url: state === "COMPLETED" ? "/static/runs/r/scene_0.png" : null,
        }),
      },
    });
    expect(wrapper.find(".spinner").exists()).toBe(false);
  });

  const attemptStates: Illustration["state"][] = [
    "RENDERING",
    "REVISING_PROMPTS",
    "RETHINKING_CONCEPT",
  ];

  it.each(attemptStates)(
    "shows attempt counter during %s",
    (state) => {
      const wrapper = mount(IllustrationCard, {
        props: {
          illustration: makeIllustration({ state, prompt_attempt: 2, concept_attempt: 1 }),
        },
      });
      expect(wrapper.text()).toContain("pokus");
    }
  );

  it("does not show attempt counter in PENDING state", () => {
    const wrapper = mount(IllustrationCard, {
      props: { illustration: makeIllustration({ state: "PENDING" }) },
    });
    expect(wrapper.text()).not.toContain("pokus");
  });

  it("renders image on COMPLETED", () => {
    const wrapper = mount(IllustrationCard, {
      props: {
        illustration: makeIllustration({
          state: "COMPLETED",
          image_url: "/static/runs/r/scene_0.png",
        }),
      },
    });
    const img = wrapper.find("img");
    expect(img.exists()).toBe(true);
    expect(img.attributes("src")).toBe("/static/runs/r/scene_0.png");
  });

  it("renders generic Slovak failure text on FAILED", () => {
    const wrapper = mount(IllustrationCard, {
      props: {
        illustration: makeIllustration({ state: "FAILED" }),
      },
    });
    expect(wrapper.text()).toContain("Túto ilustráciu sa nepodarilo vytvoriť");
  });

  it("shows CANCELLED card as greyed out", () => {
    const wrapper = mount(IllustrationCard, {
      props: { illustration: makeIllustration({ state: "CANCELLED" }) },
    });
    expect(wrapper.classes()).toContain("cancelled");
  });

  it("renders the current concept text", () => {
    const wrapper = mount(IllustrationCard, {
      props: {
        illustration: makeIllustration({ current_concept: "A boy holding a kite" }),
      },
    });
    const concept = wrapper.find("[data-testid='concept-text']");
    expect(concept.exists()).toBe(true);
    expect(concept.text()).toContain("A boy holding a kite");
  });

  it("reactively updates concept text when the same illustration object changes", async () => {
    // Hold a reference to a reactive illustration object. The runStore
    // mutates the same object's `current_concept` field on each
    // `illustration_state` SSE event; the card must re-render without
    // remounting (§ 9.1 Screen B).
    const illustration = reactive(makeIllustration({ current_concept: "Initial concept" }));
    const wrapper = mount(IllustrationCard, {
      props: { illustration },
    });
    expect(wrapper.find("[data-testid='concept-text']").text()).toContain("Initial concept");

    // Mutate the field in place (this mirrors what runStore does).
    illustration.current_concept = "Rethought concept";
    await wrapper.vm.$nextTick();

    expect(wrapper.find("[data-testid='concept-text']").text()).toContain("Rethought concept");
    expect(wrapper.find("[data-testid='concept-text']").text()).not.toContain("Initial concept");
  });
});
