// Debounced calls where only the latest result counts (the pace slider's dry-run preview).

export interface Latest<I> {
  call: (input: I) => void;
  cancel: () => void;
}

export function latestOnly<I, O>(
  fn: (input: I, signal: AbortSignal) => Promise<O>,
  delayMs: number,
  handlers: { onResult: (out: O) => void; onError?: (error: unknown) => void },
): Latest<I> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let seq = 0;

  const cancel = () => {
    clearTimeout(timer);
    controller?.abort();
    seq += 1;
  };

  return {
    call(input) {
      clearTimeout(timer);
      const id = ++seq;
      timer = setTimeout(async () => {
        controller?.abort();
        const current = new AbortController();
        controller = current;
        try {
          const out = await fn(input, current.signal);
          if (id === seq) handlers.onResult(out);
        } catch (error) {
          if (id === seq && !current.signal.aborted) handlers.onError?.(error);
        }
      }, delayMs);
    },
    cancel,
  };
}
