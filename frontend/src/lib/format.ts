import type { Summary, VenueResult } from './types'

export const VENUE_LABEL: Record<string, string> = { kalshi: 'Kalshi', polymarket: 'Polymarket' }

export const pct = (p: number) => `${Math.round(p * 100)}%`
export const num = (x: number, d = 3) => x.toFixed(d)
export const signed = (x: number, d = 3) => `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(d)}`

export function monthSpan([start, end]: [string, string]): string {
  const f = (iso: string) =>
    new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
  return `${f(start)} – ${f(end)}`
}

export function ago(ts: number, now = Date.now() / 1000): string {
  const m = Math.max(0, Math.round((now - ts) / 60))
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`
}

export type Verdict = { text: string; tone: 'model' | 'market' | 'neutral' }

/** Who is more accurate on Brier, judged only where the 95% interval excludes zero. */
export function verdict(rows: Summary[]): Verdict {
  if (!rows.length) return { text: 'No scored events yet', tone: 'neutral' }
  const market = rows.filter((r) => r.brier_diff_ci[0] > 0).length
  const model = rows.filter((r) => r.brier_diff_ci[1] < 0).length
  if (market === rows.length) return { text: 'Market more accurate at every lead time', tone: 'market' }
  if (model === rows.length) return { text: 'Model more accurate at every lead time', tone: 'model' }
  if (market && !model) return { text: 'Market more accurate at some lead times', tone: 'market' }
  if (model && !market) return { text: 'Model more accurate at some lead times', tone: 'model' }
  return { text: 'No clear difference', tone: 'neutral' }
}

export const totalEvents = (v: VenueResult) => Math.max(0, ...v.summary.map((r) => r.n_events))
