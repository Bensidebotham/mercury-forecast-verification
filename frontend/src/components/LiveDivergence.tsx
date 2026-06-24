'use client'
import { AlertTriangle } from 'lucide-react'

export type LiveDisagreement = {
  market_uid: string
  venue: string
  city: string
  target_date: string
  question: string
  bucket_lo: number | null
  bucket_hi: number | null
  model_prob: number
  market_prob: number
  edge: number
  lead_hours: number
}

interface LiveDivergenceProps {
  items: LiveDisagreement[]
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n - 1) + '…'
}

function DivergingBar({ modelProb, marketProb }: { modelProb: number; marketProb: number }) {
  const modelPct = Math.round(modelProb * 100)
  const marketPct = Math.round(marketProb * 100)
  const max = Math.max(modelPct, marketPct, 10)

  return (
    <div className="flex flex-col gap-0.5 min-w-[80px]" aria-hidden="true">
      <div className="flex items-center gap-1.5">
        <div className="w-14 flex justify-end">
          <div
            className="h-2 rounded-sm bg-[#3B82F6]"
            style={{ width: `${(modelPct / max) * 56}px` }}
          />
        </div>
        <span className="font-mono text-[10px] tabular-nums text-[#3B82F6] w-8">{modelPct}%</span>
      </div>
      <div className="flex items-center gap-1.5">
        <div className="w-14 flex justify-end">
          <div
            className="h-2 rounded-sm bg-[#D97706]"
            style={{ width: `${(marketPct / max) * 56}px` }}
          />
        </div>
        <span className="font-mono text-[10px] tabular-nums text-[#D97706] w-8">{marketPct}%</span>
      </div>
    </div>
  )
}

function EdgeBadge({ edge }: { edge: number }) {
  const abs = Math.abs(edge)
  const modelAhead = edge > 0
  const label = modelAhead
    ? `model +${abs.toFixed(2)}`
    : `market +${abs.toFixed(2)}`
  const color = modelAhead ? 'text-[#3B82F6]' : 'text-[#D97706]'
  const bg = modelAhead ? 'bg-blue-950/60 border-blue-800' : 'bg-amber-950/60 border-amber-800'

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold border tabular-nums ${color} ${bg}`}
    >
      {label}
    </span>
  )
}

export default function LiveDivergence({ items }: LiveDivergenceProps) {
  const top = items.slice(0, 12)

  return (
    <section
      className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl overflow-hidden mb-8"
      aria-labelledby="live-div-heading"
    >
      <div className="px-6 pt-5 pb-3 border-b border-[var(--color-border)]">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="w-4 h-4 text-[#D97706] mt-0.5 shrink-0"
            aria-hidden="true"
          />
          <div>
            <h2
              id="live-div-heading"
              className="text-sm font-semibold uppercase tracking-widest text-[var(--color-muted)]"
            >
              Where the model disagrees with the market — right now
            </h2>
            <p className="text-xs text-[var(--color-muted)] mt-1 leading-relaxed">
              Open markets (not yet settled), ranked by the gap between the model&apos;s probability
              and the market&apos;s implied probability.
            </p>
          </div>
        </div>
      </div>

      {top.length === 0 ? (
        <div className="px-6 py-10 text-center text-sm text-[var(--color-muted)]">
          No open markets with paired snapshots right now — the next ingest cycle will refresh this.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)]">
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-[var(--color-muted)]">
                  City
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-[var(--color-muted)]">
                  Question
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-[var(--color-muted)]">
                  Model vs Market
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-[var(--color-muted)]">
                  Edge
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-[var(--color-muted)]">
                  Lead
                </th>
              </tr>
            </thead>
            <tbody>
              {top.map((item) => (
                <tr
                  key={item.market_uid}
                  className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-border)] transition-colors duration-150 motion-reduce:transition-none"
                >
                  <td className="px-4 py-3 text-[var(--color-text)] font-medium whitespace-nowrap">
                    {item.city}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)] max-w-[280px]">
                    <span title={item.question}>{truncate(item.question, 60)}</span>
                  </td>
                  <td className="px-4 py-3">
                    <DivergingBar modelProb={item.model_prob} marketProb={item.market_prob} />
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <EdgeBadge edge={item.edge} />
                  </td>
                  <td className="px-4 py-3 font-mono tabular-nums text-[var(--color-muted)] whitespace-nowrap">
                    {item.lead_hours.toFixed(1)}h
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
