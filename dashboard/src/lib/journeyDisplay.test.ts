import { describe, expect, it } from "vitest";
import type { ProjectDetail } from "@/lib/api";
import { getJourneyDisplay, isPostProductionCycleActive } from "./journeyDisplay";

function baseDetail(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    id: "p1",
    name: "Test",
    description: "",
    state: "PRODUCTION",
    pipeline_running: false,
    artifacts: [],
    created_at: "",
    updated_at: "",
    ...overrides,
  } as ProjectDetail;
}

describe("isPostProductionCycleActive", () => {
  it("is false for production projects with no active cycle", () => {
    expect(isPostProductionCycleActive(baseDetail())).toBe(false);
  });

  it("is true when post_production_cycle_active is set", () => {
    expect(
      isPostProductionCycleActive(
        baseDetail({ post_production_cycle_active: true })
      )
    ).toBe(true);
  });

  it("is true when pipeline is running with self-propelling enabled", () => {
    expect(
      isPostProductionCycleActive(
        baseDetail({
          pipeline_running: true,
          self_propelling: { enabled: true },
        })
      )
    ).toBe(true);
  });
});

describe("getJourneyDisplay", () => {
  it("keeps production on the live step when idle", () => {
    const display = getJourneyDisplay(baseDetail());
    expect(display.state).toBe("PRODUCTION");
    expect(display.postProductionCycle).toBe(false);
  });

  it("maps enrichment to the build phase", () => {
    const display = getJourneyDisplay(
      baseDetail({
        post_production_cycle_active: true,
        pipeline_running: true,
        self_propelling: { enabled: true, rapid_iterations: true },
        pipeline_substage: { gate: "PRODUCTION", step: "enrichment" },
      })
    );
    expect(display.state).toBe("IMPLEMENTING");
    expect(display.postProductionStep).toBe("enrichment");
    expect(display.substateLabel).toContain("Rapid improvement cycle");
  });

  it("maps testing to the verify phase", () => {
    const display = getJourneyDisplay(
      baseDetail({
        post_production_cycle_active: true,
        pipeline_running: true,
        pipeline_substage: { gate: "PRODUCTION", step: "testing" },
      })
    );
    expect(display.state).toBe("SMOKE_TESTING");
    expect(display.postProductionStep).toBe("testing");
  });

  it("maps redeploy to the ship phase", () => {
    const display = getJourneyDisplay(
      baseDetail({
        post_production_cycle_active: true,
        pipeline_running: true,
        pipeline_substage: { gate: "PRODUCTION", step: "redeploy" },
      })
    );
    expect(display.state).toBe("DOCKER_BUILD");
    expect(display.postProductionStep).toBe("redeploy");
  });
});
