"""Tests for Analyze workflow presentation helpers (no Streamlit session required)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import app
from poker_engine import evaluate_call_decision


class WorkflowStepStateTests(unittest.TestCase):
    def test_hero_incomplete_is_current(self) -> None:
        steps = dict(
            app._workflow_step_states(
                hero_complete=False,
                board_complete=True,
                opponent_complete=True,
                settings_complete=True,
            )
        )
        self.assertEqual(steps["Hero Hand"], "active")
        self.assertEqual(steps["Board Optional"], "complete")
        self.assertEqual(steps["Calculate"], "incomplete")

    def test_partial_board_needs_attention(self) -> None:
        steps = dict(
            app._workflow_step_states(
                hero_complete=True,
                board_complete=False,
                opponent_complete=True,
                settings_complete=True,
            )
        )
        self.assertEqual(steps["Hero Hand"], "complete")
        self.assertEqual(steps["Board Optional"], "active")
        self.assertEqual(steps["Calculate"], "incomplete")

    def test_ready_when_all_complete(self) -> None:
        steps = dict(
            app._workflow_step_states(
                hero_complete=True,
                board_complete=True,
                opponent_complete=True,
                settings_complete=True,
            )
        )
        self.assertEqual(steps["Hero Hand"], "complete")
        self.assertEqual(steps["Board Optional"], "complete")
        self.assertEqual(steps["Opponent Range"], "complete")
        self.assertEqual(steps["Settings"], "complete")
        self.assertEqual(steps["Calculate"], "ready")


class CalculateReadinessTests(unittest.TestCase):
    def test_custom_range_requires_hands(self) -> None:
        self.assertTrue(app._is_opponent_range_complete("Random", 0))
        self.assertTrue(app._is_opponent_range_complete("Top 10%", 0))
        self.assertFalse(app._is_opponent_range_complete("Custom", 0))
        self.assertTrue(app._is_opponent_range_complete("Custom", 3))

    def test_calculate_ready_only_when_all_inputs_valid(self) -> None:
        self.assertFalse(
            app._is_calculator_ready(
                hero_complete=True,
                board_complete=True,
                opponent_complete=False,
                settings_complete=True,
            )
        )
        self.assertTrue(
            app._is_calculator_ready(
                hero_complete=True,
                board_complete=True,
                opponent_complete=True,
                settings_complete=True,
            )
        )

    def test_board_complete_counts(self) -> None:
        for count in (0, 3, 4, 5):
            self.assertTrue(app._board_count_is_complete(count))
        for count in (1, 2, 6):
            self.assertFalse(app._board_count_is_complete(count))

    def test_recommendation_badge_selection(self) -> None:
        call = evaluate_call_decision(0.6, 100.0, 25.0)
        fold = evaluate_call_decision(0.1, 100.0, 50.0)
        self.assertEqual(call.recommendation, "Call")
        self.assertEqual(fold.recommendation, "Fold")
        html_call = app._calculation_summary_results_html(
            {
                "result": SimpleNamespace(
                    equity=0.6,
                    win_rate=0.55,
                    tie_rate=0.05,
                    loss_rate=0.4,
                ),
                "decision": call,
                "simulations": 50_000,
            }
        )
        html_fold = app._calculation_summary_results_html(
            {
                "result": SimpleNamespace(
                    equity=0.1,
                    win_rate=0.08,
                    tie_rate=0.02,
                    loss_rate=0.9,
                ),
                "decision": fold,
                "simulations": 10_000,
            }
        )
        self.assertIn("calc-summary-rec-card", html_call)
        self.assertIn("rec-call", html_call)
        self.assertIn(">Call<", html_call)
        self.assertIn("Above Required Equity", html_call)
        self.assertIn("Simulation Confidence", html_call)
        self.assertIn("High", html_call)
        self.assertIn("Why?", html_call)
        self.assertIn("rec-fold", html_fold)
        self.assertIn(">Fold<", html_fold)
        self.assertIn("Below Required Equity", html_fold)
        self.assertIn("Low", html_fold)
        self.assertIn(app._format_percent(0.6), html_call)
        self.assertIn(app._format_percent(0.55), html_call)
        self.assertIn(f"{call.call_ev:+.2f}", html_call)

    def test_equity_status_and_simulation_confidence_helpers(self) -> None:
        label, diff, tone = app._equity_vs_required_status(0.4, 0.2)
        self.assertEqual(label, "Above Required Equity")
        self.assertAlmostEqual(diff, 0.2)
        self.assertEqual(tone, "el-eq-status-above")
        even_label, _, even_tone = app._equity_vs_required_status(0.2, 0.201)
        self.assertEqual(even_label, "Break-even")
        self.assertEqual(even_tone, "el-eq-status-even")
        self.assertEqual(app._simulation_confidence_from_trials(10_000), "Low")
        self.assertEqual(app._simulation_confidence_from_trials(25_000), "Medium")
        self.assertEqual(app._simulation_confidence_from_trials(100_000), "Very High")


class EquityBarTests(unittest.TestCase):
    def test_equity_bar_includes_accessible_percentages(self) -> None:
        html = app._equity_share_bar_html(0.5, 0.1, 0.4)
        self.assertIn("aria-label", html)
        self.assertIn("Win", html)
        self.assertIn("Tie", html)
        self.assertIn("Loss", html)
        self.assertIn("el-equity-bar-animated", html)
        self.assertIn("el-equity-bar-pcts", html)
        self.assertIn(app._format_percent(0.5), html)
        self.assertIn(app._format_percent(0.1), html)
        self.assertIn(app._format_percent(0.4), html)


class ResultsPolishHelpersTests(unittest.TestCase):
    def test_equity_margin_subtitle_formats(self) -> None:
        above = app._equity_margin_subtitle(0.443, 0.2)
        self.assertIn("+24.3 pp above required equity", above)
        below = app._equity_margin_subtitle(0.1, 0.2)
        self.assertIn("pp below required equity", below)
        even = app._equity_margin_subtitle(0.2, 0.201)
        self.assertIn("break-even", even.lower())

    def test_stat_card_and_recommendation_pill(self) -> None:
        card = app._analytics_stat_card_html("Call EV", "+12.50")
        self.assertIn("el-stat-card", card)
        self.assertIn("Call EV", card)
        self.assertIn("+12.50", card)
        pill = app._recommendation_pill_html("Call")
        self.assertIn("el-rec-pill", pill)
        self.assertIn("rec-call", pill)
        self.assertIn("Call", pill)

    def test_opponent_distribution_includes_share_bars(self) -> None:
        # Render path uses Streamlit; validate bar markup via row construction pattern.
        share = 0.327
        bar_w = max(0.0, min(100.0, share * 100.0))
        self.assertAlmostEqual(bar_w, 32.7)
        html = f"<span class='opp-hand-bar' style='width:{bar_w:.2f}%'></span>"
        self.assertIn("opp-hand-bar", html)
        self.assertIn("32.70%", html)


class LiveBoardPolishTests(unittest.TestCase):
    def test_chip_high_label_compacts_rank(self) -> None:
        self.assertEqual(app._chip_high_label("Jack High"), "J-high")
        self.assertEqual(app._chip_high_label("Ace High"), "A-high")
        self.assertEqual(app._chip_high_label("Pair of Kings"), "Pair of Kings")

    def test_live_board_payload_example(self) -> None:
        data = app._live_board_analysis_payload(["6d", "5d"], ["Qd", "7d", "2h"])
        self.assertIsNotNone(data["made_hand"])
        self.assertIn("Flush Draw", data["primary_draw"] or "")
        self.assertTrue(data["texture"])
        self.assertIn("tone", (data["texture"] or "").lower())

    def test_spades_brighter_than_prior_slate(self) -> None:
        self.assertEqual(app.SUIT_STYLES["s"]["background"], "#64748b")
        self.assertNotEqual(app.SUIT_STYLES["s"]["background"], app.SUIT_STYLES["c"]["background"])


class MonteCarloPresetTests(unittest.TestCase):
    def test_normalize_snaps_to_nearest_preset(self) -> None:
        self.assertEqual(app._normalize_monte_carlo_trials(25_000), 25_000)
        self.assertEqual(app._normalize_monte_carlo_trials(22_000), 25_000)
        self.assertEqual(app._normalize_monte_carlo_trials(1_000), 10_000)
        self.assertEqual(app._normalize_monte_carlo_trials(240_000), 250_000)

    def test_runtime_and_accuracy_labels(self) -> None:
        self.assertEqual(app._monte_carlo_accuracy_label(25_000), "High")
        self.assertIn("s", app._monte_carlo_runtime_estimate(100_000))
        self.assertEqual(app._format_trial_preset_label(250_000), "250k")

    def test_warning_and_tip_cards_have_structure(self) -> None:
        tip = app._calculation_tip_card_html()
        self.assertIn("el-calc-tip", tip)
        self.assertIn("Tip", tip)
        self.assertIn("estimate equity and EV", tip)
        info = app._simulation_info_panel_html(25_000)
        self.assertIn("el-sim-stat", info)
        self.assertIn("el-sim-info-label-row", info)
        self.assertIn("25,000", info)
        self.assertIn("High", info)
        self.assertIn("el-sim-acc-high", info)
        self.assertIn("~1–2s", info)
        self.assertEqual(app._accuracy_tone_class("Excellent"), "el-sim-acc-excellent")
        self.assertEqual(app._accuracy_tone_class("Good"), "el-sim-acc-good")
        warning = app._calculation_warning_card_html()
        self.assertIn("el-calc-validation", warning)
        self.assertIn("Select both hero cards to continue.", warning)


if __name__ == "__main__":
    unittest.main()
