/**
 * Render + jest-axe tests for RunExpandedRow.
 */
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { axe, toHaveNoViolations } from "jest-axe";
import { RunExpandedRow } from "../components/RunExpandedRow";

expect.extend(toHaveNoViolations);

const RULES = {
  rules: {
    "color-contrast": { enabled: false },
    region: { enabled: false },
  },
};

afterEach(cleanup);

async function expectNoViolations(node: HTMLElement) {
  const results = await axe(node, RULES);
  expect(results).toHaveNoViolations();
}

const baseProps = {
  record: { kind: "user", ts: "2026-01-01T00:00:00Z", payload: "hello world" },
  index: 0,
  lineNumber: 1,
  lineKey: "run-0-line",
  rawLine: '{"kind":"user","payload":"hello world"}',
  colSpan: 6,
  copied: null,
  rowKey: "run-0",
  onCopyText: () => {},
};

// ── RunExpandedRow (generic record) ──────────────────────────────────────────

describe("RunExpandedRow", () => {
  it("renders record index and line number", async () => {
    const { container } = render(
      <table><tbody>
        <RunExpandedRow {...baseProps} />
      </tbody></table>
    );
    expect(container.textContent).toContain("record 1");
    expect(container.textContent).toContain("line 1");
    await expectNoViolations(container);
  });

  it("renders field list for non-inference records", async () => {
    const { container } = render(
      <table><tbody>
        <RunExpandedRow {...baseProps} />
      </tbody></table>
    );
    expect(container.textContent).toContain("All JSON fields");
    expect(container.textContent).toContain("payload");
    await expectNoViolations(container);
  });

  it("renders raw record panel", () => {
    const { container } = render(
      <table><tbody>
        <RunExpandedRow {...baseProps} />
      </tbody></table>
    );
    expect(container.textContent).toContain("Raw record");
    expect(container.textContent).toContain(baseProps.rawLine);
  });

  it("renders Copy JSONL line button", () => {
    const { getByRole } = render(
      <table><tbody>
        <RunExpandedRow {...baseProps} />
      </tbody></table>
    );
    expect(getByRole("button", { name: /copy jsonl line/i })).toBeInTheDocument();
  });

  it("shows Copied label when copied matches lineKey", () => {
    const { getAllByText } = render(
      <table><tbody>
        <RunExpandedRow {...baseProps} copied={baseProps.lineKey} />
      </tbody></table>
    );
    expect(getAllByText("Copied").length).toBeGreaterThan(0);
  });
});

// ── RunExpandedRow (inference record) ────────────────────────────────────────

describe("RunExpandedRow — inference", () => {
  const inferenceProps = {
    ...baseProps,
    record: {
      kind: "inference",
      operation: "completion",
      request: {
        system: "you are helpful",
        messages: [{ role: "user", content: "hello" }],
        endpoint: { model: "gpt-4", provider: "openai", name: "gpt-4" },
      },
      stream: [{ channel: "model", text: "hi there" }],
      text: "hi there",
      status: "done",
      duration_ms: "120",
    },
  };

  it("renders InferenceExpanded for inference records", async () => {
    const { container } = render(
      <table><tbody>
        <RunExpandedRow {...inferenceProps} />
      </tbody></table>
    );
    expect(container.textContent).toContain("Stream transcript");
    expect(container.textContent).toContain("Completion");
    await expectNoViolations(container);
  });

  it("renders the stream text", () => {
    const { container } = render(
      <table><tbody>
        <RunExpandedRow {...inferenceProps} />
      </tbody></table>
    );
    expect(container.textContent).toContain("hi there");
  });
});
