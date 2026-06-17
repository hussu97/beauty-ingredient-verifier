import { useQuery } from "@tanstack/react-query";
import { Boxes, Building2, ChevronLeft, ChevronRight, Layers3, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ClinicalProfile, DirectoryGroup } from "../api/types";
import ProfilePanel from "../components/ProfilePanel";
import StatusBadge from "../components/StatusBadge";
import { firstImageUrl } from "../lib/format";
import { loadProfile } from "../lib/profile";
import { severityClass, severityLabel } from "../lib/severity";

type GroupKind = "brand" | "category";
const PAGE_SIZE = 12;

function ProductRiskBadge({ severity }: { severity: string }) {
  const normalized = severity.toLowerCase();
  const tone = normalized === "high" || normalized === "critical"
    ? "danger"
    : normalized === "moderate"
      ? "warn"
      : normalized === "low" || normalized === "minimal"
        ? "good"
        : "neutral";
  return <StatusBadge tone={tone}>{severityLabel(severity)}</StatusBadge>;
}

export default function DirectoryPage() {
  const [kind, setKind] = useState<GroupKind>("brand");
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [groupSearch, setGroupSearch] = useState("");
  const [page, setPage] = useState(1);
  const [profile, setProfile] = useState<ClinicalProfile>(() => loadProfile());
  const profileKey = JSON.stringify(profile);

  const groupsQuery = useQuery({
    queryKey: ["directory-groups", kind],
    queryFn: () => api.directoryGroups(kind),
  });
  const groups = useMemo(() => groupsQuery.data ?? [], [groupsQuery.data]);
  const filteredGroups = useMemo(() => {
    const normalized = groupSearch.trim().toLowerCase();
    if (!normalized) return groups;
    return groups.filter((group) => group.name.toLowerCase().includes(normalized));
  }, [groupSearch, groups]);
  const selectedGroup = groups.find((group) => group.code === selectedCode) ?? groups[0] ?? null;

  useEffect(() => {
    setSelectedCode(null);
    setGroupSearch("");
  }, [kind]);

  useEffect(() => {
    setPage(1);
  }, [kind, selectedGroup?.code, profileKey]);

  const productsQuery = useQuery({
    queryKey: ["directory-products", kind, selectedGroup?.code, profileKey, page],
    queryFn: () => api.directoryProducts(kind, selectedGroup!.code, profile, {
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    }),
    enabled: Boolean(selectedGroup),
  });
  const productPage = productsQuery.data;
  const products = productPage?.items ?? [];
  const totalProducts = productPage?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalProducts / PAGE_SIZE));
  const pageStart = totalProducts === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const pageEnd = Math.min(totalProducts, page * PAGE_SIZE);

  function selectKind(nextKind: GroupKind) {
    setKind(nextKind);
    setPage(1);
  }

  function selectGroup(code: string) {
    setSelectedCode(code);
    setPage(1);
  }

  return (
    <div className="directory-page">
      <header className="page-header directory-header">
        <div>
          <span className="eyebrow">Product directory</span>
          <h1>Browse by brand or category.</h1>
          <p>Products are ranked by the strongest source-backed warning for the active profile.</p>
        </div>
      </header>

      <ProfilePanel profile={profile} onChange={setProfile} />

      <section className="directory-layout">
        <aside className="directory-groups" aria-label={`${kind} groups`}>
          <div className="directory-kind-switch" role="tablist" aria-label="Directory grouping">
            <button className={kind === "brand" ? "active" : ""} onClick={() => selectKind("brand")} type="button">
              <Building2 size={17} />
              Brands
            </button>
            <button className={kind === "category" ? "active" : ""} onClick={() => selectKind("category")} type="button">
              <Layers3 size={17} />
              Categories
            </button>
          </div>
          <div className="section-heading compact">
            <div>
              <h2>{kind === "brand" ? "Brands" : "Categories"}</h2>
              <p>{groups.length} groups loaded</p>
            </div>
          </div>
          <label className="search-field directory-search">
            <Search size={17} />
            <input
              aria-label={`Search ${kind === "brand" ? "brands" : "categories"}`}
              onChange={(event) => setGroupSearch(event.target.value)}
              placeholder={`Search ${kind === "brand" ? "brands" : "categories"}`}
              value={groupSearch}
            />
          </label>
          <div className="group-list">
            {groupsQuery.isLoading && <div className="loading-line">Loading groups...</div>}
            {filteredGroups.map((group: DirectoryGroup) => (
              <button
                className={selectedGroup?.code === group.code ? "group-row active" : "group-row"}
                key={group.code}
                type="button"
                onClick={() => selectGroup(group.code)}
              >
                <span>{group.name}</span>
                <small>{group.product_count} products</small>
              </button>
            ))}
            {!groupsQuery.isLoading && filteredGroups.length === 0 && (
              <div className="empty-state compact">
                No {kind === "brand" ? "brands" : "categories"} match that search.
              </div>
            )}
          </div>
        </aside>

        <div className="directory-products">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Ranked PLP</span>
              <h2>{selectedGroup?.name ?? "Select a group"}</h2>
              <p>Highest warning levels appear first. Ingredients with no matched rules remain unknown, not cleared.</p>
            </div>
            {selectedGroup && (
              <div className="pagination-summary">
                {productsQuery.isLoading ? "Ranking..." : `${pageStart}-${pageEnd} of ${totalProducts}`}
              </div>
            )}
          </div>
          <div className="plp-list">
            {productsQuery.isLoading && <div className="loading-line">Ranking products...</div>}
            {products.map((item) => {
              const imageUrl = firstImageUrl(item.product.images);
              return (
                <Link
                  to={`/products/${item.product.product_code}`}
                  className={`plp-row ${severityClass(item.severity)}`}
                  key={item.product.product_code}
                >
                  <div className="row-image">
                    {imageUrl ? <img src={imageUrl} alt={item.product.name} /> : <span>{item.product.name.slice(0, 2)}</span>}
                  </div>
                  <div className="plp-copy">
                    <strong>{item.product.name}</strong>
                    <span>{item.product.brand?.name ?? "Unknown brand"}</span>
                    <small>{item.product.category_text ?? "Uncategorized product"}</small>
                  </div>
                  <div className="plp-risk">
                    <ProductRiskBadge severity={item.severity} />
                    <span>{item.matched_ingredient_count} flagged ingredients</span>
                    {item.side_effects.length > 0 && <small>{item.side_effects.slice(0, 3).join(", ")}</small>}
                  </div>
                </Link>
              );
            })}
            {!productsQuery.isLoading && products.length === 0 && (
              <div className="empty-state">
                <Boxes size={22} />
                No products found for this group yet.
              </div>
            )}
          </div>
          {totalProducts > PAGE_SIZE && (
            <nav className="pagination-controls" aria-label="Product pagination">
              <button
                disabled={page <= 1 || productsQuery.isFetching}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                type="button"
              >
                <ChevronLeft size={17} />
                Previous
              </button>
              <span>Page {page} of {totalPages}</span>
              <button
                disabled={page >= totalPages || productsQuery.isFetching}
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                type="button"
              >
                Next
                <ChevronRight size={17} />
              </button>
            </nav>
          )}
        </div>
      </section>
    </div>
  );
}
