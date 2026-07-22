import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Capture the onEvent callback runAgent is given so the test can stream events
// into the transcript at will (mirrors a live SSE stream).
type AgentEvent = Record<string, unknown>;
let capturedOnEvent: ((ev: AgentEvent) => void) | null = null;

vi.mock("../api", () => ({
  runAgent: vi.fn((_body: unknown, onEvent: (ev: AgentEvent) => void) => {
    capturedOnEvent = onEvent;
    // Never resolves on its own — the run stays "live" for the test.
    return new Promise<void>(() => {});
  }),
  verdictKind: () => "neutral",
  api: {
    settings: vi.fn().mockResolvedValue({ agent: undefined }),
    tools: vi.fn().mockResolvedValue([]),
    agentProfiles: vi.fn().mockResolvedValue({ roles: { attacker: { profiles: [] } } }),
  },
}));

import { Agent } from "../components/Agent";

// jsdom does not lay out elements, so scroll metrics are always 0. Define them
// on the prototype so the component's isPinnedToBottom() reads our values.
function stubScrollMetrics({ scrollTop, scrollHeight, clientHeight }: {
  scrollTop: number; scrollHeight: number; clientHeight: number;
}) {
  Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => scrollHeight });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => clientHeight });
  // scrollTop must be read/writable so we can detect if the component wrote to it.
  let value = scrollTop;
  Object.defineProperty(HTMLElement.prototype, "scrollTop", {
    configurable: true,
    get: () => value,
    set: (v: number) => { value = v; },
  });
}

function restoreScrollMetrics() {
  for (const prop of ["scrollHeight", "clientHeight", "scrollTop"]) {
    // Deleting the own prototype override restores jsdom's default behaviour.
    // @ts-expect-error dynamic delete on prototype
    delete HTMLElement.prototype[prop];
  }
}

const originalRaf = window.requestAnimationFrame;
const originalMatchMedia = window.matchMedia;

beforeEach(() => {
  capturedOnEvent = null;
  // rAF runs synchronously so the auto-scroll (if any) happens within act().
  window.requestAnimationFrame = ((cb: FrameRequestCallback) => { cb(0); return 0; }) as typeof window.requestAnimationFrame;
  // Reduced-motion off (matchMedia is undefined in jsdom) so the pinned-to-bottom
  // check is the only gate under test.
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  restoreScrollMetrics();
  window.requestAnimationFrame = originalRaf;
  window.matchMedia = originalMatchMedia;
  vi.restoreAllMocks();
  cleanup();
});

async function startRun() {
  const textarea = await screen.findByPlaceholderText(/assess whether the target/i);
  await userEvent.type(textarea, "probe the target");
  await userEvent.click(screen.getByRole("button", { name: /RUN AGENT/i }));
  await waitFor(() => expect(capturedOnEvent).not.toBeNull());
}

describe("Agent transcript auto-scroll (VIS-5)", () => {
  it("does NOT auto-scroll when the user has scrolled up", async () => {
    // User scrolled way up: distance from bottom (900 - 0 - 100 = 800) >> threshold.
    stubScrollMetrics({ scrollTop: 0, scrollHeight: 900, clientHeight: 100 });
    render(<Agent hasTarget />);
    await startRun();

    act(() => { capturedOnEvent!({ type: "text", text: "streamed line" }); });

    // The pane was left where the user put it — no programmatic jump to the bottom.
    const pane = document.querySelector(".transcript") as HTMLElement;
    expect(pane.scrollTop).toBe(0);
  });

  it("auto-scrolls to the bottom when the user is already pinned", async () => {
    // Pinned: distance from bottom (900 - 800 - 100 = 0) <= threshold.
    stubScrollMetrics({ scrollTop: 800, scrollHeight: 900, clientHeight: 100 });
    render(<Agent hasTarget />);
    await startRun();

    act(() => { capturedOnEvent!({ type: "text", text: "streamed line" }); });

    const pane = document.querySelector(".transcript") as HTMLElement;
    // Followed the stream: scrollTop was set to scrollHeight.
    expect(pane.scrollTop).toBe(900);
  });
});
