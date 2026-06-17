import { useQuery } from "@tanstack/react-query";
import { Activity, Database, FileSearch, FlaskConical, Search } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, NavLink, useParams } from "react-router-dom";
import { api } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { firstImageUrl } from "../lib/format";

const tabs = [
  { key: "products", label: "Products", icon: Database },
  { key: "ingredients", label: "Ingredients", icon: FlaskConical },
  { key: "sources", label: "Sources", icon: FileSearch },
  { key: "imports", label: "Imports", icon: Activity },
];

export default function AdminPage() {
  const { tab = "products" } = useParams();
  const [query, setQuery] = useState("");
  const activeTab = tabs.some((item) => item.key === tab) ? tab : null;

  const productsQuery = useQuery({
    queryKey: ["admin-products", query],
    queryFn: () => api.products(query),
    enabled: activeTab === "products",
  });
  const ingredientsQuery = useQuery({
    queryKey: ["admin-ingredients", query],
    queryFn: () => api.ingredients(query),
    enabled: activeTab === "ingredients",
  });
  const sourcesQuery = useQuery({
    queryKey: ["admin-sources"],
    queryFn: api.sources,
    enabled: activeTab === "sources" || activeTab === "imports",
  });
  const statusQuery = useQuery({
    queryKey: ["admin-import-status"],
    queryFn: api.importStatus,
    enabled: activeTab === "imports",
  });

  if (!activeTab) return <Navigate to="/admin/products" replace />;

  return (
    <div className="admin-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Admin</span>
          <h1>Database and source operations</h1>
          <p>Search imported products and inspect provenance away from the scanner flow.</p>
        </div>
      </header>

      <nav className="admin-tabs" aria-label="Admin sections">
        {tabs.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink to={`/admin/${item.key}`} key={item.key} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon size={17} />
              {item.label}
            </NavLink>
          );
        })}
      </nav>

      {(activeTab === "products" || activeTab === "ingredients") && (
        <label className="search-field">
          <Search size={18} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={`Search ${activeTab}`}
          />
        </label>
      )}

      {activeTab === "products" && (
        <section className="admin-panel">
          <div className="section-heading"><h2>Products</h2></div>
          <div className="product-list">
            {productsQuery.data?.map((product) => {
              const imageUrl = firstImageUrl(product.images);
              return (
                <Link to={`/products/${product.product_code}`} className="product-row" key={product.product_code}>
                  <div className="row-image">
                    {imageUrl ? <img src={imageUrl} alt={product.name} /> : <span>{product.name.slice(0, 2)}</span>}
                  </div>
                  <div>
                    <strong>{product.name}</strong>
                    <span>{product.brand?.name ?? "Unknown brand"}</span>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {activeTab === "ingredients" && (
        <section className="admin-panel">
          <div className="section-heading"><h2>Ingredients</h2></div>
          <div className="ingredient-list wide">
            {ingredientsQuery.data?.map((ingredient) => (
              <Link to={`/ingredients/${ingredient.ingredient_code}`} key={ingredient.ingredient_code}>
                <strong>{ingredient.canonical_name}</strong>
                <span>{ingredient.regulatory_status}</span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {activeTab === "sources" && (
        <section className="admin-panel">
          <div className="section-heading"><h2>Sources</h2></div>
          <div className="source-list">
            {sourcesQuery.data?.map((source) => (
              <article key={source.source_code} className="source-row">
                <div>
                  <strong>{source.name}</strong>
                  <span>{source.kind}</span>
                </div>
                <StatusBadge>{source.reliability}</StatusBadge>
                {source.homepage_url && <a href={source.homepage_url} target="_blank" rel="noreferrer">Open source</a>}
              </article>
            ))}
          </div>
        </section>
      )}

      {activeTab === "imports" && (
        <section className="admin-panel">
          <div className="section-heading"><h2>Import status</h2></div>
          {statusQuery.data && (
            <div className="metric-band">
              {Object.entries(statusQuery.data).map(([key, value]) => (
                <div className="metric" key={key}>
                  <span>{key.replace(/_/g, " ")}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
          )}
          <div className="source-footnote">
            {sourcesQuery.data?.length ?? 0} source adapters are currently registered for provenance and enrichment.
          </div>
        </section>
      )}
    </div>
  );
}
