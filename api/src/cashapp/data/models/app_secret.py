"""ORM model for secrets stored encrypted in the database."""

from datetime import datetime

from sqlalchemy import Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import UtcDateTime


class AppSecret(Base):
    """One secret, by name. `ciphertext` is nonce + AES-GCM output; the value is never stored."""

    __tablename__ = "app_secret"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(256), nullable=False)
