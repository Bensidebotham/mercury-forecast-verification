export default function Footer() {
  return (
    <footer className="mt-16 py-8 border-t border-[var(--color-border)] text-center text-sm text-[var(--color-muted)]">
      <p>Read-only research dashboard — not financial advice.</p>
      <p className="mt-1">
        Data refreshes on a schedule ·{' '}
        <a
          href="https://github.com/Bensidebotham/mercury-forecast-verification"
          className="underline hover:text-[var(--color-text)] transition-colors duration-150 motion-reduce:transition-none"
        >
          GitHub
        </a>
      </p>
    </footer>
  )
}
