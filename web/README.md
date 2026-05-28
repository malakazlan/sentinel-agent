# Sentinel — Next.js frontend

The production UI for Sentinel. Drives the five-agent pipeline live via the
FastAPI backend at `localhost:8000`.

## Run locally

You need two terminals — one for the backend, one for this frontend.

**Terminal 1 — FastAPI backend (from project root):**

```powershell
.\.venv\Scripts\python.exe -m uvicorn sentinel.api.main:app --reload --port 8000
```

The OpenAPI docs are served at `http://localhost:8000/docs`. Health check at
`http://localhost:8000/health`.

**Terminal 2 — Next.js dev server (from `web/`):**

```powershell
cd web
cp .env.example .env.local       # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm install
npm run dev
```

The app is at `http://localhost:3000`.

## What to expect

1. Land on **Scenarios** — three FinServ incidents (fraud FP burst, KYC PEP
   hallucination, lending latency regression).
2. Click any **Run pipeline**. The page navigates to `/incidents/run/<id>`
   which POSTs to the backend and redirects you to the live console.
3. The **Live console** stepper updates as events stream in (SSE). Stages
   flip from queued → running → done. The learned-routing callout under
   Coordinator is the self-improvement loop made visible.
4. When `incident_completed` fires, the **View postmortem** button activates.
   Click it for the validated Google-SRE document.

## Architecture

- Next.js 14 App Router, TypeScript strict
- Tailwind with design tokens lifted from `/design/styles.css`
- shadcn/ui primitives (button, badge, card) — hand-imported (not the full bundle)
- TanStack Query for the postmortem GET
- Native `EventSource` for SSE (zero extra dep)
- Lucide icons

The TypeScript wire types in `lib/types.ts` mirror Python event schemas in
`sentinel/events.py`. If the backend schema changes, update both — the
backend has `extra="forbid"` enabled, so drift surfaces as 400/422 instantly.

## Scripts

```
npm run dev         # Next.js dev server on :3000
npm run build       # production build
npm run start       # serve the production build
npm run lint        # next lint
npm run typecheck   # tsc --noEmit
```

## Routes

| Route | Purpose |
|---|---|
| `/` | Scenarios picker |
| `/incidents/run/[scenarioId]` | Server-side POST to backend, redirect to live console |
| `/incidents/[id]` | Live agent activity stepper (SSE) |
| `/incidents/[id]/postmortem` | Validated Google-SRE postmortem document |

## Troubleshooting

**Stream stays "connecting"** — backend probably isn't running. Check
`http://localhost:8000/health`.

**CORS error in console** — backend CORS allowlist is `localhost:3000` only;
make sure you're hitting `http://localhost:3000`, not `127.0.0.1:3000`.

**Stepper shows nothing for minutes** — the Gemini-3.1-Pro call latencies
are 30–60s each. Five agents → ~4-5 min end-to-end is normal.

**Postmortem page shows "Failed to load"** — clicked the postmortem link
before the pipeline finished. Go back, wait for the "View postmortem"
button to enable.
