import type { ProductIngredient, RiskEvaluation, ScanCandidate, ScanJob } from "../api/types";
import { severityOrder } from "./severity";

export type IngredientRiskMatch = RiskEvaluation["matched_ingredients"][number];

export type IngredientWarning = ProductIngredient & {
  matches: IngredientRiskMatch[];
  severity: string;
  warningLabel: string;
  sideEffects: string[];
};

const ingredientCollator = new Intl.Collator(undefined, { sensitivity: "base" });

function ingredientDisplayName(ingredient: ProductIngredient): string {
  return ingredient.raw_name || ingredient.ingredient.canonical_name;
}

function severityRank(severity: string): number {
  const rank = severityOrder.indexOf(severity.toLowerCase());
  return rank === -1 ? 0 : rank;
}

export function getTopCandidate(scan: ScanJob | null): ScanCandidate | null {
  if (!scan || scan.candidates.length === 0) return null;
  const matched = scan.matched_product_code
    ? scan.candidates.find((candidate) => candidate.product_code === scan.matched_product_code)
    : null;
  return matched ?? [...scan.candidates].sort((a, b) => a.rank - b.rank)[0] ?? null;
}

export function getMatchedProductCode(scan: ScanJob | null): string | null {
  return scan?.matched_product_code ?? getTopCandidate(scan)?.product_code ?? null;
}

export function sortIngredientsAlphabetically<T extends ProductIngredient>(ingredients: T[]): T[] {
  return [...ingredients].sort((left, right) =>
    ingredientCollator.compare(ingredientDisplayName(left), ingredientDisplayName(right)),
  );
}

export function mergeIngredientWarnings(
  ingredients: ProductIngredient[],
  risk: RiskEvaluation | null | undefined,
): IngredientWarning[] {
  const matchesByIngredient = new Map<string, IngredientRiskMatch[]>();
  risk?.matched_ingredients.forEach((match) => {
    const existing = matchesByIngredient.get(match.ingredient_code) ?? [];
    existing.push(match);
    matchesByIngredient.set(match.ingredient_code, existing);
  });

  return sortIngredientsAlphabetically(ingredients).map((ingredient) => {
    const matches = matchesByIngredient.get(ingredient.ingredient.ingredient_code) ?? [];
    const severity = matches.reduce(
      (current, match) => (severityRank(match.severity) > severityRank(current) ? match.severity : current),
      "unknown",
    );
    const sideEffects = Array.from(new Set(matches.flatMap((match) => match.side_effects)));

    return {
      ...ingredient,
      matches,
      severity,
      sideEffects,
      warningLabel: matches.length ? `${severity} warning` : "No warning found",
    };
  });
}
