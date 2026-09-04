import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContractPanel } from "./ContractPanel";

const publicConfig = {
  api_url: "http://localhost:3000",
  ws_url: "ws://localhost:3000",
  preview_host: "localhost",
  setup_complete: true,
  api_key_required: false,
  gateway_mode: true,
};

const contractPayload = {
  contract: {
    goal: "Build an invoice manager for freelancers",
    users: ["freelancers"],
    requirements: [
      {
        id: "R1",
        description: "Users can create invoices",
        acceptance: ["Invoice form saves to database"],
        priority: "must",
      },
      {
        id: "R2",
        description: "Users can download invoices as PDF",
        acceptance: ["PDF matches invoice data"],
        priority: "should",
      },
    ],
    non_goals: ["No multi-currency support"],
    constraints: ["Must run in a single Docker container"],
    quality_targets: [],
    security_requirements: [],
    version: 3,
    source: "architect",
  },
  version: 3,
  source: "architect",
  history: [{ version: 3, source: "architect", created_at: "2026-09-01T10:00:00Z" }],
};

function jsonResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => data } as Response;
}

const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input);
  if (url.includes("/api/settings/public")) return jsonResponse(publicConfig);
  if (url.includes("/contract")) return jsonResponse(contractPayload);
  throw new Error(`Unexpected fetch: ${url}`);
});

describe("ContractPanel", () => {
  beforeEach(() => {
    fetchMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders the contract in view mode", async () => {
    render(<ContractPanel projectId="p1" />);

    expect(
      await screen.findByText("Build an invoice manager for freelancers")
    ).toBeInTheDocument();

    expect(screen.getByText("R1")).toBeInTheDocument();
    expect(screen.getByText("Users can create invoices")).toBeInTheDocument();
    expect(screen.getByText("Invoice form saves to database")).toBeInTheDocument();
    expect(screen.getByText("R2")).toBeInTheDocument();
    expect(screen.getByText("Users can download invoices as PDF")).toBeInTheDocument();

    expect(screen.getByText("No multi-currency support")).toBeInTheDocument();
    expect(screen.getByText("Must run in a single Docker container")).toBeInTheDocument();

    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.getByText("architect")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Edit contract" })).toBeInTheDocument();
  });

  it("shows an empty state when no contract exists", async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/settings/public")) return jsonResponse(publicConfig);
      if (url.includes("/contract")) {
        return jsonResponse({ contract: null, version: null, source: null, history: [] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<ContractPanel projectId="p1" />);

    expect(
      await screen.findByText(/No contract yet/)
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit contract" })).not.toBeInTheDocument();
  });
});
