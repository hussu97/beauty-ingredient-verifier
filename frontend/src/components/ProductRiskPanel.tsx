import { AlertTriangle, CheckCircle2, ExternalLink, Info, ShieldAlert } from "lucide-react";
import type { ProductDetail, RiskEvaluation } from "../api/types";
import { firstImageUrl, formatDate } from "../lib/format";
import { mergeIngredientWarnings } from "../lib/result";
import { severityClass, severityLabel } from "../lib/severity";
import StatusBadge from "./StatusBadge";

type Props = {
  product: ProductDetail;
  risk?: RiskEvaluation | null;
  isEvaluating?: boolean;
};

function severityTone(severity: string): "neutral" | "good" | "warn" | "danger" {
  const normalized = severity.toLowerCase();
  if (normalized === "critical" || normalized === "high") return "danger";
  if (normalized === "moderate") return "warn";
  if (normalized === "low" || normalized === "minimal") return "good";
  return "neutral";
}

export default function ProductRiskPanel({ product, risk, isEvaluating = false }: Props) {
  const imageUrl = firstImageUrl(product.images);
  const ingredientWarnings = mergeIngredientWarnings(product.ingredients, risk);

  return (
    <div className="product-risk-panel">
      <div className="product-result">
        <div className="product-image-stage">
          {imageUrl ? <img src={imageUrl} alt={product.name} /> : <span>{product.name.slice(0, 2)}</span>}
        </div>
        <div className="product-result-copy">
          <span className="eyebrow">{product.brand?.name ?? "Unknown brand"}</span>
          <h2>{product.name}</h2>
          <p>{product.category_text ?? "Uncategorized product"}</p>
          <div className="product-facts">
            <span>Barcode: {product.barcode ?? "not detected"}</span>
            <span>Updated: {formatDate(product.last_source_update_at)}</span>
          </div>
          {isEvaluating && <div className="loading-line">Checking profile-aware ingredient rules...</div>}
          {risk && (
            <div className={`risk-summary ${severityClass(risk.severity)}`}>
              {risk.score >= 3 ? <AlertTriangle size={22} /> : <CheckCircle2 size={22} />}
              <div>
                <strong>{severityLabel(risk.severity)} profile match</strong>
                <span>{risk.explanation}</span>
              </div>
            </div>
          )}
          <details className="read-more">
            <summary><Info size={15} /> Product source notes</summary>
            <p>Open product data can be incomplete or outdated. Treat unknowns as unknowns, not approvals.</p>
            {product.data_quality_warnings.map((warning) => (
              <span className="data-warning" key={warning}>{warning}</span>
            ))}
            {product.ingredient_text && <p className="raw-ingredients">{product.ingredient_text}</p>}
          </details>
        </div>
      </div>

      <section className="ingredient-section">
        <div className="section-heading">
          <div>
            <h2>Ingredients</h2>
            <p>Flagged only when a source-backed rule matches this product and profile.</p>
          </div>
        </div>
        <div className="ingredient-warning-list">
          {ingredientWarnings.map((item) => (
            <article className={`ingredient-warning-row ${severityClass(item.severity)}`} key={item.product_ingredient_code}>
              <div className="ingredient-name">
                <strong>{item.raw_name}</strong>
              </div>
              <div className="ingredient-warning-copy">
                <StatusBadge tone={severityTone(item.severity)}>{item.matches.length ? severityLabel(item.severity) : "No warning found"}</StatusBadge>
                {item.matches.length === 0 ? (
                  <span>No source-backed issue matched this profile.</span>
                ) : (
                  item.matches.map((match) => (
                    <div className="issue-card" key={match.rule_code}>
                      <strong>
                        <ShieldAlert size={15} />
                        {match.title}
                      </strong>
                      {match.side_effects.length > 0 && <span>Possible effects: {match.side_effects.join(", ")}</span>}
                      <details className="issue-detail">
                        <summary>Read evidence</summary>
                        <p>{match.summary}</p>
                        {match.source_url && (
                          <a href={match.source_url} target="_blank" rel="noreferrer">
                            Source <ExternalLink size={13} />
                          </a>
                        )}
                      </details>
                    </div>
                  ))
                )}
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
