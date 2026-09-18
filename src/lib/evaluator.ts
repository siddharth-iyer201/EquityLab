
export const HAND_CATEGORIES = [
  'High card',
  'One pair',
  'Two pair',
  'Three of a kind',
  'Straight',
  'Flush',
  'Full house',
  'Four of a kind',
  'Straight flush',
] as const;

export type HandCategory = (typeof HAND_CATEGORIES)[number];

export type HandScore = {
  category: number;
  values: number[];
  label: HandCategory;
};

type ValueGroup = {
  value: number;
  count: number;
};

export function evaluateBestHand(cards: Card[]): HandScore {
  if (cards.length < 5 || cards.length > 7) {
    throw new Error(`Expected 5 to 7 cards, got ${cards.length}.`);
  }

  let best: HandScore | null = null;

  for (const combo of combinations(cards, 5)) {
    const score = evaluateFiveCardHand(combo);
    if (!best || compareScores(score, best) > 0) {
      best = score;
    }
  }

  if (!best) {
    throw new Error('Unable to evaluate hand.');
  }

  return best;
}

export function compareHands(first: Card[], second: Card[]): number {
  return compareScores(evaluateBestHand(first), evaluateBestHand(second));
}

export function compareScores(first: HandScore, second: HandScore): number {
  if (first.category !== second.category) {
    return first.category - second.category;
  }

  const valueCount = Math.max(first.values.length, second.values.length);
  for (let index = 0; index < valueCount; index += 1) {
    const firstValue = first.values[index] ?? 0;
    const secondValue = second.values[index] ?? 0;
    if (firstValue !== secondValue) {
      return firstValue - secondValue;
    }
  }

  return 0;
}

function evaluateFiveCardHand(cards: Card[]): HandScore {
  if (cards.length !== 5) {
    throw new Error(`Expected 5 cards, got ${cards.length}.`);
  }

  const values = cards.map((card) => RANK_VALUE[card.rank]).sort(descending);
  const flush = cards.every((card) => card.suit === cards[0]?.suit);
  const straightHigh = getStraightHigh(values);
  const groups = groupValues(values);

  if (straightHigh && flush) {
    return score(8, [straightHigh]);
  }

  const four = groups.find((group) => group.count === 4);
  if (four) {
    return score(7, [four.value, ...values.filter((value) => value !== four.value)]);
  }

  const trips = groups.filter((group) => group.count === 3);
  const pairs = groups.filter((group) => group.count === 2);

  const firstTrips = trips[0];
  const firstPair = pairs[0];
  if (firstTrips && firstPair) {
    return score(6, [firstTrips.value, firstPair.value]);
  }

  if (flush) {
    return score(5, values);
  }

  if (straightHigh) {
    return score(4, [straightHigh]);
  }

  if (firstTrips) {
    return score(3, [firstTrips.value, ...values.filter((value) => value !== firstTrips.value)]);
  }

  if (pairs.length >= 2) {
    const pairValues = pairs.map((group) => group.value).sort(descending);
    const kicker = values.find((value) => !pairValues.includes(value));
    return score(2, [...pairValues, kicker ?? 0]);
  }

  if (firstPair) {
    return score(1, [firstPair.value, ...values.filter((value) => value !== firstPair.value)]);
  }

  return score(0, values);
}

function score(category: number, values: number[]): HandScore {
  const label = HAND_CATEGORIES[category];
  if (!label) {
    throw new Error(`Unknown hand category: ${category}.`);
  }

  return { category, values, label };
}

function groupValues(values: number[]): ValueGroup[] {
  const counts = new Map<number, number>();

  for (const value of values) {
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }

  return Array.from(counts.entries())
    .map(([value, count]) => ({ value, count }))
    .sort((first, second) => second.count - first.count || second.value - first.value);
}

function getStraightHigh(values: number[]): number | null {
  const unique = Array.from(new Set(values)).sort(descending);
  if (unique.includes(14)) {
    unique.push(1);
  }

  for (let index = 0; index <= unique.length - 5; index += 1) {
    const high = unique[index];
    if (high === undefined) {
      continue;
    }

    const isStraight = [0, 1, 2, 3, 4].every((offset) => unique[index + offset] === high - offset);
    if (isStraight) {
      return high;
    }
  }

  return null;
}

function combinations<T>(items: T[], size: number): T[][] {
  if (size === 0) {
    return [[]];
  }

  if (items.length < size) {
    return [];
  }

  const result: T[][] = [];

  for (let index = 0; index <= items.length - size; index += 1) {
    const item = items[index];
    if (item === undefined) {
      continue;
    }

    for (const rest of combinations(items.slice(index + 1), size - 1)) {
      result.push([item, ...rest]);
    }
  }

  return result;
}

function descending(first: number, second: number): number {
  return second - first;
}
import { type Card, RANK_VALUE } from './cards.ts';
