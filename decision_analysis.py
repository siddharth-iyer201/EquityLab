"""Pure EV / decision-explanation helpers for the Equity Calculator.

These functions are intentionally free of Streamlit and simulation state so they
can be unit-tested in isolation. UI code should call into this module rather
than re-implementing the formulas.

Documented exact-threshold rule
-------------------------------
When Call EV is exactly zero (hero equity equals required equity), the
recommendation is **Call** because ``evaluate_call_decision`` uses
``call_ev >= 0``. Confidence is **Marginal Call** (equity margin of 0).
Sensitivity copy states that Call EV is effectively zero at the current equity.

Confidence bands (deterministic, from equity margin = hero − required)
----------------------------------------------------------------------
Thresholds live only in ``DECISION_MARGIN_MARGINAL`` / ``DECISION_MARGIN_STRONG``:

======= ===================== ========================
|margin| Call side            Fold side
======= ===================== ========================
≥ 0.10   Very Strong Call      Very Strong Fold
≥ 0.03   Strong Call           Strong Fold
else     Marginal Call         Marginal Fold
======= ===================== ========================

Boundaries are inclusive on the Call/Fold side thresholds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Bump when this module's public API changes so Streamlit reloads it.
DECISION_ANALYSIS_VERSION = 3

# Confidence bands from |equity margin| (hero equity − required equity).
# Keep all UI confidence copy derived from these two constants only.
DECISION_MARGIN_MARGINAL = 0.03
DECISION_MARGIN_STRONG = 0.10

CONFIDENCE_LABELS = (
    "Very Strong Call",
    "Strong Call",
    "Marginal Call",
    "Marginal Fold",
    "Strong Fold",
    "Very Strong Fold",
)


@dataclass(frozen=True)
class DecisionMetrics:
    pot_size: float
    call_amount: float
    hero_equity: float
    required_equity: float
    equity_margin: float
    call_ev: float
    recommendation: str
    confidence: str


@dataclass(frozen=True)
class DecisionStability:
    """Whether Monte Carlo uncertainty can change the call/fold decision."""

    label: str
    lower_equity: float
    upper_equity: float
    threshold_overlaps: bool


def required_equity(pot_size: float, call_amount: float) -> float:
    """Required Equity = Call / (Pot + Call). Zero when nothing is at risk.

    ``pot_size`` is pot chips *before* hero calls; ``call_amount`` is chips to call.
    """
    if call_amount < 0:
        raise ValueError("Call amount cannot be negative.")
    if pot_size < 0:
        raise ValueError("Pot size cannot be negative.")
    if call_amount <= 0:
        return 0.0
    return call_amount / (pot_size + call_amount)


def call_ev(hero_equity: float, pot_size: float, call_amount: float) -> float:
    """Call EV = Equity × (Pot Before Calling + Call) − Call.

    Positive values mean calling is +EV vs folding (fold EV = 0 in this model).
    """
    if call_amount < 0:
        raise ValueError("Call amount cannot be negative.")
    if pot_size < 0:
        raise ValueError("Pot size cannot be negative.")
    return hero_equity * (pot_size + call_amount) - call_amount


def equity_margin(hero_equity: float, required: float) -> float:
    """Equity margin = Hero Equity − Required Equity."""
    return float(hero_equity) - float(required)


def recommendation_from_call_ev(ev: float) -> str:
    """Call when EV is non-negative; Fold when EV is negative."""
    return "Call" if ev >= 0 else "Fold"


def confidence_level(margin: float) -> str:
    """Map equity margin to a deterministic confidence label."""
    abs_margin = abs(margin)
    if margin >= 0:
        if abs_margin >= DECISION_MARGIN_STRONG:
            return "Very Strong Call"
        if abs_margin >= DECISION_MARGIN_MARGINAL:
            return "Strong Call"
        return "Marginal Call"
    if abs_margin >= DECISION_MARGIN_STRONG:
        return "Very Strong Fold"
    if abs_margin >= DECISION_MARGIN_MARGINAL:
        return "Strong Fold"
    return "Marginal Fold"


def monte_carlo_equity_standard_error(equity: float, samples: int) -> float:
    """Binomial SE for an equity proportion approximated from ``samples`` trials.

    Uses ``sqrt(p(1-p)/n)``. Appropriate for Monte Carlo boards/trials; not used
    for exact enumeration.
    """
    n = int(samples)
    if n <= 1:
        return 0.0
    p = min(max(float(equity), 0.0), 1.0)
    return math.sqrt(p * (1.0 - p) / n)


def monte_carlo_equity_ci_halfwidth(
    equity: float,
    samples: int,
    *,
    z: float = 1.96,
) -> float:
    """Half-width of an approximate normal CI (default ~95% with z=1.96)."""
    return float(z) * monte_carlo_equity_standard_error(equity, samples)


def format_monte_carlo_equity_ci(
    equity: float,
    samples: int,
    *,
    z: float = 1.96,
) -> str:
    """e.g. ``49.1% ± 0.6% (95% Monte Carlo CI)``."""
    half = monte_carlo_equity_ci_halfwidth(equity, samples, z=z)
    coverage = "95" if abs(float(z) - 1.96) < 1e-6 else f"{float(z):.2f}σ"
    return f"{format_percent(equity)} ± {half * 100.0:.1f}% ({coverage}% Monte Carlo CI)"


def decision_stability(
    equity: float,
    required: float,
    samples: int,
    *,
    z: float = 1.96,
) -> DecisionStability:
    """Classify whether a Monte Carlo interval stays on one side of break-even.

    The recommendation itself still uses the point estimate. This helper only
    reports whether ordinary sampling noise could move that estimate across the
    required-equity threshold. Equality belongs to Call, matching the EV rule.
    """
    half = monte_carlo_equity_ci_halfwidth(equity, samples, z=z)
    lower = max(0.0, float(equity) - half)
    upper = min(1.0, float(equity) + half)
    threshold = float(required)
    if lower >= threshold:
        label = "Stable Call"
        overlaps = False
    elif upper < threshold:
        label = "Stable Fold"
        overlaps = False
    else:
        label = "Threshold Overlap"
        overlaps = True
    return DecisionStability(label, lower, upper, overlaps)


def build_decision_metrics(
    hero_equity: float,
    pot_size: float,
    call_amount: float,
) -> DecisionMetrics:
    required = required_equity(pot_size, call_amount)
    ev = call_ev(hero_equity, pot_size, call_amount)
    margin = equity_margin(hero_equity, required)
    return DecisionMetrics(
        pot_size=float(pot_size),
        call_amount=float(call_amount),
        hero_equity=float(hero_equity),
        required_equity=required,
        equity_margin=margin,
        call_ev=ev,
        recommendation=recommendation_from_call_ev(ev),
        confidence=confidence_level(margin),
    )


def format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def format_signed_ev(value: float) -> str:
    """Format Call EV with an explicit sign for positive and negative values."""
    return f"{value:+,.2f}"


def format_signed_margin_pp(margin: float) -> str:
    """Format equity margin in percentage points with an explicit sign."""
    return f"{margin * 100.0:+.1f}"


def build_decision_explanation(
    hero_equity: float,
    required: float,
    call_ev_value: float,
    recommendation: str,
) -> str:
    """Synthesize equity / EV into one explanation (not a bullet restatement)."""
    margin = equity_margin(hero_equity, required)
    hero_s = format_percent(hero_equity)
    required_s = format_percent(required)
    margin_s = format_signed_margin_pp(margin)
    ev_s = format_signed_ev(call_ev_value)

    return (
        f"Hero has {hero_s} equity against a {required_s} break-even threshold, "
        f"giving a {margin_s} percentage-point margin. At the current pot and call size "
        f"this produces {ev_s} chips of call EV, making {recommendation} the "
        f"EV-maximizing action."
    )


def build_decision_sensitivity(
    hero_equity: float,
    required: float,
    call_ev_value: float,
) -> str:
    """One sentence on how far equity can move before the decision flips."""
    margin = equity_margin(hero_equity, required)
    buffer_pp = abs(margin) * 100.0
    break_even = format_percent(required)

    if abs(margin) < 1e-12 or abs(call_ev_value) < 1e-9:
        return (
            "Call EV is effectively zero at the current equity; any decrease makes calling "
            "unprofitable, and any increase makes calling profitable."
        )

    if margin > 0:
        if buffer_pp >= DECISION_MARGIN_STRONG * 100.0:
            return (
                f"This decision remains profitable even if equity decreases by up to "
                f"{buffer_pp:.1f} percentage points (break-even at {break_even})."
            )
        only = "only " if buffer_pp < DECISION_MARGIN_MARGINAL * 100.0 else ""
        return (
            f"If equity dropped by {only}{buffer_pp:.1f} percentage points "
            f"(to {break_even}), this call would become unprofitable."
        )

    if buffer_pp >= DECISION_MARGIN_STRONG * 100.0:
        return (
            f"Calling remains unprofitable unless equity increases by at least "
            f"{buffer_pp:.1f} percentage points (break-even at {break_even})."
        )
    only = "only " if buffer_pp < DECISION_MARGIN_MARGINAL * 100.0 else ""
    return (
        f"If equity rose by {only}{buffer_pp:.1f} percentage points "
        f"(to {break_even}), calling would become profitable."
    )
