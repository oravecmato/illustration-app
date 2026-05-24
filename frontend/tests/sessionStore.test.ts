import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useSessionStore } from "../src/stores/session";
import type { CollectedBrief, Session } from "../src/types";

vi.mock("../src/services/api", () => ({
  createSession: vi.fn(),
  getSession: vi.fn(),
  postSessionMessage: vi.fn(),
  finalizeSession: vi.fn(),
}));

import {
  createSession,
  finalizeSession,
  getSession,
  postSessionMessage,
} from "../src/services/api";

const createSessionMock = vi.mocked(createSession);
const getSessionMock = vi.mocked(getSession);
const postSessionMessageMock = vi.mocked(postSessionMessage);
const finalizeSessionMock = vi.mocked(finalizeSession);

function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: "sess-1",
    state: "CHATTING",
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
    topic: "prvý deň v škole",
    notes: "",
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
    expect(store.messages).toHaveLength(1);
    expect(store.phase).toBe("gathering");
    expect(store.errorMessage).toBeNull();
  });

  it("sendMessage() updates session and phase", async () => {
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
    await store.sendMessage("chcem príbeh");

    expect(postSessionMessageMock).toHaveBeenCalledWith("sess-1", "chcem príbeh");
    expect(store.session?.state).toBe("AWAITING_CONFIRMATION");
    expect(store.messages).toHaveLength(3);
    expect(store.phase).toBe("awaiting_confirmation");
    expect(store.canFinalize).toBe(true);
  });

  it("canFinalize is false while still gathering", async () => {
    createSessionMock.mockResolvedValue(makeSession());
    const store = useSessionStore();
    await store.start();

    expect(store.canFinalize).toBe(false);
  });

  it("sendMessage() sets errorMessage and re-throws on failure", async () => {
    createSessionMock.mockResolvedValue(makeSession());
    postSessionMessageMock.mockRejectedValue(new Error("network down"));

    const store = useSessionStore();
    await store.start();

    await expect(store.sendMessage("hi")).rejects.toThrow("network down");
    expect(store.errorMessage).toBe("network down");
    expect(store.isSending).toBe(false);
  });

  it("finalize() returns run_id from the API", async () => {
    createSessionMock.mockResolvedValue(makeSession({ state: "AWAITING_CONFIRMATION" }));
    finalizeSessionMock.mockResolvedValue({ run_id: "run-42" });

    const store = useSessionStore();
    await store.start();
    const runId = await store.finalize();

    expect(runId).toBe("run-42");
    expect(finalizeSessionMock).toHaveBeenCalledWith("sess-1");
    expect(store.isFinalizing).toBe(false);
  });

  it("finalize() sets errorMessage and re-throws on failure", async () => {
    createSessionMock.mockResolvedValue(makeSession({ state: "AWAITING_CONFIRMATION" }));
    finalizeSessionMock.mockRejectedValue(new Error("conflict"));

    const store = useSessionStore();
    await store.start();

    await expect(store.finalize()).rejects.toThrow("conflict");
    expect(store.errorMessage).toBe("conflict");
    expect(store.isFinalizing).toBe(false);
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
  });
});
