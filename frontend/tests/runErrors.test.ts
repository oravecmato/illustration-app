import { describe, it, expect } from "vitest";
import { getRunErrorMessage } from "../src/i18n/runErrors";

describe("getRunErrorMessage", () => {
  it("maps CHAT_FAILED to the correct Slovak message", () => {
    const msg = getRunErrorMessage("CHAT_FAILED");
    expect(msg).toContain("Konverzácia");
  });

  it("maps STORY_BUILD_FAILED to the correct Slovak message", () => {
    const msg = getRunErrorMessage("STORY_BUILD_FAILED");
    expect(msg).toContain("Tvorba príbehu");
  });

  it("maps INTERNAL_ERROR to the correct Slovak message", () => {
    const msg = getRunErrorMessage("INTERNAL_ERROR");
    expect(msg).toContain("neočakávaná chyba");
  });

  it("falls back to INTERNAL_ERROR message for unknown error codes", () => {
    const knownMsg = getRunErrorMessage("INTERNAL_ERROR");
    const unknownMsg = getRunErrorMessage("SOME_UNKNOWN_CODE");
    expect(unknownMsg).toBe(knownMsg);
  });

  it("returns empty string for null error code", () => {
    expect(getRunErrorMessage(null)).toBe("");
  });

  it("returns empty string for undefined error code", () => {
    expect(getRunErrorMessage(undefined)).toBe("");
  });
});
