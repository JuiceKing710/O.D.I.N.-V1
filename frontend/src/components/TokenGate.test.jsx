import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TokenGate } from "./TokenGate.jsx";

const submitToken = vi.fn();

vi.mock("../state/appContext.jsx", () => ({
  useAppState: () => ({ submitToken }),
}));

describe("TokenGate", () => {
  afterEach(() => {
    cleanup();
    submitToken.mockReset();
  });

  it("submits the entered token", async () => {
    submitToken.mockResolvedValue({});
    render(<TokenGate />);

    fireEvent.change(screen.getByLabelText("Remote access token"), {
      target: { value: "my-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(submitToken).toHaveBeenCalledWith("my-secret"));
  });

  it("shows a rejection message on a 401", async () => {
    submitToken.mockRejectedValue(Object.assign(new Error("nope"), { status: 401 }));
    render(<TokenGate />);

    fireEvent.change(screen.getByLabelText("Remote access token"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByText(/was not accepted/i)).toBeInTheDocument();
  });
});
