import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ClinicalProfile } from "../api/types";
import ProductRiskPanel from "../components/ProductRiskPanel";
import ProfilePanel from "../components/ProfilePanel";
import { loadProfile } from "../lib/profile";

export default function ProductDetailPage() {
  const { productCode } = useParams();
  const [profile, setProfile] = useState<ClinicalProfile>(() => loadProfile());
  const profileKey = JSON.stringify(profile);
  const productQuery = useQuery({
    queryKey: ["product", productCode],
    queryFn: () => api.product(productCode!),
    enabled: Boolean(productCode),
  });
  const riskQuery = useQuery({
    queryKey: ["risk-evaluation", productCode, profileKey],
    queryFn: () => api.evaluateRisk(productCode!, profile),
    enabled: Boolean(productCode),
  });

  if (productQuery.isLoading) return <div className="page-stack">Loading product...</div>;
  if (!productQuery.data) return <div className="page-stack">Product not found.</div>;

  return (
    <div className="pdp-page">
      <Link to="/directory" className="back-link"><ArrowLeft size={16} /> Directory</Link>
      <section className="pdp-profile-band">
        <div>
          <span className="eyebrow">Product profile check</span>
          <h1>{productQuery.data.name}</h1>
          <p>Update the profile below to refresh this product's warning summary.</p>
        </div>
      </section>
      <ProfilePanel profile={profile} onChange={setProfile} />
      <ProductRiskPanel
        product={productQuery.data}
        risk={riskQuery.data}
        isEvaluating={riskQuery.isLoading || riskQuery.isFetching}
      />
      {riskQuery.error && <div className="error-banner">{riskQuery.error.message}</div>}
    </div>
  );
}
