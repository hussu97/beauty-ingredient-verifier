import { describe, expect, it } from "vitest";
import type { ProductIngredient, RiskEvaluation, ScanJob } from "../api/types";
import { getMatchedProductCode, getTopCandidate, mergeIngredientWarnings, sortIngredientsAlphabetically } from "../lib/result";

const baseScan: ScanJob = {
  scan_code: "scn_1",
  upload_filename: "product.jpg",
  status: "completed",
  barcode: null,
  ocr_text: null,
  extracted_brand: null,
  extracted_product_name: null,
  extracted_ingredient_text: null,
  confidence_score: 0.84,
  matched_product_code: null,
  error_message: null,
  created_at: "2026-06-17T00:00:00Z",
  updated_at: "2026-06-17T00:00:00Z",
  candidates: [
    {
      candidate_code: "cand_2",
      product_code: "prd_second",
      candidate_name: "Second",
      brand_name: "Brand",
      confidence_score: 0.74,
      match_reasons: ["ocr"],
      rank: 2,
    },
    {
      candidate_code: "cand_1",
      product_code: "prd_first",
      candidate_name: "First",
      brand_name: "Brand",
      confidence_score: 0.84,
      match_reasons: ["CLIP image similarity"],
      rank: 1,
    },
  ],
};

const ingredients: ProductIngredient[] = [
  {
    product_ingredient_code: "pi_1",
    raw_name: "Parfum",
    rank: 3,
    percent_min: null,
    percent_max: null,
    percent_estimate: null,
    ingredient: {
      ingredient_code: "ing_fragrance",
      canonical_name: "Parfum",
      inci_name: "Parfum",
      regulatory_status: "unknown",
    },
  },
  {
    product_ingredient_code: "pi_2",
    raw_name: "Water",
    rank: 1,
    percent_min: null,
    percent_max: null,
    percent_estimate: null,
    ingredient: {
      ingredient_code: "ing_water",
      canonical_name: "Water",
      inci_name: "Aqua",
      regulatory_status: "unknown",
    },
  },
];

const risk: RiskEvaluation = {
  evaluation_code: "eval_1",
  product_code: "prd_first",
  product_name: "First",
  severity: "moderate",
  score: 2,
  side_effects: ["itching"],
  matched_rule_codes: ["rule_1"],
  matched_ingredients: [
    {
      ingredient_code: "ing_fragrance",
      ingredient_name: "Parfum",
      rule_code: "rule_1",
      title: "Fragrance allergen sensitivity",
      summary: "May bother fragrance-sensitive users.",
      severity: "moderate",
      severity_score: 2,
      side_effects: ["itching", "rash"],
      confidence_score: 0.8,
      evidence_kind: "regulatory",
      source_record_code: "src_1",
      source_url: "https://example.com",
    },
  ],
  explanation: "Matched one ingredient rule.",
  disclaimer: "Not medical advice.",
};

describe("scan result utilities", () => {
  it("selects the top candidate by rank unless an explicit match exists", () => {
    expect(getTopCandidate(baseScan)?.product_code).toBe("prd_first");
    expect(getMatchedProductCode({ ...baseScan, matched_product_code: "prd_second" })).toBe("prd_second");
  });

  it("merges risk matches into product ingredients", () => {
    const merged = mergeIngredientWarnings(ingredients, risk);

    expect(merged.map((item) => item.raw_name)).toEqual(["Parfum", "Water"]);
    expect(merged[0].severity).toBe("moderate");
    expect(merged[0].matches[0].title).toBe("Fragrance allergen sensitivity");
    expect(merged[0].sideEffects).toEqual(["itching", "rash"]);
    expect(merged[1].severity).toBe("unknown");
    expect(merged[1].warningLabel).toBe("No warning found");
  });

  it("sorts ingredients alphabetically for UI display", () => {
    expect(sortIngredientsAlphabetically([...ingredients].reverse()).map((item) => item.raw_name)).toEqual([
      "Parfum",
      "Water",
    ]);
  });
});
