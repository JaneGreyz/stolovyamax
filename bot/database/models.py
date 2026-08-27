from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

OrderStatus = str

STATUS_NEW = "new"
STATUS_ACCEPTED = "accepted"
STATUS_AWAITING_PAYMENT = "awaiting_payment"
STATUS_IN_DELIVERY = "in_delivery"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES = (
    STATUS_NEW,
    STATUS_ACCEPTED,
    STATUS_AWAITING_PAYMENT,
    STATUS_IN_DELIVERY,
)

STATUS_CALLBACK_MAP = {
    "accepted": STATUS_ACCEPTED,
    "awaiting_payment": STATUS_AWAITING_PAYMENT,
    "in_delivery": STATUS_IN_DELIVERY,
    "completed": STATUS_COMPLETED,
    "cancelled": STATUS_CANCELLED,
}


@dataclass
class Address:
    id: int
    full_name: str
    short_name: str
    is_active: bool
    sort_order: int


@dataclass
class Order:
    id: int
    guest_id: int
    guest_username: str | None
    guest_name: str
    address: str
    address_short: str
    address_clarification: str
    phone: str
    order_text: str
    status: OrderStatus
    submitted: bool
    staff_message_mid: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: Any) -> "Order":
        return cls(
            id=row["id"],
            guest_id=row["guest_id"],
            guest_username=row["guest_username"],
            guest_name=row["guest_name"],
            address=row["address"],
            address_short=row["address_short"],
            address_clarification=row["address_clarification"],
            phone=row["phone"],
            order_text=row["order_text"],
            status=row["status"],
            submitted=bool(row["submitted"]),
            staff_message_mid=row["staff_message_mid"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


DEFAULT_ADDRESSES: list[tuple[str, str]] = [
    ("Улица Юрия Якулина, 3", "ЮН 3"),
    ("Ленинградский проспект, 36, строение 13", "ЛП 36с13"),
    ("Ленинградский проспект, 36, строение 39", "ЛП 36с39"),
    ("Ленинградский проспект, 36, строение 40", "ЛП 36с40"),
    ("Ленинградский проспект, 36, строение 41", "ЛП 36с41"),
    ("Ленинградский проспект, 36, строение 30", "ЛП 36с30"),
    ("Ленинградский проспект, 36, строение 38", "ЛП 36с38"),
    ("Ленинградский проспект, 36, строение 37", "ЛП 36с37"),
    ("Ленинградский проспект, 36, строение 36", "ЛП 36с36"),
    ("Ленинградский проспект, 36, строение 11", "ЛП 36с11"),
    ("Ленинградский проспект, 36, строение 10", "ЛП 36с10"),
    ("Ленинградский проспект, 36, строение 9", "ЛП 36с9"),
    ("Ленинградский проспект, 36, строение 31", "ЛП 36с31"),
    ("Ленинградский проспект, 36, строение 33", "ЛП 36с33"),
    ("Ленинградский проспект, владение 36", "ЛП вл36"),
]
