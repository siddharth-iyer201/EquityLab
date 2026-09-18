import { describe, expect, it } from 'vitest';
import { formatCard, parseCards } from './cards';

describe('parseCards', () => {
  it('parses spaced and compact card notation', () => {
    expect(parseCards('Ah Ks').map(formatCard)).toEqual(['AH', 'KS']);
    expect(parseCards('AhKs').map(formatCard)).toEqual(['AH', 'KS']);
    expect(parseCards('10h Jd').map(formatCard)).toEqual(['TH', 'JD']);
  });

  it('rejects duplicate cards', () => {
    expect(() => parseCards('Ah Ah')).toThrow(/Duplicate card/);
  });

  it('validates expected card count', () => {
    expect(() => parseCards('Ah', 2)).toThrow(/Expected 2 cards/);
  });
});
