'use client'
import { useState } from 'react'

export type CityRow = {
  city: string
  modelBrier: number
  marketBrier: number
  n: number
  winner: string
}

interface CityTableProps {
  rows: CityRow[]
}

type SortKey = keyof CityRow
type SortDir = 'asc' | 'desc'

export default function CityTable({ rows }: CityTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('modelBrier')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  if (!rows || rows.length === 0) return null

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const sorted = [...rows].sort((a, b) => {
    const av = a[sortKey]
    const bv = b[sortKey]
    if (typeof av === 'string' && typeof bv === 'string') {
      return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
    }
    if (typeof av === 'number' && typeof bv === 'number') {
      return sortDir === 'asc' ? av - bv : bv - av
    }
    return 0
  })

  function WinnerBadge({ winner }: { winner: string }) {
    if (winner === 'model') {
      return (
        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-900/60 text-emerald-300 border border-emerald-700">
          model
        </span>
      )
    }
    if (winner === 'market') {
      return (
        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-900/60 text-amber-300 border border-amber-700">
          market
        </span>
      )
    }
    return (
      <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-600">
        tie
      </span>
    )
  }

  function SortIcon({ col }: { col: SortKey }) {
    if (col !== sortKey) return <span className="ml-1 opacity-30">↕</span>
    return <span className="ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>
  }

  const thClass =
    'px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-[var(--color-muted)] cursor-pointer select-none hover:text-[var(--color-text)] transition-colors'

  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl overflow-hidden mb-8">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-[var(--color-muted)] px-6 pt-5 pb-4">
        By City
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-[var(--color-border)]">
              <th
                className={thClass}
                onClick={() => handleSort('city')}
                aria-sort={sortKey === 'city' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                City <SortIcon col="city" />
              </th>
              <th
                className={thClass}
                onClick={() => handleSort('n')}
                aria-sort={sortKey === 'n' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                N <SortIcon col="n" />
              </th>
              <th
                className={thClass}
                onClick={() => handleSort('modelBrier')}
                aria-sort={sortKey === 'modelBrier' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                Model Brier <SortIcon col="modelBrier" />
              </th>
              <th
                className={thClass}
                onClick={() => handleSort('marketBrier')}
                aria-sort={sortKey === 'marketBrier' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                Market Brier <SortIcon col="marketBrier" />
              </th>
              <th
                className={thClass}
                onClick={() => handleSort('winner')}
                aria-sort={sortKey === 'winner' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                Winner <SortIcon col="winner" />
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={row.city}
                className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-border)] transition-colors"
              >
                <td className="px-4 py-3 text-[var(--color-text)] font-medium">{row.city}</td>
                <td className="px-4 py-3 font-mono tabular-nums text-[var(--color-muted)]">{row.n}</td>
                <td className="px-4 py-3 font-mono tabular-nums text-[var(--color-text)]">
                  {row.modelBrier.toFixed(3)}
                </td>
                <td className="px-4 py-3 font-mono tabular-nums text-[var(--color-text)]">
                  {row.marketBrier.toFixed(3)}
                </td>
                <td className="px-4 py-3">
                  <WinnerBadge winner={row.winner} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
