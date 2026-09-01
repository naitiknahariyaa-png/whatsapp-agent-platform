import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Alerts from "../pages/Alerts";
import Approvals from "../pages/Approvals";

// Login gate lives in App/Auth; here we render pages directly with a fake token.
const FAKE_TOKEN = "t";

vi.mock("../auth", () => ({
  useAuth: () => ({ token: FAKE_TOKEN, email: "t@t", login: vi.fn(), logout: vi.fn() }),
}));

describe("Approvals page", () => {
  it("renders a row from the API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({
          pending: [{ id: "abc123", action_type: "refund", client_id: 1, amount: 5000,
                      payload: {}, created_by: "u", created_at: "2026-08-31T00:00:00", expires_at: null, risk: "high" }],
        }), { status: 200, headers: { "Content-Type": "application/json" } })
      )
    );
    render(
      <MemoryRouter>
        <Approvals />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByText("refund")).toBeInTheDocument());
  });
});