# Sentinel — design mockups

Static HTML / CSS only. No JS, no framework. The goal is to validate the
visual direction *before* committing to the Next.js + FastAPI build.

## Open the pages

Just open the HTML files directly in a browser — they share `styles.css` and
load Inter + JetBrains Mono from Google Fonts.

```
design/
├── index.html        scenarios picker + recent runs table
├── incident.html     live incident console (the hero)
├── postmortem.html   validated Google-SRE postmortem document
└── styles.css        shared design tokens (light theme)
```

## Aesthetic decisions

- **Light only.** No dark theme, no gradients, no glow, no AI chrome.
- **Black + zinc primary** (Notion / Vercel lineage). Text near-black,
  surfaces white, borders 1px zinc-200.
- **One restrained accent** (`#1E40AF` muted blue) used *only* for the
  learned-routing callout. CTAs are near-black so they feel deliberate
  without being loud.
- **Inter** for UI, **JetBrains Mono** for incident IDs / timestamps.
- **Generous whitespace.** Cards padded 24px, sections separated 32px.

## What each page is meant to prove

**`index.html`** — that the scenarios are first-class objects (not just
debug buttons). Each one has its workflow, severity, and a short
operational summary. The recent-runs table shows cold vs warm round-trip
delta directly in the listing.

**`incident.html`** — that the live agent activity is the hero. Vertical
stepper with status (done / running / queued / skipped), one-line action,
and per-step latency. The **learned-routing callout** under Coordinator
is the self-improvement loop made legible — a subtle accented box, not a
banner. The determinism comparison at the bottom is the cold-vs-warm
proof point.

**`postmortem.html`** — that the final artifact is a proper document,
not a chat reply. Google-SRE sections, monospace IDs, action items as
structured cards with severity and owner role, and a collapsed reference
to the proposed remediation underneath.

## What to redirect if it's off

- Accent color (`--accent` in `styles.css`)
- Type scale (h1/h2/h3 sizes near the top of `styles.css`)
- Card padding / whitespace density
- Stepper visual treatment (the vertical line, dot styling)

Once the visual direction is approved, the Next.js + FastAPI build per the
supervisor spec re-implements these screens with live SSE wiring.
