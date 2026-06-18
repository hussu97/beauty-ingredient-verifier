import { describe, expect, it } from "vitest";
import {
  defaultProfile,
  isDefaultProfile,
  normalizeProfile,
  profileOptions,
  profileSummary,
} from "../lib/profile";

describe("profile utilities", () => {
  it("normalizes old free-text aliases into selectable profile values", () => {
    expect(
      normalizeProfile({
        skin_types: ["Reactive"],
        age_band: "toddler",
        sensitivities: ["perfume", "AHA", "MI"],
        allergies: ["natural rubber", "p-phenylenediamine"],
        conditions: ["allergic contact dermatitis"],
      }),
    ).toMatchObject({
      skin_types: ["sensitive"],
      age_band: "child",
      sensitivities: ["fragrance", "acids", "isothiazolinone"],
      allergies: ["latex", "ppd"],
      conditions: ["contact dermatitis"],
    });
  });

  it("drops unsupported profile values instead of sending arbitrary strings to rules", () => {
    expect(
      normalizeProfile({
        hair_types: ["curly"],
        sensitivities: ["unsupported"],
        allergies: ["unknown allergy"],
      }),
    ).toMatchObject({
      hair_types: [],
      sensitivities: [],
      allergies: [],
    });
  });

  it("detects and summarizes the default profile", () => {
    expect(isDefaultProfile(defaultProfile)).toBe(true);
    expect(profileSummary(defaultProfile)).toBe("sensitive skin + fragrance / perfume sensitivity");
  });

  it("exposes only select-backed profile fields", () => {
    expect(Object.keys(profileOptions.fields)).toEqual([
      "skin_types",
      "scalp_types",
      "age_band",
      "sensitivities",
      "allergies",
      "conditions",
    ]);
  });

  it("includes the profile vocabulary needed by Vercel frontend builds", () => {
    expect(profileOptions.version).toBe("2026-06-18.1");
    expect(profileOptions.fields.sensitivities.options.map((option) => option.value)).toContain("fragrance");
    expect(profileOptions.booleans.pregnancy.aliases).toContain("pregnant");
  });
});
