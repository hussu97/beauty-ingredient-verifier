from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Brand, ImageEmbedding, Ingredient, Product, ProductIngredient
from app.services.ml import cosine_similarity
from app.services.normalization import normalize_text, split_ingredients
from app.services.vector_store import query_postgres_vec, query_sqlite_vec


@dataclass(frozen=True)
class ProductMatch:
    product: Product
    confidence: float
    reasons: list[str]


def _product_load_options() -> tuple:
    return (
        selectinload(Product.brand),
        selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
    )


def _add_candidates(candidates: dict[str, Product], products: list[Product], *, limit: int) -> None:
    for product in products:
        candidates.setdefault(product.product_code, product)
        if len(candidates) >= limit:
            break


def _candidate_products(
    db: Session,
    *,
    normalized_query: str,
    raw_query: str | None,
    query_ingredients: set[str],
    limit: int,
) -> list[Product]:
    candidates: dict[str, Product] = {}
    candidate_limit = max(limit * 80, 120)

    if normalized_query:
        like_query = f"%{normalized_query}%"
        filters = [
            Product.normalized_name.like(like_query),
            Brand.normalized_name.like(like_query),
        ]
        if raw_query:
            filters.extend(
                [
                    Product.product_code.like(f"%{raw_query}%"),
                    Product.barcode.like(f"%{raw_query}%"),
                ]
            )
        stmt = (
            select(Product)
            .outerjoin(Brand)
            .where(or_(*filters))
            .options(*_product_load_options())
            .order_by(Product.normalized_name)
            .limit(candidate_limit)
        )
        _add_candidates(candidates, list(db.scalars(stmt).unique().all()), limit=candidate_limit)

        if len(candidates) < candidate_limit:
            tokens = [token for token in normalized_query.split() if len(token) >= 3][:5]
            if tokens:
                token_filters = [
                    or_(Product.normalized_name.like(f"%{token}%"), Brand.normalized_name.like(f"%{token}%"))
                    for token in tokens
                ]
                stmt = (
                    select(Product)
                    .outerjoin(Brand)
                    .where(or_(*token_filters))
                    .options(*_product_load_options())
                    .order_by(Product.normalized_name)
                    .limit(candidate_limit)
                )
                _add_candidates(candidates, list(db.scalars(stmt).unique().all()), limit=candidate_limit)

    if query_ingredients and len(candidates) < candidate_limit:
        ingredient_stmt = (
            select(Product)
            .join(ProductIngredient)
            .join(Ingredient)
            .where(Ingredient.normalized_name.in_(query_ingredients))
            .options(*_product_load_options())
            .limit(candidate_limit)
        )
        _add_candidates(candidates, list(db.scalars(ingredient_stmt).unique().all()), limit=candidate_limit)

    if not candidates and not normalized_query and not query_ingredients:
        stmt = select(Product).options(*_product_load_options()).order_by(Product.updated_at.desc()).limit(candidate_limit)
        _add_candidates(candidates, list(db.scalars(stmt).unique().all()), limit=candidate_limit)

    return list(candidates.values())


def search_products(
    db: Session,
    *,
    query: str | None = None,
    barcode: str | None = None,
    ingredient_text: str | None = None,
    limit: int = 5,
) -> list[ProductMatch]:
    if barcode:
        product = db.scalar(select(Product).where(Product.barcode == barcode))
        if product is not None:
            return [ProductMatch(product=product, confidence=0.99, reasons=["barcode exact match"])]

    normalized_query = normalize_text(query)
    query_ingredients = {normalize_text(item) for item in split_ingredients(ingredient_text)}
    query_ingredients.discard("")
    products = _candidate_products(
        db,
        normalized_query=normalized_query,
        raw_query=query,
        query_ingredients=query_ingredients,
        limit=limit,
    )
    matches: list[ProductMatch] = []
    for product in products:
        reasons: list[str] = []
        score = 0.0
        if normalized_query:
            name_score = fuzz.token_set_ratio(normalized_query, product.normalized_name) / 100
            if product.brand:
                brand_score = fuzz.token_set_ratio(normalized_query, product.brand.normalized_name) / 100
            else:
                brand_score = 0
            score += max(name_score, brand_score * 0.9) * 0.7
            if name_score > 0.65:
                reasons.append("product name similarity")
            if brand_score > 0.7:
                reasons.append("brand similarity")
        if query_ingredients and product.ingredients:
            product_ingredients = {link.ingredient.normalized_name for link in product.ingredients}
            overlap = len(query_ingredients & product_ingredients)
            if overlap:
                ingredient_score = min(overlap / max(len(query_ingredients), 1), 1)
                score += ingredient_score * 0.3
                reasons.append(f"{overlap} ingredient overlap")
        if score > 0:
            matches.append(ProductMatch(product=product, confidence=round(min(score, 0.96), 3), reasons=reasons))
    return sorted(matches, key=lambda item: item.confidence, reverse=True)[:limit]


def search_products_by_image_embedding(
    db: Session,
    *,
    vector: list[float],
    model_name: str,
    limit: int = 5,
) -> list[ProductMatch]:
    if not vector:
        return []

    hits = query_postgres_vec(db, model_name=model_name, vector=vector, limit=limit * 4)
    if not hits:
        hits = query_sqlite_vec(db, model_name=model_name, vector=vector, limit=limit * 4)
    matches_by_product: dict[str, ProductMatch] = {}
    if hits:
        embeddings = {
            item.embedding_code: item
            for item in db.scalars(
                select(ImageEmbedding).where(
                    ImageEmbedding.embedding_code.in_([hit.embedding_code for hit in hits])
                )
            ).all()
        }
        for hit in hits:
            embedding = embeddings.get(hit.embedding_code)
            if embedding is None:
                continue
            product = db.get(Product, embedding.product_code)
            if product is None:
                continue
            confidence = round(max(0.0, min(0.98, 1 - (hit.distance / 2))), 3)
            existing = matches_by_product.get(product.product_code)
            if existing is None or confidence > existing.confidence:
                matches_by_product[product.product_code] = ProductMatch(
                    product=product,
                    confidence=confidence,
                    reasons=["CLIP image similarity"],
                )
    else:
        embedding_count = db.scalar(
            select(func.count())
            .select_from(ImageEmbedding)
            .where(
                ImageEmbedding.model_name == model_name,
                ImageEmbedding.dimensions == len(vector),
            )
        ) or 0
        if embedding_count > 5000:
            return []
        embeddings = db.scalars(
            select(ImageEmbedding).where(
                ImageEmbedding.model_name == model_name,
                ImageEmbedding.dimensions == len(vector),
            )
        ).all()
        for embedding in embeddings:
            similarity = cosine_similarity(vector, embedding.vector)
            confidence = round(max(0.0, min(0.98, (similarity + 1) / 2)), 3)
            if confidence <= 0:
                continue
            product = db.get(Product, embedding.product_code)
            if product is None:
                continue
            existing = matches_by_product.get(product.product_code)
            if existing is None or confidence > existing.confidence:
                matches_by_product[product.product_code] = ProductMatch(
                    product=product,
                    confidence=confidence,
                    reasons=["CLIP image similarity"],
                )
    return sorted(matches_by_product.values(), key=lambda item: item.confidence, reverse=True)[:limit]


def merge_product_matches(*match_lists: list[ProductMatch], limit: int = 5) -> list[ProductMatch]:
    merged: dict[str, ProductMatch] = {}
    for matches in match_lists:
        for match in matches:
            existing = merged.get(match.product.product_code)
            if existing is None:
                merged[match.product.product_code] = match
                continue
            confidence = max(existing.confidence, match.confidence)
            reasons = list(dict.fromkeys([*existing.reasons, *match.reasons]))
            merged[match.product.product_code] = ProductMatch(
                product=match.product,
                confidence=confidence,
                reasons=reasons,
            )
    return sorted(merged.values(), key=lambda item: item.confidence, reverse=True)[:limit]
