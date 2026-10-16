import { REPO_URL } from './Header'

export default function Footer({ generatedTs }: { generatedTs: number | null }) {
  return (
    <footer className="border-t border-[var(--color-border)] pt-6 text-xs text-[var(--color-muted)] flex flex-wrap justify-between gap-2">
      <span>Read-only research. No orders are placed anywhere in this project.</span>
      <span>
        {generatedTs ? `Data published ${new Date(generatedTs * 1000).toUTCString()}` : 'No data published yet'} ·{' '}
        <a className="underline hover:text-[var(--color-text)]" href={REPO_URL}>GitHub</a>
      </span>
    </footer>
  )
}
