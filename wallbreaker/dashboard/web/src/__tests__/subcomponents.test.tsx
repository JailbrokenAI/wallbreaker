/**
 * TG4 (R-F1): render + jest-axe tests for extracted subcomponents.
 * NOTE: Deferred manual NVDA/VoiceOver screen-reader pass — see tasks.md 4.4.
 * Code patterns verified via jest-axe (automated). Manual SR quality pass
 * (announcement timing, verbosity) recommended before public release.
 * Status: DEFERRED — not blocking ship (per security-audit-prep.md §3 human confirmations).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { axe, toHaveNoViolations } from "jest-axe";

expect.extend(toHaveNoViolations);

const RULES = {
  rules: {
    "color-contrast": { enabled: false },
    region: { enabled: false },
  },
};

// ── mock api (same pattern as axe.views.test.tsx) ────────────────────────────

const mockApi = vi.hoisted(() => ({
  agentProfiles: vi.fn().mockResolvedValue({
    roles: {
      attacker: {
        active: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false },
        profiles: [{ name: "p1", role: "attacker", provider: "openrouter", model: "m", prompt_source: "none", system_prompt: "", system_prompt_file: "" }],
      },
      target: { active: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false }, profiles: [] },
      judge: { active: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false }, profiles: [] },
    },
  }),
  providers: vi.fn().mockResolvedValue([
    { name: "openrouter", protocol: "openai", base_url: "https://x", model: "m", modality: "text", enabled: true, api_key_env: "K", has_api_key: true, auth_style: "bearer", inference_path: "", models_path: "", timeout: 120, reasoning: false },
  ]),
  models: vi.fn().mockResolvedValue({ profile: "openrouter", protocol: "openai", models: ["m"], fetched: true, error: "" }),
  switchAgentAttacker: vi.fn().mockResolvedValue({ provider: "openrouter", attacker: "m", paused: false, pause_ready: false }),
}));

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, api: mockApi };
});

import { FindingExpanded, TextPanel } from "../components/FindingExpanded";
import { RunDetailView, DEFAULT_COLUMNS } from "../components/RunDetailView";
import { AttackerSwitch, Row, transcriptStatus } from "../components/AgentTranscript";

afterEach(cleanup);

async function expectNoViolations(node: HTMLElement) {
  const results = await axe(node, RULES);
  expect(results).toHaveNoViolations();
}

// ── TextPanel ─────────────────────────────────────────────────────────────────

describe("TextPanel", () => {
  it("renders with value", async () => {
    const { container } = render(
      <table><tbody><tr><td>
        <TextPanel title="Payload" value="test payload" copyKey="k1" copied={null} onCopy={() => {}} />
      </td></tr></tbody></table>
    );
    expect(container.textContent).toContain("test payload");
    await expectNoViolations(container);
  });

  it("renders empty state", async () => {
    const { container } = render(
      <table><tbody><tr><td>
        <TextPanel title="Response" value="" copyKey="k2" copied={null} onCopy={() => {}} />
      </td></tr></tbody></table>
    );
    expect(container.textContent).toContain("Not recorded");
    await expectNoViolations(container);
  });
});

// ── FindingExpanded ───────────────────────────────────────────────────────────

describe("FindingExpanded", () => {
  const finding = {
    run: "run-1.jsonl",
    ts: "2026-01-01",
    label: "COMPLIED",
    technique: "author_persona",
    payload: "test payload",
    reason: "test reason",
    response: "test response",
    category: "jailbreak",
    line: 5,
    technique_detail: {},
    fields: { payload: "test payload" },
    judging: { label: "COMPLIED", score: 0.9, reason: "reason", source: "judge" },
    conversation: [{ role: "user", content: "hello", source: "" }],
  };

  it("renders without throwing", async () => {
    const { container } = render(
      <table><tbody>
        <FindingExpanded
          finding={finding as Parameters<typeof FindingExpanded>[0]["finding"]}
          rowKey="test-key"
          colSpan={8}
          copied={null}
          judgingOpen={false}
          onCopy={() => {}}
          onToggleJudging={() => {}}
        />
      </tbody></table>
    );
    expect(container.textContent).toContain("test payload");
    await expectNoViolations(container);
  });

  it("renders judging criteria when judgingOpen=true", () => {
    const { container } = render(
      <table><tbody>
        <FindingExpanded
          finding={finding as Parameters<typeof FindingExpanded>[0]["finding"]}
          rowKey="test-key"
          colSpan={8}
          copied={null}
          judgingOpen={true}
          onCopy={() => {}}
          onToggleJudging={() => {}}
        />
      </tbody></table>
    );
    expect(container.textContent).toContain("Hide criteria");
  });
});

// ── RunDetailView ─────────────────────────────────────────────────────────────

describe("RunDetailView", () => {
  const noop = () => {};
  const baseProps = {
    open: "run-1.jsonl",
    runDetail: null,
    records: [{ kind: "user", ts: "2026-01-01T00:00:00Z", payload: "hello" }],
    expanded: new Set<number>(),
    copied: null,
    columns: DEFAULT_COLUMNS.map((c) => ({ ...c })),
    dragColumn: null,
    resizing: null,
    onBack: noop,
    onToggleRow: noop,
    onToggleAllExpanded: noop,
    onCopyText: noop,
    onStartColumnDrag: noop,
    onDropColumn: noop,
    onStartColumnResize: noop,
    onNudgeColumnWidth: noop,
    onDragEnd: noop,
  };

  it("renders run name and record count", async () => {
    const { container } = render(<RunDetailView {...baseProps} />);
    expect(container.textContent).toContain("run-1.jsonl");
    await expectNoViolations(container);
  });

  it("renders back button", () => {
    const { getByRole } = render(<RunDetailView {...baseProps} />);
    expect(getByRole("button", { name: /back/i })).toBeInTheDocument();
  });
});

// ── AttackerSwitch ────────────────────────────────────────────────────────────

describe("AttackerSwitch", () => {
  it("renders without throwing", async () => {
    const { container } = render(
      <AttackerSwitch current={{ provider: "openrouter", model: "gpt-4" }} onSwitched={() => {}} />
    );
    expect(container.textContent).toContain("Switch attacker");
    await expectNoViolations(container);
  });
});

// ── Row ───────────────────────────────────────────────────────────────────────

describe("Row", () => {
  it("renders text item", () => {
    const { container } = render(<Row it={{ kind: "text", text: "hello from the agent" }} />);
    expect(container.textContent).toContain("hello from the agent");
  });

  it("renders round item", () => {
    const { container } = render(<Row it={{ kind: "round", round: 2, max: 5 }} />);
    expect(container.textContent).toContain("2/5");
  });

  it("renders done item", () => {
    const { container } = render(<Row it={{ kind: "done", status: "finished", summary: "all done" }} />);
    expect(container.textContent).toContain("finished");
  });

  it("renders error item", () => {
    const { container } = render(<Row it={{ kind: "error", error: "something broke" }} />);
    expect(container.textContent).toContain("something broke");
  });
});

// ── transcriptStatus ──────────────────────────────────────────────────────────

describe("transcriptStatus", () => {
  it("returns empty string for no items", () => {
    expect(transcriptStatus([])).toBe("");
  });

  it("returns done status", () => {
    const result = transcriptStatus([{ kind: "done", status: "finished", summary: "all done" }]);
    expect(result).toContain("finished");
  });

  it("returns round status", () => {
    const result = transcriptStatus([{ kind: "round", round: 1, max: 3 }]);
    expect(result).toContain("Round 1 of 3");
  });

  it("returns error status", () => {
    const result = transcriptStatus([{ kind: "error", error: "boom" }]);
    expect(result).toContain("Error: boom");
  });
});
