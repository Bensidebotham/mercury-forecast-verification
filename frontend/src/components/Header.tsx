import type { Verdict } from '@/lib/format'

export const REPO_URL = 'https://github.com/Bensidebotham/mercury-forecast-verification'

const TONE: Record<Verdict['tone'], string> = {
  model: 'border-[var(--color-model)] text-[var(--color-text)]',
  market: 'border-[var(--color-market)] text-[var(--color-text)]',
  neutral: 'border-[var(--color-border)] text-[var(--color-muted)]',
}

export default function Header({ verdicts }: { verdicts: { venue: string; v: Verdict }[] }) {
  return (
    <header className="mb-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="font-mono text-3xl sm:text-4xl font-bold tracking-tight text-[var(--color-text)]">
          weather-vs-market
        </h1>
        <a href={REPO_URL} className="text-sm text-[var(--color-muted)] hover:text-[var(--color-text)] underline underline-offset-4">
          Source &amp; method on GitHub
        </a>
      </div>
      <p className="text-[var(--color-muted)] mt-2 max-w-2xl">
        Can a bias-corrected weather model out-predict Kalshi and Polymarket on tomorrow&apos;s high temperature?
        Every forecast is scored against the official result, with no trading involved.
      </p>
      {verdicts.length > 0 && (
        <ul className="flex flex-wrap gap-2 mt-4" aria-label="Verdict per venue">
          {verdicts.map(({ venue, v }) => (
            <li key={venue} className={`px-3 py-1 rounded-full border text-xs font-semibold ${TONE[v.tone]}`}>
              {venue}: {v.text}
            </li>
          ))}
        </ul>
      )}
    </header>
  )
}
