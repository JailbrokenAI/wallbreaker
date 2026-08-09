import { describe, it, expect, afterEach } from "vitest";
import { useEffect, useState } from "react";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

afterEach(cleanup);

// Deferred promise helper so tests control resolution order.
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

// Mirrors the REL-5 stale-guard: `let active = true; return () => { active = false }`
// so a superseded response never calls setState.
function KeyedView({ fetchByKey, keyValue }: { fetchByKey: (k: string) => Promise<string>; keyValue: string }) {
  const [value, setValue] = useState("");
  useEffect(() => {
    let active = true;
    fetchByKey(keyValue).then((v) => { if (active) setValue(v); });
    return () => { active = false; };
  }, [fetchByKey, keyValue]);
  return <div data-testid="value">{value}</div>;
}

describe("stale-guard (REL-5)", () => {
  it("does not let a superseded (slow) response overwrite newer state", async () => {
    const slow = deferred<string>();
    const fast = deferred<string>();
    const byKey: Record<string, ReturnType<typeof deferred<string>>> = { a: slow, b: fast };
    const fetchByKey = (k: string) => byKey[k].promise;

    const { rerender } = render(<KeyedView fetchByKey={fetchByKey} keyValue="a" />);
    // Switch key before "a" resolves — this unmounts the "a" effect (active=false).
    rerender(<KeyedView fetchByKey={fetchByKey} keyValue="b" />);

    // Newer request resolves first.
    fast.resolve("B-result");
    await waitFor(() => expect(screen.getByTestId("value")).toHaveTextContent("B-result"));

    // The stale "a" request resolves later; it must be ignored.
    slow.resolve("A-result");
    await Promise.resolve();
    expect(screen.getByTestId("value")).toHaveTextContent("B-result");
    expect(screen.getByTestId("value")).not.toHaveTextContent("A-result");
  });
});
