"use client";

// Lets a screen move the flow on (e.g. Taste's Skip) without importing the step list.

import { createContext, useContext } from "react";

export const StepNav = createContext<{ next: () => void }>({ next: () => {} });

export const useStepNav = () => useContext(StepNav);
