'use client'

interface HeaderProps {
  verdict: string
  verdictPositive: boolean
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

export default function Header({ verdict, verdictPositive, generatedTs, isSample }: HeaderProps) {
  return (
    <header className="mb-10">
      <div className="flex flex-col sm:flex-row sm:items-end gap-4 mb-2">
        <h1 className="font-mono text-4xl font-bold tracking-tight text-[var(--color-text)]">
          MERCURY
        </h1>
        <div className="flex flex-wrap items-center gap-2 pb-1">
          <span
            className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold ${
              verdictPositive
                ? 'bg-emerald-900/60 text-emerald-300 border border-emerald-700'
                : 'bg-slate-800 text-slate-400 border border-slate-600'
            }`}
          >
            {verdict}
          </span>
          <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs bg-slate-800 text-[var(--color-muted)] border border-[var(--color-border)]">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
            live · updated {timeAgo(generatedTs)}
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
