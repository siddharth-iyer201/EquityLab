"""Unit tests for EV formulas and Decision Explanation logic."""

from __future__ import annotations

import unittest

from decision_analysis import (
    DECISION_MARGIN_MARGINAL,
    DECISION_MARGIN_STRONG,
    build_decision_explanation,
    build_decision_metrics,
    build_decision_sensitivity,
    call_ev,
    confidence_level,
    equity_margin,
    format_monte_carlo_equity_ci,
    format_percent,
    format_signed_ev,
    format_signed_margin_pp,
    monte_carlo_equity_ci_halfwidth,
    monte_carlo_equity_standard_error,
    recommendation_from_call_ev,
    required_equity,
)
from poker_engine import evaluate_call_decision


class RequiredEquityAndCallEvFormulaTests(unittest.TestCase):
    def test_required_equity_formula(self) -> None:
        # Call / (Pot + Call) = 25 / 125 = 0.20
        self.assertAlmostEqual(required_equity(100.0, 25.0), 0.20)
        self.assertAlmostEqual(required_equity(50.0, 50.0), 0.50)

    def test_required_equity_zero_when_no_call(self) -> None:
        self.assertEqual(required_equity(100.0, 0.0), 0.0)

    def test_call_ev_formula(self) -> None:
        # Equity × (Pot + Call) − Call = 0.40 × 125 − 25 = 25
        self.assertAlmostEqual(call_ev(0.40, 100.0, 25.0), 25.0)
        # 0.10 × 125 − 25 = −12.5
        self.assertAlmostEqual(call_ev(0.10, 100.0, 25.0), -12.5)

    def test_equity_margin_formula(self) -> None:
        self.assertAlmostEqual(equity_margin(0.67, 0.20), 0.47)
        self.assertAlmostEqual(equity_margin(0.18, 0.20), -0.02)

    def test_engine_evaluate_call_decision_matches_pure_formulas(self) -> None:
        decision = evaluate_call_decision(equity=0.40, pot_size=100.0, call_amount=25.0)
        self.assertAlmostEqual(decision.required_equity, required_equity(100.0, 25.0))
        self.assertAlmostEqual(decision.call_ev, call_ev(0.40, 100.0, 25.0))
        self.assertEqual(decision.recommendation, recommendation_from_call_ev(decision.call_ev))


class FormattingTests(unittest.TestCase):
    def test_percent_formatting(self) -> None:
        self.assertEqual(format_percent(0.672), "67.2%")
        self.assertEqual(format_percent(0.20), "20.0%")

    def test_positive_and_negative_ev_formatting(self) -> None:
        self.assertEqual(format_signed_ev(58.95), "+58.95")
        self.assertEqual(format_signed_ev(-6.25), "-6.25")
        self.assertEqual(format_signed_ev(0.0), "+0.00")

    def test_signed_margin_formatting(self) -> None:
        self.assertEqual(format_signed_margin_pp(0.472), "+47.2")
        self.assertEqual(format_signed_margin_pp(-0.05), "-5.0")


class ConfidenceBoundaryTests(unittest.TestCase):
    def test_call_boundaries(self) -> None:
        self.assertEqual(confidence_level(0.0), "Marginal Call")
        self.assertEqual(confidence_level(DECISION_MARGIN_MARGINAL - 1e-9), "Marginal Call")
        self.assertEqual(confidence_level(DECISION_MARGIN_MARGINAL), "Strong Call")
        self.assertEqual(confidence_level(DECISION_MARGIN_STRONG - 1e-9), "Strong Call")
        self.assertEqual(confidence_level(DECISION_MARGIN_STRONG), "Very Strong Call")

    def test_fold_boundaries(self) -> None:
        self.assertEqual(confidence_level(-1e-9), "Marginal Fold")
        self.assertEqual(confidence_level(-(DECISION_MARGIN_MARGINAL - 1e-9)), "Marginal Fold")
        self.assertEqual(confidence_level(-DECISION_MARGIN_MARGINAL), "Strong Fold")
        self.assertEqual(confidence_level(-(DECISION_MARGIN_STRONG - 1e-9)), "Strong Fold")
        self.assertEqual(confidence_level(-DECISION_MARGIN_STRONG), "Very Strong Fold")


class DecisionScenarioTests(unittest.TestCase):
    def test_strong_profitable_call(self) -> None:
        # 67.2% equity vs 20% required → +47.2 pp, large +EV
        metrics = build_decision_metrics(0.672, pot_size=100.0, call_amount=25.0)
        self.assertGreater(metrics.equity_margin, DECISION_MARGIN_STRONG)
        self.assertGreater(metrics.call_ev, 0.0)
        self.assertEqual(metrics.recommendation, "Call")
        self.assertIn(metrics.confidence, {"Strong Call", "Very Strong Call"})
        self.assertEqual(metrics.confidence, "Very Strong Call")

        explanation = build_decision_explanation(
            metrics.hero_equity,
            metrics.required_equity,
            metrics.call_ev,
            metrics.recommendation,
        )
        self.assertIn("67.2%", explanation)
        self.assertIn("20.0%", explanation)
        self.assertIn("+47.2", explanation)
        self.assertIn(format_signed_ev(metrics.call_ev), explanation)
        self.assertIn("Call", explanation)
        self.assertIn("break-even threshold", explanation)

        sensitivity = build_decision_sensitivity(
            metrics.hero_equity, metrics.required_equity, metrics.call_ev
        )
        self.assertIn("remains profitable", sensitivity)

    def test_marginal_profitable_call(self) -> None:
        # 21% equity vs 20% required → +1 pp, small +EV
        metrics = build_decision_metrics(0.21, pot_size=100.0, call_amount=25.0)
        self.assertGreater(metrics.equity_margin, 0.0)
        self.assertLess(metrics.equity_margin, DECISION_MARGIN_MARGINAL)
        self.assertGreater(metrics.call_ev, 0.0)
        self.assertLess(metrics.call_ev, 5.0)
        self.assertEqual(metrics.recommendation, "Call")
        self.assertEqual(metrics.confidence, "Marginal Call")

        explanation = build_decision_explanation(
            metrics.hero_equity,
            metrics.required_equity,
            metrics.call_ev,
            metrics.recommendation,
        )
        self.assertIn("Call", explanation)
        self.assertIn("+1.0", explanation)

        sensitivity = build_decision_sensitivity(
            metrics.hero_equity, metrics.required_equity, metrics.call_ev
        )
        self.assertIn("only", sensitivity.lower())
        self.assertIn("unprofitable", sensitivity.lower())

    def test_marginal_fold(self) -> None:
        # 19% equity vs 20% required → −1 pp, small −EV
        metrics = build_decision_metrics(0.19, pot_size=100.0, call_amount=25.0)
        self.assertLess(metrics.equity_margin, 0.0)
        self.assertGreater(metrics.equity_margin, -DECISION_MARGIN_MARGINAL)
        self.assertLess(metrics.call_ev, 0.0)
        self.assertGreater(metrics.call_ev, -5.0)
        self.assertEqual(metrics.recommendation, "Fold")
        self.assertEqual(metrics.confidence, "Marginal Fold")

        explanation = build_decision_explanation(
            metrics.hero_equity,
            metrics.required_equity,
            metrics.call_ev,
            metrics.recommendation,
        )
        self.assertIn("Fold", explanation)
        self.assertIn("1.0", explanation)
        self.assertIn(format_signed_ev(metrics.call_ev), explanation)

        sensitivity = build_decision_sensitivity(
            metrics.hero_equity, metrics.required_equity, metrics.call_ev
        )
        self.assertIn("only", sensitivity.lower())
        self.assertIn("profitable", sensitivity.lower())

    def test_clear_fold(self) -> None:
        # 5% equity vs 20% required → −15 pp, clearly −EV
        metrics = build_decision_metrics(0.05, pot_size=100.0, call_amount=25.0)
        self.assertLess(metrics.equity_margin, -DECISION_MARGIN_STRONG)
        self.assertLess(metrics.call_ev, 0.0)
        self.assertEqual(metrics.recommendation, "Fold")
        self.assertIn(metrics.confidence, {"Strong Fold", "Very Strong Fold"})
        self.assertEqual(metrics.confidence, "Very Strong Fold")

        explanation = build_decision_explanation(
            metrics.hero_equity,
            metrics.required_equity,
            metrics.call_ev,
            metrics.recommendation,
        )
        self.assertIn("Fold", explanation)
        self.assertIn(format_signed_ev(metrics.call_ev), explanation)

        sensitivity = build_decision_sensitivity(
            metrics.hero_equity, metrics.required_equity, metrics.call_ev
        )
        self.assertIn("at least", sensitivity.lower())

    def test_exact_threshold_documents_call_on_zero_ev(self) -> None:
        """
        Exact threshold rule: equity == required ⇒ Call EV ≈ 0 ⇒ Call / Marginal Call.

        This matches evaluate_call_decision's ``call_ev >= 0`` recommendation.
        """
        pot_size = 100.0
        call_amount = 25.0
        hero_equity = required_equity(pot_size, call_amount)  # exactly 20%
        metrics = build_decision_metrics(hero_equity, pot_size, call_amount)

        self.assertAlmostEqual(metrics.required_equity, 0.20)
        self.assertAlmostEqual(metrics.equity_margin, 0.0)
        self.assertAlmostEqual(metrics.call_ev, 0.0, places=9)
        self.assertEqual(metrics.recommendation, "Call")
        self.assertEqual(metrics.confidence, "Marginal Call")

        engine = evaluate_call_decision(hero_equity, pot_size, call_amount)
        self.assertEqual(engine.recommendation, metrics.recommendation)
        self.assertAlmostEqual(engine.call_ev, metrics.call_ev, places=9)

        explanation = build_decision_explanation(
            metrics.hero_equity,
            metrics.required_equity,
            metrics.call_ev,
            metrics.recommendation,
        )
        self.assertIn("Call", explanation)
        self.assertIn("+0.0", explanation)  # margin formatting
        self.assertIn("+0.00", explanation)  # EV formatting

        sensitivity = build_decision_sensitivity(
            metrics.hero_equity, metrics.required_equity, metrics.call_ev
        )
        self.assertIn("effectively zero", sensitivity.lower())


class MonteCarloUncertaintyTests(unittest.TestCase):
    def test_standard_error_and_ci(self) -> None:
        se = monte_carlo_equity_standard_error(0.5, 10_000)
        self.assertAlmostEqual(se, (0.25 / 10_000) ** 0.5)
        half = monte_carlo_equity_ci_halfwidth(0.5, 10_000)
        self.assertAlmostEqual(half, 1.96 * se)
        text = format_monte_carlo_equity_ci(0.491, 25_000)
        self.assertIn("49.1%", text)
        self.assertIn("±", text)
        self.assertIn("95% Monte Carlo CI", text)

    def test_zero_samples_yields_zero_error(self) -> None:
        self.assertEqual(monte_carlo_equity_standard_error(0.4, 0), 0.0)
        self.assertEqual(monte_carlo_equity_ci_halfwidth(0.4, 1), 0.0)


if __name__ == "__main__":
    unittest.main()
