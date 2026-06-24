'use client'
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import Header from '@/components/Header'
import TrackingStrip from '@/components/TrackingStrip'
import LiveDivergence from '@/components/LiveDivergence'
import type { LiveDisagreement } from '@/components/LiveDivergence'
import StatTiles from '@/components/StatTiles'
import BrierChart from '@/components/BrierChart'
import CalibrationChart from '@/components/CalibrationChart'
import CityTable from '@/components/CityTable'
import type { CityRow } from '@/components/CityTable'
import EmptyState from '@/components/EmptyState'
import Footer from '@/components/Footer'

type Row = {
  market_uid?: string
  city: string
  lead_hours: number
  outcome: number
  model_prob: number
  market_prob: number
}

type ByLead = {
  lead_hours: number
  model_brier: number
  market_brier: number
  model_logloss: number
  market_logloss: number
  n: number
}

type Tracking = {
  n_markets: number
  n_open: number
  n_settled: number
  n_quotes: number
  n_preds: number
  n_cities: number
  last_snapshot_ts: number
}

type EvalData = {
  generated_ts: number
  n_resolved: number
  by_lead: ByLead[]
  rows: Row[]
  tracking?: Tracking
  live_disagreements?: LiveDisagreement[]
}

function computeCalibrationCurve(
  rows: Row[],
  probKey: keyof Pick<Row, 'model_prob' | 'market_prob'>
) {
  const bins: { sumPred: number; sumObs: number; count: number }[] = Array.from(
    { length: 10 },
    () => ({ sumPred: 0, sumObs: 0, count: 0 })
  )

  for (const r of rows) {
    const p = r[probKey]
    const idx = Math.min(Math.floor(p * 10), 9)
    bins[idx].sumPred += p
    bins[idx].sumObs += r.outcome
    bins[idx].count += 1
  }

  return bins
    .filter((b) => b.count > 0)
    .map((b) => ({ pred: b.sumPred / b.count, obs: b.sumObs / b.count }))
}

function computeBrier(
  rows: Row[],
  probKey: keyof Pick<Row, 'model_prob' | 'market_prob'>
): number {
  const sum = rows.reduce((acc, r) => acc + Math.pow(r[probKey] - r.outcome, 2), 0)
  return sum / rows.length
}

function groupByCity(rows: Row[]): CityRow[] {
  const map = new Map<string, Row[]>()
  for (const r of rows) {
    if (!map.has(r.city)) map.set(r.city, [])
    map.get(r.city)!.push(r)
  }

  const result: CityRow[] = []
  for (const [city, cityRows] of map.entries()) {
    const modelBrier = computeBrier(cityRows, 'model_prob')
    const marketBrier = computeBrier(cityRows, 'market_prob')
    const diff = marketBrier - modelBrier
    const winner = Math.abs(diff) < 0.001 ? 'tie' : diff > 0 ? 'model' : 'market'
    result.push({ city, modelBrier, marketBrier, n: cityRows.length, winner })
  }

  return result
}

/**
 * Compute an honest verdict for the header badge.
 * Rules:
 *  - n_resolved < 30 → "Measuring — {n} resolved so far" (neutral)
 *  - model_brier < market_brier AND n >= 20 at that lead → "Model leads at {lead}h" (positive)
 *  - market ahead → "Market leads model" (negative, stated neutrally)
 *  - no data → "Awaiting data" (neutral)
 */
function computeVerdict(
  byLead: ByLead[],
  nResolved: number
): { verdict: string; tone: 'positive' | 'negative' | 'neutral' } {
  if (nResolved === 0) {
    return { verdict: 'Awaiting data', tone: 'neutral' }
  }
  if (nResolved < 30) {
    return {
      verdict: `Measuring — ${nResolved} resolved so far`,
      tone: 'neutral',
    }
  }

  // Find best lead where model wins and has sufficient n
  const modelLeadBuckets = byLead.filter(
    (b) => b.n >= 20 && b.model_brier < b.market_brier
  )
  if (modelLeadBuckets.length > 0) {
    // Pick lead with largest margin
    const best = modelLeadBuckets.reduce((a, b) =>
      b.market_brier - b.model_brier > a.market_brier - a.model_brier ? b : a
    )
    return { verdict: `Model leads at ${best.lead_hours}h`, tone: 'positive' }
  }

  // Check if market is ahead at any lead with n >= 20
  const marketLeadBuckets = byLead.filter(
    (b) => b.n >= 20 && b.market_brier < b.model_brier
  )
  if (marketLeadBuckets.length > 0) {
    return { verdict: 'Market leads model', tone: 'negative' }
  }

  return { verdict: 'Measuring — insufficient data per lead', tone: 'neutral' }
}

function DashboardContent() {
  const searchParams = useSearchParams()
  const isSample = searchParams.get('sample') === '1'
  const [data, setData] = useState<EvalData | null>(null)

  useEffect(() => {
    fetch(isSample ? '/evaluations.sample.json' : '/evaluations.json')
      .then((r) => r.json())
      .then(setData)
      .catch(console.error)
  }, [isSample])

  if (!data) {
    return (
      <div className="min-h-screen bg-[#0B0F17] flex items-center justify-center">
        <div className="text-[var(--color-muted)] font-mono text-sm">Loading…</div>
      </div>
    )
  }

  const hasResolvedData = data.rows.length > 0
  const hasLiveData =
    Array.isArray(data.live_disagreements) && data.live_disagreements.length > 0
  const hasAnyData = hasResolvedData || hasLiveData

  const modelBrier = hasResolvedData ? computeBrier(data.rows, 'model_prob') : null
  const marketBrier = hasResolvedData ? computeBrier(data.rows, 'market_prob') : null
  const cities = [...new Set(data.rows.map((r) => r.city))]
  const { verdict, tone } = computeVerdict(data.by_lead, data.n_resolved)

  const modelCurve = hasResolvedData ? computeCalibrationCurve(data.rows, 'model_prob') : []
  const marketCurve = hasResolvedData
    ? computeCalibrationCurve(data.rows, 'market_prob')
    : []
  const cityRows = hasResolvedData ? groupByCity(data.rows) : []

  // Fallback tracking if field is absent (old JSON shape)
  const tracking: EvalData['tracking'] = data.tracking ?? {
    n_markets: 0,
    n_open: 0,
    n_settled: data.n_resolved,
    n_quotes: 0,
    n_preds: data.rows.length,
    n_cities: cities.length,
    last_snapshot_ts: data.generated_ts,
  }

  const liveDisagreements = data.live_disagreements ?? []

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-10">
        <Header verdict={verdict} verdictTone={tone} isSample={isSample} />

        {/* Hero tracking strip — always shown */}
        <TrackingStrip
          tracking={tracking}
          generatedTs={data.generated_ts}
          isSample={isSample}
        />

        {/* Live divergence — the main "alive" section */}
        <LiveDivergence items={liveDisagreements} />

        {/* Divider */}
        <div
          className="border-t border-[var(--color-border)] mb-8"
          role="separator"
          aria-label="Settled market results"
        />

        {/* Resolved / settled section */}
        {hasResolvedData ? (
          <>
            <StatTiles
              nResolved={data.n_resolved}
              nCities={cities.length}
              modelBrier={modelBrier}
              marketBrier={marketBrier}
            />
            <BrierChart data={data.by_lead} />
            <CalibrationChart modelCurve={modelCurve} marketCurve={marketCurve} />
            <CityTable rows={cityRows} />
          </>
        ) : hasAnyData ? (
          /* Live data exists but no settled yet — show muted notice */
          <div className="text-center py-16 text-[var(--color-muted)] text-sm">
            <p className="font-semibold text-[var(--color-text)] mb-2">
              Settled results pending
            </p>
            <p>
              Model and market probabilities are being snapshotted on open markets; scoring
              populates as those markets settle (typically within 24–48h).
            </p>
          </div>
        ) : (
          <EmptyState />
        )}

        <Footer />
      </main>
    </div>
  )
}

export default function Page() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#0B0F17]" />}>
      <DashboardContent />
    </Suspense>
  )
}
