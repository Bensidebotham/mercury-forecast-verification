export default function Footer() {
  return (
    <footer className="mt-16 py-8 border-t border-[var(--color-border)] text-center text-sm text-[var(--color-muted)]">
      <p>Read-only research dashboard — not financial advice.</p>
      <p className="mt-1">
        Data refreshes on a schedule ·{' '}
        <a href="https://github.com" className="underline hover:text-[var(--color-text)]">
          GitHub
        </a>
      </p>
    </footer>
  )
}
