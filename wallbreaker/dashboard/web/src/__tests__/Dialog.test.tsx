import { describe, it, expect, afterEach } from "vitest";
import { useState } from "react";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Dialog } from "../primitives/Dialog";

afterEach(cleanup);

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>open dialog</button>
      <Dialog open={open} title="Test dialog" onClose={() => setOpen(false)}>
        <input aria-label="first" />
        <button type="button">last</button>
      </Dialog>
    </div>
  );
}

describe("Dialog (accessibility)", () => {
  it("exposes role=dialog, aria-modal and aria-labelledby", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "open dialog" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const labelledby = dialog.getAttribute("aria-labelledby");
    expect(labelledby).toBeTruthy();
    expect(document.getElementById(labelledby!)).toHaveTextContent("Test dialog");
  });

  it("traps focus: Tab from the last element cycles back to the first", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "open dialog" }));
    const first = screen.getByLabelText("first");
    const last = screen.getByRole("button", { name: "last" });

    last.focus();
    expect(last).toHaveFocus();
    await userEvent.tab();
    expect(first).toHaveFocus();

    // Shift+Tab from the first wraps to the last.
    await userEvent.tab({ shift: true });
    expect(last).toHaveFocus();
  });

  it("closes on Escape and restores focus to the trigger", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "open dialog" });
    await userEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
