import { describe, expect, it } from "vitest";

import { signedPct } from "./sampleDay";

describe("sample day", () => {
  it("shows how far each total is from its target, as the engine sent it", () => {
    expect(signedPct(6.7)).toBe("+6.7%");
    expect(signedPct(-3)).toBe("−3%");
    expect(signedPct(0)).toBe("on target");
  });
});
