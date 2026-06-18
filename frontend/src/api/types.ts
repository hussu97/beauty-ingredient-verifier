export type Source = {
  source_code: string;
  name: string;
  kind: string;
  homepage_url: string | null;
  license_name: string | null;
  reliability: string;
  updated_at: string;
};

export type Brand = {
  brand_code: string;
  name: string;
};

export type ProductImage = {
  image_code: string;
  kind: string;
  url: string | null;
  local_path: string | null;
  embedding_status: string;
};

export type IngredientSummary = {
  ingredient_code: string;
  canonical_name: string;
  inci_name: string | null;
  regulatory_status: string;
};

export type ProductIngredient = {
  product_ingredient_code: string;
  raw_name: string;
  rank: number | null;
  percent_min: number | null;
  percent_max: number | null;
  percent_estimate: number | null;
  ingredient: IngredientSummary;
};

export type SourceLink = {
  source_code: string;
  source_name: string;
  external_id: string;
  source_url: string | null;
  record_type: string;
  match_method: string;
  match_confidence: number;
  source_updated_at: string | null;
  active: boolean;
};

export type NormalizedAttribute = {
  term_code: string;
  term_type: string;
  slug: string;
  label: string;
  source_codes: string[];
  confidence_score: number;
};

export type SourceConflict = {
  field: string;
  display_value: string | null;
  source_values: Array<{
    source_code: string;
    source_name: string;
    value: string;
    source_url: string | null;
  }>;
};

export type SourceFact = {
  fact_code: string;
  source_code: string;
  entity_kind: string;
  fact_type: string;
  field_name: string;
  label: string | null;
  value_text: string | null;
  value_json: unknown;
  source_url: string | null;
  confidence_score: number;
};

export type Product = {
  product_code: string;
  barcode: string | null;
  name: string;
  brand: Brand | null;
  category_text: string | null;
  ingredient_text: string | null;
  confidence_score: number;
  data_quality_warnings: string[];
  images: ProductImage[];
};

export type ProductDetail = Product & {
  categories: Array<{ category: { category_code: string; name: string; slug: string } }>;
  ingredients: ProductIngredient[];
  source_links: SourceLink[];
  normalized_attributes: NormalizedAttribute[];
  source_conflicts: SourceConflict[];
  source_facts: SourceFact[];
  source_last_updated_at: string | null;
  last_source_update_at: string | null;
  created_at: string;
  updated_at: string;
};

export type DirectoryGroup = {
  kind: "brand" | "category";
  code: string;
  name: string;
  slug: string | null;
  product_count: number;
};

export type DirectoryProductRisk = {
  product: Product;
  severity: string;
  score: number;
  matched_ingredient_count: number;
  side_effects: string[];
};

export type DirectoryProductsPage = {
  items: DirectoryProductRisk[];
  total: number;
  limit: number;
  offset: number;
};

export type RiskRule = {
  risk_rule_code: string;
  title: string;
  summary: string;
  severity: string;
  severity_score: number;
  side_effects: string[];
  applies_to: Record<string, unknown>;
  evidence_kind: string;
  confidence_score: number;
  source_record_code: string;
};

export type IngredientDetail = IngredientSummary & {
  cas_number: string | null;
  ec_number: string | null;
  pubchem_cid: string | null;
  functions: string[];
  risk_rules: RiskRule[];
  created_at: string;
  updated_at: string;
};

export type ClinicalProfile = {
  skin_types: string[];
  hair_types: string[];
  scalp_types: string[];
  age_band: string | null;
  allergies: string[];
  sensitivities: string[];
  pregnancy: boolean;
  lactation: boolean;
  conditions: string[];
};

export type RiskEvaluation = {
  evaluation_code: string;
  product_code: string;
  product_name: string;
  severity: string;
  score: number;
  side_effects: string[];
  matched_rule_codes: string[];
  matched_ingredients: Array<{
    ingredient_code: string;
    ingredient_name: string;
    rule_code: string;
    title: string;
    summary: string;
    severity: string;
    severity_score: number;
    side_effects: string[];
    confidence_score: number;
    evidence_kind: string;
    source_record_code: string;
    source_url: string | null;
  }>;
  explanation: string;
  disclaimer: string;
};

export type ScanCandidate = {
  candidate_code: string;
  product_code: string | null;
  candidate_name: string;
  brand_name: string | null;
  confidence_score: number;
  match_reasons: string[];
  rank: number;
};

export type ScanJob = {
  scan_code: string;
  upload_filename: string;
  status: string;
  barcode: string | null;
  ocr_text: string | null;
  extracted_brand: string | null;
  extracted_product_name: string | null;
  extracted_ingredient_text: string | null;
  confidence_score: number;
  matched_product_code: string | null;
  error_message: string | null;
  candidates: ScanCandidate[];
  created_at: string;
  updated_at: string;
};

export type ScanProgress = {
  phase: "uploading" | "analyzing" | "complete";
  percent: number | null;
  label: string;
};

export type ImportStatus = {
  products: number;
  ingredients: number;
  sources: number;
  source_records: number;
  risk_rules: number;
  scan_jobs: number;
  product_source_links: number;
  ingredient_source_links: number;
  canonical_terms: number;
  source_record_facts: number;
  ewg_source_records: number;
  source_conflict_products: number;
};

export type SourceTermSummary = {
  term_code: string;
  term_type: string;
  slug: string;
  label: string;
  product_count: number;
  ingredient_count: number;
};

export type SourceConflictProduct = {
  product_code: string;
  product_name: string;
  source_conflicts: SourceConflict[];
};
