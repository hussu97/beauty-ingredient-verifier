from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, case, desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Brand, Category, Product, ProductCategory, ProductIngredient
from app.db.session import get_db
from app.schemas import (
    CategoryOut,
    DirectoryGroupOut,
    DirectoryProductsIn,
    DirectoryProductsPageOut,
    DirectoryProductRiskOut,
    ProductDetailOut,
    ProductListOut,
)
from app.services.normalization import normalize_text
from app.services.risk import evaluate_loaded_product_risk

router = APIRouter(prefix="/products", tags=["catalog"])


def _product_options() -> tuple:
    return (
        selectinload(Product.brand),
        selectinload(Product.images),
        selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
        selectinload(Product.categories).selectinload(ProductCategory.category),
    )


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
    stmt: Select[tuple[Product]]
    if payload.group_kind == "brand":
        if db.get(Brand, payload.group_code) is None:
            raise HTTPException(status_code=404, detail="Brand not found")
        stmt = select(Product).where(Product.brand_code == payload.group_code)
    else:
        if db.get(Category, payload.group_code) is None:
            raise HTTPException(status_code=404, detail="Category not found")
        stmt = select(Product).join(ProductCategory).where(ProductCategory.category_code == payload.group_code)

    products = list(
        db.scalars(
            stmt.options(*_product_options())
            .order_by(Product.name)
        )
        .unique()
        .all()
    )
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
        "items": summaries[payload.offset : payload.offset + payload.limit],
        "total": len(summaries),
        "limit": payload.limit,
        "offset": payload.offset,
    }


@router.get("/meta/count", include_in_schema=False)
def product_count(db: Session = Depends(get_db)) -> dict[str, int]:
    return {"products": db.scalar(select(func.count()).select_from(Product)) or 0}


@router.get("/{product_code}", response_model=ProductDetailOut)
def get_product(product_code: str, db: Session = Depends(get_db)) -> Product:
    product = db.scalar(
        select(Product).where(Product.product_code == product_code).options(*_product_options())
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get("/{product_code}/categories", response_model=list[CategoryOut])
def get_product_categories(product_code: str, db: Session = Depends(get_db)) -> list[CategoryOut]:
    product = db.scalar(
        select(Product).where(Product.product_code == product_code).options(selectinload(Product.categories).selectinload(ProductCategory.category))
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return [CategoryOut.model_validate(link.category) for link in product.categories]
