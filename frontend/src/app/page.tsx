import Header from '@/components/Header'
import Headline from '@/components/Headline'
import DiffChart from '@/components/DiffChart'
import CalibrationChart from '@/components/CalibrationChart'
import CityTable from '@/components/CityTable'
import LiveSection from '@/components/LiveSection'
import Method from '@/components/Method'
import Footer from '@/components/Footer'
import { loadDashboard } from '@/lib/data'
import { VENUE_LABEL, monthSpan, verdict } from '@/lib/format'

// The pipeline publishes hourly; re-read the newest document at most every 10 minutes.
export const revalidate = 600

export default async function Page() {
  const data = await loadDashboard()
  const backtest = data?.backtest ?? null
  const venues = backtest ? Object.entries(backtest.venues).filter(([, v]) => v.summary.length) : []

  return (
    <main className="max-w-5xl mx-auto px-4 sm:px-6 py-10">
      <Header verdicts={venues.map(([venue, v]) => ({ venue: VENUE_LABEL[venue] ?? venue, v: verdict(v.summary) }))} />
      {backtest && venues.length > 0 ? (
        <>
          <Headline backtest={backtest} />
          <DiffChart
            rows={venues.flatMap(([venue, v]) => v.summary.map((s) => ({ venue, s })))}
            windowLabel={`${backtest.window_name} window, ${monthSpan(backtest.window)}`}
          />
          <CalibrationChart venues={backtest.venues} />
          <CityTable backtest={backtest} />
        </>
      ) : (
        <p className="text-[var(--color-muted)] mb-8">The backtest results have not been published yet.</p>
      )}
      {data && <LiveSection data={data} />}
      <Method backtest={backtest} />
      <Footer generatedTs={data?.generated_ts ?? null} />
    </main>
  )
}
