# weather-vs-market dashboard

Next.js dashboard for the [weather-vs-market](../README.md) pipeline. It renders the newest document the
pipeline published (`wvm publish`), re-reading it at most every 10 minutes.

- **Production:** `WVM_DATABASE_URL` points at Postgres through a read-only role; the page reads the newest
  row of `wvm.published_result`.
- **Local:** without that variable it reads `public/evaluations.json`. Write one with
  `uv run wvm publish --out frontend/public/evaluations.json` from the repo root.

```bash
npm install
npm run dev     # http://localhost:3000
```
