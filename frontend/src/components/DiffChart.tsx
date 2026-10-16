'use client'
import { useState } from 'react'
import type { Summary } from '@/lib/types'
import { VENUE_LABEL, num, signed } from '@/lib/format'

type Metric = 'brier' | 'rps' | 'logscore'
const METRICS: { key: Metric; label: string }[] = [
  { key: 'brier', label: 'Brier' },
  { key: 'rps', label: 'RPS' },
  { key: 'logscore', label: 'Log score' },
]

type Row = { venue: string; s: Summary }

const W = 640
const ROW_H = 44
const LEFT = 170
const RIGHT = 24
const TOP = 28

/** Model − market score difference per venue and lead, with its 95% bootstrap interval. */
export default function DiffChart({ rows, windowLabel }: { rows: Row[]; windowLabel: string }) {
  const [metric, setMetric] = useState<Metric>('brier')
  const [hover, setHover] = useState<number | null>(null)
  if (!rows.length) return null

  const diff = (r: Row) => r.s[`${metric}_diff`] as number
  const ci = (r: Row) => r.s[`${metric}_diff_ci`] as [number, number]
  const extent = Math.max(0.01, ...rows.flatMap((r) => ci(r).map(Math.abs))) * 1.15
  const H = TOP + rows.length * ROW_H + 30
  const x = (v: number) => LEFT + ((v + extent) / (2 * extent)) * (W - LEFT - RIGHT)
  const ticks = [-extent, -extent / 2, 0, extent / 2, extent].map((t) => +t.toPrecision(2))

  return (
    <figure className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6 mb-8">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
        <figcaption>
          <h2 className="text-base font-semibold text-[var(--color-text)]">Model minus market, {windowLabel}</h2>
          <p className="text-xs text-[var(--color-muted)] mt-1 max-w-xl">
            Mean per-event score difference with a 95% paired bootstrap interval. Lower scores are better, so
            a point left of zero means the model was more accurate; right of zero, the market.
          </p>
        </figcaption>
        <div role="radiogroup" aria-label="Score" className="flex gap-1 text-xs">
          {METRICS.map((m) => (
            <button
              key={m.key}
              role="radio"
              aria-checked={metric === m.key}
              onClick={() => setMetric(m.key)}
              className={`px-3 py-1 rounded-full border transition-colors ${
                metric === m.key
                  ? 'border-[var(--color-text)] text-[var(--color-text)]'
                  : 'border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-text)]'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
             aria-label="Dot and interval chart of model minus market score differences">
          <text x={x(-extent)} y={14} fill="var(--color-model)" fontSize={11}>← model better</text>
          <text x={x(extent)} y={14} fill="var(--color-market)" fontSize={11} textAnchor="end">market better →</text>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={TOP - 6} y2={H - 26}
                    stroke={t === 0 ? 'var(--color-muted)' : 'var(--color-border)'} strokeWidth={t === 0 ? 1.5 : 1} />
              <text x={x(t)} y={H - 10} fill="var(--color-muted)" fontSize={11} textAnchor="middle">
                {t === 0 ? '0' : signed(t, 2)}
              </text>
            </g>
          ))}
          {rows.map((r, i) => {
            const y = TOP + i * ROW_H + ROW_H / 2
            const [lo, hi] = ci(r)
            const color = hi < 0 ? 'var(--color-model)' : lo > 0 ? 'var(--color-market)' : 'var(--color-muted)'
            return (
              <g key={`${r.venue}-${r.s.lead}`} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect x={0} y={y - ROW_H / 2} width={W} height={ROW_H} fill={hover === i ? 'var(--color-border)' : 'transparent'} opacity={0.4} />
                <text x={8} y={y - 3} fill="var(--color-text)" fontSize={13}>{VENUE_LABEL[r.venue] ?? r.venue}</text>
                <text x={8} y={y + 13} fill="var(--color-muted)" fontSize={11}>{r.s.lead} · {r.s.n_events} days</text>
                <line x1={x(lo)} x2={x(hi)} y1={y} y2={y} stroke={color} strokeWidth={2} strokeLinecap="round" />
                <circle cx={x(diff(r))} cy={y} r={5} fill={color} stroke="var(--color-surface)" strokeWidth={2} />
              </g>
            )
          })}
        </svg>
        {hover !== null && (
          <div
            className="absolute pointer-events-none text-xs bg-[var(--color-bg)] border border-[var(--color-border)] rounded-lg px-3 py-2 shadow-lg"
            style={{ left: `${(x(diff(rows[hover])) / W) * 100}%`, top: TOP + hover * ROW_H - 52, transform: 'translateX(-50%)' }}
          >
            <div className="text-[var(--color-text)] font-medium">
              {VENUE_LABEL[rows[hover].venue]} · {rows[hover].s.lead}
            </div>
            <div className="text-[var(--color-muted)] tabular-nums">
              model {num(rows[hover].s[`model_${metric}`] as number)} · market {num(rows[hover].s[`market_${metric}`] as number)}
            </div>
            <div className="text-[var(--color-muted)] tabular-nums">
              diff {signed(diff(rows[hover]))} [{signed(ci(rows[hover])[0])}, {signed(ci(rows[hover])[1])}]
            </div>
          </div>
        )}
      </div>
    </figure>
  )
}
