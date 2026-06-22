'use client'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

interface CurvePoint {
  pred: number
  obs: number
}

interface CalibrationChartProps {
  modelCurve: CurvePoint[]
  marketCurve: CurvePoint[]
}

export default function CalibrationChart({ modelCurve, marketCurve }: CalibrationChartProps) {
  if (!modelCurve || modelCurve.length === 0) return null

  // Merge into combined dataset keyed by pred bin
  const allPreds = Array.from(
    new Set([
      ...modelCurve.map((p) => p.pred),
      ...marketCurve.map((p) => p.pred),
      0, 0.5, 1,
    ])
  ).sort((a, b) => a - b)

  const modelMap = new Map(modelCurve.map((p) => [p.pred, p.obs]))
  const marketMap = new Map(marketCurve.map((p) => [p.pred, p.obs]))

  const combined = allPreds.map((pred) => ({
    pred,
    model_obs: modelMap.get(pred) ?? null,
    market_obs: marketMap.get(pred) ?? null,
    ref_obs: pred,
  }))

  return (
    <div
      className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6 mb-8"
      aria-label="Calibration chart"
    >
      <h2 className="text-sm font-semibold uppercase tracking-widest text-[var(--color-muted)] mb-4">
        Calibration Curve
      </h2>
      <div style={{ height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={combined} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis
              dataKey="pred"
              domain={[0, 1]}
              type="number"
              tickFormatter={(v) => v.toFixed(1)}
              tick={{ fill: 'var(--color-muted)', fontSize: 12 }}
              axisLine={{ stroke: 'var(--color-border)' }}
              tickLine={false}
              label={{ value: 'Predicted prob', position: 'insideBottom', offset: -2, fill: 'var(--color-muted)', fontSize: 11 }}
            />
            <YAxis
              domain={[0, 1]}
              tickFormatter={(v) => v.toFixed(1)}
              tick={{ fill: 'var(--color-muted)', fontSize: 12 }}
              axisLine={{ stroke: 'var(--color-border)' }}
              tickLine={false}
              label={{ value: 'Observed freq', angle: -90, position: 'insideLeft', fill: 'var(--color-muted)', fontSize: 11 }}
            />
            <Tooltip
              contentStyle={{
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                borderRadius: 8,
                color: 'var(--color-text)',
              }}
              labelFormatter={(v) => `Pred: ${Number(v).toFixed(2)}`}
            />
            <Legend wrapperStyle={{ color: 'var(--color-muted)', fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey="ref_obs"
              name="Perfect"
              stroke="#4B5563"
              strokeDasharray="4 4"
              dot={false}
              strokeWidth={1}
            />
            <Line
              type="monotone"
              dataKey="model_obs"
              name="Model"
              stroke="#3B82F6"
              dot={{ fill: '#3B82F6', r: 3 }}
              strokeWidth={2}
              connectNulls={false}
            />
            <Line
              type="monotone"
              dataKey="market_obs"
              name="Market"
              stroke="#D97706"
              dot={{ fill: '#D97706', r: 3 }}
              strokeWidth={2}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
