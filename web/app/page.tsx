import type { Route } from "next";
import { Topbar } from "@/components/topbar";
import { ScenarioCard } from "@/components/scenario-card";
import { SCENARIOS } from "@/lib/scenarios";

export default function HomePage() {
  return (
    <div className="min-h-screen">
      <Topbar
        active="scenarios"
        status={{ dot: "ok", label: "Phoenix reachable · sentinel" }}
        context="fraud-detector-prod, kyc-screener-prod, underwriting-prod"
      />
      <main className="mx-auto w-full max-w-[1180px] px-8 pb-16 pt-10">
        <div className="mb-8">
          <h1 className="mb-2.5 text-2xl font-semibold tracking-tight">Incident response scenarios</h1>
          <p className="max-w-[720px] text-[15px] text-text-secondary">
            Three production AI workloads with known failure modes. Each runs the full five-agent
            pipeline — coordinator, trace analyzer, eval runner, root cause, remediation,
            postmortem — against seeded watched-system traces and produces a validated Google-SRE
            postmortem.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-5">
          {SCENARIOS.map((scenario) => (
            <ScenarioCard
              key={scenario.id}
              scenario={scenario}
              href={`/incidents/run/${scenario.id}` as Route}
            />
          ))}
        </div>
      </main>
    </div>
  );
}
