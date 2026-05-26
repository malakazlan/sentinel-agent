# Sentinel API — endpoint contract

> Source of truth for the frontend's TypeScript types. If you change this,
> regenerate `web/lib/types.ts` and re-run `npm run typecheck`.

## Endpoints

### `POST /incidents`

Start a new incident pipeline run.

**Request:**
```json
{ "scenario_id": "fraud-fp-burst" | "kyc-sanctions-hallucination" | "lending-latency-regression" }
```

**Response (201):**
```json
{
  "incident_id": "fraud-fp-spike-20260524T204248Z-<uuid8>",
  "scenario_id": "fraud-fp-burst",
  "severity": "P1",
  "title": "Fraud detection — false-positive burst",
  "started_at": "2026-05-26T13:30:12.000Z"
}
```

**Errors:** `400` unknown scenario, `422` missing/invalid body.

---

### `GET /incidents/{id}/stream` (text/event-stream)

Subscribe to the live event stream. Each SSE `data:` line is one JSON-encoded `IncidentEvent`. The stream closes when an `incident_completed` or `incident_failed` event is sent.

**Event types (discriminated on `type`):**

| `type` | Lifecycle position | Key fields |
|---|---|---|
| `incident_started` | first | `scenario_id`, `severity`, `title`, `watched_project` |
| `seed_completed` | after Phoenix seed | `project`, `spans_written`, `n_ok`, `n_error` |
| `stage_started` | per stage | `stage` (investigate / root_cause / remediation / postmortem), `prompt_preview` |
| `stage_completed` | per stage | `stage`, `latency_ms`, `authors[]`, `final_text` |
| `postmortem_validated` | after postmortem stage | `completeness_score`, `completeness_label`, `postmortem_json` |
| `incident_completed` | terminal | `total_latency_ms` |
| `incident_failed` | terminal (on error) | `error` |

Every event also carries `incident_id` and `elapsed_ms`.

**Errors:** `404` unknown incident.

---

### `GET /incidents/{id}`

Fetch the final validated result (or the running status if the pipeline is still in flight).

**Response (200, completed and succeeded):**
```json
{
  "incident_id": "...",
  "scenario_id": "fraud-fp-burst",
  "succeeded": true,
  "total_latency_ms": 254383,
  "postmortem": { /* validated Postmortem (see sentinel/agents/schemas.py) */ },
  "completeness": { "score": 1.0, "label": "complete" },
  "seed_summary": { "project": "fraud-detector-prod", "spans_written": 42, "n_ok": 30, "n_error": 12 }
}
```

**Response (200, completed and failed):**
```json
{
  "incident_id": "...",
  "succeeded": false,
  "error": "RuntimeError: ..."
}
```

**Response (202, still running):**
```json
{ "incident_id": "...", "status": "running", "scenario_id": "fraud-fp-burst" }
```

**Errors:** `404` unknown incident.

---

## CORS

The dev server allowlists `http://localhost:3000` and `http://127.0.0.1:3000` for the Next.js frontend. Production deployment will need explicit origin configuration.

## Auto-generated OpenAPI

`docs/openapi.json` is the OpenAPI 3.x schema exported from FastAPI. Regenerate with:

```powershell
.\.venv\Scripts\python.exe -c "import json; from sentinel.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/openapi.json
```

`/docs` (Swagger UI) and `/redoc` are also served by the running app for interactive exploration.
