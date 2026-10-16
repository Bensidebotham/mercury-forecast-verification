'use client'
import { useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { VenueResult } from '@/lib/types'
import { VENUE_LABEL, pct } from '@/lib/format'

const MIN_BIN = 10 // bins with fewer bucket-level forecasts are too noisy to plot

type Point = { p: number; model?: number; market?: number; nModel?: number; nMarket?: number }

/** Reliability diagram: of the buckets given ~X% chance, how often did they win? */
export default function CalibrationChart({ venues }: { venues: Record<string, VenueResult> }) {
  const names = Object.keys(venues).filter((v) => Object.keys(venues[v].calibration).length)
  const [venue, setVenue] = useState(names[0])
  const leads = venue ? Object.keys(venues[venue].calibration) : []
  const [lead, setLead] = useState(leads[0])
  if (!venue || !lead || !venues[venue].calibration[lead]) return null

  const { model, market } = venues[venue].calibration[lead]
  const points: Point[] = []
  for (const [side, bins] of [['model', model], ['market', market]] as const) {
    for (const b of bins) {
      if (b.n < MIN_BIN || b.avg_prob === null || b.win_rate === null) continue
      const pt: Point = { p: b.avg_prob }
      if (side === 'model') Object.assign(pt, { model: b.win_rate, nModel: b.n })
      else Object.assign(pt, { market: b.win_rate, nMarket: b.n })
      points.push(pt)
    }
  }
  points.sort((a, b) => a.p - b.p)

  const toggle = (opts: string[], value: string, set: (v: string) => void, label: (v: string) => string) => (
    <div role="radiogroup" className="flex gap-1 text-xs">
      {opts.map((o) => (
        <button key={o} role="radio" aria-checked={value === o} onClick={() => set(o)}
          className={`px-3 py-1 rounded-full border transition-colors ${value === o
            ? 'border-[var(--color-text)] text-[var(--color-text)]'
            : 'border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-text)]'}`}>
          {label(o)}
        </button>
      ))}
    </div>
  )

  return (
    <figure className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6 mb-8">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <figcaption>
          <h2 className="text-base font-semibold text-[var(--color-text)]">Calibration</h2>
          <p className="text-xs text-[var(--color-muted)] mt-1 max-w-md">
            Each point groups bucket forecasts by stated probability and shows how often those buckets won. On the
            dashed line, a 30% forecast wins 30% of the time. Bins under {MIN_BIN} forecasts are hidden.
          </p>
        </figcaption>
        <div className="flex flex-col gap-2 items-end">
          {toggle(names, venue, (v) => { setVenue(v); setLead(Object.keys(venues[v].calibration)[0]) }, (v) => VENUE_LABEL[v] ?? v)}
          {toggle(leads, lead, setLead, (l) => l)}
        </div>
      </div>
      <div style={{ height: 320 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 16, left: 0, bottom: 16 }}>
            <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" />
            <XAxis dataKey="p" type="number" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={pct}
              tick={{ fill: 'var(--color-muted)', fontSize: 12 }} axisLine={{ stroke: 'var(--color-border)' }} tickLine={false}
              label={{ value: 'Forecast probability', position: 'insideBottom', offset: -10, fill: 'var(--color-muted)', fontSize: 11 }} />
            <YAxis type="number" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={pct}
              tick={{ fill: 'var(--color-muted)', fontSize: 12 }} axisLine={{ stroke: 'var(--color-border)' }} tickLine={false}
              label={{ value: 'How often it won', angle: -90, position: 'insideLeft', fill: 'var(--color-muted)', fontSize: 11 }} />
            <Tooltip
              contentStyle={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', borderRadius: 8, fontSize: 12 }}
              labelFormatter={(v) => `Forecast ${pct(Number(v))}`}
              formatter={(value, name, item) => {
                const n = name === 'Model' ? item.payload.nModel : item.payload.nMarket
                return [`won ${pct(Number(value))} (n=${n})`, name]
              }}
            />
            <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12, color: 'var(--color-muted)' }} />
            <Line data={[{ p: 0, ref: 0 }, { p: 1, ref: 1 }]} dataKey="ref" name="Perfectly calibrated" stroke="var(--color-muted)"
              strokeDasharray="4 4" dot={false} strokeWidth={1} isAnimationActive={false} legendType="plainline" />
            <Line dataKey="model" name="Model" stroke="var(--color-model)" strokeWidth={2} connectNulls
              dot={{ r: 4, fill: 'var(--color-model)', stroke: 'var(--color-surface)', strokeWidth: 2 }} isAnimationActive={false} />
            <Line dataKey="market" name="Market" stroke="var(--color-market)" strokeWidth={2} connectNulls
              dot={{ r: 4, fill: 'var(--color-market)', stroke: 'var(--color-surface)', strokeWidth: 2 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
