import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, waitFor, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, toHaveNoViolations } from "jest-axe";

expect.extend(toHaveNoViolations);

// TG7 (WCAG 2.2 AA) — automated axe-core sweep of every main view. Each view is
// rendered with a mocked ../api (so it renders without a backend) and asserted to
// have zero axe violations for the criteria this task addressed.
//
// We scope axe to the rules that map to the applied findings (labels, buttons vs
// spans, aria on comboboxes/dialogs, list/landmark structure, image alt, etc.).
// Color-contrast is verified statically (jsdom has no layout/paint, so axe's
// color-contrast check cannot run reliably here) — see the note in the report.

const RULES = {
  rules: {
    // jsdom cannot compute rendered colors → contrast is checked outside the browser.
    "color-contrast": { enabled: false },
    // These views are rendered in isolation (no <main>/App shell), so the
    // page-level "all content in a landmark" rule is not meaningful here — the
    // real landmark structure (nav/main/h1/skip-link) is asserted separately in
    // the App shell test (A11Y-13). The Dialog also portals into document.body.
    region: { enabled: false },
  },
};

// A permissive api mock: every method resolves to an empty/minimal shape so the
// views render their populated (not just loading) states. Defined via vi.hoisted
// so it is available inside the hoisted vi.mock factory.
const mockApi = vi.hoisted(() => ({
  overview: vi.fn().mockResolvedValue({
    config: { has_target: true, target: "t", target_modality: "text", profile: "p", judge: "j" },
    scorecard: { asr: 0.25, total: 8, hits: 2, grade: "B", by_technique: { author_persona: { hits: 1, total: 4 } } },
    findings_count: 2, runs_count: 3, latest_run: "run-1",
  }),
  config: vi.fn().mockResolvedValue({ has_target: true, target: "t", profile: "p", judge: "j" }),
  settings: vi.fn().mockResolvedValue({ agent: undefined }),
  roles: vi.fn().mockResolvedValue({
    attacker: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false },
    target: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false },
    judge: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false },
  }),
  presets: vi.fn().mockResolvedValue([{ name: "dan", description: "roleplay preset", template: "x {request}" }]),
  transforms: vi.fn().mockResolvedValue([
    { name: "base64", description: "base64 encode", lossy: false, reversible: true },
    { name: "morse", description: "morse code", lossy: true, reversible: false },
  ]),
  tools: vi.fn().mockResolvedValue([
    { name: "author_persona", description: "author a persona", control: false },
    { name: "finish", description: "end the run", control: true },
  ]),
  providers: vi.fn().mockResolvedValue([
    { name: "openrouter", protocol: "openai", base_url: "https://x", model: "m", modality: "text", enabled: true, api_key_env: "K", has_api_key: true, auth_style: "bearer", inference_path: "", models_path: "", timeout: 120, reasoning: false },
  ]),
  agentProfiles: vi.fn().mockResolvedValue({
    roles: {
      attacker: { active: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false }, profiles: [{ name: "p1", role: "attacker", provider: "openrouter", model: "m", prompt_source: "none", system_prompt: "", system_prompt_file: "" }] },
      target: { active: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false }, profiles: [] },
      judge: { active: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false }, profiles: [] },
    },
  }),
  findingRuns: vi.fn().mockResolvedValue([
    { name: "run-1.jsonl", time: "2026-01-01 00:00:00", models: { target: "m", recorded: true }, size: 100, records: 4, hits: 1, findings: 1 },
  ]),
  findings: vi.fn().mockResolvedValue([
    { run: "run-1.jsonl", ts: "2026-01-01", label: "COMPLIED", technique: "author_persona", payload: "p", reason: "r", category: "c", models: { target: "m" } },
  ]),
  runs: vi.fn().mockResolvedValue([
    { name: "run-1.jsonl", time: "2026-01-01 00:00:00", models: { target: "m", recorded: true }, size: 100, records: 4, hits: 1 },
  ]),
  models: vi.fn().mockResolvedValue({ profile: "openrouter", protocol: "openai", models: ["m"], fetched: true, error: "" }),
  refreshModels: vi.fn().mockResolvedValue({ profile: "openrouter", protocol: "openai", models: ["m"], fetched: true, error: "" }),
  addModel: vi.fn().mockResolvedValue({}),
}));

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, api: mockApi };
});

import { App } from "../App";
import { Overview } from "../components/Overview";
import { Console } from "../components/Console";
import { Agent } from "../components/Agent";
import { Arsenal } from "../components/Arsenal";
import { Runs } from "../components/Runs";
import { Findings } from "../components/Findings";
import { Profiles } from "../components/Profiles";
import { ProviderManager } from "../components/ProviderManager";

afterEach(cleanup);

async function expectNoViolations(node: HTMLElement) {
  const results = await axe(node, RULES);
  expect(results).toHaveNoViolations();
}

describe("TG7 axe sweep (WCAG 2.2 AA)", () => {
  it("App shell has landmarks (nav/main), an h1, a skip link, and no violations (A11Y-13)", async () => {
    const { container, findByRole } = render(<App />);
    // Landmarks + heading + skip link.
    await findByRole("navigation", { name: /primary navigation/i });
    expect(container.querySelector("main#main-content")).toBeInTheDocument();
    expect(container.querySelector("h1")).toBeInTheDocument();
    const skip = container.querySelector("a.skip-link");
    expect(skip).toHaveAttribute("href", "#main-content");
    // Region rule is meaningful here (full shell), so re-enable it for this one.
    // heading-order is disabled: cards use <h3> titles by design and the topbar
    // <h1> now precedes them (h1→h3 skip). Normalising the full heading tree is a
    // separate concern outside TG7's A11Y-13 scope (which only promotes the topbar
    // title to h1); tracked as a deferred item in the report.
    const results = await axe(container, { rules: { "color-contrast": { enabled: false }, "heading-order": { enabled: false } } });
    expect(results).toHaveNoViolations();
  });

  it("Overview has no violations", async () => {
    const { container, findByText } = render(
      <Overview
        ov={{
          config: { has_target: true, target: "t", target_modality: "text", profile: "p", judge: "j" },
          scorecard: { asr: 0.25, total: 8, hits: 2, grade: "B", by_technique: { author_persona: { hits: 1, total: 4 } } },
          findings_count: 2, runs_count: 3, latest_run: "run-1",
        }}
        status="data"
      />,
    );
    await findByText(/Attack success rate/i);
    await expectNoViolations(container);
  });

  it("Console has no violations", async () => {
    const { container, findByText } = render(<Console hasTarget />);
    await findByText(/Compose attack/i);
    await waitFor(() => expect(mockApi.transforms).toHaveBeenCalled());
    await expectNoViolations(container);
  });

  it("Agent has no violations", async () => {
    const { container, findByText } = render(<Agent hasTarget />);
    await findByText(/drives the attack loop/i);
    await expectNoViolations(container);
  });

  it("Arsenal has no violations", async () => {
    const { container, findByText } = render(<Arsenal />);
    await findByText(/Prompt template|Select an arsenal/i);
    await expectNoViolations(container);
  });

  it("Runs has no violations", async () => {
    const { container, findByText } = render(<Runs />);
    await findByText(/run log/i);
    await expectNoViolations(container);
  });

  it("Findings has no violations", async () => {
    const { container, findByText } = render(<Findings />);
    await findByText(/Run selection/i);
    await waitFor(() => expect(mockApi.findings).toHaveBeenCalled());
    await expectNoViolations(container);
  });

  it("Profiles has no violations", async () => {
    const { container, findByText } = render(<Profiles />);
    await findByText(/attacker profiles/i);
    await expectNoViolations(container);
  });

  it("ProviderManager has no violations (list + open editor dialog)", async () => {
    const { container, findByText } = render(<ProviderManager onChanged={() => {}} />);
    await findByText(/Provider connections/i);
    await waitFor(() => expect(mockApi.providers).toHaveBeenCalled());
    await expectNoViolations(container);

    // Open the editor Dialog (A11Y-1) and re-check — the modal surface, its
    // fieldset/legend and password autocomplete must also be violation-free.
    await userEvent.click(screen.getByRole("button", { name: "Add provider" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await expectNoViolations(document.body);
  });
});
