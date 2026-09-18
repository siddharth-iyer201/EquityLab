"""Unit tests for analyze_board_texture (community-card texture labels)."""

from __future__ import annotations

import unittest

from poker_engine import analyze_board_texture, parse_cards


class BoardTextureAnalysisTests(unittest.TestCase):
    def test_preflop_empty_board(self) -> None:
        texture = analyze_board_texture([])
        self.assertEqual(texture.labels, ("Preflop",))
        self.assertIn("No community cards", texture.explanation)

    def test_monotone_flop(self) -> None:
        texture = analyze_board_texture(parse_cards("Ah Kh 2h"))
        self.assertIn("Monotone flop", texture.labels)

    def test_two_tone_flop(self) -> None:
        texture = analyze_board_texture(parse_cards("Ah Kd 9h"))
        self.assertIn("Two-tone flop", texture.labels)

    def test_rainbow_flop(self) -> None:
        texture = analyze_board_texture(parse_cards("Ah Kd 9c"))
        self.assertIn("Rainbow flop", texture.labels)

    def test_paired_board(self) -> None:
        texture = analyze_board_texture(parse_cards("Kh Kd 9c"))
        self.assertIn("Paired board", texture.labels)

    def test_connected_board(self) -> None:
        # Rainbow + one close gap → Connected, not Highly coordinated.
        texture = analyze_board_texture(parse_cards("9h 8d 2c"))
        self.assertIn("Connected board", texture.labels)
        self.assertNotIn("Highly coordinated board", texture.labels)

    def test_highly_coordinated_board(self) -> None:
        texture = analyze_board_texture(parse_cards("9h 8h 7d"))
        self.assertIn("Highly coordinated board", texture.labels)
        self.assertNotIn("Connected board", texture.labels)

    def test_dry_board(self) -> None:
        texture = analyze_board_texture(parse_cards("Kh 7d 2c"))
        self.assertIn("Dry board", texture.labels)
        self.assertIn("Rainbow flop", texture.labels)

    def test_ace_high_board(self) -> None:
        texture = analyze_board_texture(parse_cards("Ah 9d 2c"))
        self.assertIn("Ace-high board", texture.labels)

    def test_broadway_heavy_board(self) -> None:
        texture = analyze_board_texture(parse_cards("Kh Qd 2c"))
        self.assertIn("Broadway-heavy board", texture.labels)

    def test_low_board(self) -> None:
        texture = analyze_board_texture(parse_cards("7h 4d 2c"))
        self.assertIn("Low board", texture.labels)
        self.assertNotIn("Dry board", texture.labels)

    def test_turn_uses_flop_for_suit_texture(self) -> None:
        # Flop rainbow; turn adds another heart — suit tag still from flop.
        texture = analyze_board_texture(parse_cards("Ah Kd 9c 2h"))
        self.assertIn("Rainbow flop", texture.labels)

    def test_rejects_duplicate_cards(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate card"):
            analyze_board_texture(parse_cards("Ah Kd Ah"))

    def test_rejects_more_than_five_cards(self) -> None:
        with self.assertRaisesRegex(ValueError, "more than 5"):
            analyze_board_texture(parse_cards("Ah Kd 9c 2h 7s 3d"))

    def test_explanation_is_one_sentence(self) -> None:
        texture = analyze_board_texture(parse_cards("Ah Kh Qh"))
        self.assertTrue(texture.explanation.endswith("."))
        self.assertEqual(texture.explanation.count("."), 1)


if __name__ == "__main__":
    unittest.main()
