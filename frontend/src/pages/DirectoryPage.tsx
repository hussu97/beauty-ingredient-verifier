import { useQuery } from "@tanstack/react-query";
import { Boxes, ChevronLeft, ChevronRight, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ClinicalProfile, DirectoryFacet, DirectorySort } from "../api/types";
import ProfilePanel from "../components/ProfilePanel";
import StatusBadge from "../components/StatusBadge";
import { firstImageUrl } from "../lib/format";
import { loadProfile } from "../lib/profile";
import { severityClass, severityLabel } from "../lib/severity";

const PAGE_SIZE = 12;
const SEARCH_DEBOUNCE_MS = 300;

const sortOptions: Array<{ value: DirectorySort; label: string }> = [
  { value: "risk_desc", label: "Highest warning" },
  { value: "name_asc", label: "Name A-Z" },
  { value: "name_desc", label: "Name Z-A" },
  { value: "brand_asc", label: "Brand A-Z" },
  { value: "confidence_desc", label: "Source confidence" },
];

function useDebouncedValue(value: string, delayMs = SEARCH_DEBOUNCE_MS) {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setDebouncedValue(value), delayMs);
    return () => window.clearTimeout(timeoutId);
  }, [value, delayMs]);

  return debouncedValue;
}

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

function toggleCode(codes: string[], code: string) {
  return codes.includes(code) ? codes.filter((item) => item !== code) : [...codes, code];
}

function FacetList({
  title,
  facets,
  selectedCodes,
  onToggle,
}: {
  title: string;
  facets: DirectoryFacet[];
  selectedCodes: string[];
  onToggle: (code: string) => void;
}) {
  return (
    <section className="facet-section">
      <div className="facet-heading">
        <h2>{title}</h2>
        <span>{facets.length}</span>
      </div>
      <div className="facet-list">
        {facets.map((facet) => (
          <label className="facet-row" key={facet.code}>
            <input
              checked={selectedCodes.includes(facet.code)}
              onChange={() => onToggle(facet.code)}
              type="checkbox"
            />
            <span>{facet.name}</span>
            <small>{facet.product_count}</small>
          </label>
        ))}
        {facets.length === 0 && <div className="empty-state compact">No matching facets.</div>}
      </div>
    </section>
  );
}

export default function DirectoryPage() {
  const [search, setSearch] = useState("");
  const [selectedBrands, setSelectedBrands] = useState<string[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [sort, setSort] = useState<DirectorySort>("risk_desc");
  const [page, setPage] = useState(1);
  const [profile, setProfile] = useState<ClinicalProfile>(() => loadProfile());
  const profileKey = JSON.stringify(profile);
  const debouncedSearch = useDebouncedValue(search);
  const normalizedSearch = (search.trim() ? debouncedSearch : "").trim();

  useEffect(() => {
    setPage(1);
  }, [normalizedSearch, selectedBrands, selectedCategories, sort, profileKey]);

  const productsQuery = useQuery({
    queryKey: [
      "directory-products",
      normalizedSearch,
      selectedBrands,
      selectedCategories,
      sort,
      profileKey,
      page,
    ],
    queryFn: () => api.directoryProducts({
      q: normalizedSearch || undefined,
      brand_codes: selectedBrands,
      category_codes: selectedCategories,
      sort,
      profile,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    }),
  });
  const productPage = productsQuery.data;
  const products = productPage?.items ?? [];
  const totalProducts = productPage?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalProducts / PAGE_SIZE));
  const pageStart = totalProducts === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const pageEnd = Math.min(totalProducts, page * PAGE_SIZE);
  const activeFilters = selectedBrands.length + selectedCategories.length + (normalizedSearch ? 1 : 0);

  const selectedFacetNames = useMemo(() => {
    const facets = [...(productPage?.brand_facets ?? []), ...(productPage?.category_facets ?? [])];
    return facets
      .filter((facet) => selectedBrands.includes(facet.code) || selectedCategories.includes(facet.code))
      .map((facet) => facet.name);
  }, [productPage?.brand_facets, productPage?.category_facets, selectedBrands, selectedCategories]);

  function clearFilters() {
    setSearch("");
    setSelectedBrands([]);
    setSelectedCategories([]);
    setPage(1);
  }

  return (
    <div className="directory-page">
      <header className="page-header directory-header">
        <div>
          <span className="eyebrow">Product directory</span>
          <h1>Products</h1>
          <p>{productsQuery.isLoading ? "Loading catalog..." : `${totalProducts} products match the current filters.`}</p>
        </div>
      </header>

      <ProfilePanel profile={profile} onChange={setProfile} />

      <section className="directory-toolbar" aria-label="Product listing controls">
        <label className="search-field directory-search">
          <Search size={17} />
          <input
            aria-label="Search products"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search products, brands, categories, or barcode"
            value={search}
          />
        </label>
        <label className="sort-control">
          <span>Sort</span>
          <select
            aria-label="Sort products"
            onChange={(event) => setSort(event.target.value as DirectorySort)}
            value={sort}
          >
            {sortOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      </section>

      <section className="directory-layout">
        <aside className="directory-groups" aria-label="Product filters">
          <div className="filter-summary">
            <div>
              <SlidersHorizontal size={18} />
              <strong>Filters</strong>
            </div>
            {activeFilters > 0 && (
              <button onClick={clearFilters} type="button">
                <X size={15} />
                Clear
              </button>
            )}
          </div>
          {selectedFacetNames.length > 0 && (
            <div className="active-filter-list">
              {selectedFacetNames.map((name) => <span key={name}>{name}</span>)}
            </div>
          )}
          <FacetList
            facets={productPage?.brand_facets ?? []}
            onToggle={(code) => setSelectedBrands((current) => toggleCode(current, code))}
            selectedCodes={selectedBrands}
            title="Brands"
          />
          <FacetList
            facets={productPage?.category_facets ?? []}
            onToggle={(code) => setSelectedCategories((current) => toggleCode(current, code))}
            selectedCodes={selectedCategories}
            title="Categories"
          />
        </aside>

        <div className="directory-products">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Catalog PLP</span>
              <h2>{productsQuery.isFetching ? "Updating products" : "Product grid"}</h2>
              <p>Risk labels reflect the active profile and source-backed ingredient rules.</p>
            </div>
            <div className="pagination-summary">
              {productsQuery.isLoading ? "Loading..." : `${pageStart}-${pageEnd} of ${totalProducts}`}
            </div>
          </div>
          <div className="plp-grid">
            {productsQuery.isLoading && <div className="loading-line">Loading products...</div>}
            {products.map((item) => {
              const imageUrl = firstImageUrl(item.product.images);
              const categories = item.category_labels.length > 0
                ? item.category_labels.slice(0, 2).join(", ")
                : item.product.category_text ?? "Uncategorized";
              return (
                <Link
                  to={`/products/${item.product.product_code}`}
                  className={`plp-card ${severityClass(item.severity)}`}
                  key={item.product.product_code}
                >
                  <div className="tile-image">
                    {imageUrl ? <img src={imageUrl} alt={item.product.name} /> : <span>{item.product.name.slice(0, 2)}</span>}
                  </div>
                  <div className="plp-card-copy">
                    <div>
                      <strong>{item.product.name}</strong>
                      <span>{item.product.brand?.name ?? "Unknown brand"}</span>
                    </div>
                    <small>{categories}</small>
                  </div>
                  <div className="plp-card-meta">
                    <ProductRiskBadge severity={item.severity} />
                    <span>{item.matched_ingredient_count} flagged ingredients</span>
                  </div>
                  <div className="source-chip-list compact">
                    {(item.source_labels.length > 0 ? item.source_labels : ["Unknown source"]).slice(0, 3).map((label) => (
                      <span className="source-chip" key={label}>{label}</span>
                    ))}
                  </div>
                </Link>
              );
            })}
            {!productsQuery.isLoading && products.length === 0 && (
              <div className="empty-state plp-empty">
                <Boxes size={22} />
                No products match these filters.
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
