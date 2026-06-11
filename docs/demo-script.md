# Sentinel — 3-minute demo voiceover script

> Recorded against the live URL at **https://sentinel-web-586014642476.us-central1.run.app**.
> Target read time: **2:50** (judges cut at 3:00). Word budget: **358 words at ~126 wpm** — composed operator pace.
> Backup: see [§ Alt cut (2:00)](#alt-cut-2-minutes) at the bottom in case the full read runs long.

## Pre-flight checklist (before pressing record)

- [ ] Hard refresh https://sentinel-web-586014642476.us-central1.run.app (Ctrl+Shift+R)
- [ ] Browser tab pinned to that URL, dev tools closed, no extension chrome visible
- [ ] OS notifications silenced; Discord/Slack quit
- [ ] Two browser windows side by side ready to swap: (1) live console, (2) `/prompts` page
- [ ] Test mic level — speak the opening line and check no clipping
- [ ] Verify revision `sentinel-api-00010-bqv` or later is live (look at the fraud incident's gate banner — if no banner appears after compliance, the deploy didn't take and you need to redeploy)
- [ ] Tone: composed, declarative, no "imagine if" or "what if"
- [ ] Record three takes before reviewing — first take is always a warm-up

---

## Scene 1 — 0:00 – 0:15 (15s)

**On screen:** A bank fraud-detection dashboard with the false-positive alert visible at the top — red banner "FP rate 0.213 vs baseline 0.072 — P1." Quiet for the first 1.5s before voiceover starts.

**Overlay:** *(none — let the alert speak)*

**Voiceover:**
> When a bank's fraud AI starts blocking legitimate customer transactions, every minute costs real money and real customer trust. The on-call engineer needs answers in fifteen minutes — and they don't yet know what changed.

*(36 words)*

---

## Scene 2 — 0:15 – 0:45 (30s)

**On screen:** Click the *fraud-fp-burst* scenario card. The live console populates left to right — Coordinator, Trace analyzer, Eval fan-out, Deploy correlator each light up in sequence. The agent stepper is visible. Camera stays on the stepper as it fills.

**Overlay:** `9 stages · gemini-3.1-pro routing`

**Voiceover:**
> Sentinel takes the alert. The Coordinator pulls the trace window from Phoenix, runs the evaluation suite in parallel across four checks, and queries the GitHub MCP for any recent deploy that could have caused this. Eighteen specialist sub-agents under one Coordinator — every transfer recorded on the trace tree, every decision auditable.

*(58 words)*

---

## Scene 3 — 0:45 – 1:15 (30s)

**On screen:** Scroll up briefly to the *Learned routing* callout. Highlight the "Similar past incidents" section showing three rows with cosine similarity scores. Then the Drift detective and Bias / fairness audit stages complete in the stepper.

**Overlay:** `Top similar: fraud-fp-spike-… · 0.86`

**Voiceover:**
> Before any reasoning, the Coordinator queries its own memory of past incidents. Three similar patterns from the last quarter surface, cited by ID, used as precedent. The deterministic stages run on the same trace data — KS test, PSI on distributions, the EEOC four-fifths rule and equalized odds on decision outcomes. Drift severity: severe. Fairness flag: significant.

*(63 words)*

---

## Scene 4 — 1:15 – 1:45 (30s)

**On screen:** Customer impact stage completes — pulse the hero strip briefly. Then compliance stage runs. The blue "Awaiting human approval" banner appears at the top of the page with Approve / Reject buttons. Pause cursor over Approve for 2 seconds without clicking.

**Overlay:** `$84,293 · 312 customers`

**Voiceover:**
> The customer impact quantifier reads the scenario seed and renders the dollars at risk, the customer count, the trust delta — every figure cited to a source. The compliance officer searches the curated regulator corpus. SR 11-7, EU AI Act Article 15. A reporting obligation triggers. Before Sentinel drafts the regulator notification, it asks for human approval.

*(64 words)*

---

## Scene 5 — 1:45 – 2:15 (30s)

**On screen:** Click Approve. Banner dismisses, pipeline finishes. Click "View postmortem →." Postmortem page loads. Scroll smoothly through: hero strip → audit citations → regulatory exposure → drift table → fairness audit → timeline. Don't linger on any one section — the cumulative density is the point.

**Overlay:** `Completeness 1.000`

**Voiceover:**
> Approve. The pipeline continues. The postmortem renders in Google SRE format with five sections most teams skip — quantified impact with audit citations, distribution drift, fairness audit, regulator citations with grounded clause numbers, and a synthesized internal review obligation. The critic agent scored this draft at one-point-zero on a four-dimension rubric. No revision needed.

*(60 words)*

---

## Scene 6 — 2:15 – 2:40 (25s)

**On screen:** Cut to the `/prompts` page. Show the per-agent rolling-score table. Then briefly to the Self-improvement loop · determinism delta panel back on the live console — the 3-to-2 round-trips comparison.

**Overlay:** `Round-trips: 3 → 2 · warm path`

**Voiceover:**
> Sentinel doesn't just respond — it learns from itself. When an agent's rolling critic score slips, the prompt evolver proposes refinements, replays them against stored past incidents, and surfaces a scored winner — gated behind operator approval, fully rollback-able. Round-trips dropped from three to two on the warm path. Deterministic. Reproducible.

*(52 words)*

---

## Scene 7 — 2:40 – 2:50 (10s)

**On screen:** Hero shot — Sentinel logo + product wordmark. GitHub URL renders on screen for the full 10 seconds.

**Overlay:** `github.com/malakazlan/sentinel-agent` *(plus live URL underneath)*

**Voiceover:**
> An AI Site Reliability Engineer for production AI in financial services. Open source. Built on Google ADK, Gemini, and Arize Phoenix.

*(22 words)*

---

**Total word count: 355 words.** At a composed 125–130 wpm operator pace, this lands at **2:48 – 2:52**.

---

# Alt cut (2 minutes)

Use this when the 3-min version times out past 3:00 on the recorded take. Cuts Scene 6 (prompt evolution) and tightens every other scene. **Prompt evolution falls into the readme + repo browse**, not the video.

## Scene A1 — 0:00 – 0:15 (15s)

**On screen:** Fraud-detection dashboard, red P1 alert visible.

**Voiceover:**
> When a bank's fraud AI starts blocking legitimate customer transactions, every minute costs real money and real customer trust. The on-call engineer needs answers in fifteen minutes — and they don't yet know what changed.

*(36 words)*

## Scene A2 — 0:15 – 0:35 (20s)

**On screen:** Click scenario, console populates left to right.

**Overlay:** `18 sub-agents · A2A protocol`

**Voiceover:**
> Sentinel takes the alert. The Coordinator pulls the trace window, runs the eval suite in parallel across four checks, queries the GitHub MCP for recent deploys. Eighteen specialist sub-agents — every transfer auditable on the trace tree.

*(38 words)*

## Scene A3 — 0:35 – 1:05 (30s)

**On screen:** Briefing card with similar incidents, then drift + fairness stages complete.

**Overlay:** `Drift: severe · Fairness: significant`

**Voiceover:**
> Before any reasoning, the Coordinator queries its memory of past incidents. Three similar patterns from the last quarter surface, cited by ID. Deterministic stages run on the trace data — KS test, PSI on distributions, the EEOC four-fifths rule. Drift severity, severe. Fairness flag, significant.

*(46 words)*

## Scene A4 — 1:05 – 1:35 (30s)

**On screen:** Customer impact hero pulses, then compliance stage, then the blue approval banner appears. Pause on Approve.

**Overlay:** `$84,293 · 312 customers`

**Voiceover:**
> Customer impact is quantified — eighty-four thousand dollars at risk, three hundred twelve customers, every figure cited to a seed value. The compliance officer searches the curated regulator corpus. SR 11-7, EU AI Act. A reporting obligation triggers. Before Sentinel drafts the notification, it asks for human approval.

*(50 words)*

## Scene A5 — 1:35 – 1:50 (15s)

**On screen:** Click Approve. Pipeline completes. Smooth scroll through postmortem — hero, drift, fairness, regulator citations.

**Overlay:** `Completeness 1.000`

**Voiceover:**
> Approve. The postmortem renders — Google SRE format, with five sections most teams skip: quantified impact, distribution drift, fairness audit, regulator citations, audit trail. Critic scored: one-point-zero.

*(28 words)*

## Scene A6 — 1:50 – 2:00 (10s)

**On screen:** Logo + GitHub URL.

**Overlay:** `github.com/malakazlan/sentinel-agent`

**Voiceover:**
> An AI Site Reliability Engineer for production AI. Open source. Google ADK, Gemini, Arize Phoenix.

*(17 words)*

**Total word count: 215 words. Lands at 1:58 – 2:02.**

---

## Recording notes

- **Pace yourself.** Composed operator voice is ~125 wpm. If you finish the full script in under 2:35, slow down or add half-second pauses at scene transitions. If you finish over 3:00, switch to the alt cut for the next take.
- **One overlay per scene.** Resist the urge to layer metrics. The voiceover carries them.
- **Don't read the postmortem.** Scroll past it. The density is the message.
- **Close strong.** The closing 10 seconds is the only place "Sentinel" is named verbally in the voiceover — make it land.
- **Three takes minimum.** Do not review take 1 before recording take 2 — your nerves are still fresh. Review takes 2 and 3 together.
