import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// TG7 focused RTL tests for the interactive a11y wiring:
//  - A11Y-3: Console transform chip toggles via keyboard (Space/Enter) and flips
//    aria-pressed.
//  - A11Y-1: a Dialog surface (RoleChooser menu) traps focus, closes on Escape,
//    and restores focus to the trigger.
//  - A11Y-2: the ModelChooser combobox exposes aria-activedescendant on ArrowDown.

const mockApi = vi.hoisted(() => ({
  presets: vi.fn().mockResolvedValue([]),
  transforms: vi.fn().mockResolvedValue([
    { name: "base64", description: "base64 encode", lossy: false, reversible: true },
  ]),
  agentProfiles: vi.fn().mockResolvedValue({
    roles: {
      attacker: { active: {}, profiles: [] },
      target: { active: {}, profiles: [] },
      judge: { active: {}, profiles: [] },
    },
  }),
  saveRole: vi.fn().mockResolvedValue({}),
  models: vi.fn().mockResolvedValue({ profile: "openrouter", protocol: "openai", models: ["gpt-x", "claude-y", "grok-z"], fetched: true, error: "" }),
  refreshModels: vi.fn().mockResolvedValue({ profile: "openrouter", protocol: "openai", models: ["gpt-x"], fetched: true, error: "" }),
  addModel: vi.fn().mockResolvedValue({}),
}));

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, api: mockApi };
});
// Keep RoleChooser's nested choosers inert so the focus-trap test is deterministic.
vi.mock("../components/ProviderChooser", () => ({ ProviderChooser: () => null }));

import { Console } from "../components/Console";
import { RoleChooser } from "../components/RoleChooser";
import { ModelChooser } from "../components/ModelChooser";

afterEach(cleanup);

describe("A11Y-3: Console transform chip is a keyboard button with aria-pressed", () => {
  it("toggles aria-pressed via Space and Enter", async () => {
    render(<Console hasTarget />);
    const chip = await screen.findByRole("button", { name: "base64" });
    expect(chip).toHaveAttribute("aria-pressed", "false");

    chip.focus();
    await userEvent.keyboard(" ");
    expect(chip).toHaveAttribute("aria-pressed", "true");

    await userEvent.keyboard("{Enter}");
    expect(chip).toHaveAttribute("aria-pressed", "false");
  });
});

describe("A11Y-1: RoleChooser menu is a focus-trapping Dialog", () => {
  it("opens on the chip, closes on Escape, and restores focus to the trigger", async () => {
    const value = { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none" as const, has_system_prompt: false };
    render(<RoleChooser role="attacker" value={value} onSaved={() => {}} />);

    const trigger = screen.getByRole("button", { name: /attacker/i });
    await userEvent.click(trigger);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
});

describe("A11Y-2: ModelChooser combobox exposes aria-activedescendant on ArrowDown", () => {
  it("sets aria-controls and moves aria-activedescendant to the first option", async () => {
    render(<ModelChooser profile="openrouter" value="" onChange={() => {}} ariaLabel="Target model" />);
    const input = screen.getByRole("combobox", { name: "Target model" });

    // aria-controls points at the listbox id even before it opens.
    const listId = input.getAttribute("aria-controls");
    expect(listId).toBeTruthy();

    input.focus();
    await waitFor(() => expect(mockApi.models).toHaveBeenCalled());
    await userEvent.keyboard("{ArrowDown}");

    const active = input.getAttribute("aria-activedescendant");
    expect(active).toBeTruthy();
    // The highlighted option's id must match aria-activedescendant.
    expect(document.getElementById(active!)).toHaveAttribute("role", "option");
  });
});
