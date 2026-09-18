"""Tests for SQLite-backed hand history persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hand_history_store as store


class HandHistoryDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "history.db"
        self.db_patch = patch.object(store, "DB_PATH", self.db_path)
        self.db_patch.start()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _insert_entry(self) -> None:
        store.insert_hand_history_entry(
            {
                "timestamp": "2026-09-17 21:00:00",
                "hero_hand": "As Ks",
                "board": "",
                "opponent_range": "Random",
                "equity": "67.0%",
                "win": "66.0%",
                "tie": "2.0%",
                "loss": "32.0%",
                "call_ev": "58.75",
                "recommendation": "Call",
                "calculation_mode": "Monte Carlo",
            }
        )

    def test_delete_existing_history_entry(self) -> None:
        self._insert_entry()
        entry_id = store.load_hand_history_entries()[0]["id"]

        self.assertTrue(store.delete_hand_history_entry_by_id(entry_id))
        self.assertEqual(store.load_hand_history_entries(), [])

    def test_delete_missing_history_entry_is_safe(self) -> None:
        self.assertFalse(store.delete_hand_history_entry_by_id(999))
