import { describe, it, expect } from "vitest";
import { getRunErrorMessage } from "../src/i18n/runErrors";

describe("getRunErrorMessage", () => {
  it("maps NO_SUITABLE_SCENES to the dedicated Slovak message", () => {
    const msg = getRunErrorMessage("NO_SUITABLE_SCENES");
    expect(msg).toContain("Zadaný text nie je vhodný");
    expect(msg).toContain("jednou postavou");
  });

  it("maps STEP0_FAILED to the correct Slovak message", () => {
    const msg = getRunErrorMessage("STEP0_FAILED");
    expect(msg).toContain("Analýza textu zlyhala");
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
