import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ClinicalProfile, ScanJob } from "../api/types";
import { getMatchedProductCode, getTopCandidate } from "../lib/result";
import ProductRiskPanel from "./ProductRiskPanel";

type Props = {
  scan: ScanJob | null;
  profile: ClinicalProfile;
};

export default function ResultPanel({ scan, profile }: Props) {
  const matchedCode = getMatchedProductCode(scan);
  const topCandidate = getTopCandidate(scan);
  const otherCandidates = scan?.candidates.filter((candidate) => candidate.candidate_code !== topCandidate?.candidate_code) ?? [];
  const profileKey = JSON.stringify(profile);

  const productQuery = useQuery({
    queryKey: ["product", matchedCode],
    queryFn: () => api.product(matchedCode!),
    enabled: Boolean(matchedCode),
  });

  const riskQuery = useQuery({
    queryKey: ["risk-evaluation", matchedCode, profileKey],
    queryFn: () => api.evaluateRisk(matchedCode!, profile),
    enabled: Boolean(matchedCode),
  });

  if (!scan) {
    return (
      <section className="result-panel empty">
        <span className="eyebrow">Step 4 · result</span>
        <h2>Your product details will appear here</h2>
        <p>After upload, the page will show the top match, product details, and ingredient warnings without sending you elsewhere.</p>
      </section>
    );
  }

  const product = productQuery.data;
  const risk = riskQuery.data;

  return (
    <motion.section className="result-panel result-ready" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
      <div className="result-kicker">
        <span className="eyebrow">Step 4 · result</span>
      </div>

      {productQuery.isLoading && <div className="loading-line">Loading product details...</div>}
      {product && <ProductRiskPanel product={product} risk={risk} isEvaluating={riskQuery.isLoading && Boolean(matchedCode)} />}

      {otherCandidates.length > 0 && (
        <details className="alternate-matches">
          <summary>Other possible matches ({otherCandidates.length})</summary>
          <div className="candidate-list">
            {otherCandidates.map((candidate) => (
              <Link
                to={candidate.product_code ? `/products/${candidate.product_code}` : "#"}
                className="candidate-row"
                key={candidate.candidate_code}
              >
                <div>
                  <strong>{candidate.candidate_name}</strong>
                  <small>{candidate.brand_name ?? "Unknown brand"}</small>
                </div>
              </Link>
            ))}
          </div>
        </details>
      )}
    </motion.section>
  );
}
