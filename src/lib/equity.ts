
export type EquityMode = 'exact' | 'monte-carlo';

export type EquityOptions = {
  simulations?: number;
  exactMaxMatchups?: number;
  rng?: () => number;
};

export type EquityResult = {
  wins: number;
  ties: number;
  losses: number;
  total: number;
  equity: number;
  mode: EquityMode;
  heroHandLabel: string;
};

const DEFAULT_SIMULATIONS = 25_000;
const DEFAULT_EXACT_MAX_MATCHUPS = 1_500_000;

export function calculateEquity(heroHand: Card[], board: Card[], options: EquityOptions = {}): EquityResult {
  validateInputs(heroHand, board);

  const knownCards = [...heroHand, ...board];
  const availableCards = removeCards(fullDeck(), knownCards);
  const missingBoardCards = 5 - board.length;
  const exactMatchups = combinationCount(availableCards.length, missingBoardCards) * combinationCount(availableCards.length - missingBoardCards, 2);
  const exactMaxMatchups = options.exactMaxMatchups ?? DEFAULT_EXACT_MAX_MATCHUPS;

  if (exactMatchups <= exactMaxMatchups) {
    return calculateExact(heroHand, board, availableCards, missingBoardCards);
  }

  return calculateMonteCarlo(heroHand, board, availableCards, missingBoardCards, {
    rng: options.rng ?? Math.random,
  });
}

export function createSeededRng(seed: number): () => number {
  let state = seed >>> 0;

  return () => {
    state = (1664525 * state + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

function calculateExact(heroHand: Card[], board: Card[], availableCards: Card[], missingBoardCards: number): EquityResult {
  const tally = createTally();

  for (const boardRunout of combinations(availableCards, missingBoardCards)) {
    const completedBoard = [...board, ...boardRunout];
    const opponentDeck = removeCards(availableCards, boardRunout);

    for (const opponentHand of combinations(opponentDeck, 2)) {
      tallyMatchup(tally, heroHand, opponentHand, completedBoard);
    }
  }

  return finalizeTally(tally, 'exact', heroHand, board);
}

function calculateMonteCarlo(
  heroHand: Card[],
  board: Card[],
  availableCards: Card[],
  missingBoardCards: number,
  options: Required<Pick<EquityOptions, 'simulations' | 'rng'>>,
): EquityResult {
  const tally = createTally();

  for (let trial = 0; trial < options.simulations; trial += 1) {
    const shuffledDeck = shuffle(availableCards, options.rng);
    const boardRunout = shuffledDeck.slice(0, missingBoardCards);
    const opponentHand = shuffledDeck.slice(missingBoardCards, missingBoardCards + 2);
    tallyMatchup(tally, heroHand, opponentHand, [...board, ...boardRunout]);
  }

  return finalizeTally(tally, 'monte-carlo', heroHand, board);
}

function tallyMatchup(tally: Tally, heroHand: Card[], opponentHand: Card[], completedBoard: Card[]): void {
  const comparison = compareHands([...heroHand, ...completedBoard], [...opponentHand, ...completedBoard]);

  if (comparison > 0) {
    tally.wins += 1;
  } else if (comparison < 0) {
    tally.losses += 1;
  } else {
    tally.ties += 1;
  }
}

function finalizeTally(tally: Tally, mode: EquityMode, heroHand: Card[], board: Card[]): EquityResult {
  const total = tally.wins + tally.ties + tally.losses;
  const equity = total === 0 ? 0 : (tally.wins + tally.ties / 2) / total;
  const heroHandLabel = board.length === 5 ? evaluateBestHand([...heroHand, ...board]).label : 'Pending runout';

  return {
    wins: tally.wins,
    ties: tally.ties,
    losses: tally.losses,
    total,
    equity,
    mode,
    heroHandLabel,
  };
}

function validateInputs(heroHand: Card[], board: Card[]): void {
  if (heroHand.length !== 2) {
    throw new Error(`Hero hand must contain exactly 2 cards, got ${heroHand.length}.`);
  }

  if (![0, 3, 4, 5].includes(board.length)) {
    throw new Error('Board must be empty or contain 3, 4, or 5 cards.');
  }

  assertNoDuplicates([...heroHand, ...board]);
}

type Tally = {
  wins: number;
  ties: number;
  losses: number;
};

function createTally(): Tally {
  return {
    wins: 0,
    ties: 0,
    losses: 0,
  };
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

function shuffle<T>(items: T[], rng: () => number): T[] {
  const shuffled = [...items];

  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(rng() * (index + 1));
    const current = shuffled[index];
    const swap = shuffled[swapIndex];

    if (current !== undefined && swap !== undefined) {
      shuffled[index] = swap;
      shuffled[swapIndex] = current;
    }
  }

  return shuffled;
}

function combinationCount(total: number, choose: number): number {
  if (choose < 0 || total < choose) {
    return 0;
  }

  if (choose === 0 || choose === total) {
    return 1;
  }

  const smallerChoose = Math.min(choose, total - choose);
  let numerator = 1;
  let denominator = 1;

  for (let index = 1; index <= smallerChoose; index += 1) {
    numerator *= total - smallerChoose + index;
    denominator *= index;
  }

  return numerator / denominator;
}
    simulations: normalizeSimulationCount(options.simulations),

function normalizeSimulationCount(simulations: number | undefined): number {
  if (simulations === undefined || !Number.isFinite(simulations)) {
    return DEFAULT_SIMULATIONS;
  }

  return Math.max(1, Math.floor(simulations));
}
import { assertNoDuplicates, type Card, fullDeck, removeCards } from './cards.ts';
import { compareHands, evaluateBestHand } from './evaluator.ts';
