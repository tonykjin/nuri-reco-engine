"use client";

// The last plan request and response, for /results (persisted like the answers).

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

import type { PlanRequest } from "./mapAnswers";

export type PlanResponse = components["schemas"]["PlanResponse"];

interface PlanState {
  request: PlanRequest | null;
  response: PlanResponse | null;
  save: (request: PlanRequest, response: PlanResponse) => void;
  clear: () => void;
}

export const usePlan = create<PlanState>()(
  persist(
    (set) => ({
      request: null,
      response: null,
      save: (request, response) => set({ request, response }),
      clear: () => set({ request: null, response: null }),
    }),
    {
      name: "nuri.plan",
      version: 1,
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({ request: s.request, response: s.response }),
      skipHydration: true,
    },
  ),
);

/** POST /v1/plan; dryRun skips patterns and foods. Throws on an API error. */
export async function fetchPlan(
  request: PlanRequest,
  { dryRun = false, signal }: { dryRun?: boolean; signal?: AbortSignal } = {},
): Promise<PlanResponse> {
  const { data, error } = await api.POST("/v1/plan", {
    params: { query: { dry_run: dryRun } },
    body: request,
    signal,
  });
  if (error || !data) {
    const message = (error as { error?: { message?: string } } | undefined)?.error?.message;
    throw new Error(message ?? "The plan service didn't respond.");
  }
  return data;
}
