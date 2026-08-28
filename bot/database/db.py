from __future__ import annotations

import json

import aiosqlite
from pathlib import Path

from bot.database.models import ACTIVE_STATUSES, DEFAULT_ADDRESSES, Address, Order

GROUP_MENU_MIDS_KEY = "group_menu_mids"
GROUP_MENU_CHAT_ID_KEY = "group_menu_chat_id"
MAX_GROUP_MENU_MESSAGES = 8


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA foreign_keys = ON")
        await self._create_tables()
        await self._seed_addresses()

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not connected")
        return self._connection

    async def _create_tables(self) -> None:
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL UNIQUE,
                short_name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guest_id INTEGER NOT NULL,
                guest_username TEXT,
                guest_name TEXT NOT NULL,
                address TEXT NOT NULL,
                address_short TEXT NOT NULL,
                address_clarification TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL,
                order_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                submitted INTEGER NOT NULL DEFAULT 0,
                staff_message_mid TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_orders_guest_id ON orders(guest_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

            -- Связь mid сообщений сотрудника с заказом (для Reply)
            CREATE TABLE IF NOT EXISTS staff_messages (
                mid TEXT PRIMARY KEY,
                order_id INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'card'
            );

            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE,
                guest_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            """
        )
        await self.conn.commit()

    async def _seed_addresses(self) -> None:
        cursor = await self.conn.execute("SELECT COUNT(*) FROM addresses")
        row = await cursor.fetchone()
        if row[0] > 0:
            return

        for index, (full_name, short_name) in enumerate(DEFAULT_ADDRESSES):
            await self.conn.execute(
                """
                INSERT INTO addresses (full_name, short_name, is_active, sort_order)
                VALUES (?, ?, 1, ?)
                """,
                (full_name, short_name, index),
            )
        await self.conn.commit()

    # --- Addresses ---

    async def get_active_addresses(self) -> list[Address]:
        cursor = await self.conn.execute(
            """
            SELECT id, full_name, short_name, is_active, sort_order
            FROM addresses
            WHERE is_active = 1
            ORDER BY sort_order, id
            """
        )
        rows = await cursor.fetchall()
        return [
            Address(
                id=row["id"],
                full_name=row["full_name"],
                short_name=row["short_name"],
                is_active=bool(row["is_active"]),
                sort_order=row["sort_order"],
            )
            for row in rows
        ]

    async def get_address_by_id(self, address_id: int) -> Address | None:
        cursor = await self.conn.execute(
            """
            SELECT id, full_name, short_name, is_active, sort_order
            FROM addresses WHERE id = ?
            """,
            (address_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return Address(
            id=row["id"],
            full_name=row["full_name"],
            short_name=row["short_name"],
            is_active=bool(row["is_active"]),
            sort_order=row["sort_order"],
        )

    # --- Orders ---

    async def create_order(
        self,
        guest_id: int,
        guest_username: str | None,
        guest_name: str,
        address: str,
        address_short: str,
        address_clarification: str,
        phone: str,
    ) -> Order:
        cursor = await self.conn.execute(
            """
            INSERT INTO orders (
                guest_id, guest_username, guest_name,
                address, address_short, address_clarification, phone
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guest_id,
                guest_username,
                guest_name,
                address,
                address_short,
                address_clarification,
                phone,
            ),
        )
        await self.conn.commit()
        order = await self.get_order(cursor.lastrowid)
        if order is None:
            raise RuntimeError("Failed to create order")
        return order

    async def get_order(self, order_id: int) -> Order | None:
        cursor = await self.conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        )
        row = await cursor.fetchone()
        return Order.from_row(row) if row else None

    async def get_active_order_for_guest(self, guest_id: int) -> Order | None:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        cursor = await self.conn.execute(
            f"""
            SELECT * FROM orders
            WHERE guest_id = ? AND status IN ({placeholders})
            ORDER BY id DESC LIMIT 1
            """,
            (guest_id, *ACTIVE_STATUSES),
        )
        row = await cursor.fetchone()
        return Order.from_row(row) if row else None

    async def get_pending_order_for_guest(self, guest_id: int) -> Order | None:
        """Активный заказ, который ещё не ушёл сотруднику."""
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        cursor = await self.conn.execute(
            f"""
            SELECT * FROM orders
            WHERE guest_id = ? AND status IN ({placeholders}) AND submitted = 0
            ORDER BY id DESC LIMIT 1
            """,
            (guest_id, *ACTIVE_STATUSES),
        )
        row = await cursor.fetchone()
        return Order.from_row(row) if row else None

    async def get_last_completed_order_without_review(
        self, guest_id: int
    ) -> Order | None:
        cursor = await self.conn.execute(
            """
            SELECT o.* FROM orders o
            LEFT JOIN reviews r ON r.order_id = o.id
            WHERE o.guest_id = ? AND o.status = 'completed' AND r.id IS NULL
            ORDER BY o.id DESC LIMIT 1
            """,
            (guest_id,),
        )
        row = await cursor.fetchone()
        return Order.from_row(row) if row else None

    async def save_review(
        self,
        order_id: int,
        guest_id: int,
        rating: int,
        comment: str = "",
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO reviews (order_id, guest_id, rating, comment)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                rating = excluded.rating,
                comment = excluded.comment,
                created_at = datetime('now', 'localtime')
            """,
            (order_id, guest_id, rating, comment),
        )
        await self.conn.commit()

    async def has_review(self, order_id: int) -> bool:
        cursor = await self.conn.execute(
            "SELECT 1 FROM reviews WHERE order_id = ?",
            (order_id,),
        )
        return await cursor.fetchone() is not None

    async def update_order_text(self, order_id: int, order_text: str) -> None:
        await self.conn.execute(
            """
            UPDATE orders
            SET order_text = ?, updated_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (order_text, order_id),
        )
        await self.conn.commit()

    async def update_order_status(self, order_id: int, status: str) -> None:
        await self.conn.execute(
            """
            UPDATE orders
            SET status = ?, updated_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (status, order_id),
        )
        await self.conn.commit()

    async def mark_order_submitted(
        self,
        order_id: int,
        staff_message_mid: str | None = None,
    ) -> None:
        await self.conn.execute(
            """
            UPDATE orders
            SET submitted = 1,
                staff_message_mid = COALESCE(?, staff_message_mid),
                updated_at = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (staff_message_mid, order_id),
        )
        await self.conn.commit()

    # --- Staff message mapping (Reply → заказ) ---

    async def save_staff_message(
        self,
        mid: str,
        order_id: int,
        kind: str = "card",
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO staff_messages (mid, order_id, kind)
            VALUES (?, ?, ?)
            ON CONFLICT(mid) DO UPDATE SET
                order_id = excluded.order_id,
                kind = excluded.kind
            """,
            (mid, order_id, kind),
        )
        await self.conn.commit()

    async def get_order_by_staff_mid(self, mid: str) -> Order | None:
        cursor = await self.conn.execute(
            """
            SELECT o.* FROM orders o
            JOIN staff_messages sm ON sm.order_id = o.id
            WHERE sm.mid = ?
            """,
            (mid,),
        )
        row = await cursor.fetchone()
        return Order.from_row(row) if row else None

    # --- Settings / group menu ---

    async def get_guest_keyboard_mids(self, user_id: int) -> list[str]:
        raw = await self.get_setting(f"guest_kb:{user_id}")
        if not raw:
            return []
        try:
            mids = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [mid for mid in mids if isinstance(mid, str) and mid]

    async def set_guest_keyboard_mids(self, user_id: int, mids: list[str]) -> None:
        unique: list[str] = []
        for mid in mids:
            if mid and mid not in unique:
                unique.append(mid)
        await self.set_setting(f"guest_kb:{user_id}", json.dumps(unique[-20:]))

    async def get_setting(self, key: str) -> str | None:
        cursor = await self.conn.execute(
            "SELECT value FROM bot_settings WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO bot_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        await self.conn.commit()

    async def save_group_menu_message(self, chat_id: int, mid: str) -> None:
        """Запоминаем последние сообщения группы — их отправим гостю как меню дня."""
        raw = await self.get_setting(GROUP_MENU_MIDS_KEY)
        mids: list[str] = json.loads(raw) if raw else []
        if mid not in mids:
            mids.append(mid)
        mids = mids[-MAX_GROUP_MENU_MESSAGES:]
        await self.set_setting(GROUP_MENU_MIDS_KEY, json.dumps(mids))
        await self.set_setting(GROUP_MENU_CHAT_ID_KEY, str(chat_id))

    async def get_group_menu_mids(self) -> tuple[int, list[str]] | None:
        raw = await self.get_setting(GROUP_MENU_MIDS_KEY)
        chat_raw = await self.get_setting(GROUP_MENU_CHAT_ID_KEY)
        if not raw or not chat_raw:
            return None
        mids = json.loads(raw)
        if not mids:
            return None
        return int(chat_raw), mids
