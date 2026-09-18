import random
import unittest

from poker_engine import (
    HAND_CATEGORIES,
    calculate_equity,
    compare_hands,
    describe_hand,
    evaluate_best_hand,
    evaluate_call_decision,
    parse_cards,
    parse_opponent_range,
)


class ParseCardsTests(unittest.TestCase):
    def test_parses_spaced_and_compact_notation(self) -> None:
        self.assertEqual([card.display() for card in parse_cards("Ah Ks")], ["AH", "KS"])
        self.assertEqual([card.display() for card in parse_cards("AhKs")], ["AH", "KS"])
        self.assertEqual([card.display() for card in parse_cards("10h Jd")], ["TH", "JD"])

    def test_rejects_duplicate_cards(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate card"):
            parse_cards("Ah Ah")

    def test_validates_expected_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected 2 cards"):
            parse_cards("Ah", expected_count=2)


class EvaluatorTests(unittest.TestCase):
    def test_recognizes_royal_flush_as_straight_flush(self) -> None:
        score = evaluate_best_hand(parse_cards("As Ks Qs Js Ts 2d 3c"))

        self.assertEqual(score.label, "Straight flush")
        self.assertEqual(score.values, (14,))

    def test_supports_ace_low_straights(self) -> None:
        score = evaluate_best_hand(parse_cards("Ah 2d 3s 4c 5h Kd Qs"))

        self.assertEqual(score.label, "Straight")
        self.assertEqual(score.values, (5,))

    def test_compares_full_houses_by_trips_first(self) -> None:
        aces_full = parse_cards("Ah Ad As Kc Kd 2c 3d")
        kings_full = parse_cards("Kh Kd Ks Ac Ad 2c 3d")

        self.assertGreater(compare_hands(aces_full, kings_full), 0)

    def test_describes_made_hands_explicitly(self) -> None:
        pair_of_nines = evaluate_best_hand(parse_cards("9h 9d Ah Kc 2s"))
        self.assertEqual(describe_hand(pair_of_nines), "Pair of 9s")

        two_pair = evaluate_best_hand(parse_cards("9h 9d 5c 5h Ah"))
        self.assertEqual(describe_hand(two_pair), "Two pair, 9s and 5s")

        trips = evaluate_best_hand(parse_cards("Qh Qd Qc 2s 7h"))
        self.assertEqual(describe_hand(trips), "Three of a kind, Queens")

        full_house = evaluate_best_hand(parse_cards("Kh Kd Ks 9c 9h"))
        self.assertEqual(describe_hand(full_house), "Full house, Kings full of 9s")


class EquityTests(unittest.TestCase):
    def test_uses_exact_enumeration_on_complete_board(self) -> None:
        result = calculate_equity(parse_cards("As Ks"), parse_cards("Qs Js Ts 2d 3c"))

        self.assertEqual(result.mode, "exact")
        self.assertEqual(result.equity, 1)
        self.assertEqual(result.losses, 0)
        self.assertEqual(sum(result.hand_distribution.values()), result.total)
        self.assertEqual(result.hand_distribution["Straight flush"], result.total)
        self.assertEqual(sum(result.opponent_hand_distribution.values()), result.total)
        self.assertEqual(set(result.opponent_hand_distribution), set(HAND_CATEGORIES))
        self.assertEqual(result.boards_evaluated, result.total)
        self.assertGreater(result.opponent_combinations_evaluated, 0)
        self.assertGreaterEqual(result.runtime_ms, 0)

    def test_uses_monte_carlo_when_exact_search_is_too_large(self) -> None:
        seeded_random = random.Random(7)
        result = calculate_equity(
            parse_cards("Qs Qd"),
            [],
            simulations=500,
            exact_max_matchups=0,
            rng=seeded_random.random,
        )

        self.assertEqual(result.mode, "monte-carlo")
        self.assertEqual(result.total, 500)
        self.assertGreater(result.equity, 0.6)
        self.assertLess(result.equity, 0.9)
        self.assertEqual(sum(result.hand_distribution.values()), result.total)
        self.assertEqual(sum(result.opponent_hand_distribution.values()), result.total)
        self.assertEqual(result.boards_evaluated, 500)
        self.assertEqual(result.opponent_combinations_evaluated, 500)

    def test_opponent_hand_distribution_tracks_made_categories(self) -> None:
        # Fixed river: hero has the nut straight flush. Every opponent combo still
        # gets a final made-hand category counted without changing equity math.
        result = calculate_equity(parse_cards("As Ks"), parse_cards("Qs Js Ts 2d 3c"))

        self.assertEqual(result.equity, 1)
        self.assertEqual(sum(result.opponent_hand_distribution.values()), result.total)
        self.assertGreater(result.opponent_hand_distribution["Straight Flush"], 0)
        strongest_first = list(reversed(HAND_CATEGORIES))
        self.assertEqual(strongest_first[0], "Straight Flush")
        self.assertEqual(strongest_first[-1], "High Card")

    def test_win_tie_loss_and_equity_identities(self) -> None:
        result = calculate_equity(
            parse_cards("Ah Ad"),
            parse_cards("Kh 7c 2s"),
            simulations=2_000,
            exact_max_matchups=0,
            rng=random.Random(11).random,
        )
        self.assertAlmostEqual(result.win_rate + result.tie_rate + result.loss_rate, 1.0, places=9)
        self.assertAlmostEqual(
            result.equity,
            result.win_rate + 0.5 * result.tie_rate,
            places=9,
        )
        hero_share = sum(result.hand_distribution.values())
        opp_share = sum(result.opponent_hand_distribution.values())
        self.assertAlmostEqual(hero_share, result.total, places=6)
        self.assertAlmostEqual(opp_share, result.total, places=6)
        if result.total:
            hero_pct = sum(result.hand_distribution.values()) / result.total
            opp_pct = sum(result.opponent_hand_distribution.values()) / result.total
            self.assertAlmostEqual(hero_pct, 1.0, places=9)
            self.assertAlmostEqual(opp_pct, 1.0, places=9)

    def test_allows_partial_boards_before_the_flop(self) -> None:
        result = calculate_equity(
            parse_cards("Ah Kh"),
            parse_cards("2c"),
            simulations=25,
            exact_max_matchups=0,
        )

        self.assertEqual(result.mode, "monte-carlo")
        self.assertEqual(result.total, 25)

    def test_calculates_against_selected_opponent_range(self) -> None:
        result = calculate_equity(
            parse_cards("As Ks"),
            parse_cards("Qs Js Ts 2d 3c"),
            opponent_range=parse_opponent_range("QQ+"),
        )

        self.assertEqual(result.mode, "exact")
        self.assertEqual(result.equity, 1)


class RangeTests(unittest.TestCase):
    def test_parses_pair_plus_ranges(self) -> None:
        opponent_range = parse_opponent_range("QQ+")

        self.assertEqual(len(opponent_range), 18)

    def test_parses_suited_and_offsuit_ranges(self) -> None:
        suited = parse_opponent_range("AKs")
        offsuit = parse_opponent_range("AKo")
        both = parse_opponent_range("AK")

        self.assertEqual(len(suited), 4)
        self.assertEqual(len(offsuit), 12)
        self.assertEqual(len(both), 16)

    def test_parses_unpaired_plus_ranges(self) -> None:
        opponent_range = parse_opponent_range("AJs+")

        self.assertEqual(len(opponent_range), 12)


class CallDecisionTests(unittest.TestCase):
    def test_calculates_required_equity_and_positive_call_ev(self) -> None:
        decision = evaluate_call_decision(equity=0.4, pot_size=100, call_amount=25)

        self.assertAlmostEqual(decision.required_equity, 0.2)
        self.assertAlmostEqual(decision.call_ev, 25)
        self.assertEqual(decision.recommendation, "Call")

    def test_recommends_fold_for_negative_ev_calls(self) -> None:
        decision = evaluate_call_decision(equity=0.1, pot_size=100, call_amount=25)

        self.assertLess(decision.call_ev, 0)
        self.assertEqual(decision.recommendation, "Fold")


if __name__ == "__main__":
    unittest.main()
