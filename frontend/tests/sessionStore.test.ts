import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useSessionStore } from "../src/stores/session";
import type { CollectedBrief, Session } from "../src/types";

vi.mock("../src/services/api", () => ({
  createSession: vi.fn(),
  getSession: vi.fn(),
  postSessionMessage: vi.fn(),
}));

import {
  createSession,
  getSession,
  postSessionMessage,
} from "../src/services/api";

const createSessionMock = vi.mocked(createSession);
const getSessionMock = vi.mocked(getSession);
const postSessionMessageMock = vi.mocked(postSessionMessage);

function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: "sess-1",
    state: "CHATTING",
    source_language: null,
    detected_language: null,
    topic_short: null,
    collected_brief: null,
    run_id: null,
    error_code: null,
    error_message: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    messages: [
      {
        id: "m-1",
        role: "assistant",
        content: "Ahoj!",
        created_at: "2024-01-01T00:00:00Z",
      },
    ],
    ...overrides,
  };
}

function makeBrief(): CollectedBrief {
  return {
    characters: [
      { role: "male", name_in_story: "Adam", short_description: "chlapec so zelenými vlasmi" },
    ],
    main_character_role: "male",
    topic: "prvý deň v škole",
    notes: "",
    non_human_entities: [],
  };
}

describe("sessionStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("start() creates a session and resets phase to gathering", async () => {
    const session = makeSession();
    createSessionMock.mockResolvedValue(session);

    const store = useSessionStore();
    await store.start();

    expect(createSessionMock).toHaveBeenCalledOnce();
    expect(store.session?.id).toBe("sess-1");
    // start() prepends a synthetic welcome message in front of the
    // server's transcript, so the total is server-messages + 1.
    expect(store.messages).toHaveLength(2);
    expect(store.messages[0].id).toBe("welcome");
    expect(store.phase).toBe("gathering");
    expect(store.errorMessage).toBeNull();
  });

  it("sendMessage() updates session and phase on awaiting_confirmation", async () => {
    createSessionMock.mockResolvedValue(makeSession());
    const updated = makeSession({
      state: "AWAITING_CONFIRMATION",
      collected_brief: makeBrief(),
      messages: [
        { id: "m-1", role: "assistant", content: "Ahoj!", created_at: "t0" },
        { id: "m-2", role: "user", content: "chcem príbeh", created_at: "t1" },
        { id: "m-3", role: "assistant", content: "Zhrnutie...", created_at: "t2" },
      ],
    });
    postSessionMessageMock.mockResolvedValue({ session: updated, phase: "awaiting_confirmation" });

    const store = useSessionStore();
    await store.start();
    const runId = await store.sendMessage("chcem príbeh");

    expect(postSessionMessageMock).toHaveBeenCalledWith("sess-1", "chcem príbeh");
    expect(store.session?.state).toBe("AWAITING_CONFIRMATION");
    expect(store.messages).toHaveLength(3);
    expect(store.phase).toBe("awaiting_confirmation");
    expect(runId).toBeNull();
  });

  it("sendMessage() returns pre-allocated run_id when phase becomes confirmed", async () => {
    createSessionMock.mockResolvedValue(
      makeSession({ state: "AWAITING_CONFIRMATION", collected_brief: makeBrief() }),
    );
    const confirmed = makeSession({
      state: "FINALIZING",
      run_id: "run-99",
      collected_brief: makeBrief(),
      messages: [
        { id: "m-1", role: "assistant", content: "Ahoj!", created_at: "t0" },
        { id: "m-2", role: "user", content: "áno", created_at: "t1" },
        {
          id: "m-3",
          role: "assistant",
          content: "Skvelé, ide na to. Pripravujem príbeh a ilustrácie…",
          created_at: "t2",
        },
      ],
    });
    postSessionMessageMock.mockResolvedValue({
      session: confirmed,
      phase: "confirmed",
      run_id: "run-99",
    });

    const store = useSessionStore();
    await store.start();
    const runId = await store.sendMessage("áno");

    expect(runId).toBe("run-99");
    expect(store.phase).toBe("confirmed");
  });

  it("sendMessage() shows optimistic row immediately, before POST resolves", async () => {
    createSessionMock.mockResolvedValue(makeSession());

    let resolvePost!: (value: { session: Session; phase: "awaiting_confirmation" }) => void;
    postSessionMessageMock.mockImplementation(
      () =>
        new Promise((res) => {
          resolvePost = res as never;
        }),
    );

    const store = useSessionStore();
    await store.start();
    // welcome + the mocked session's "Ahoj!" assistant message
    expect(store.messages).toHaveLength(2);

    // Don't await yet — we want to inspect the optimistic state mid-flight.
    const pending = store.sendMessage("hello");

    // Optimistic row is present, pending=true, and at the end of the list.
    expect(store.messages).toHaveLength(3);
    const optimistic = store.messages[2];
    expect(optimistic.role).toBe("user");
    expect(optimistic.content).toBe("hello");
    expect(optimistic.pending).toBe(true);
    expect(optimistic.client_id).toBeDefined();
    expect(store.isSending).toBe(true);

    // Resolve the POST and let reconciliation finish.
    const resolved = makeSession({
      state: "AWAITING_CONFIRMATION",
      messages: [
        { id: "m-1", role: "assistant", content: "Ahoj!", created_at: "t0" },
        { id: "m-2", role: "user", content: "hello", created_at: "t1" },
        { id: "m-3", role: "assistant", content: "Súhrn…", created_at: "t2" },
      ],
    });
    resolvePost({ session: resolved, phase: "awaiting_confirmation" });
    await pending;

    // Optimistic row replaced in place; index of the user message is
    // unchanged (still position 1).
    expect(store.messages).toHaveLength(3);
    expect(store.messages[1].id).toBe("m-2");
    expect(store.messages[1].pending).toBeFalsy();
    expect(store.messages[1].content).toBe("hello");
  });

  it("sendMessage() rolls back optimistic row and restores draft on failure", async () => {
    createSessionMock.mockResolvedValue(makeSession());
    postSessionMessageMock.mockRejectedValue(new Error("network down"));

    const store = useSessionStore();
    await store.start();
    // welcome + the mocked session's "Ahoj!" assistant message
    expect(store.messages).toHaveLength(2);

    await expect(store.sendMessage("hi")).rejects.toThrow("network down");

    // Optimistic row removed; welcome + server message remain.
    expect(store.messages).toHaveLength(2);
    expect(store.errorMessage).toBe("network down");
    expect(store.lastFailedDraft).toBe("hi");
    expect(store.isSending).toBe(false);
    expect(store.session?.state).toBe("CHATTING");
  });

  it("clearFailedDraft() clears the restored draft", async () => {
    createSessionMock.mockResolvedValue(makeSession());
    postSessionMessageMock.mockRejectedValue(new Error("oops"));

    const store = useSessionStore();
    await store.start();
    await expect(store.sendMessage("hi")).rejects.toThrow();
    expect(store.lastFailedDraft).toBe("hi");

    store.clearFailedDraft();
    expect(store.lastFailedDraft).toBeNull();
  });

  it("refresh() loads session from server", async () => {
    const session = makeSession({ state: "FINALIZED", run_id: "run-9" });
    getSessionMock.mockResolvedValue(session);

    const store = useSessionStore();
    await store.refresh("sess-1");

    expect(getSessionMock).toHaveBeenCalledWith("sess-1");
    expect(store.session?.run_id).toBe("run-9");
  });

  it("reset() clears state", async () => {
    createSessionMock.mockResolvedValue(makeSession());
    const store = useSessionStore();
    await store.start();

    store.reset();

    expect(store.session).toBeNull();
    expect(store.messages).toHaveLength(0);
    expect(store.phase).toBe("gathering");
    expect(store.errorMessage).toBeNull();
    expect(store.lastFailedDraft).toBeNull();
  });
});
