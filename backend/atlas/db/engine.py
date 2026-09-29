"""The one SQLAlchemy engine factory for Atlas's database."""

import sqlalchemy
from sqlalchemy import Engine

from atlas.settings import Settings


def create_engine(settings: Settings) -> Engine:
    """An engine for `settings.database_url`; pre-ping drops connections the server closed."""
    return sqlalchemy.create_engine(settings.database_url, pool_pre_ping=True)
