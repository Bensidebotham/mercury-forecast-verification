# weather-vs-market dashboard

Next.js + Recharts dashboard for the [weather-vs-market](../README.md) pipeline. It reads a single
static snapshot, `public/evaluations.json`, which the scheduled ingest job regenerates.

```bash
npm install
npm run dev     # http://localhost:3000        live snapshot
                # http://localhost:3000/?sample=1  illustrative sample data
```
