import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { formatConfidence } from "../lib/format";
import { severityClass, severityLabel } from "../lib/severity";

export default function IngredientDetailPage() {
  const { ingredientCode } = useParams();
  const ingredientQuery = useQuery({
    queryKey: ["ingredient", ingredientCode],
    queryFn: () => api.ingredient(ingredientCode!),
    enabled: Boolean(ingredientCode),
  });
  const ingredient = ingredientQuery.data;

  if (ingredientQuery.isLoading) return <div className="page-stack">Loading ingredient...</div>;
  if (!ingredient) return <div className="page-stack">Ingredient not found.</div>;

  return (
    <div className="page-stack">
      <Link to="/admin/ingredients" className="back-link"><ArrowLeft size={16} /> Admin</Link>
      <header className="page-header">
        <div>
          <span className="eyebrow">Ingredient</span>
          <h1>{ingredient.canonical_name}</h1>
          <p>INCI: {ingredient.inci_name ?? "unknown"} · CAS: {ingredient.cas_number ?? "unknown"}</p>
        </div>
      </header>
      <section className="rule-stack">
        <div className="section-heading"><h2>Risk rules</h2></div>
        {ingredient.risk_rules.length === 0 && <p>No source-backed risk rules are attached to this ingredient yet.</p>}
        {ingredient.risk_rules.map((rule) => (
          <article className={`rule-row ${severityClass(rule.severity)}`} key={rule.risk_rule_code}>
            <div>
              <strong>{rule.title}</strong>
              <span>{rule.summary}</span>
            </div>
            <div className="rule-meta">
              <span>{severityLabel(rule.severity)}</span>
              <span>{rule.evidence_kind}</span>
              <span>{formatConfidence(rule.confidence_score)}</span>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}
