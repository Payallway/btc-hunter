import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import aiosqlite

logger = logging.getLogger(__name__)


class OfferRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS offers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raw_text TEXT NOT NULL,
                    country TEXT,
                    method TEXT,
                    fee TEXT,
                    rate TEXT,
                    limits TEXT,
                    conditions TEXT,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            await db.commit()

            cursor = await db.execute("PRAGMA table_info(offers);")
            columns = [row[1] for row in await cursor.fetchall()]

            if "kind" not in columns:
                await db.execute("ALTER TABLE offers ADD COLUMN kind TEXT;")
            if "fee_percent" not in columns:
                await db.execute("ALTER TABLE offers ADD COLUMN fee_percent REAL;")

            await db.commit()

        logger.info("Database initialised at %s", self.db_path)

    async def save_offer(self, parsed: Dict[str, Any], raw_text: str) -> int:
        now = datetime.utcnow().isoformat()

        def safe_float(value: Any) -> Optional[float]:
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO offers (
                    raw_text, country, method, fee, rate, limits,
                    conditions, status, created_at, updated_at,
                    kind, fee_percent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_text,
                    parsed.get("country"),
                    parsed.get("method"),
                    parsed.get("fee"),
                    parsed.get("rate"),
                    parsed.get("limits"),
                    parsed.get("conditions"),
                    "new",
                    now,
                    now,
                    parsed.get("kind"),
                    safe_float(parsed.get("fee_percent")),
                ),
            )
            await db.commit()
            return cursor.lastrowid

    async def list_last_offers(self, limit: int = 10) -> List[Sequence[Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT id, country, method, fee, rate, status, created_at, kind, fee_percent
                FROM offers
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return await cursor.fetchall()

    async def get_offer_by_id(self, offer_id: int) -> Optional[Tuple[Any, ...]]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT id, raw_text, country, method, fee, rate,
                       limits, conditions, status, created_at, updated_at,
                       kind, fee_percent
                FROM offers
                WHERE id = ?
                """,
                (offer_id,),
            )
            return await cursor.fetchone()

    async def search_offers(self, filters: Dict[str, Any], limit: int = 20) -> List[Sequence[Any]]:
        conditions: List[str] = []
        params: List[Any] = []

        country = filters.get("country")
        method = filters.get("method")
        status = filters.get("status")
        kind = filters.get("kind")
        min_fee = filters.get("min_fee_percent")
        max_fee = filters.get("max_fee_percent")

        if country:
            conditions.append("LOWER(country) LIKE ?")
            params.append(f"%{country.lower()}%")
        if method:
            conditions.append("LOWER(method) LIKE ?")
            params.append(f"%{method.lower()}%")
        if status:
            conditions.append("status = ?")
            params.append(status)
        if kind:
            conditions.append("kind = ?")
            params.append(kind)
        if min_fee is not None:
            conditions.append("fee_percent >= ?")
            params.append(float(min_fee))
        if max_fee is not None:
            conditions.append("fee_percent <= ?")
            params.append(float(max_fee))

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"""
                SELECT id, country, method, fee, rate, status, kind, fee_percent
                FROM offers
                WHERE {where_clause}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            )
            return await cursor.fetchall()
