"""Unit tests for classify_completed_hand (7-card category evaluation)."""

from __future__ import annotations

import unittest

from poker_engine import HAND_CATEGORIES, classify_completed_hand, parse_cards


class ClassifyCompletedHandTests(unittest.TestCase):
    def test_requires_exactly_seven_cards(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 7 cards"):
            classify_completed_hand(parse_cards("As Kd Qh Jc Ts 9d"))

        with self.assertRaisesRegex(ValueError, "exactly 7 cards"):
            classify_completed_hand(parse_cards("As Kd Qh Jc Ts 9d 8c 7h"))

    def test_rejects_duplicate_cards(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate card"):
            classify_completed_hand(parse_cards("As Kd Qh Jc Ts 9d As"))

    def test_high_card(self) -> None:
        cards = parse_cards("Ah Kd 9c 7s 5h 3d 2c")
        self.assertEqual(classify_completed_hand(cards), "High Card")

    def test_one_pair(self) -> None:
        cards = parse_cards("Ah Ad Kc 9s 7h 5d 2c")
        self.assertEqual(classify_completed_hand(cards), "One Pair")

    def test_two_pair(self) -> None:
        cards = parse_cards("Ah Ad Kc Ks 7h 5d 2c")
        self.assertEqual(classify_completed_hand(cards), "Two Pair")

    def test_three_of_a_kind(self) -> None:
        cards = parse_cards("Qh Qd Qc 9s 7h 5d 2c")
        self.assertEqual(classify_completed_hand(cards), "Three of a Kind")

    def test_straight(self) -> None:
        cards = parse_cards("9h 8d 7c 6s 5h Kd 2c")
        self.assertEqual(classify_completed_hand(cards), "Straight")

    def test_flush(self) -> None:
        cards = parse_cards("Ah Kh 9h 7h 3h Qd 2s")
        self.assertEqual(classify_completed_hand(cards), "Flush")

    def test_full_house(self) -> None:
        cards = parse_cards("Kh Kd Ks 9c 9h 2d 3c")
        self.assertEqual(classify_completed_hand(cards), "Full House")

    def test_four_of_a_kind(self) -> None:
        cards = parse_cards("Ah Ad Ac As 9h Kd 2c")
        self.assertEqual(classify_completed_hand(cards), "Four of a Kind")

    def test_straight_flush(self) -> None:
        cards = parse_cards("9h 8h 7h 6h 5h Kd 2c")
        self.assertEqual(classify_completed_hand(cards), "Straight Flush")

    def test_covers_all_nine_categories(self) -> None:
        samples = {
            "High Card": "Ah Kd 9c 7s 5h 3d 2c",
            "One Pair": "Ah Ad Kc 9s 7h 5d 2c",
            "Two Pair": "Ah Ad Kc Ks 7h 5d 2c",
            "Three of a Kind": "Qh Qd Qc 9s 7h 5d 2c",
            "Straight": "9h 8d 7c 6s 5h Kd 2c",
            "Flush": "Ah Kh 9h 7h 3h Qd 2s",
            "Full House": "Kh Kd Ks 9c 9h 2d 3c",
            "Four of a Kind": "Ah Ad Ac As 9h Kd 2c",
            "Straight Flush": "9h 8h 7h 6h 5h Kd 2c",
        }
        self.assertEqual(set(samples), set(HAND_CATEGORIES))
        for category, notation in samples.items():
            self.assertEqual(classify_completed_hand(parse_cards(notation)), category)

    def test_ace_low_straight_a2345(self) -> None:
        cards = parse_cards("Ah 2d 3c 4s 5h Kd Qc")
        self.assertEqual(classify_completed_hand(cards), "Straight")

    def test_chooses_best_five_cards_from_seven(self) -> None:
        # Also contains a pair of twos; best five is the heart flush.
        cards = parse_cards("Ah Kh 9h 7h 3h 2d 2c")
        self.assertEqual(classify_completed_hand(cards), "Flush")

        # Also contains trips; best five is the nine-high straight.
        cards = parse_cards("9h 8d 7c 6s 5h 5d 5c")
        self.assertEqual(classify_completed_hand(cards), "Straight")

    def test_flush_that_is_not_a_straight_flush(self) -> None:
        # Five hearts, not consecutive ranks.
        cards = parse_cards("Ah Jh 8h 5h 2h Kd Qc")
        self.assertEqual(classify_completed_hand(cards), "Flush")

    def test_full_house_with_two_different_trips(self) -> None:
        # AAA + KKK (+2) → Aces full of Kings.
        cards = parse_cards("Ah Ad Ac Kh Kd Ks 2c")
        self.assertEqual(classify_completed_hand(cards), "Full House")

    def test_royal_flush_is_straight_flush(self) -> None:
        cards = parse_cards("As Ks Qs Js Ts 2d 3c")
        self.assertEqual(classify_completed_hand(cards), "Straight Flush")


if __name__ == "__main__":
    unittest.main()
