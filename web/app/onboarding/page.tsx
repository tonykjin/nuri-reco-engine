import { redirect } from "next/navigation";

import { STEP_IDS } from "@/lib/onboarding/steps";

export default function OnboardingPage() {
  redirect(`/onboarding/${STEP_IDS[0]}`);
}
