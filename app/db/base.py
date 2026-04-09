from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import models so SQLAlchemy registers them before create_all()/Alembic autogenerate.
from app.db import models  # noqa: E402,F401
