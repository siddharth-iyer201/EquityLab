import { describe, expect, it } from 'vitest';
import { parseCards } from './cards';
import { calculateEquity, createSeededRng } from './equity';

describe('calculateEquity', () => {
  it('uses exact enumeration on a complete board', () => {
    const result = calculateEquity(parseCards('As Ks'), parseCards('Qs Js Ts 2d 3c'));

    expect(result.mode).toBe('exact');
    expect(result.equity).toBe(1);
    expect(result.losses).toBe(0);
  });

  it('uses Monte Carlo when exact enumeration is too large', () => {
    const result = calculateEquity(parseCards('Qs Qd'), [], {
      simulations: 500,
      exactMaxMatchups: 0,
      rng: createSeededRng(7),
    });

    expect(result.mode).toBe('monte-carlo');
    expect(result.total).toBe(500);
    expect(result.equity).toBeGreaterThan(0.6);
    expect(result.equity).toBeLessThan(0.9);
  });

  it('rejects invalid partial boards', () => {
    expect(() => calculateEquity(parseCards('Ah Kh'), parseCards('2c'))).toThrow(/Board must be empty/);
  });
});
