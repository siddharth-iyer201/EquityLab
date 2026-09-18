import { type FormEvent, useState } from 'react';
import { calculateEquity, type EquityResult } from './lib/equity';

type CalculationState =
  | {
      status: 'idle';
    }
  | {
      status: 'error';
      message: string;
    }
  | {
      status: 'success';
      result: EquityResult;
    };

const EXAMPLE_HANDS = ['Ah Kh', 'Qs Qd', '7c 6c'];
const EXAMPLE_BOARDS = ['As Ts 2d', 'Ah Kd Qs Jc', '2h 7d Tc Js 4c'];

export default function App() {
  const [heroInput, setHeroInput] = useState('Ah Kh');
  const [boardInput, setBoardInput] = useState('');
  const [simulations, setSimulations] = useState(25_000);
  const [calculation, setCalculation] = useState<CalculationState>({ status: 'idle' });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      const heroHand = parseCards(heroInput, 2);
      const board = boardInput.trim() ? parseCards(boardInput) : [];
      const result = calculateEquity(heroHand, board, { simulations });
      setCalculation({ status: 'success', result });
    } catch (error) {
      setCalculation({
        status: 'error',
        message: error instanceof Error ? error.message : 'Unable to calculate equity.',
      });
    }
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Texas Hold'em</p>
        <h1>Calculate heads-up poker equity.</h1>
        <p className="lede">
          Enter your two hole cards and an optional board to estimate your equity against one random opponent.
          River, turn, and flop-sized searches run exactly when practical; preflop uses Monte Carlo simulation.
        </p>
      </section>

      <section className="calculator-card">
        <form onSubmit={handleSubmit} className="calculator-form">
          <label>
            <span>Hero hand</span>
            <input
              value={heroInput}
              onChange={(event) => setHeroInput(event.target.value)}
              placeholder="Ah Kh"
              autoComplete="off"
            />
          </label>

          <label>
            <span>Board (optional)</span>
            <input
              value={boardInput}
              onChange={(event) => setBoardInput(event.target.value)}
              placeholder="As Ts 2d"
              autoComplete="off"
            />
          </label>

          <label>
            <span>Monte Carlo trials</span>
            <input
              type="number"
              min={1_000}
              max={200_000}
              step={1_000}
              value={simulations}
              onChange={(event) => setSimulations(Number(event.target.value))}
            />
          </label>

          <button type="submit">Calculate equity</button>
        </form>

        <aside className="help-panel">
          <h2>Input format</h2>
          <p>Use rank+suit notation. Ranks are 2-9, T, J, Q, K, A. Suits are c, d, h, s.</p>
          <p>
            Hands: {EXAMPLE_HANDS.join(' | ')}
            <br />
            Boards: {EXAMPLE_BOARDS.join(' | ')}
          </p>
        </aside>
      </section>

      <ResultPanel calculation={calculation} />
    </main>
  );
}

function ResultPanel({ calculation }: { calculation: CalculationState }) {
  if (calculation.status === 'idle') {
    return (
      <section className="results-card muted">
        <h2>Ready when you are</h2>
        <p>Add cards and run a calculation to see win, tie, loss, and total equity.</p>
      </section>
    );
  }

  if (calculation.status === 'error') {
    return (
      <section className="results-card error">
        <h2>Check your cards</h2>
        <p>{calculation.message}</p>
      </section>
    );
  }

  const { result } = calculation;

  return (
    <section className="results-card">
      <div className="results-heading">
        <div>
          <p className="eyebrow">Equity</p>
          <h2>{formatPercent(result.equity)}</h2>
        </div>
        <span className="mode-pill">{result.mode === 'exact' ? 'Exact enumeration' : 'Monte Carlo'}</span>
      </div>

      <div className="stat-grid">
        <Stat label="Win" value={formatPercent(result.wins / result.total)} />
        <Stat label="Tie" value={formatPercent(result.ties / result.total)} />
        <Stat label="Loss" value={formatPercent(result.losses / result.total)} />
        <Stat label="Matchups" value={result.total.toLocaleString()} />
      </div>

      <p className="result-note">
        Hero made hand: {result.heroHandLabel}. Equity counts ties as half a win.
      </p>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat('en', {
    style: 'percent',
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value);
}
import { parseCards } from './lib/cards';
