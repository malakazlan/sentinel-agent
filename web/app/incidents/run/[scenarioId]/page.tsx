import { redirect } from "next/navigation";
import type { Route } from "next";
import { createIncident } from "@/lib/api";

interface RunPageProps {
  params: { scenarioId: string };
}

export default async function RunScenarioPage({ params }: RunPageProps) {
  const response = await createIncident(params.scenarioId);
  redirect(`/incidents/${encodeURIComponent(response.incident_id)}` as Route);
}
