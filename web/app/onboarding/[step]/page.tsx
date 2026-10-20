import { notFound } from "next/navigation";

import { OnboardingFlow } from "@/components/onboarding/OnboardingFlow";
import { STEP_IDS } from "@/lib/onboarding/steps";

export function generateStaticParams() {
  return STEP_IDS.map((step) => ({ step }));
}

export default async function OnboardingStepPage({ params }: PageProps<"/onboarding/[step]">) {
  const { step } = await params;
  if (!STEP_IDS.includes(step)) notFound();
  return <OnboardingFlow stepId={step} />;
}
