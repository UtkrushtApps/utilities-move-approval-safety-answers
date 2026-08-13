from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from agent.schemas import PendingMove


class SessionOwnershipError(ValueError):
    """Raised when a session identifier is reused by another customer."""


class PendingStateConflict(RuntimeError):
    """Raised when an executing proposal cannot safely be replaced."""


class MoveStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(
            str(path),
            isolation_level=None,
            check_same_thread=False,
            timeout=30,
        )
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._create_schema()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Run a short write transaction while protecting the shared connection."""
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
            else:
                self.connection.execute("COMMIT")

    def _create_schema(self) -> None:
        with self._lock:
            self.connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS move_sessions (
                    session_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    pending_account_id TEXT,
                    pending_stop_date TEXT,
                    pending_state TEXT,
                    pending_revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_claims (
                    operation_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS service_orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    stop_date TEXT NOT NULL,
                    operation_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS tool_calls (
                    call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    stop_date TEXT NOT NULL,
                    operation_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trace_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self.connection.executemany(
                "INSERT OR IGNORE INTO accounts(account_id, customer_id) VALUES (?, ?)",
                [
                    ("acct_1001", "customer_north"),
                    ("acct_2002", "customer_south"),
                ],
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def operation_key(account_id: str, stop_date: date) -> str:
        """Build the global idempotency key for one irreversible closure."""
        return f"close-service:{account_id}:{stop_date.isoformat()}"

    @staticmethod
    def _pending_from_row(row: sqlite3.Row | None) -> PendingMove | None:
        if row is None or row["pending_account_id"] is None:
            return None
        return PendingMove(
            session_id=row["session_id"],
            customer_id=row["customer_id"],
            account_id=row["pending_account_id"],
            stop_date=date.fromisoformat(row["pending_stop_date"]),
            state=row["pending_state"],
            revision=row["pending_revision"],
        )

    def ensure_session(self, session_id: str, customer_id: str) -> None:
        with self._transaction():
            self.connection.execute(
                """
                INSERT OR IGNORE INTO move_sessions(
                    session_id, customer_id, updated_at
                ) VALUES (?, ?, ?)
                """,
                (session_id, customer_id, self._now()),
            )
            row = self.connection.execute(
                "SELECT customer_id FROM move_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None or row["customer_id"] != customer_id:
                raise SessionOwnershipError(
                    "Session is unavailable to the supplied customer"
                )

    def account_belongs_to(self, account_id: str, customer_id: str) -> bool:
        with self._lock:
            row = self.connection.execute(
                "SELECT 1 FROM accounts WHERE account_id = ? AND customer_id = ?",
                (account_id, customer_id),
            ).fetchone()
        return row is not None

    def save_pending(
        self,
        session_id: str,
        customer_id: str,
        account_id: str,
        stop_date: date,
    ) -> PendingMove:
        """Persist the exact proposal awaiting a later customer decision."""
        self.ensure_session(session_id, customer_id)
        with self._transaction():
            row = self.connection.execute(
                "SELECT pending_state FROM move_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is not None and row["pending_state"] == "executing":
                raise PendingStateConflict("A move approval is already executing")

            cursor = self.connection.execute(
                """
                UPDATE move_sessions
                SET pending_account_id = ?, pending_stop_date = ?,
                    pending_state = 'awaiting',
                    pending_revision = pending_revision + 1,
                    updated_at = ?
                WHERE session_id = ? AND customer_id = ?
                """,
                (
                    account_id,
                    stop_date.isoformat(),
                    self._now(),
                    session_id,
                    customer_id,
                ),
            )
            if cursor.rowcount != 1:
                raise SessionOwnershipError("Session is unavailable")
            stored = self.connection.execute(
                "SELECT * FROM move_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        pending = self._pending_from_row(stored)
        if pending is None:
            raise RuntimeError("Pending move could not be persisted")
        return pending

    def get_pending(
        self,
        session_id: str,
        customer_id: str,
    ) -> PendingMove | None:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT * FROM move_sessions
                WHERE session_id = ? AND customer_id = ?
                  AND pending_account_id IS NOT NULL
                """,
                (session_id, customer_id),
            ).fetchone()
        return self._pending_from_row(row)

    def claim_pending(
        self,
        session_id: str,
        customer_id: str,
    ) -> PendingMove | None:
        """Atomically change an awaiting proposal to executing.

        Only the caller receiving a non-None value owns the execution attempt.
        """
        with self._transaction():
            cursor = self.connection.execute(
                """
                UPDATE move_sessions
                SET pending_state = 'executing', updated_at = ?
                WHERE session_id = ? AND customer_id = ?
                  AND pending_state = 'awaiting'
                  AND pending_account_id IS NOT NULL
                  AND pending_stop_date IS NOT NULL
                """,
                (self._now(), session_id, customer_id),
            )
            if cursor.rowcount != 1:
                return None
            row = self.connection.execute(
                "SELECT * FROM move_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._pending_from_row(row)

    def mark_completed(self, session_id: str, revision: int) -> None:
        with self._lock:
            self.connection.execute(
                """
                UPDATE move_sessions
                SET pending_state = 'completed', updated_at = ?
                WHERE session_id = ? AND pending_revision = ?
                  AND pending_state IN ('awaiting', 'executing', 'completed')
                """,
                (self._now(), session_id, revision),
            )

    def release_pending(self, session_id: str, revision: int) -> None:
        with self._lock:
            self.connection.execute(
                """
                UPDATE move_sessions
                SET pending_state = 'awaiting', updated_at = ?
                WHERE session_id = ? AND pending_revision = ?
                  AND pending_state = 'executing'
                """,
                (self._now(), session_id, revision),
            )

    def cancel_pending(self, session_id: str, customer_id: str) -> bool:
        with self._lock:
            cursor = self.connection.execute(
                """
                UPDATE move_sessions
                SET pending_state = 'cancelled', updated_at = ?
                WHERE session_id = ? AND customer_id = ?
                  AND pending_state = 'awaiting'
                """,
                (self._now(), session_id, customer_id),
            )
        return cursor.rowcount == 1

    def claim_operation(self, operation_key: str) -> bool:
        """Reserve a global account/date operation before crossing the tool boundary."""
        with self._transaction():
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO execution_claims(
                    operation_key, status, updated_at
                ) VALUES (?, 'executing', ?)
                """,
                (operation_key, self._now()),
            )
            return cursor.rowcount == 1

    def complete_operation(self, operation_key: str) -> None:
        with self._lock:
            self.connection.execute(
                """
                UPDATE execution_claims
                SET status = 'completed', updated_at = ?
                WHERE operation_key = ?
                """,
                (self._now(), operation_key),
            )

    def release_operation(self, operation_key: str) -> None:
        with self._lock:
            self.connection.execute(
                """
                DELETE FROM execution_claims
                WHERE operation_key = ? AND status = 'executing'
                """,
                (operation_key,),
            )

    def get_order_id(self, operation_key: str) -> int | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT order_id FROM service_orders WHERE operation_key = ?",
                (operation_key,),
            ).fetchone()
        return None if row is None else int(row["order_id"])

    def record_trace(
        self,
        session_id: str,
        event_type: str,
        details: dict[str, object],
    ) -> None:
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO trace_events(
                    session_id, event_type, details, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    event_type,
                    json.dumps(details, sort_keys=True),
                    self._now(),
                ),
            )

    def count_orders(self) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COUNT(*) FROM service_orders"
            ).fetchone()
        return int(row[0])

    def count_tool_calls(self) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COUNT(*) FROM tool_calls"
            ).fetchone()
        return int(row[0])

    def count_traces(self, session_id: str) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COUNT(*) FROM trace_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row[0])
