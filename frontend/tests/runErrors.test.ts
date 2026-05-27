import { describe, it, expect } from "vitest";
import { runErrorKey } from "../src/i18n/runErrors";

describe("runErrorKey", () => {
  it("maps INTERNAL_ERROR to the correct key", () => {
    expect(runErrorKey("INTERNAL_ERROR")).toBe("errors.run.internal_error");
  });

  it("maps TRANSLATE_FAILED to the correct key", () => {
    expect(runErrorKey("TRANSLATE_FAILED")).toBe("errors.run.translate_failed");
  });

  it("falls back to INTERNAL_ERROR key for unknown error codes", () => {
    expect(runErrorKey("SOME_UNKNOWN_CODE")).toBe("errors.run.internal_error");
  });

  it("returns empty string for null error code", () => {
    expect(runErrorKey(null)).toBe("");
  });

  it("returns empty string for undefined error code", () => {
    expect(runErrorKey(undefined)).toBe("");
  });
});
