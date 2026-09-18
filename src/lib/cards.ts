export const RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A'] as const;
export const SUITS = ['c', 'd', 'h', 's'] as const;

export type Rank = (typeof RANKS)[number];
export type Suit = (typeof SUITS)[number];

export type Card = {
  rank: Rank;
  suit: Suit;
};

export const RANK_VALUE: Record<Rank, number> = {
  '2': 2,
  '3': 3,
  '4': 4,
  '5': 5,
  '6': 6,
  '7': 7,
  '8': 8,
  '9': 9,
  T: 10,
  J: 11,
  Q: 12,
  K: 13,
  A: 14,
};

const RANK_ALIASES: Record<string, Rank> = {
  '2': '2',
  '3': '3',
  '4': '4',
  '5': '5',
  '6': '6',
  '7': '7',
  '8': '8',
  '9': '9',
  T: 'T',
  J: 'J',
  Q: 'Q',
  K: 'K',
  A: 'A',
};

const SUIT_ALIASES: Record<string, Suit> = {
  C: 'c',
  CLUB: 'c',
  CLUBS: 'c',
  D: 'd',
  DIAMOND: 'd',
  DIAMONDS: 'd',
  H: 'h',
  HEART: 'h',
  HEARTS: 'h',
  S: 's',
  SPADE: 's',
  SPADES: 's',
};

export function cardKey(card: Card): string {
  return `${card.rank}${card.suit}`;
}

export function formatCard(card: Card): string {
  return cardKey(card).toUpperCase();
}

export function fullDeck(): Card[] {
  return SUITS.flatMap((suit) => RANKS.map((rank) => ({ rank, suit })));
}

export function removeCards(deck: Card[], cardsToRemove: Card[]): Card[] {
  const removed = new Set(cardsToRemove.map(cardKey));
  return deck.filter((card) => !removed.has(cardKey(card)));
}

export function assertNoDuplicates(cards: Card[]): void {
  const seen = new Set<string>();

  for (const card of cards) {
    const key = cardKey(card);
    if (seen.has(key)) {
      throw new Error(`Duplicate card: ${formatCard(card)}`);
    }
    seen.add(key);
  }
}

export function parseCards(input: string, expectedCount?: number): Card[] {
  const cards = tokenizeCards(input).map(parseCardToken);

  if (expectedCount !== undefined && cards.length !== expectedCount) {
    throw new Error(`Expected ${expectedCount} card${expectedCount === 1 ? '' : 's'}, got ${cards.length}.`);
  }

  assertNoDuplicates(cards);
  return cards;
}

function tokenizeCards(input: string): string[] {
  const normalized = input
    .trim()
    .toUpperCase()
    .replace(/10/g, 'T')
    .replace(/[,\n\t]+/g, ' ')
    .replace(/[♣]/g, 'C')
    .replace(/[♦]/g, 'D')
    .replace(/[♥]/g, 'H')
    .replace(/[♠]/g, 'S');

  if (normalized.length === 0) {
    return [];
  }

  const spaced = normalized.split(/\s+/).filter(Boolean);
  if (spaced.length > 1) {
    return spaced;
  }

  const compact = spaced[0];
  if (!compact || compact.length % 2 !== 0) {
    throw new Error('Cards must use rank+suit notation, such as Ah Ks or AhKs.');
  }

  const tokens: string[] = [];
  for (let index = 0; index < compact.length; index += 2) {
    tokens.push(compact.slice(index, index + 2));
  }

  return tokens;
}

function parseCardToken(token: string): Card {
  const rankText = token.slice(0, -1);
  const suitText = token.slice(-1);
  const rank = RANK_ALIASES[rankText];
  const suit = SUIT_ALIASES[suitText];

  if (!rank || !suit) {
    throw new Error(`Invalid card: ${token}. Use ranks 2-9, T, J, Q, K, A and suits c, d, h, s.`);
  }

  return { rank, suit };
}
