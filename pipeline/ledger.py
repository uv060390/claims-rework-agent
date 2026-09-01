"""Append-only audit ledger.

Every decision layer appends one ``pipeline_events`` row. The full provenance of
any outcome must be reconstructable from this table alone. The public API exposes
append and read — deliberately no update or delete (see CLAUDE.md hard rules).
"""

import hashlib
import json
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
    select,
)

from pipeline.config import LEDGER_DB_URL
from pipeline.schemas import LedgerEvent

metadata = MetaData()

pipeline_events = Table(
    "pipeline_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("request_id", String(32), nullable=False, index=True),
    Column("layer", String(64), nullable=False),
    Column("decision", String(256), nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


def hash_payload(payload: dict[str, Any]) -> str:
    """Canonical sha256 of a JSON-serializable payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Ledger:
    def __init__(self, db_url: str = LEDGER_DB_URL):
        self.engine = create_engine(db_url)
        metadata.create_all(self.engine)

    def append(self, event: LedgerEvent) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(insert(pipeline_events).values(**event.model_dump()))
            return int(result.inserted_primary_key[0])

    def for_request(self, request_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(pipeline_events)
            .where(pipeline_events.c.request_id == request_id)
            .order_by(pipeline_events.c.id)
        )
        with self.engine.connect() as conn:
            return [dict(row._mapping) for row in conn.execute(stmt)]
