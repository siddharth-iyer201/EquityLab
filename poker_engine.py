from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import combinations
import bisect
import math
import random
import re
import time
from typing import Callable, Iterable, Literal

RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A")
SUITS = ("c", "d", "h", "s")
RANK_VALUE = {rank: index + 2 for index, rank in enumerate(RANKS)}
RANK_INDEX = {rank: index for index, rank in enumerate(RANKS)}
HAND_LABELS = (
    "High card",
    "One pair",
    "Two pair",
    "Three of a kind",
    "Straight",
    "Flush",
    "Full house",
    "Four of a kind",
    "Straight flush",
)

# Canonical category names for completed-hand classification (postflop analysis).
HAND_CATEGORIES = (
    "High Card",
    "One Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
)
_VALUE_TO_RANK = {value: rank for rank, value in RANK_VALUE.items()}
_RANK_PLURALS = {
    "A": "Aces",
    "K": "Kings",
    "Q": "Queens",
    "J": "Jacks",
    "T": "10s",
    "9": "9s",
    "8": "8s",
    "7": "7s",
    "6": "6s",
    "5": "5s",
    "4": "4s",
    "3": "3s",
    "2": "2s",
}

EquityMode = Literal["exact", "monte-carlo"]
RandomFloat = Callable[[], float]
OpponentHand = tuple["Card", "Card"]

# Bump when the equity engine changes so Streamlit reloads this module.
ENGINE_VERSION = 11

_SUIT_INDEX = {suit: index for index, suit in enumerate(SUITS)}
_FULL_DECK: tuple["Card", ...] | None = None
_ALL_STARTING_HANDS: tuple[OpponentHand, ...] | None = None

# Rank bits use values 2..14. Precompute straight highs and top-five rank tuples.
_STRAIGHT_HIGH = [0] * (1 << 15)
_TOP_FIVE_RANKS: list[tuple[int, ...]] = [()] * (1 << 15)


def _build_rank_lookup_tables() -> None:
    wheel = (1 << 14) | (1 << 5) | (1 << 4) | (1 << 3) | (1 << 2)
    straight_masks = []
    for high in range(14, 5, -1):
        needed = 0
        for offset in range(5):
            needed |= 1 << (high - offset)
        straight_masks.append((needed, high))
    straight_masks.append((wheel, 5))

    for mask in range(1 << 15):
        straight_high = 0
        for needed, high in straight_masks:
            if mask & needed == needed:
                straight_high = high
                break
        _STRAIGHT_HIGH[mask] = straight_high

        values: list[int] = []
        for value in range(14, 1, -1):
            if mask & (1 << value):
                values.append(value)
                if len(values) == 5:
                    break
        _TOP_FIVE_RANKS[mask] = tuple(values)


_build_rank_lookup_tables()


@dataclass(frozen=True, order=True)
class Card:
    rank: str
    suit: str

    def key(self) -> str:
        return f"{self.rank}{self.suit}"

    def display(self) -> str:
        return self.key().upper()


@dataclass(frozen=True)
class HandScore:
    category: int
    values: tuple[int, ...]

    @property
    def label(self) -> str:
        return HAND_LABELS[self.category]


@dataclass(frozen=True)
class EquityResult:
    wins: float
    ties: float
    losses: float
    total: float
    equity: float
    mode: EquityMode
    hero_hand_label: str
    hand_distribution: dict[str, float] = field(default_factory=dict)
    opponent_hand_distribution: dict[str, float] = field(default_factory=dict)
    boards_evaluated: int = 0
    opponent_combinations_evaluated: int = 0
    runtime_ms: float = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total else 0

    @property
    def tie_rate(self) -> float:
        return self.ties / self.total if self.total else 0

    @property
    def loss_rate(self) -> float:
        return self.losses / self.total if self.total else 0


@dataclass(frozen=True)
class CallDecision:
    pot_size: float
    call_amount: float
    required_equity: float
    call_ev: float
    recommendation: str


@dataclass(frozen=True)
class BoardTextureAnalysis:
    labels: tuple[str, ...]
    explanation: str


DRAW_LABELS = (
    "Flush Draw",
    "Nut Flush Draw",
    "Open-Ended Straight Draw",
    "Double Gutshot Straight Draw",
    "Gutshot Straight Draw",
)

EXTENDED_DRAW_LABELS = (
    "Flush Draw",
    "Nut Flush Draw",
    "Open-Ended Straight Draw",
    "Double Gutshot Straight Draw",
    "Gutshot Straight Draw",
    "Backdoor Flush Draw",
    "Backdoor Straight Draw",
)


@dataclass(frozen=True)
class HeroSituationAnalysis:
    street: str
    made_hand_label: str
    overcard_count: int
    draws: tuple[str, ...]
    outs: int | None
    notes: tuple[str, ...]

# Five-card straight windows; Ace is high (14) and also low in the wheel.
_STRAIGHT_WINDOWS: tuple[tuple[int, ...], ...] = (
    (14, 5, 4, 3, 2),
    (6, 5, 4, 3, 2),
    (7, 6, 5, 4, 3),
    (8, 7, 6, 5, 4),
    (9, 8, 7, 6, 5),
    (10, 9, 8, 7, 6),
    (11, 10, 9, 8, 7),
    (12, 11, 10, 9, 8),
    (13, 12, 11, 10, 9),
    (14, 13, 12, 11, 10),
)

BROADWAY_RANKS = frozenset({"T", "J", "Q", "K", "A"})
LOW_RANKS = frozenset({"2", "3", "4", "5", "6", "7", "8"})


def parse_cards(text: str, expected_count: int | None = None) -> list[Card]:
    cards = [_parse_card_token(token) for token in _tokenize_cards(text)]

    if expected_count is not None and len(cards) != expected_count:
        plural = "" if expected_count == 1 else "s"
        raise ValueError(f"Expected {expected_count} card{plural}, got {len(cards)}.")

    assert_no_duplicates(cards)
    return cards


def full_deck() -> list[Card]:
    return list(_get_full_deck())


def _get_full_deck() -> tuple[Card, ...]:
    global _FULL_DECK
    if _FULL_DECK is None:
        _FULL_DECK = tuple(Card(rank, suit) for suit in SUITS for rank in RANKS)
    return _FULL_DECK


def remove_cards(deck: Iterable[Card], cards_to_remove: Iterable[Card]) -> list[Card]:
    removed = {card.key() for card in cards_to_remove}
    return [card for card in deck if card.key() not in removed]


def assert_no_duplicates(cards: Iterable[Card]) -> None:
    seen: set[str] = set()

    for card in cards:
        key = card.key()
        if key in seen:
            raise ValueError(f"Duplicate card: {card.display()}")
        seen.add(key)


def evaluate_best_hand(cards: list[Card]) -> HandScore:
    if len(cards) < 5 or len(cards) > 7:
        raise ValueError(f"Expected 5 to 7 cards, got {len(cards)}.")

    category, values = _rank_hand(cards)
    return HandScore(category, values)


def classify_completed_hand(cards: list[Card]) -> str:
    """
    Classify a completed Hold'em hand from exactly 7 cards (2 hole + 5 board).

    Reuses evaluate_best_hand / _rank_hand — does not reimplement ranking.
    Returns only the canonical category name from HAND_CATEGORIES.
    """
    if len(cards) != 7:
        raise ValueError(f"Expected exactly 7 cards, got {len(cards)}.")
    assert_no_duplicates(cards)
    score = evaluate_best_hand(cards)
    return HAND_CATEGORIES[score.category]


def analyze_board_texture(board: list[Card]) -> BoardTextureAnalysis:
    """
    Describe community-card texture in poker terms.

    Independent of equity simulation — analysis layer only.
    """
    assert_no_duplicates(board)
    if len(board) > 5:
        raise ValueError(f"Board cannot contain more than 5 cards, got {len(board)}.")
    if not board:
        return BoardTextureAnalysis(
            ("Preflop",),
            "No community cards are out yet, so board texture analysis starts once a flop is dealt.",
        )

    ranks = [card.rank for card in board]
    suits = [card.suit for card in board]
    values = sorted({RANK_VALUE[rank] for rank in ranks})
    rank_counts: dict[str, int] = {}
    for rank in ranks:
        rank_counts[rank] = rank_counts.get(rank, 0) + 1

    labels: list[str] = []
    reasons: list[str] = []

    paired = any(count >= 2 for count in rank_counts.values())
    if paired:
        labels.append("Paired board")
        pair_rank = next(rank for rank, count in rank_counts.items() if count >= 2)
        reasons.append(f"the board is paired with {pair_rank}s")

    flop = board[:3] if len(board) >= 3 else board
    if len(flop) == 3:
        flop_suits = {card.suit for card in flop}
        if len(flop_suits) == 1:
            labels.append("Monotone flop")
            reasons.append("the flop is monotone with all three cards the same suit")
        elif len(flop_suits) == 2:
            labels.append("Two-tone flop")
            reasons.append("the flop is two-tone with exactly two suits")
        else:
            labels.append("Rainbow flop")
            reasons.append("the flop is rainbow with three different suits")

    gaps = [values[index + 1] - values[index] for index in range(len(values) - 1)] if len(values) > 1 else []
    connected = bool(gaps) and any(gap <= 2 for gap in gaps)
    highly_connected = bool(gaps) and sum(1 for gap in gaps if gap <= 2) >= 2
    disconnected = (not gaps) or all(gap >= 3 for gap in gaps)

    if highly_connected or (connected and len(flop) == 3 and len({card.suit for card in flop}) <= 2):
        labels.append("Highly coordinated board")
        reasons.append("ranks and suits interact closely, creating a highly coordinated texture")
    elif connected:
        labels.append("Connected board")
        reasons.append("several board ranks sit close together, making the board connected")

    broadway_count = sum(1 for rank in ranks if rank in BROADWAY_RANKS)
    highest = max(ranks, key=lambda rank: RANK_VALUE[rank])
    all_low = all(rank in LOW_RANKS for rank in ranks)

    dry = (
        not paired
        and disconnected
        and (len(flop) < 3 or len({card.suit for card in flop}) == 3)
        and broadway_count <= 1
        and not all_low
    )
    if dry:
        labels.append("Dry board")
        reasons.append("the board is dry with little connectivity or flush potential")

    if highest == "A":
        labels.append("Ace-high board")
        reasons.append("an Ace is the highest board card")

    if broadway_count >= 2:
        labels.append("Broadway-heavy board")
        reasons.append(f"{broadway_count} broadway cards (T–A) appear on the board")

    if all_low:
        labels.append("Low board")
        reasons.append("every community card is eight or lower")

    if not labels:
        labels.append("Standard board")
        reasons.append("the board does not show an extreme texture pattern")

    explanation = _board_texture_explanation(labels, reasons)
    return BoardTextureAnalysis(tuple(labels), explanation)


def _board_texture_explanation(labels: list[str], reasons: list[str]) -> str:
    if not reasons:
        return "Board texture looks fairly standard."
    detail = "; ".join(reasons)
    return detail[0].upper() + detail[1:] + "."


def analyze_hero_draws(hero_hand: list[Card], board: list[Card]) -> tuple[str, ...]:
    """
    Detect common draws from currently known hero + board cards only.

    Does not simulate future runouts. Returns active draw labels in DRAW_LABELS order.
    """
    situation = analyze_hero_situation(hero_hand, board)
    return tuple(label for label in situation.draws if label in DRAW_LABELS)


def analyze_hero_situation(hero_hand: list[Card], board: list[Card]) -> HeroSituationAnalysis:
    """
    Richer hero board-state analysis for study UI: made hand, draws, overcards, outs.

    Uses currently known cards only — does not run Monte Carlo.
    """
    if len(hero_hand) != 2:
        raise ValueError(f"Hero hand must contain exactly 2 cards, got {len(hero_hand)}.")
    if len(board) > 5:
        raise ValueError(f"Board cannot contain more than 5 cards, got {len(board)}.")
    assert_no_duplicates([*hero_hand, *board])

    street = _street_name(len(board))
    made_hand_label = _hero_made_hand_label(hero_hand, board)
    if len(board) >= 5:
        return HeroSituationAnalysis(street, made_hand_label, 0, (), None, ())

    cards = [*hero_hand, *board]
    draws: list[str] = []

    # Never advertise a flush draw once a flush (or better flush category) is already made.
    made_flush = _hero_has_made_flush_category(hero_hand, board)
    flush_suit = None if made_flush else _flush_draw_suit(hero_hand, cards)
    if flush_suit is not None:
        # Prefer a single precise label: nut draw OR non-nut draw (not both).
        if _is_nut_flush_draw(hero_hand, cards, flush_suit):
            draws.append("Nut Flush Draw")
        else:
            draws.append("Flush Draw")

    straight_draw = _straight_draw_label(hero_hand, cards)
    if straight_draw:
        draws.append(straight_draw)

    if len(board) == 3:
        # Backdoors only when the corresponding live draw is not already present.
        if flush_suit is None and not made_flush and _has_backdoor_flush_draw(hero_hand, cards):
            draws.append("Backdoor Flush Draw")
        if straight_draw is None and _has_backdoor_straight_draw(hero_hand, cards):
            draws.append("Backdoor Straight Draw")

    overcard_count = _overcard_count(hero_hand, board)
    outs = _count_draw_outs(hero_hand, board, cards)
    notes: list[str] = []
    if overcard_count:
        notes.append(f"{overcard_count} overcard{'s' if overcard_count != 1 else ''}")

    return HeroSituationAnalysis(
        street=street,
        made_hand_label=made_hand_label,
        overcard_count=overcard_count,
        draws=tuple(draws),
        outs=outs,
        notes=tuple(notes),
    )


def _hero_has_made_flush_category(hero_hand: list[Card], board: list[Card]) -> bool:
    """True when hero's best hand is already a Flush or Straight Flush."""
    cards = [*hero_hand, *board]
    if len(cards) < 5:
        return False
    category = evaluate_best_hand(cards).category
    return category in (5, 8)  # Flush, Straight flush


def _street_name(board_count: int) -> str:
    if board_count <= 0:
        return "Preflop"
    if board_count <= 3:
        return "Flop"
    if board_count == 4:
        return "Turn"
    return "River"


def _hero_made_hand_label(hero_hand: list[Card], board: list[Card]) -> str:
    cards = [*hero_hand, *board]
    if len(cards) >= 5:
        return HAND_CATEGORIES[evaluate_best_hand(cards).category]
    return "Hand not complete"


def _overcard_count(hero_hand: list[Card], board: list[Card]) -> int:
    if len(board) < 3 or len(board) > 4:
        return 0
    board_high = max(RANK_VALUE[card.rank] for card in board)
    return sum(1 for card in hero_hand if RANK_VALUE[card.rank] > board_high)


def _has_backdoor_flush_draw(hero_hand: list[Card], cards: list[Card]) -> bool:
    """Flop-only: exactly two cards to a suit, with hero holding at least one."""
    if len(cards) != 5:  # 2 hero + 3 board
        return False
    suit_counts = {suit: 0 for suit in SUITS}
    for card in cards:
        suit_counts[card.suit] += 1
    hero_suits = {card.suit for card in hero_hand}
    for suit, count in suit_counts.items():
        if count == 2 and suit in hero_suits:
            # Skip if already a live flush draw (4 to a suit).
            if suit_counts[suit] >= 4:
                continue
            return True
    return False


def _has_backdoor_straight_draw(hero_hand: list[Card], cards: list[Card]) -> bool:
    """Flop-only: a five-card window missing exactly two ranks, using a hero card."""
    if len(cards) != 5:
        return False
    rank_values = {RANK_VALUE[card.rank] for card in cards}
    hero_values = {RANK_VALUE[card.rank] for card in hero_hand}
    for window in _STRAIGHT_WINDOWS:
        present = [value for value in window if value in rank_values]
        missing = [value for value in window if value not in rank_values]
        if len(missing) != 2:
            continue
        if not any(value in hero_values for value in present):
            continue
        return True
    return False


def _count_draw_outs(hero_hand: list[Card], board: list[Card], cards: list[Card]) -> int | None:
    """Count unique remaining cards that complete a flush or straight draw."""
    if len(board) < 3 or len(board) >= 5:
        return None

    known = {card.key() for card in cards}
    completing: set[str] = set()

    if not _hero_has_made_flush_category(hero_hand, board):
        flush_suit = _flush_draw_suit(hero_hand, cards)
        if flush_suit is not None:
            for rank in RANKS:
                key = f"{rank}{flush_suit}"
                if key not in known:
                    completing.add(key)

    completing_ranks = _straight_completing_ranks(hero_hand, cards)
    for value in completing_ranks:
        rank = _VALUE_TO_RANK[value]
        for suit in SUITS:
            key = f"{rank}{suit}"
            if key not in known:
                completing.add(key)

    if not completing:
        return None
    return len(completing)


def _straight_completing_ranks(hero_hand: list[Card], cards: list[Card]) -> set[int]:
    rank_values = {RANK_VALUE[card.rank] for card in cards}
    hero_values = {RANK_VALUE[card.rank] for card in hero_hand}
    completing: set[int] = set()
    has_made_straight = False
    for window in _STRAIGHT_WINDOWS:
        present = [value for value in window if value in rank_values]
        missing = [value for value in window if value not in rank_values]
        if not missing:
            has_made_straight = True
            continue
        if len(missing) != 1:
            continue
        if not any(value in hero_values for value in present):
            continue
        completing.add(missing[0])
    if has_made_straight:
        return set()
    return completing


def _flush_draw_suit(hero_hand: list[Card], cards: list[Card]) -> str | None:
    suit_counts = {suit: 0 for suit in SUITS}
    for card in cards:
        suit_counts[card.suit] += 1

    hero_suits = {card.suit for card in hero_hand}
    for suit, count in suit_counts.items():
        if count == 4 and suit in hero_suits:
            return suit
    return None


def _is_nut_flush_draw(hero_hand: list[Card], cards: list[Card], suit: str) -> bool:
    hero_flush_values = [RANK_VALUE[card.rank] for card in hero_hand if card.suit == suit]
    if not hero_flush_values:
        return False
    hero_high = max(hero_flush_values)
    known_keys = {card.key() for card in cards}
    for rank, value in RANK_VALUE.items():
        if value <= hero_high:
            continue
        if f"{rank}{suit}" not in known_keys:
            return False
    return True


def _straight_draw_label(hero_hand: list[Card], cards: list[Card]) -> str | None:
    completing = _straight_completing_ranks(hero_hand, cards)
    if not completing:
        return None
    if len(completing) == 1:
        return "Gutshot Straight Draw"
    if _is_open_ended_straight_draw(hero_hand, cards, completing):
        return "Open-Ended Straight Draw"
    return "Double Gutshot Straight Draw"


def _is_open_ended_straight_draw(
    hero_hand: list[Card],
    cards: list[Card],
    completing: set[int],
) -> bool:
    """True when four connected ranks are present and both end-ranks are outs."""
    rank_values = {RANK_VALUE[card.rank] for card in cards}
    hero_values = {RANK_VALUE[card.rank] for card in hero_hand}
    # Four consecutive ranks (Ace-high only; wheel handled separately below).
    for low in range(2, 12):
        seq = (low, low + 1, low + 2, low + 3)
        if not all(value in rank_values for value in seq):
            continue
        if not any(value in hero_values for value in seq):
            continue
        low_out = low - 1
        high_out = low + 4
        if low_out in completing and high_out in completing:
            return True
    # Wheel OESD-style: A234 present → outs 5 (and sometimes broadways not both ends).
    wheel_four = (14, 2, 3, 4)
    if all(value in rank_values for value in wheel_four) and any(
        value in hero_values for value in wheel_four
    ):
        if 5 in completing and (14 in completing or 6 in completing):
            # Not a classic double-ended wheel OESD; treat A234x with 5 as gutshot-like.
            pass
    return False


def _rank_hand(cards: Iterable[Card]) -> tuple[int, tuple[int, ...]]:
    return _rank_from_counts(*_counts_from_cards(cards))


def _counts_from_cards(cards: Iterable[Card]) -> tuple[list[int], list[int], list[int], int]:
    rank_counts = [0] * 15
    suit_counts = [0, 0, 0, 0]
    suit_masks = [0, 0, 0, 0]
    rank_mask = 0

    for card in cards:
        value = RANK_VALUE[card.rank]
        suit = _SUIT_INDEX[card.suit]
        rank_counts[value] += 1
        suit_counts[suit] += 1
        suit_masks[suit] |= 1 << value
        rank_mask |= 1 << value

    return rank_counts, suit_counts, suit_masks, rank_mask


def _counts_from_value_suits(
    value_suits: Iterable[tuple[int, int]],
) -> tuple[list[int], list[int], list[int], int]:
    rank_counts = [0] * 15
    suit_counts = [0, 0, 0, 0]
    suit_masks = [0, 0, 0, 0]
    rank_mask = 0

    for value, suit in value_suits:
        rank_counts[value] += 1
        suit_counts[suit] += 1
        suit_masks[suit] |= 1 << value
        rank_mask |= 1 << value

    return rank_counts, suit_counts, suit_masks, rank_mask


def _rank_with_extra(
    base_counts: tuple[list[int], list[int], list[int], int],
    extra_value_suits: Iterable[tuple[int, int]],
) -> tuple[int, tuple[int, ...]]:
    rank_counts = base_counts[0][:]
    suit_counts = base_counts[1][:]
    suit_masks = base_counts[2][:]
    rank_mask = base_counts[3]

    for value, suit in extra_value_suits:
        rank_counts[value] += 1
        suit_counts[suit] += 1
        suit_masks[suit] |= 1 << value
        rank_mask |= 1 << value

    return _rank_from_counts(rank_counts, suit_counts, suit_masks, rank_mask)


def _rank_from_counts(
    rank_counts: list[int],
    suit_counts: list[int],
    suit_masks: list[int],
    rank_mask: int,
) -> tuple[int, tuple[int, ...]]:
    flush_mask = 0
    for suit in range(4):
        if suit_counts[suit] >= 5:
            flush_mask = suit_masks[suit]
            straight_flush_high = _STRAIGHT_HIGH[flush_mask]
            if straight_flush_high:
                return 8, (straight_flush_high,)
            break

    quad = trip1 = trip2 = pair1 = pair2 = pair3 = 0
    single1 = single2 = single3 = single4 = single5 = 0
    singles = 0

    for value in range(14, 1, -1):
        count = rank_counts[value]
        if count == 4:
            if not quad:
                quad = value
        elif count == 3:
            if not trip1:
                trip1 = value
            elif not trip2:
                trip2 = value
        elif count == 2:
            if not pair1:
                pair1 = value
            elif not pair2:
                pair2 = value
            elif not pair3:
                pair3 = value
        elif count == 1:
            singles += 1
            if singles == 1:
                single1 = value
            elif singles == 2:
                single2 = value
            elif singles == 3:
                single3 = value
            elif singles == 4:
                single4 = value
            elif singles == 5:
                single5 = value

    if quad:
        kicker = 0
        for value in (trip1, pair1, pair2, pair3, single1, single2, single3, single4, single5):
            if value > kicker:
                kicker = value
        return 7, (quad, kicker)

    if trip1 and (pair1 or trip2):
        return 6, (trip1, trip2 if trip2 else pair1)

    if flush_mask:
        return 5, _TOP_FIVE_RANKS[flush_mask]

    straight_high = _STRAIGHT_HIGH[rank_mask]
    if straight_high:
        return 4, (straight_high,)

    if trip1:
        return 3, (trip1, single1, single2)

    if pair1 and pair2:
        kicker = pair3
        for value in (single1, single2, single3, single4, single5):
            if value > kicker:
                kicker = value
        return 2, (pair1, pair2, kicker)

    if pair1:
        return 1, (pair1, single1, single2, single3)

    return 0, (single1, single2, single3, single4, single5)


def describe_hand(score: HandScore) -> str:
    values = score.values

    if score.category == 8:
        if values[0] == 14:
            return "Royal flush"
        return f"Straight flush, {_value_to_rank(values[0])}-high"

    if score.category == 7:
        return f"Four of a kind, {_rank_plural(values[0])}"

    if score.category == 6:
        return f"Full house, {_rank_plural(values[0])} full of {_rank_plural(values[1])}"

    if score.category == 5:
        return f"Flush, {_value_to_rank(values[0])}-high"

    if score.category == 4:
        return f"Straight, {_value_to_rank(values[0])}-high"

    if score.category == 3:
        return f"Three of a kind, {_rank_plural(values[0])}"

    if score.category == 2:
        return f"Two pair, {_rank_plural(values[0])} and {_rank_plural(values[1])}"

    if score.category == 1:
        return f"Pair of {_rank_plural(values[0])}"

    return f"High card, {_value_to_rank(values[0])}-high"


def _value_to_rank(value: int) -> str:
    rank = _VALUE_TO_RANK[value]
    return "10" if rank == "T" else rank


def _rank_plural(value: int) -> str:
    return _RANK_PLURALS[_VALUE_TO_RANK[value]]


def compare_hands(first: list[Card], second: list[Card]) -> int:
    return _compare_scores(evaluate_best_hand(first), evaluate_best_hand(second))


def parse_opponent_range(text: str) -> list[OpponentHand]:
    normalized = text.strip().upper().replace("10", "T")
    if not normalized or normalized in {"ANY", "ANY TWO", "RANDOM", "ALL"}:
        return all_starting_hands()

    hands: dict[tuple[str, str], OpponentHand] = {}
    tokens = [token for token in re.split(r"[\s,;]+", normalized) if token]

    for token in tokens:
        for hand in _expand_range_token(token):
            key = tuple(sorted((hand[0].key(), hand[1].key())))
            hands[key] = hand

    if not hands:
        raise ValueError("Opponent range did not include any hands.")

    return list(hands.values())


def expand_weighted_range(hand_weights: dict[str, float]) -> tuple[list[OpponentHand], list[float]]:
    """
    Expand hand-class weights into concrete combos.

    Each combo inherits its class weight. Weights should be relative (typically 0–1).
    Classes with non-positive weight are skipped.
    """
    unique_hands: dict[tuple[str, str], tuple[OpponentHand, float]] = {}
    for hand_class, weight in hand_weights.items():
        relative_weight = float(weight)
        if relative_weight <= 0:
            continue
        for hand in _expand_range_token(str(hand_class).strip().upper().replace("10", "T")):
            key = tuple(sorted((hand[0].key(), hand[1].key())))
            unique_hands[key] = (hand, relative_weight)
    if not unique_hands:
        raise ValueError("Opponent range did not include any hands.")
    hands = [entry[0] for entry in unique_hands.values()]
    weights = [entry[1] for entry in unique_hands.values()]
    return hands, weights


def all_starting_hands() -> list[OpponentHand]:
    global _ALL_STARTING_HANDS
    if _ALL_STARTING_HANDS is None:
        _ALL_STARTING_HANDS = tuple(tuple(hand) for hand in combinations(_get_full_deck(), 2))
    return list(_ALL_STARTING_HANDS)


def format_range_size(opponent_range: list[OpponentHand]) -> str:
    percent = len(opponent_range) / len(all_starting_hands())
    return f"{len(opponent_range):,} combos ({percent:.1%})"


def evaluate_call_decision(equity: float, pot_size: float, call_amount: float) -> CallDecision:
    if pot_size < 0:
        raise ValueError("Pot size cannot be negative.")
    if call_amount < 0:
        raise ValueError("Call amount cannot be negative.")

    required_equity = call_amount / (pot_size + call_amount) if call_amount > 0 else 0
    call_ev = equity * (pot_size + call_amount) - call_amount
    recommendation = "Call" if call_ev >= 0 else "Fold"

    return CallDecision(pot_size, call_amount, required_equity, call_ev, recommendation)


def calculate_equity(
    hero_hand: list[Card],
    board: list[Card],
    simulations: int = 25_000,
    exact_max_matchups: int = 75_000,
    rng: RandomFloat | None = None,
    opponent_range: list[OpponentHand] | None = None,
    opponent_weights: list[float] | None = None,
) -> EquityResult:
    _validate_equity_inputs(hero_hand, board)

    started_at = time.perf_counter()
    known_cards = [*hero_hand, *board]
    available_cards = remove_cards(_get_full_deck(), known_cards)
    missing_board_cards = 5 - len(board)
    source_hands = opponent_range or all_starting_hands()
    if opponent_weights is None:
        source_weights = [1.0] * len(source_hands)
    else:
        if len(opponent_weights) != len(source_hands):
            raise ValueError("opponent_weights must match opponent_range length.")
        source_weights = [float(weight) for weight in opponent_weights]

    legal_opponent_hands, legal_weights = _filter_weighted_range(
        source_hands, source_weights, known_cards
    )

    if not legal_opponent_hands:
        raise ValueError("Opponent range has no legal hands after removing known cards.")

    exact_matchups = len(legal_opponent_hands) * math.comb(len(available_cards) - 2, missing_board_cards)

    if exact_matchups <= exact_max_matchups:
        result = _calculate_exact(
            hero_hand,
            board,
            available_cards,
            legal_opponent_hands,
            legal_weights,
            missing_board_cards,
        )
    else:
        result = _calculate_monte_carlo(
            hero_hand,
            board,
            available_cards,
            legal_opponent_hands,
            legal_weights,
            missing_board_cards,
            max(1, int(simulations)),
            rng or random.random,
        )

    return replace(result, runtime_ms=(time.perf_counter() - started_at) * 1000)


def _calculate_exact(
    hero_hand: list[Card],
    board: list[Card],
    available_cards: list[Card],
    legal_opponent_hands: list[OpponentHand],
    legal_weights: list[float],
    missing_board_cards: int,
) -> EquityResult:
    wins = ties = losses = 0.0
    boards_evaluated = 0
    hand_distribution = _empty_hand_distribution()
    opponent_hand_distribution = _empty_opponent_hand_distribution()
    opponent_entries = [
        (
            RANK_VALUE[hand[0].rank],
            _SUIT_INDEX[hand[0].suit],
            RANK_VALUE[hand[1].rank],
            _SUIT_INDEX[hand[1].suit],
            _card_bit(hand[0]) | _card_bit(hand[1]),
            float(weight),
        )
        for hand, weight in zip(legal_opponent_hands, legal_weights)
    ]
    hero_cards = [
        (RANK_VALUE[card.rank], _SUIT_INDEX[card.suit]) for card in hero_hand
    ]
    board_values = [(RANK_VALUE[card.rank], _SUIT_INDEX[card.suit]) for card in board]

    if missing_board_cards == 0:
        board_counts = _counts_from_value_suits(board_values)
        hero_score = _rank_with_extra(board_counts, hero_cards)
        hero_label = HAND_LABELS[hero_score[0]]
        for first_value, first_suit, second_value, second_suit, _, weight in opponent_entries:
            boards_evaluated += 1
            opponent_score = _rank_with_extra(
                board_counts, ((first_value, first_suit), (second_value, second_suit))
            )
            hand_distribution[hero_label] += weight
            opponent_hand_distribution[HAND_CATEGORIES[opponent_score[0]]] += weight
            wins, ties, losses = _add_weighted_result(
                _compare_rank_scores(hero_score, opponent_score), weight, wins, ties, losses
            )
    else:
        for board_runout in combinations(available_cards, missing_board_cards):
            runout_bits = 0
            runout_values = []
            for card in board_runout:
                runout_bits |= _card_bit(card)
                runout_values.append((RANK_VALUE[card.rank], _SUIT_INDEX[card.suit]))

            board_counts = _counts_from_value_suits([*board_values, *runout_values])
            hero_score = _rank_with_extra(board_counts, hero_cards)
            hero_label = HAND_LABELS[hero_score[0]]

            for first_value, first_suit, second_value, second_suit, opponent_bits, weight in opponent_entries:
                if opponent_bits & runout_bits:
                    continue
                boards_evaluated += 1
                opponent_score = _rank_with_extra(
                    board_counts, ((first_value, first_suit), (second_value, second_suit))
                )
                hand_distribution[hero_label] += weight
                opponent_hand_distribution[HAND_CATEGORIES[opponent_score[0]]] += weight
                wins, ties, losses = _add_weighted_result(
                    _compare_rank_scores(hero_score, opponent_score), weight, wins, ties, losses
                )

    return _finalize_equity(
        wins,
        ties,
        losses,
        "exact",
        hero_hand,
        board,
        hand_distribution,
        opponent_hand_distribution,
        boards_evaluated,
        len(legal_opponent_hands),
    )


def _calculate_monte_carlo(
    hero_hand: list[Card],
    board: list[Card],
    available_cards: list[Card],
    legal_opponent_hands: list[OpponentHand],
    legal_weights: list[float],
    missing_board_cards: int,
    simulations: int,
    rng: RandomFloat,
) -> EquityResult:
    wins = ties = losses = 0.0
    hand_distribution = _empty_hand_distribution()
    opponent_hand_distribution = _empty_opponent_hand_distribution()
    available_meta = [
        (card, _card_bit(card), RANK_VALUE[card.rank], _SUIT_INDEX[card.suit])
        for card in available_cards
    ]
    opponent_entries = [
        (
            RANK_VALUE[hand[0].rank],
            _SUIT_INDEX[hand[0].suit],
            RANK_VALUE[hand[1].rank],
            _SUIT_INDEX[hand[1].suit],
            _card_bit(hand[0]) | _card_bit(hand[1]),
        )
        for hand in legal_opponent_hands
    ]
    cumulative_weights, total_weight = _cumulative_weights(legal_weights)
    hero_cards = [(RANK_VALUE[card.rank], _SUIT_INDEX[card.suit]) for card in hero_hand]
    board_values = [(RANK_VALUE[card.rank], _SUIT_INDEX[card.suit]) for card in board]

    for _ in range(simulations):
        opponent_index = _sample_weighted_index(cumulative_weights, total_weight, rng)
        first_value, first_suit, second_value, second_suit, blocked_bits = opponent_entries[opponent_index]
        runout_values = _sample_value_suits(available_meta, missing_board_cards, blocked_bits, rng)
        board_counts = _counts_from_value_suits([*board_values, *runout_values])
        hero_score = _rank_with_extra(board_counts, hero_cards)
        opponent_score = _rank_with_extra(
            board_counts, ((first_value, first_suit), (second_value, second_suit))
        )
        hand_distribution[HAND_LABELS[hero_score[0]]] += 1
        opponent_hand_distribution[HAND_CATEGORIES[opponent_score[0]]] += 1
        wins, ties, losses = _add_weighted_result(
            _compare_rank_scores(hero_score, opponent_score), 1.0, wins, ties, losses
        )

    return _finalize_equity(
        wins,
        ties,
        losses,
        "monte-carlo",
        hero_hand,
        board,
        hand_distribution,
        opponent_hand_distribution,
        simulations,
        simulations,
    )


def _compare_scores(first_score: HandScore, second_score: HandScore) -> int:
    return _compare_rank_scores((first_score.category, first_score.values), (second_score.category, second_score.values))


def _compare_rank_scores(
    first_score: tuple[int, tuple[int, ...]],
    second_score: tuple[int, tuple[int, ...]],
) -> int:
    if first_score > second_score:
        return 1
    if first_score < second_score:
        return -1
    return 0


def _finalize_equity(
    wins: float,
    ties: float,
    losses: float,
    mode: EquityMode,
    hero_hand: list[Card],
    board: list[Card],
    hand_distribution: dict[str, float],
    opponent_hand_distribution: dict[str, float],
    boards_evaluated: int,
    opponent_combinations_evaluated: int,
) -> EquityResult:
    total = wins + ties + losses
    equity = (wins + ties / 2) / total if total else 0
    hero_hand_label = evaluate_best_hand([*hero_hand, *board]).label if len(board) == 5 else "Pending runout"

    return EquityResult(
        wins,
        ties,
        losses,
        total,
        equity,
        mode,
        hero_hand_label,
        hand_distribution,
        opponent_hand_distribution,
        boards_evaluated,
        opponent_combinations_evaluated,
    )


def _card_bit(card: Card) -> int:
    return 1 << (RANK_INDEX[card.rank] * 4 + _SUIT_INDEX[card.suit])


def _sample_value_suits(
    available_meta: list[tuple[Card, int, int, int]],
    count: int,
    blocked_bits: int,
    rng: RandomFloat,
) -> list[tuple[int, int]]:
    if count <= 0:
        return []

    n = len(available_meta)
    chosen: list[tuple[int, int]] = []
    chosen_bits = 0
    while len(chosen) < count:
        index = min(int(rng() * n), n - 1)
        _, bit, value, suit = available_meta[index]
        if bit & blocked_bits or bit & chosen_bits:
            continue
        chosen.append((value, suit))
        chosen_bits |= bit
    return chosen


def _tokenize_cards(text: str) -> list[str]:
    normalized = (
        text.strip()
        .upper()
        .replace("10", "T")
        .replace(",", " ")
        .replace("\n", " ")
        .replace("\t", " ")
        .replace("♣", "C")
        .replace("♦", "D")
        .replace("♥", "H")
        .replace("♠", "S")
    )

    if not normalized:
        return []

    spaced_tokens = [token for token in normalized.split(" ") if token]
    if len(spaced_tokens) > 1:
        return spaced_tokens

    compact = spaced_tokens[0]
    if len(compact) % 2 != 0:
        raise ValueError("Cards must use rank+suit notation, such as Ah Ks or AhKs.")

    return [compact[index : index + 2] for index in range(0, len(compact), 2)]


def _parse_card_token(token: str) -> Card:
    rank = token[:-1]
    suit = token[-1:].lower()

    if rank not in RANKS or suit not in SUITS:
        raise ValueError(f"Invalid card: {token}. Use ranks 2-9, T, J, Q, K, A and suits c, d, h, s.")

    return Card(rank, suit)


def _add_result(result: int, wins: int, ties: int, losses: int) -> tuple[int, int, int]:
    if result > 0:
        wins += 1
    elif result < 0:
        losses += 1
    else:
        ties += 1

    return wins, ties, losses


def _add_weighted_result(
    result: int,
    weight: float,
    wins: float,
    ties: float,
    losses: float,
) -> tuple[float, float, float]:
    if result > 0:
        wins += weight
    elif result < 0:
        losses += weight
    else:
        ties += weight
    return wins, ties, losses


def _cumulative_weights(weights: list[float]) -> tuple[list[float], float]:
    cumulative: list[float] = []
    running = 0.0
    for weight in weights:
        running += max(0.0, float(weight))
        cumulative.append(running)
    if running <= 0:
        raise ValueError("Opponent range weights must sum to a positive value.")
    return cumulative, running


def _sample_weighted_index(cumulative: list[float], total_weight: float, rng: RandomFloat) -> int:
    target = rng() * total_weight
    index = bisect.bisect_left(cumulative, target)
    if index >= len(cumulative):
        return len(cumulative) - 1
    return index


def _validate_equity_inputs(hero_hand: list[Card], board: list[Card]) -> None:
    if len(hero_hand) != 2:
        raise ValueError(f"Hero hand must contain exactly 2 cards, got {len(hero_hand)}.")
    if len(board) > 5:
        raise ValueError("Board cannot contain more than 5 cards.")

    assert_no_duplicates([*hero_hand, *board])


def _expand_range_token(token: str) -> list[OpponentHand]:
    has_plus = token.endswith("+")
    base_token = token[:-1] if has_plus else token
    suitedness: str | None = None

    if len(base_token) >= 3 and base_token[-1] in {"S", "O"}:
        suitedness = base_token[-1].lower()
        base_token = base_token[:-1]

    if len(base_token) != 2:
        raise ValueError(f"Invalid range token: {token}. Examples: AA, TT+, AKs, AJo+.")

    first_rank, second_rank = base_token[0], base_token[1]
    if first_rank not in RANKS or second_rank not in RANKS:
        raise ValueError(f"Invalid range token: {token}. Use ranks 2-9, T, J, Q, K, A.")

    if first_rank == second_rank:
        if suitedness:
            raise ValueError(f"Pairs cannot be marked suited or offsuit: {token}.")
        ranks = RANKS[RANK_INDEX[first_rank] :] if has_plus else (first_rank,)
        return [hand for rank in ranks for hand in _pair_combos(rank)]

    high_rank, low_rank = sorted((first_rank, second_rank), key=lambda rank: RANK_VALUE[rank], reverse=True)
    if has_plus:
        low_ranks = RANKS[RANK_INDEX[low_rank] : RANK_INDEX[high_rank]]
    else:
        low_ranks = (low_rank,)

    if not low_ranks:
        raise ValueError(f"Invalid plus range token: {token}.")

    return [
        hand
        for current_low_rank in low_ranks
        for hand in _unpaired_combos(high_rank, current_low_rank, suitedness)
    ]


def _pair_combos(rank: str) -> list[OpponentHand]:
    return [(Card(rank, first_suit), Card(rank, second_suit)) for first_suit, second_suit in combinations(SUITS, 2)]


def _unpaired_combos(high_rank: str, low_rank: str, suitedness: str | None) -> list[OpponentHand]:
    hands: list[OpponentHand] = []

    for high_suit in SUITS:
        for low_suit in SUITS:
            if suitedness == "s" and high_suit != low_suit:
                continue
            if suitedness == "o" and high_suit == low_suit:
                continue
            hands.append((Card(high_rank, high_suit), Card(low_rank, low_suit)))

    return hands


def _filter_range(opponent_range: list[OpponentHand], blocked_cards: Iterable[Card]) -> list[OpponentHand]:
    blocked = {card.key() for card in blocked_cards}

    return [
        hand
        for hand in opponent_range
        if hand[0].key() not in blocked and hand[1].key() not in blocked and hand[0].key() != hand[1].key()
    ]


def _filter_weighted_range(
    opponent_range: list[OpponentHand],
    weights: list[float],
    blocked_cards: Iterable[Card],
) -> tuple[list[OpponentHand], list[float]]:
    blocked = {card.key() for card in blocked_cards}
    legal_hands: list[OpponentHand] = []
    legal_weights: list[float] = []
    for hand, weight in zip(opponent_range, weights):
        if weight <= 0:
            continue
        if hand[0].key() in blocked or hand[1].key() in blocked or hand[0].key() == hand[1].key():
            continue
        legal_hands.append(hand)
        legal_weights.append(float(weight))
    return legal_hands, legal_weights


def _empty_hand_distribution() -> dict[str, float]:
    return {label: 0.0 for label in HAND_LABELS}


def _empty_opponent_hand_distribution() -> dict[str, float]:
    return {label: 0.0 for label in HAND_CATEGORIES}
