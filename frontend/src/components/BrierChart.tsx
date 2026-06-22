'use client'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

interface BrierChartProps {
  data: Array<{ lead_hours: number; model_brier: number; market_brier: number }>
}

export default function BrierChart({ data }: BrierChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6 mb-8">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-[var(--color-muted)] mb-4">
        Brier Score by Lead Time
      </h2>
      <div style={{ height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis
              dataKey="lead_hours"
              tickFormatter={(v) => `${v}h`}
              tick={{ fill: 'var(--color-muted)', fontSize: 12 }}
              axisLine={{ stroke: 'var(--color-border)' }}
              tickLine={false}
            />
            <YAxis
              domain={[0, 0.35]}
              tick={{ fill: 'var(--color-muted)', fontSize: 12 }}
              axisLine={{ stroke: 'var(--color-border)' }}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                borderRadius: 8,
                color: 'var(--color-text)',
              }}
              labelFormatter={(v) => `${v}h lead`}
            />
            <Legend
              wrapperStyle={{ color: 'var(--color-muted)', fontSize: 12 }}
            />
            <Bar dataKey="model_brier" name="Model" fill="#3B82F6" radius={[4, 4, 0, 0]} />
            <Bar dataKey="market_brier" name="Market" fill="#D97706" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-[var(--color-muted)] mt-3 text-center">
        Lower Brier score = better calibration
      </p>
    </div>
  )
}
