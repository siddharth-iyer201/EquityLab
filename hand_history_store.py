"""SQLite persistence for Hand History analyses and saved ranges."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "hand_history.db"
STORE_VERSION = 5

_CREATE_HAND_HISTORY_SQL = """
CREATE TABLE IF NOT EXISTS hand_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    hero_hand TEXT NOT NULL,
    board TEXT NOT NULL,
    opponent_range TEXT NOT NULL,
    equity TEXT NOT NULL,
    win TEXT NOT NULL,
    tie TEXT NOT NULL,
    loss TEXT NOT NULL,
    call_ev TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    calculation_mode TEXT NOT NULL,
    opponent_label TEXT NOT NULL DEFAULT '',
    custom_hands TEXT NOT NULL DEFAULT '[]',
    pot_size REAL NOT NULL DEFAULT 100,
    call_amount REAL NOT NULL DEFAULT 25,
    simulations INTEGER NOT NULL DEFAULT 25000
)
"""

_CREATE_SAVED_RANGES_SQL = """
CREATE TABLE IF NOT EXISTS saved_ranges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    hand_classes TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_HAND_HISTORY_COLUMN_MIGRATIONS = (
    ("opponent_label", "TEXT NOT NULL DEFAULT ''"),
    ("custom_hands", "TEXT NOT NULL DEFAULT '[]'"),
    ("pot_size", "REAL NOT NULL DEFAULT 100"),
    ("call_amount", "REAL NOT NULL DEFAULT 25"),
    ("simulations", "INTEGER NOT NULL DEFAULT 25000"),
)


class DuplicateRangeNameError(ValueError):
    """Raised when saving a range whose name already exists."""


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_hand_history_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in connection.execute("PRAGMA table_info(hand_history)")
    }
    for column_name, column_type in _HAND_HISTORY_COLUMN_MIGRATIONS:
        if column_name not in existing:
            connection.execute(
                f"ALTER TABLE hand_history ADD COLUMN {column_name} {column_type}"
            )


def initialize_hand_history_db() -> None:
    """Ensure the shared app database and tables exist."""
    with _connect() as connection:
        connection.execute(_CREATE_HAND_HISTORY_SQL)
        connection.execute(_CREATE_SAVED_RANGES_SQL)
        _ensure_hand_history_columns(connection)
        connection.commit()


def normalize_hand_weights(payload) -> dict[str, int]:
    """
    Normalize persisted hand-class payloads to {hand_class: weight_percent}.

    Accepts:
    - legacy list[str] → all weights 100
    - dict[str, number] → clamped 1–100 ints (0/negative dropped)
    - list[{hand, weight}] → same clamping
    """
    if payload is None:
        return {}

    weights: dict[str, int] = {}
    if isinstance(payload, dict):
        items = payload.items()
        for hand, raw_weight in items:
            hand_key = str(hand).strip()
            if not hand_key:
                continue
            try:
                weight = int(round(float(raw_weight)))
            except (TypeError, ValueError):
                weight = 100
            if weight > 0:
                weights[hand_key] = min(100, weight)
        return weights

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                hand_key = str(item.get("hand", "")).strip()
                if not hand_key:
                    continue
                try:
                    weight = int(round(float(item.get("weight", 100))))
                except (TypeError, ValueError):
                    weight = 100
                if weight > 0:
                    weights[hand_key] = min(100, weight)
            else:
                hand_key = str(item).strip()
                if hand_key:
                    weights[hand_key] = 100
        return weights

    return {}


def serialize_hand_weights(hand_weights: dict[str, int]) -> str:
    normalized = normalize_hand_weights(hand_weights)
    ordered = {hand: normalized[hand] for hand in sorted(normalized)}
    return json.dumps(ordered)


def insert_hand_history_entry(entry: dict) -> None:
    initialize_hand_history_db()
    custom_hands = entry.get("custom_hands", {})
    if isinstance(custom_hands, str):
        custom_hands_json = custom_hands
    else:
        custom_hands_json = serialize_hand_weights(
            custom_hands if isinstance(custom_hands, dict) else {hand: 100 for hand in list(custom_hands)}
        )

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO hand_history (
                timestamp,
                hero_hand,
                board,
                opponent_range,
                equity,
                win,
                tie,
                loss,
                call_ev,
                recommendation,
                calculation_mode,
                opponent_label,
                custom_hands,
                pot_size,
                call_amount,
                simulations
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["timestamp"],
                entry["hero_hand"],
                entry["board"],
                entry["opponent_range"],
                entry["equity"],
                entry["win"],
                entry["tie"],
                entry["loss"],
                entry["call_ev"],
                entry["recommendation"],
                entry["calculation_mode"],
                entry.get("opponent_label", ""),
                custom_hands_json,
                float(entry.get("pot_size", 100)),
                float(entry.get("call_amount", 25)),
                int(entry.get("simulations", 25000)),
            ),
        )
        connection.commit()


def _parse_custom_hands(raw: str | None) -> dict[str, int]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return normalize_hand_weights(payload)


def _row_to_hand_history_entry(row: sqlite3.Row) -> dict:
    keys = set(row.keys())
    weights = _parse_custom_hands(row["custom_hands"] if "custom_hands" in keys else "{}")
    return {
        "id": int(row["id"]),
        "timestamp": row["timestamp"],
        "hero_hand": row["hero_hand"],
        "board": row["board"],
        "opponent_range": row["opponent_range"],
        "equity_pct": row["equity"],
        "win_pct": row["win"],
        "tie_pct": row["tie"],
        "loss_pct": row["loss"],
        "ev_of_call": row["call_ev"],
        "recommendation": row["recommendation"],
        "calculation_mode": row["calculation_mode"],
        "opponent_label": row["opponent_label"] if "opponent_label" in keys else "",
        "custom_hands": list(weights.keys()),
        "custom_hand_weights": weights,
        "pot_size": float(row["pot_size"]) if "pot_size" in keys and row["pot_size"] is not None else 100.0,
        "call_amount": float(row["call_amount"]) if "call_amount" in keys and row["call_amount"] is not None else 25.0,
        "simulations": int(row["simulations"]) if "simulations" in keys and row["simulations"] is not None else 25000,
    }


def load_hand_history_entries() -> list[dict]:
    """Return saved analyses newest-first, shaped for the existing card renderer."""
    initialize_hand_history_db()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM hand_history
            ORDER BY id DESC
            """
        ).fetchall()
    return [_row_to_hand_history_entry(row) for row in rows]


def get_hand_history_entry(entry_id: int) -> dict | None:
    initialize_hand_history_db()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM hand_history WHERE id = ?",
            (int(entry_id),),
        ).fetchone()
    if row is None:
        return None
    return _row_to_hand_history_entry(row)


def _row_to_saved_range(row: sqlite3.Row) -> dict:
    try:
        payload = json.loads(row["hand_classes"])
    except json.JSONDecodeError:
        payload = []
    weights = normalize_hand_weights(payload)
    hands = list(weights.keys())
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "hands": hands,
        "weights": weights,
        "range_text": _format_weighted_range_text(weights),
        "created_at": row["created_at"],
    }


def _format_weighted_range_text(weights: dict[str, int]) -> str:
    parts: list[str] = []
    for hand in sorted(weights):
        weight = weights[hand]
        if weight >= 100:
            parts.append(hand)
        else:
            parts.append(f"{hand}:{weight}%")
    return ", ".join(parts)


def insert_saved_range(name: str, hand_classes, created_at: str) -> None:
    initialize_hand_history_db()
    payload = serialize_hand_weights(
        hand_classes if isinstance(hand_classes, dict) else {hand: 100 for hand in list(hand_classes)}
    )
    try:
        with _connect() as connection:
            connection.execute(
                """
                INSERT INTO saved_ranges (name, hand_classes, created_at)
                VALUES (?, ?, ?)
                """,
                (name, payload, created_at),
            )
            connection.commit()
    except sqlite3.IntegrityError as error:
        raise DuplicateRangeNameError(name) from error


def update_saved_range_by_id(range_id: int, name: str, hand_classes) -> None:
    """Overwrite an existing saved range by primary key."""
    initialize_hand_history_db()
    payload = serialize_hand_weights(
        hand_classes if isinstance(hand_classes, dict) else {hand: 100 for hand in list(hand_classes)}
    )
    try:
        with _connect() as connection:
            cursor = connection.execute(
                """
                UPDATE saved_ranges
                SET name = ?, hand_classes = ?
                WHERE id = ?
                """,
                (name, payload, int(range_id)),
            )
            connection.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"Saved range id {range_id} was not found.")
    except sqlite3.IntegrityError as error:
        raise DuplicateRangeNameError(name) from error


def get_saved_range_by_id(range_id: int) -> dict | None:
    initialize_hand_history_db()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, name, hand_classes, created_at
            FROM saved_ranges
            WHERE id = ?
            """,
            (int(range_id),),
        ).fetchone()
    if row is None:
        return None
    return _row_to_saved_range(row)


def load_saved_ranges() -> list[dict]:
    """Return saved ranges newest-first for the Range Builder list."""
    initialize_hand_history_db()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, name, hand_classes, created_at
            FROM saved_ranges
            ORDER BY id DESC
            """
        ).fetchall()
    return [_row_to_saved_range(row) for row in rows]


def delete_saved_range_by_id(range_id: int) -> None:
    """Delete exactly one saved range by primary key."""
    initialize_hand_history_db()
    with _connect() as connection:
        connection.execute("DELETE FROM saved_ranges WHERE id = ?", (int(range_id),))
        connection.commit()
