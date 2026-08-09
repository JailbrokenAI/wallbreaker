import { describe, it, expect, vi, afterEach } from "vitest";
import { useEffect, useState } from "react";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AsyncView, type AsyncStatus } from "../primitives/AsyncView";

afterEach(cleanup);

// A component that mirrors the REL-9 pattern: catch -> error status (NOT loading).
function Harness({ fetcher }: { fetcher: () => Promise<string> }) {
  const [status, setStatus] = useState<AsyncStatus>("loading");
  const [data, setData] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let active = true;
    setStatus("loading");
    fetcher()
      .then((v) => { if (active) { setData(v); setStatus("data"); } })
      .catch((e) => { if (active) { setError((e as Error).message); setStatus("error"); } });
    return () => { active = false; };
  }, [fetcher, tick]);

  return (
    <AsyncView<string> status={status} data={data} error={error} onRetry={() => setTick((n) => n + 1)}>
      {(value) => <div data-testid="data">{value}</div>}
    </AsyncView>
  );
}

describe("AsyncView (REL-9)", () => {
  it("renders the error state with a Retry button on a rejected fetch (not a spinner)", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error("boom"));
    render(<Harness fetcher={fetcher} />);

    // The error card appears; it must NOT be stuck showing a loading spinner.
    await screen.findByRole("alert");
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });

  it("Retry re-runs the fetch and shows data on success", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce("ok-now");
    render(<Harness fetcher={fetcher} />);

    await screen.findByRole("button", { name: "Retry" });
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByTestId("data")).toHaveTextContent("ok-now"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
