import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Capture the signal handed to runAgent so we can assert it was aborted on unmount.
let capturedSignal: AbortSignal | null = null;

vi.mock("../api", () => ({
  runAgent: vi.fn((_body: unknown, _onEvent: unknown, signal?: AbortSignal) => {
    capturedSignal = signal ?? null;
    // Never resolves on its own — only the abort ends it (mirrors a live SSE stream).
    return new Promise<void>((_resolve, reject) => {
      signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    });
  }),
  verdictKind: () => "neutral",
  api: {
    settings: vi.fn().mockResolvedValue({ agent: undefined }),
    tools: vi.fn().mockResolvedValue([]),
    agentProfiles: vi.fn().mockResolvedValue({ roles: { attacker: { profiles: [] } } }),
  },
}));

import { Agent } from "../components/Agent";

beforeEach(() => { capturedSignal = null; });
afterEach(cleanup);

describe("Agent SSE abort (REL-4)", () => {
  it("aborts the in-flight fetch when the component unmounts mid-stream", async () => {
    const warn = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(<Agent hasTarget />);

    const textarea = await screen.findByPlaceholderText(/assess whether the target/i);
    await userEvent.type(textarea, "probe the target");
    await userEvent.click(screen.getByRole("button", { name: /RUN AGENT/i }));

    await waitFor(() => expect(capturedSignal).not.toBeNull());
    expect(capturedSignal!.aborted).toBe(false);

    unmount();

    // The unmount cleanup must abort the controller passed into runAgent.
    expect(capturedSignal!.aborted).toBe(true);
    // No "setState after unmount" React warning should have been logged.
    const warned = warn.mock.calls.some((c) => String(c[0]).includes("unmounted component"));
    expect(warned).toBe(false);
    warn.mockRestore();
  });
});
