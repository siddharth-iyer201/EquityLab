"""Tests for equity heatmap computation and caching."""

from __future__ import annotations

import unittest

from equity_heatmap import (
    build_heatmap_cache_key,
    clear_equity_heatmap_cache,
    compute_equity_heatmap,
    equity_heatmap_cache_size,
    get_or_compute_equity_heatmap,
    legal_hero_combos,
    pick_display_combo,
    starting_hand_classes,
)
from poker_engine import parse_cards, parse_opponent_range


class EquityHeatmapTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_equity_heatmap_cache()

    def tearDown(self) -> None:
        clear_equity_heatmap_cache()

    def test_starting_hand_classes_cover_full_grid(self) -> None:
        hands = starting_hand_classes()
        self.assertEqual(len(hands), 169)
        self.assertEqual(hands[0], "AA")
        self.assertIn("AKs", hands)
        self.assertIn("AKo", hands)
        self.assertEqual(hands[-1], "22")

    def test_board_blocks_illegal_hero_combos(self) -> None:
        board = parse_cards("As Kh")
        legal = legal_hero_combos("AKs", board)
        self.assertTrue(legal)
        for hand in legal:
            keys = {hand[0].key(), hand[1].key()}
            self.assertNotIn("As", keys)
            self.assertNotIn("Kh", keys)
        self.assertLess(len(legal), 4)

    def test_pick_display_combo_respects_board(self) -> None:
        board = parse_cards("As Ah Ad")
        self.assertIsNone(pick_display_combo("AA", board))
        combo = pick_display_combo("KK", board)
        self.assertIsNotNone(combo)
        assert combo is not None
        self.assertEqual({combo[0].rank, combo[1].rank}, {"K"})

    def test_identical_inputs_return_cached_object(self) -> None:
        board = parse_cards("Ah 7d 2c 9s 3h")
        opponent = parse_opponent_range("QQ+, AKs")
        first = get_or_compute_equity_heatmap(
            board,
            opponent_range=opponent,
            simulations=500,
        )
        self.assertEqual(equity_heatmap_cache_size(), 1)

        second = get_or_compute_equity_heatmap(
            board,
            opponent_range=opponent,
            simulations=500,
        )
        self.assertIs(first, second)
        self.assertEqual(equity_heatmap_cache_size(), 1)

        self.assertIsNotNone(first["AA"].equity)
        self.assertIsNotNone(first["72o"].equity)
        assert first["AA"].equity is not None
        assert first["72o"].equity is not None
        self.assertGreater(first["AA"].equity, first["72o"].equity)

    def test_changing_board_invalidates_cache(self) -> None:
        board_a = parse_cards("Ah 7d 2c 9s 3h")
        board_b = parse_cards("Ah 7d 2c 9s 4d")
        opponent = parse_opponent_range("TT+")
        key_a = build_heatmap_cache_key(board_a, opponent, None, 1_000)
        key_b = build_heatmap_cache_key(board_b, opponent, None, 1_000)
        self.assertNotEqual(key_a, key_b)

        get_or_compute_equity_heatmap(board_a, opponent_range=opponent, simulations=400)
        self.assertEqual(equity_heatmap_cache_size(), 1)
        get_or_compute_equity_heatmap(board_b, opponent_range=opponent, simulations=400)
        self.assertEqual(equity_heatmap_cache_size(), 2)
        # Second request with board_a hits the original cache entry.
        again = get_or_compute_equity_heatmap(board_a, opponent_range=opponent, simulations=400)
        self.assertEqual(equity_heatmap_cache_size(), 2)
        self.assertIn("AA", again)

    def test_changing_range_invalidates_cache(self) -> None:
        board = parse_cards("Kh 9d 2c 5s 8h")
        range_a = parse_opponent_range("JJ+")
        range_b = parse_opponent_range("22+")
        key_a = build_heatmap_cache_key(board, range_a, None, 800)
        key_b = build_heatmap_cache_key(board, range_b, None, 800)
        self.assertNotEqual(key_a, key_b)

        get_or_compute_equity_heatmap(board, opponent_range=range_a, simulations=300)
        get_or_compute_equity_heatmap(board, opponent_range=range_b, simulations=300)
        self.assertEqual(equity_heatmap_cache_size(), 2)

    def test_changing_simulations_invalidates_cache_key(self) -> None:
        board = parse_cards("Qs Jh 2d")
        opponent = parse_opponent_range("AK")
        key_a = build_heatmap_cache_key(board, opponent, None, 500)
        key_b = build_heatmap_cache_key(board, opponent, None, 2_000)
        self.assertNotEqual(key_a, key_b)

    def test_simulation_budget_shares_cache_above_cap(self) -> None:
        board = parse_cards("Ah 7d 2c 9s 3h")
        opponent = parse_opponent_range("JJ+")
        first = get_or_compute_equity_heatmap(board, opponent_range=opponent, simulations=25_000)
        second = get_or_compute_equity_heatmap(board, opponent_range=opponent, simulations=50_000)
        self.assertIs(first, second)
        self.assertEqual(equity_heatmap_cache_size(), 1)
        third = get_or_compute_equity_heatmap(board, opponent_range=opponent, simulations=1_000)
        self.assertIsNot(first, third)
        self.assertEqual(equity_heatmap_cache_size(), 2)

    def test_weighted_range_changes_cache_key(self) -> None:
        board = parse_cards("8h 8d 3c")
        hands = parse_opponent_range("AA, KK")
        weights_a = [1.0] * len(hands)
        weights_b = [1.0 if hand[0].rank == "A" else 0.25 for hand in hands]
        key_a = build_heatmap_cache_key(board, hands, weights_a, 700)
        key_b = build_heatmap_cache_key(board, hands, weights_b, 700)
        self.assertNotEqual(key_a, key_b)

    def test_compute_subset_matches_engine_ordering(self) -> None:
        board = parse_cards("Ad Kd 9c 5s 8h")
        opponent = parse_opponent_range("QQ")
        cells = compute_equity_heatmap(
            board,
            opponent_range=opponent,
            simulations=200,
            hand_classes=["AA", "72o", "AKs"],
        )
        self.assertEqual(set(cells), {"AA", "72o", "AKs"})
        self.assertIsNotNone(cells["AA"].equity)
        self.assertIsNotNone(cells["72o"].equity)
        assert cells["AA"].equity is not None
        assert cells["72o"].equity is not None
        self.assertGreater(cells["AA"].equity, cells["72o"].equity)


if __name__ == "__main__":
    unittest.main()
