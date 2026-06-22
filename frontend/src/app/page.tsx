'use client'
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import Header from '@/components/Header'
import StatTiles from '@/components/StatTiles'
import BrierChart from '@/components/BrierChart'
import CalibrationChart from '@/components/CalibrationChart'
import CityTable from '@/components/CityTable'
import type { CityRow } from '@/components/CityTable'
import EmptyState from '@/components/EmptyState'
import Footer from '@/components/Footer'

type Row = {
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

type EvalData = {
  generated_ts: number
  n_resolved: number
  by_lead: ByLead[]
  rows: Row[]
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

  const hasData = data.rows.length > 0

  const modelBrier = hasData ? computeBrier(data.rows, 'model_prob') : null
  const marketBrier = hasData ? computeBrier(data.rows, 'market_prob') : null
  const cities = [...new Set(data.rows.map((r) => r.city))]
  const verdictPositive = data.by_lead.some((b) => b.model_brier < b.market_brier)
  const verdict = verdictPositive
    ? 'Model leads market'
    : hasData
    ? 'Market leads model'
    : 'Awaiting data'

  const modelCurve = hasData ? computeCalibrationCurve(data.rows, 'model_prob') : []
  const marketCurve = hasData ? computeCalibrationCurve(data.rows, 'market_prob') : []
  const cityRows = hasData ? groupByCity(data.rows) : []

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-10">
        <Header
          verdict={verdict}
          verdictPositive={verdictPositive}
          generatedTs={data.generated_ts}
          isSample={isSample}
        />
        <StatTiles
          nResolved={data.n_resolved}
          nCities={cities.length}
          modelBrier={modelBrier}
          marketBrier={marketBrier}
        />
        {hasData ? (
          <>
            <BrierChart data={data.by_lead} />
            <CalibrationChart modelCurve={modelCurve} marketCurve={marketCurve} />
            <CityTable rows={cityRows} />
          </>
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
