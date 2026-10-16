import type { Backtest } from '@/lib/types'
import { REPO_URL } from './Header'

export default function Method({ backtest }: { backtest: Backtest | null }) {
  const agree = backtest?.data_quality.kalshi_cli_agreement
  return (
    <section className="text-sm text-[var(--color-muted)] leading-relaxed mb-8 max-w-3xl">
      <h2 className="text-base font-semibold text-[var(--color-text)] mb-2">How this is measured</h2>
      <ul className="list-disc pl-5 space-y-1.5">
        <li>
          <strong className="text-[var(--color-text)]">Model.</strong> The mean of GFS and ECMWF deterministic
          forecasts, made one or two days earlier, plus a per-station bias, with a Normal error whose width was fit
          on {backtest ? `${backtest.train_window[0]} to ${backtest.train_window[1]}` : 'a training window'} only.
        </li>
        <li>
          <strong className="text-[var(--color-text)]">No look-ahead.</strong> Scores are taken at fixed local times
          (noon the day before, 08:00 on the day), using only forecasts and prices that existed by then.
        </li>
        <li>
          <strong className="text-[var(--color-text)]">Unit of analysis.</strong> One city-day ladder, scored as a whole.
          Market prices are normalized across the ladder. Intervals resample city-days.
        </li>
        <li>
          <strong className="text-[var(--color-text)]">Pre-registered.</strong> The protocol was committed before the
          test window was scored. <a className="underline hover:text-[var(--color-text)]" href={`${REPO_URL}/blob/main/docs/PROTOCOL.md`}>Read it</a>.
        </li>
        <li>
          <strong className="text-[var(--color-text)]">Caveats.</strong> Polymarket history has a trade price rather than
          a bid/ask and starts later (NYC Jan 2025; other cities Dec 2025 or Mar 2026). Kalshi moved its settlement source
          to The Weather Company around Aug 2026; scores use each venue&apos;s own result
          {agree?.rate != null ? `, and the NWS daily high matched Kalshi's winning bucket on ${agree.agree} of ${agree.n} test days` : ''}.
        </li>
      </ul>
    </section>
  )
}
