"""Equity heatmap over the 169 starting-hand classes.

Reuses ``poker_engine.calculate_equity`` (exact / Monte Carlo) rather than a
separate simulator. Results are cached by board + opponent range + simulation
settings so repeated identical requests stay responsive.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable

from poker_engine import (
    ENGINE_VERSION,
    Card,
    OpponentHand,
    calculate_equity,
    parse_opponent_range,
)

HEATMAP_RANKS = ("A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2")

# Bump when this module's public API changes so Streamlit reloads it.
HEATMAP_MODULE_VERSION = 2

RandomFloat = Callable[[], float]

_HEATMAP_CACHE: dict[tuple, dict[str, "HandEquityCell"]] = {}
_LAST_HEATMAP_CACHE_HIT = False


def last_heatmap_cache_hit() -> bool:
    return _LAST_HEATMAP_CACHE_HIT


@dataclass(frozen=True)
class HandEquityCell:
    hand: str
    equity: float | None
    win_rate: float | None
    tie_rate: float | None
    loss_rate: float | None
    legal_combos: int


def starting_hand_classes() -> list[str]:
    """Return all 169 grid labels in row-major order (AA … 22)."""
    hands: list[str] = []
    for row_rank in HEATMAP_RANKS:
        for column_rank in HEATMAP_RANKS:
            hands.append(_grid_hand_label(row_rank, column_rank))
    return hands


def _grid_hand_label(row_rank: str, column_rank: str) -> str:
    if row_rank == column_rank:
        return f"{row_rank}{column_rank}"
    high_rank, low_rank = sorted(
        (row_rank, column_rank), key=lambda rank: HEATMAP_RANKS.index(rank)
    )
    if HEATMAP_RANKS.index(row_rank) < HEATMAP_RANKS.index(column_rank):
        return f"{high_rank}{low_rank}s"
    return f"{high_rank}{low_rank}o"


def clear_equity_heatmap_cache() -> None:
    _HEATMAP_CACHE.clear()


def equity_heatmap_cache_size() -> int:
    return len(_HEATMAP_CACHE)


def build_heatmap_cache_key(
    board: list[Card],
    opponent_range: list[OpponentHand] | None,
    opponent_weights: list[float] | None,
    simulations: int,
    exact_max_matchups: int = 75_000,
) -> tuple:
    board_keys = tuple(sorted(card.key() for card in board))
    range_fp = _opponent_range_fingerprint(opponent_range, opponent_weights)
    return (
        ENGINE_VERSION,
        board_keys,
        range_fp,
        int(simulations),
        int(exact_max_matchups),
    )


def _opponent_range_fingerprint(
    opponent_range: list[OpponentHand] | None,
    opponent_weights: list[float] | None,
) -> str:
    if opponent_range is None:
        return "ALL"
    weights = opponent_weights
    if weights is None:
        weights = [1.0] * len(opponent_range)
    if len(weights) != len(opponent_range):
        raise ValueError("opponent_weights must match opponent_range length.")
    parts = [
        f"{hand[0].key()}{hand[1].key()}:{float(weight):.8g}"
        for hand, weight in zip(opponent_range, weights)
    ]
    parts.sort()
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{len(parts)}:{digest}"


def legal_hero_combos(hand_class: str, board: list[Card]) -> list[OpponentHand]:
    blocked = {card.key() for card in board}
    return [
        hand
        for hand in parse_opponent_range(hand_class)
        if hand[0].key() not in blocked and hand[1].key() not in blocked
    ]


def pick_display_combo(hand_class: str, board: list[Card]) -> OpponentHand | None:
    """Stable concrete combo for loading a class into the calculator."""
    legal = legal_hero_combos(hand_class, board)
    return legal[0] if legal else None


def compute_equity_heatmap(
    board: list[Card],
    opponent_range: list[OpponentHand] | None = None,
    opponent_weights: list[float] | None = None,
    simulations: int = 25_000,
    exact_max_matchups: int = 75_000,
    rng: RandomFloat | None = None,
    hand_classes: list[str] | None = None,
) -> dict[str, HandEquityCell]:
    """Compute equity for each starting-hand class vs the given range/board."""
    classes = hand_classes if hand_classes is not None else starting_hand_classes()
    cells: dict[str, HandEquityCell] = {}
    for hand_class in classes:
        cells[hand_class] = _compute_hand_class_cell(
            hand_class,
            board,
            opponent_range=opponent_range,
            opponent_weights=opponent_weights,
            simulations=simulations,
            exact_max_matchups=exact_max_matchups,
            rng=rng,
        )
    return cells


def heatmap_exact_max_matchups(board: list[Card], exact_max_matchups: int) -> int:
    """Cap exact enumeration on incomplete boards so 169-hand matrices stay responsive."""
    effective = int(exact_max_matchups)
    if len(board) < 5:
        effective = min(effective, 2_500)
    return effective


def heatmap_simulation_budget(simulations: int) -> int:
    """Honor calculator settings while keeping full-matrix updates interactive."""
    return max(250, min(int(simulations), 10_000))


def get_or_compute_equity_heatmap(
    board: list[Card],
    opponent_range: list[OpponentHand] | None = None,
    opponent_weights: list[float] | None = None,
    simulations: int = 25_000,
    exact_max_matchups: int = 75_000,
    rng: RandomFloat | None = None,
    hand_classes: list[str] | None = None,
) -> dict[str, HandEquityCell]:
    """Return a cached heatmap for identical inputs, otherwise compute and store."""
    global _LAST_HEATMAP_CACHE_HIT

    effective_sims = heatmap_simulation_budget(simulations)
    effective_exact_max = heatmap_exact_max_matchups(board, exact_max_matchups)
    key = build_heatmap_cache_key(
        board,
        opponent_range,
        opponent_weights,
        effective_sims,
        effective_exact_max,
    )
    # Full-matrix caches only (custom hand_classes lists are not cached).
    if hand_classes is None and key in _HEATMAP_CACHE:
        _LAST_HEATMAP_CACHE_HIT = True
        return _HEATMAP_CACHE[key]

    _LAST_HEATMAP_CACHE_HIT = False
    cells = compute_equity_heatmap(
        board,
        opponent_range=opponent_range,
        opponent_weights=opponent_weights,
        simulations=effective_sims,
        exact_max_matchups=effective_exact_max,
        rng=rng,
        hand_classes=hand_classes,
    )
    if hand_classes is None:
        _HEATMAP_CACHE[key] = cells
    return cells


def _compute_hand_class_cell(
    hand_class: str,
    board: list[Card],
    *,
    opponent_range: list[OpponentHand] | None,
    opponent_weights: list[float] | None,
    simulations: int,
    exact_max_matchups: int,
    rng: RandomFloat | None,
) -> HandEquityCell:
    legal = legal_hero_combos(hand_class, board)
    if not legal:
        return HandEquityCell(hand_class, None, None, None, None, 0)

    # Split the simulation budget across legal combos so class equity is an
    # average over blockers/suits while total work scales with `simulations`.
    sims_each = max(50, int(simulations) // len(legal))
    equities: list[float] = []
    win_rates: list[float] = []
    tie_rates: list[float] = []
    loss_rates: list[float] = []

    for combo in legal:
        try:
            result = calculate_equity(
                list(combo),
                board,
                simulations=sims_each,
                exact_max_matchups=exact_max_matchups,
                rng=rng,
                opponent_range=opponent_range,
                opponent_weights=opponent_weights,
            )
        except ValueError:
            continue
        equities.append(result.equity)
        win_rates.append(result.win_rate)
        tie_rates.append(result.tie_rate)
        loss_rates.append(result.loss_rate)

    if not equities:
        return HandEquityCell(hand_class, None, None, None, None, len(legal))

    count = float(len(equities))
    return HandEquityCell(
        hand=hand_class,
        equity=sum(equities) / count,
        win_rate=sum(win_rates) / count,
        tie_rate=sum(tie_rates) / count,
        loss_rate=sum(loss_rates) / count,
        legal_combos=len(legal),
    )


def equity_to_heatmap_color(equity: float | None) -> str:
    """Dark red (poor) → yellow (medium) → bright green (high)."""
    if equity is None:
        return "#1e293b"

    value = max(0.0, min(1.0, float(equity)))
    if value <= 0.5:
        t = value / 0.5
        return _lerp_hex("#7f1d1d", "#ca8a04", t)
    t = (value - 0.5) / 0.5
    return _lerp_hex("#ca8a04", "#4ade80", t)


def _lerp_hex(start: str, end: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    s = _hex_to_rgb(start)
    e = _hex_to_rgb(end)
    mixed = tuple(int(round(a + (b - a) * t)) for a, b in zip(s, e))
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    raw = color.removeprefix("#")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
