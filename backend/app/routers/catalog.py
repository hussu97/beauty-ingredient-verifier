from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, and_, case, desc, func, select
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
    DirectoryGroupOut,
    DirectoryProductsIn,
    DirectoryProductsPageOut,
    ProductDetailOut,
    ProductListOut,
)
from app.services.normalization import normalize_text
from app.services.risk import evaluate_loaded_product_risk
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
    product_filter = None
    if payload.group_kind == "brand":
        if db.get(Brand, payload.group_code) is None:
            raise HTTPException(status_code=404, detail="Brand not found")
        product_filter = Product.brand_code == payload.group_code
        total_stmt = select(func.count()).select_from(Product).where(product_filter)
        rank_from = select(Product.product_code)
    else:
        if db.get(Category, payload.group_code) is None:
            raise HTTPException(status_code=404, detail="Category not found")
        product_filter = ProductCategory.category_code == payload.group_code
        total_stmt = (
            select(func.count(func.distinct(Product.product_code)))
            .select_from(Product)
            .join(ProductCategory)
            .where(product_filter)
        )
        rank_from = select(Product.product_code).join(ProductCategory)

    total = db.scalar(total_stmt) or 0
    coarse_score = func.coalesce(func.max(RiskRule.severity_score), 0).label("coarse_score")
    matched_rule_count = func.count(func.distinct(RiskRule.risk_rule_code)).label("matched_rule_count")
    window_limit = min(max(payload.limit * 4, payload.limit), 240)
    rank_rows = db.execute(
        rank_from.add_columns(coarse_score, matched_rule_count)
        .outerjoin(ProductIngredient, ProductIngredient.product_code == Product.product_code)
        .outerjoin(
            RiskRule,
            and_(
                RiskRule.ingredient_code == ProductIngredient.ingredient_code,
                RiskRule.active.is_(True),
            ),
        )
        .where(product_filter)
        .group_by(Product.product_code)
        .order_by(desc("coarse_score"), desc("matched_rule_count"), Product.normalized_name)
        .offset(payload.offset)
        .limit(window_limit)
    ).all()
    product_codes = [row[0] for row in rank_rows]
    products_by_code = {
        product.product_code: product
        for product in db.scalars(
            select(Product)
            .where(Product.product_code.in_(product_codes))
            .options(*_product_options())
        )
        .unique()
        .all()
    }
    products = [products_by_code[code] for code in product_codes if code in products_by_code]
    summaries = []
    profile = payload.profile.model_dump()
    for product in products:
        risk = evaluate_loaded_product_risk(db, product, profile, persist=False)
        summaries.append(
            {
                "product": product,
                "severity": risk["severity"],
                "score": risk["score"],
                "matched_ingredient_count": len(risk["matched_ingredients"]),
                "side_effects": risk["side_effects"],
            }
        )

    summaries.sort(
        key=lambda item: (
            -item["score"],
            -item["matched_ingredient_count"],
            -len(item["side_effects"]),
            item["product"].name.lower(),
        )
    )
    return {
        "items": summaries[: payload.limit],
        "total": total,
        "limit": payload.limit,
        "offset": payload.offset,
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
