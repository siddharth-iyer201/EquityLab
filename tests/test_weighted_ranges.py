"""Unit tests for weighted opponent ranges."""

from __future__ import annotations

import random
import unittest

from hand_history_store import normalize_hand_weights, serialize_hand_weights
from poker_engine import calculate_equity, expand_weighted_range, parse_cards, parse_opponent_range


class WeightedRangeTests(unittest.TestCase):
    def test_expand_weighted_range_scales_combos(self) -> None:
        hands, weights = expand_weighted_range({"AA": 1.0, "AKs": 0.5})
        self.assertEqual(len(hands), len(weights))
        self.assertEqual(len(hands), 10)  # 6 pair + 4 suited
        aa_weights = [
            weight
            for hand, weight in zip(hands, weights)
            if hand[0].rank == "A" and hand[1].rank == "A"
        ]
        aks_weights = [
            weight
            for hand, weight in zip(hands, weights)
            if {hand[0].rank, hand[1].rank} == {"A", "K"} and hand[0].suit == hand[1].suit
        ]
        self.assertEqual(aa_weights, [1.0] * 6)
        self.assertEqual(aks_weights, [0.5] * 4)

    def test_monte_carlo_samples_by_weight(self) -> None:
        # Force Monte Carlo and a tiny range so sampling bias is obvious.
        hands, weights = expand_weighted_range({"AA": 1.0, "72o": 0.01})
        seeded = random.Random(11)
        result = calculate_equity(
            parse_cards("Kh Kd"),
            [],
            simulations=4_000,
            exact_max_matchups=0,
            rng=seeded.random,
            opponent_range=hands,
            opponent_weights=weights,
        )
        self.assertEqual(result.mode, "monte-carlo")
        self.assertEqual(result.total, 4_000)
        # Against mostly AA, KK should be a clear dog.
        self.assertLess(result.equity, 0.35)

    def test_exact_weights_change_equity_vs_uniform(self) -> None:
        board = parse_cards("2c 3d 4h 5s 7c")
        hero = parse_cards("Ah Kh")
        uniform = calculate_equity(
            hero,
            board,
            opponent_range=parse_opponent_range("AA, 72o"),
        )
        weighted_hands, weighted_weights = expand_weighted_range({"AA": 1.0, "72o": 0.05})
        weighted = calculate_equity(
            hero,
            board,
            opponent_range=weighted_hands,
            opponent_weights=weighted_weights,
        )
        self.assertEqual(uniform.mode, "exact")
        self.assertEqual(weighted.mode, "exact")
        # Down-weighting 72o should make the matchup harder (more AA mass).
        self.assertLess(weighted.equity, uniform.equity)

    def test_normalize_legacy_list_defaults_to_100(self) -> None:
        self.assertEqual(normalize_hand_weights(["AA", "AKs"]), {"AA": 100, "AKs": 100})

    def test_serialize_round_trip_preserves_weights(self) -> None:
        payload = serialize_hand_weights({"AKs": 50, "AA": 100, "72o": 25})
        restored = normalize_hand_weights(__import__("json").loads(payload))
        self.assertEqual(restored, {"AA": 100, "AKs": 50, "72o": 25})


if __name__ == "__main__":
    unittest.main()
