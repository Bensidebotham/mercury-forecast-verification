'use client'

interface StatTilesProps {
  nResolved: number
  nCities: number
  modelBrier: number | null
  marketBrier: number | null
}

export default function StatTiles({ nResolved, nCities, modelBrier, marketBrier }: StatTilesProps) {
  const modelWins = modelBrier !== null && marketBrier !== null && modelBrier < marketBrier
  const marketWins = modelBrier !== null && marketBrier !== null && marketBrier < modelBrier

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5">
        <p className="text-xs text-[var(--color-muted)] uppercase tracking-widest mb-2">Resolved</p>
        <p className="font-mono text-3xl font-bold text-[var(--color-text)]">{nResolved}</p>
      </div>
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5">
        <p className="text-xs text-[var(--color-muted)] uppercase tracking-widest mb-2">Cities</p>
        <p className="font-mono text-3xl font-bold text-[var(--color-text)]">{nCities}</p>
      </div>
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5">
        <p className="text-xs text-[var(--color-muted)] uppercase tracking-widest mb-2">Model Brier</p>
        <p
          className={`font-mono text-3xl font-bold ${
            modelWins ? 'text-emerald-400' : 'text-[var(--color-text)]'
          }`}
        >
          {modelBrier !== null ? modelBrier.toFixed(3) : '—'}
        </p>
      </div>
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5">
        <p className="text-xs text-[var(--color-muted)] uppercase tracking-widest mb-2">Market Brier</p>
        <p
          className={`font-mono text-3xl font-bold ${
            marketWins ? 'text-emerald-400' : 'text-[var(--color-text)]'
          }`}
        >
          {marketBrier !== null ? marketBrier.toFixed(3) : '—'}
        </p>
      </div>
    </div>
  )
}
