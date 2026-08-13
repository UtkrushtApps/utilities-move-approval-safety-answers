from __future__ import annotations

import sqlite3
from datetime import date

from agent.state import MoveStore


class ToolFailure(RuntimeError):
    """Raised when the service-order boundary rejects an operation."""


class CloseServiceTool:
    def __init__(self, store: MoveStore) -> None:
        self.store = store

    async def close_service_account(
        self,
        *,
        customer_id: str,
        account_id: str,
        stop_date: date,
        operation_key: str,
    ) -> int:
        """Create one service order for an idempotency key.

        The public tool contract remains unchanged. The durable unique keys are a
        final defensive layer; orchestration is responsible for reserving the
        operation before invoking this boundary.
        """
        if not self.store.account_belongs_to(account_id, customer_id):
            raise ToolFailure("Account is unavailable to this customer")

        try:
            with self.store._transaction():
                existing = self.store.connection.execute(
                    "SELECT order_id FROM service_orders WHERE operation_key = ?",
                    (operation_key,),
                ).fetchone()
                if existing is not None:
                    return int(existing["order_id"])

                self.store.connection.execute(
                    """
                    INSERT INTO tool_calls(
                        account_id, stop_date, operation_key, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        stop_date.isoformat(),
                        operation_key,
                        self.store._now(),
                    ),
                )
                cursor = self.store.connection.execute(
                    """
                    INSERT INTO service_orders(
                        account_id, stop_date, operation_key
                    ) VALUES (?, ?, ?)
                    """,
                    (account_id, stop_date.isoformat(), operation_key),
                )
                return int(cursor.lastrowid)
        except sqlite3.DatabaseError as exc:
            raise ToolFailure("Service order could not be recorded") from exc
