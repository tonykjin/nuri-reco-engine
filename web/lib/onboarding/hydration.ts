"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

interface Persisted {
  // Undefined on the server, where sessionStorage doesn't exist.
  persist?: {
    hasHydrated: () => boolean;
    rehydrate: () => Promise<void> | void;
    onFinishHydration: (fn: () => void) => () => void;
  };
}

/** Loads a sessionStorage-backed store after mount; true once it has. */
export function useHydrated(store: Persisted): boolean {
  useEffect(() => {
    if (store.persist && !store.persist.hasHydrated()) void store.persist.rehydrate();
  }, [store]);
  const subscribe = useCallback(
    (onChange: () => void) => store.persist?.onFinishHydration(onChange) ?? (() => {}),
    [store],
  );
  return useSyncExternalStore(
    subscribe,
    () => store.persist?.hasHydrated() ?? false,
    () => false,
  );
}
