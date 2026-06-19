from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, and_, case, desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Brand,
    Category,
    Product,
    ProductCategory,
    ProductIngredient,
    ProductSourceLink,
    ProductTermLink,
    RiskRule,
    SourceRecordFact,
)
from app.db.session import get_db
from app.schemas import (
    CategoryOut,
    DirectoryFacetOut,
    DirectoryGroupOut,
    DirectoryProductsIn,
    DirectoryProductsPageOut,
    ProductDetailOut,
    ProductListOut,
)
from app.services.normalization import normalize_text
from app.services.risk import SEVERITY_LABELS, _rule_applies
from app.services.source_fusion import normalized_product_attributes, product_source_conflicts

router = APIRouter(prefix="/products", tags=["catalog"])


def _product_options() -> tuple:
    return (
        selectinload(Product.brand),
        selectinload(Product.images),
        selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
        selectinload(Product.categories).selectinload(ProductCategory.category),
    )


def _product_detail_options() -> tuple:
    return (
        *_product_options(),
        selectinload(Product.source_links).selectinload(ProductSourceLink.source),
        selectinload(Product.source_links).selectinload(ProductSourceLink.source_record),
        selectinload(Product.term_links).selectinload(ProductTermLink.term),
    )


def _source_link_rows(product: Product) -> list[dict]:
    rows = []
    for link in sorted(product.source_links, key=lambda item: (item.source_code, item.external_id)):
        rows.append(
            {
                "source_code": link.source_code,
                "source_name": link.source.name if link.source else link.source_code,
                "external_id": link.external_id,
                "source_url": link.source_url,
                "record_type": link.source_record.record_type if link.source_record else "unknown",
                "match_method": link.match_method,
                "match_confidence": link.match_confidence,
                "source_updated_at": link.source_updated_at,
                "active": link.active,
            }
        )
    return rows


def _source_fact_rows(db: Session, product: Product) -> list[dict]:
    facts = db.scalars(
        select(SourceRecordFact)
        .where(SourceRecordFact.product_code == product.product_code)
        .order_by(SourceRecordFact.fact_type, SourceRecordFact.field_name)
        .limit(80)
    ).all()
    return [
        {
            "fact_code": fact.fact_code,
            "source_code": fact.source_code,
            "entity_kind": fact.entity_kind,
            "fact_type": fact.fact_type,
            "field_name": fact.field_name,
            "label": fact.label,
            "value_text": fact.value_text,
            "value_json": fact.value_json,
            "source_url": fact.source_url,
            "confidence_score": fact.confidence_score,
        }
        for fact in facts
    ]


def _product_detail_payload(db: Session, product: Product) -> dict:
    base = ProductListOut.model_validate(product).model_dump()
    source_dates = [
        date
        for date in [product.last_source_update_at, *[link.source_updated_at for link in product.source_links]]
        if date is not None
    ]
    return {
        **base,
        "categories": [
            {"category": CategoryOut.model_validate(link.category).model_dump()}
            for link in product.categories
            if link.category
        ],
        "ingredients": [
            {
                **{
                    "product_ingredient_code": link.product_ingredient_code,
                    "raw_name": link.raw_name,
                    "rank": link.rank,
                    "percent_min": link.percent_min,
                    "percent_max": link.percent_max,
                    "percent_estimate": link.percent_estimate,
                },
                "ingredient": {
                    "ingredient_code": link.ingredient.ingredient_code,
                    "canonical_name": link.ingredient.canonical_name,
                    "inci_name": link.ingredient.inci_name,
                    "regulatory_status": link.ingredient.regulatory_status,
                },
            }
            for link in product.ingredients
            if link.ingredient
        ],
        "source_links": _source_link_rows(product),
        "normalized_attributes": normalized_product_attributes(product),
        "source_conflicts": product_source_conflicts(product),
        "source_facts": _source_fact_rows(db, product),
        "source_last_updated_at": max(source_dates) if source_dates else None,
        "last_source_update_at": product.last_source_update_at,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }


def _directory_product_options() -> tuple:
    return (
        *_product_options(),
        selectinload(Product.source_links).selectinload(ProductSourceLink.source),
    )


def _normalized_codes(values: list[str]) -> list[str]:
    seen = set()
    codes = []
    for value in values:
        code = value.strip()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _directory_filters(
    payload: DirectoryProductsIn,
    *,
    include_brand: bool = True,
    include_category: bool = True,
) -> list:
    filters = []
    if payload.q:
        raw_query = payload.q.strip()
        if raw_query:
            normalized_query = normalize_text(raw_query)
            normalized = f"%{normalized_query}%"
            raw_like = f"%{raw_query}%"
            category_match = Product.categories.any(
                ProductCategory.category.has(
                    or_(
                        Category.slug.like(normalized),
                        func.lower(Category.name).like(normalized),
                    )
                )
            )
            filters.append(
                or_(
                    Product.normalized_name.like(normalized),
                    Product.product_code.like(raw_like),
                    Product.barcode.like(raw_like),
                    Product.brand.has(Brand.normalized_name.like(normalized)),
                    category_match,
                )
            )
    if include_brand and payload.brand_codes:
        filters.append(Product.brand_code.in_(payload.brand_codes))
    if include_category and payload.category_codes:
        filters.append(Product.categories.any(ProductCategory.category_code.in_(payload.category_codes)))
    return filters


def _coerce_directory_payload(payload: DirectoryProductsIn) -> DirectoryProductsIn:
    payload.brand_codes = _normalized_codes(payload.brand_codes)
    payload.category_codes = _normalized_codes(payload.category_codes)
    if payload.group_kind == "brand" and payload.group_code:
        payload.brand_codes = _normalized_codes([*payload.brand_codes, payload.group_code])
    if payload.group_kind == "category" and payload.group_code:
        payload.category_codes = _normalized_codes([*payload.category_codes, payload.group_code])
    return payload


def _source_labels(product: Product) -> list[str]:
    labels = {
        link.source.name if link.source else link.source_code
        for link in product.source_links
        if link.active
    }
    return sorted(labels)


def _category_labels(product: Product) -> list[str]:
    labels = {link.category.name for link in product.categories if link.category}
    return sorted(labels)


def _risk_summaries(db: Session, products: list[Product], profile: dict) -> dict[str, dict]:
    ingredient_codes = sorted(
        {
            link.ingredient_code
            for product in products
            for link in product.ingredients
            if link.ingredient_code
        }
    )
    if ingredient_codes:
        rules = db.scalars(
            select(RiskRule)
            .where(RiskRule.ingredient_code.in_(ingredient_codes), RiskRule.active.is_(True))
            .options(selectinload(RiskRule.ingredient))
        ).all()
    else:
        rules = []
    rules_by_ingredient: dict[str, list[RiskRule]] = defaultdict(list)
    for rule in rules:
        rules_by_ingredient[rule.ingredient_code].append(rule)

    summaries = {}
    for product in products:
        candidate_rules = [
            rule
            for ingredient in product.ingredients
            for rule in rules_by_ingredient.get(ingredient.ingredient_code, [])
        ]
        matched = [rule for rule in candidate_rules if _rule_applies(rule, product, profile)]
        score = max([rule.severity_score for rule in matched], default=0)
        summaries[product.product_code] = {
            "severity": SEVERITY_LABELS.get(score, "unknown"),
            "score": score,
            "matched_ingredient_count": len({rule.ingredient_code for rule in matched}),
            "side_effects": sorted({effect for rule in matched for effect in rule.side_effects}),
        }
    return summaries


def _brand_facets(db: Session, payload: DirectoryProductsIn) -> list[DirectoryFacetOut]:
    rows = db.execute(
        select(Brand, func.count(func.distinct(Product.product_code)).label("product_count"))
        .join(Product, Product.brand_code == Brand.brand_code)
        .where(*_directory_filters(payload, include_brand=False))
        .group_by(Brand.brand_code, Brand.name)
        .order_by(desc("product_count"), Brand.name)
        .limit(120)
    ).all()
    selected = set(payload.brand_codes)
    return [
        DirectoryFacetOut(
            kind="brand",
            code=brand.brand_code,
            name=brand.name,
            product_count=product_count,
            selected=brand.brand_code in selected,
        )
        for brand, product_count in rows
    ]


def _category_facets(db: Session, payload: DirectoryProductsIn) -> list[DirectoryFacetOut]:
    rows = db.execute(
        select(Category, func.count(func.distinct(Product.product_code)).label("product_count"))
        .join(ProductCategory, ProductCategory.category_code == Category.category_code)
        .join(Product, Product.product_code == ProductCategory.product_code)
        .where(*_directory_filters(payload, include_category=False))
        .group_by(Category.category_code, Category.name, Category.slug)
        .order_by(desc("product_count"), Category.name)
        .limit(120)
    ).all()
    selected = set(payload.category_codes)
    return [
        DirectoryFacetOut(
            kind="category",
            code=category.category_code,
            name=category.name,
            slug=category.slug,
            product_count=product_count,
            selected=category.category_code in selected,
        )
        for category, product_count in rows
    ]


@router.get("", response_model=list[ProductListOut])
def list_products(
    q: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Product]:
    stmt: Select[tuple[Product]] = select(Product).options(*_product_options()).offset(offset).limit(limit)
    if q:
        normalized = f"%{normalize_text(q)}%"
        stmt = stmt.where(
            (Product.normalized_name.like(normalized))
            | Product.product_code.like(f"%{q}%")
            | Product.barcode.like(f"%{q}%")
        )
    return list(db.scalars(stmt).unique().all())


@router.get("/directory/groups", response_model=list[DirectoryGroupOut])
def list_directory_groups(
    kind: str = Query(default="brand", pattern="^(brand|category)$"),
    q: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[DirectoryGroupOut]:
    if kind == "brand":
        stmt = (
            select(Brand, func.count(Product.product_code).label("product_count"))
            .join(Product, Product.brand_code == Brand.brand_code)
        )
        if q:
            normalized_query = normalize_text(q)
            normalized = f"%{normalized_query}%"
            prefix = f"{normalized_query}%"
            stmt = stmt.where(Brand.normalized_name.like(normalized))
            order_by = (
                case((Brand.normalized_name == normalized_query, 0), else_=1),
                case((Brand.normalized_name.like(prefix), 0), else_=1),
                desc("product_count"),
                Brand.name,
            )
        else:
            order_by = (desc("product_count"), Brand.name)
        rows = db.execute(
            stmt
            .group_by(Brand.brand_code)
            .order_by(*order_by)
            .limit(limit)
        ).all()
        return [
            DirectoryGroupOut(
                kind="brand",
                code=brand.brand_code,
                name=brand.name,
                product_count=product_count,
            )
            for brand, product_count in rows
        ]

    stmt = (
        select(Category, func.count(ProductCategory.product_code).label("product_count"))
        .join(ProductCategory, ProductCategory.category_code == Category.category_code)
    )
    if q:
        normalized_query = normalize_text(q)
        normalized = f"%{normalized_query}%"
        prefix = f"{normalized_query}%"
        category_name = func.lower(Category.name)
        stmt = stmt.where((Category.slug.like(normalized)) | (category_name.like(normalized)))
        order_by = (
            case((Category.slug == normalized_query, 0), else_=1),
            case((category_name == normalized_query, 0), else_=1),
            case((Category.slug.like(prefix), 0), else_=1),
            case((category_name.like(prefix), 0), else_=1),
            desc("product_count"),
            Category.name,
        )
    else:
        order_by = (desc("product_count"), Category.name)
    rows = db.execute(
        stmt
        .group_by(Category.category_code)
        .order_by(*order_by)
        .limit(limit)
    ).all()
    return [
        DirectoryGroupOut(
            kind="category",
            code=category.category_code,
            name=category.name,
            slug=category.slug,
            product_count=product_count,
        )
        for category, product_count in rows
    ]


@router.post("/directory/products", response_model=DirectoryProductsPageOut)
def list_directory_products(payload: DirectoryProductsIn, db: Session = Depends(get_db)) -> dict:
    payload = _coerce_directory_payload(payload)
    filters = _directory_filters(payload)
    total = db.scalar(select(func.count()).select_from(Product).where(*filters)) or 0
    coarse_score = func.coalesce(func.max(RiskRule.severity_score), 0).label("coarse_score")
    matched_rule_count = func.count(func.distinct(RiskRule.risk_rule_code)).label("matched_rule_count")
    ranking_stmt = (
        select(Product.product_code, coarse_score, matched_rule_count)
        .outerjoin(Brand, Product.brand_code == Brand.brand_code)
        .outerjoin(ProductIngredient, ProductIngredient.product_code == Product.product_code)
        .outerjoin(
            RiskRule,
            and_(
                RiskRule.ingredient_code == ProductIngredient.ingredient_code,
                RiskRule.active.is_(True),
            ),
        )
        .where(*filters)
        .group_by(Product.product_code, Product.normalized_name, Product.confidence_score, Brand.name)
    )
    sort_orders = {
        "risk_desc": (coarse_score.desc(), matched_rule_count.desc(), Product.normalized_name),
        "name_asc": (Product.normalized_name, Product.product_code),
        "name_desc": (desc(Product.normalized_name), Product.product_code),
        "brand_asc": (Brand.name, Product.normalized_name, Product.product_code),
        "confidence_desc": (desc(Product.confidence_score), Product.normalized_name, Product.product_code),
    }
    rank_rows = db.execute(
        ranking_stmt
        .order_by(*sort_orders.get(payload.sort, sort_orders["risk_desc"]))
        .offset(payload.offset)
        .limit(payload.limit)
    ).all()
    product_codes = [row[0] for row in rank_rows]
    products_by_code = {}
    if product_codes:
        products_by_code = {
            product.product_code: product
            for product in db.scalars(
                select(Product)
                .where(Product.product_code.in_(product_codes))
                .options(*_directory_product_options())
            )
            .unique()
            .all()
        }
    products = [products_by_code[code] for code in product_codes if code in products_by_code]
    profile = payload.profile.model_dump()
    risk_by_code = _risk_summaries(db, products, profile)
    summaries = []
    for product in products:
        risk = risk_by_code[product.product_code]
        summaries.append(
            {
                "product": product,
                "severity": risk["severity"],
                "score": risk["score"],
                "matched_ingredient_count": risk["matched_ingredient_count"],
                "side_effects": risk["side_effects"],
                "source_labels": _source_labels(product),
                "category_labels": _category_labels(product),
            }
        )
    return {
        "items": summaries,
        "total": total,
        "limit": payload.limit,
        "offset": payload.offset,
        "sort": payload.sort,
        "brand_facets": _brand_facets(db, payload),
        "category_facets": _category_facets(db, payload),
    }


@router.get("/meta/count", include_in_schema=False)
def product_count(db: Session = Depends(get_db)) -> dict[str, int]:
    return {"products": db.scalar(select(func.count()).select_from(Product)) or 0}


@router.get("/{product_code}", response_model=ProductDetailOut)
def get_product(product_code: str, db: Session = Depends(get_db)) -> dict:
    product = db.scalar(
        select(Product).where(Product.product_code == product_code).options(*_product_detail_options())
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return _product_detail_payload(db, product)


@router.get("/{product_code}/categories", response_model=list[CategoryOut])
def get_product_categories(product_code: str, db: Session = Depends(get_db)) -> list[CategoryOut]:
    product = db.scalar(
        select(Product).where(Product.product_code == product_code).options(selectinload(Product.categories).selectinload(ProductCategory.category))
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return [CategoryOut.model_validate(link.category) for link in product.categories]
