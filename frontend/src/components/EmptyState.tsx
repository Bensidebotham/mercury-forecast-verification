import { Clock } from 'lucide-react'

export default function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 px-8 text-center">
      <Clock className="w-12 h-12 text-[var(--color-muted)] mb-6" />
      <h2 className="text-2xl font-semibold text-[var(--color-text)] mb-3">Pipeline Live — Accruing Data</h2>
      <p className="max-w-md text-[var(--color-muted)] leading-relaxed">
        Model and market probabilities are being snapshotted on open markets; scoring populates as those markets settle (typically within 24–48h).
      </p>
    </div>
  )
}
