// Shape of the document `wvm publish` writes (schema_version 2).

export type Summary = {
  lead: string
  n_events: number
  model_brier: number
  market_brier: number
  brier_diff: number
  brier_diff_ci: [number, number]
  model_rps: number
  market_rps: number
  rps_diff: number
  rps_diff_ci: [number, number]
  model_logscore: number
  market_logscore: number
  logscore_diff: number
  logscore_diff_ci: [number, number]
}

export type CurveBin = { bin: string; n: number; avg_prob: number | null; win_rate: number | null }

export type VenueResult = {
  summary: Summary[]
  calibration: Record<string, { model: CurveBin[]; market: CurveBin[] }>
  by_city: { lead: string; city: string; n_events: number; model_brier: number; market_brier: number }[]
  stats: Record<string, number>
  date_span: [string, string] | null
}

export type Backtest = {
  protocol: string
  model: string
  window_name: string
  window: [string, string]
  train_window: [string, string]
  generated_ts: number
  git_sha: string | null
  venues: Record<string, VenueResult>
  data_quality: { kalshi_cli_agreement: { n: number; agree: number; rate: number | null } }
}

export type LiveDisagreement = {
  market_uid: string
  venue: string
  city: string
  target_date: string
  question: string
  bucket_lo: number | null
  bucket_hi: number | null
  model_prob: number
  market_prob: number
  gap: number
  lead_hours: number
}

export type Run = {
  run_id: string
  started_ts: number
  finished_ts: number | null
  status: string
  n_markets: number | null
  n_quotes: number | null
  n_preds: number | null
  n_skipped: number | null
}

export type Dashboard = {
  schema_version: number
  generated_ts: number
  backtest: Backtest | null
  live: { model: string; scores: Record<string, { summary: Summary[]; n_events: number }> }
  tracking: {
    n_markets: number
    n_open: number
    n_settled: number
    n_live_quotes: number
    n_preds: number
    last_run: Run | null
  }
  live_disagreements: LiveDisagreement[]
}
