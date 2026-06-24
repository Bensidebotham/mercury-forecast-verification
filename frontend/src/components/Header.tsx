'use client'

interface HeaderProps {
  verdict: string
  verdictTone: 'positive' | 'negative' | 'neutral'
  isSample: boolean
}

export default function Header({ verdict, verdictTone, isSample }: HeaderProps) {
  const badgeClass =
    verdictTone === 'positive'
      ? 'bg-emerald-900/60 text-emerald-300 border-emerald-700'
      : verdictTone === 'negative'
      ? 'bg-amber-900/60 text-amber-300 border-amber-700'
      : 'bg-slate-800 text-slate-400 border-slate-600'

  return (
    <header className="mb-6">
      <div className="flex flex-col sm:flex-row sm:items-end gap-4 mb-2">
        <h1 className="font-mono text-4xl font-bold tracking-tight text-[var(--color-text)]">
          MERCURY
        </h1>
        <div className="flex flex-wrap items-center gap-2 pb-1">
          <span
            className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold border ${badgeClass}`}
          >
            {verdict}
          </span>
          {isSample && (
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-amber-900/60 text-amber-300 border border-amber-700">
              sample data
            </span>
          )}
        </div>
      </div>
      <p className="text-[var(--color-muted)] text-sm">
        Can a weather model beat the prediction market?
      </p>
    </header>
  )
}
