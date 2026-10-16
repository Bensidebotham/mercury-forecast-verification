import type { Backtest } from '@/lib/types'
import { VENUE_LABEL, monthSpan, num, signed, totalEvents } from '@/lib/format'

/** One card per venue: scored city-days, then model vs market Brier at each lead point. */
export default function Headline({ backtest }: { backtest: Backtest }) {
  return (
    <section aria-label="Headline results" className="grid gap-4 sm:grid-cols-2 mb-8">
      {Object.entries(backtest.venues).filter(([, v]) => v.summary.length).map(([venue, v]) => (
        <div key={venue} className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-base font-semibold text-[var(--color-text)]">{VENUE_LABEL[venue] ?? venue}</h2>
            <span className="text-xs text-[var(--color-muted)]">
              {totalEvents(v).toLocaleString()} city-days{v.date_span ? ` · ${monthSpan(v.date_span)}` : ''}
            </span>
          </div>
          <table className="w-full mt-3 text-sm tabular-nums">
            <thead>
              <tr className="text-xs text-[var(--color-muted)] text-left">
                <th className="font-normal py-1">Lead</th>
                <th className="font-normal py-1 text-right"><span className="text-[var(--color-model)]">●</span> Model</th>
                <th className="font-normal py-1 text-right"><span className="text-[var(--color-market)]">●</span> Market</th>
                <th className="font-normal py-1 text-right">Diff [95% CI]</th>
              </tr>
            </thead>
            <tbody>
              {v.summary.map((r) => (
                <tr key={r.lead} className="border-t border-[var(--color-border)]">
                  <td className="py-2 text-[var(--color-text)]">{r.lead}</td>
                  <td className="py-2 text-right text-[var(--color-text)]">{num(r.model_brier)}</td>
                  <td className="py-2 text-right text-[var(--color-text)]">{num(r.market_brier)}</td>
                  <td className="py-2 text-right text-[var(--color-muted)]">
                    {signed(r.brier_diff)} [{signed(r.brier_diff_ci[0])}, {signed(r.brier_diff_ci[1])}]
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-[var(--color-muted)] mt-3">
            Multi-bucket Brier score per city-day; lower is better.
          </p>
        </div>
      ))}
    </section>
  )
}
