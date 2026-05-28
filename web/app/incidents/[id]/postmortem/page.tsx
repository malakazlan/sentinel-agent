import { Topbar } from "@/components/topbar";
import { Button } from "@/components/ui/button";
import { PostmortemDocument } from "@/components/postmortem-document";
import type { Postmortem } from "@/lib/types";

// Static placeholder — Task 7 wires this to GET /incidents/{id}.
const SAMPLE_PM: Postmortem = {
  title: "False Positive Spike in Electronics Transaction Classification",
  incident_id: "fraud-fp-spike-20260526T133012Z-abcd1234",
  severity: "P1",
  summary:
    "A spike in false positive fraud classifications occurred for retail electronics transactions. The fraud detection model incorrectly flagged 12 consecutive legitimate transactions as fraudulent between 13:16 and 13:21 UTC.",
  impact:
    "12 legitimate retail transactions in the electronics category were incorrectly declined by the fraud detection system. This resulted in direct customer friction and potential revenue loss for these specific transactions.",
  timeline: [
    "13:16 UTC — Onset of false positive spike detected in electronics category transactions.",
    "13:21 UTC — Final observed false positive trace in the current window.",
    "13:22 UTC — Postmortem drafted from trace evidence; investigation into model drift or feature bias pending.",
  ],
  root_cause:
    "The fraud classification model exhibited high-confidence false positives specifically for transactions in the 'electronics' merchant category. The model incorrectly associated these transactions with fraudulent patterns, likely due to recent feature weight shifts or training data bias.",
  detection:
    "Discovered via automated monitoring of classification error rates and post-hoc verification logs, which flagged the discrepancy between model output and verified transaction status.",
  resolution:
    "Investigation is ongoing. Immediate mitigation involves reviewing the recent model deployment and evaluating the necessity of a rollback to the previous stable version.",
  action_items: [
    {
      description:
        "Perform root cause analysis on the model's sensitivity to 'electronics' category transactions to identify specific feature bias.",
      owner_role: "fraud-ml-team",
      severity: "P1",
      due_within_days: 7,
    },
    {
      description:
        "Implement automated guardrails to prevent high-confidence false positives for known low-risk merchant categories.",
      owner_role: "fraud-ml-team",
      severity: "P2",
      due_within_days: 14,
    },
  ],
  lessons_learned: [
    "Model confidence scores can be misleading during drift events; high-confidence predictions should still be subject to category-based sanity checks.",
    "Real-time monitoring of classification error rates by merchant category is essential for early detection of segment-specific model degradation.",
  ],
};

export default function PostmortemPage({ params }: { params: { id: string } }) {
  void params.id; // unused until Task 7 wires this to GET /incidents/{id}
  return (
    <div className="min-h-screen">
      <Topbar
        active="postmortem"
        status={{ label: "Validated · completeness 1.000" }}
        context=""
      />
      <main className="mx-auto w-full max-w-[1180px] px-8 pb-16 pt-10">
        <PostmortemDocument
          pm={SAMPLE_PM}
          completenessLabel="complete"
          completenessScore={1.0}
          generatedRelative="2 min ago"
          watchedModel="fraud-classifier-v2.3.1"
          watchedProject="fraud-detector-prod"
        />
        <div className="mx-auto mt-12 flex max-w-[820px] items-center justify-end gap-2">
          <Button variant="secondary">Export JSON</Button>
        </div>
      </main>
    </div>
  );
}
