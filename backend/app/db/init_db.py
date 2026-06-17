from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Base, Product, Source
from app.db.session import engine
from app.services.enrichment import seed_reference_sources_and_rules
from app.services.importers.open_beauty_facts import import_open_beauty_facts


def init_db(settings: Settings) -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    if settings.bootstrap_demo_data:
        with Session(engine) as db:
            has_sources = db.scalar(select(Source).limit(1))
            has_products = db.scalar(select(Product).limit(1))
            if not has_sources:
                seed_reference_sources_and_rules(db)
                db.commit()
            if not has_products:
                import_open_beauty_facts(db, source_path=None, limit=20)
                seed_reference_sources_and_rules(db)
                db.commit()
