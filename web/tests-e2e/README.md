# Sentinel E2E (Playwright)

Drives both servers + the real Gemini pipeline end-to-end. Costs ~$0.10 per
run in Vertex tokens. Treat as a release-gate test, not per-PR.

## Run

From project root:

```powershell
# Headless (default)
npx playwright test

# Headed (watch it run)
npx playwright test --headed

# Debug
npx playwright test --debug
```

## What it asserts

1. Scenarios page renders 3 cards.
2. Click "Run pipeline" on fraud-fp-burst → redirects to a unique incident URL.
3. Live stepper progresses through all 4 stages.
4. "View postmortem" button enables.
5. Postmortem renders with severity P1 + electronics root cause.

## Notes

- Vertex env vars (`GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`,
  `GOOGLE_CLOUD_LOCATION`) must be set in the backend's `.env`. The FastAPI
  process loads them at startup.
- Phoenix must be reachable at `localhost:6006`. Start with `phoenix serve`
  in a separate terminal if not already running.
- `reuseExistingServer: true` means already-running dev servers are reused.
  If a stale server has a different `.env`, kill it first.

## Browser

Default: **system-installed Chrome** (`channel: "chrome"` in `playwright.config.ts`).
This avoids the ~150 MB Playwright Chromium download, which was being
blocked by ECONNRESET on the Azure CDN in our environment.

If you'd rather use the pinned bundled Chromium build (more reproducible
for CI), run `cd web && npx playwright install chromium` once, then change
the project name in `playwright.config.ts` from `chrome` to `chromium` and
remove the `channel: "chrome"` line.
