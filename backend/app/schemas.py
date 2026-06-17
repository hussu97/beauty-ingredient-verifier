from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceOut(BaseModel):
    source_code: str
    name: str
    kind: str
    homepage_url: str | None
    license_name: str | None
    reliability: str
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BrandOut(BaseModel):
    brand_code: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class CategoryOut(BaseModel):
    category_code: str
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class ProductCategoryOut(BaseModel):
    category: CategoryOut

    model_config = ConfigDict(from_attributes=True)


class ProductImageOut(BaseModel):
    image_code: str
    kind: str
    url: str | None
    local_path: str | None
    embedding_status: str

    model_config = ConfigDict(from_attributes=True)


class IngredientSummaryOut(BaseModel):
    ingredient_code: str
    canonical_name: str
    inci_name: str | None
    regulatory_status: str

    model_config = ConfigDict(from_attributes=True)


class ProductIngredientOut(BaseModel):
    product_ingredient_code: str
    raw_name: str
    rank: int | None
    percent_min: float | None
    percent_max: float | None
    percent_estimate: float | None
    ingredient: IngredientSummaryOut

    model_config = ConfigDict(from_attributes=True)


class ProductListOut(BaseModel):
    product_code: str
    barcode: str | None
    name: str
    brand: BrandOut | None
    category_text: str | None
    ingredient_text: str | None
    confidence_score: float
    data_quality_warnings: list[str]
    images: list[ProductImageOut]

    model_config = ConfigDict(from_attributes=True)


class ProductDetailOut(ProductListOut):
    categories: list[ProductCategoryOut]
    ingredients: list[ProductIngredientOut]
    last_source_update_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DirectoryGroupOut(BaseModel):
    kind: str
    code: str
    name: str
    slug: str | None = None
    product_count: int


class DirectoryProductRiskOut(BaseModel):
    product: ProductListOut
    severity: str
    score: int
    matched_ingredient_count: int
    side_effects: list[str]


class DirectoryProductsPageOut(BaseModel):
    items: list[DirectoryProductRiskOut]
    total: int
    limit: int
    offset: int


class RiskRuleOut(BaseModel):
    risk_rule_code: str
    title: str
    summary: str
    severity: str
    severity_score: int
    side_effects: list[str]
    applies_to: dict[str, Any]
    evidence_kind: str
    confidence_score: float
    source_record_code: str

    model_config = ConfigDict(from_attributes=True)


class IngredientDetailOut(IngredientSummaryOut):
    cas_number: str | None
    ec_number: str | None
    pubchem_cid: str | None
    functions: list[str]
    risk_rules: list[RiskRuleOut]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClinicalProfile(BaseModel):
    skin_types: list[str] = Field(default_factory=list)
    hair_types: list[str] = Field(default_factory=list)
    scalp_types: list[str] = Field(default_factory=list)
    age_band: str | None = None
    allergies: list[str] = Field(default_factory=list)
    sensitivities: list[str] = Field(default_factory=list)
    pregnancy: bool = False
    lactation: bool = False
    conditions: list[str] = Field(default_factory=list)


class DirectoryProductsIn(BaseModel):
    group_kind: str = Field(pattern="^(brand|category)$")
    group_code: str
    profile: ClinicalProfile = Field(default_factory=ClinicalProfile)
    limit: int = Field(default=24, ge=1, le=60)
    offset: int = Field(default=0, ge=0)


class RiskEvaluateIn(BaseModel):
    product_code: str
    profile: ClinicalProfile = Field(default_factory=ClinicalProfile)


class MatchedIngredientOut(BaseModel):
    ingredient_code: str
    ingredient_name: str
    rule_code: str
    title: str
    summary: str
    severity: str
    severity_score: int
    side_effects: list[str]
    confidence_score: float
    evidence_kind: str
    source_record_code: str
    source_url: str | None


class RiskEvaluationOut(BaseModel):
    evaluation_code: str
    product_code: str
    product_name: str
    severity: str
    score: int
    side_effects: list[str]
    matched_rule_codes: list[str]
    matched_ingredients: list[MatchedIngredientOut]
    explanation: str
    disclaimer: str


class ScanCandidateOut(BaseModel):
    candidate_code: str
    product_code: str | None
    candidate_name: str
    brand_name: str | None
    confidence_score: float
    match_reasons: list[str]
    rank: int

    model_config = ConfigDict(from_attributes=True)


class ScanJobOut(BaseModel):
    scan_code: str
    upload_filename: str
    status: str
    barcode: str | None
    ocr_text: str | None
    extracted_brand: str | None
    extracted_product_name: str | None
    extracted_ingredient_text: str | None
    confidence_score: float
    matched_product_code: str | None
    error_message: str | None
    candidates: list[ScanCandidateOut]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HealthOut(BaseModel):
    app: str
    env: str
    database: str
    status: str


class ImportStatusOut(BaseModel):
    products: int
    ingredients: int
    sources: int
    source_records: int
    risk_rules: int
    scan_jobs: int
