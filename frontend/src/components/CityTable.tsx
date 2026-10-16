import type { Backtest } from '@/lib/types'
import { VENUE_LABEL, num } from '@/lib/format'

export default function CityTable({ backtest }: { backtest: Backtest }) {
  const rows = Object.entries(backtest.venues).flatMap(([venue, v]) => v.by_city.map((c) => ({ venue, ...c })))
  if (!rows.length) return null
  return (
    <section className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl mb-8 overflow-x-auto">
      <h2 className="text-base font-semibold text-[var(--color-text)] px-6 pt-5">By city</h2>
      <p className="text-xs text-[var(--color-muted)] px-6 mt-1">
        Shown for context only; the headline uses the pooled result, not the best city.
      </p>
      <table className="w-full text-sm tabular-nums mt-3">
        <thead>
          <tr className="text-xs text-[var(--color-muted)] text-left border-b border-[var(--color-border)]">
            {['Venue', 'City', 'Lead', 'City-days', 'Model Brier', 'Market Brier'].map((h, i) => (
              <th key={h} className={`font-normal px-6 py-2 ${i > 2 ? 'text-right' : ''}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.venue}-${r.city}-${r.lead}`} className="border-b border-[var(--color-border)] last:border-0">
              <td className="px-6 py-2 text-[var(--color-muted)]">{VENUE_LABEL[r.venue] ?? r.venue}</td>
              <td className="px-6 py-2 text-[var(--color-text)]">{r.city}</td>
              <td className="px-6 py-2 text-[var(--color-muted)]">{r.lead}</td>
              <td className="px-6 py-2 text-right text-[var(--color-muted)]">{r.n_events}</td>
              <td className="px-6 py-2 text-right text-[var(--color-text)]">{num(r.model_brier)}</td>
              <td className="px-6 py-2 text-right text-[var(--color-text)]">{num(r.market_brier)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
