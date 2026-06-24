'use client'

interface TrackingData {
  n_markets: number
  n_open: number
  n_settled: number
  n_quotes: number
  n_preds: number
  n_cities: number
  last_snapshot_ts: number
}

interface TrackingStripProps {
  tracking: TrackingData
  generatedTs: number
  isSample: boolean
}

function timeAgo(ts: number): string {
  const diff = Date.now() / 1000 - ts
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function Tile({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5 flex flex-col gap-1">
      <p className="text-xs text-[var(--color-muted)] uppercase tracking-widest">{label}</p>
      <p className="font-mono text-3xl font-bold text-[var(--color-text)] tabular-nums leading-none">
        {value.toLocaleString()}
      </p>
    </div>
  )
}

export default function TrackingStrip({ tracking, generatedTs, isSample }: TrackingStripProps) {
  const ts = tracking.last_snapshot_ts ?? generatedTs

  return (
    <div className="mb-10">
      <div className="flex items-center gap-2 mb-4">
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs bg-slate-800 text-[var(--color-muted)] border border-[var(--color-border)]">
          <span
            className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"
            aria-hidden="true"
          />
          live · updated {timeAgo(ts)}
          {isSample && ' · sample data'}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
        <Tile label="Markets tracked" value={tracking.n_markets} />
        <Tile label="Cities" value={tracking.n_cities} />
        <Tile label="Open now" value={tracking.n_open} />
        <Tile label="Settled" value={tracking.n_settled} />
        <Tile label="Snapshots" value={tracking.n_preds} />
      </div>
    </div>
  )
}
