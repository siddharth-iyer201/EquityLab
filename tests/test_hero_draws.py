"""Unit tests for analyze_hero_draws (known-card draw detection)."""

from __future__ import annotations

import unittest

from poker_engine import analyze_hero_draws, analyze_hero_situation, parse_cards


class HeroDrawAnalysisTests(unittest.TestCase):
    def test_flush_draw(self) -> None:
        draws = analyze_hero_draws(parse_cards("Ah Kh"), parse_cards("2h 7h 9c"))
        self.assertIn("Nut Flush Draw", draws)
        self.assertNotIn("Flush Draw", draws)

    def test_non_nut_flush_draw(self) -> None:
        draws = analyze_hero_draws(parse_cards("Kh Qh"), parse_cards("2h 7h 9c"))
        self.assertIn("Flush Draw", draws)
        self.assertNotIn("Nut Flush Draw", draws)

    def test_nut_flush_draw_when_ace_on_board(self) -> None:
        draws = analyze_hero_draws(parse_cards("Kh Qd"), parse_cards("Ah 2h 7h"))
        self.assertIn("Nut Flush Draw", draws)
        self.assertNotIn("Flush Draw", draws)

    def test_made_flush_suppresses_flush_draw(self) -> None:
        draws = analyze_hero_draws(parse_cards("Ah Kh"), parse_cards("2h 7h 9h 3c"))
        self.assertNotIn("Flush Draw", draws)
        self.assertNotIn("Nut Flush Draw", draws)
        situation = analyze_hero_situation(parse_cards("Ah Kh"), parse_cards("2h 7h 9h 3c"))
        self.assertEqual(situation.made_hand_label, "Flush")

    def test_open_ended_straight_draw(self) -> None:
        draws = analyze_hero_draws(parse_cards("9h 8d"), parse_cards("7c 6s 2h"))
        self.assertIn("Open-Ended Straight Draw", draws)
        self.assertNotIn("Gutshot Straight Draw", draws)
        self.assertNotIn("Double Gutshot Straight Draw", draws)

    def test_gutshot_straight_draw(self) -> None:
        draws = analyze_hero_draws(parse_cards("9h 8d"), parse_cards("7c 5s 2h"))
        self.assertIn("Gutshot Straight Draw", draws)
        self.assertNotIn("Open-Ended Straight Draw", draws)

    def test_double_gutshot_straight_draw(self) -> None:
        draws = analyze_hero_draws(parse_cards("9h 7d"), parse_cards("5c 8s Jh"))
        self.assertIn("Double Gutshot Straight Draw", draws)
        self.assertNotIn("Open-Ended Straight Draw", draws)

    def test_no_draws_on_river(self) -> None:
        draws = analyze_hero_draws(parse_cards("Ah Kh"), parse_cards("2h 7h 9c 3d 4s"))
        self.assertEqual(draws, ())

    def test_no_significant_draws_preflop(self) -> None:
        draws = analyze_hero_draws(parse_cards("Ah Kh"), [])
        self.assertEqual(draws, ())

    def test_board_flush_without_hero_suit_is_not_hero_draw(self) -> None:
        draws = analyze_hero_draws(parse_cards("As Kd"), parse_cards("2h 7h 9h 3h"))
        self.assertNotIn("Flush Draw", draws)

    def test_made_straight_suppresses_straight_draws(self) -> None:
        draws = analyze_hero_draws(parse_cards("9h 8d"), parse_cards("7c 6s 5h"))
        self.assertNotIn("Open-Ended Straight Draw", draws)
        self.assertNotIn("Gutshot Straight Draw", draws)
        self.assertNotIn("Double Gutshot Straight Draw", draws)

    def test_situation_reports_overcards_and_backdoor_flush(self) -> None:
        situation = analyze_hero_situation(parse_cards("Ah Kh"), parse_cards("2c 7d 9s"))
        self.assertEqual(situation.overcard_count, 2)
        self.assertIn("Backdoor Flush Draw", situation.draws)
        self.assertIsNone(situation.outs)

    def test_situation_counts_flush_outs_without_double_counting(self) -> None:
        situation = analyze_hero_situation(parse_cards("Ah Kh"), parse_cards("2h 7h 9c"))
        self.assertIn("Nut Flush Draw", situation.draws)
        self.assertIsNotNone(situation.outs)
        assert situation.outs is not None
        self.assertEqual(situation.outs, 9)

    def test_combo_draw_outs_are_unique(self) -> None:
        # Flush + OESD: overlapping completing cards must not be double-counted.
        situation = analyze_hero_situation(parse_cards("9h 8h"), parse_cards("7h 6h 2d"))
        self.assertIn("Flush Draw", situation.draws)
        self.assertIn("Open-Ended Straight Draw", situation.draws)
        assert situation.outs is not None
        # 9 flush outs + up to 6 straight outs, but overlap removes duplicates.
        self.assertLessEqual(situation.outs, 15)
        self.assertGreaterEqual(situation.outs, 9)

    def test_backdoor_straight_on_flop(self) -> None:
        situation = analyze_hero_situation(parse_cards("9h 8d"), parse_cards("2c 5s Kh"))
        self.assertIn("Backdoor Straight Draw", situation.draws)

    def test_backdoor_suppressed_when_live_draw_exists(self) -> None:
        situation = analyze_hero_situation(parse_cards("Ah Kh"), parse_cards("2h 7h 9c"))
        self.assertNotIn("Backdoor Flush Draw", situation.draws)


if __name__ == "__main__":
    unittest.main()
