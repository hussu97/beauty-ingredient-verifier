import { describe, expect, it } from "vitest";
import { firstImageUrl, formatConfidence } from "../lib/format";
import { severityClass, severityLabel } from "../lib/severity";

describe("format utilities", () => {
  it("formats confidence", () => {
    expect(formatConfidence(0.624)).toBe("62%");
    expect(formatConfidence(null)).toBe("unknown");
  });

  it("selects front image first", () => {
    expect(
      firstImageUrl([
        { kind: "ingredients", url: "ingredients.jpg" },
        { kind: "front", url: "front.jpg" },
      ]),
    ).toBe("front.jpg");
  });

  it("labels severity", () => {
    expect(severityLabel("moderate")).toBe("Moderate");
    expect(severityClass("high")).toBe("severity-high");
  });
});
