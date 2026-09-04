import { describe, expect, it } from "vitest";
import { BUILD_SUBSTAGES, substageStatus, VERIFICATION_SUBSTAGES } from "./pipelineSubstages";

describe("substageStatus", () => {
  it("marks the active verification step", () => {
    expect(
      substageStatus("user_journey", VERIFICATION_SUBSTAGES, {
        activeStep: "user_journey",
      })
    ).toBe("active");
  });

  it("marks earlier verification steps done", () => {
    expect(
      substageStatus("acceptance", VERIFICATION_SUBSTAGES, {
        activeStep: "user_journey",
      })
    ).toBe("done");
  });

  it("marks disabled steps skipped", () => {
    expect(
      substageStatus("adversary", VERIFICATION_SUBSTAGES, {
        activeStep: "acceptance",
        enabled: false,
      })
    ).toBe("skipped");
  });

  it("marks build unit tests active during implementing gate", () => {
    expect(
      substageStatus("unit_testing", BUILD_SUBSTAGES, {
        activeStep: "unit_testing",
      })
    ).toBe("active");
  });
});
