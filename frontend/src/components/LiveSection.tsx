import type { Dashboard } from '@/lib/types'
import { VENUE_LABEL, ago, pct } from '@/lib/format'

function bucket(lo: number | null, hi: number | null): string {
  if (lo === null && hi !== null) return `≤${hi}°F`
  if (hi === null && lo !== null) return `≥${lo}°F`
  return lo === hi ? `${lo}°F` : `${lo}–${hi}°F`
}

/** Forward tracking: pipeline health plus where the live ensemble model and the market disagree now. */
export default function LiveSection({ data }: { data: Dashboard }) {
  const { tracking, live_disagreements: rows } = data
  const run = tracking.last_run
  const forward = Object.entries(data.live.scores).map(([venue, s]) => `${VENUE_LABEL[venue] ?? venue} ${s.n_events}`)
  return (
    <section className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl mb-8">
      <div className="px-6 pt-5">
        <h2 className="text-base font-semibold text-[var(--color-text)]">Live tracking</h2>
        <p className="text-xs text-[var(--color-muted)] mt-1 max-w-2xl">
          Every hour the pipeline snapshots open markets and a live ensemble model (GFS + ECMWF members, which
          have no archive and so can only be scored going forward). Settled city-days scored so far:{' '}
          {forward.join(' · ')}.
        </p>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4 text-sm">
          {[
            ['Last run', run ? `${run.status} · ${ago(run.started_ts)}` : '—'],
            ['Markets tracked', tracking.n_markets.toLocaleString()],
            ['Open now', tracking.n_open.toLocaleString()],
            ['Live price snapshots', tracking.n_live_quotes.toLocaleString()],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs text-[var(--color-muted)]">{k}</dt>
              <dd className="text-[var(--color-text)] tabular-nums mt-0.5">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
      {rows.length > 0 && (
        <div className="overflow-x-auto mt-5">
          <table className="w-full text-sm tabular-nums">
            <caption className="text-left text-xs text-[var(--color-muted)] px-6 pb-2">
              Largest current disagreements between the live model and the market
            </caption>
            <thead>
              <tr className="text-xs text-[var(--color-muted)] text-left border-y border-[var(--color-border)]">
                {['Venue', 'City', 'Date', 'Bucket', 'Model', 'Market', 'Hours to close'].map((h, i) => (
                  <th key={h} className={`font-normal px-6 py-2 ${i > 3 ? 'text-right' : ''}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 10).map((r) => (
                <tr key={r.market_uid} className="border-b border-[var(--color-border)] last:border-0">
                  <td className="px-6 py-2 text-[var(--color-muted)]">{VENUE_LABEL[r.venue] ?? r.venue}</td>
                  <td className="px-6 py-2 text-[var(--color-text)]">{r.city}</td>
                  <td className="px-6 py-2 text-[var(--color-muted)]">{r.target_date}</td>
                  <td className="px-6 py-2 text-[var(--color-text)]">{bucket(r.bucket_lo, r.bucket_hi)}</td>
                  <td className="px-6 py-2 text-right text-[var(--color-text)]">{pct(r.model_prob)}</td>
                  <td className="px-6 py-2 text-right text-[var(--color-text)]">{pct(r.market_prob)}</td>
                  <td className="px-6 py-2 text-right text-[var(--color-muted)]">{r.lead_hours.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="pb-5" />
    </section>
  )
}
