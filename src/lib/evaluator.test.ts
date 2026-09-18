import { describe, expect, it } from 'vitest';
import { parseCards } from './cards';
import { compareHands, evaluateBestHand } from './evaluator';

describe('evaluateBestHand', () => {
  it('recognizes a royal flush as a straight flush', () => {
    const score = evaluateBestHand(parseCards('As Ks Qs Js Ts 2d 3c'));

    expect(score.label).toBe('Straight flush');
    expect(score.values).toEqual([14]);
  });

  it('supports ace-low straights', () => {
    const score = evaluateBestHand(parseCards('Ah 2d 3s 4c 5h Kd Qs'));

    expect(score.label).toBe('Straight');
    expect(score.values).toEqual([5]);
  });

  it('compares full houses by trips first', () => {
    const acesFull = parseCards('Ah Ad As Kc Kd 2c 3d');
    const kingsFull = parseCards('Kh Kd Ks Ac Ad 2c 3d');

    expect(compareHands(acesFull, kingsFull)).toBeGreaterThan(0);
  });
});
