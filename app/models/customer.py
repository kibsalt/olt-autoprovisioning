from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FixedPppoeCust(Base, TimestampMixin):
    __tablename__ = "fixed_pppoe_cust"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    service_id: Mapped[str] = mapped_column(String(100), nullable=False)
    package: Mapped[str] = mapped_column(String(50), nullable=False, server_default="GPON-10M")
    pppoe_username: Mapped[str] = mapped_column(String(255), nullable=False)
    pppoe_password: Mapped[str] = mapped_column(String(255), nullable=False)
    vlan_id: Mapped[int] = mapped_column(Integer, nullable=False)
