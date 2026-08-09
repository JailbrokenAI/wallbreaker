import { useCallback, useEffect, useRef } from "react";

/**
 * useAbortableFetch (REL-4/REL-5) — owns an AbortController that is aborted on
 * component unmount and on demand. `start()` aborts any in-flight controller and
 * returns a fresh one wired to the same lifecycle, so a new fetch/stream cancels
 * the previous one. Read the current controller via `controllerRef`.
 */
export function useAbortableFetch() {
  const controllerRef = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  /** Abort any prior controller and hand back a fresh signal for the new request. */
  const start = useCallback((): AbortController => {
    controllerRef.current?.abort();
    const next = new AbortController();
    controllerRef.current = next;
    return next;
  }, []);

  useEffect(() => () => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  return { controllerRef, start, abort };
}

/** True when the rejection is an intentional abort (should not surface as an error). */
export function isAbortError(error: unknown): boolean {
  return (
    error instanceof DOMException && error.name === "AbortError"
  ) || (error instanceof Error && error.name === "AbortError");
}
