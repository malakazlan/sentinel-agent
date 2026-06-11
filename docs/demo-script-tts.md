# Sentinel demo — TTS-ready script (paste into Descript)

> Companion to [`demo-script.md`](demo-script.md). Same scene structure and timing — text rewritten so AI TTS reads cleanly (no `$`, no version-string parsing failures, no acronym garbling).
> Target: **2:50** at 125–130 wpm composed-operator pace.
> Workflow: paste each scene's block separately into Descript's script lane; record screen against the scene-on-screen cue; align voiceover audio to the on-screen action.

## Paste targets (in order)

Copy each block below into Descript as a separate clip. Scene-on-screen notes are for YOU when recording; do NOT paste them as voiceover text.

---

## Scene 1 — 0:00 to 0:15

**On screen:** Bank fraud-detection dashboard. Red P1 alert at top. Quiet for 1.5 seconds before voiceover begins.

**Overlay chip:** none — let the red alert carry it.

**Voiceover (paste this):**

> When a bank's fraud A.I. starts blocking legitimate customer transactions, every minute costs real money and real customer trust. The on-call engineer needs answers in fifteen minutes — and they don't yet know what changed.

---

## Scene 2 — 0:15 to 0:45

**On screen:** Click the fraud-false-positive scenario card. Console populates left to right — Coordinator, Trace Analyzer, Eval Fan-out, Deploy Correlator light up in sequence.

**Overlay chip:** `9 stages · Gemini routing`

**Voiceover (paste this):**

> Sentinel takes the alert. The Coordinator pulls the trace window from Phoenix, runs the evaluation suite in parallel across four checks, and queries the GitHub MCP server for any recent deploy that could have caused this. Eighteen specialist sub-agents under one Coordinator — every transfer recorded on the trace tree, every decision auditable.

---

## Scene 3 — 0:45 to 1:15

**On screen:** Scroll up briefly to the *Learned routing* callout. Highlight the *Similar past incidents* card showing three rows with cosine similarity scores. Then Drift Detective and Bias-Fairness Audit stages complete in the stepper.

**Overlay chip:** `Top similar: 0.86`

**Voiceover (paste this):**

> Before any reasoning, the Coordinator queries its own memory of past incidents. Three similar patterns from the last quarter surface, cited by I.D., used as precedent. The deterministic stages run on the same trace data — K-S test, P-S-I on distributions, the E-E-O-C four-fifths rule and equalized odds on decision outcomes. Drift severity: severe. Fairness flag: significant.

---

## Scene 4 — 1:15 to 1:45

**On screen:** Customer impact stage completes — pulse the hero strip briefly. Then compliance stage runs. The blue *Awaiting human approval* banner appears with Approve / Reject buttons. Pause cursor over Approve for 2 seconds without clicking.

**Overlay chip:** `eighty-four thousand · three hundred twelve customers`

**Voiceover (paste this):**

> The customer impact quantifier reads the scenario seed and renders the dollars at risk, the customer count, the trust delta — every figure cited to a source. Eighty-four thousand dollars at risk. Three hundred twelve customers affected. The compliance officer searches the curated regulator corpus. S-R eleven dash seven. E-U A-I Act Article fifteen. A reporting obligation triggers. Before Sentinel drafts the regulator notification, it asks for human approval.

---

## Scene 5 — 1:45 to 2:15

**On screen:** Click Approve. Banner dismisses, pipeline finishes. Click *View postmortem*. Postmortem page loads. Scroll smoothly through: hero strip → audit citations → regulatory exposure → drift table → fairness audit → timeline. Don't linger.

**Overlay chip:** `Completeness 1.000`

**Voiceover (paste this):**

> Approve. The pipeline continues. The postmortem renders in Google S-R-E format with five sections most teams skip — quantified impact with audit citations, distribution drift, fairness audit, regulator citations with grounded clause numbers, and a synthesized internal review obligation. The critic agent scored this draft at one point zero on a four-dimension rubric. No revision needed.

---

## Scene 6 — 2:15 to 2:40

**On screen:** Cut to the Prompts page. Show the per-agent rolling-score table — eval-runner row sits at zero point seven four. Then briefly to the Self-improvement loop · determinism delta panel back on the live console.

**Overlay chip:** `Round-trips: 3 to 2`

**Voiceover (paste this):**

> Sentinel doesn't just respond — it learns from itself. When an agent's rolling critic score slips below the threshold — eval-runner here at zero point seven four — the prompt evolver proposes refinements, replays them against stored past incidents, and surfaces a scored winner. Gated behind operator approval, fully rollback-able. Round-trips dropped from three to two on the warm path. Deterministic. Reproducible.

---

## Scene 7 — 2:40 to 2:50

**On screen:** Hero shot — Sentinel logo + product wordmark. GitHub URL renders on screen for the full 10 seconds.

**Overlay chip:** `github.com/malakazlan/sentinel-agent`

**Voiceover (paste this):**

> An A.I. Site Reliability Engineer for production A.I. in financial services. Open source. Built on Google A-D-K, Gemini, and Arize Phoenix.

---

## Total word count: ~395 words. At Descript's default Overdub pace, lands at 2:48 to 2:52.

---

# Descript-specific recording notes

- **One scene per Descript clip.** Keeps timing aligned with screen action.
- **Overdub voice:** the "Confident, calm" male or female presets read this script cleanly. Try a 5-second preview on Scene 1 before generating all seven.
- **External voice (better):** Settings → Voice → Add ElevenLabs API. Use "Brian" or "Daniel" — operator register.
- **Screen-recording portion:** record at 1920x1080, 30fps minimum. Descript's built-in recorder is fine.
- **Speed up the agent-streaming middle.** Scenes 2–4 are the live pipeline — the actual run takes 9 minutes. Record the full thing, then in Descript select the long stages and set playback speed to 6x or 8x. Voiceover stays at 1x and aligns to the sped-up video.
- **Overlay chips** — Descript text/title layer, lower-right corner, sans-serif, 16pt. Each appears half a second after voiceover mentions it, holds for 4 seconds, fades out.
- **Three takes minimum.** Generate the voiceover once, re-record the screen three times against it.

# Alt cut (2:00) — TTS version

Same shape as the [main alt cut](demo-script.md#alt-cut-2-minutes). Cuts Scene 6 (prompt evolution) and tightens Scene 2. Use if your first take of the main cut goes over 3:00.

---

## Scene A1 — 0:00 to 0:15

> When a bank's fraud A.I. starts blocking legitimate customer transactions, every minute costs real money and real customer trust. The on-call engineer needs answers in fifteen minutes — and they don't yet know what changed.

## Scene A2 — 0:15 to 0:35

> Sentinel takes the alert. The Coordinator pulls the trace window, runs the eval suite in parallel across four checks, queries the GitHub MCP for recent deploys. Eighteen specialist sub-agents — every transfer auditable on the trace tree.

## Scene A3 — 0:35 to 1:05

> Before any reasoning, the Coordinator queries its memory of past incidents. Three similar patterns from the last quarter surface, cited by I.D. Deterministic stages run on the trace data — K-S test, P-S-I, the four-fifths rule. Drift severity, severe. Fairness flag, significant.

## Scene A4 — 1:05 to 1:35

> Customer impact is quantified. Eighty-four thousand dollars at risk, three hundred twelve customers, every figure cited to a seed value. The compliance officer searches the curated regulator corpus — S-R eleven dash seven, E-U A-I Act. A reporting obligation triggers. Before Sentinel drafts the notification, it asks for human approval.

## Scene A5 — 1:35 to 1:50

> Approve. The postmortem renders — Google S-R-E format, with five sections most teams skip: quantified impact, drift, fairness, regulator citations, audit trail. Critic scored: one point zero.

## Scene A6 — 1:50 to 2:00

> An A.I. Site Reliability Engineer for production A.I. in financial services. Open source. Google A-D-K, Gemini, Arize Phoenix.
