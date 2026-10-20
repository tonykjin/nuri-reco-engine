"use client";

// The answers store, persisted to sessionStorage so a refresh keeps the user's answers.

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { type Answers, initialAnswers } from "./answers";

interface AnswersState {
  answers: Answers;
  update: (patch: Partial<Answers>) => void;
  replace: (answers: Answers) => void;
  reset: () => void;
}

export const useAnswers = create<AnswersState>()(
  persist(
    (set) => ({
      answers: initialAnswers,
      update: (patch) => set((s) => ({ answers: { ...s.answers, ...patch } })),
      replace: (answers) => set({ answers }),
      reset: () => set({ answers: initialAnswers }),
    }),
    {
      name: "nuri.onboarding.answers",
      version: 1,
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({ answers: s.answers }),
      // Rehydrated after mount (OnboardingFlow) so server and first client render match.
      skipHydration: true,
    },
  ),
);
