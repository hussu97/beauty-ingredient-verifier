from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class UTCAwareDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Datetime values must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow, onupdate=utcnow)


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    source_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(80))
    homepage_url: Mapped[str | None] = mapped_column(String(500))
    license_name: Mapped[str | None] = mapped_column(String(160))
    terms_url: Mapped[str | None] = mapped_column(String(500))
    reliability: Mapped[str] = mapped_column(String(80), default="unknown")

    records: Mapped[list[SourceRecord]] = relationship(back_populates="source")


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("source_code", "record_type", "external_id", name="uq_source_records_source_type_external"),
        Index("ix_source_records_source_external", "source_code", "external_id"),
    )

    source_record_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_code: Mapped[str] = mapped_column(ForeignKey("sources.source_code"))
    external_id: Mapped[str] = mapped_column(String(300))
    record_type: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str | None] = mapped_column(String(800))
    content_hash: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)

    source: Mapped[Source] = relationship(back_populates="records")


class SourceRecordFact(Base):
    __tablename__ = "source_record_facts"
    __table_args__ = (
        Index(
            "ix_source_record_facts_record_field_value",
            "source_record_code",
            "entity_kind",
            "field_name",
            "normalized_value",
        ),
    )

    fact_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_record_code: Mapped[str] = mapped_column(ForeignKey("source_records.source_record_code"), index=True)
    source_code: Mapped[str] = mapped_column(ForeignKey("sources.source_code"), index=True)
    entity_kind: Mapped[str] = mapped_column(String(40), index=True)
    product_code: Mapped[str | None] = mapped_column(ForeignKey("products.product_code"), index=True)
    ingredient_code: Mapped[str | None] = mapped_column(ForeignKey("ingredients.ingredient_code"), index=True)
    fact_type: Mapped[str] = mapped_column(String(80), index=True)
    field_name: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str | None] = mapped_column(String(240))
    value_text: Mapped[str | None] = mapped_column(Text)
    value_json: Mapped[Any] = mapped_column(JSON, default=dict)
    normalized_value: Mapped[str | None] = mapped_column(String(500), index=True)
    source_url: Mapped[str | None] = mapped_column(String(800))
    confidence_score: Mapped[float] = mapped_column(Float, default=0.8)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow, onupdate=utcnow)

    source_record: Mapped[SourceRecord] = relationship()
    source: Mapped[Source] = relationship()
    product: Mapped[Product | None] = relationship()
    ingredient: Mapped[Ingredient | None] = relationship()


class ProductSourceLink(Base):
    __tablename__ = "product_source_links"
    __table_args__ = (
        UniqueConstraint("product_code", "source_record_code", name="uq_product_source_links_product_record"),
        UniqueConstraint("source_code", "external_id", name="uq_product_source_links_source_external"),
    )

    product_source_link_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_code: Mapped[str] = mapped_column(ForeignKey("products.product_code"), index=True)
    source_record_code: Mapped[str] = mapped_column(ForeignKey("source_records.source_record_code"), index=True)
    source_code: Mapped[str] = mapped_column(ForeignKey("sources.source_code"), index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(800))
    match_method: Mapped[str] = mapped_column(String(80))
    match_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCAwareDateTime())
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow, onupdate=utcnow)

    product: Mapped[Product] = relationship(back_populates="source_links")
    source_record: Mapped[SourceRecord] = relationship()
    source: Mapped[Source] = relationship()


class IngredientSourceLink(Base):
    __tablename__ = "ingredient_source_links"
    __table_args__ = (
        UniqueConstraint("ingredient_code", "source_record_code", name="uq_ingredient_source_links_ingredient_record"),
    )

    ingredient_source_link_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    ingredient_code: Mapped[str] = mapped_column(ForeignKey("ingredients.ingredient_code"), index=True)
    source_record_code: Mapped[str] = mapped_column(ForeignKey("source_records.source_record_code"), index=True)
    source_code: Mapped[str] = mapped_column(ForeignKey("sources.source_code"), index=True)
    external_id: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(800))
    match_method: Mapped[str] = mapped_column(String(80))
    match_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow, onupdate=utcnow)

    ingredient: Mapped[Ingredient] = relationship(back_populates="source_links")
    source_record: Mapped[SourceRecord] = relationship()
    source: Mapped[Source] = relationship()


class CanonicalTerm(Base, TimestampMixin):
    __tablename__ = "canonical_terms"
    __table_args__ = (
        UniqueConstraint("term_type", "slug", name="uq_canonical_terms_type_slug"),
    )

    term_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    term_type: Mapped[str] = mapped_column(String(80), index=True)
    slug: Mapped[str] = mapped_column(Text, index=True)
    label: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    aliases: Mapped[list[TermAlias]] = relationship(back_populates="term", cascade="all, delete-orphan")
    product_links: Mapped[list[ProductTermLink]] = relationship(back_populates="term", cascade="all, delete-orphan")
    ingredient_links: Mapped[list[IngredientTermLink]] = relationship(back_populates="term", cascade="all, delete-orphan")


class TermAlias(Base):
    __tablename__ = "term_aliases"
    __table_args__ = (
        UniqueConstraint("term_code", "source_code", "normalized_alias", name="uq_term_aliases_term_source_alias"),
    )

    alias_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    term_code: Mapped[str] = mapped_column(ForeignKey("canonical_terms.term_code"), index=True)
    source_code: Mapped[str | None] = mapped_column(ForeignKey("sources.source_code"))
    alias: Mapped[str] = mapped_column(String(240))
    normalized_alias: Mapped[str] = mapped_column(String(260), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)

    term: Mapped[CanonicalTerm] = relationship(back_populates="aliases")


class ProductTermLink(Base):
    __tablename__ = "product_term_links"
    __table_args__ = (
        UniqueConstraint(
            "product_code",
            "term_code",
            "source_record_code",
            name="uq_product_term_links_product_term_record",
        ),
    )

    product_term_link_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_code: Mapped[str] = mapped_column(ForeignKey("products.product_code"), index=True)
    term_code: Mapped[str] = mapped_column(ForeignKey("canonical_terms.term_code"), index=True)
    source_record_code: Mapped[str] = mapped_column(ForeignKey("source_records.source_record_code"), index=True)
    source_code: Mapped[str] = mapped_column(ForeignKey("sources.source_code"), index=True)
    raw_value: Mapped[str] = mapped_column(String(300))
    confidence_score: Mapped[float] = mapped_column(Float, default=0.8)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="term_links")
    term: Mapped[CanonicalTerm] = relationship(back_populates="product_links")
    source_record: Mapped[SourceRecord] = relationship()
    source: Mapped[Source] = relationship()


class IngredientTermLink(Base):
    __tablename__ = "ingredient_term_links"
    __table_args__ = (
        UniqueConstraint(
            "ingredient_code",
            "term_code",
            "source_record_code",
            name="uq_ingredient_term_links_ingredient_term_record",
        ),
    )

    ingredient_term_link_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    ingredient_code: Mapped[str] = mapped_column(ForeignKey("ingredients.ingredient_code"), index=True)
    term_code: Mapped[str] = mapped_column(ForeignKey("canonical_terms.term_code"), index=True)
    source_record_code: Mapped[str] = mapped_column(ForeignKey("source_records.source_record_code"), index=True)
    source_code: Mapped[str] = mapped_column(ForeignKey("sources.source_code"), index=True)
    raw_value: Mapped[str] = mapped_column(String(300))
    confidence_score: Mapped[float] = mapped_column(Float, default=0.8)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)

    ingredient: Mapped[Ingredient] = relationship(back_populates="term_links")
    term: Mapped[CanonicalTerm] = relationship(back_populates="ingredient_links")
    source_record: Mapped[SourceRecord] = relationship()
    source: Mapped[Source] = relationship()


class Brand(Base, TimestampMixin):
    __tablename__ = "brands"

    brand_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    source_record_code: Mapped[str | None] = mapped_column(ForeignKey("source_records.source_record_code"))

    products: Mapped[list[Product]] = relationship(back_populates="brand")


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    category_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)

    products: Mapped[list[ProductCategory]] = relationship(back_populates="category")


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    product_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    barcode: Mapped[str | None] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(340), index=True)
    brand_code: Mapped[str | None] = mapped_column(ForeignKey("brands.brand_code"), index=True)
    source_record_code: Mapped[str | None] = mapped_column(ForeignKey("source_records.source_record_code"))
    category_text: Mapped[str | None] = mapped_column(Text)
    ingredient_text: Mapped[str | None] = mapped_column(Text)
    data_quality_warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    last_source_update_at: Mapped[datetime | None] = mapped_column(UTCAwareDateTime())

    brand: Mapped[Brand | None] = relationship(back_populates="products")
    categories: Mapped[list[ProductCategory]] = relationship(back_populates="product", cascade="all, delete-orphan")
    images: Mapped[list[ProductImage]] = relationship(back_populates="product", cascade="all, delete-orphan")
    ingredients: Mapped[list[ProductIngredient]] = relationship(back_populates="product", cascade="all, delete-orphan")
    source_links: Mapped[list[ProductSourceLink]] = relationship(back_populates="product", cascade="all, delete-orphan")
    term_links: Mapped[list[ProductTermLink]] = relationship(back_populates="product", cascade="all, delete-orphan")


class ProductCategory(Base):
    __tablename__ = "product_categories"

    product_code: Mapped[str] = mapped_column(ForeignKey("products.product_code"), primary_key=True)
    category_code: Mapped[str] = mapped_column(ForeignKey("categories.category_code"), primary_key=True, index=True)

    product: Mapped[Product] = relationship(back_populates="categories")
    category: Mapped[Category] = relationship(back_populates="products")


class ProductImage(Base, TimestampMixin):
    __tablename__ = "product_images"

    image_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_code: Mapped[str] = mapped_column(ForeignKey("products.product_code"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="front")
    url: Mapped[str | None] = mapped_column(String(800))
    local_path: Mapped[str | None] = mapped_column(String(800))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    source_record_code: Mapped[str | None] = mapped_column(ForeignKey("source_records.source_record_code"))
    embedding_status: Mapped[str] = mapped_column(String(40), default="pending")

    product: Mapped[Product] = relationship(back_populates="images")


class Ingredient(Base, TimestampMixin):
    __tablename__ = "ingredients"

    ingredient_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text, unique=True, index=True)
    inci_name: Mapped[str | None] = mapped_column(Text)
    cas_number: Mapped[str | None] = mapped_column(String(80))
    ec_number: Mapped[str | None] = mapped_column(String(80))
    pubchem_cid: Mapped[str | None] = mapped_column(String(80))
    functions: Mapped[list[str]] = mapped_column(JSON, default=list)
    regulatory_status: Mapped[str] = mapped_column(String(120), default="unknown")
    source_record_code: Mapped[str | None] = mapped_column(ForeignKey("source_records.source_record_code"))

    synonyms: Mapped[list[IngredientSynonym]] = relationship(back_populates="ingredient", cascade="all, delete-orphan")
    product_links: Mapped[list[ProductIngredient]] = relationship(back_populates="ingredient")
    risk_rules: Mapped[list[RiskRule]] = relationship(back_populates="ingredient")
    source_links: Mapped[list[IngredientSourceLink]] = relationship(back_populates="ingredient", cascade="all, delete-orphan")
    term_links: Mapped[list[IngredientTermLink]] = relationship(back_populates="ingredient", cascade="all, delete-orphan")


class IngredientSynonym(Base):
    __tablename__ = "ingredient_synonyms"

    synonym_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    ingredient_code: Mapped[str] = mapped_column(ForeignKey("ingredients.ingredient_code"))
    name: Mapped[str] = mapped_column(String(260))
    normalized_name: Mapped[str] = mapped_column(String(280), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)

    ingredient: Mapped[Ingredient] = relationship(back_populates="synonyms")


class ProductIngredient(Base):
    __tablename__ = "product_ingredients"
    __table_args__ = (
        UniqueConstraint("product_code", "ingredient_code", name="uq_product_ingredients_product_ingredient"),
    )

    product_ingredient_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_code: Mapped[str] = mapped_column(ForeignKey("products.product_code"), index=True)
    ingredient_code: Mapped[str] = mapped_column(ForeignKey("ingredients.ingredient_code"), index=True)
    raw_name: Mapped[str] = mapped_column(Text)
    rank: Mapped[int | None] = mapped_column(Integer)
    percent_min: Mapped[float | None] = mapped_column(Float)
    percent_max: Mapped[float | None] = mapped_column(Float)
    percent_estimate: Mapped[float | None] = mapped_column(Float)
    source_record_code: Mapped[str | None] = mapped_column(ForeignKey("source_records.source_record_code"))
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="ingredients")
    ingredient: Mapped[Ingredient] = relationship(back_populates="product_links")


class RiskRule(Base, TimestampMixin):
    __tablename__ = "risk_rules"

    risk_rule_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    ingredient_code: Mapped[str] = mapped_column(ForeignKey("ingredients.ingredient_code"), index=True)
    source_record_code: Mapped[str] = mapped_column(ForeignKey("source_records.source_record_code"))
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(40))
    severity_score: Mapped[int] = mapped_column(Integer)
    side_effects: Mapped[list[str]] = mapped_column(JSON, default=list)
    applies_to: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_kind: Mapped[str] = mapped_column(String(80))
    confidence_score: Mapped[float] = mapped_column(Float, default=0.6)
    version: Mapped[str] = mapped_column(String(40), default="1")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    ingredient: Mapped[Ingredient] = relationship(back_populates="risk_rules")


class RiskEvaluation(Base):
    __tablename__ = "risk_evaluations"

    evaluation_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_code: Mapped[str] = mapped_column(ForeignKey("products.product_code"), index=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(40))
    score: Mapped[int] = mapped_column(Integer)
    matched_rule_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)


class ScanJob(Base, TimestampMixin):
    __tablename__ = "scan_jobs"

    scan_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    upload_filename: Mapped[str] = mapped_column(String(300))
    image_path: Mapped[str] = mapped_column(String(800))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    barcode: Mapped[str | None] = mapped_column(String(80))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    extracted_brand: Mapped[str | None] = mapped_column(String(240))
    extracted_product_name: Mapped[str | None] = mapped_column(String(300))
    extracted_ingredient_text: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float, default=0)
    matched_product_code: Mapped[str | None] = mapped_column(ForeignKey("products.product_code"))
    error_message: Mapped[str | None] = mapped_column(Text)

    candidates: Mapped[list[ScanCandidate]] = relationship(back_populates="scan", cascade="all, delete-orphan")


class ScanCandidate(Base):
    __tablename__ = "scan_candidates"

    candidate_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    scan_code: Mapped[str] = mapped_column(ForeignKey("scan_jobs.scan_code"), index=True)
    product_code: Mapped[str | None] = mapped_column(ForeignKey("products.product_code"))
    candidate_name: Mapped[str] = mapped_column(String(300))
    brand_name: Mapped[str | None] = mapped_column(String(240))
    confidence_score: Mapped[float] = mapped_column(Float)
    match_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    rank: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)

    scan: Mapped[ScanJob] = relationship(back_populates="candidates")
    product: Mapped[Product | None] = relationship()


class AdverseEventSignal(Base):
    __tablename__ = "adverse_event_signals"

    signal_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_code: Mapped[str | None] = mapped_column(ForeignKey("products.product_code"))
    ingredient_code: Mapped[str | None] = mapped_column(ForeignKey("ingredients.ingredient_code"))
    source_record_code: Mapped[str] = mapped_column(ForeignKey("source_records.source_record_code"))
    reaction_name: Mapped[str] = mapped_column(String(240))
    severity: Mapped[str] = mapped_column(String(40))
    report_count: Mapped[int] = mapped_column(Integer)
    signal_score: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)


class ImageEmbedding(Base):
    __tablename__ = "image_embeddings"
    __table_args__ = (
        Index("ix_image_embeddings_model_dimensions", "model_name", "dimensions"),
        Index("ix_image_embeddings_product_model", "product_code", "model_name"),
    )

    embedding_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    image_code: Mapped[str] = mapped_column(ForeignKey("product_images.image_code"))
    product_code: Mapped[str] = mapped_column(ForeignKey("products.product_code"))
    model_name: Mapped[str] = mapped_column(String(120))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list[float]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    sync_run_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    mode: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="running")
    source_database: Mapped[str] = mapped_column(String(1000))
    source_fingerprint: Mapped[str] = mapped_column(String(80), index=True)
    tables: Mapped[list[str]] = mapped_column(JSON, default=list)
    row_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCAwareDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCAwareDateTime())
