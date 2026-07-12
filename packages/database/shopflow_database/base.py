"""
Each service needs its OWN declarative base with its OWN MetaData — NOT a
shared Base class imported from here. SQLAlchemy ties MetaData to the
specific Base class: if auth-service and inventory-service both imported
one shared `Base`, every model in both services would register into the
same MetaData registry, and Alembic autogenerate for either service would
see (and try to manage) the other service's tables. That's exactly the
cross-service leakage this architecture avoids (see mixins.py docstring).

So this module exports a FACTORY, not an instance:

    # in your service's app/domain/base.py
    from shopflow_database import create_base
    Base = create_base()

Each call returns a brand new class with its own fresh MetaData.
"""
from sqlalchemy.orm import DeclarativeBase


def create_base() -> type[DeclarativeBase]:
    """Return a fresh declarative base with its own isolated MetaData.

    Call this once per service, at import time, and reuse the returned
    class for every model in that service.
    """

    class Base(DeclarativeBase):
        pass

    return Base
