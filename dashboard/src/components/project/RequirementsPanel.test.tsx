import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RequirementsPanel } from "./RequirementsPanel";

const publicConfig = {
  api_url: "http://localhost:3000",
  ws_url: "ws://localhost:3000",
  preview_host: "localhost",
  setup_complete: true,
  api_key_required: false,
  gateway_mode: true,
};

const requirementsPayload = {
  requirements: [
    {
      req_id: "R1",
      description: "Users can log in with email and password",
      acceptance: ["Login form validates credentials"],
      status: "verified",
      contract_version: 1,
      evidence: [
        {
          kind: "integration_test",
          reference: "tests/test_login.py::test_login",
          passed: true,
          payload: {},
          created_at: "2026-09-01T10:00:00Z",
        },
      ],
    },
    {
      req_id: "R2",
      description: "Users can export data as CSV",
      acceptance: ["Export downloads a CSV file"],
      status: "failed",
      contract_version: 1,
      evidence: [],
    },
  ],
  health: {
    total_requirements: 2,
    verified: 1,
    failed: 1,
    unverified: 0,
    health_percent: 50,
  },
};

function jsonResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => data } as Response;
}

const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input);
  if (url.includes("/api/settings/public")) return jsonResponse(publicConfig);
  if (url.includes("/waive")) return jsonResponse({ req_id: "R1", status: "waived" });
  if (url.includes("/requirements")) return jsonResponse(requirementsPayload);
  throw new Error(`Unexpected fetch: ${url}`);
});

describe("RequirementsPanel", () => {
  beforeEach(() => {
    fetchMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders health bar and requirement rows with status pills", async () => {
    render(<RequirementsPanel projectId="p1" />);

    expect(await screen.findByText("R1")).toBeInTheDocument();
    expect(screen.getByText("R2")).toBeInTheDocument();
    expect(screen.getByText("Users can log in with email and password")).toBeInTheDocument();
    expect(screen.getByText("Users can export data as CSV")).toBeInTheDocument();

    expect(screen.getByText("verified")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();

    expect(screen.getByText("1 / 2 verified")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();

    expect(screen.getByText("Login form validates credentials")).toBeInTheDocument();
  });

  it("shows evidence when a row is expanded", async () => {
    render(<RequirementsPanel projectId="p1" />);

    const row = await screen.findByRole("button", { name: /R1/ });
    fireEvent.click(row);

    expect(await screen.findByText("tests/test_login.py::test_login")).toBeInTheDocument();
    expect(screen.getByText("PASS")).toBeInTheDocument();
    expect(screen.getByText("integration_test")).toBeInTheDocument();
  });

  it("calls the waive endpoint and refreshes when Waive is clicked", async () => {
    render(<RequirementsPanel projectId="p1" />);

    const waiveButtons = await screen.findAllByRole("button", { name: "Waive" });
    expect(waiveButtons).toHaveLength(2);

    fireEvent.click(waiveButtons[0]);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:3000/api/projects/p1/requirements/R1/waive",
        expect.objectContaining({ method: "POST" })
      );
    });

    // After waiving, the panel re-fetches the requirements list.
    await waitFor(() => {
      const requirementFetches = fetchMock.mock.calls.filter(
        ([input]) => String(input).endsWith("/api/projects/p1/requirements")
      );
      expect(requirementFetches.length).toBeGreaterThanOrEqual(2);
    });
  });
});
