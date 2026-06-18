from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorHit:
    embedding_code: str
    distance: float


def _dbapi_connection(db: Session):
    raw = db.connection().connection
    return (
        getattr(raw, "driver_connection", None)
        or getattr(raw, "dbapi_connection", None)
        or raw
    )


def load_sqlite_vec(db: Session) -> bool:
    if db.bind is None or db.bind.dialect.name != "sqlite":
        return False
    try:
        import sqlite_vec
    except ImportError:
        logger.debug("sqlite-vec is not installed")
        return False

    connection = _dbapi_connection(db)
    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        connection.execute("select vec_version()").fetchone()
    except Exception:
        logger.exception("Failed to load sqlite-vec extension")
        try:
            connection.enable_load_extension(False)
        except Exception:
            pass
        return False
    return True


def _table_name(dimensions: int) -> str:
    return f"image_embedding_vec_{int(dimensions)}"


def upsert_sqlite_vec_embedding(
    db: Session,
    *,
    embedding_code: str,
    image_code: str,
    product_code: str,
    model_name: str,
    vector: list[float],
) -> bool:
    if not vector or not load_sqlite_vec(db):
        return False

    connection = _dbapi_connection(db)
    dimensions = len(vector)
    table_name = _table_name(dimensions)
    vector_json = json.dumps(vector)
    try:
        connection.execute(
            """
            create table if not exists image_embedding_vec_meta (
              rowid integer primary key,
              embedding_code text not null unique,
              image_code text not null,
              product_code text not null,
              model_name text not null,
              dimensions integer not null
            )
            """
        )
        connection.execute(
            f"create virtual table if not exists {table_name} using vec0(embedding float[{dimensions}])"
        )
        row = connection.execute(
            "select rowid from image_embedding_vec_meta where embedding_code = ?",
            (embedding_code,),
        ).fetchone()
        if row is None:
            cursor = connection.execute(
                """
                insert into image_embedding_vec_meta
                  (embedding_code, image_code, product_code, model_name, dimensions)
                values (?, ?, ?, ?, ?)
                """,
                (embedding_code, image_code, product_code, model_name, dimensions),
            )
            rowid = cursor.lastrowid
        else:
            rowid = row[0]
            connection.execute(
                """
                update image_embedding_vec_meta
                set image_code = ?, product_code = ?, model_name = ?, dimensions = ?
                where rowid = ?
                """,
                (image_code, product_code, model_name, dimensions, rowid),
            )
            connection.execute(f"delete from {table_name} where rowid = ?", (rowid,))
        connection.execute(
            f"insert into {table_name}(rowid, embedding) values (?, ?)",
            (rowid, vector_json),
        )
    except Exception:
        logger.exception("Failed to upsert sqlite-vec embedding %s", embedding_code)
        return False
    return True


def query_sqlite_vec(
    db: Session,
    *,
    model_name: str,
    vector: list[float],
    limit: int,
) -> list[VectorHit]:
    if not vector or not load_sqlite_vec(db):
        return []

    connection = _dbapi_connection(db)
    dimensions = len(vector)
    table_name = _table_name(dimensions)
    vector_json = json.dumps(vector)
    try:
        rows = connection.execute(
            f"""
            select meta.embedding_code, vec.distance
            from {table_name} vec
            join image_embedding_vec_meta meta on meta.rowid = vec.rowid
            where vec.embedding match ?
              and meta.model_name = ?
            order by vec.distance
            limit ?
            """,
            (vector_json, model_name, limit),
        ).fetchall()
    except Exception:
        logger.exception("sqlite-vec query failed for model %s", model_name)
        return []
    return [VectorHit(embedding_code=str(row[0]), distance=float(row[1])) for row in rows]


def query_postgres_vec(
    db: Session,
    *,
    model_name: str,
    vector: list[float],
    limit: int,
) -> list[VectorHit]:
    if not vector or db.bind is None or db.bind.dialect.name != "postgresql":
        return []

    vector_json = json.dumps([float(item) for item in vector])
    try:
        rows = db.execute(
            sa.text(
                """
                select embedding_code, embedding <=> cast(:vector as vector) as distance
                from image_embedding_vectors
                where model_name = :model_name
                  and dimensions = :dimensions
                order by embedding <=> cast(:vector as vector)
                limit :limit
                """
            ),
            {
                "vector": vector_json,
                "model_name": model_name,
                "dimensions": len(vector),
                "limit": limit,
            },
        ).all()
    except Exception:
        logger.exception("PostgreSQL pgvector query failed for model %s", model_name)
        return []
    return [VectorHit(embedding_code=str(row[0]), distance=float(row[1])) for row in rows]
