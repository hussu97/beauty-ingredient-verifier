import { describe, expect, it } from "vitest";
import { harmLevelFor, harmLevels } from "../lib/harmScale";

describe("harm scale", () => {
  it("keeps unknown as the first non-clear state", () => {
    expect(harmLevels[0].severity).toBe("unknown");
    expect(harmLevels[0].meaning).toContain("not the same as cleared");
  });

  it("finds severity descriptions case-insensitively", () => {
    expect(harmLevelFor("Moderate").label).toBe("Moderate");
  });

  it("falls back to unknown for unsupported labels", () => {
    expect(harmLevelFor("clear").severity).toBe("unknown");
  });
});
