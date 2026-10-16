import 'server-only'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { neon } from '@neondatabase/serverless'
import type { Dashboard } from './types'

const SCHEMA_VERSION = 2

/**
 * The newest document the pipeline published. In production this comes from
 * Neon through a read-only role (WVM_DATABASE_URL). Without it (local dev, CI
 * builds) it falls back to public/evaluations.json written by
 * `uv run wvm publish --out frontend/public/evaluations.json`.
 */
export async function loadDashboard(): Promise<Dashboard | null> {
  const doc = await loadRaw()
  return doc?.schema_version === SCHEMA_VERSION ? doc : null
}

async function loadRaw(): Promise<Dashboard | null> {
  const url = process.env.WVM_DATABASE_URL
  if (url) {
    const sql = neon(url)
    const rows = await sql`SELECT doc FROM wvm.published_result ORDER BY id DESC LIMIT 1`
    return rows.length ? (JSON.parse(rows[0].doc as string) as Dashboard) : null
  }
  try {
    const file = path.join(process.cwd(), 'public', 'evaluations.json')
    return JSON.parse(await readFile(file, 'utf8')) as Dashboard
  } catch {
    return null
  }
}
