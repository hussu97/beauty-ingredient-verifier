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
};
