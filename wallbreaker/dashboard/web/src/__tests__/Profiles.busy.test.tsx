import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AgentProfilesResponse } from "../api";

// vi.mock is hoisted, so the mock state must be created via vi.hoisted.
const mocks = vi.hoisted(() => {
  const roleData = (role: "attacker" | "target" | "judge") => ({
    active: { provider: "openrouter", model: "m", profile: "", custom: true, prompt_source: "none", has_system_prompt: false },
    profiles: role === "attacker"
      ? [{ name: "p1", role, provider: "openrouter", model: "m", prompt_source: "none", system_prompt: "", system_prompt_file: "" }]
      : [],
  });
  const profilesResponse = {
    roles: { attacker: roleData("attacker"), target: roleData("target"), judge: roleData("judge") },
  } as unknown as AgentProfilesResponse;
  const state: { deleteResolve: (() => void) | null } = { deleteResolve: null };
  const deleteAgentProfile = vi.fn((..._args: unknown[]) => new Promise<{ ok: boolean }>((resolve) => {
    state.deleteResolve = () => resolve({ ok: true });
  }));
  return { profilesResponse, state, deleteAgentProfile };
});

vi.mock("../api", () => ({
  api: {
    agentProfiles: vi.fn().mockResolvedValue(mocks.profilesResponse),
    deleteAgentProfile: mocks.deleteAgentProfile,
    saveAgentProfile: vi.fn().mockResolvedValue({}),
    saveRole: vi.fn().mockResolvedValue({}),
  },
}));

// Keep child choosers inert.
vi.mock("../components/ModelChooser", () => ({ ModelChooser: () => null }));
vi.mock("../components/ProviderChooser", () => ({ ProviderChooser: () => null }));

import { Profiles } from "../components/Profiles";

afterEach(() => { cleanup(); mocks.deleteAgentProfile.mockClear(); mocks.state.deleteResolve = null; });

describe("Profiles double-submit guard (REL-10)", () => {
  it("fires exactly one request on a double-click of Remove", async () => {
    render(<Profiles />);

    // Find the attacker card's Remove button.
    const heading = await screen.findByText("attacker profiles");
    const card = heading.closest("section")!;
    const remove = within(card).getByRole("button", { name: "Remove" });

    // Two rapid clicks while the first mutation is still pending.
    await userEvent.click(remove);
    await userEvent.click(remove);

    expect(mocks.deleteAgentProfile).toHaveBeenCalledTimes(1);

    // Resolve the in-flight mutation so the component settles cleanly.
    mocks.state.deleteResolve?.();
    await waitFor(() => expect(mocks.deleteAgentProfile).toHaveBeenCalledTimes(1));
  });
});
